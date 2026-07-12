# -*- coding: utf-8 -*-
import re
from pathlib import Path

s = Path("data/_wantgoo_dp.js").read_text(encoding="utf-8", errors="ignore")
print("len", len(s))
print(s[:2000])
print("----")
found = set()
for m in re.finditer(r"""['"]([^'"]{4,160})['"]""", s):
    u = m.group(1)
    low = u.lower()
    if any(
        k in low
        for k in (
            "api",
            "inapi",
            "discount",
            "premium",
            "etf",
            "chart",
            "http",
            "stock",
            "ajax",
            "date",
        )
    ):
        found.add(u)
for u in sorted(found):
    print("STR", u)

for pat in [
    "inapi",
    "discount",
    "premium",
    "getJSON",
    "ajax",
    "fetch",
    "stockNo",
    "/stock/",
    "url:",
]:
    idx = 0
    c = 0
    while c < 5:
        i = s.find(pat, idx)
        if i < 0:
            break
        print("CTX", pat, ":", s[max(0, i - 60) : i + 120].replace("\n", " "))
        idx = i + len(pat)
        c += 1
