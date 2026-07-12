"""Snapshot persistence for dashboard and Actions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import LATEST_SNAPSHOT_PATH, SETTINGS_PATH, ensure_data_dir
from .market_hours import now_taipei

logger = logging.getLogger(__name__)


def save_snapshot(snapshot: dict[str, Any], path: Path | None = None) -> Path:
    path = path or LATEST_SNAPSHOT_PATH
    ensure_data_dir()
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_snapshot(path: Path | None = None) -> dict[str, Any] | None:
    path = path or LATEST_SNAPSHOT_PATH
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load snapshot: %s", exc)
        return None


def load_settings_file(path: Path | None = None) -> dict[str, Any]:
    path = path or SETTINGS_PATH
    defaults = {
        "premium_threshold": 3.0,
        "discount_threshold": -3.0,
        "data_max_age_minutes": 10,
    }
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return defaults
        defaults.update({k: data[k] for k in defaults if k in data})
        return defaults
    except Exception:
        return defaults


def save_settings_file(settings: dict[str, Any], path: Path | None = None) -> None:
    path = path or SETTINGS_PATH
    ensure_data_dir()
    current = load_settings_file(path)
    current.update(settings)
    current["updated_at"] = now_taipei().isoformat()
    path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
