"""Alert lock state: one notification per ETF per direction until recovery."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ALERT_STATE_PATH, ensure_data_dir
from .market_hours import TZ, now_taipei

logger = logging.getLogger(__name__)


def load_alert_state(path: Path | None = None) -> dict[str, Any]:
    path = path or ALERT_STATE_PATH
    if not path.exists():
        return {"locks": {}, "history": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"locks": {}, "history": []}
        data.setdefault("locks", {})
        data.setdefault("history", [])
        return data
    except Exception as exc:
        logger.warning("Failed to load alert state: %s", exc)
        return {"locks": {}, "history": []}


def save_alert_state(state: dict[str, Any], path: Path | None = None) -> None:
    path = path or ALERT_STATE_PATH
    ensure_data_dir()
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def lock_key(code: str, direction: str) -> str:
    return f"{code}:{direction}"


def is_locked(state: dict[str, Any], code: str, direction: str) -> bool:
    locks = state.get("locks") or {}
    return lock_key(code, direction) in locks


def set_lock(
    state: dict[str, Any],
    *,
    code: str,
    name: str,
    direction: str,
    rate: float,
    market_price: float | None,
    estimated_nav: float | None,
) -> None:
    locks = state.setdefault("locks", {})
    now = now_taipei().isoformat()
    locks[lock_key(code, direction)] = {
        "code": code,
        "name": name,
        "direction": direction,
        "rate": rate,
        "market_price": market_price,
        "estimated_nav": estimated_nav,
        "notified_at": now,
        "updated_at": now,
    }


def clear_lock(state: dict[str, Any], code: str, direction: str) -> bool:
    locks = state.get("locks") or {}
    key = lock_key(code, direction)
    if key in locks:
        del locks[key]
        return True
    return False


def clear_all_locks_for_code(state: dict[str, Any], code: str) -> list[str]:
    locks = state.get("locks") or {}
    removed = []
    for direction in ("premium", "discount"):
        key = lock_key(code, direction)
        if key in locks:
            del locks[key]
            removed.append(direction)
    return removed


def append_history(
    state: dict[str, Any],
    entry: dict[str, Any],
    max_history: int = 200,
) -> None:
    history = state.setdefault("history", [])
    history.insert(0, entry)
    del history[max_history:]


def active_alerts(state: dict[str, Any]) -> list[dict[str, Any]]:
    locks = state.get("locks") or {}
    rows = list(locks.values())
    rows.sort(key=lambda r: r.get("notified_at") or "", reverse=True)
    return rows
