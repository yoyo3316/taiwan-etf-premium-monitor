# -*- coding: utf-8 -*-
import re
from pathlib import Path

import requests

H = {"User-Agent": "Mozilla/5.0"}
page = requests.get(
    "https://www.wantgoo.com/stock/etf/00685l/discount-premium",
    headers=H,
    timeout=30,
).text
srcs = re.findall(r"""src=["']?(/js/[^"'>\s]+)""", page)
print("scripts", len(srcs))
for src in srcs:
    url = "https://www.wantgoo.com" + src.split("?")[0]
    try:
        t = requests.get(url, headers=H, timeout=20).text
    except Exception as exc:
        print("fail", src, exc)
        continue
    if any(
        k in t
        for k in (
            "http.default",
            "default.settings",
            "RequestVerificationToken",
            "beforeSend",
            "client_fingerprint",
            "CryptoJS",
        )
    ):
        print("HIT", src, len(t))
        for pat in [
            "http.default",
            "beforeSend",
            "headers",
            "fingerprint",
            "BID",
            "client_fingerprint",
            "CryptoJS",
            "token",
            "dataType",
        ]:
            i = t.find(pat)
            if i >= 0:
                print(" ", pat, t[max(0, i - 50) : i + 140].replace("\n", " ")[:200])

# also search inline scripts in page
print("--- page inline ---")
for pat in ["http.default", "client_fingerprint", "CryptoJS", "beforeSend"]:
    i = page.find(pat)
    if i >= 0:
        print(pat, page[max(0, i - 60) : i + 160].replace("\n", " ")[:220])
