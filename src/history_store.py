"""Persist WantGoo / TWSE historical premium-discount series."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import DATA_DIR, ensure_data_dir
from .market_hours import TZ, now_taipei

logger = logging.getLogger(__name__)

HISTORY_DIR = DATA_DIR / "history"
WANTGOO_DIR = HISTORY_DIR / "wantgoo"
TWSE_EOD_PATH = HISTORY_DIR / "twse_eod.json"
CONVERGENCE_CACHE_PATH = HISTORY_DIR / "convergence_cache.json"


def _ensure() -> None:
    ensure_data_dir()
    WANTGOO_DIR.mkdir(parents=True, exist_ok=True)


def wantgoo_history_path(code: str) -> Path:
    return WANTGOO_DIR / f"{code.upper()}.json"


def load_wantgoo_history(code: str) -> dict[str, Any] | None:
    path = wantgoo_history_path(code)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("load wantgoo history %s: %s", code, exc)
        return None


def save_wantgoo_history(payload: dict[str, Any]) -> Path:
    _ensure()
    code = str(payload.get("code") or "UNKNOWN").upper()
    path = wantgoo_history_path(code)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def is_fresh(payload: dict[str, Any] | None, max_age_hours: int = 20) -> bool:
    if not payload or not payload.get("rows"):
        return False
    if payload.get("error"):
        return False
    ts = payload.get("fetched_at")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return now_taipei() - dt.astimezone(TZ) <= timedelta(hours=max_age_hours)
    except Exception:
        return False


def load_twse_eod() -> dict[str, Any]:
    _ensure()
    if not TWSE_EOD_PATH.exists():
        return {"source": "twse", "by_code": {}, "updated_at": None}
    try:
        return json.loads(TWSE_EOD_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"source": "twse", "by_code": {}, "updated_at": None}


def append_twse_eod_snapshot(
    etf_rows: list[dict[str, Any]],
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Append one end-of-day (or latest) PD point per ETF (dedupe by date)."""
    _ensure()
    store = load_twse_eod()
    by_code: dict[str, Any] = store.setdefault("by_code", {})
    day = as_of_date or now_taipei().strftime("%Y-%m-%d")

    for r in etf_rows:
        code = str(r.get("code") or "").upper()
        pct = r.get("premium_discount_pct")
        if not code or not isinstance(pct, (int, float)):
            continue
        # prefer rows that have price/nav
        series = by_code.setdefault(code, {"code": code, "name": r.get("name"), "rows": []})
        series["name"] = r.get("name") or series.get("name")
        rows: list[dict[str, Any]] = series["rows"]
        # replace same day
        rows = [x for x in rows if x.get("date") != day]
        rows.append(
            {
                "date": day,
                "close": r.get("market_price"),
                "nav": r.get("estimated_nav"),
                "premium_discount_pct": round(float(pct), 4),
                "source": "twse",
            }
        )
        rows.sort(key=lambda x: x["date"])
        # keep ~2 years trading days
        series["rows"] = rows[-520:]

    store["updated_at"] = now_taipei().isoformat()
    TWSE_EOD_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return store


def get_twse_series(code: str) -> list[dict[str, Any]]:
    store = load_twse_eod()
    entry = (store.get("by_code") or {}).get(code.upper()) or {}
    return list(entry.get("rows") or [])


def load_convergence_cache() -> dict[str, Any]:
    _ensure()
    if not CONVERGENCE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CONVERGENCE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_convergence_cache(cache: dict[str, Any]) -> None:
    _ensure()
    CONVERGENCE_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
