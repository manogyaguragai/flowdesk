"""
detector.py — YOLO detection + line-crossing tracker.

Runs in a background thread. Uses YOLO with built-in object tracking
(model.track()) for stable person IDs across frames.

Supports both vertical and horizontal counting lines, configurable at runtime.
Supports runtime model switching between YOLO variants.

Crossing detection uses a side-tracking state machine with configurable
hysteresis zone to prevent miscounts from centroid jitter near the line.
"""

import os
import time
import threading
import cv2
import numpy as np
from ultralytics import YOLO

# Base path for model files — set by launcher.py, falls back to current dir
_BASE = os.environ.get("FLOWDESK_BASE", ".")
_MODEL_BASE = os.path.join(_BASE, "models")

# Available YOLO models — user can switch between these at runtime.
# Each auto-downloads on first use (~6MB to ~130MB depending on size).
AVAILABLE_MODELS = {
    "yolo11n": os.path.join(_MODEL_BASE, "yolo11n.pt"),
    "yolo11s": os.path.join(_MODEL_BASE, "yolo11s.pt"),
    "yolo11m": os.path.join(_MODEL_BASE, "yolo11m.pt"),
    "yolo11l": os.path.join(_MODEL_BASE, "yolo11l.pt"),
    "yolo11x": os.path.join(_MODEL_BASE, "yolo11x.pt"),
    "yolo26n": os.path.join(_MODEL_BASE, "yolo26n.pt"),
    "yolo26s": os.path.join(_MODEL_BASE, "yolo26s.pt"),
    "yolo26m": os.path.join(_MODEL_BASE, "yolo26m.pt"),
    "yolo26l": os.path.join(_MODEL_BASE, "yolo26l.pt"),
    "yolo26x": os.path.join(_MODEL_BASE, "yolo26x.pt"),
}

DEFAULT_MODEL = "yolo26n"


class PeopleDetector:
    """
    Opens a webcam feed, runs YOLO person detection + tracking,
    and counts people crossing a configurable counting line.

    Crossing detection uses a side-tracking state machine:
    - Each tracked person is classified as being on the "before" or "after"
      side of the counting line.
    - "before" = left of vertical line / above horizontal line
    - "after"  = right of vertical line / below horizontal line
    - A crossing is counted when a person transitions from one side to the other.
    - An optional hysteresis zone around the line prevents jitter-induced miscounts.
    """

    def __init__(self, camera_index: int = 0, counting_line_position: float = 0.5,
                 model_name: str = DEFAULT_MODEL):
        """
        Args:
            camera_index: Webcam device index (default 0).
            counting_line_position: Fraction of frame dimension for the counting line
                                    (0.0–1.0, default 0.5 = center).
            model_name: YOLO model key from AVAILABLE_MODELS (default "yolo11n").
        """
        self.camera_index = camera_index
        self.counting_line_position = counting_line_position

        # Line orientation: "vertical" or "horizontal"
        self._orientation = "vertical"

        # Direction: False = default (left→right or top→bottom = IN)
        #            True  = swapped (left→right or top→bottom = OUT)
        self._direction_swapped = False

        # Counters
        self._count_in = 0
        self._count_out = 0
        self._lock = threading.Lock()

        # Tracking state — side-tracking state machine
        # Maps track_id -> "before" | "after" (which side of the line the person is on)
        self._track_side: dict[int, str] = {}

        # Hysteresis zone — prevents jitter-induced miscounts near the line
        self._hysteresis_enabled = True
        self._hysteresis_margin = 30  # pixels on each side of the line

        # Frame buffer
        self._frame: bytes | None = None
        self._frame_lock = threading.Lock()

        # Thread control
        self._running = False
        self._thread: threading.Thread | None = None

        # Camera switch request
        self._camera_switch_requested = False
        self._new_camera_index: int | None = None

        # Model switching
        self._current_model_name = model_name
        self._model_switch_requested = False
        self._new_model_name: str | None = None
        self._model_loading = False  # True while a model is being downloaded/loaded

        # Load YOLO model (auto-downloads on first run)
        model_file = AVAILABLE_MODELS.get(model_name, AVAILABLE_MODELS[DEFAULT_MODEL])
        self._model = YOLO(model_file)

    # ── Public API ───────────────────────────────

    def start(self):
        """Start the detection thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the detection thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def get_counts(self) -> dict:
        """Return current in/out counts (thread-safe)."""
        with self._lock:
            return {
                "count_in": self._count_in,
                "count_out": self._count_out,
            }

    def reset_counts(self):
        """Reset in-memory counters to 0 (thread-safe)."""
        with self._lock:
            self._count_in = 0
            self._count_out = 0
            self._track_side.clear()

    def get_frame(self) -> bytes | None:
        """Return the latest annotated frame as JPEG bytes, or None."""
        with self._frame_lock:
            return self._frame

    def swap_direction(self):
        """Swap IN/OUT direction assignment (thread-safe)."""
        with self._lock:
            self._direction_swapped = not self._direction_swapped
            # Swap existing counts to match new direction
            self._count_in, self._count_out = self._count_out, self._count_in

    def get_direction(self) -> str:
        """Return current direction mode."""
        with self._lock:
            if self._orientation == "vertical":
                return "right_in" if self._direction_swapped else "left_in"
            else:
                return "bottom_in" if self._direction_swapped else "top_in"

    def set_orientation(self, orientation: str):
        """Set line orientation ('vertical' or 'horizontal'). Clears tracking state."""
        if orientation not in ("vertical", "horizontal"):
            return
        with self._lock:
            self._orientation = orientation
            self._track_side.clear()

    def get_orientation(self) -> str:
        """Return current line orientation."""
        with self._lock:
            return self._orientation

    def set_line_position(self, position: float):
        """Set line position (0.0–1.0). Clears tracking state."""
        position = max(0.0, min(1.0, position))
        with self._lock:
            self.counting_line_position = position
            self._track_side.clear()

    def get_line_position(self) -> float:
        """Return current line position."""
        return self.counting_line_position

    def change_camera(self, camera_index: int):
        """Request a camera source change (takes effect on next loop iteration)."""
        with self._lock:
            self._new_camera_index = camera_index
            self._camera_switch_requested = True

    def get_camera_index(self) -> int:
        """Return the current camera index."""
        return self.camera_index

    def change_model(self, model_name: str) -> bool:
        """Request a model switch. Returns False if model_name is invalid."""
        if model_name not in AVAILABLE_MODELS:
            return False
        with self._lock:
            self._new_model_name = model_name
            self._model_switch_requested = True
        return True

    def get_model_name(self) -> str:
        """Return the current model name."""
        with self._lock:
            return self._current_model_name

    def is_model_loading(self) -> bool:
        """Return True if a model is currently being loaded/downloaded."""
        with self._lock:
            return self._model_loading

    def set_hysteresis(self, enabled: bool | None = None, margin: int | None = None):
        """Configure hysteresis zone. Clears tracking state on change."""
        with self._lock:
            changed = False
            if enabled is not None and enabled != self._hysteresis_enabled:
                self._hysteresis_enabled = enabled
                changed = True
            if margin is not None and margin != self._hysteresis_margin:
                self._hysteresis_margin = max(0, min(100, margin))
                changed = True
            if changed:
                self._track_side.clear()

    def get_hysteresis(self) -> dict:
        """Return current hysteresis configuration."""
        with self._lock:
            return {
                "enabled": self._hysteresis_enabled,
                "margin": self._hysteresis_margin,
            }

    @staticmethod
    def list_models() -> list[dict]:
        """Return list of available models with metadata."""
        size_hints = {
            "yolo11n": {"label": "YOLO11 Nano", "size": "~6 MB", "speed": "Fastest"},
            "yolo11s": {"label": "YOLO11 Small", "size": "~22 MB", "speed": "Fast"},
            "yolo11m": {"label": "YOLO11 Medium", "size": "~51 MB", "speed": "Balanced"},
            "yolo11l": {"label": "YOLO11 Large", "size": "~87 MB", "speed": "Accurate"},
            "yolo11x": {"label": "YOLO11 XLarge", "size": "~130 MB", "speed": "Most Accurate"},
        }
        models = []
        for key in AVAILABLE_MODELS:
            info = size_hints.get(key, {"label": key, "size": "?", "speed": "?"})
            models.append({
                "key": key,
                "label": info["label"],
                "size": info["size"],
                "speed": info["speed"],
            })
        return models

    # ── Internal ─────────────────────────────────

    def _run(self):
        """Main detection loop — runs in a background thread."""
        cap = None

        while self._running:
            # Check for camera switch request
            with self._lock:
                if self._camera_switch_requested:
                    self._camera_switch_requested = False
                    self.camera_index = self._new_camera_index
                    self._new_camera_index = None
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._track_side.clear()

            # Check for model switch request
            switch_model_name = None
            with self._lock:
                if self._model_switch_requested:
                    self._model_switch_requested = False
                    switch_model_name = self._new_model_name
                    self._new_model_name = None

            # Load new model in a background thread so webcam keeps streaming
            if switch_model_name:
                with self._lock:
                    self._model_loading = True
                print(f"[FlowDesk] Loading model {switch_model_name}...")

                def _load_model(name):
                    model_file = AVAILABLE_MODELS[name]
                    new_model = YOLO(model_file)
                    with self._lock:
                        self._model = new_model
                        self._current_model_name = name
                        self._track_side.clear()
                        self._model_loading = False
                    print(f"[FlowDesk] Model switched to {name}")

                threading.Thread(target=_load_model, args=(switch_model_name,), daemon=True).start()

            # Open / re-open webcam
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                cap = cv2.VideoCapture(self.camera_index)
                if not cap.isOpened():
                    print(f"[FlowDesk] Cannot open camera {self.camera_index}, retrying in 3s...")
                    time.sleep(3)
                    continue
                # Reduce frame buffering latency (read latest frame, not queued)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            ret, frame = cap.read()
            if not ret:
                print("[FlowDesk] Frame read failed, retrying in 3s...")
                cap.release()
                cap = None
                time.sleep(3)
                continue

            # If model is loading, just draw the counting line (no YOLO)
            with self._lock:
                loading = self._model_loading

            if loading:
                annotated = self._draw_line_only(frame)
            else:
                annotated = self._process_frame(frame)

            # Encode to JPEG — high quality
            _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
            with self._frame_lock:
                self._frame = jpeg.tobytes()

        # Cleanup
        if cap is not None:
            cap.release()

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Run YOLO tracking on a frame, detect line crossings, draw annotations."""
        h, w = frame.shape[:2]

        with self._lock:
            orientation = self._orientation
            swapped = self._direction_swapped
            line_pos = self.counting_line_position
            hyst_enabled = self._hysteresis_enabled
            hyst_margin = self._hysteresis_margin

        # Run YOLO tracking — class 0 = "person" in COCO
        results = self._model.track(frame, classes=[0], persist=True, verbose=False)

        if orientation == "vertical":
            line_px = int(w * line_pos)
            self._draw_hysteresis_zone(frame, orientation, line_px, h, w, hyst_enabled, hyst_margin)
            self._draw_vertical_line(frame, line_px, h, w, swapped)
            self._process_crossings_vertical(frame, results, line_px, swapped, hyst_enabled, hyst_margin)
        else:
            line_px = int(h * line_pos)
            self._draw_hysteresis_zone(frame, orientation, line_px, h, w, hyst_enabled, hyst_margin)
            self._draw_horizontal_line(frame, line_px, h, w, swapped)
            self._process_crossings_horizontal(frame, results, line_px, swapped, hyst_enabled, hyst_margin)

        return frame

    def _draw_line_only(self, frame: np.ndarray) -> np.ndarray:
        """Draw just the counting line on a frame (no YOLO). Used while model is loading."""
        h, w = frame.shape[:2]
        with self._lock:
            orientation = self._orientation
            swapped = self._direction_swapped
            line_pos = self.counting_line_position
            hyst_enabled = self._hysteresis_enabled
            hyst_margin = self._hysteresis_margin

        if orientation == "vertical":
            line_px = int(w * line_pos)
            self._draw_hysteresis_zone(frame, orientation, line_px, h, w, hyst_enabled, hyst_margin)
            self._draw_vertical_line(frame, line_px, h, w, swapped)
        else:
            line_px = int(h * line_pos)
            self._draw_hysteresis_zone(frame, orientation, line_px, h, w, hyst_enabled, hyst_margin)
            self._draw_horizontal_line(frame, line_px, h, w, swapped)

        # Add "Loading model..." text
        cv2.putText(frame, "Loading model...", (10, 30),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)

        return frame

    def _draw_hysteresis_zone(self, frame, orientation, line_px, h, w, enabled, margin):
        """Draw a semi-transparent band around the counting line to visualize the hysteresis zone."""
        if not enabled or margin <= 0:
            return

        # Create overlay for semi-transparent drawing
        overlay = frame.copy()

        if orientation == "vertical":
            x1 = max(0, line_px - margin)
            x2 = min(w, line_px + margin)
            cv2.rectangle(overlay, (x1, 0), (x2, h), (0, 200, 255), -1)
        else:
            y1 = max(0, line_px - margin)
            y2 = min(h, line_px + margin)
            cv2.rectangle(overlay, (0, y1), (w, y2), (0, 200, 255), -1)

        # Blend with ~20% opacity
        cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)

    def _draw_vertical_line(self, frame, line_x, h, w, swapped):
        """Draw a vertical counting line with direction labels."""
        cv2.line(frame, (line_x, 0), (line_x, h), (0, 255, 255), 2)

        # Labels show what happens when crossing in each direction
        # Default (not swapped): crossing right → = IN, crossing left ← = OUT
        right_action = "OUT" if swapped else "IN"
        left_action = "IN" if swapped else "OUT"
        right_color = (0, 0, 200) if swapped else (0, 200, 0)
        left_color = (0, 200, 0) if swapped else (0, 0, 200)

        cv2.putText(frame, f"{right_action} -->", (line_x + 10, h // 2),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, right_color, 2)
        cv2.putText(frame, f"<-- {left_action}", (max(line_x - 120, 5), h // 2),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, left_color, 2)

    def _draw_horizontal_line(self, frame, line_y, h, w, swapped):
        """Draw a horizontal counting line with direction labels."""
        cv2.line(frame, (0, line_y), (w, line_y), (0, 255, 255), 2)

        # Default (not swapped): crossing down ↓ = IN, crossing up ↑ = OUT
        down_action = "OUT" if swapped else "IN"
        up_action = "IN" if swapped else "OUT"
        down_color = (0, 0, 200) if swapped else (0, 200, 0)
        up_color = (0, 200, 0) if swapped else (0, 0, 200)

        cv2.putText(frame, f"^ {up_action}", (w // 2 - 30, max(line_y - 15, 20)),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, up_color, 2)
        cv2.putText(frame, f"v {down_action}", (w // 2 - 30, line_y + 30),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, down_color, 2)

    def _process_crossings_vertical(self, frame, results, line_x, swapped,
                                     hyst_enabled, hyst_margin):
        """Process person crossings for a vertical line using side-tracking state machine."""
        if not results or len(results) == 0:
            return
        result = results[0]
        if result.boxes is None or result.boxes.id is None:
            return

        boxes = result.boxes.xyxy.cpu().numpy()
        track_ids = result.boxes.id.int().cpu().tolist()
        active_ids = set()

        margin = hyst_margin if hyst_enabled else 0

        for box, track_id in zip(boxes, track_ids):
            x1, y1, x2, y2 = box.astype(int)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            active_ids.add(track_id)

            # Draw bounding box and track ID
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"ID:{track_id}", (x1, y1 - 10),
                         cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.circle(frame, (cx, cy), 4, (255, 0, 0), -1)

            # Determine which side of the line the centroid is on
            if cx < line_x - margin:
                current_side = "before"   # left of line (+ margin)
            elif cx > line_x + margin:
                current_side = "after"    # right of line (+ margin)
            else:
                current_side = None       # inside hysteresis zone — hold state

            prev_side = self._track_side.get(track_id)

            # Count crossing only when side definitively changes
            if current_side is not None and prev_side is not None and current_side != prev_side:
                if prev_side == "before" and current_side == "after":
                    # Crossed left → right
                    with self._lock:
                        if swapped:
                            self._count_out += 1
                        else:
                            self._count_in += 1
                elif prev_side == "after" and current_side == "before":
                    # Crossed right → left
                    with self._lock:
                        if swapped:
                            self._count_in += 1
                        else:
                            self._count_out += 1

            # Update side tracking (only when outside hysteresis zone)
            if current_side is not None:
                self._track_side[track_id] = current_side

        # Clean up stale tracks (people who left the frame)
        stale = [tid for tid in self._track_side if tid not in active_ids]
        for tid in stale:
            del self._track_side[tid]

    def _process_crossings_horizontal(self, frame, results, line_y, swapped,
                                       hyst_enabled, hyst_margin):
        """Process person crossings for a horizontal line using side-tracking state machine."""
        if not results or len(results) == 0:
            return
        result = results[0]
        if result.boxes is None or result.boxes.id is None:
            return

        boxes = result.boxes.xyxy.cpu().numpy()
        track_ids = result.boxes.id.int().cpu().tolist()
        active_ids = set()

        margin = hyst_margin if hyst_enabled else 0

        for box, track_id in zip(boxes, track_ids):
            x1, y1, x2, y2 = box.astype(int)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            active_ids.add(track_id)

            # Draw bounding box and track ID
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"ID:{track_id}", (x1, y1 - 10),
                         cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.circle(frame, (cx, cy), 4, (255, 0, 0), -1)

            # Determine which side of the line the centroid is on
            if cy < line_y - margin:
                current_side = "before"   # above line (+ margin)
            elif cy > line_y + margin:
                current_side = "after"    # below line (+ margin)
            else:
                current_side = None       # inside hysteresis zone — hold state

            prev_side = self._track_side.get(track_id)

            # Count crossing only when side definitively changes
            if current_side is not None and prev_side is not None and current_side != prev_side:
                if prev_side == "before" and current_side == "after":
                    # Crossed top → bottom
                    with self._lock:
                        if swapped:
                            self._count_out += 1
                        else:
                            self._count_in += 1
                elif prev_side == "after" and current_side == "before":
                    # Crossed bottom → top
                    with self._lock:
                        if swapped:
                            self._count_in += 1
                        else:
                            self._count_out += 1

            # Update side tracking (only when outside hysteresis zone)
            if current_side is not None:
                self._track_side[track_id] = current_side

        # Clean up stale tracks (people who left the frame)
        stale = [tid for tid in self._track_side if tid not in active_ids]
        for tid in stale:
            del self._track_side[tid]
