"""Unit tests for premium/discount logic (no network)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.monitor import compute_premium_discount, evaluate_record
from src.twse_client import parse_all_etf

TZ = ZoneInfo("Asia/Taipei")


def test_compute_premium_discount():
    assert abs(compute_premium_discount(103, 100) - 3.0) < 1e-9
    assert abs(compute_premium_discount(97, 100) - (-3.0)) < 1e-9
    assert compute_premium_discount(100, 0) is None
    assert compute_premium_discount(0, 100) is None
    assert compute_premium_discount(None, 100) is None


def test_evaluate_cross_check_anomaly():
    now = datetime(2026, 7, 10, 10, 0, 0, tzinfo=TZ)
    row = {
        "code": "TEST",
        "name": "測試",
        "market_price": 100.0,
        "estimated_nav": 100.0,
        "official_premium_discount_pct": 1.0,  # mismatch vs calc 0
        "data_date": "20260710",
        "data_time": "10:00:00",
    }
    out = evaluate_record(
        row,
        premium_threshold=3.0,
        discount_threshold=-3.0,
        data_max_age_minutes=10,
        cross_check_tolerance_pp=0.05,
        now=now,
    )
    assert out["status"] == "anomaly"
    assert out["alert_direction"] is None


def test_evaluate_premium_alert():
    now = datetime(2026, 7, 10, 10, 0, 0, tzinfo=TZ)
    row = {
        "code": "0050",
        "name": "元大台灣50",
        "market_price": 103.5,
        "estimated_nav": 100.0,
        "official_premium_discount_pct": 3.5,
        "data_date": "20260710",
        "data_time": "10:00:00",
    }
    out = evaluate_record(
        row,
        premium_threshold=3.0,
        discount_threshold=-3.0,
        data_max_age_minutes=10,
        cross_check_tolerance_pp=0.05,
        now=now,
    )
    assert out["status"] == "ok"
    assert out["alert_direction"] == "premium"


def test_parse_all_etf_minimal():
    payload = {
        "a1": [
            {
                "refURL": "https://example.com",
                "msgArray": [
                    {
                        "a": "0050",
                        "b": "元大台灣50",
                        "c": "1",
                        "d": "0",
                        "e": "100",
                        "f": "99",
                        "g": "1.01",
                        "h": "98",
                        "i": "20260710",
                        "j": "10:00:00",
                        "k": "1",
                    }
                ],
            }
        ]
    }
    rows = parse_all_etf(payload)
    assert len(rows) == 1
    assert rows[0]["code"] == "0050"
    assert rows[0]["market_price"] == 100.0


if __name__ == "__main__":
    test_compute_premium_discount()
    test_evaluate_cross_check_anomaly()
    test_evaluate_premium_alert()
    test_parse_all_etf_minimal()
    print("all tests passed")
