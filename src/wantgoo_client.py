"""WantGoo (玩股網) historical premium/discount client — reference only.

Frontend page:
  https://www.wantgoo.com/stock/etf/{code}/discount-premium

Actual XHR used by discount-premium.min.js:
  GET /stock/etf/{id}/discount-premium-data
      -> list[{date, bookValue, netChange, ...}]
  GET /investrue/{id}/daily-candlesticks?after={ms}
      -> list[{tradeDate, close, ...}]

Client-side formula (same as WantGoo):
  discountPremium = close - bookValue
  discountPremiumPercent = discountPremium / bookValue * 100

NOTE:
  Real-time TWSE data remains the primary alert source.
  WantGoo history is optional reference for next-day convergence stats.
  The JSON endpoints may return HTTP 400 for automated clients; callers
  must tolerate failure and fall back to local/TWSE history.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .market_hours import TZ

logger = logging.getLogger(__name__)

WANTGOO_ORIGIN = "https://www.wantgoo.com"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": WANTGOO_ORIGIN,
}


def wantgoo_page_url(code: str) -> str:
    return f"{WANTGOO_ORIGIN}/stock/etf/{code.lower()}/discount-premium"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def _to_ms_date(value: Any) -> int | None:
    if value is None:
        return None
    try:
        v = int(value)
        # seconds -> ms
        if v < 10_000_000_000:
            v *= 1000
        return v
    except (TypeError, ValueError):
        return None


def _ms_to_ymd(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(TZ)
    return dt.strftime("%Y-%m-%d")


def fetch_discount_premium_raw(
    code: str, timeout: int = 25
) -> list[dict[str, Any]]:
    """Fetch WantGoo NAV series (bookValue by date)."""
    code = code.strip()
    url = f"{WANTGOO_ORIGIN}/stock/etf/{code}/discount-premium-data"
    sess = _session()
    # warm referer page (some WAF care about path continuity)
    try:
        sess.get(wantgoo_page_url(code), timeout=timeout)
    except Exception:
        pass
    resp = sess.get(
        url,
        headers={"Referer": wantgoo_page_url(code)},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"WantGoo discount-premium-data HTTP {resp.status_code}: "
            f"{resp.text[:120]}"
        )
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected WantGoo discount-premium-data shape")
    return data


def fetch_daily_candles_after(
    code: str, after_ms: int, timeout: int = 25
) -> list[dict[str, Any]]:
    code = code.strip()
    url = (
        f"{WANTGOO_ORIGIN}/investrue/{code}/daily-candlesticks"
        f"?after={int(after_ms)}"
    )
    sess = _session()
    resp = sess.get(
        url,
        headers={"Referer": wantgoo_page_url(code)},
        timeout=timeout,
    )
    if resp.status_code != 200:
        # try singular path seen in some builds
        url2 = (
            f"{WANTGOO_ORIGIN}/investrue/{code}/daily-candlestick"
            f"?after={int(after_ms)}"
        )
        resp = sess.get(
            url2,
            headers={"Referer": wantgoo_page_url(code)},
            timeout=timeout,
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"WantGoo candlesticks HTTP {resp.status_code}: {resp.text[:120]}"
        )
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected WantGoo candlesticks shape")
    return data


def build_history_from_wantgoo(code: str) -> dict[str, Any]:
    """Merge NAV + close into daily premium/discount series (WantGoo formula)."""
    code = code.strip().upper()
    nav_rows = fetch_discount_premium_raw(code)
    if not nav_rows:
        return {
            "code": code,
            "source": "wantgoo",
            "page_url": wantgoo_page_url(code),
            "rows": [],
            "error": "empty discount-premium-data",
            "fetched_at": datetime.now(TZ).isoformat(),
        }

    dates = [_to_ms_date(r.get("date")) for r in nav_rows]
    dates = [d for d in dates if d is not None]
    after_ms = min(dates) - 86_400_000 if dates else 0
    # WantGoo uses last_nav_date - 1 day as after for candles
    last_ms = max(dates) if dates else 0
    candle_after = last_ms - 86_400_000 if last_ms else after_ms

    candles: list[dict[str, Any]] = []
    candle_err = None
    try:
        candles = fetch_daily_candles_after(code, candle_after)
    except Exception as exc:
        candle_err = str(exc)
        logger.warning("WantGoo candles failed for %s: %s", code, exc)

    candle_by_date: dict[int, float] = {}
    for c in candles:
        td = _to_ms_date(c.get("tradeDate") or c.get("date"))
        close = c.get("close")
        if td is None or close is None:
            continue
        try:
            candle_by_date[td] = float(close)
        except (TypeError, ValueError):
            continue

    rows: list[dict[str, Any]] = []
    for r in nav_rows:
        d_ms = _to_ms_date(r.get("date"))
        if d_ms is None:
            continue
        try:
            book = float(r.get("bookValue"))
        except (TypeError, ValueError):
            continue
        if book <= 0:
            continue
        close = candle_by_date.get(d_ms)
        if close is None:
            # keep NAV-only day without PD
            rows.append(
                {
                    "date": _ms_to_ymd(d_ms),
                    "date_ms": d_ms,
                    "close": None,
                    "nav": round(book, 4),
                    "premium_discount_pct": None,
                    "premium_discount": None,
                }
            )
            continue
        prem = close - book
        pct = prem / book * 100.0
        rows.append(
            {
                "date": _ms_to_ymd(d_ms),
                "date_ms": d_ms,
                "close": round(close, 4),
                "nav": round(book, 4),
                "premium_discount": round(prem, 4),
                "premium_discount_pct": round(pct, 4),
            }
        )

    rows.sort(key=lambda x: x["date"])
    return {
        "code": code,
        "source": "wantgoo",
        "page_url": wantgoo_page_url(code),
        "rows": rows,
        "row_count": len(rows),
        "usable_pd_count": sum(
            1 for r in rows if r.get("premium_discount_pct") is not None
        ),
        "candle_error": candle_err,
        "fetched_at": datetime.now(TZ).isoformat(),
    }


def try_fetch_history(code: str) -> dict[str, Any]:
    """Best-effort fetch; never raises."""
    try:
        return build_history_from_wantgoo(code)
    except Exception as exc:
        logger.warning("WantGoo history failed for %s: %s", code, exc)
        return {
            "code": code.strip().upper(),
            "source": "wantgoo",
            "page_url": wantgoo_page_url(code),
            "rows": [],
            "error": str(exc),
            "fetched_at": datetime.now(TZ).isoformat(),
        }
