"""
nepali_utils.py — BS/AD date conversion helpers using nepali-datetime.
"""

import nepali_datetime

# Nepali month names (1-indexed)
_BS_MONTH_NAMES = [
    "",          # placeholder for index 0
    "Baisakh",
    "Jestha",
    "Ashadh",
    "Shrawan",
    "Bhadra",
    "Ashwin",
    "Kartik",
    "Mangsir",
    "Poush",
    "Magh",
    "Falgun",
    "Chaitra",
]


def today_bs() -> str:
    """Return today's Bikram Sambat date as 'YYYY-MM-DD'."""
    now = nepali_datetime.date.today()
    return now.strftime("%Y-%m-%d")


def today_ad() -> str:
    """Return today's Gregorian date as 'YYYY-MM-DD'."""
    import datetime
    return datetime.date.today().strftime("%Y-%m-%d")


def ad_to_bs(ad_str: str) -> str:
    """Convert a Gregorian 'YYYY-MM-DD' string to BS 'YYYY-MM-DD'."""
    import datetime
    ad_date = datetime.date.fromisoformat(ad_str)
    bs_date = nepali_datetime.date.from_datetime_date(ad_date)
    return bs_date.strftime("%Y-%m-%d")


def bs_to_ad(bs_str: str) -> str:
    """Convert a BS 'YYYY-MM-DD' string to Gregorian 'YYYY-MM-DD'."""
    parts = bs_str.split("-")
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    bs_date = nepali_datetime.date(year, month, day)
    ad_date = bs_date.to_datetime_date()
    return ad_date.strftime("%Y-%m-%d")


def bs_month_name(month_int: int) -> str:
    """Return the Nepali month name for a 1-indexed month number."""
    if 1 <= month_int <= 12:
        return _BS_MONTH_NAMES[month_int]
    return ""


def today_bs_parts() -> dict:
    """Return today's BS date as a dict with year, month, day, month_name."""
    now = nepali_datetime.date.today()
    return {
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "month_name": bs_month_name(now.month),
    }
