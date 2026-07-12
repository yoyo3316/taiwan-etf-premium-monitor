# -*- coding: utf-8 -*-
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

urls = [
    "https://www.wantgoo.com/stock/etf/0050/discount-premium",
    "https://www.wantgoo.com/stock/etf/00685l/discount-premium",
    "https://www.wantgoo.com/stock/etf/net-value",
]


def capture(start_url: str):
    hits = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            u = resp.url
            if "wantgoo.com" not in u:
                return
            # skip static assets
            if any(u.endswith(ext) for ext in (".js", ".css", ".png", ".svg", ".woff2", ".ico")):
                return
            if "/lib/" in u or "/cdn-cgi/" in u:
                return
            try:
                ct = resp.headers.get("content-type", "")
                text = ""
                if "json" in ct or "text/plain" in ct or "javascript" in ct:
                    text = resp.text()[:200]
                hits.append({"url": u, "status": resp.status, "ct": ct, "head": text})
            except Exception as exc:
                hits.append({"url": u, "status": resp.status, "err": str(exc)})

        page.on("response", on_response)
        print("===", start_url)
        page.goto(start_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
        browser.close()
    for h in hits:
        print(h["status"], h.get("ct", "")[:25], h["url"][:120], (h.get("head") or "")[:80].replace("\n", " "))
    return hits


all_hits = []
for u in urls:
    all_hits.extend(capture(u))
Path("data/_wantgoo_all_net.json").write_text(
    json.dumps(all_hits, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("saved", len(all_hits))
