"""Streamlit dashboard for Taiwan ETF premium/discount monitoring.

Readable-first: high-contrast light theme, minimal custom CSS,
native Streamlit widgets so text never disappears.
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

# Only spacing tweaks — do NOT override theme text/background colors
# (that caused white-on-white on Streamlit Cloud / dark mode).
st.markdown(
    """
    <style>
      .block-container { padding-top: 1rem; max-width: 1400px; }
      h1 { font-size: 1.7rem !important; }
      div[data-testid="stMetricValue"] { font-size: 1.15rem !important; }
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
    if len(s) >= 16:
        return s[5:16]
    return s[:19]


def _short_name(name: str, n: int = 16) -> str:
    name = (name or "").strip()
    if len(name) <= n:
        return name
    return name[: n - 1] + "…"


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
            tag = "🔴溢價"
        elif direction == "discount":
            tag = "🔵折價"
        else:
            tag = ""

        rec = {
            "代號": code,
            "名稱": _short_name(name, 18 if simple else 36),
            "市價": r.get("market_price"),
            "預估淨值": r.get("estimated_nav"),
            "折溢價%": pd_pct,
            "狀態": f"{STATUS_EMOJI.get(status, '')}{STATUS_LABELS.get(status, status)}",
            "標籤": tag,
            "資料時間": _fmt_time(r.get("data_time_iso")),
            "_sort_pd": pd_pct if isinstance(pd_pct, (int, float)) else None,
        }
        if not simple:
            rec["官方%"] = r.get("official_premium_discount_pct")
            rec["誤差pp"] = r.get("cross_check_diff_pp")
            issues = r.get("issues") or []
            rec["備註"] = (
                "；".join(issues) if isinstance(issues, list) else str(issues)
            )
        records.append(rec)

    return pd.DataFrame(records)


def _column_config(df: pd.DataFrame) -> dict:
    cfg = {
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
        "備註": st.column_config.TextColumn("備註", width="large"),
    }
    return {k: v for k, v in cfg.items() if k in df.columns}


def _render_table(df: pd.DataFrame, height: int = 420) -> None:
    if df.empty:
        st.info("沒有符合條件的資料")
        return
    show = df.drop(
        columns=[c for c in df.columns if c.startswith("_")], errors="ignore"
    )
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        height=height,
        column_config=_column_config(show),
    )


def _rank_dataframe(items: list[dict]) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(items, 1):
        pct = float(r["premium_discount_pct"])
        rows.append(
            {
                "#": i,
                "代號": r.get("code"),
                "名稱": _short_name(str(r.get("name") or ""), 14),
                "折溢價%": pct,
                "市價": r.get("market_price"),
                "預估淨值": r.get("estimated_nav"),
            }
        )
    return pd.DataFrame(rows)


def _top_ranks(
    rows: list[dict], premium: float, discount: float, n: int
) -> None:
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
        st.subheader("🔴 溢價排行（市價偏高）")
        st.caption(f"超過 +{premium:.2f}% 者請特別留意")
        df = _rank_dataframe(by_prem)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=48 + 35 * max(len(df), 1),
            column_config={
                "#": st.column_config.NumberColumn("#", width="small"),
                "代號": st.column_config.TextColumn("代號", width="small"),
                "名稱": st.column_config.TextColumn("名稱", width="medium"),
                "折溢價%": st.column_config.NumberColumn(
                    "折溢價%", format="%+.2f%%", width="small"
                ),
                "市價": st.column_config.NumberColumn("市價", format="%.2f", width="small"),
                "預估淨值": st.column_config.NumberColumn(
                    "淨值", format="%.2f", width="small"
                ),
            },
        )
    with right:
        st.subheader("🔵 折價排行（市價偏低）")
        st.caption(f"低於 {discount:.2f}% 者請特別留意")
        df = _rank_dataframe(by_disc)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=48 + 35 * max(len(df), 1),
            column_config={
                "#": st.column_config.NumberColumn("#", width="small"),
                "代號": st.column_config.TextColumn("代號", width="small"),
                "名稱": st.column_config.TextColumn("名稱", width="medium"),
                "折溢價%": st.column_config.NumberColumn(
                    "折溢價%", format="%+.2f%%", width="small"
                ),
                "市價": st.column_config.NumberColumn("市價", format="%.2f", width="small"),
                "預估淨值": st.column_config.NumberColumn(
                    "淨值", format="%.2f", width="small"
                ),
            },
        )


def main() -> None:
    st.title("📊 台灣 ETF 折溢價監控")
    st.write(
        "資料來源：[TWSE 指標價值揭露]("
        "https://mis.twse.com.tw/stock/various-areas/etf-price/"
        "indicator-disclosure-etf?lang=zhHant) · "
        "官方端點 `all_etf.txt` · 每 5 分鐘輔助監控"
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
        )
        discount = st.number_input(
            "折價門檻 (%)",
            value=float(file_settings.get("discount_threshold", -3.0)),
            step=0.1,
            format="%.2f",
        )
        max_age = st.number_input(
            "資料過期（分）",
            value=int(file_settings.get("data_max_age_minutes", 10)),
            min_value=1,
            max_value=120,
            step=1,
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("儲存", use_container_width=True):
                save_settings_file(
                    {
                        "premium_threshold": float(premium),
                        "discount_threshold": float(discount),
                        "data_max_age_minutes": int(max_age),
                    }
                )
                st.success("已儲存")
        with c2:
            if st.button("重新整理", use_container_width=True, type="primary"):
                st.cache_data.clear()
                st.rerun()

        data_mode = st.radio(
            "資料來源",
            options=["即時 TWSE", "Repo 快照"],
            index=0,
        )

        st.divider()
        st.markdown(
            "**使用提示**\n\n"
            "1. 先看溢價／折價排行\n"
            "2. 紅＝溢價、藍＝折價\n"
            "3. 休市／盤前資料可能非即時\n"
            "4. 僅供輔助，不可當自動下單"
        )

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

    # Status — use native Streamlit alerts (theme-safe)
    state = sess.get("state")
    in_session = sess.get("in_session")
    now_s = _fmt_time(sess.get("now"))
    window = sess.get("session", "08:50–13:30")

    if in_session and state == "pre_market":
        st.info(
            f"**盤前監控中**（{window}，正式開盤 "
            f"{sess.get('official_open', '09:00')}）· 現在 {now_s}\n\n"
            "資料可能仍為前一交易日，僅供開盤前留意。"
        )
    elif in_session:
        st.success(f"**交易時段中**（{window}）· 現在 {now_s}")
    elif state == "closed_day":
        st.warning(
            f"**休市日** · 現在 {now_s}\n\n"
            "畫面資料不是盤中即時，請勿當作下單依據。"
        )
    else:
        st.warning(
            f"**非監控時段**：{sess.get('reason')} · 現在 {now_s}\n\n"
            "畫面資料可能不是盤中即時。"
        )

    st.caption(
        (snapshot or {}).get("disclaimer")
        or "僅為輔助監控與告警，不可視為即時交易或自動下單系統。"
    )

    if live_error:
        st.error(f"即時抓取失敗，改顯示快照：{live_error}")

    if not snapshot:
        st.error("尚無資料。請確認 TWSE 可連線，或先執行監控腳本。")
        st.code("python scripts/run_monitor.py --no-notify", language="bash")
        return

    rows = _prepare_rows(snapshot, float(premium), float(discount))
    n_prem = sum(1 for r in rows if r.get("alert_direction") == "premium")
    n_disc = sum(1 for r in rows if r.get("alert_direction") == "discount")
    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_stale = sum(1 for r in rows if r.get("status") == "stale")
    n_bad = sum(
        1 for r in rows if r.get("status") in ("anomaly", "missing", "invalid")
    )
    total = len(rows)
    fetched = _fmt_time(snapshot.get("fetched_at"))

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("更新時間", fetched)
    k2.metric("ETF 總數", f"{total}")
    k3.metric("有效", f"{n_ok}")
    k4.metric("逾時", f"{n_stale}")
    k5.metric("溢價超標", f"{n_prem}")
    k6.metric("折價超標", f"{n_disc}")
    if n_bad:
        st.caption(f"另有 {n_bad} 筆異常／缺值（不納入告警）")

    # Alerts
    locked = snapshot.get("active_alerts") or active_alerts(load_alert_state())
    over = [r for r in rows if r.get("over_threshold")]
    if locked or over:
        st.subheader("⚡ 需留意")
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
                        {"premium": "🔴溢價", "discount": "🔵折價"}
                    )
                if "通知時間" in show.columns:
                    show["通知時間"] = show["通知時間"].map(_fmt_time)
                if "名稱" in show.columns:
                    show["名稱"] = show["名稱"].map(
                        lambda x: _short_name(str(x), 18)
                    )
                st.dataframe(
                    show,
                    use_container_width=True,
                    hide_index=True,
                    height=min(220, 48 + 36 * max(len(show), 1)),
                    column_config={
                        "折溢價%": st.column_config.NumberColumn(format="%+.2f%%"),
                    },
                )
        if over:
            st.markdown(f"**目前超過門檻 · {len(over)} 檔**（門檻 溢價≥+{premium:.2f}% / 折價≤{discount:.2f}%）")
            over_df = _build_display_df(over, simple=True)
            if not over_df.empty and "_sort_pd" in over_df.columns:
                over_df = over_df.reindex(
                    over_df["_sort_pd"].abs().sort_values(ascending=False).index
                )
            _render_table(over_df, height=min(320, 48 + 36 * max(len(over), 1)))
        st.divider()

    st.subheader("排行榜")
    top_n = st.slider("排行顯示筆數", 5, 20, 10, 1)
    _top_ranks(rows, float(premium), float(discount), n=top_n)

    st.divider()
    st.subheader("全部清單")

    f1, f2, f3, f4 = st.columns([2.2, 1.3, 1, 1])
    with f1:
        q = st.text_input(
            "搜尋代號或名稱",
            placeholder="例如 0050、高股息",
        )
    with f2:
        status_filter = st.selectbox(
            "狀態篩選",
            options=["全部", "僅有效", "僅逾時", "僅異常／缺值"],
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
    if not full_df.empty and "_sort_pd" in full_df.columns:
        full_df = full_df.reindex(
            full_df["_sort_pd"].fillna(0).abs().sort_values(ascending=False).index
        )

    st.caption(f"顯示 **{len(full_df)}** / {total} 檔 · 點欄位標題可排序")
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
