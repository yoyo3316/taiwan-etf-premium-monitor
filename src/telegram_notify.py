"""Telegram Bot API notifications (token/chat from environment only)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import TWSE_INDICATOR_PAGE

logger = logging.getLogger(__name__)


def format_alert_message(row: dict[str, Any]) -> str:
    direction = row.get("alert_direction")
    if direction == "premium":
        title = "🔴 溢價警示"
    elif direction == "discount":
        title = "🔵 折價警示"
    else:
        title = "⚠️ ETF 折溢價警示"

    rate = row.get("premium_discount_pct")
    rate_s = f"{rate:+.2f}%" if isinstance(rate, (int, float)) else "N/A"
    price = row.get("market_price")
    nav = row.get("estimated_nav")
    price_s = f"{price:.4f}" if isinstance(price, (int, float)) else "N/A"
    nav_s = f"{nav:.4f}" if isinstance(nav, (int, float)) else "N/A"
    data_time = row.get("data_time_iso") or (
        f"{row.get('data_date', '')} {row.get('data_time', '')}".strip()
    )

    lines = [
        title,
        "",
        f"代號：{row.get('code', '')}",
        f"名稱：{row.get('name', '')}",
        f"市價：{price_s}",
        f"預估淨值／指標價值：{nav_s}",
        f"折溢價：{rate_s}",
        f"通知類型：{'溢價警示' if direction == 'premium' else '折價警示'}",
        f"資料時間：{data_time}",
        f"資料來源：{TWSE_INDICATOR_PAGE}",
    ]
    return "\n".join(lines)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    timeout: int = 30,
) -> bool:
    if not bot_token or not chat_id:
        logger.error("Telegram credentials missing; skip send")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code != 200:
            logger.error(
                "Telegram API error %s: %s", resp.status_code, resp.text[:300]
            )
            return False
        data = resp.json()
        if not data.get("ok"):
            logger.error("Telegram API not ok: %s", data)
            return False
        return True
    except Exception as exc:
        logger.exception("Telegram send failed: %s", exc)
        return False


def notify_alert(
    bot_token: str | None,
    chat_id: str | None,
    row: dict[str, Any],
) -> bool:
    if not bot_token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; dry-run")
        logger.info("Would notify:\n%s", format_alert_message(row))
        return False
    return send_telegram_message(bot_token, chat_id, format_alert_message(row))
