#!/usr/bin/env python3
"""Fetch WantGoo historical premium/discount for one or more ETF codes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.convergence import analyze_code, format_convergence_brief
from src.history_store import get_twse_series, save_wantgoo_history
from src.wantgoo_client import try_fetch_history


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch WantGoo ETF PD history")
    p.add_argument("codes", nargs="+", help="ETF codes e.g. 0050 00685L")
    p.add_argument("--threshold", type=float, default=3.0)
    args = p.parse_args()

    for code in args.codes:
        print(f"=== {code} ===")
        payload = try_fetch_history(code)
        if payload.get("rows"):
            save_wantgoo_history(payload)
            print(
                f"saved rows={payload.get('row_count')} "
                f"usable_pd={payload.get('usable_pd_count')}"
            )
        else:
            print("error:", payload.get("error"))
        analysis = analyze_code(
            code,
            wantgoo_payload=payload,
            twse_series=get_twse_series(code),
            abs_threshold=args.threshold,
        )
        print(format_convergence_brief(analysis))
        print("page:", payload.get("page_url"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
