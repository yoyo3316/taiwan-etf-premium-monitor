"""Curated popular Taiwan ETFs (high discussion / volume / AUM / DCA).

Sources (public rankings, 2025–2026 media & exchange stats):
  - High beneficiaries / DCA: 0050, 0056, 00878, 00919
  - High volume: 00685L, 00631L, 00403A, 00981A, 00632R, 009816
  - Popular themes: 0052, 006208, 00918, 00940, 00881, 00929

This list is a static watchlist for "don't chase >1% premium" reminders.
It is NOT a live volume feed; update periodically as market fads change.
"""

from __future__ import annotations

from typing import Any

# code -> short label / category for UI
HOT_ETFS: dict[str, dict[str, str]] = {
    # 國民級 / 受益人、定期定額討論度高
    "0050": {"name": "元大台灣50", "group": "市值", "why": "受益人／定額人氣王"},
    "006208": {"name": "富邦台50", "group": "市值", "why": "台50雙雄、費用低"},
    "0052": {"name": "富邦科技", "group": "市值", "why": "科技權值、討論度高"},
    "009816": {"name": "凱基台灣TOP50", "group": "市值", "why": "新市值型、成交熱"},
    # 高股息族（存股討論核心）
    "0056": {"name": "元大高股息", "group": "高股息", "why": "老牌高息、定額前段"},
    "00878": {"name": "國泰永續高股息", "group": "高股息", "why": "月配討論／受益人多"},
    "00919": {"name": "群益台灣精選高息", "group": "高股息", "why": "高息人氣、規模大"},
    "00918": {"name": "大華優利高填息30", "group": "高股息", "why": "高息話題常客"},
    "00929": {"name": "復華台灣科技優息", "group": "高股息", "why": "科技高息、討論多"},
    "00940": {"name": "元大台灣價值高息", "group": "高股息", "why": "月配／成交常前段"},
    "00881": {"name": "國泰台灣科技龍頭", "group": "主題", "why": "科技龍頭人氣"},
    # 主動式（2025–26 量能常霸榜）
    "00403A": {"name": "主動統一升級50", "group": "主動", "why": "五日均量常居前"},
    "00981A": {"name": "主動統一台股增長", "group": "主動", "why": "主動式人氣／規模增"},
    # 槓桿反向（成交量常居前，波動大）
    "00631L": {"name": "元大台灣50正2", "group": "槓反", "why": "成交值／量常前段"},
    "00685L": {"name": "群益臺灣加權正2", "group": "槓反", "why": "均量常居成交王"},
    "00632R": {"name": "元大台灣50反1", "group": "槓反", "why": "避險量能高"},
}

# Premium threshold for "不要追價" reminder on hot list
HOT_CHASE_PREMIUM_PCT = 1.0


def hot_codes() -> list[str]:
    return list(HOT_ETFS.keys())


def build_hot_watch_rows(
    etf_rows: list[dict[str, Any]],
    *,
    chase_premium_pct: float = HOT_CHASE_PREMIUM_PCT,
) -> list[dict[str, Any]]:
    """Merge live TWSE rows with hot list; flag premium > chase threshold."""
    by_code = {str(r.get("code") or "").upper(): r for r in etf_rows}
    out: list[dict[str, Any]] = []
    for code, meta in HOT_ETFS.items():
        live = by_code.get(code.upper()) or {}
        pct = live.get("premium_discount_pct")
        if not isinstance(pct, (int, float)):
            # try official field
            pct = live.get("official_premium_discount_pct")
        chase = isinstance(pct, (int, float)) and pct >= chase_premium_pct
        discount_ok = isinstance(pct, (int, float)) and pct <= -chase_premium_pct
        if chase:
            advice = f"⚠ 溢價≥{chase_premium_pct:.0f}%｜不建議追價"
            tone = "chase"
        elif discount_ok:
            advice = f"折價≥{chase_premium_pct:.0f}%｜可留意（非建議）"
            tone = "discount"
        elif isinstance(pct, (int, float)):
            advice = "折溢價尚可"
            tone = "ok"
        else:
            advice = "暫無報價"
            tone = "na"

        out.append(
            {
                "code": code,
                "name": live.get("name") or meta["name"],
                "group": meta["group"],
                "why": meta["why"],
                "market_price": live.get("market_price"),
                "estimated_nav": live.get("estimated_nav"),
                "premium_discount_pct": pct
                if isinstance(pct, (int, float))
                else None,
                "status": live.get("status"),
                "chase_warning": chase,
                "tone": tone,
                "advice": advice,
            }
        )
    # Sort: chase first, then by abs premium
    out.sort(
        key=lambda r: (
            0 if r["tone"] == "chase" else 1 if r["tone"] == "discount" else 2,
            -(abs(r["premium_discount_pct"]) if r["premium_discount_pct"] is not None else -1),
        )
    )
    return out
