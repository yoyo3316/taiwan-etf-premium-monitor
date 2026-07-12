"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Project paths
PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent
DATA_DIR = ROOT_DIR / "data"

LATEST_SNAPSHOT_PATH = DATA_DIR / "latest.json"
ALERT_STATE_PATH = DATA_DIR / "alert_state.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# Official TWSE endpoints used by indicator / value disclosure pages
TWSE_ALL_ETF_URL = "https://mis.twse.com.tw/stock/data/all_etf.txt"
TWSE_CATEGORY_URL = "https://mis.twse.com.tw/stock/api/getCategory.jsp"
TWSE_INDICATOR_PAGE = (
    "https://mis.twse.com.tw/stock/various-areas/etf-price/"
    "indicator-disclosure-etf?lang=zhHant"
)
TWSE_VALUE_PAGE = (
    "https://mis.twse.com.tw/stock/various-areas/etf-price/"
    "value-disclosure-etf?lang=zhHant"
)

TIMEZONE = "Asia/Taipei"
MARKET_OPEN = (9, 0)  # 09:00
MARKET_CLOSE = (13, 30)  # 13:30

DEFAULT_PREMIUM_THRESHOLD = 3.0
DEFAULT_DISCOUNT_THRESHOLD = -3.0
DEFAULT_DATA_MAX_AGE_MINUTES = 10
CROSS_CHECK_TOLERANCE_PP = 0.05  # percentage points


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    premium_threshold: float = DEFAULT_PREMIUM_THRESHOLD
    discount_threshold: float = DEFAULT_DISCOUNT_THRESHOLD
    data_max_age_minutes: int = DEFAULT_DATA_MAX_AGE_MINUTES
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    cross_check_tolerance_pp: float = CROSS_CHECK_TOLERANCE_PP

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            premium_threshold=_float_env(
                "PREMIUM_THRESHOLD", DEFAULT_PREMIUM_THRESHOLD
            ),
            discount_threshold=_float_env(
                "DISCOUNT_THRESHOLD", DEFAULT_DISCOUNT_THRESHOLD
            ),
            data_max_age_minutes=_int_env(
                "DATA_MAX_AGE_MINUTES", DEFAULT_DATA_MAX_AGE_MINUTES
            ),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            cross_check_tolerance_pp=CROSS_CHECK_TOLERANCE_PP,
        )


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
