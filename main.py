"""
main.py — FastAPI app + all routes for FlowDesk.

Configuration constants are defined at the top.
"""

import os
import sys
import io
import csv
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

from detector import PeopleDetector, AVAILABLE_MODELS
from nepali_utils import today_bs, today_ad, today_bs_parts
import storage

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────
CAMERA_INDEX = 0
COUNTING_LINE_POSITION = 0.5   # fraction of frame dimension

# Determine base path (for frozen PyInstaller or dev)
if getattr(sys, 'frozen', False):
    BASE_PATH = sys._MEIPASS
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# In dev mode (non-frozen), apply default CSV path if not already set by launcher
if not getattr(sys, 'frozen', False) and storage.CSV_PATH == "data/counts.csv":
    storage.set_csv_path(os.path.join(BASE_PATH, "data", "counts.csv"))

# ──────────────────────────────────────────────
# GLOBALS
# ──────────────────────────────────────────────
detector = PeopleDetector(
    camera_index=CAMERA_INDEX,
    counting_line_position=COUNTING_LINE_POSITION,
)
scheduler = BackgroundScheduler()
_last_saved_bs_date: str = ""


# ──────────────────────────────────────────────
# MIDNIGHT RESET
# ──────────────────────────────────────────────
def _midnight_reset():
    """Save current counts to CSV, then reset counters."""
    global _last_saved_bs_date
    counts = detector.get_counts()
    # Save using the date that was active (before midnight)
    storage.save_today(counts["count_in"], counts["count_out"])
    detector.reset_counts()
    _last_saved_bs_date = today_bs()


def _check_date_change():
    """
    If the BS date has changed since the last save, trigger save + reset.
    Handles server restarts across midnight.
    """
    global _last_saved_bs_date
    current_bs = today_bs()
    if _last_saved_bs_date and _last_saved_bs_date != current_bs:
        # Date has changed — save yesterday's counts and reset
        counts = detector.get_counts()
        storage.save_today(counts["count_in"], counts["count_out"])
        detector.reset_counts()
    _last_saved_bs_date = current_bs


# ──────────────────────────────────────────────
# LIFESPAN
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start detector + scheduler on startup, clean up on shutdown."""
    global _last_saved_bs_date
    _last_saved_bs_date = today_bs()

    # Restore today's counts from CSV if the server restarts mid-day
    saved = storage.load_today()
    if saved:
        detector._lock.acquire()
        detector._count_in = saved["count_in"]
        detector._count_out = saved["count_out"]
        detector._lock.release()

    # Start detector
    detector.start()

    # Schedule midnight reset
    scheduler.add_job(_midnight_reset, "cron", hour=0, minute=0, second=0)
    scheduler.start()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    # Save current counts before shutting down
    counts = detector.get_counts()
    storage.save_today(counts["count_in"], counts["count_out"])
    detector.stop()


# ──────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────
app = FastAPI(title="FlowDesk", lifespan=lifespan)

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────

@app.get("/video_feed")
async def video_feed():
    """MJPEG stream: multipart/x-mixed-replace with JPEG frames."""

    def generate():
        import time
        while True:
            frame = detector.get_frame()
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            else:
                # No frame yet — send a tiny delay
                time.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/status")
async def api_status():
    """Return current counts, date info, and line configuration."""
    # Check for date change (handles server restarts across midnight)
    _check_date_change()

    counts = detector.get_counts()
    bs_parts = today_bs_parts()

    # Throttle CSV saves — write at most every 30 seconds, not every poll
    import time as _time
    now = _time.time()
    if not hasattr(api_status, "_last_csv_save"):
        api_status._last_csv_save = 0
    if now - api_status._last_csv_save > 30:
        storage.save_today(counts["count_in"], counts["count_out"])
        api_status._last_csv_save = now

    return JSONResponse({
        "bs_date": today_bs(),
        "ad_date": today_ad(),
        "bs_month_name": bs_parts["month_name"],
        "bs_day": bs_parts["day"],
        "bs_year": bs_parts["year"],
        "count_in": counts["count_in"],
        "count_out": counts["count_out"],
        "net": counts["count_in"] - counts["count_out"],
        "direction": detector.get_direction(),
        "camera_index": detector.get_camera_index(),
        "orientation": detector.get_orientation(),
        "line_position": detector.get_line_position(),
        "model_name": detector.get_model_name(),
        "model_loading": detector.is_model_loading(),
        "hysteresis": detector.get_hysteresis(),
    })


@app.get("/api/export/csv")
async def api_export_csv(
    from_bs: str = Query(default=None, description="Start BS date (YYYY-MM-DD)"),
    to_bs: str = Query(default=None, description="End BS date (YYYY-MM-DD)"),
):
    """Export counts CSV filtered by BS date range."""
    rows = storage.load_range(from_bs, to_bs)

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["bs_date", "ad_date", "count_in", "count_out"])
    writer.writeheader()
    writer.writerows(rows)
    csv_content = output.getvalue()

    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=flowdesk_export.csv"
        },
    )


@app.post("/api/reset")
async def api_reset():
    """Reset today's in-memory counters to 0 (does NOT delete CSV data)."""
    detector.reset_counts()
    return JSONResponse({
        "status": "reset",
        "bs_date": today_bs(),
        "ad_date": today_ad(),
    })


@app.post("/api/swap-direction")
async def api_swap_direction():
    """Swap IN/OUT direction assignment."""
    detector.swap_direction()
    return JSONResponse({
        "status": "swapped",
        "direction": detector.get_direction(),
    })


@app.get("/api/camera")
async def api_get_camera():
    """Return current camera index."""
    return JSONResponse({
        "camera_index": detector.get_camera_index(),
    })


@app.post("/api/camera")
async def api_set_camera(camera_index: int = Query(..., description="Camera device index")):
    """Switch to a different camera source."""
    detector.change_camera(camera_index)
    return JSONResponse({
        "status": "switching",
        "camera_index": camera_index,
    })


@app.post("/api/line/orientation")
async def api_set_orientation(orientation: str = Query(..., description="'vertical' or 'horizontal'")):
    """Set counting line orientation."""
    if orientation not in ("vertical", "horizontal"):
        return JSONResponse({"error": "Must be 'vertical' or 'horizontal'"}, status_code=400)
    detector.set_orientation(orientation)
    return JSONResponse({
        "status": "ok",
        "orientation": detector.get_orientation(),
    })


@app.post("/api/line/position")
async def api_set_line_position(position: float = Query(..., ge=0.05, le=0.95, description="Line position 0.05–0.95")):
    """Set counting line position (fraction of frame dimension)."""
    detector.set_line_position(position)
    return JSONResponse({
        "status": "ok",
        "line_position": detector.get_line_position(),
    })


@app.get("/api/hysteresis")
async def api_get_hysteresis():
    """Return current hysteresis zone configuration."""
    return JSONResponse(detector.get_hysteresis())


@app.post("/api/hysteresis")
async def api_set_hysteresis(
    enabled: bool = Query(default=None, description="Enable/disable hysteresis zone"),
    margin: int = Query(default=None, ge=0, le=100, description="Hysteresis margin in pixels"),
):
    """Configure hysteresis zone (toggle on/off, set margin)."""
    detector.set_hysteresis(enabled=enabled, margin=margin)
    return JSONResponse(detector.get_hysteresis())


@app.get("/api/models")
async def api_list_models():
    """List available YOLO models."""
    return JSONResponse({
        "current": detector.get_model_name(),
        "models": detector.list_models(),
    })


@app.post("/api/models")
async def api_set_model(model_name: str = Query(..., description="Model key, e.g. 'yolo11n'")):
    """Switch to a different YOLO model."""
    if model_name not in AVAILABLE_MODELS:
        return JSONResponse(
            {"error": f"Unknown model. Available: {list(AVAILABLE_MODELS.keys())}"},
            status_code=400,
        )
    detector.change_model(model_name)
    return JSONResponse({
        "status": "switching",
        "model_name": model_name,
    })


@app.post("/api/shutdown")
async def api_shutdown():
    """Gracefully shut down the application."""
    # Save counts before shutting down
    counts = detector.get_counts()
    storage.save_today(counts["count_in"], counts["count_out"])
    detector.stop()
    scheduler.shutdown(wait=False)

    # Send SIGINT to the current process to stop uvicorn
    import threading
    def _kill():
        import time
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)
    threading.Thread(target=_kill, daemon=True).start()

    return JSONResponse({
        "status": "shutting_down",
    })


# ──────────────────────────────────────────────
# SERVE ASSETS + FRONTEND (frontend catch-all must be last)
# ──────────────────────────────────────────────
_assets_dir = os.path.join(BASE_PATH, "assets")
app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

_frontend_dir = os.path.join(BASE_PATH, "frontend")
app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
