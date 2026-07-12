"""Core premium/discount evaluation and monitoring orchestration."""

from __future__ import annotations

import logging
from typing import Any

from .config import PREMARKET_DATA_MAX_AGE_MINUTES, Settings, TWSE_INDICATOR_PAGE
from .market_hours import (
    is_premarket_watch,
    is_stale,
    now_taipei,
    parse_twse_datetime,
    session_status,
)
from .state import (
    active_alerts,
    append_history,
    clear_all_locks_for_code,
    is_locked,
    load_alert_state,
    save_alert_state,
    set_lock,
)
from .storage import save_snapshot
from .telegram_notify import notify_alert
from .twse_client import fetch_etf_records

logger = logging.getLogger(__name__)


def compute_premium_discount(
    market_price: float | None, estimated_nav: float | None
) -> float | None:
    """(market_price - estimated_nav) / estimated_nav * 100"""
    if market_price is None or estimated_nav is None:
        return None
    if estimated_nav <= 0 or market_price <= 0:
        return None
    return (market_price - estimated_nav) / estimated_nav * 100.0


def evaluate_record(
    raw: dict[str, Any],
    *,
    premium_threshold: float,
    discount_threshold: float,
    data_max_age_minutes: int,
    cross_check_tolerance_pp: float,
    now=None,
) -> dict[str, Any]:
    """Evaluate a single ETF row for validity, staleness, and alert direction."""
    now = now or now_taipei()
    market_price = raw.get("market_price")
    est_nav = raw.get("estimated_nav")
    official_pd = raw.get("official_premium_discount_pct")
    calc_pd = compute_premium_discount(market_price, est_nav)

    data_dt = parse_twse_datetime(raw.get("data_date"), raw.get("data_time"))
    data_time_iso = data_dt.isoformat() if data_dt else None
    # Pre-open watch may still use prior-session TWSE figures.
    effective_max_age = data_max_age_minutes
    if is_premarket_watch(now):
        effective_max_age = max(data_max_age_minutes, PREMARKET_DATA_MAX_AGE_MINUTES)
    stale = is_stale(data_dt, effective_max_age, now=now)

    status = "ok"
    issues: list[str] = []

    if market_price is None:
        status = "missing"
        issues.append("缺市價")
    elif market_price <= 0:
        # TWSE sometimes publishes 0.00 when no trade / not available
        status = "invalid"
        issues.append("市價<=0")
        market_price = None
        calc_pd = None

    if est_nav is None:
        status = "missing" if status == "ok" else status
        issues.append("缺預估淨值")
    elif est_nav <= 0:
        status = "invalid"
        issues.append("預估淨值<=0")
        calc_pd = None

    if calc_pd is None and status == "ok":
        status = "missing"
        issues.append("無法計算折溢價")

    if calc_pd is not None and official_pd is not None:
        diff = abs(calc_pd - official_pd)
        if diff > cross_check_tolerance_pp:
            status = "anomaly"
            issues.append(
                f"交叉驗證誤差 {diff:.4f}pp > {cross_check_tolerance_pp}pp"
            )

    if status == "ok" and stale:
        status = "stale"
        issues.append(f"資料超過 {effective_max_age} 分鐘")
    elif status == "ok" and is_premarket_watch(now):
        issues.append("盤前監控（可能為前一交易日資料）")

    # Prefer calculated value; fall back to official if calc missing but official present
    pd_pct = calc_pd if calc_pd is not None else official_pd

    alert_direction = None
    if status == "ok" and pd_pct is not None:
        if pd_pct >= premium_threshold:
            alert_direction = "premium"
        elif pd_pct <= discount_threshold:
            alert_direction = "discount"

    return {
        **{k: v for k, v in raw.items() if k != "raw"},
        "premium_discount_pct": round(pd_pct, 4) if pd_pct is not None else None,
        "calculated_premium_discount_pct": (
            round(calc_pd, 4) if calc_pd is not None else None
        ),
        "official_premium_discount_pct": official_pd,
        "cross_check_diff_pp": (
            round(abs(calc_pd - official_pd), 4)
            if calc_pd is not None and official_pd is not None
            else None
        ),
        "data_time_iso": data_time_iso,
        "is_stale": stale,
        "status": status,
        "issues": issues,
        "alert_direction": alert_direction,
        "source_link": TWSE_INDICATOR_PAGE,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    total = len(rows)
    valid = sum(1 for r in rows if r.get("status") == "ok")
    anomaly = sum(1 for r in rows if r.get("status") == "anomaly")
    stale = sum(1 for r in rows if r.get("status") == "stale")
    missing = sum(1 for r in rows if r.get("status") in ("missing", "invalid"))
    premium_alerts = sum(1 for r in rows if r.get("alert_direction") == "premium")
    discount_alerts = sum(1 for r in rows if r.get("alert_direction") == "discount")
    return {
        "total": total,
        "valid": valid,
        "anomaly": anomaly,
        "stale": stale,
        "missing_or_invalid": missing,
        "premium_alert_candidates": premium_alerts,
        "discount_alert_candidates": discount_alerts,
    }


def run_monitor(
    settings: Settings | None = None,
    *,
    send_notifications: bool = True,
    persist: bool = True,
    force_outside_session: bool = False,
) -> dict[str, Any]:
    """Run one monitoring cycle.

    Notifications are only sent during market session (Asia/Taipei), unless
    force_outside_session=True (for testing). Snapshot is always updated when
    persist=True so the dashboard has data outside market hours.
    """
    settings = settings or Settings.from_env()
    now = now_taipei()
    sess = session_status(now)

    logger.info(
        "Monitor cycle start now=%s session=%s in_session=%s",
        now.isoformat(),
        sess["state"],
        sess["in_session"],
    )

    raw_rows, meta = fetch_etf_records()
    evaluated = [
        evaluate_record(
            r,
            premium_threshold=settings.premium_threshold,
            discount_threshold=settings.discount_threshold,
            data_max_age_minutes=settings.data_max_age_minutes,
            cross_check_tolerance_pp=settings.cross_check_tolerance_pp,
            now=now,
        )
        for r in raw_rows
    ]

    summary = summarize(evaluated)
    state = load_alert_state()
    notifications_sent: list[dict[str, Any]] = []
    locks_cleared: list[str] = []

    can_notify = send_notifications and (
        sess["in_session"] or force_outside_session
    )

    # Release locks when ETF returns to normal range (valid data only)
    for row in evaluated:
        code = row["code"]
        pd_pct = row.get("premium_discount_pct")
        if row.get("status") != "ok" or pd_pct is None:
            continue
        within_normal = (
            settings.discount_threshold < pd_pct < settings.premium_threshold
        )
        if within_normal:
            removed = clear_all_locks_for_code(state, code)
            if removed:
                locks_cleared.append(code)

    # Fire alerts with one-shot lock per direction
    if can_notify:
        for row in evaluated:
            direction = row.get("alert_direction")
            if not direction:
                continue
            # Extra guards already in status==ok for alert_direction
            if row.get("status") != "ok":
                continue
            if is_locked(state, row["code"], direction):
                logger.debug(
                    "Skip notify %s %s (already locked)", row["code"], direction
                )
                continue

            ok = notify_alert(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                row,
                dashboard_url=settings.dashboard_url,
            )
            if ok or (
                not settings.telegram_bot_token or not settings.telegram_chat_id
            ):
                # Always set lock after attempted send when credentials missing
                # in dry-run? Better: only lock on successful send.
                # If no credentials, do not lock so real deploy can notify later.
                if ok:
                    set_lock(
                        state,
                        code=row["code"],
                        name=row.get("name") or "",
                        direction=direction,
                        rate=float(row["premium_discount_pct"]),
                        market_price=row.get("market_price"),
                        estimated_nav=row.get("estimated_nav"),
                    )
                    entry = {
                        "code": row["code"],
                        "name": row.get("name"),
                        "direction": direction,
                        "rate": row.get("premium_discount_pct"),
                        "notified_at": now.isoformat(),
                        "data_time": row.get("data_time_iso"),
                    }
                    append_history(state, entry)
                    notifications_sent.append(entry)
    else:
        logger.info(
            "Notifications suppressed (outside session or disabled). "
            "session=%s",
            sess["state"],
        )

    alerts = active_alerts(state)

    snapshot = {
        "fetched_at": now.isoformat(),
        "timezone": "Asia/Taipei",
        "session": sess,
        "thresholds": {
            "premium": settings.premium_threshold,
            "discount": settings.discount_threshold,
            "data_max_age_minutes": settings.data_max_age_minutes,
            "cross_check_tolerance_pp": settings.cross_check_tolerance_pp,
        },
        "source": meta,
        "summary": summary,
        "notifications_sent": notifications_sent,
        "locks_cleared": locks_cleared,
        "active_alerts": alerts,
        "etfs": evaluated,
        "disclaimer": (
            "本系統僅為輔助監控與告警，不可視為即時交易或自動下單系統。"
            "資料來源為臺灣證券交易所基本市況報導，預估淨值由投信提供僅供參考。"
        ),
    }

    if persist:
        save_snapshot(snapshot)
        save_alert_state(state)
        logger.info(
            "Snapshot saved: total=%s valid=%s notified=%s",
            summary["total"],
            summary["valid"],
            len(notifications_sent),
        )

    return snapshot
