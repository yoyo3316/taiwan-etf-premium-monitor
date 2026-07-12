"""Streamlit dashboard for Taiwan ETF premium/discount monitoring."""

from __future__ import annotations

import sys
from pathlib import Path

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
)

STATUS_LABELS = {
    "ok": "✅ 有效",
    "stale": "⏰ 逾時",
    "anomaly": "⚠️ 異常",
    "missing": "❌ 缺值",
    "invalid": "❌ 無效",
}


def _status_banner(sess: dict, snapshot: dict | None) -> None:
    in_session = sess.get("in_session")
    state = sess.get("state")
    if in_session:
        if state == "pre_market":
            st.info(
                f"盤前監控中（Asia/Taipei {sess.get('session')}，"
                f"正式開盤 {sess.get('official_open', '09:00')}）｜"
                f"現在：{sess.get('now')}　"
                "此時資料可能仍為前一交易日，僅供開盤前留意。"
            )
        else:
            st.success(
                f"交易時段中（Asia/Taipei {sess.get('session')}）｜"
                f"現在：{sess.get('now')}"
            )
    else:
        st.warning(
            f"非監控時段／休市｜狀態：{sess.get('reason')}（{state}）｜"
            f"現在：{sess.get('now')}　"
            "儀表板資料可能非即時，請勿當作盤中即時報價。"
        )

    if snapshot and snapshot.get("disclaimer"):
        st.caption(snapshot["disclaimer"])
    else:
        st.caption(
            "本系統僅為輔助監控與告警，不可視為即時交易或自動下單系統。"
            "資料來源：臺灣證券交易所基本市況報導（all_etf.txt）。"
        )


@st.cache_data(ttl=60, show_spinner="正在向 TWSE 取得最新 ETF 資料…")
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
        "disclaimer": (
            "本系統僅為輔助監控與告警，不可視為即時交易或自動下單系統。"
        ),
    }


def _to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    cols = [
        "code",
        "name",
        "market_price",
        "estimated_nav",
        "premium_discount_pct",
        "official_premium_discount_pct",
        "cross_check_diff_pp",
        "data_time_iso",
        "status",
        "alert_direction",
        "issues",
    ]
    present = [c for c in cols if c in df.columns]
    df = df[present].copy()
    if "status" in df.columns:
        df["status_label"] = df["status"].map(
            lambda s: STATUS_LABELS.get(s, s)
        )
    if "issues" in df.columns:
        df["issues"] = df["issues"].apply(
            lambda x: "；".join(x) if isinstance(x, list) else x
        )
    rename = {
        "code": "代號",
        "name": "名稱",
        "market_price": "市價",
        "estimated_nav": "預估淨值",
        "premium_discount_pct": "折溢價%",
        "official_premium_discount_pct": "官方折溢價%",
        "cross_check_diff_pp": "交叉誤差(pp)",
        "data_time_iso": "資料時間",
        "status_label": "驗證狀態",
        "alert_direction": "告警方向",
        "issues": "備註",
    }
    keep = [c for c in rename if c in df.columns or c == "status_label"]
    # rebuild with status_label
    out_cols = []
    for c in [
        "code",
        "name",
        "market_price",
        "estimated_nav",
        "premium_discount_pct",
        "official_premium_discount_pct",
        "cross_check_diff_pp",
        "data_time_iso",
        "status_label",
        "alert_direction",
        "issues",
    ]:
        if c in df.columns:
            out_cols.append(c)
    df = df[out_cols].rename(columns=rename)
    return df


def main() -> None:
    st.title("📊 台灣 ETF 盤中折溢價監控")
    st.markdown(
        "資料來源：[TWSE ETF 即時指標價值揭露]("
        "https://mis.twse.com.tw/stock/various-areas/etf-price/"
        "indicator-disclosure-etf?lang=zhHant)　／　"
        "官方端點：`mis.twse.com.tw/stock/data/all_etf.txt`"
    )

    file_settings = load_settings_file()
    sess = session_status()

    with st.sidebar:
        st.header("設定")
        premium = st.number_input(
            "溢價通知門檻 (%)",
            value=float(file_settings.get("premium_threshold", 3.0)),
            step=0.1,
            format="%.2f",
        )
        discount = st.number_input(
            "折價通知門檻 (%)",
            value=float(file_settings.get("discount_threshold", -3.0)),
            step=0.1,
            format="%.2f",
        )
        max_age = st.number_input(
            "資料過期分鐘數",
            value=int(file_settings.get("data_max_age_minutes", 10)),
            min_value=1,
            max_value=120,
            step=1,
        )
        if st.button("儲存閾值設定"):
            save_settings_file(
                {
                    "premium_threshold": float(premium),
                    "discount_threshold": float(discount),
                    "data_max_age_minutes": int(max_age),
                }
            )
            st.success("已寫入 data/settings.json（本機／repo 可持久化）")

        data_mode = st.radio(
            "資料來源模式",
            options=["即時向 TWSE 抓取", "讀取 repo 快照 (data/latest.json)"],
            index=0,
        )
        if st.button("重新整理"):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        st.markdown(
            "**注意**\n\n"
            "- GitHub Actions 排程可能延遲，告警非毫秒級即時。\n"
            "- 非交易時段請勿將畫面解讀為盤中即時。\n"
            "- Telegram 憑證僅透過環境變數／Secrets 設定。"
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

    _status_banner(sess, snapshot)

    if live_error:
        st.error(f"即時抓取失敗，改顯示本地快照（若有）：{live_error}")

    if not snapshot:
        st.error("尚無可顯示資料。請先執行監控腳本或確認 TWSE 端點可連線。")
        st.code("python scripts/run_monitor.py --no-notify", language="bash")
        return

    fetched_at = snapshot.get("fetched_at", "未知")
    summary = snapshot.get("summary") or {}
    if data_mode.startswith("即時"):
        # Re-evaluate with current sidebar thresholds for display consistency
        pass

    st.subheader("總覽")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("資料更新時間", fetched_at.replace("T", " ")[:19])
    c2.metric("總 ETF 筆數", summary.get("total", 0))
    c3.metric("資料有效筆數", summary.get("valid", 0))
    c4.metric(
        "異常／逾時",
        (summary.get("anomaly", 0) or 0)
        + (summary.get("stale", 0) or 0)
        + (summary.get("missing_or_invalid", 0) or 0),
    )
    c5.metric(
        "告警候選",
        (summary.get("premium_alert_candidates", 0) or 0)
        + (summary.get("discount_alert_candidates", 0) or 0),
    )

    # Copy rows so sidebar threshold overrides do not mutate cached objects
    rows = []
    for src in snapshot.get("etfs") or []:
        r = dict(src)
        pd_pct = r.get("premium_discount_pct")
        # For ranking UI: apply sidebar thresholds when data is usable.
        # Outside session most rows are "stale"; still show threshold hits
        # for research, but banner already warns non-realtime.
        usable = r.get("status") in ("ok", "stale")
        if usable and isinstance(pd_pct, (int, float)):
            if pd_pct >= float(premium):
                r["alert_direction"] = "premium"
            elif pd_pct <= float(discount):
                r["alert_direction"] = "discount"
            else:
                r["alert_direction"] = None
        rows.append(r)

    df = _to_df(rows)

    st.subheader("搜尋")
    q = st.text_input("依代號或名稱搜尋", placeholder="例如 0050 或 台灣50")
    view = df
    if q and not df.empty:
        mask = df["代號"].astype(str).str.contains(q, case=False, na=False) | df[
            "名稱"
        ].astype(str).str.contains(q, case=False, na=False)
        view = df[mask]

    tab_all, tab_prem, tab_disc, tab_alert, tab_bad = st.tabs(
        ["全部 ETF", "溢價排行", "折價排行", "已觸發告警", "異常／逾時"]
    )

    with tab_all:
        st.dataframe(view, use_container_width=True, hide_index=True, height=480)

    with tab_prem:
        if df.empty or "折溢價%" not in df.columns:
            st.info("無資料")
        else:
            prem = df.dropna(subset=["折溢價%"]).sort_values(
                "折溢價%", ascending=False
            )
            st.dataframe(prem.head(50), use_container_width=True, hide_index=True)

    with tab_disc:
        if df.empty or "折溢價%" not in df.columns:
            st.info("無資料")
        else:
            disc = df.dropna(subset=["折溢價%"]).sort_values(
                "折溢價%", ascending=True
            )
            st.dataframe(disc.head(50), use_container_width=True, hide_index=True)

    with tab_alert:
        alerts = snapshot.get("active_alerts") or active_alerts(load_alert_state())
        if not alerts:
            st.info("目前沒有鎖定中的告警（或尚未由 Actions 寫入 alert_state）。")
        else:
            adf = pd.DataFrame(alerts)
            rename = {
                "code": "代號",
                "name": "名稱",
                "direction": "方向",
                "rate": "折溢價%",
                "market_price": "市價",
                "estimated_nav": "預估淨值",
                "notified_at": "最近通知時間",
            }
            cols = [c for c in rename if c in adf.columns]
            st.dataframe(
                adf[cols].rename(columns=rename),
                use_container_width=True,
                hide_index=True,
            )

        # Also show current candidates by threshold
        candidates = [
            r
            for r in rows
            if r.get("alert_direction") in ("premium", "discount")
            and r.get("status") == "ok"
        ]
        st.markdown("#### 目前超過門檻（依畫面設定）")
        if not candidates:
            st.write("無")
        else:
            st.dataframe(
                _to_df(candidates), use_container_width=True, hide_index=True
            )

    with tab_bad:
        bad = [r for r in rows if r.get("status") != "ok"]
        if not bad:
            st.success("沒有異常或缺值資料")
        else:
            st.dataframe(_to_df(bad), use_container_width=True, hide_index=True)

    with st.expander("來源與欄位說明"):
        st.markdown(
            """
- **官方頁面**：ETF 即時指標價值揭露、ETF 淨值揭露（Vue SPA）
- **實際資料端點**：`https://mis.twse.com.tw/stock/data/all_etf.txt`
  （由前端 `category-*.js` 的 `S()` 載入）
- **折溢價公式**：\\((市價 - 預估淨值) / 預估淨值 × 100\\%\\)
- **交叉驗證**：自算與官方欄位誤差 > 0.05 個百分點 → 標記異常且不告警
- **告警**：預設溢價 ≥ +3%、折價 ≤ −3%；同一方向鎖定至回到正常區間
            """
        )
        src = snapshot.get("source") or {}
        st.json(src)


if __name__ == "__main__":
    main()
