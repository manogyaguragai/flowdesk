"""
launcher.py — PyWebView entry point for FlowDesk desktop app.

Starts FastAPI + uvicorn on localhost:8000 in a background thread,
then opens a native PyWebView window pointing to the local server.

Exposes a Python API (js_api) to the frontend for settings management:
  - get_settings()  → returns current CSV path config
  - set_csv_path()  → opens native folder picker
  - get_csv_path()  → returns current CSV path string
"""

import os
import sys
import json
import time
import threading

# ── Determine base path (works for both dev and PyInstaller frozen) ──
if getattr(sys, 'frozen', False):
    BASE_PATH = sys._MEIPASS
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# Set working directory so FastAPI can find frontend/, models, etc.
os.chdir(BASE_PATH)

# Set environment variable for detector.py to find model files
os.environ["FLOWDESK_BASE"] = BASE_PATH

# ── Suppress stdout/stderr in frozen mode (no console window) ──
if getattr(sys, 'frozen', False):
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

# ── Settings management ─────────────────────────────────────────

# On Windows: %APPDATA%/FlowDesk/
# On Linux/macOS (dev): ~/.config/FlowDesk/
if sys.platform == "win32":
    _appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    SETTINGS_DIR = os.path.join(_appdata, "FlowDesk")
else:
    SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".config", "FlowDesk")

os.makedirs(SETTINGS_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")


def load_settings() -> dict:
    """Load settings from disk. Returns defaults if file doesn't exist."""
    default_csv_dir = os.path.join(SETTINGS_DIR, "data")
    defaults = {"csv_path": default_csv_dir}

    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
            # Ensure csv_path key exists
            if "csv_path" not in settings:
                settings["csv_path"] = default_csv_dir
            return settings
        except (json.JSONDecodeError, IOError):
            pass

    return defaults


def save_settings(settings: dict):
    """Persist settings dict to disk as JSON."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except IOError:
        pass


# ── PyWebView JavaScript API ────────────────────────────────────

class FlowDeskAPI:
    """Exposed to the frontend via window.pywebview.api.*"""

    def get_settings(self):
        """Return current settings dict."""
        return load_settings()

    def set_csv_path(self):
        """Open a native folder picker. Returns {success, path}."""
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.FOLDER_DIALOG
        )

        if result and len(result) > 0:
            chosen = result[0]
            settings = load_settings()
            settings["csv_path"] = chosen
            save_settings(settings)

            # Update storage module's CSV_PATH at runtime
            import storage
            new_csv_path = os.path.join(chosen, "counts.csv")
            storage.set_csv_path(new_csv_path)

            return {"success": True, "path": chosen}

        return {"success": False}

    def get_csv_path(self):
        """Return current CSV directory path string."""
        settings = load_settings()
        return settings["csv_path"]


# ── Server startup ──────────────────────────────────────────────

def start_server():
    """Run uvicorn in the current thread (called from a daemon thread)."""
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        log_level="error",
    )


def wait_for_server(max_attempts=15, delay=1.0):
    """Poll the server until it responds or we give up."""
    import urllib.request
    for i in range(max_attempts):
        try:
            req = urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=2)
            req.close()
            return True
        except Exception:
            time.sleep(delay)
    return False


# ── Main ────────────────────────────────────────────────────────

def main():
    # 1. Load settings and configure CSV path
    settings = load_settings()
    csv_dir = settings["csv_path"]
    os.makedirs(csv_dir, exist_ok=True)

    # Set CSV_PATH in storage module before FastAPI app is imported
    import storage
    storage.set_csv_path(os.path.join(csv_dir, "counts.csv"))

    # 2. Start uvicorn in a daemon thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 3. Wait for server to become ready
    if not wait_for_server():
        # Server didn't start — show error and exit
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "FlowDesk",
                "Failed to start the FlowDesk server.\n\n"
                "Please check that port 8000 is not in use\n"
                "and try again."
            )
        except Exception:
            pass
        sys.exit(1)

    # 4. Create PyWebView window
    try:
        import webview
        api = FlowDeskAPI()
        webview.create_window(
            "FlowDesk",
            "http://localhost:8000",
            width=1100,
            height=750,
            min_size=(800, 600),
            resizable=True,
            js_api=api,
        )
        webview.start(debug=False)
    except Exception as e:
        error_msg = str(e).lower()
        if "webview2" in error_msg or "edge" in error_msg or "runtime" in error_msg:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror(
                    "FlowDesk",
                    "WebView2 runtime not found.\n\n"
                    "Please download and install it from:\n"
                    "https://developer.microsoft.com/en-us/microsoft-edge/webview2/\n\n"
                    "Then restart FlowDesk."
                )
            except Exception:
                pass
            sys.exit(1)
        else:
            raise

    # 5. When window closes, exit cleanly
    os._exit(0)


if __name__ == "__main__":
    main()
