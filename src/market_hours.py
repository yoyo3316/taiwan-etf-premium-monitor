"""Taiwan stock market session helpers (Asia/Taipei)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Iterable
from zoneinfo import ZoneInfo

import requests

from .config import MARKET_CLOSE, MARKET_OFFICIAL_OPEN, MARKET_OPEN, TIMEZONE

TZ = ZoneInfo(TIMEZONE)

# Fallback holidays if TWSE calendar fetch fails (YYYY-MM-DD).
# Keep a small rolling set; Actions should still prefer live calendar.
_FALLBACK_HOLIDAYS: frozenset[str] = frozenset(
    {
        # 2025
        "2025-01-01",
        "2025-01-27",
        "2025-01-28",
        "2025-01-29",
        "2025-01-30",
        "2025-01-31",
        "2025-02-28",
        "2025-04-03",
        "2025-04-04",
        "2025-05-01",
        "2025-05-30",
        "2025-10-06",
        "2025-10-10",
        # 2026
        "2026-01-01",
        "2026-01-02",
        "2026-02-16",
        "2026-02-17",
        "2026-02-18",
        "2026-02-19",
        "2026-02-20",
        "2026-02-27",
        "2026-04-03",
        "2026-04-06",
        "2026-05-01",
        "2026-06-19",
        "2026-09-25",
        "2026-10-09",
        "2026-10-12",
    }
)


def now_taipei() -> datetime:
    return datetime.now(TZ)


def _parse_holiday_date(value: str) -> date | None:
    value = (value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


@lru_cache(maxsize=4)
def fetch_twse_holidays(year: int) -> frozenset[date]:
    """Fetch TWSE holiday list for a calendar year.

    Endpoint used by TWSE holiday schedule pages. Failures fall back to empty
    set so weekday checks still apply; callers merge with fallback holidays.
    """
    url = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidayList"
    try:
        resp = requests.get(
            url,
            params={"response": "json", "queryYear": str(year)},
            timeout=20,
            headers={"User-Agent": "taiwan-etf-premium-monitor/1.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return frozenset()

    holidays: set[date] = set()
    rows: Iterable = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("tables") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or []
    for row in rows:
        # Typical row: [date, name, weekday, description...]
        if isinstance(row, (list, tuple)) and row:
            d = _parse_holiday_date(str(row[0]))
            if d:
                holidays.add(d)
        elif isinstance(row, dict):
            for key in ("Date", "date", "日期"):
                if key in row:
                    d = _parse_holiday_date(str(row[key]))
                    if d:
                        holidays.add(d)
                    break
    return frozenset(holidays)


def holiday_set_for(d: date) -> set[date]:
    holidays = set(fetch_twse_holidays(d.year))
    for s in _FALLBACK_HOLIDAYS:
        parsed = _parse_holiday_date(s)
        if parsed and parsed.year == d.year:
            holidays.add(parsed)
    return holidays


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # Sat=5, Sun=6


def is_trading_day(d: date | None = None) -> bool:
    d = d or now_taipei().date()
    if is_weekend(d):
        return False
    if d in holiday_set_for(d):
        return False
    return True


def is_market_session(when: datetime | None = None) -> bool:
    """True during monitor window: weekdays 08:50–13:30 Taipei, non-holiday.

    08:50–09:00 is pre-open watch; 09:00–13:30 is the continuous auction session.
    """
    when = when or now_taipei()
    if when.tzinfo is None:
        when = when.replace(tzinfo=TZ)
    else:
        when = when.astimezone(TZ)

    if not is_trading_day(when.date()):
        return False

    open_t = time(*MARKET_OPEN)
    close_t = time(*MARKET_CLOSE)
    t = when.time()
    return open_t <= t <= close_t


def is_premarket_watch(when: datetime | None = None) -> bool:
    """True on trading days during 08:50–09:00 (before official open)."""
    when = when or now_taipei()
    if when.tzinfo is None:
        when = when.replace(tzinfo=TZ)
    else:
        when = when.astimezone(TZ)
    if not is_trading_day(when.date()):
        return False
    t = when.time()
    return time(*MARKET_OPEN) <= t < time(*MARKET_OFFICIAL_OPEN)


def session_status(when: datetime | None = None) -> dict:
    when = when or now_taipei()
    if when.tzinfo is None:
        when = when.replace(tzinfo=TZ)
    else:
        when = when.astimezone(TZ)

    trading_day = is_trading_day(when.date())
    in_session = is_market_session(when)
    if not trading_day:
        reason = "休市日（週末或國定假日）"
        state = "closed_day"
    elif when.time() < time(*MARKET_OPEN):
        reason = "監控開始前"
        state = "before_watch"
    elif when.time() < time(*MARKET_OFFICIAL_OPEN):
        reason = "盤前監控中（08:50 起）"
        state = "pre_market"
    elif when.time() > time(*MARKET_CLOSE):
        reason = "收盤後"
        state = "after_market"
    else:
        reason = "交易時段中"
        state = "open"

    return {
        "now": when.isoformat(),
        "timezone": TIMEZONE,
        "is_trading_day": trading_day,
        "in_session": in_session,
        "is_premarket_watch": is_premarket_watch(when),
        "state": state,
        "reason": reason,
        "session": f"{MARKET_OPEN[0]:02d}:{MARKET_OPEN[1]:02d}"
        f"–{MARKET_CLOSE[0]:02d}:{MARKET_CLOSE[1]:02d}",
        "official_open": f"{MARKET_OFFICIAL_OPEN[0]:02d}:{MARKET_OFFICIAL_OPEN[1]:02d}",
    }


def parse_twse_datetime(date_str: str | None, time_str: str | None) -> datetime | None:
    """Parse TWSE fields i=YYYYMMDD, j=HH:MM:SS into aware Taipei datetime."""
    if not date_str or not time_str:
        return None
    date_str = str(date_str).strip()
    time_str = str(time_str).strip()
    if not date_str or not time_str:
        return None
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M:%S")
        return dt.replace(tzinfo=TZ)
    except ValueError:
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M")
            return dt.replace(tzinfo=TZ)
        except ValueError:
            return None


def is_stale(
    data_time: datetime | None,
    max_age_minutes: int,
    now: datetime | None = None,
) -> bool:
    if data_time is None:
        return True
    now = now or now_taipei()
    if data_time.tzinfo is None:
        data_time = data_time.replace(tzinfo=TZ)
    age = now - data_time.astimezone(TZ)
    return age > timedelta(minutes=max_age_minutes)
