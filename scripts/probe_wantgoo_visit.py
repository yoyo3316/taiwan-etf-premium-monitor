# -*- coding: utf-8 -*-
import hashlib
import json
import time

import requests

try:
    from curl_cffi import requests as cr

    USE_CFFI = True
except Exception:
    USE_CFFI = False

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

if USE_CFFI:
    s = cr.Session(impersonate="chrome124")
else:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

fp = hashlib.md5(f"probe-{time.time()}".encode()).hexdigest()
bid = hashlib.md5(f"bid-{time.time()}".encode()).hexdigest()[:16]
print("fp", fp, "bid", bid, "cffi", USE_CFFI)

# set cookies
for domain in [".wantgoo.com", "www.wantgoo.com"]:
    try:
        s.cookies.set("client_fingerprint", fp, domain=domain)
        s.cookies.set("BID", bid, domain=domain)
    except Exception:
        pass

# visit track
visit_url = (
    f"https://www.wantgoo.com/visit?load={fp}_{bid}_anonymous_"
    f"/stock/etf/00685l/discount-premium"
)
r = s.get(visit_url, headers={"User-Agent": UA, "Referer": "https://www.wantgoo.com/"}, timeout=20)
print("visit", r.status_code, r.text[:100], dict(s.cookies))

page = s.get(
    "https://www.wantgoo.com/stock/etf/00685l/discount-premium",
    headers={"User-Agent": UA},
    timeout=30,
)
print("page", page.status_code, len(page.text))

# try several codes and endpoints
codes = ["00685l", "00685L", "0050", "0050.TW"]
endpoints = [
    "/stock/etf/{c}/discount-premium-data",
    "/stock/etf/{c}/daily-value-data",
    "/stock/etf/{c}/basic-data",
    "/investrue/{c}/daily-candlesticks?after=1609459200000",
    "/investrue/{c}/commoditystate",
]
for c in codes:
    for ep in endpoints:
        url = "https://www.wantgoo.com" + ep.format(c=c)
        r = s.get(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.wantgoo.com/stock/etf/{c}/discount-premium",
                "Origin": "https://www.wantgoo.com",
            },
            timeout=20,
        )
        snippet = r.text[:80].replace("\n", " ")
        print(r.status_code, ep.format(c=c), snippet)
        if r.status_code == 200 and r.text.strip()[:1] in "[{":
            data = r.json()
            print("  SUCCESS", type(data), str(data)[:200])
            with open("data/_wantgoo_success.json", "w", encoding="utf-8") as f:
                json.dump(data[:5] if isinstance(data, list) else data, f, ensure_ascii=False, indent=2)
            raise SystemExit(0)

print("no success")
