# -*- coding: utf-8 -*-
import re

import requests

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
page = requests.get(
    "https://www.wantgoo.com/stock/etf/00685l/discount-premium",
    headers=H,
    timeout=30,
).text
srcs = re.findall(r"""(?:src)=["']?(/[^"'>\s]+\.js[^"'>\s]*)""", page)
# also common libs
extra = [
    "/lib/jquery-chefextend/1.8.20/jquery-chefextend.min.js",
]
paths = [s.split("?")[0] for s in srcs] + extra
seen = set()
for path in paths:
    if path in seen:
        continue
    seen.add(path)
    url = "https://www.wantgoo.com" + path
    try:
        t = requests.get(url, headers=H, timeout=25).text
    except Exception as exc:
        continue
    for key in [
        "ajaxSetup",
        "ajaxPrefilter",
        "beforeSend",
        "http.default.settings",
        "RequestVerification",
        "X-XSRF",
        "xsrf",
        "antiforgery",
        "wantgoo-",
        "wg-",
        "dataType:\"json\"",
        "dataType:'json'",
    ]:
        if key.lower() in t.lower() or key in t:
            # filter noise
            if key in ("beforeSend",) and t.count(key) > 50:
                continue
            print("HIT", key, path, "count", t.lower().count(key.lower()))
            i = t.lower().find(key.lower())
            print(" ", t[max(0, i - 60) : i + 180].replace("\n", " ")[:240])

# try APIs that return HTML page with data embedded - net-value list
for api in [
    "https://www.wantgoo.com/stock/etf/net-value",
    "https://www.wantgoo.com/stock/etf/net-value-data",
    "https://www.wantgoo.com/inapi/etf/net-value",
]:
    r = requests.get(api, headers={**H, "Accept": "application/json,*/*"}, timeout=20)
    print("API", r.status_code, api, r.headers.get("content-type"), r.text[:100].replace("\n", " "))
