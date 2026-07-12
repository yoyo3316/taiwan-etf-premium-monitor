#!/usr/bin/env python3
"""CLI entry point for GitHub Actions / local monitor runs."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running without installing the package
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings  # noqa: E402
from src.monitor import run_monitor  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Taiwan ETF premium/discount monitor (TWSE official data)"
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Fetch and evaluate only; do not send Telegram messages",
    )
    parser.add_argument(
        "--force-notify",
        action="store_true",
        help="Allow notifications even outside market session (testing only)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write data/latest.json or alert_state.json",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    snapshot = run_monitor(
        settings,
        send_notifications=not args.no_notify,
        persist=not args.no_persist,
        force_outside_session=args.force_notify,
    )

    summary = snapshot.get("summary") or {}
    session = snapshot.get("session") or {}
    print(
        f"OK fetched_at={snapshot.get('fetched_at')} "
        f"session={session.get('state')} "
        f"total={summary.get('total')} valid={summary.get('valid')} "
        f"anomaly={summary.get('anomaly')} stale={summary.get('stale')} "
        f"notified={len(snapshot.get('notifications_sent') or [])}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("Monitor failed: %s", exc)
        raise SystemExit(1) from exc
