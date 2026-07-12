# -*- coding: utf-8 -*-
"""Load Wantgoo page in Chromium and capture discount-premium-data API."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

code = "00685L"
url = f"https://www.wantgoo.com/stock/etf/{code.lower()}/discount-premium"
captured = []


def on_response(resp):
    u = resp.url
    if any(
        k in u
        for k in (
            "discount-premium-data",
            "daily-candlesticks",
            "daily-value-data",
            "basic-data",
        )
    ):
        try:
            body = resp.text()
        except Exception as exc:
            body = f"<err {exc}>"
        captured.append(
            {
                "url": u,
                "status": resp.status,
                "body_head": body[:300],
                "is_json": body.strip()[:1] in "[{",
            }
        )
        if body.strip()[:1] in "[{":
            Path("data/_wantgoo_browser_capture.json").write_text(
                body, encoding="utf-8"
            )
            print("SAVED", u, "status", resp.status, "len", len(body))


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        locale="zh-TW",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.on("response", on_response)
    print("goto", url)
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(5000)
    # try read table text
    try:
        table = page.locator("#discountPremiumTable").inner_text(timeout=5000)
        print("TABLE", table[:500])
    except Exception as exc:
        print("table err", exc)
    print("captured", len(captured))
    for c in captured:
        print(c["status"], c["url"], c["body_head"][:120].replace("\n", " "))
    browser.close()

if captured:
    Path("data/_wantgoo_capture_meta.json").write_text(
        json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8"
    )
