#!/usr/bin/env python3
"""
Aperture Query — Intelligence brief generator.

Connects all data sources (entities, signals, funding, contracts, relationships,
policy alignment) into a single-command pipeline that produces markdown briefs.

Usage:
    python scripts/aperture_query.py --type deal --entity "Scout Space" \
        --output reports/brief_scout_space.md

    # Skip Claude API call for testing:
    python scripts/aperture_query.py --type deal --entity "Scout Space" --no-claude
"""

import argparse
import json
import logging
import re
import sqlite3
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Signal weights (mirrored from processing/rag_engine.py) ──────────────

POSITIVE_WEIGHTS = {
    "sbir_to_contract_transition": 3.0,
    "rapid_contract_growth": 2.5,
    "sbir_to_vc_raise": 2.0,
    "outsized_award": 2.0,
    "sbir_phase_3_transition": 2.0,
    "time_to_contract": 2.0,
    "sbir_validated_raise": 2.5,
    "sbir_phase_2_transition": 1.5,
    "multi_agency_interest": 1.5,
    "sbir_graduation_speed": 1.5,
    "funding_velocity": 1.5,
    "high_priority_technology": 1.0,
    "first_dod_contract": 1.0,
}

NEGATIVE_WEIGHTS = {
    "sbir_stalled": -2.0,
    "customer_concentration": -1.5,
    "gone_stale": -1.5,
}

ALL_WEIGHTS = {**POSITIVE_WEIGHTS, **NEGATIVE_WEIGHTS}

SIGNAL_DISPLAY_NAMES = {
    "sbir_to_contract_transition": "SBIR->Contract",
    "rapid_contract_growth": "Rapid Growth",
    "sbir_to_vc_raise": "SBIR + VC Raise",
    "outsized_award": "Outsized Award",
    "sbir_phase_2_transition": "SBIR Phase II",
    "sbir_phase_3_transition": "SBIR Phase III",
    "time_to_contract": "Fast Time-to-Contract",
    "sbir_validated_raise": "SBIR Validated Raise",
    "multi_agency_interest": "Multi-Agency",
    "sbir_graduation_speed": "Fast SBIR Graduation",
    "funding_velocity": "Funding Velocity",
    "high_priority_technology": "High-Priority Tech",
    "first_dod_contract": "First DoD Contract",
    "sbir_stalled": "SBIR Stalled",
    "customer_concentration": "Customer Concentration",
    "gone_stale": "Gone Stale",
}

BUDGET_WEIGHTS = {
    "space_resilience": 1.38,
    "nuclear_modernization": 1.26,
    "autonomous_systems": 1.22,
    "supply_chain_resilience": 1.15,
    "contested_logistics": 1.12,
    "electronic_warfare": 1.10,
    "jadc2": 1.10,
    "border_homeland": 1.05,
    "cyber_offense_defense": 1.04,
    "hypersonics": 0.57,
}

BUDGET_DIRECTION = {
    "space_resilience": "+38% growth",
    "nuclear_modernization": "+26% growth",
    "autonomous_systems": "+22% growth",
    "supply_chain_resilience": "+15% growth",
    "contested_logistics": "+12% growth",
    "electronic_warfare": "+10% growth",
    "jadc2": "+10% growth",
    "border_homeland": "+5% growth",
    "cyber_offense_defense": "+4% growth",
    "hypersonics": "-43% decline",
}


# ── Helpers ──────────────────────────────────────────────────────────────

def _db_path() -> str:
    """Extract sqlite file path from DATABASE_URL."""
    url = settings.DATABASE_URL
    # sqlite:///path/to/db → path/to/db
    return url.replace("sqlite:///", "")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_currency(val: float) -> str:
    if val is None or val == 0:
        return "$0"
    val = float(val)
    if abs(val) >= 1_000_000_000:
        return f"${val / 1_000_000_000:.1f}B"
    if abs(val) >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if abs(val) >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:,.0f}"


def _fmt_date(d) -> str:
    if d is None:
        return "N/A"
    if isinstance(d, str):
        try:
            d = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return d
    return d.strftime("%B %Y")


def _parse_date(d):
    """Parse a date string to a date object, or return None."""
    if d is None:
        return None
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _months_between(d1, d2):
    """Return signed months from d1 to d2."""
    if d1 is None or d2 is None:
        return None
    d1 = _parse_date(d1)
    d2 = _parse_date(d2)
    if d1 is None or d2 is None:
        return None
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def _parse_json(val):
    """Safely parse a JSON string or return as-is if already a dict/list."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ── Entity lookup ────────────────────────────────────────────────────────

def lookup_entity(conn: sqlite3.Connection, name: str) -> dict | None:
    """Find entity by exact match then fuzzy match. Skip merged entities."""
    # Exact match (case-insensitive)
    row = conn.execute(
        "SELECT * FROM entities WHERE LOWER(canonical_name) = LOWER(?) "
        "AND merged_into_id IS NULL",
        (name,),
    ).fetchone()
    if row:
        return dict(row)

    # Fuzzy match
    try:
        from rapidfuzz import process, fuzz, utils
    except ImportError:
        logger.error("rapidfuzz not installed — cannot fuzzy match entity name")
        return None

    rows = conn.execute(
        "SELECT id, canonical_name FROM entities WHERE merged_into_id IS NULL"
    ).fetchall()
    names = {r["canonical_name"]: r["id"] for r in rows}

    result = process.extractOne(
        name, list(names.keys()), scorer=fuzz.token_sort_ratio,
        processor=utils.default_process, score_cutoff=75,
    )
    if result is None:
        return None

    matched_name, score, _ = result
    logger.info("Fuzzy matched '%s' → '%s' (score: %.0f)", name, matched_name, score)

    row = conn.execute(
        "SELECT * FROM entities WHERE id = ?", (names[matched_name],)
    ).fetchone()
    return dict(row) if row else None


# ── Section builders ─────────────────────────────────────────────────────

def build_company_profile(entity: dict) -> str:
    """Section 1: Company Profile."""
    lines = ["## Company Profile", ""]
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| **Name** | {entity['canonical_name']} |")
    lines.append(f"| **Location** | {entity.get('headquarters_location') or 'N/A'} |")
    lines.append(f"| **Type** | {entity.get('entity_type', 'N/A')} |")
    lines.append(f"| **Core Business** | {entity.get('core_business', 'N/A')} |")

    conf = entity.get("core_business_confidence")
    if conf is not None:
        lines.append(f"| **Classification Confidence** | {float(conf):.2f} |")

    reasoning = entity.get("core_business_reasoning")
    if reasoning:
        lines.append(f"| **Business Description** | {reasoning} |")

    tags = _parse_json(entity.get("technology_tags"))
    if tags:
        lines.append(f"| **Technology Tags** | {', '.join(tags)} |")

    if entity.get("founded_date"):
        lines.append(f"| **Founded** | {entity['founded_date']} |")
    if entity.get("website_url"):
        lines.append(f"| **Website** | {entity['website_url']} |")

    lines.append("")
    return "\n".join(lines)


def build_government_traction(conn: sqlite3.Connection, entity_id: str) -> str:
    """Section 2: Government Traction (SBIRs + Contracts)."""
    lines = ["## Government Traction", ""]

    # SBIRs
    sbirs = conn.execute(
        """SELECT event_type, amount, event_date, source, round_stage,
                  json_extract(raw_data, '$."Award Title"') as title,
                  json_extract(raw_data, '$."Agency"') as agency
           FROM funding_events
           WHERE entity_id = ? AND event_type IN ('SBIR_PHASE_1','SBIR_PHASE_2','SBIR_PHASE_3')
           ORDER BY event_date""",
        (entity_id,),
    ).fetchall()

    if sbirs:
        p1 = sum(1 for s in sbirs if s["event_type"] == "SBIR_PHASE_1")
        p2 = sum(1 for s in sbirs if s["event_type"] == "SBIR_PHASE_2")
        p3 = sum(1 for s in sbirs if s["event_type"] == "SBIR_PHASE_3")
        total_sbir = sum(float(s["amount"] or 0) for s in sbirs)
        phase_str = []
        if p1:
            phase_str.append(f"{p1} Phase I")
        if p2:
            phase_str.append(f"{p2} Phase II")
        if p3:
            phase_str.append(f"{p3} Phase III")
        lines.append(f"**SBIR Awards:** {len(sbirs)} ({', '.join(phase_str)}) — {_fmt_currency(total_sbir)} total")
        lines.append("")

        lines.append("| Date | Phase | Amount | Agency | Title |")
        lines.append("|------|-------|--------|--------|-------|")
        for s in sbirs:
            phase_label = s["event_type"].replace("SBIR_", "").replace("_", " ").title()
            title = s["title"] or ""
            # Clean junk from title
            title = re.sub(r'^[?\s\x00-\x1f\ufffd]+', '', title).strip()
            if len(title) > 80:
                title = title[:77] + "..."
            agency = s["agency"] or s["source"] or ""
            lines.append(
                f"| {_fmt_date(s['event_date'])} | {phase_label} | "
                f"{_fmt_currency(s['amount'])} | {agency} | {title} |"
            )
        lines.append("")
    else:
        lines.append("*No SBIR awards found.*\n")

    # Contracts
    contracts = conn.execute(
        """SELECT contract_number, contracting_agency, contract_value, award_date,
                  contract_type, procurement_type, place_of_performance
           FROM contracts WHERE entity_id = ? ORDER BY award_date""",
        (entity_id,),
    ).fetchall()

    if contracts:
        total_contract = sum(float(c["contract_value"] or 0) for c in contracts)
        ota_count = sum(1 for c in contracts if c["procurement_type"] == "ota")

        lines.append(f"**Contracts:** {len(contracts)} — {_fmt_currency(total_contract)} total")
        if ota_count:
            lines.append(f"  - Including {ota_count} OTA contract{'s' if ota_count > 1 else ''}")
        lines.append("")

        lines.append("| Date | Agency | Value | Type | Procurement |")
        lines.append("|------|--------|-------|------|-------------|")
        for c in contracts:
            lines.append(
                f"| {_fmt_date(c['award_date'])} | {c['contracting_agency'] or 'N/A'} | "
                f"{_fmt_currency(c['contract_value'])} | {c['contract_type'] or 'N/A'} | "
                f"{c['procurement_type'] or 'standard'} |"
            )
        lines.append("")
    else:
        lines.append("*No contracts found.*\n")

    return "\n".join(lines)


def build_private_capital(conn: sqlite3.Connection, entity_id: str) -> str:
    """Section 3: Private Capital Activity."""
    lines = ["## Private Capital Activity", ""]

    regd = conn.execute(
        """SELECT amount, event_date, source, round_stage, raw_data
           FROM funding_events
           WHERE entity_id = ? AND event_type = 'REG_D_FILING'
           ORDER BY event_date""",
        (entity_id,),
    ).fetchall()

    if not regd:
        lines.append("*No Reg D filings found. No private capital raised on record.*\n")
        return "\n".join(lines)

    total = sum(float(r["amount"] or 0) for r in regd)
    lines.append(f"**Total Private Capital:** {_fmt_currency(total)} across {len(regd)} filing{'s' if len(regd) > 1 else ''}")
    lines.append("")

    lines.append("| Date | Amount | Round Stage | Source |")
    lines.append("|------|--------|-------------|--------|")
    for r in regd:
        lines.append(
            f"| {_fmt_date(r['event_date'])} | {_fmt_currency(r['amount'])} | "
            f"{r['round_stage'] or 'N/A'} | {r['source'] or 'N/A'} |"
        )
    lines.append("")

    # Timeline relative to government milestones
    first_sbir = conn.execute(
        """SELECT MIN(event_date) as d FROM funding_events
           WHERE entity_id = ? AND event_type IN ('SBIR_PHASE_1','SBIR_PHASE_2','SBIR_PHASE_3')""",
        (entity_id,),
    ).fetchone()

    first_p2 = conn.execute(
        """SELECT MIN(event_date) as d FROM funding_events
           WHERE entity_id = ? AND event_type = 'SBIR_PHASE_2'""",
        (entity_id,),
    ).fetchone()

    first_contract = conn.execute(
        "SELECT MIN(award_date) as d FROM contracts WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()

    first_raise_date = _parse_date(regd[0]["event_date"])
    milestones = []
    if first_sbir and first_sbir["d"]:
        gap = _months_between(first_sbir["d"], regd[0]["event_date"])
        if gap is not None:
            milestones.append(f"First raise was {abs(gap)} months {'after' if gap >= 0 else 'before'} first SBIR")
    if first_p2 and first_p2["d"]:
        gap = _months_between(first_p2["d"], regd[0]["event_date"])
        if gap is not None:
            milestones.append(f"{abs(gap)} months {'after' if gap >= 0 else 'before'} first Phase II")
    if first_contract and first_contract["d"]:
        gap = _months_between(first_contract["d"], regd[0]["event_date"])
        if gap is not None:
            milestones.append(f"{abs(gap)} months {'after' if gap >= 0 else 'before'} first contract")

    if milestones:
        lines.append("**Timeline relative to government milestones:**")
        for m in milestones:
            lines.append(f"- {m}")
        lines.append("")

    return "\n".join(lines)


def build_signal_profile(conn: sqlite3.Connection, entity_id: str) -> str:
    """Section 4: Signal Profile with composite scoring."""
    lines = ["## Signal Profile", ""]

    signals = conn.execute(
        """SELECT signal_type, confidence_score, detected_date, evidence,
                  status, freshness_weight
           FROM signals WHERE entity_id = ? AND status = 'ACTIVE'
           ORDER BY confidence_score DESC""",
        (entity_id,),
    ).fetchall()

    if not signals:
        lines.append("*No active signals detected.*\n")
        return "\n".join(lines)

    # Compute composite score
    positive_score = 0.0
    negative_score = 0.0
    positive_signals = []
    negative_signals = []

    for sig in signals:
        weight = ALL_WEIGHTS.get(sig["signal_type"], 0.0)
        confidence = float(sig["confidence_score"] or 0)
        freshness = float(sig["freshness_weight"] or 1.0)
        weighted = weight * confidence * freshness
        display = SIGNAL_DISPLAY_NAMES.get(sig["signal_type"], sig["signal_type"])

        entry = {
            "name": display,
            "type": sig["signal_type"],
            "score": round(weighted, 2),
            "confidence": confidence,
            "freshness": freshness,
        }

        if weight > 0:
            positive_score += weighted
            positive_signals.append(entry)
        elif weight < 0:
            negative_score += weighted
            negative_signals.append(entry)

    positive_signals.sort(key=lambda x: -x["score"])
    negative_signals.sort(key=lambda x: x["score"])

    composite = round(positive_score + negative_score, 2)
    freshness_adj = composite  # already freshness-weighted

    if composite >= 5.0:
        tier = "Tier 1"
    elif composite >= 3.0:
        tier = "Tier 2"
    elif composite >= 1.0:
        tier = "Tier 3"
    else:
        tier = "Unscored"

    lines.append(f"**Composite Score:** {composite:.2f} ({tier})")
    lines.append(f"  - Positive: +{positive_score:.2f} | Negative: {negative_score:.2f}")
    lines.append("")

    # Signal table
    lines.append("| Signal | Weight | Confidence | Freshness | Score |")
    lines.append("|--------|--------|------------|-----------|-------|")
    for s in positive_signals:
        lines.append(
            f"| [+] {s['name']} | {ALL_WEIGHTS[s['type']]:.1f} | "
            f"{s['confidence']:.2f} | {s['freshness']:.2f} | +{s['score']:.2f} |"
        )
    for s in negative_signals:
        lines.append(
            f"| [-] {s['name']} | {ALL_WEIGHTS[s['type']]:.1f} | "
            f"{s['confidence']:.2f} | {s['freshness']:.2f} | {s['score']:.2f} |"
        )
    lines.append("")

    return "\n".join(lines)


def _extract_policy_scores(pa: dict) -> dict:
    """Extract priority scores from policy_alignment, handling nested 'scores' key."""
    geo_keys = {"pacific_relevance", "nato_interoperability", "arctic_operations"}
    meta_keys = {"top_priorities", "policy_tailwind_score", "reasoning", "scored_date", "scores"}
    scores = {}

    # Handle nested "scores" dict
    score_source = pa.get("scores", pa)
    for key, val in score_source.items():
        if key in geo_keys or key in meta_keys:
            continue
        if isinstance(val, (int, float)):
            scores[key] = float(val)
    return scores


def build_policy_alignment(entity: dict) -> str:
    """Section 5: Policy Alignment."""
    lines = ["## Policy Alignment", ""]

    pa = _parse_json(entity.get("policy_alignment"))
    if not pa:
        lines.append("*No policy alignment data available.*\n")
        return "\n".join(lines)

    scores = _extract_policy_scores(pa)

    if not scores:
        lines.append("*No priority scores found in alignment data.*\n")
        return "\n".join(lines)

    # Top 3 priorities
    sorted_priorities = sorted(scores.items(), key=lambda x: -x[1])
    lines.append("**Top Priority Areas:**")
    lines.append("")
    lines.append("| Priority | Score | Budget Weight | Budget Direction |")
    lines.append("|----------|-------|---------------|------------------|")
    for key, score in sorted_priorities[:3]:
        bw = BUDGET_WEIGHTS.get(key, 1.0)
        bd = BUDGET_DIRECTION.get(key, "N/A")
        label = key.replace("_", " ").title()
        lines.append(f"| {label} | {score:.2f} | {bw:.2f}x | {bd} |")
    lines.append("")

    # Policy tailwind score (only priorities with score > 0.2)
    tailwind_num = 0.0
    tailwind_den = 0.0
    for key, score in scores.items():
        if score > 0.2:
            bw = BUDGET_WEIGHTS.get(key, 1.0)
            tailwind_num += score * bw
            tailwind_den += bw

    tailwind = tailwind_num / tailwind_den if tailwind_den > 0 else 0.0
    lines.append(f"**Policy Tailwind Score:** {tailwind:.3f}")

    lines.append("")
    return "\n".join(lines)


def build_lifecycle_position(
    conn: sqlite3.Connection, entity_id: str, entity: dict
) -> str:
    """Section 6: Lifecycle Position — narrative with dated progression."""
    lines = ["## Lifecycle Position", ""]

    # Gather data points
    sbir_counts = conn.execute(
        """SELECT event_type, COUNT(*) as cnt, SUM(amount) as total
           FROM funding_events
           WHERE entity_id = ? AND event_type IN ('SBIR_PHASE_1','SBIR_PHASE_2','SBIR_PHASE_3')
           GROUP BY event_type""",
        (entity_id,),
    ).fetchall()

    phase_counts = {r["event_type"]: r["cnt"] for r in sbir_counts}
    p1 = phase_counts.get("SBIR_PHASE_1", 0)
    p2 = phase_counts.get("SBIR_PHASE_2", 0)
    p3 = phase_counts.get("SBIR_PHASE_3", 0)
    total_sbirs = p1 + p2 + p3

    # Key dates
    first_p1 = conn.execute(
        "SELECT MIN(event_date) as d FROM funding_events WHERE entity_id = ? AND event_type = 'SBIR_PHASE_1'",
        (entity_id,),
    ).fetchone()
    first_p2 = conn.execute(
        "SELECT MIN(event_date) as d FROM funding_events WHERE entity_id = ? AND event_type = 'SBIR_PHASE_2'",
        (entity_id,),
    ).fetchone()
    last_p2 = conn.execute(
        "SELECT MAX(event_date) as d FROM funding_events WHERE entity_id = ? AND event_type = 'SBIR_PHASE_2'",
        (entity_id,),
    ).fetchone()
    first_p3 = conn.execute(
        "SELECT MIN(event_date) as d FROM funding_events WHERE entity_id = ? AND event_type = 'SBIR_PHASE_3'",
        (entity_id,),
    ).fetchone()

    contracts = conn.execute(
        """SELECT contract_value, procurement_type, award_date FROM contracts
           WHERE entity_id = ? ORDER BY award_date""",
        (entity_id,),
    ).fetchall()

    contract_count = len(contracts)
    max_contract = max((float(c["contract_value"] or 0) for c in contracts), default=0)
    has_production = any(float(c["contract_value"] or 0) > 1_000_000 for c in contracts)
    first_contract_date = contracts[0]["award_date"] if contracts else None

    regd_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM funding_events WHERE entity_id = ? AND event_type = 'REG_D_FILING'",
        (entity_id,),
    ).fetchone()["cnt"]

    regd_total = float(conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM funding_events WHERE entity_id = ? AND event_type = 'REG_D_FILING'",
        (entity_id,),
    ).fetchone()["total"])

    first_regd = conn.execute(
        "SELECT MIN(event_date) as d FROM funding_events WHERE entity_id = ? AND event_type = 'REG_D_FILING'",
        (entity_id,),
    ).fetchone()

    # Determine lifecycle stage
    if p3 > 0 or (has_production and contract_count > 0):
        stage = "Production"
    elif contract_count > 1 and regd_total > 0:
        stage = "Growth"
    elif p2 > 0 or (contract_count > 0 and max_contract <= 1_000_000):
        stage = "Prototype"
    else:
        stage = "Pre-revenue R&D"

    lines.append(f"**Stage:** {stage}")
    lines.append("")

    # Build narrative progression (3-4 sentences with dates)
    name = entity["canonical_name"]
    narrative = []

    # Sentence 1: SBIR origin
    if total_sbirs > 0 and first_p1 and first_p1["d"]:
        sbir_total_val = sum(float(r["total"] or 0) for r in sbir_counts)
        narrative.append(
            f"{name} entered the DoD ecosystem with its first Phase I SBIR in "
            f"{_fmt_date(first_p1['d'])}, and has since accumulated {total_sbirs} "
            f"SBIR awards ({p1} Phase I, {p2} Phase II"
            f"{f', {p3} Phase III' if p3 else ''}"
            f") totaling {_fmt_currency(sbir_total_val)}."
        )
    elif total_sbirs > 0:
        sbir_total_val = sum(float(r["total"] or 0) for r in sbir_counts)
        narrative.append(
            f"{name} holds {total_sbirs} SBIR awards totaling {_fmt_currency(sbir_total_val)}."
        )

    # Sentence 2: Phase II progression
    if p2 > 0 and first_p2 and first_p2["d"]:
        p1_to_p2 = _months_between(first_p1["d"], first_p2["d"]) if first_p1 and first_p1["d"] else None
        grad_str = f" — {p1_to_p2} months from first Phase I to first Phase II" if p1_to_p2 else ""
        last_p2_str = f", with the most recent in {_fmt_date(last_p2['d'])}" if last_p2 and last_p2["d"] and last_p2["d"] != first_p2["d"] else ""
        narrative.append(
            f"The company achieved Phase II in {_fmt_date(first_p2['d'])}{grad_str}{last_p2_str}."
        )

    # Sentence 3: Contract traction
    if contract_count > 0:
        total_cv = sum(float(c["contract_value"] or 0) for c in contracts)
        multi = f", with {contract_count} contracts totaling {_fmt_currency(total_cv)}" if contract_count > 1 else ""
        narrative.append(
            f"It secured its first production contract ({_fmt_currency(max_contract)}, "
            f"{contracts[0]['procurement_type'] or 'standard'}) in {_fmt_date(first_contract_date)}{multi}."
        )
    else:
        narrative.append("No production contracts have been awarded to date.")

    # Sentence 4: Private capital status
    if regd_count > 0 and first_regd and first_regd["d"]:
        narrative.append(
            f"Private capital activity began in {_fmt_date(first_regd['d'])}, "
            f"with {_fmt_currency(regd_total)} raised across {regd_count} "
            f"Reg D filing{'s' if regd_count > 1 else ''}."
        )
    else:
        narrative.append(
            "No private capital has been raised on record, suggesting the company has "
            "been self-sustaining on government funding."
        )

    lines.append(" ".join(narrative))
    lines.append("")

    return "\n".join(lines)


def _get_entity_sbir_regd_stats(conn: sqlite3.Connection, eid: str) -> dict:
    """Get SBIR counts, Reg D amounts, and contract info for a single entity."""
    sbir_row = conn.execute(
        """SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total
           FROM funding_events
           WHERE entity_id = ? AND event_type IN ('SBIR_PHASE_1','SBIR_PHASE_2','SBIR_PHASE_3')""",
        (eid,),
    ).fetchone()

    p2_row = conn.execute(
        """SELECT COUNT(*) as cnt FROM funding_events
           WHERE entity_id = ? AND event_type = 'SBIR_PHASE_2'""",
        (eid,),
    ).fetchone()

    p1_row = conn.execute(
        """SELECT COUNT(*) as cnt FROM funding_events
           WHERE entity_id = ? AND event_type = 'SBIR_PHASE_1'""",
        (eid,),
    ).fetchone()

    regd_rows = conn.execute(
        """SELECT amount, event_date FROM funding_events
           WHERE entity_id = ? AND event_type = 'REG_D_FILING'
           ORDER BY event_date""",
        (eid,),
    ).fetchall()

    contract_row = conn.execute(
        """SELECT COUNT(*) as cnt, COALESCE(SUM(contract_value), 0) as total
           FROM contracts WHERE entity_id = ?""",
        (eid,),
    ).fetchone()

    first_p2 = conn.execute(
        """SELECT MIN(event_date) as d FROM funding_events
           WHERE entity_id = ? AND event_type = 'SBIR_PHASE_2'""",
        (eid,),
    ).fetchone()

    regd_total = sum(float(r["amount"] or 0) for r in regd_rows)
    first_raise_date = regd_rows[0]["event_date"] if regd_rows else None
    first_raise_amt = float(regd_rows[0]["amount"] or 0) if regd_rows else 0

    # SBIRs and P2s at time of first raise
    sbirs_at_raise = 0
    p2s_at_raise = 0
    if first_raise_date:
        sbir_at = conn.execute(
            """SELECT COUNT(*) as cnt FROM funding_events
               WHERE entity_id = ? AND event_type IN ('SBIR_PHASE_1','SBIR_PHASE_2','SBIR_PHASE_3')
               AND event_date <= ?""",
            (eid, first_raise_date),
        ).fetchone()
        p2_at = conn.execute(
            """SELECT COUNT(*) as cnt FROM funding_events
               WHERE entity_id = ? AND event_type = 'SBIR_PHASE_2'
               AND event_date <= ?""",
            (eid, first_raise_date),
        ).fetchone()
        sbirs_at_raise = sbir_at["cnt"]
        p2s_at_raise = p2_at["cnt"]

    p2_to_raise_months = None
    if first_p2 and first_p2["d"] and first_raise_date:
        p2_to_raise_months = _months_between(first_p2["d"], first_raise_date)

    return {
        "sbir_count": sbir_row["cnt"],
        "sbir_total": float(sbir_row["total"]),
        "p1_count": p1_row["cnt"],
        "p2_count": p2_row["cnt"],
        "regd_total": regd_total,
        "regd_count": len(regd_rows),
        "first_raise_amount": first_raise_amt,
        "first_raise_date": first_raise_date,
        "contract_count": contract_row["cnt"],
        "contract_total": float(contract_row["total"]),
        "p2_to_raise_months": p2_to_raise_months,
        "sbirs_at_raise": sbirs_at_raise,
        "p2s_at_raise": p2s_at_raise,
        "first_p2_date": first_p2["d"] if first_p2 else None,
    }


def build_comparables(
    conn: sqlite3.Connection, entity_id: str, entity: dict
) -> str:
    """Section 7: Comparables Analysis."""
    lines = ["## Comparables Analysis", ""]

    core_business = entity.get("core_business")
    pa = _parse_json(entity.get("policy_alignment"))

    # Target stats
    target_stats = _get_entity_sbir_regd_stats(conn, entity_id)
    target_sbir = target_stats["sbir_count"]

    # Find target's top policy score
    target_top_key = None
    target_top_score = 0.0
    if pa:
        target_scores = _extract_policy_scores(pa)
        for key, val in target_scores.items():
            if val > target_top_score:
                target_top_score = val
                target_top_key = key

    # Build candidate pool: policy-aligned startups (primary), then same core_business
    # This matches the benchmark methodology: find all startups aligned to the
    # target's top policy area, regardless of core_business classification.
    existing_ids = set()
    candidates = []

    # Primary: policy alignment match (target's top priority >= 0.5)
    if target_top_key:
        policy_candidates = conn.execute(
            """SELECT e.id, e.canonical_name, e.core_business, e.policy_alignment
               FROM entities e
               WHERE e.merged_into_id IS NULL
                 AND e.entity_type = 'STARTUP'
                 AND e.id != ?
                 AND e.policy_alignment IS NOT NULL""",
            (entity_id,),
        ).fetchall()
        for pc in policy_candidates:
            pc_pa = _parse_json(pc["policy_alignment"])
            if pc_pa:
                pc_scores = _extract_policy_scores(pc_pa)
                if target_top_key in pc_scores and pc_scores[target_top_key] >= 0.5:
                    candidates.append(pc)
                    existing_ids.add(pc["id"])

    # Secondary: same core_business (catch any that weren't policy-scored)
    cb_candidates = conn.execute(
        """SELECT e.id, e.canonical_name, e.core_business, e.policy_alignment
           FROM entities e
           WHERE e.merged_into_id IS NULL
             AND e.entity_type = 'STARTUP'
             AND e.core_business = ?
             AND e.id != ?""",
        (core_business, entity_id),
    ).fetchall()
    for c in cb_candidates:
        if c["id"] not in existing_ids:
            candidates.append(c)
            existing_ids.add(c["id"])

    # Filter and collect stats for each candidate
    sbir_min = max(3, int(target_sbir * 0.5))
    sbir_max = max(20, int(target_sbir * 2))
    comps = []
    for c in candidates:
        cid = c["id"]
        stats = _get_entity_sbir_regd_stats(conn, cid)

        # Must have at least one Reg D with total >= $50K
        if stats["regd_count"] == 0 or stats["regd_total"] < 50_000:
            continue
        # SBIR count within 0.5x-2x of target
        if stats["sbir_count"] < sbir_min or stats["sbir_count"] > sbir_max:
            continue
        # Must have at least 1 Phase II (eliminates tangential SBIR touches)
        if stats["p2_count"] < 1:
            continue

        # Policy alignment — extract comp scores
        c_pa = _parse_json(c["policy_alignment"])
        c_scores = _extract_policy_scores(c_pa) if c_pa else {}
        c_top_score = 0.0
        if c_scores and target_top_key:
            c_top_score = c_scores.get(target_top_key, 0.0)

        # Compute tailwind for comp (only priorities with score > 0.2)
        comp_tailwind = 0.0
        if c_scores:
            tw_num = 0.0
            tw_den = 0.0
            for key, val in c_scores.items():
                if val > 0.2:
                    bw = BUDGET_WEIGHTS.get(key, 1.0)
                    tw_num += val * bw
                    tw_den += bw
            comp_tailwind = tw_num / tw_den if tw_den > 0 else 0.0

        comps.append({
            "id": cid,
            "name": c["canonical_name"],
            "core_business": c["core_business"],
            **stats,
            "policy_top_score": c_top_score,
            "tailwind": comp_tailwind,
        })

    comps.sort(key=lambda x: -x["regd_total"])

    method_desc = []
    if target_top_key:
        method_desc.append(f"{target_top_key.replace('_', ' ')}-aligned ({target_top_key.replace('_', ' ')} >= 0.5)")
    if core_business:
        method_desc.append(f"same core business ({core_business})")
    lines.append(
        f"**Methodology:** {len(comps)} comparable companies "
        f"({' + '.join(method_desc)}) "
        f"with {sbir_min}-{sbir_max} SBIR awards, at least 1 Phase II, "
        f"and at least one Reg D filing with reported capital raised."
    )
    lines.append("")

    if not comps:
        lines.append("*No comparable companies found matching the criteria.*\n")
        return "\n".join(lines)

    # Score each comp by profile similarity to target (used for table + ranking)
    for c in comps:
        sim = 0.0
        if target_sbir > 0:
            sim += max(0, 1.0 - abs(c["sbir_count"] - target_sbir) / target_sbir) * 2.0
        target_p2 = target_stats["p2_count"]
        if target_p2 > 0:
            sim += max(0, 1.0 - abs(c["p2_count"] - target_p2) / max(target_p2, 1)) * 1.5
        target_sbir_val = target_stats["sbir_total"]
        if target_sbir_val > 0:
            sim += max(0, 1.0 - abs(c["sbir_total"] - target_sbir_val) / target_sbir_val) * 1.0
        if target_top_score > 0:
            sim += max(0, 1.0 - abs(c["policy_top_score"] - target_top_score) / max(target_top_score, 0.1)) * 1.0
        target_contracts = target_stats["contract_count"]
        if target_contracts > 0 and c["contract_count"] > 0:
            sim += 1.5
        elif target_contracts == 0 and c["contract_count"] == 0:
            sim += 0.5
        c["similarity_score"] = sim

    comps.sort(key=lambda x: -x["similarity_score"])

    # Comparables table — top 15 by profile similarity
    display_count = min(15, len(comps))
    lines.append(f"### Closest Comparables (top {display_count} by profile similarity)")
    lines.append("")
    lines.append(
        "| # | Company | SBIRs | P2 | First Raise | Total Raised "
        "| Months P2\u2192Raise | Contracts | Ctr Value |"
    )
    lines.append(
        "|---|---------|------:|---:|----------:|-----------:"
        "|-------:|--------:|--------:|"
    )

    for i, c in enumerate(comps[:display_count], 1):
        p2_raise_str = "N/A"
        if c["p2_to_raise_months"] is not None:
            m = c["p2_to_raise_months"]
            p2_raise_str = f"{m:+d}"

        lines.append(
            f"| {i} | {c['name']} | {c['sbir_count']} | {c['p2_count']} | "
            f"{_fmt_currency(c['first_raise_amount'])} | {_fmt_currency(c['regd_total'])} | "
            f"{p2_raise_str} | {c['contract_count']} | {_fmt_currency(c['contract_total'])} |"
        )

    lines.append("")
    lines.append(
        "*Months P2\u2192Raise: months from first Phase II to first private raise. "
        "Negative values mean the company raised before Phase II.*"
    )
    lines.append("")

    # Market Benchmarks (computed over full comp set, not just displayed)
    lines.append("### Market Benchmarks")
    lines.append("")

    totals = [c["regd_total"] for c in comps]
    first_raises = [c["first_raise_amount"] for c in comps if c["first_raise_amount"] > 0]

    lines.append("#### Capital Raised")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| **Median total raised** | **{_fmt_currency(statistics.median(totals))}** |")
    lines.append(f"| Mean total raised | {_fmt_currency(statistics.mean(totals))} |")
    if len(totals) >= 4:
        q = statistics.quantiles(totals, n=4)
        lines.append(f"| 25th percentile | {_fmt_currency(q[0])} |")
        lines.append(f"| 75th percentile | {_fmt_currency(q[2])} |")
    lines.append(f"| Range | {_fmt_currency(min(totals))} \u2014 {_fmt_currency(max(totals))} |")
    if first_raises:
        lines.append(f"| **Median first raise** | **{_fmt_currency(statistics.median(first_raises))}** |")
        lines.append(f"| Mean first raise | {_fmt_currency(statistics.mean(first_raises))} |")
    lines.append("")

    # P2 to raise timing
    p2_gaps = [c["p2_to_raise_months"] for c in comps if c["p2_to_raise_months"] is not None]
    if p2_gaps:
        before_p2 = sum(1 for g in p2_gaps if g < 0)
        after_p2 = sum(1 for g in p2_gaps if g > 0)
        after_gaps = [g for g in p2_gaps if g > 0]

        lines.append("#### Timing: Phase II to First Raise")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Companies that raised BEFORE Phase II | {before_p2} of {len(comps)} ({before_p2*100//len(comps)}%) |")
        lines.append(f"| Companies that raised AFTER Phase II | {after_p2} of {len(comps)} ({after_p2*100//len(comps)}%) |")
        if after_gaps:
            lines.append(f"| Median gap (post-P2 raisers) | **{statistics.median(after_gaps):.0f} months** |")
            lines.append(f"| Mean gap (post-P2 raisers) | {statistics.mean(after_gaps):.1f} months |")
        lines.append("")

    # SBIR depth at raise
    sbirs_at = [c["sbirs_at_raise"] for c in comps if c["sbirs_at_raise"] > 0]
    p2s_at = [c["p2s_at_raise"] for c in comps]
    if sbirs_at:
        lines.append("#### SBIR Depth at Time of First Raise")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Median SBIRs at first raise | {statistics.median(sbirs_at):.0f} |")
        lines.append(f"| Mean SBIRs at first raise | {statistics.mean(sbirs_at):.1f} |")
        if p2s_at:
            lines.append(f"| Median Phase IIs at first raise | {statistics.median(p2s_at):.0f} |")
            lines.append(f"| Mean Phase IIs at first raise | {statistics.mean(p2s_at):.1f} |")
        lines.append("")

    # Contract traction correlation
    with_contracts = [c for c in comps if c["contract_count"] > 0]
    without_contracts = [c for c in comps if c["contract_count"] == 0]

    if with_contracts and without_contracts:
        lines.append("#### Contract Traction and Capital Raised")
        lines.append("")
        lines.append("| Segment | Count | Median Raised | Mean Raised |")
        lines.append("|---------|------:|-------------:|------------:|")
        wc_totals = [c["regd_total"] for c in with_contracts]
        wo_totals = [c["regd_total"] for c in without_contracts]
        lines.append(
            f"| With production contracts | {len(with_contracts)}/{len(comps)} | "
            f"{_fmt_currency(statistics.median(wc_totals))} | {_fmt_currency(statistics.mean(wc_totals))} |"
        )
        lines.append(
            f"| Without production contracts | {len(without_contracts)}/{len(comps)} | "
            f"{_fmt_currency(statistics.median(wo_totals))} | {_fmt_currency(statistics.mean(wo_totals))} |"
        )
        lines.append("")

    # Top 5 detailed comp profiles
    lines.append("### Top 5 Comparable Profiles")
    lines.append("")

    for i, c in enumerate(comps[:5], 1):
        lines.append(f"**{i}. {c['name']}**")
        lines.append(
            f"- **Profile:** {c['sbir_count']} SBIRs ({c['p1_count']} P1, {c['p2_count']} P2), "
            f"{_fmt_currency(c['sbir_total'])} SBIR value"
        )
        lines.append(f"- **Raised:** {_fmt_currency(c['regd_total'])} total")
        if c["first_raise_amount"] > 0:
            lines.append(f"- **First raise:** {_fmt_currency(c['first_raise_amount'])}")
        if c["p2_to_raise_months"] is not None:
            m = c["p2_to_raise_months"]
            direction = "after" if m >= 0 else "before"
            lines.append(f"- **Timing:** Raised {abs(m)} months {direction} first Phase II")
        lines.append(f"- **Contracts:** {c['contract_count']} ({_fmt_currency(c['contract_total'])})")
        lines.append("")

    return "\n".join(lines)


def build_analyst_assessment(
    sections_data: dict, entity: dict, no_claude: bool = False
) -> str:
    """Section 8: Analyst Assessment via Claude API."""
    lines = ["## Analyst Assessment", ""]

    if no_claude:
        lines.append("*Analyst assessment skipped (--no-claude flag).*\n")
        return "\n".join(lines)

    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        lines.append("*Analyst assessment skipped (ANTHROPIC_API_KEY not set).*\n")
        return "\n".join(lines)

    try:
        from anthropic import Anthropic
    except ImportError:
        lines.append("*Analyst assessment skipped (anthropic package not installed).*\n")
        return "\n".join(lines)

    client = Anthropic(api_key=api_key)

    report_date = date.today().strftime("%B %d, %Y")
    system_prompt = (
        "You are an Aperture Signals analyst. Write a concise, professional "
        "intelligence assessment based on the following data. Be specific. "
        "Reference numbers. Flag risks honestly. Do not hedge excessively. "
        f"Today's date is {report_date}. Frame all temporal references accordingly. "
        "Do not reference past dates as future events."
    )

    # Build data context from all sections
    context_parts = []
    context_parts.append(f"ENTITY: {entity['canonical_name']}")
    for section_name, section_md in sections_data.items():
        context_parts.append(f"\n--- {section_name.upper()} ---\n{section_md}")

    user_prompt = (
        f"Based on the following intelligence data for {entity['canonical_name']}, "
        f"write an assessment covering:\n"
        f"1. The investment case (what makes this company interesting)\n"
        f"2. Key risks (what could go wrong)\n"
        f"3. What would change the picture (catalysts or red flags to watch for)\n\n"
        f"Write 2-3 paragraphs. Be direct and data-driven.\n\n"
        f"{''.join(context_parts)}"
    )

    logger.info("Requesting analyst assessment from Claude...")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        assessment = response.content[0].text.strip()
        lines.append(assessment)
        lines.append("")
    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        lines.append(f"*Analyst assessment failed: {e}*\n")

    return "\n".join(lines)


# ── Report assembly ──────────────────────────────────────────────────────

def generate_deal_brief(
    entity_name: str,
    output_path: str | None = None,
    no_claude: bool = False,
    pdf: bool = False,
) -> str:
    """Generate a full deal intelligence brief for the given entity."""
    conn = _connect()

    # Lookup entity
    entity = lookup_entity(conn, entity_name)
    if entity is None:
        print(f"Error: Entity '{entity_name}' not found in database.")
        sys.exit(1)

    entity_id = entity["id"]
    name = entity["canonical_name"]
    report_date = date.today().strftime("%B %d, %Y")

    print(f"Generating deal brief for: {name}")

    # Build all sections
    sections = {}

    sections["Company Profile"] = build_company_profile(entity)
    print("  [1/8] Company Profile")

    sections["Government Traction"] = build_government_traction(conn, entity_id)
    print("  [2/8] Government Traction")

    sections["Private Capital Activity"] = build_private_capital(conn, entity_id)
    print("  [3/8] Private Capital Activity")

    sections["Signal Profile"] = build_signal_profile(conn, entity_id)
    print("  [4/8] Signal Profile")

    sections["Policy Alignment"] = build_policy_alignment(entity)
    print("  [5/8] Policy Alignment")

    sections["Lifecycle Position"] = build_lifecycle_position(conn, entity_id, entity)
    print("  [6/8] Lifecycle Position")

    sections["Comparables Analysis"] = build_comparables(conn, entity_id, entity)
    print("  [7/8] Comparables Analysis")

    sections["Analyst Assessment"] = build_analyst_assessment(
        sections, entity, no_claude=no_claude
    )
    print("  [8/8] Analyst Assessment")

    # Assemble markdown
    md_parts = [
        f"# Deal Intelligence Brief: {name}",
        "",
        f"**Date:** {report_date}",
        f"**Query Type:** Deal Analysis",
        "",
        "---",
        "",
    ]

    for section_md in sections.values():
        md_parts.append(section_md)
        md_parts.append("---\n")

    md_parts.append(
        f"*Analysis generated from Aperture Signals knowledge graph. "
        f"Data sourced from SBIR.gov, SEC EDGAR, and USASpending.gov.*"
    )

    report = "\n".join(md_parts)

    # Determine output path
    if output_path is None:
        output_path = f"reports/brief_{_slug(name)}.md"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\nReport written to: {out}")

    # Optional PDF
    if pdf:
        try:
            from scripts.generate_pdf_report import build_pdf
            pdf_path = out.with_suffix(".pdf")
            # build_pdf expects prospect-style data; for deal briefs we just
            # convert the markdown. This is a minimal integration.
            print(f"PDF generation not yet integrated for deal briefs.")
        except ImportError:
            print("PDF generation requires fpdf2. Install with: pip install fpdf2")

    conn.close()
    return str(out)


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Aperture Query — Intelligence brief generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/aperture_query.py --type deal --entity "Scout Space"
  python scripts/aperture_query.py --type deal --entity "Scout Space" --no-claude
  python scripts/aperture_query.py --type deal --entity "Scout Space" --output reports/scout.md
        """,
    )
    parser.add_argument(
        "--type", required=True, choices=["deal"],
        help="Query type (currently only 'deal' is supported)",
    )
    parser.add_argument(
        "--entity", required=True,
        help="Entity name to analyze",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output file path (default: reports/brief_{entity_slug}.md)",
    )
    parser.add_argument(
        "--pdf", action="store_true",
        help="Also generate PDF output",
    )
    parser.add_argument(
        "--no-claude", action="store_true",
        help="Skip analyst assessment (no API calls)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.type == "deal":
        generate_deal_brief(
            entity_name=args.entity,
            output_path=args.output,
            no_claude=args.no_claude,
            pdf=args.pdf,
        )


if __name__ == "__main__":
    main()
