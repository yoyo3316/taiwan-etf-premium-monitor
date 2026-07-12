"""Build verified ETF pair list from holdings overlap + same-index identity.

Overlap metrics (using disclosed holdings):
  weighted_min_overlap = sum_i min(w_a[i], w_b[i])   # percentage points of NAV
  within_top_ratio = weighted_min_overlap / min(coverage_a, coverage_b)

Same-index pairs are marked using official product index mapping
(TWSE / issuer product pages) — equity universe is identical by construction.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any

from .market_hours import now_taipei

logger = logging.getLogger(__name__)

# Official same underlying index (TWSE product / prospectus).
# When two ETFs track the same index, equity constituents match by design.
SAME_INDEX_GROUPS: list[dict[str, Any]] = [
    {
        "index_name": "富時臺灣證券交易所臺灣50指數",
        "codes": ["0050", "006208"],
        "names": {"0050": "元大台灣50", "006208": "富邦台50"},
        "evidence": (
            "TWSE ETF product pages: both track FTSE TWSE Taiwan 50 Index "
            "(富時臺灣證券交易所臺灣50指數)."
        ),
        "universe_overlap": 1.0,
    },
]

# Universe of ETFs to scan each week (hot + known similar pairs)
PAIR_UNIVERSE: list[str] = [
    "0050",
    "006208",
    "0052",
    "009816",
    "0056",
    "00878",
    "00919",
    "00918",
    "00929",
    "00940",
    "00881",
    "00403A",
    "00981A",
    "00631L",
    "00685L",
    "00632R",
]


def _weights_map(holdings_payload: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in holdings_payload.get("holdings") or []:
        c = str(h.get("code") or "").upper()
        try:
            w = float(h.get("weight"))
        except (TypeError, ValueError):
            continue
        if c:
            out[c] = w
    return out


def compute_pair_overlap(
    a_code: str,
    b_code: str,
    holdings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    a = holdings.get(a_code.upper()) or {}
    b = holdings.get(b_code.upper()) or {}
    wa = _weights_map(a)
    wb = _weights_map(b)
    common = sorted(set(wa) & set(wb))
    only_a = sorted(set(wa) - set(wb))
    only_b = sorted(set(wb) - set(wa))
    weighted_min = sum(min(wa[c], wb[c]) for c in common)
    cov_a = sum(wa.values())
    cov_b = sum(wb.values())
    denom = min(cov_a, cov_b) if min(cov_a, cov_b) > 0 else None
    within_top = (weighted_min / denom * 100.0) if denom else None

    common_detail = [
        {
            "code": c,
            "weight_a": wa[c],
            "weight_b": wb[c],
            "min_weight": min(wa[c], wb[c]),
        }
        for c in common
    ]
    common_detail.sort(key=lambda x: -x["min_weight"])

    return {
        "a": a_code.upper(),
        "b": b_code.upper(),
        "common_count": len(common),
        "common_codes": common,
        "common_detail": common_detail[:15],
        "only_a_sample": only_a[:8],
        "only_b_sample": only_b[:8],
        "weighted_min_overlap_pct": round(weighted_min, 4),
        "coverage_a_pct": round(cov_a, 4),
        "coverage_b_pct": round(cov_b, 4),
        "within_top_overlap_pct": (
            round(within_top, 4) if within_top is not None else None
        ),
        "holding_count_a": len(wa),
        "holding_count_b": len(wb),
        "source_a": a.get("source_url"),
        "source_b": b.get("source_url"),
        "method": "top_holdings_weighted_min",
    }


def same_index_lookup(a: str, b: str) -> dict[str, Any] | None:
    a, b = a.upper(), b.upper()
    for g in SAME_INDEX_GROUPS:
        codes = {c.upper() for c in g["codes"]}
        if a in codes and b in codes:
            return g
    return None


def _is_leveraged_or_inverse(code: str) -> bool:
    c = code.upper()
    return c.endswith("L") or c.endswith("R") or c.endswith("U")


def _holdings_usable(payload: dict[str, Any] | None) -> bool:
    """Require enough disclosed names/coverage to avoid bogus overlap."""
    if not payload or payload.get("error"):
        return False
    n = int(payload.get("holding_count") or 0)
    cov = float(payload.get("weight_coverage_pct") or 0)
    return n >= 5 and cov >= 30.0


def build_pairs(
    holdings: dict[str, dict[str, Any]],
    *,
    min_weighted_overlap: float = 40.0,
    min_within_top: float = 70.0,
    include_same_index_always: bool = True,
    exclude_leveraged: bool = True,
) -> list[dict[str, Any]]:
    """Return ranked pairs that pass verification thresholds."""
    codes = sorted(
        {
            c.upper()
            for c in list(holdings.keys()) + PAIR_UNIVERSE
            if c
        }
    )
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for a, b in itertools.combinations(codes, 2):
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        if a not in holdings or b not in holdings:
            continue
        if exclude_leveraged and (
            _is_leveraged_or_inverse(a) or _is_leveraged_or_inverse(b)
        ):
            # Leveraged/inverse products are not stock-basket pair candidates
            continue
        if holdings[a].get("error") or holdings[b].get("error"):
            continue
        if not holdings[a].get("holdings") or not holdings[b].get("holdings"):
            # still allow same-index annotation without top holdings
            sig = same_index_lookup(a, b)
            if include_same_index_always and sig:
                pairs.append(
                    {
                        "a": a,
                        "b": b,
                        "name_a": (sig.get("names") or {}).get(a, a),
                        "name_b": (sig.get("names") or {}).get(b, b),
                        "same_index": True,
                        "index_name": sig["index_name"],
                        "index_evidence": sig["evidence"],
                        "universe_overlap": sig["universe_overlap"],
                        "weighted_min_overlap_pct": None,
                        "within_top_overlap_pct": None,
                        "qualify_reason": "same_official_index",
                        "research_note": (
                            "Same official index → equity constituents identical "
                            "by construction; residual cash/weight drift only. "
                            "Not risk-free arbitrage for retail."
                        ),
                    }
                )
                seen.add(key)
            continue

        # Skip thin disclosures (e.g. 1-name futures ETF shell)
        if not _holdings_usable(holdings[a]) or not _holdings_usable(holdings[b]):
            sig = same_index_lookup(a, b)
            if include_same_index_always and sig:
                # keep same-index even if pocket top list thin
                pass
            else:
                continue

        ov = compute_pair_overlap(a, b, holdings)
        sig = same_index_lookup(a, b)
        same = sig is not None
        within = ov.get("within_top_overlap_pct")
        wmin = ov.get("weighted_min_overlap_pct") or 0

        # Reject thin-disclosure artifacts: high within_top but tiny common set
        if (
            not same
            and (ov.get("common_count") or 0) < 5
            and (wmin < 50)
        ):
            continue

        qualify = False
        reason = []
        if same:
            qualify = True
            reason.append("same_official_index")
        if (
            within is not None
            and within >= min_within_top
            and (ov.get("common_count") or 0) >= 5
            and wmin >= 35
        ):
            qualify = True
            reason.append(f"within_top>={min_within_top}")
        if wmin >= min_weighted_overlap and (ov.get("common_count") or 0) >= 5:
            qualify = True
            reason.append(f"weighted_min>={min_weighted_overlap}")

        if not qualify and not (include_same_index_always and same):
            continue

        name_a = a
        name_b = b
        if sig:
            name_a = (sig.get("names") or {}).get(a, a)
            name_b = (sig.get("names") or {}).get(b, b)

        pairs.append(
            {
                **ov,
                "name_a": name_a,
                "name_b": name_b,
                "same_index": same,
                "index_name": (sig or {}).get("index_name"),
                "index_evidence": (sig or {}).get("evidence"),
                "universe_overlap": (sig or {}).get("universe_overlap"),
                "qualify_reason": "+".join(reason) if reason else "manual",
                "research_note": (
                    "Relative-value research only. High holdings overlap does "
                    "NOT mean risk-free arbitrage (costs, residual, timing)."
                ),
            }
        )
        seen.add(key)

    def sort_key(p: dict[str, Any]):
        if p.get("same_index"):
            return (0, 0.0)
        w = p.get("within_top_overlap_pct")
        if w is None:
            w = p.get("weighted_min_overlap_pct") or 0
        return (1, -float(w))

    pairs.sort(key=sort_key)
    return pairs


def _row_pd(row: dict[str, Any]) -> float | None:
    for key in (
        "premium_discount_pct",
        "official_premium_discount_pct",
        "calculated_premium_discount_pct",
    ):
        v = row.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            try:
                return float(v)
            except ValueError:
                continue
    # compute from price/nav if present
    try:
        px = float(row.get("market_price"))
        nav = float(row.get("estimated_nav"))
        if nav > 0 and px > 0:
            return (px - nav) / nav * 100.0
    except (TypeError, ValueError):
        pass
    return None


def attach_live_premium_gap(
    pairs: list[dict[str, Any]],
    etf_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach live premium/discount and gap for dashboard."""
    by = {str(r.get("code") or "").upper(): r for r in etf_rows}
    out = []
    for p in pairs:
        a = by.get(p["a"], {})
        b = by.get(p["b"], {})
        pa = _row_pd(a)
        pb = _row_pd(b)
        gap = None
        if isinstance(pa, (int, float)) and isinstance(pb, (int, float)):
            gap = round(pa - pb, 4)
        row = {
            **p,
            "premium_a": pa if isinstance(pa, (int, float)) else None,
            "premium_b": pb if isinstance(pb, (int, float)) else None,
            "premium_gap_a_minus_b": gap,
            "name_a": a.get("name") or p.get("name_a") or p["a"],
            "name_b": b.get("name") or p.get("name_b") or p["b"],
            "price_a": a.get("market_price"),
            "price_b": b.get("market_price"),
            "nav_a": a.get("estimated_nav"),
            "nav_b": b.get("estimated_nav"),
        }
        # simple research flag: |gap| large and high overlap
        interesting = False
        if gap is not None and abs(gap) >= 1.0:
            if p.get("same_index") or (p.get("within_top_overlap_pct") or 0) >= 70:
                interesting = True
        row["gap_interesting"] = interesting
        if interesting:
            # cheaper leg relative to NAV
            if gap > 0:
                row["relative_hint"] = (
                    f"{p['a']} 相對較貴(溢價高 {gap:+.2f}pp)，"
                    f"{p['b']} 相對較便宜 — 僅研究、非下單建議"
                )
            else:
                row["relative_hint"] = (
                    f"{p['b']} 相對較貴(溢價高 {-gap:+.2f}pp)，"
                    f"{p['a']} 相對較便宜 — 僅研究、非下單建議"
                )
        else:
            row["relative_hint"] = "—"
        out.append(row)
    return out


def build_pairs_payload(
    holdings: dict[str, dict[str, Any]],
    etf_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pairs = build_pairs(holdings)
    if etf_rows is not None:
        pairs = attach_live_premium_gap(pairs, etf_rows)
    return {
        "updated_at": now_taipei().isoformat(),
        "timezone": "Asia/Taipei",
        "universe": PAIR_UNIVERSE,
        "same_index_groups": SAME_INDEX_GROUPS,
        "methodology": {
            "holdings_source": "pocket.tw top disclosed holdings (SSR embed)",
            "overlap_metric": (
                "weighted_min = sum min(w_a,w_b); "
                "within_top = weighted_min / min(coverage_a, coverage_b)"
            ),
            "same_index": (
                "Official product index identity (TWSE/issuer). "
                "Identical equity universe by construction."
            ),
            "thresholds": {
                "min_weighted_overlap_pct": 40,
                "min_within_top_overlap_pct": 70,
            },
            "disclaimer": (
                "For relative-value research only. Not investment advice. "
                "Not risk-free arbitrage. Creation/redemption is institutional."
            ),
        },
        "pair_count": len(pairs),
        "pairs": pairs,
    }
