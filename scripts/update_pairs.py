#!/usr/bin/env python3
"""Weekly job: fetch holdings, verify overlap, write pair list."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import DATA_DIR, ensure_data_dir
from src.holdings_client import fetch_many
from src.pair_builder import PAIR_UNIVERSE, build_pairs_payload
from src.twse_client import fetch_etf_records

logger = logging.getLogger(__name__)

PAIRS_DIR = DATA_DIR / "pairs"
HOLDINGS_PATH = PAIRS_DIR / "holdings_snapshot.json"
PAIRS_PATH = PAIRS_DIR / "etf_pairs.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Update ETF pair overlap list")
    parser.add_argument(
        "--codes",
        nargs="*",
        default=None,
        help="ETF codes (default: PAIR_UNIVERSE)",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Skip attaching live TWSE premium gap",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    ensure_data_dir()
    PAIRS_DIR.mkdir(parents=True, exist_ok=True)

    codes = args.codes or PAIR_UNIVERSE
    logger.info("Fetching holdings for %s ETFs…", len(codes))
    holdings = fetch_many(list(codes))
    HOLDINGS_PATH.write_text(
        json.dumps(holdings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote %s", HOLDINGS_PATH)

    etf_rows = None
    if not args.no_live:
        try:
            etf_rows, _meta = fetch_etf_records()
            logger.info("Live TWSE rows: %s", len(etf_rows))
        except Exception as exc:
            logger.warning("Live TWSE fetch failed: %s", exc)

    payload = build_pairs_payload(holdings, etf_rows=etf_rows)
    PAIRS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Wrote %s pairs=%s",
        PAIRS_PATH,
        payload.get("pair_count"),
    )
    for p in (payload.get("pairs") or [])[:12]:
        print(
            f"{p['a']}/{p['b']} same_index={p.get('same_index')} "
            f"wmin={p.get('weighted_min_overlap_pct')} "
            f"within={p.get('within_top_overlap_pct')} "
            f"gap={p.get('premium_gap_a_minus_b')} "
            f"reason={p.get('qualify_reason')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
