# FlowDesk — People Counting System

A lightweight web application that uses a webcam feed and **YOLO26 nano** computer vision to count people entering and exiting a location in real time. Counts reset daily at midnight. Data is stored in a local CSV file with dates shown in both **Nepali (BS)** and **English (AD)** formats.

---

## Installation

```bash
# Clone or navigate to the project directory
cd flowdesk

# Install dependencies
pip install -r requirements.txt
```

> **Note:** `yolo26n.pt` (≈6 MB) downloads automatically on first run via the Ultralytics library.

---

## Run

```bash
uvicorn main:app --reload
```

Open your browser at: **http://localhost:8000**

---

## How It Works

1. The app opens your webcam and runs YOLO26 nano person detection + tracking.
2. A **horizontal counting line** is drawn across the frame (default: 50% height).
3. When a person's centroid crosses the line:
   - **Top → Bottom** = counted as **IN**
   - **Bottom → Top** = counted as **OUT**
4. Counts are saved to `data/counts.csv` and reset automatically at **12:00 AM** daily.

---

## Configuration

Edit the constants at the top of `main.py`:

| Variable                  | Default | Description                                      |
|---------------------------|---------|--------------------------------------------------|
| `CAMERA_INDEX`            | `0`     | Webcam device index (try 1, 2, etc. for external)|
| `COUNTING_LINE_POSITION`  | `0.5`   | Fraction of frame height (0.0=top, 1.0=bottom)   |
| `CSV_PATH`                | `data/counts.csv` | Path to the data file                  |

---

## CSV File Format

File: `data/counts.csv`

```csv
bs_date,ad_date,count_in,count_out
2081-01-15,2024-04-27,42,38
2081-01-16,2024-04-28,17,15
```

- One row per day
- `bs_date`: Bikram Sambat (YYYY-MM-DD)
- `ad_date`: Gregorian (YYYY-MM-DD)
- Human-readable and editable

---

## API Endpoints

| Endpoint              | Method | Description                        |
|-----------------------|--------|------------------------------------|
| `/video_feed`         | GET    | MJPEG live stream with overlays    |
| `/api/status`         | GET    | Current counts + date info (JSON)  |
| `/api/export/csv`     | GET    | Download filtered CSV              |
| `/api/reset`          | POST   | Reset today's counters to 0        |

### Export API Example

```bash
# Export a date range
curl "http://localhost:8000/api/export/csv?from_bs=2081-01-01&to_bs=2081-01-30" -o export.csv

# Export all data
curl "http://localhost:8000/api/export/csv" -o export_all.csv
```

### Integration Note

The export endpoint can be called directly from any external web application — no authentication is required for local use.

---

## Project Structure

```
flowdesk/
├── main.py               # FastAPI app + all routes
├── detector.py           # YOLO26 detection + line-crossing tracker
├── storage.py            # CSV read/write helpers
├── nepali_utils.py       # BS/AD date conversion helpers
├── data/
│   └── counts.csv        # Auto-created on first run
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── requirements.txt
└── README.md
```

---

## License

YOLO26 is licensed under **AGPL-3.0** for open-source and personal use. See the [Ultralytics License](https://github.com/ultralytics/ultralytics/blob/main/LICENSE) for details.
