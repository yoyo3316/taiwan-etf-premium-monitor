"""Next-day premium/discount convergence statistics.

Question answered (reference only, not a trading signal):
  When |折溢價| exceeds a threshold on day T, how often does it move
  closer to 0 on day T+1?

Uses WantGoo historical series when available; falls back to TWSE
self-collected end-of-day series.
"""

from __future__ import annotations

from typing import Any, Iterable


def _series_from_wantgoo(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    out = []
    for r in payload.get("rows") or []:
        pct = r.get("premium_discount_pct")
        if pct is None:
            continue
        out.append(
            {
                "date": r.get("date"),
                "premium_discount_pct": float(pct),
                "close": r.get("close"),
                "nav": r.get("nav"),
            }
        )
    out.sort(key=lambda x: x["date"] or "")
    return out


def compute_next_day_convergence(
    series: Iterable[dict[str, Any]],
    *,
    abs_threshold: float = 3.0,
    direction: str | None = None,
) -> dict[str, Any]:
    """Compute convergence stats for days beyond abs_threshold.

    direction:
      None = both sides
      "premium" = pct >= +threshold
      "discount" = pct <= -threshold
    """
    rows = [
        r
        for r in series
        if isinstance(r.get("premium_discount_pct"), (int, float)) and r.get("date")
    ]
    rows.sort(key=lambda x: x["date"])

    events: list[dict[str, Any]] = []
    for i in range(len(rows) - 1):
        cur = rows[i]
        nxt = rows[i + 1]
        pct = float(cur["premium_discount_pct"])
        nxt_pct = float(nxt["premium_discount_pct"])

        if direction == "premium":
            if pct < abs_threshold:
                continue
        elif direction == "discount":
            if pct > -abs_threshold:
                continue
        else:
            if abs(pct) < abs_threshold:
                continue

        # moved toward zero?
        moved_toward_zero = abs(nxt_pct) < abs(pct)
        # sign flip or within 1% = strong convergence
        strong = abs(nxt_pct) <= 1.0 or (pct > 0 > nxt_pct) or (pct < 0 < nxt_pct)
        # worsened (farther from zero)
        worsened = abs(nxt_pct) > abs(pct)
        change = nxt_pct - pct

        events.append(
            {
                "date": cur["date"],
                "next_date": nxt["date"],
                "pct": round(pct, 4),
                "next_pct": round(nxt_pct, 4),
                "change_pp": round(change, 4),
                "moved_toward_zero": moved_toward_zero,
                "strong_converge": strong,
                "worsened": worsened,
            }
        )

    n = len(events)
    if n == 0:
        return {
            "sample_size": 0,
            "abs_threshold": abs_threshold,
            "direction": direction or "both",
            "converge_rate": None,
            "strong_converge_rate": None,
            "worsen_rate": None,
            "avg_next_pct": None,
            "avg_abs_next_pct": None,
            "avg_abs_change_toward_zero": None,
            "label": "樣本不足",
            "events_tail": [],
        }

    conv = sum(1 for e in events if e["moved_toward_zero"])
    strong_n = sum(1 for e in events if e["strong_converge"])
    worse = sum(1 for e in events if e["worsened"])
    avg_next = sum(e["next_pct"] for e in events) / n
    avg_abs_next = sum(abs(e["next_pct"]) for e in events) / n
    # positive = abs shrink
    avg_toward = sum(abs(e["pct"]) - abs(e["next_pct"]) for e in events) / n

    rate = conv / n
    if rate >= 0.7:
        label = "歷史上較容易收斂"
    elif rate >= 0.5:
        label = "歷史上中性偏收斂"
    elif rate >= 0.35:
        label = "歷史上收斂不穩"
    else:
        label = "歷史上較不易收斂"

    return {
        "sample_size": n,
        "abs_threshold": abs_threshold,
        "direction": direction or "both",
        "converge_rate": round(rate, 4),
        "strong_converge_rate": round(strong_n / n, 4),
        "worsen_rate": round(worse / n, 4),
        "avg_next_pct": round(avg_next, 4),
        "avg_abs_next_pct": round(avg_abs_next, 4),
        "avg_abs_change_toward_zero": round(avg_toward, 4),
        "label": label,
        "events_tail": events[-10:],
    }


def analyze_code(
    code: str,
    *,
    wantgoo_payload: dict[str, Any] | None,
    twse_series: list[dict[str, Any]] | None,
    abs_threshold: float = 3.0,
    direction: str | None = None,
) -> dict[str, Any]:
    """Prefer WantGoo series; fall back to TWSE self history."""
    code = code.upper()
    wg_series = _series_from_wantgoo(wantgoo_payload)
    source = "wantgoo"
    series = wg_series
    if len(wg_series) < 5:
        series = twse_series or []
        source = "twse_eod" if series else "none"

    stats = compute_next_day_convergence(
        series, abs_threshold=abs_threshold, direction=direction
    )
    page = None
    if wantgoo_payload:
        page = wantgoo_payload.get("page_url")
    if not page:
        page = f"https://www.wantgoo.com/stock/etf/{code.lower()}/discount-premium"

    return {
        "code": code,
        "history_source": source,
        "history_points": len(series),
        "wantgoo_error": (wantgoo_payload or {}).get("error"),
        "wantgoo_page": page,
        "stats": stats,
        "disclaimer": (
            "隔日收斂統計僅供參考，非投資建議；不保證未來表現。"
            "即時告警仍以 TWSE 為準；歷史優先玩股網，失敗時用本系統累積之 TWSE 日結。"
        ),
    }


def format_convergence_brief(analysis: dict[str, Any] | None) -> str:
    if not analysis:
        return "隔日收斂：尚無資料"
    st = analysis.get("stats") or {}
    n = st.get("sample_size") or 0
    if n <= 0:
        err = analysis.get("wantgoo_error")
        src = analysis.get("history_source")
        if err:
            return f"隔日收斂：玩股網暫不可用（{err[:40]}），樣本不足"
        return f"隔日收斂：樣本不足（來源 {src}）"
    rate = st.get("converge_rate")
    label = st.get("label") or ""
    pct = f"{rate * 100:.0f}%" if isinstance(rate, float) else "—"
    return (
        f"隔日收斂參考：{label}｜收斂率 {pct}（n={n}，"
        f"來源 {analysis.get('history_source')}）"
    )
