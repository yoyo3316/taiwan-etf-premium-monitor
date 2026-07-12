#!/usr/bin/env python3
"""Verify TWSE official all_etf.txt endpoint and field cross-check."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.monitor import compute_premium_discount
from src.twse_client import fetch_all_etf_raw, parse_all_etf


def main() -> int:
    payload = fetch_all_etf_raw()
    rows = parse_all_etf(payload)
    print(f"blocks={len(payload.get('a1') or [])} records={len(rows)}")

    ok = bad = skip = 0
    max_diff = 0.0
    for r in rows:
        calc = compute_premium_discount(r.get("market_price"), r.get("estimated_nav"))
        official = r.get("official_premium_discount_pct")
        if calc is None or official is None:
            skip += 1
            continue
        diff = abs(calc - official)
        max_diff = max(max_diff, diff)
        if diff > 0.05:
            bad += 1
            print(
                f"  anomaly {r['code']}: official={official} calc={calc:.4f} "
                f"diff={diff:.4f}"
            )
        else:
            ok += 1

    print(f"cross-check ok={ok} anomaly={bad} skip={skip} max_diff={max_diff:.4f}")
    if rows:
        s = rows[0]
        print(
            "sample:",
            s["code"],
            s["name"],
            s["market_price"],
            s["estimated_nav"],
            s["official_premium_discount_pct"],
            s["data_date"],
            s["data_time"],
        )
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
