# -*- coding: utf-8 -*-
import json
import re
import sys
from pathlib import Path

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.wantgoo.com/stock/etf/00685L/discount-premium",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def probe_page(code: str = "00685L") -> None:
    url = f"https://www.wantgoo.com/stock/etf/{code.lower()}/discount-premium"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    s = r.text
    print("page", r.status_code, len(s), url)
    Path("data/_wantgoo_page.html").write_text(s, encoding="utf-8")

    srcs = re.findall(r"""src=["']([^"']+)["']""", s)
    for u in srcs:
        if any(k in u.lower() for k in ("etf", "stock", "app", "main", "chunk", "bundle")):
            print("src", u)

    for pat in (
        r"""["'](/[^"']*(?:discount|premium|etf|inapi|api|chart)[^"']*)["']""",
        r"""["'](https?://[^"']*wantgoo[^"']*)["']""",
    ):
        for u in sorted(set(re.findall(pat, s, flags=re.I))):
            if len(u) < 200:
                print("hit", u)


def try_apis(code: str = "00685L") -> None:
    code_u = code.upper()
    code_l = code.lower()
    candidates = [
        f"https://www.wantgoo.com/inapi/stock/etf/{code_l}/discount-premium",
        f"https://www.wantgoo.com/inapi/stock/etf/{code_u}/discount-premium",
        f"https://www.wantgoo.com/inapi/etf/{code_l}/discount-premium",
        f"https://www.wantgoo.com/inapi/etf/discount-premium?stockNo={code_u}",
        f"https://www.wantgoo.com/stock/etf/{code_l}/discount-premium/data",
        f"https://www.wantgoo.com/api/stock/etf/{code_l}/discount-premium",
        f"https://www.wantgoo.com/inapi/stock/{code_u}/etf/discount-premium",
        f"https://www.wantgoo.com/inapi/agent/stock/etf/discount-premium?stockNo={code_u}",
        f"https://www.wantgoo.com/inapi/agent/stock/etf/{code_u}/discount-premium",
        f"https://www.wantgoo.com/stock/api/etf/discountpremium/{code_u}",
        f"https://www.wantgoo.com/inapi/etf/premium-discount/{code_u}",
        f"https://www.wantgoo.com/inapi/etf/premiumdiscount?code={code_u}",
    ]
    for url in candidates:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            ct = resp.headers.get("content-type", "")
            body = resp.text[:200].replace("\n", " ")
            print(f"{resp.status_code} {ct[:40]} {url} :: {body}")
            if resp.status_code == 200 and "json" in ct and resp.text.strip().startswith(("{", "[")):
                data = resp.json()
                out = Path("data") / f"_wantgoo_{code_u}.json"
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2)[:5000], encoding="utf-8")
                print("SAVED", out, "keys", list(data)[:20] if isinstance(data, dict) else type(data))
        except Exception as exc:
            print("ERR", url, exc)


def scan_js_for_endpoints() -> None:
    page = Path("data/_wantgoo_page.html")
    if not page.exists():
        return
    s = page.read_text(encoding="utf-8", errors="ignore")
    # inline scripts often contain api paths
    for m in re.finditer(r".{0,40}(discount|premium|折溢價).{0,80}", s, re.I):
        print("ctx", m.group(0).replace("\n", " ")[:140])


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "00685L"
    Path("data").mkdir(exist_ok=True)
    probe_page(code)
    print("--- apis ---")
    try_apis(code)
    print("--- scan ---")
    scan_js_for_endpoints()
