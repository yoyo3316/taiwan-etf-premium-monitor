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

# collect all script srcs including lib
srcs = re.findall(r"""(?:src|href)=["']?(/[^"'>\s]+\.js[^"'>\s]*)""", page)
print("js count", len(srcs))
for src in srcs:
    path = src.split("?")[0]
    url = "https://www.wantgoo.com" + path
    try:
        t = requests.get(url, headers=H, timeout=25).text
    except Exception as exc:
        print("fail", path, exc)
        continue
    if "http.default" in t or "$.http" in t and "settings" in t:
        # only print if likely configures settings
        if re.search(r"http\.default\.settings\s*=", t) or re.search(
            r"http\.default\.settings", t
        ):
            print("FOUND settings assignment in", path, len(t))
            for m in re.finditer(r".{0,40}http\.default\.settings.{0,200}", t):
                print(m.group(0).replace("\n", " ")[:280])
        elif "http.default" in t:
            print("mention http.default", path)
            i = t.find("http.default")
            print(t[max(0, i - 40) : i + 160].replace("\n", " "))

# search page inline
for m in re.finditer(r".{0,30}http\.default\.settings.{0,250}", page):
    print("PAGE", m.group(0).replace("\n", " ")[:300])

# Try common wantgoo middleware headers used in community scrapers
s = requests.Session()
s.headers.update(H)
s.get("https://www.wantgoo.com/stock/etf/00685l/discount-premium", timeout=30)

# fingerprint-like cookies sometimes required
s.cookies.set("client_fingerprint", "testfp1234567890", domain="www.wantgoo.com")
s.cookies.set("BID", "testbid", domain="www.wantgoo.com")

extra_headers_variants = [
    {},
    {"RequestVerificationToken": "x"},
    {"x-requested-with": "XMLHttpRequest"},
    {"accept": "application/json"},
    {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "x-requested-with": "XMLHttpRequest",
        "referer": "https://www.wantgoo.com/stock/etf/00685l/discount-premium",
    },
]

api = "https://www.wantgoo.com/stock/etf/00685l/discount-premium-data"
for i, eh in enumerate(extra_headers_variants):
    r = s.get(api, headers=eh, timeout=20)
    print(i, r.status_code, r.text[:60], eh)
