"""
storage.py — CSV read/write helpers for daily people counts.

CSV format:
  bs_date,ad_date,count_in,count_out
  2081-01-15,2024-04-27,42,38
"""

import csv
import os
import threading

from nepali_utils import today_bs, today_ad

# CSV path — set at runtime by launcher.py (or main.py for dev mode)
CSV_PATH = "data/counts.csv"
_CSV_HEADER = ["bs_date", "ad_date", "count_in", "count_out"]
_file_lock = threading.Lock()


def set_csv_path(path: str):
    """Update the CSV file path at runtime. Creates parent directory if needed."""
    global CSV_PATH
    CSV_PATH = path
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _ensure_csv():
    """Create the CSV file and data/ directory if they don't exist."""
    directory = os.path.dirname(CSV_PATH)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(_CSV_HEADER)


def _read_all_rows() -> list[dict]:
    """Read all rows from the CSV as a list of dicts."""
    _ensure_csv()
    with open(CSV_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _write_all_rows(rows: list[dict]):
    """Write all rows back to the CSV (overwrites the file)."""
    _ensure_csv()
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def load_today() -> dict | None:
    """Read CSV and return today's row as a dict, or None if not found."""
    bs_today = today_bs()
    with _file_lock:
        rows = _read_all_rows()
        for row in rows:
            if row["bs_date"] == bs_today:
                return {
                    "bs_date": row["bs_date"],
                    "ad_date": row["ad_date"],
                    "count_in": int(row["count_in"]),
                    "count_out": int(row["count_out"]),
                }
    return None


def save_today(count_in: int, count_out: int):
    """Upsert today's row in the CSV with the given counts."""
    bs_today = today_bs()
    ad_today = today_ad()
    with _file_lock:
        rows = _read_all_rows()
        found = False
        for row in rows:
            if row["bs_date"] == bs_today:
                row["count_in"] = str(count_in)
                row["count_out"] = str(count_out)
                found = True
                break
        if not found:
            rows.append({
                "bs_date": bs_today,
                "ad_date": ad_today,
                "count_in": str(count_in),
                "count_out": str(count_out),
            })
        _write_all_rows(rows)


def load_range(from_bs: str = None, to_bs: str = None) -> list[dict]:
    """
    Return rows filtered by BS date range (inclusive).
    If no params given, return all rows.
    """
    with _file_lock:
        rows = _read_all_rows()

    if not from_bs and not to_bs:
        return rows

    filtered = []
    for row in rows:
        bs = row["bs_date"]
        if from_bs and bs < from_bs:
            continue
        if to_bs and bs > to_bs:
            continue
        filtered.append(row)
    return filtered
