"""TWSE official data client for ETF premium/discount fields.

The Vue frontend pages:
  - indicator-disclosure-etf
  - value-disclosure-etf

load data via category-*.js:

  function S() {
    return request({ method: "get", url: `/stock/data/all_etf.txt?_=${Date.now()}` })
  }

Field mapping (confirmed from page UI + sample payload):
  a  ETF code
  b  ETF name
  c  outstanding units
  d  unit change vs previous day
  e  market price (成交價)
  f  estimated NAV / indicator value (預估淨值)
  g  estimated premium/discount % (預估折溢價幅度)
  h  previous business day NAV
  i  data date YYYYMMDD
  j  data time HH:MM:SS
  k  category (1 domestic, 2 Asia, 3 Europe/America, 4 global, etc.)
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import TWSE_ALL_ETF_URL, TWSE_CATEGORY_URL

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; taiwan-etf-premium-monitor/1.0; "
        "+https://github.com/)"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": (
        "https://mis.twse.com.tw/stock/various-areas/etf-price/"
        "indicator-disclosure-etf?lang=zhHant"
    ),
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if s in ("", "-", "--", "N/A", "n/a", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def fetch_all_etf_raw(timeout: int = 30) -> dict[str, Any]:
    """Fetch the official all_etf.txt JSON used by TWSE disclosure pages."""
    url = f"{TWSE_ALL_ETF_URL}?_={int(__import__('time').time() * 1000)}"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    # TWSE serves UTF-8 JSON; force utf-8 to avoid mis-detection on some clients
    resp.encoding = "utf-8"
    data = resp.json()
    if not isinstance(data, dict) or "a1" not in data:
        raise ValueError("Unexpected all_etf.txt structure: missing key 'a1'")
    return data


def fetch_category_etf_codes(
    exchange: str = "tse", category: str = "B0", timeout: int = 20
) -> list[dict[str, str]]:
    """Optional: TWSE category list (B0 = ETF) for cross-reference."""
    url = (
        f"{TWSE_CATEGORY_URL}?ex={exchange}&i={category}"
        f"&_={int(__import__('time').time() * 1000)}&lang=zh_tw"
    )
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning("getCategory.jsp failed: %s", exc)
        return []

    rows = payload.get("msgArray") or []
    out: list[dict[str, str]] = []
    for row in rows:
        ch = _to_str(row.get("ch"))
        code = ch.split(".")[0] if ch else _to_str(row.get("c") or row.get("n"))
        name = _to_str(row.get("n") or row.get("name"))
        if code:
            out.append(
                {
                    "code": code,
                    "name": name,
                    "ex": _to_str(row.get("ex") or exchange),
                    "ch": ch,
                }
            )
    return out


def parse_all_etf(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten issuer blocks into a list of normalized ETF records."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for block in payload.get("a1") or []:
        if not isinstance(block, dict):
            continue
        ref_url = _to_str(block.get("refURL"))
        user_delay = block.get("userDelay") or block.get("userdelay")
        for row in block.get("msgArray") or []:
            if not isinstance(row, dict):
                continue
            code = _to_str(row.get("a"))
            if not code or code in seen:
                continue
            seen.add(code)

            market_price = _to_float(row.get("e"))
            est_nav = _to_float(row.get("f"))
            official_pd = _to_float(row.get("g"))
            prev_nav = _to_float(row.get("h"))

            records.append(
                {
                    "code": code,
                    "name": _to_str(row.get("b")),
                    "units": _to_float(row.get("c")),
                    "unit_change": _to_float(row.get("d")),
                    "market_price": market_price,
                    "estimated_nav": est_nav,
                    "official_premium_discount_pct": official_pd,
                    "prev_nav": prev_nav,
                    "data_date": _to_str(row.get("i")),
                    "data_time": _to_str(row.get("j")),
                    "category": _to_str(row.get("k")),
                    "issuer_ref_url": ref_url,
                    "user_delay_ms": _to_float(user_delay),
                    "raw": {
                        "a": row.get("a"),
                        "b": row.get("b"),
                        "e": row.get("e"),
                        "f": row.get("f"),
                        "g": row.get("g"),
                        "h": row.get("h"),
                        "i": row.get("i"),
                        "j": row.get("j"),
                        "k": row.get("k"),
                    },
                }
            )

    records.sort(key=lambda r: r["code"])
    return records


def fetch_etf_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch and parse all ETF rows from TWSE official all_etf.txt."""
    payload = fetch_all_etf_raw()
    records = parse_all_etf(payload)
    meta = {
        "source_url": TWSE_ALL_ETF_URL,
        "source_pages": {
            "indicator_disclosure": (
                "https://mis.twse.com.tw/stock/various-areas/etf-price/"
                "indicator-disclosure-etf?lang=zhHant"
            ),
            "value_disclosure": (
                "https://mis.twse.com.tw/stock/various-areas/etf-price/"
                "value-disclosure-etf?lang=zhHant"
            ),
        },
        "block_count": len(payload.get("a1") or []),
        "record_count": len(records),
    }
    return records, meta
