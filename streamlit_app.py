"""Streamlit dashboard for Taiwan ETF premium/discount monitoring.

Designed for quick scanning: status first, then rankings, then full list.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings
from src.market_hours import now_taipei, session_status
from src.monitor import evaluate_record, summarize
from src.state import active_alerts, load_alert_state
from src.storage import load_settings_file, load_snapshot, save_settings_file
from src.twse_client import fetch_etf_records

st.set_page_config(
    page_title="台灣 ETF 折溢價監控",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Visual style
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
  /* Tighten vertical spacing */
  .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }
  h1 { font-size: 1.65rem !important; margin-bottom: 0.25rem !important; }
  h2, h3 { margin-top: 0.6rem !important; }

  /* Status chips */
  .chip {
    display: inline-block;
    padding: 0.28rem 0.75rem;
    border-radius: 999px;
    font-weight: 600;
    font-size: 0.92rem;
    margin-right: 0.4rem;
    margin-bottom: 0.35rem;
  }
  .chip-ok { background: #dcfce7; color: #166534; }
  .chip-warn { background: #fef3c7; color: #92400e; }
  .chip-bad { background: #fee2e2; color: #991b1b; }
  .chip-info { background: #e0f2fe; color: #075985; }
  .chip-muted { background: #f3f4f6; color: #374151; }

  .subline { color: #6b7280; font-size: 0.9rem; margin-bottom: 0.75rem; }
  .hint { color: #6b7280; font-size: 0.85rem; }

  /* Metric cards via st.metric already; soft section cards */
  .section-card {
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 0.9rem 1rem;
    background: #fafafa;
    margin-bottom: 0.75rem;
  }
  .section-title {
    font-weight: 700;
    font-size: 1.05rem;
    margin-bottom: 0.35rem;
  }
  .pd-pos { color: #dc2626; font-weight: 700; }
  .pd-neg { color: #2563eb; font-weight: 700; }
  .pd-zero { color: #6b7280; font-weight: 600; }

  /* Dataframe header contrast */
  [data-testid="stDataFrame"] { font-size: 0.95rem; }

  /* Sidebar cleaner */
  section[data-testid="stSidebar"] { background: #f8fafc; }
</style>
""",
    unsafe_allow_html=True,
)

STATUS_LABELS = {
    "ok": "有效",
    "stale": "逾時",
    "anomaly": "異常",
    "missing": "缺值",
    "invalid": "無效",
}

STATUS_EMOJI = {
    "ok": "🟢",
    "stale": "🟡",
    "anomaly": "🟠",
    "missing": "🔴",
    "invalid": "🔴",
}


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    s = str(iso).replace("T", " ")
    # 2026-07-10 16:59:57+08:00 -> 07-10 16:59
    if len(s) >= 16:
        return s[5:16]
    return s[:19]


def _fmt_pct(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_price(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        x = float(v)
        if x >= 100:
            return f"{x:.2f}"
        return f"{x:.3f}".rstrip("0").rstrip(".") if x < 10 else f"{x:.2f}"
    except (TypeError, ValueError):
        return "—"


def _short_name(name: str, n: int = 18) -> str:
    name = (name or "").strip()
    if len(name) <= n:
        return name
    return name[: n - 1] + "…"


def _status_banner(sess: dict, snapshot: dict | None) -> None:
    state = sess.get("state")
    in_session = sess.get("in_session")
    now_s = _fmt_time(sess.get("now"))
    window = sess.get("session", "08:50–13:30")

    if in_session and state == "pre_market":
        chip_cls, chip_txt = "chip-info", f"盤前監控 {window}"
    elif in_session:
        chip_cls, chip_txt = "chip-ok", f"交易時段 {window}"
    elif state == "closed_day":
        chip_cls, chip_txt = "chip-bad", "休市日"
    else:
        chip_cls, chip_txt = "chip-warn", sess.get("reason") or "非監控時段"

    st.markdown(
        f'<span class="chip {chip_cls}">{chip_txt}</span>'
        f'<span class="chip chip-muted">現在 {now_s}</span>'
        f'<span class="chip chip-muted">門檻 溢價≥+{st.session_state.get("_prem", 3):.1f}% / '
        f'折價≤{st.session_state.get("_disc", -3):.1f}%</span>',
        unsafe_allow_html=True,
    )
    if not in_session:
        st.caption("⚠️ 目前非監控時段或休市，畫面資料可能不是盤中即時，請勿當作下單依據。")
    elif state == "pre_market":
        st.caption("ℹ️ 盤前時段：資料可能仍為前一交易日，僅供開盤前留意。")
    st.caption(
        (snapshot or {}).get("disclaimer")
        or "僅為輔助監控與告警，不可視為即時交易或自動下單系統。資料來源：TWSE all_etf.txt"
    )


@st.cache_data(ttl=60, show_spinner="正在向證交所取得 ETF 資料…")
def _live_fetch(premium: float, discount: float, max_age: int) -> dict:
    settings = Settings(
        premium_threshold=premium,
        discount_threshold=discount,
        data_max_age_minutes=max_age,
    )
    raw_rows, meta = fetch_etf_records()
    now = now_taipei()
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
    return {
        "fetched_at": now.isoformat(),
        "session": session_status(now),
        "source": meta,
        "summary": summarize(evaluated),
        "etfs": evaluated,
        "thresholds": {
            "premium": premium,
            "discount": discount,
            "data_max_age_minutes": max_age,
        },
        "active_alerts": active_alerts(load_alert_state()),
        "disclaimer": "本系統僅為輔助監控與告警，不可視為即時交易或自動下單系統。",
    }


def _prepare_rows(
    snapshot: dict, premium: float, discount: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for src in snapshot.get("etfs") or []:
        r = dict(src)
        pd_pct = r.get("premium_discount_pct")
        # Rank/search: allow stale rows so off-hours still useful for review
        usable = r.get("status") in ("ok", "stale") and isinstance(
            pd_pct, (int, float)
        )
        if usable:
            if pd_pct >= premium:
                r["alert_direction"] = "premium"
            elif pd_pct <= discount:
                r["alert_direction"] = "discount"
            else:
                r["alert_direction"] = None
            r["over_threshold"] = r["alert_direction"] is not None
        else:
            r["alert_direction"] = None
            r["over_threshold"] = False
        rows.append(r)
    return rows


def _build_display_df(
    rows: list[dict],
    *,
    simple: bool = True,
    query: str = "",
    only_alert: bool = False,
    status_filter: str = "全部",
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        pd_pct = r.get("premium_discount_pct")
        status = r.get("status") or ""
        direction = r.get("alert_direction")
        if only_alert and not r.get("over_threshold"):
            continue
        if status_filter == "僅有效" and status != "ok":
            continue
        if status_filter == "僅逾時" and status != "stale":
            continue
        if status_filter == "僅異常／缺值" and status in ("ok", "stale"):
            continue

        code = str(r.get("code") or "")
        name = str(r.get("name") or "")
        if query:
            q = query.strip().lower()
            if q not in code.lower() and q not in name.lower():
                continue

        if direction == "premium":
            tag = "🔴 溢價"
        elif direction == "discount":
            tag = "🔵 折價"
        else:
            tag = "—"

        rec = {
            "代號": code,
            "名稱": _short_name(name, 20 if simple else 40),
            "全名": name,
            "市價": r.get("market_price"),
            "預估淨值": r.get("estimated_nav"),
            "折溢價%": pd_pct,
            "狀態": f"{STATUS_EMOJI.get(status, '')} {STATUS_LABELS.get(status, status)}",
            "標籤": tag,
            "資料時間": _fmt_time(r.get("data_time_iso")),
            "_sort_pd": pd_pct if isinstance(pd_pct, (int, float)) else None,
            "_status": status,
        }
        if not simple:
            rec["官方%"] = r.get("official_premium_discount_pct")
            rec["誤差pp"] = r.get("cross_check_diff_pp")
            issues = r.get("issues") or []
            rec["備註"] = "；".join(issues) if isinstance(issues, list) else str(issues)
        records.append(rec)

    df = pd.DataFrame(records)
    if df.empty:
        return df
    return df


def _style_pd(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Color the 折溢價% column; format numbers."""
    if df.empty:
        return df.style

    fmt_cols = {}
    if "市價" in df.columns:
        fmt_cols["市價"] = lambda v: _fmt_price(v)
    if "預估淨值" in df.columns:
        fmt_cols["預估淨值"] = lambda v: _fmt_price(v)
    if "折溢價%" in df.columns:
        fmt_cols["折溢價%"] = lambda v: _fmt_pct(v)
    if "官方%" in df.columns:
        fmt_cols["官方%"] = lambda v: _fmt_pct(v)
    if "誤差pp" in df.columns:
        fmt_cols["誤差pp"] = (
            lambda v: "—"
            if v is None or (isinstance(v, float) and pd.isna(v))
            else f"{float(v):.3f}"
        )

    def _color_pd(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        try:
            x = float(val)
        except (TypeError, ValueError):
            return ""
        if x >= 3:
            return "color: #b91c1c; font-weight: 700; background-color: #fef2f2"
        if x > 0.5:
            return "color: #dc2626; font-weight: 600"
        if x <= -3:
            return "color: #1d4ed8; font-weight: 700; background-color: #eff6ff"
        if x < -0.5:
            return "color: #2563eb; font-weight: 600"
        return "color: #4b5563"

    show = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")
    # Hide full name column from default view if present
    if "全名" in show.columns:
        show = show.drop(columns=["全名"])

    styler = show.style
    if "折溢價%" in show.columns:
        styler = styler.map(_color_pd, subset=["折溢價%"])
    if fmt_cols:
        styler = styler.format(fmt_cols)
    return styler


def _render_table(df: pd.DataFrame, height: int = 420) -> None:
    if df.empty:
        st.info("沒有符合條件的資料")
        return
    # column_config for nicer display without losing sort on raw numbers
    config = {
        "代號": st.column_config.TextColumn("代號", width="small"),
        "名稱": st.column_config.TextColumn("名稱", width="medium"),
        "市價": st.column_config.NumberColumn("市價", format="%.2f", width="small"),
        "預估淨值": st.column_config.NumberColumn(
            "預估淨值", format="%.2f", width="small"
        ),
        "折溢價%": st.column_config.NumberColumn(
            "折溢價%", format="%+.2f%%", width="small"
        ),
        "狀態": st.column_config.TextColumn("狀態", width="small"),
        "標籤": st.column_config.TextColumn("標籤", width="small"),
        "資料時間": st.column_config.TextColumn("時間", width="small"),
        "官方%": st.column_config.NumberColumn("官方%", format="%+.2f%%", width="small"),
        "誤差pp": st.column_config.NumberColumn("誤差", format="%.3f", width="small"),
        "備註": st.column_config.TextColumn("備註", width="medium"),
    }
    show = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")
    if "全名" in show.columns:
        show = show.drop(columns=["全名"])
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        height=height,
        column_config={k: v for k, v in config.items() if k in show.columns},
    )


def _top_cards(rows: list[dict], premium: float, discount: float, n: int = 8) -> None:
    """Hero: top premium and discount side by side as compact cards."""
    usable = [
        r
        for r in rows
        if isinstance(r.get("premium_discount_pct"), (int, float))
        and r.get("status") in ("ok", "stale")
    ]
    if not usable:
        st.info("目前沒有可排序的折溢價資料")
        return

    by_prem = sorted(
        usable, key=lambda r: r["premium_discount_pct"], reverse=True
    )[:n]
    by_disc = sorted(usable, key=lambda r: r["premium_discount_pct"])[:n]

    left, right = st.columns(2)
    with left:
        st.markdown("##### 🔴 溢價排行（市價偏高）")
        _render_rank_list(by_prem, highlight_gt=premium)
    with right:
        st.markdown("##### 🔵 折價排行（市價偏低）")
        _render_rank_list(by_disc, highlight_lt=discount)


def _render_rank_list(
    items: list[dict],
    *,
    highlight_gt: float | None = None,
    highlight_lt: float | None = None,
) -> None:
    if not items:
        st.caption("無資料")
        return
    lines = []
    for i, r in enumerate(items, 1):
        pct = float(r["premium_discount_pct"])
        hot = False
        if highlight_gt is not None and pct >= highlight_gt:
            hot = True
        if highlight_lt is not None and pct <= highlight_lt:
            hot = True
        color = "#b91c1c" if pct >= 0 else "#1d4ed8"
        bg = "#fef2f2" if (hot and pct >= 0) else ("#eff6ff" if hot else "transparent")
        border = "#fecaca" if (hot and pct >= 0) else ("#bfdbfe" if hot else "#e5e7eb")
        mark = "⚠ " if hot else ""
        lines.append(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f"padding:0.45rem 0.65rem;margin-bottom:0.35rem;border-radius:8px;"
            f'background:{bg};border:1px solid {border};">'
            f'<div style="min-width:0;">'
            f'<span style="color:#9ca3af;font-size:0.8rem;margin-right:0.4rem;">{i:02d}</span>'
            f'<strong style="font-size:1rem;">{r.get("code")}</strong> '
            f'<span style="color:#4b5563;font-size:0.9rem;">{_short_name(r.get("name") or "", 14)}</span>'
            f'</div>'
            f'<div style="color:{color};font-weight:700;font-size:1.05rem;white-space:nowrap;">'
            f"{mark}{pct:+.2f}%</div></div>"
        )
    st.markdown("".join(lines), unsafe_allow_html=True)


def main() -> None:
    st.title("📊 台灣 ETF 折溢價監控")
    st.markdown(
        '<p class="subline">資料來源：'
        '<a href="https://mis.twse.com.tw/stock/various-areas/etf-price/'
        'indicator-disclosure-etf?lang=zhHant" target="_blank">TWSE 指標價值揭露</a>'
        " · 官方端點 all_etf.txt · 每 5 分鐘輔助監控</p>",
        unsafe_allow_html=True,
    )

    file_settings = load_settings_file()
    sess = session_status()

    with st.sidebar:
        st.header("設定")
        premium = st.number_input(
            "溢價門檻 (%)",
            value=float(file_settings.get("premium_threshold", 3.0)),
            step=0.1,
            format="%.2f",
            help="大於等於此值視為溢價警示",
        )
        discount = st.number_input(
            "折價門檻 (%)",
            value=float(file_settings.get("discount_threshold", -3.0)),
            step=0.1,
            format="%.2f",
            help="小於等於此值視為折價警示",
        )
        max_age = st.number_input(
            "資料過期（分）",
            value=int(file_settings.get("data_max_age_minutes", 10)),
            min_value=1,
            max_value=120,
            step=1,
        )
        st.session_state["_prem"] = float(premium)
        st.session_state["_disc"] = float(discount)

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("儲存", use_container_width=True):
                save_settings_file(
                    {
                        "premium_threshold": float(premium),
                        "discount_threshold": float(discount),
                        "data_max_age_minutes": int(max_age),
                    }
                )
                st.success("已儲存")
        with col_b:
            if st.button("重新整理", use_container_width=True, type="primary"):
                st.cache_data.clear()
                st.rerun()

        data_mode = st.radio(
            "資料來源",
            options=["即時 TWSE", "Repo 快照"],
            index=0,
            help="即時：直接向證交所抓取；快照：讀取 Actions 寫入的 latest.json",
        )

        st.markdown("---")
        st.markdown(
            "**使用提示**\n\n"
            "1. 先看上方**溢價／折價排行**\n"
            "2. 紅＝溢價、藍＝折價\n"
            "3. ⚠ 表示已超過你的門檻\n"
            "4. 休市／盤前資料可能非即時"
        )

    # Load data
    snapshot = None
    live_error = None
    if data_mode.startswith("即時"):
        try:
            snapshot = _live_fetch(float(premium), float(discount), int(max_age))
        except Exception as exc:
            live_error = str(exc)
            snapshot = load_snapshot()
    else:
        snapshot = load_snapshot()

    _status_banner(sess, snapshot)

    if live_error:
        st.error(f"即時抓取失敗，改顯示快照：{live_error}")

    if not snapshot:
        st.error("尚無資料。請確認 TWSE 可連線，或先執行監控腳本。")
        st.code("python scripts/run_monitor.py --no-notify", language="bash")
        return

    rows = _prepare_rows(snapshot, float(premium), float(discount))
    summary = snapshot.get("summary") or {}
    # Recompute alert candidates with sidebar thresholds (incl. stale for display)
    n_prem = sum(1 for r in rows if r.get("alert_direction") == "premium")
    n_disc = sum(1 for r in rows if r.get("alert_direction") == "discount")
    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_stale = sum(1 for r in rows if r.get("status") == "stale")
    n_bad = sum(
        1 for r in rows if r.get("status") in ("anomaly", "missing", "invalid")
    )
    total = len(rows)
    fetched = _fmt_time(snapshot.get("fetched_at"))

    # ---- KPI row ----
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("更新時間", fetched)
    k2.metric("ETF 總數", total)
    k3.metric("有效", n_ok)
    k4.metric("逾時", n_stale)
    k5.metric("溢價超標", n_prem)
    k6.metric("折價超標", n_disc)

    if n_bad:
        st.caption(f"另有 {n_bad} 筆異常／缺值（不納入告警）")

    # ---- Alerts first if any ----
    locked = snapshot.get("active_alerts") or active_alerts(load_alert_state())
    over = [r for r in rows if r.get("over_threshold")]
    if locked or over:
        with st.container():
            st.markdown("### ⚡ 需留意")
            if locked:
                st.markdown("**Telegram 已鎖定告警**")
                adf = pd.DataFrame(locked)
                rename = {
                    "code": "代號",
                    "name": "名稱",
                    "direction": "方向",
                    "rate": "折溢價%",
                    "notified_at": "通知時間",
                }
                cols = [c for c in rename if c in adf.columns]
                if cols:
                    show = adf[cols].rename(columns=rename)
                    if "方向" in show.columns:
                        show["方向"] = show["方向"].map(
                            {
                                "premium": "🔴 溢價",
                                "discount": "🔵 折價",
                            }
                        )
                    if "通知時間" in show.columns:
                        show["通知時間"] = show["通知時間"].map(_fmt_time)
                    if "名稱" in show.columns:
                        show["名稱"] = show["名稱"].map(lambda x: _short_name(str(x), 18))
                    st.dataframe(
                        show,
                        use_container_width=True,
                        hide_index=True,
                        height=min(220, 48 + 36 * len(show)),
                        column_config={
                            "折溢價%": st.column_config.NumberColumn(format="%+.2f%%"),
                        },
                    )
            if over:
                st.markdown(
                    f"**目前超過門檻（畫面設定）· {len(over)} 檔**"
                )
                over_df = _build_display_df(over, simple=True)
                if not over_df.empty and "_sort_pd" in over_df.columns:
                    over_df = over_df.reindex(
                        over_df["_sort_pd"].abs().sort_values(ascending=False).index
                    )
                _render_table(over_df, height=min(320, 48 + 36 * max(len(over), 1)))
            st.markdown("---")

    # ---- Rankings (hero) ----
    st.markdown("### 排行榜")
    top_n = st.slider("排行顯示筆數", 5, 20, 10, 1, key="top_n")
    _top_cards(rows, float(premium), float(discount), n=top_n)

    st.markdown("---")

    # ---- Full list with filters ----
    st.markdown("### 全部清單")
    f1, f2, f3, f4 = st.columns([2, 1.2, 1.2, 1])
    with f1:
        q = st.text_input(
            "搜尋",
            placeholder="輸入代號或名稱，例如 0050、高股息",
            label_visibility="collapsed",
        )
    with f2:
        status_filter = st.selectbox(
            "狀態",
            options=["全部", "僅有效", "僅逾時", "僅異常／缺值"],
            label_visibility="collapsed",
        )
    with f3:
        only_alert = st.checkbox("只看超標", value=False)
    with f4:
        detail = st.checkbox("詳細欄位", value=False)

    full_df = _build_display_df(
        rows,
        simple=not detail,
        query=q or "",
        only_alert=only_alert,
        status_filter=status_filter,
    )
    # Default sort by abs premium for scanning, unless user sorted in UI
    if not full_df.empty and "_sort_pd" in full_df.columns:
        full_df = full_df.reindex(
            full_df["_sort_pd"].fillna(0).abs().sort_values(ascending=False).index
        )

    st.caption(f"顯示 {len(full_df)} / {total} 檔 · 點欄位標題可排序")
    _render_table(full_df, height=520)

    with st.expander("資料來源與規則說明"):
        st.markdown(
            """
| 項目 | 說明 |
|------|------|
| 端點 | `https://mis.twse.com.tw/stock/data/all_etf.txt` |
| 公式 | 折溢價% = (市價 − 預估淨值) ÷ 預估淨值 × 100 |
| 交叉驗證 | 自算與官方誤差 > 0.05pp → 異常，不告警 |
| 通知時段 | 平日 08:50–13:30（Asia/Taipei），含盤前 |
| 防洗版 | 同 ETF 同方向鎖定至回到門檻內 |
| 限制 | Actions 可能延遲，**非**即時交易系統 |
            """
        )
        src = snapshot.get("source") or {}
        if src:
            st.json(src)


if __name__ == "__main__":
    main()
