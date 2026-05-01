/**
 * app.js — FlowDesk frontend logic.
 *
 * Polls /api/status every 2 seconds, handles CSV export, counter reset,
 * direction swap, orientation toggle, line position, camera switching,
 * model switching with loading overlay, and shutdown.
 * Pure vanilla JS — no external libraries.
 */

// ── DOM References ──────────────────────────────
const elBsDate          = document.getElementById("bs-date");
const elAdDate          = document.getElementById("ad-date");
const elCountIn         = document.getElementById("count-in");
const elCountOut        = document.getElementById("count-out");
const elCountNet        = document.getElementById("count-net");
const elFromDate        = document.getElementById("from-date");
const elToDate          = document.getElementById("to-date");
const btnExport         = document.getElementById("btn-export");
const btnReset          = document.getElementById("btn-reset");
const elDirectionLabel  = document.getElementById("direction-label");
const btnSwapDirection  = document.getElementById("btn-swap-direction");
const btnOrientation    = document.getElementById("btn-orientation");
const elCameraInput     = document.getElementById("camera-input");
const btnSwitchCamera   = document.getElementById("btn-switch-camera");
const elLineSlider      = document.getElementById("line-slider");
const elLinePosValue    = document.getElementById("line-position-value");
const btnQuit           = document.getElementById("btn-quit");
const elModelSelect     = document.getElementById("model-select");
const elLoadingOverlay  = document.getElementById("model-loading-overlay");

// ── Current state ───────────────────────────────
let currentOrientation = "vertical";
let currentModelName = "";
let sliderDebounce = null;


// ── Load Models into Dropdown ───────────────────
async function loadModels() {
    try {
        const res = await fetch("/api/models");
        if (!res.ok) return;
        const data = await res.json();

        elModelSelect.innerHTML = "";
        data.models.forEach(function (m) {
            const opt = document.createElement("option");
            opt.value = m.key;
            opt.textContent = m.label + " (" + m.speed + ")";
            if (m.key === data.current) opt.selected = true;
            elModelSelect.appendChild(opt);
        });
        currentModelName = data.current;
    } catch (err) {
        console.error("[FlowDesk] Failed to load models:", err);
    }
}

// Load models on startup
loadModels();


// ── Direction Display Helper ────────────────────
function updateDirectionLabel(direction) {
    if (direction === "left_in") {
        elDirectionLabel.textContent = "← IN  |  OUT →";
    } else if (direction === "right_in") {
        elDirectionLabel.textContent = "← OUT  |  IN →";
    } else if (direction === "top_in") {
        elDirectionLabel.textContent = "↑ IN  |  OUT ↓";
    } else if (direction === "bottom_in") {
        elDirectionLabel.textContent = "↑ OUT  |  IN ↓";
    }
}

function updateOrientationButton(orientation) {
    currentOrientation = orientation;
    if (orientation === "vertical") {
        btnOrientation.textContent = "│ Vertical";
    } else {
        btnOrientation.textContent = "── Horizontal";
    }
}


// ── Loading Overlay ─────────────────────────────
function showLoadingOverlay() {
    elLoadingOverlay.classList.remove("hidden");
}

function hideLoadingOverlay() {
    elLoadingOverlay.classList.add("hidden");
}


// ── Status Polling ──────────────────────────────
async function fetchStatus() {
    try {
        const res = await fetch("/api/status");
        if (!res.ok) return;
        const data = await res.json();

        // Update date display
        elBsDate.textContent = data.bs_month_name + " " + data.bs_day + ", " + data.bs_year;
        elAdDate.textContent = data.ad_date;

        // Update counters
        elCountIn.textContent  = data.count_in;
        elCountOut.textContent = data.count_out;
        elCountNet.textContent = data.net;

        // Update direction indicator
        updateDirectionLabel(data.direction);

        // Update orientation button
        updateOrientationButton(data.orientation);

        // Update camera input to reflect actual state
        elCameraInput.value = data.camera_index;

        // Sync slider (only if user isn't actively dragging)
        if (!sliderDebounce) {
            const pct = Math.round(data.line_position * 100);
            elLineSlider.value = pct;
            elLinePosValue.textContent = pct + "%";
        }

        // Model loading overlay
        if (data.model_loading) {
            showLoadingOverlay();
        } else {
            hideLoadingOverlay();
            // Update model dropdown if model changed
            if (data.model_name !== currentModelName) {
                currentModelName = data.model_name;
                elModelSelect.value = data.model_name;
            }
        }
    } catch (err) {
        console.error("[FlowDesk] Status poll error:", err);
    }
}

// Poll every 2 seconds
setInterval(fetchStatus, 2000);
// Initial fetch
fetchStatus();


// ── Switch Model ────────────────────────────────
elModelSelect.addEventListener("change", async function () {
    const modelName = elModelSelect.value;
    if (modelName === currentModelName) return;

    showLoadingOverlay();

    try {
        const res = await fetch("/api/models?model_name=" + encodeURIComponent(modelName), { method: "POST" });
        if (res.ok) {
            currentModelName = modelName;
            // The overlay will be hidden by status polling once model finishes loading
        } else {
            alert("Failed to switch model.");
            hideLoadingOverlay();
            loadModels(); // revert dropdown
        }
    } catch (err) {
        console.error("[FlowDesk] Model switch error:", err);
        alert("Failed to switch model: " + err.message);
        hideLoadingOverlay();
        loadModels();
    }
});


// ── Swap Direction ──────────────────────────────
btnSwapDirection.addEventListener("click", async function () {
    try {
        const res = await fetch("/api/swap-direction", { method: "POST" });
        if (res.ok) {
            const data = await res.json();
            updateDirectionLabel(data.direction);
            fetchStatus();
        } else {
            alert("Failed to swap direction.");
        }
    } catch (err) {
        console.error("[FlowDesk] Swap direction error:", err);
        alert("Failed to swap direction: " + err.message);
    }
});


// ── Toggle Orientation ──────────────────────────
btnOrientation.addEventListener("click", async function () {
    const newOrientation = currentOrientation === "vertical" ? "horizontal" : "vertical";
    try {
        const res = await fetch("/api/line/orientation?orientation=" + newOrientation, { method: "POST" });
        if (res.ok) {
            const data = await res.json();
            updateOrientationButton(data.orientation);
            fetchStatus();
        } else {
            alert("Failed to change orientation.");
        }
    } catch (err) {
        console.error("[FlowDesk] Orientation error:", err);
        alert("Failed to change orientation: " + err.message);
    }
});


// ── Line Position Slider ────────────────────────
elLineSlider.addEventListener("input", function () {
    elLinePosValue.textContent = elLineSlider.value + "%";

    if (sliderDebounce) clearTimeout(sliderDebounce);
    sliderDebounce = setTimeout(async function () {
        const position = parseInt(elLineSlider.value, 10) / 100;
        try {
            await fetch("/api/line/position?position=" + position, { method: "POST" });
        } catch (err) {
            console.error("[FlowDesk] Line position error:", err);
        }
        sliderDebounce = null;
    }, 200);
});


// ── Switch Camera ───────────────────────────────
btnSwitchCamera.addEventListener("click", async function () {
    const idx = parseInt(elCameraInput.value, 10);
    if (isNaN(idx) || idx < 0) {
        alert("Please enter a valid camera index (0, 1, 2, ...)");
        return;
    }

    try {
        const res = await fetch("/api/camera?camera_index=" + idx, { method: "POST" });
        if (res.ok) {
            const videoEl = document.getElementById("video-feed");
            videoEl.src = "/video_feed?t=" + Date.now();
        } else {
            alert("Failed to switch camera.");
        }
    } catch (err) {
        console.error("[FlowDesk] Camera switch error:", err);
        alert("Failed to switch camera: " + err.message);
    }
});


// ── Export CSV ───────────────────────────────────
btnExport.addEventListener("click", function () {
    let url = "/api/export/csv";
    const params = [];

    const fromVal = elFromDate.value.trim();
    const toVal   = elToDate.value.trim();

    if (fromVal) params.push("from_bs=" + encodeURIComponent(fromVal));
    if (toVal)   params.push("to_bs=" + encodeURIComponent(toVal));

    if (params.length > 0) {
        url += "?" + params.join("&");
    }

    window.location.href = url;
});


// ── Reset Today ─────────────────────────────────
btnReset.addEventListener("click", async function () {
    const ok = confirm("Reset today's counters to 0? This will NOT delete any CSV data.");
    if (!ok) return;

    try {
        const res = await fetch("/api/reset", { method: "POST" });
        if (res.ok) {
            fetchStatus();
        } else {
            alert("Reset failed. Please try again.");
        }
    } catch (err) {
        console.error("[FlowDesk] Reset error:", err);
        alert("Reset failed: " + err.message);
    }
});


// ── Quit / Shutdown ─────────────────────────────
btnQuit.addEventListener("click", async function () {
    const ok = confirm("Shut down FlowDesk? This will stop the camera feed and exit the server.");
    if (!ok) return;

    try {
        const res = await fetch("/api/shutdown", { method: "POST" });
        if (res.ok) {
            document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;"><div style="text-align:center;"><h1 style="font-size:2rem;color:#333;">FlowDesk has been shut down</h1><p style="color:#888;margin-top:8px;">You can close this window.</p></div></div>';
        }
    } catch (err) {
        document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;"><div style="text-align:center;"><h1 style="font-size:2rem;color:#333;">FlowDesk has been shut down</h1><p style="color:#888;margin-top:8px;">You can close this window.</p></div></div>';
    }
});


// ── PyWebView Settings Bar (Desktop Mode) ──────
// Only active when running inside PyWebView (window.pywebview exists)

function initSettingsBar() {
    const settingsBar  = document.getElementById("settings-bar");
    const csvPathText  = document.getElementById("csv-path-text");
    const btnChange    = document.getElementById("btn-change-folder");
    const savedMsg     = document.getElementById("settings-saved-msg");

    if (!settingsBar || !window.pywebview || !window.pywebview.api) {
        return; // Not in desktop mode — keep bar hidden
    }

    // Show the settings bar
    settingsBar.style.display = "flex";

    // Load current path
    window.pywebview.api.get_settings().then(function (settings) {
        if (settings && settings.csv_path) {
            csvPathText.textContent = "CSV saved to: " + settings.csv_path;
        }
    }).catch(function () {
        csvPathText.textContent = "CSV saved to: (unknown)";
    });

    // Change Folder button
    btnChange.addEventListener("click", function () {
        window.pywebview.api.set_csv_path().then(function (result) {
            if (result && result.success) {
                csvPathText.textContent = "CSV saved to: " + result.path;

                // Show "✓ Saved" confirmation
                savedMsg.classList.remove("hidden");
                savedMsg.classList.add("visible");
                setTimeout(function () {
                    savedMsg.classList.remove("visible");
                    savedMsg.classList.add("hidden");
                }, 2000);
            }
        }).catch(function (err) {
            console.error("[FlowDesk] Folder picker error:", err);
        });
    });
}

// PyWebView injects window.pywebview after DOM ready — wait for it
if (window.pywebview) {
    initSettingsBar();
} else {
    window.addEventListener("pywebviewready", function () {
        initSettingsBar();
    });
}
