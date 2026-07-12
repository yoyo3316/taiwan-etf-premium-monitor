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
from src.convergence import analyze_code, format_convergence_brief
from src.history_store import get_twse_series, is_fresh, load_wantgoo_history, save_wantgoo_history
from src.config import DATA_DIR
from src.hot_etfs import HOT_CHASE_PREMIUM_PCT, build_hot_watch_rows
from src.market_hours import now_taipei, session_status
from src.monitor import evaluate_record, summarize
from src.pair_builder import attach_live_premium_gap
from src.state import active_alerts, load_alert_state
from src.storage import load_settings_file, load_snapshot, save_settings_file
from src.twse_client import fetch_etf_records
from src.wantgoo_client import try_fetch_history, wantgoo_page_url

st.set_page_config(
    page_title="台灣 ETF 折溢價監控",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Finance-style palette (light, high contrast). Leave room under Cloud Share bar.
st.markdown(
    """
    <style>
      :root {
        --bg: #f1f5f9;
        --card: #ffffff;
        --text: #0f172a;
        --muted: #64748b;
        --line: #e2e8f0;
        --blue: #1d4ed8;
        --blue-soft: #eff6ff;
        --red: #b91c1c;
        --red-soft: #fef2f2;
        --green: #166534;
        --green-soft: #ecfdf5;
        --amber: #b45309;
        --amber-soft: #fffbeb;
      }
      .stApp { background: var(--bg); }
      .block-container {
        padding-top: 3.75rem !important;
        padding-bottom: 2rem !important;
        max-width: 1080px;
      }
      header[data-testid="stHeader"] { background: rgba(241,245,249,.92); }
      section[data-testid="stSidebar"] {
        background: #f8fafc !important;
        border-right: 1px solid var(--line);
      }
      /* Title strip */
      .app-hero {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #1d4ed8 100%);
        color: #fff;
        border-radius: 14px;
        padding: 0.9rem 1.15rem;
        margin-bottom: 0.85rem;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
      }
      .app-hero h1 {
        margin: 0 !important;
        font-size: 1.35rem !important;
        font-weight: 700 !important;
        color: #fff !important;
        line-height: 1.3 !important;
      }
      .app-hero .sub {
        margin-top: 0.25rem;
        font-size: 0.86rem;
        color: #cbd5e1;
      }
      /* Status chips */
      .chip-row { display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0.35rem 0 0.75rem 0; }
      .chip {
        display: inline-flex; align-items: center; gap: 0.35rem;
        border-radius: 999px; padding: 0.28rem 0.7rem;
        font-size: 0.86rem; font-weight: 600;
        border: 1px solid transparent;
      }
      .chip-time { background: #fff; color: #0f172a; border-color: var(--line); }
      .chip-open { background: var(--green-soft); color: var(--green); border-color: #bbf7d0; }
      .chip-pre { background: var(--blue-soft); color: var(--blue); border-color: #bfdbfe; }
      .chip-closed { background: var(--amber-soft); color: var(--amber); border-color: #fde68a; }
      .chip-alert { background: var(--red-soft); color: var(--red); border-color: #fecaca; }
      .chip-ok { background: var(--green-soft); color: var(--green); border-color: #bbf7d0; }
      /* Card for attention table */
      .panel {
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: 0.85rem 1rem 1rem 1rem;
        box-shadow: 0 1px 2px rgba(15,23,42,.04);
      }
      .panel h3 {
        margin: 0 0 0.2rem 0 !important;
        font-size: 1.05rem !important;
        color: var(--text) !important;
      }
      .panel .hint { color: var(--muted); font-size: 0.84rem; margin-bottom: 0.55rem; }
      /* Metrics */
      div[data-testid="stMetric"] {
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 0.55rem 0.75rem;
      }
      div[data-testid="stMetricValue"] {
        font-size: 1.15rem !important;
        color: #0f172a !important;
        font-weight: 700 !important;
      }
      div[data-testid="stMetricLabel"] {
        font-size: 0.82rem !important;
        color: #64748b !important;
      }
      /* Dataframe */
      [data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 10px;
        overflow: hidden;
      }
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


def _code_link_column(label: str = "代號") -> st.column_config.LinkColumn:
    """Clickable ticker → WantGoo historical premium/discount page."""
    return st.column_config.LinkColumn(
        label,
        help="點擊代號開啟玩股網「淨值及折溢價」歷史頁",
        display_text=(
            r"https://www\.wantgoo\.com/stock/etf/([^/]+)/discount-premium"
        ),
        width="small",
    )


def _wantgoo_link_column(label: str = "玩股網") -> st.column_config.LinkColumn:
    return st.column_config.LinkColumn(
        label,
        help="玩股網歷史折溢價",
        display_text="歷史折溢價",
        width="small",
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
            # URL value + LinkColumn display_text shows the ticker code
            "代號": wantgoo_page_url(code) if code else "",
            "名稱": _short_name(name, 18 if simple else 36),
            "市價": r.get("market_price"),
            "預估淨值": r.get("estimated_nav"),
            "折溢價%": pd_pct,
            "狀態": f"{STATUS_EMOJI.get(status, '')}{STATUS_LABELS.get(status, status)}",
            "標籤": tag,
            "資料時間": _fmt_time(r.get("data_time_iso")),
            "_sort_pd": pd_pct if isinstance(pd_pct, (int, float)) else None,
            "_code": code,
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
        "代號": _code_link_column("代號"),
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
        "玩股網": _wantgoo_link_column("玩股網"),
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
        code = str(r.get("code") or "")
        rows.append(
            {
                "#": i,
                "代號": wantgoo_page_url(code) if code else "",
                "名稱": _short_name(str(r.get("name") or ""), 14),
                "折溢價%": pct,
                "市價": r.get("market_price"),
                "預估淨值": r.get("estimated_nav"),
            }
        )
    return pd.DataFrame(rows)


def _rank_column_config() -> dict:
    return {
        "#": st.column_config.NumberColumn("#", width="small"),
        "代號": _code_link_column("代號"),
        "名稱": st.column_config.TextColumn("名稱", width="medium"),
        "折溢價%": st.column_config.NumberColumn(
            "折溢價%", format="%+.2f%%", width="small"
        ),
        "市價": st.column_config.NumberColumn("市價", format="%.2f", width="small"),
        "預估淨值": st.column_config.NumberColumn(
            "淨值", format="%.2f", width="small"
        ),
    }


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
        st.caption("點擊「代號」→ 玩股網歷史折溢價")
        df = _rank_dataframe(by_prem)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=48 + 35 * max(len(df), 1),
            column_config=_rank_column_config(),
        )
    with right:
        st.subheader("🔵 折價排行（市價偏低）")
        st.caption(f"低於 {discount:.2f}% 者請特別留意 · 點擊代號開玩股網")
        df = _rank_dataframe(by_disc)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=48 + 35 * max(len(df), 1),
            column_config=_rank_column_config(),
        )


def _load_pairs_file() -> dict | None:
    path = DATA_DIR / "pairs" / "etf_pairs.json"
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _render_pairs_panel(rows: list[dict]) -> None:
    """Show verified high-overlap ETF pairs + live premium gap."""
    st.markdown("### 🔗 相似 ETF 配對（成分重疊驗證）")
    payload = _load_pairs_file()
    if not payload:
        st.info(
            "尚無配對資料。請執行 `python scripts/update_pairs.py`，"
            "或等待每週一 GitHub Actions 自動更新。"
        )
        return

    updated = _fmt_time(payload.get("updated_at"))
    method = (payload.get("methodology") or {}).get("holdings_source", "")
    st.caption(
        f"更新：{updated} · 持股來源：{method} · "
        "重疊以「權重取 min 加總」驗證 · **研究用，非無風險套利**"
    )

    pairs = payload.get("pairs") or []
    # refresh gap with current page rows
    pairs = attach_live_premium_gap(pairs, rows)

    interesting = [p for p in pairs if p.get("gap_interesting")]
    if interesting:
        st.warning(
            f"目前有 **{len(interesting)}** 組高重疊配對，"
            "折溢價差距 ≥ 1 個百分點（僅研究提示）。"
        )

    records = []
    for p in pairs:
        a, b = p["a"], p["b"]
        within = p.get("within_top_overlap_pct")
        wmin = p.get("weighted_min_overlap_pct")
        same = p.get("same_index")
        records.append(
            {
                "A": wantgoo_page_url(a),
                "B": wantgoo_page_url(b),
                "名稱A": _short_name(str(p.get("name_a") or a), 12),
                "名稱B": _short_name(str(p.get("name_b") or b), 12),
                "同指數": "是" if same else "—",
                "成分重疊%": within,
                "權重重疊pp": wmin,
                "共同檔數": p.get("common_count"),
                "A折溢價%": p.get("premium_a"),
                "B折溢價%": p.get("premium_b"),
                "價差A-B": p.get("premium_gap_a_minus_b"),
                "研究提示": p.get("relative_hint") or "—",
            }
        )
    df = pd.DataFrame(records)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(480, 56 + 34 * max(len(df), 1)),
        column_config={
            "A": _code_link_column("A"),
            "B": _code_link_column("B"),
            "成分重疊%": st.column_config.NumberColumn(format="%.1f%%"),
            "權重重疊pp": st.column_config.NumberColumn(format="%.1f"),
            "A折溢價%": st.column_config.NumberColumn(format="%+.2f%%"),
            "B折溢價%": st.column_config.NumberColumn(format="%+.2f%%"),
            "價差A-B": st.column_config.NumberColumn(format="%+.2f"),
        },
    )
    with st.expander("驗證方法說明"):
        st.markdown(
            """
- **同指數**：官方商品追蹤同一指數（例：0050／006208 → 臺灣50指數），權益成分宇宙相同。  
- **持股來源**：CMoney ETF 持股明細（完整揭露名單，每週一自動更新；失敗時 fallback pocket.tw）。  
  例：https://www.cmoney.tw/etf/tw/00646/fundholding  
- **權重重疊**：\\(\\sum \\min(w_A, w_B)\\)（百分點，佔 NAV）。  
- **成分重疊%**：權重重疊 ÷ 兩者持股覆蓋率之較小值。  
- **不是**機構申購買回套利；散戶雙邊成本高，僅供相對價值研究。
            """
        )


def _render_hot_etf_panel(
    rows: list[dict], *, chase_pct: float = HOT_CHASE_PREMIUM_PCT
) -> None:
    """Popular ETFs with 1% premium chase warning."""
    st.markdown("### 🔥 熱門 ETF · 溢價超過 1% 勿追價")
    st.caption(
        "名單綜合：受益人／定期定額討論度、成交量前段、高股息與主動式熱門檔"
        f"（靜態清單，門檻 **溢價 ≥ +{chase_pct:.0f}%** 顯示勿追價）。"
        "點代號 → 玩股網歷史折溢價。"
    )

    hot = build_hot_watch_rows(rows, chase_premium_pct=chase_pct)
    n_chase = sum(1 for h in hot if h.get("chase_warning"))
    if n_chase:
        st.error(
            f"⚠ 目前有 **{n_chase}** 檔熱門 ETF 溢價 ≥ +{chase_pct:.0f}%："
            "市價已高於預估淨值，**不建議追價買進**（僅供提醒，非投資建議）。"
        )
    else:
        st.info(
            f"熱門清單中暫無溢價 ≥ +{chase_pct:.0f}% 的標的（或資料暫缺）。"
        )

    records = []
    for h in hot:
        code = h["code"]
        pct = h.get("premium_discount_pct")
        records.append(
            {
                "代號": wantgoo_page_url(code),
                "名稱": h.get("name") or code,
                "類型": h.get("group"),
                "折溢價%": pct,
                "提醒": h.get("advice"),
                "市價": h.get("market_price"),
                "預估淨值": h.get("estimated_nav"),
                "入選原因": h.get("why"),
            }
        )
    df = pd.DataFrame(records)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(560, 56 + 34 * max(len(df), 1)),
        column_config={
            "代號": _code_link_column("代號"),
            "名稱": st.column_config.TextColumn("名稱", width="medium"),
            "類型": st.column_config.TextColumn("類型", width="small"),
            "折溢價%": st.column_config.NumberColumn(
                "折溢價%", format="%+.2f%%", width="small"
            ),
            "提醒": st.column_config.TextColumn("提醒", width="medium"),
            "市價": st.column_config.NumberColumn("市價", format="%.2f", width="small"),
            "預估淨值": st.column_config.NumberColumn(
                "淨值", format="%.2f", width="small"
            ),
            "入選原因": st.column_config.TextColumn("入選原因", width="medium"),
        },
    )


def _attention_df(over: list[dict], thr_abs: float) -> pd.DataFrame:
    """Compact table for stocks over threshold, with WantGoo links."""
    records = []
    for r in sorted(
        over,
        key=lambda x: abs(x.get("premium_discount_pct") or 0),
        reverse=True,
    ):
        code = str(r.get("code") or "")
        pct = r.get("premium_discount_pct")
        direction = r.get("alert_direction")
        tag = "🔴溢價" if direction == "premium" else "🔵折價"
        # optional short convergence if already attached
        conv = r.get("convergence") or {}
        st_stats = conv.get("stats") or {}
        records.append(
            {
                "代號": wantgoo_page_url(code) if code else "",
                "名稱": _short_name(str(r.get("name") or ""), 16),
                "折溢價%": pct,
                "方向": tag,
                "市價": r.get("market_price"),
                "預估淨值": r.get("estimated_nav"),
                "隔日收斂": (
                    f"{st_stats['converge_rate']*100:.0f}% (n={st_stats['sample_size']})"
                    if st_stats.get("sample_size")
                    else "—"
                ),
            }
        )
    return pd.DataFrame(records)


def main() -> None:
    st.markdown(
        """
        <div class="app-hero">
          <h1>📊 台灣 ETF 折溢價監控</h1>
          <div class="sub">超標清單 · 點代號看玩股網歷史 · 僅供輔助參考</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    file_settings = load_settings_file()
    sess = session_status()

    with st.sidebar:
        st.markdown("### 設定")
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
        if st.button("重新整理", use_container_width=True, type="primary"):
            st.cache_data.clear()
            st.rerun()
        if st.button("儲存門檻", use_container_width=True):
            save_settings_file(
                {
                    "premium_threshold": float(premium),
                    "discount_threshold": float(discount),
                    "data_max_age_minutes": int(max_age),
                }
            )
            st.success("已儲存")
        data_mode = st.radio(
            "資料來源",
            options=["即時 TWSE", "Repo 快照"],
            index=0,
        )
        st.caption("點代號 → 玩股網歷史折溢價")

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

    if live_error:
        st.error(f"抓取失敗：{live_error}")
    if not snapshot:
        st.error("尚無資料")
        return

    rows = _prepare_rows(snapshot, float(premium), float(discount))
    fetched = _fmt_time(snapshot.get("fetched_at"))
    state = sess.get("state")
    in_session = sess.get("in_session")
    if in_session and state == "pre_market":
        sess_label = "盤前"
        chip_cls = "chip-pre"
    elif in_session:
        sess_label = "盤中"
        chip_cls = "chip-open"
    elif state == "closed_day":
        sess_label = "休市"
        chip_cls = "chip-closed"
    else:
        sess_label = sess.get("reason") or "非盤中"
        chip_cls = "chip-closed"

    over = [r for r in rows if r.get("over_threshold")]
    thr_abs = max(abs(float(premium)), abs(float(discount)))
    n_prem = sum(1 for r in over if r.get("alert_direction") == "premium")
    n_disc = sum(1 for r in over if r.get("alert_direction") == "discount")
    alert_chip = "chip-alert" if over else "chip-ok"

    # Enrich attention list with convergence (best-effort)
    for r in over[:20]:
        code = str(r.get("code") or "")
        if not code:
            continue
        wg = load_wantgoo_history(code)
        analysis = analyze_code(
            code,
            wantgoo_payload=wg,
            twse_series=get_twse_series(code),
            abs_threshold=thr_abs,
            direction=r.get("alert_direction"),
        )
        r["convergence"] = analysis

    st.markdown(
        f"""
        <div class="chip-row">
          <span class="chip chip-time">🕐 更新 {fetched}</span>
          <span class="chip {chip_cls}">● {sess_label}</span>
          <span class="chip {alert_chip}">⚡ 需留意 {len(over)} 檔
            （溢價 {n_prem}／折價 {n_disc}）</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### ⚡ 需留意")
    st.caption(
        f"門檻 溢價 ≥ +{premium:.2f}% ／ 折價 ≤ {discount:.2f}% · "
        "點 **代號** 開玩股網歷史 · 🔴溢價 🔵折價"
    )

    if not over:
        st.success("目前沒有超過門檻的 ETF")
    else:
        adf = _attention_df(over, thr_abs)
        st.dataframe(
            adf,
            use_container_width=True,
            hide_index=True,
            height=min(520, 56 + 36 * max(len(adf), 1)),
            column_config={
                "代號": _code_link_column("代號"),
                "折溢價%": st.column_config.NumberColumn(
                    "折溢價%", format="%+.2f%%", width="small"
                ),
                "市價": st.column_config.NumberColumn("市價", format="%.2f", width="small"),
                "預估淨值": st.column_config.NumberColumn(
                    "淨值", format="%.2f", width="small"
                ),
                "方向": st.column_config.TextColumn("方向", width="small"),
                "隔日收斂": st.column_config.TextColumn("隔日收斂", width="small"),
            },
        )

    st.divider()
    _render_hot_etf_panel(rows, chase_pct=HOT_CHASE_PREMIUM_PCT)

    st.divider()
    _render_pairs_panel(rows)

    # Optional extras collapsed
    with st.expander("更多（排行 / 搜尋 / 說明）", expanded=False):
        usable = [
            r
            for r in rows
            if isinstance(r.get("premium_discount_pct"), (int, float))
            and r.get("status") in ("ok", "stale")
        ]
        top_p = sorted(
            usable, key=lambda r: r["premium_discount_pct"], reverse=True
        )[:5]
        top_d = sorted(usable, key=lambda r: r["premium_discount_pct"])[:5]
        left, right = st.columns(2)
        with left:
            st.markdown("**溢價 TOP5**")
            st.dataframe(
                _rank_dataframe(top_p),
                use_container_width=True,
                hide_index=True,
                column_config=_rank_column_config(),
            )
        with right:
            st.markdown("**折價 TOP5**")
            st.dataframe(
                _rank_dataframe(top_d),
                use_container_width=True,
                hide_index=True,
                column_config=_rank_column_config(),
            )

        q = st.text_input("搜尋代號或名稱", placeholder="0050")
        if q:
            hit = _build_display_df(rows, simple=True, query=q)
            _render_table(hit, height=280)

        st.markdown(
            "- 即時：[TWSE](https://mis.twse.com.tw/stock/various-areas/etf-price/"
            "indicator-disclosure-etf?lang=zhHant)  \n"
            "- 歷史：點代號 → 玩股網  \n"
            "- 僅供輔助監控，非即時交易系統"
        )


if __name__ == "__main__":
    main()
