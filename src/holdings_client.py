"""Fetch ETF disclosed holdings for overlap verification.

Primary source (weekly job):
  CMoney ETF fundholding (full disclosed shareholding list)
  Page: https://www.cmoney.tw/etf/tw/{code}/fundholding
  API:  POST https://dtno.cmoney.tw/app/v2/dtno/JsonCsv
        DtNo=59449513 (tw getShareholding), guest Bearer from page NUXT.

Fallback:
  pocket.tw top-holdings SSR embed (usually ~10 names) if CMoney fails.

Notes:
  - CMoney typically returns full disclosed constituents with high weight coverage.
  - Metrics report coverage and weighted_min overlap.
  - Same-index ETFs (e.g. 0050 / 006208 both track Taiwan 50) are annotated
    separately as official index identity (full equity universe match).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests
import urllib3

from .market_hours import now_taipei

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

CMONEY_DTNO = "59449513"  # tw getShareholding
CMONEY_API = "https://dtno.cmoney.tw/app/v2/dtno/JsonCsv"
_TOKEN_CACHE: dict[str, Any] = {"at": None, "fetched_at": 0.0}


def cmoney_url(code: str) -> str:
    return f"https://www.cmoney.tw/etf/tw/{code.upper()}/fundholding"


def pocket_url(code: str) -> str:
    return f"https://www.pocket.tw/etf/tw/{code.lower()}"


def _get_cmoney_guest_token(timeout: int = 30) -> str:
    """Extract guest access token from any CMoney ETF fundholding page NUXT."""
    now = time.time()
    cached = _TOKEN_CACHE.get("at")
    # Guest tokens typically last ~24h; refresh every 30 min to be safe.
    if cached and (now - float(_TOKEN_CACHE.get("fetched_at") or 0)) < 1800:
        return str(cached)

    url = "https://www.cmoney.tw/etf/tw/0050/fundholding"
    resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
    resp.raise_for_status()
    m = re.search(r'at:"(eyJ[^"]+)"', resp.text)
    if not m:
        raise RuntimeError("CMoney guest token not found in page NUXT payload")
    at = m.group(1)
    _TOKEN_CACHE["at"] = at
    _TOKEN_CACHE["fetched_at"] = now
    return at


def fetch_holdings_cmoney(code: str, timeout: int = 30) -> dict[str, Any]:
    """Return full disclosed holdings for one ETF from CMoney JsonCsv API."""
    code = code.strip().upper()
    page_url = cmoney_url(code)
    at = _get_cmoney_guest_token(timeout=timeout)

    # Body shape matches Nuxt Bt(): {Dtno, Params, FilterNo}
    # (Params NOT ParamStr — wrong key returns stale default data.)
    body = {
        "Dtno": int(CMONEY_DTNO),
        "Params": (
            f"AssignID={code};MTPeriod=0;DTMode=0;DTRange=1;DTOrder=1;MajorTable=M722;"
        ),
        "FilterNo": "0",
    }
    headers = {
        **HEADERS,
        "Authorization": f"Bearer {at}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.cmoney.tw",
        "Referer": page_url,
        "cmoneyapi-trace-context": (
            '{"platform":3,"appVersion":"1.0.0","osName":"Windows 10"}'
        ),
    }
    resp = requests.post(
        CMONEY_API, json=body, headers=headers, timeout=timeout, verify=False
    )
    if resp.status_code == 401:
        # Token may have expired mid-run — force refresh once.
        _TOKEN_CACHE["at"] = None
        _TOKEN_CACHE["fetched_at"] = 0.0
        at = _get_cmoney_guest_token(timeout=timeout)
        headers["Authorization"] = f"Bearer {at}"
        resp = requests.post(
            CMONEY_API, json=body, headers=headers, timeout=timeout, verify=False
        )
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("rows") or []
    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected CMoney response for {code}: no rows")

    holdings: list[dict[str, Any]] = []
    seen: set[str] = set()
    as_of: str | None = None
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        # columns: 日期, 標的代號, 標的名稱, 權重(%), 持有數, 單位
        date_s = str(row[0] or "").strip()
        stock = str(row[1] or "").strip().upper()
        name = str(row[2] or "").strip()
        try:
            w = float(row[3])
        except (TypeError, ValueError):
            continue
        if not stock or stock == code or stock in seen:
            continue
        if w <= 0:
            continue
        seen.add(stock)
        holdings.append({"code": stock, "name": name, "weight": w})
        if date_s and as_of is None:
            as_of = date_s

    if not holdings:
        raise RuntimeError(f"CMoney returned empty holdings for {code}")

    coverage = sum(h["weight"] for h in holdings)
    return {
        "etf": code,
        "source": "cmoney.tw",
        "source_url": page_url,
        "fetched_at": now_taipei().isoformat(),
        "as_of": as_of,
        "holdings": holdings,
        "holding_count": len(holdings),
        "weight_coverage_pct": round(coverage, 4),
        "note": (
            "Full disclosed shareholding from CMoney fundholding API "
            f"(DtNo={CMONEY_DTNO}); coverage may be <100% due to cash/other."
        ),
    }


def fetch_holdings_pocket(code: str, timeout: int = 30) -> dict[str, Any]:
    """Return holdings dict for one ETF from pocket.tw page embed (fallback)."""
    code = code.strip().upper()
    url = pocket_url(code)
    resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
    resp.raise_for_status()
    text = resp.text

    items = re.findall(
        r'\{name:"([^"]+)",weight:"([0-9.]+)",code:"([0-9A-Z]{4,6})"',
        text,
    )
    holdings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, weight, stock in items:
        stock = stock.upper()
        if stock in seen or stock == code:
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


def fetch_holdings(code: str, timeout: int = 30) -> dict[str, Any]:
    """Primary: CMoney full holdings; fallback: pocket.tw top list."""
    try:
        return fetch_holdings_cmoney(code, timeout=timeout)
    except Exception as exc:
        logger.warning("CMoney holdings failed %s: %s — trying pocket.tw", code, exc)
        out = fetch_holdings_pocket(code, timeout=timeout)
        out["fallback_from"] = "cmoney.tw"
        out["cmoney_error"] = str(exc)
        return out


def fetch_many(codes: list[str], pause_sec: float = 0.35) -> dict[str, dict[str, Any]]:
    """Fetch holdings for many codes; prefer CMoney, fall back to pocket."""
    out: dict[str, dict[str, Any]] = {}
    for i, code in enumerate(codes):
        try:
            out[code.upper()] = fetch_holdings(code)
            h = out[code.upper()]
            logger.info(
                "holdings %s source=%s n=%s coverage=%.1f%%",
                code,
                h.get("source"),
                h.get("holding_count"),
                h.get("weight_coverage_pct") or 0,
            )
        except Exception as exc:
            logger.warning("holdings failed %s: %s", code, exc)
            out[code.upper()] = {
                "etf": code.upper(),
                "source": "cmoney.tw",
                "source_url": cmoney_url(code),
                "fetched_at": now_taipei().isoformat(),
                "holdings": [],
                "holding_count": 0,
                "weight_coverage_pct": 0.0,
                "error": str(exc),
            }
        if pause_sec and i + 1 < len(codes):
            time.sleep(pause_sec)
    return out
