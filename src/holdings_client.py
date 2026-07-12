"""Fetch ETF disclosed holdings for overlap verification.

Primary free source used (weekly job):
  https://www.pocket.tw/etf/tw/{code}
  Embeds top holdings with {name, weight, code} in SSR payload.

Notes:
  - Pocket typically discloses **top holdings** (often ~10 names), not always
    100% of NAV. Metrics therefore report coverage and within-top overlap.
  - Same-index ETFs (e.g. 0050 / 006208 both track Taiwan 50) are annotated
    separately as official index identity (full equity universe match).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import requests
import urllib3

from .market_hours import TZ, now_taipei

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def pocket_url(code: str) -> str:
    return f"https://www.pocket.tw/etf/tw/{code.lower()}"


def fetch_holdings_pocket(code: str, timeout: int = 30) -> dict[str, Any]:
    """Return holdings dict for one ETF from pocket.tw page embed."""
    code = code.strip().upper()
    url = pocket_url(code)
    resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
    resp.raise_for_status()
    text = resp.text

    # Primary pattern from Nuxt SSR payload
    items = re.findall(
        r'\{name:"([^"]+)",weight:"([0-9.]+)",code:"([0-9A-Z]{4,6})"',
        text,
    )
    holdings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, weight, stock in items:
        stock = stock.upper()
        if stock in seen:
            continue
        # skip self-reference if any
        if stock == code:
            continue
        seen.add(stock)
        try:
            w = float(weight)
        except ValueError:
            continue
        holdings.append({"code": stock, "name": name, "weight": w})

    coverage = sum(h["weight"] for h in holdings)
    return {
        "etf": code,
        "source": "pocket.tw",
        "source_url": url,
        "fetched_at": now_taipei().isoformat(),
        "holdings": holdings,
        "holding_count": len(holdings),
        "weight_coverage_pct": round(coverage, 4),
        "note": (
            "Top disclosed holdings from pocket.tw SSR payload; "
            "not necessarily full NAV (cash/other names omitted)."
        ),
    }


def fetch_many(codes: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for code in codes:
        try:
            out[code.upper()] = fetch_holdings_pocket(code)
            logger.info(
                "holdings %s n=%s coverage=%.1f%%",
                code,
                out[code.upper()]["holding_count"],
                out[code.upper()]["weight_coverage_pct"],
            )
        except Exception as exc:
            logger.warning("holdings failed %s: %s", code, exc)
            out[code.upper()] = {
                "etf": code.upper(),
                "source": "pocket.tw",
                "source_url": pocket_url(code),
                "fetched_at": now_taipei().isoformat(),
                "holdings": [],
                "holding_count": 0,
                "weight_coverage_pct": 0.0,
                "error": str(exc),
            }
    return out
