#!/usr/bin/env python3
"""
Aperture Signals — Employment Target Identifier

Identifies top 20 small defense startups optimized for employment by a
transitioning Marine Corps helicopter pilot/instructor and JTAC (1st ANGLICO).

Background: kill chain coordination, close air support, joint/coalition fires
integration, sensor-to-shooter execution, multi-domain coordination, and
operating in degraded/denied communications environments.

Scores companies on composite signal strength, signal diversity, policy tailwind,
momentum recency, and KOP alignment, with a domain preference multiplier for
sectors where a Marine aviator/JTAC has direct domain credibility.

Usage:
    python scripts/employment_targets.py
"""

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "defense_alpha.db"
REPORT_DIR = Path(__file__).parent.parent / "reports"

# ---------------------------------------------------------------------------
# Signal weight definitions (mirrors calculate_composite_scores.py)
# ---------------------------------------------------------------------------
POSITIVE_WEIGHTS = {
    "jar_funding": 3.5,
    "sbir_to_contract_transition": 3.0,
    "meia_experimentation": 3.0,
    "rapid_contract_growth": 2.5,
    "kop_alignment": 2.5,
    "sbir_validated_raise": 2.5,
    "sbir_to_vc_raise": 2.0,
    "outsized_award": 2.0,
    "sbir_phase_2_transition": 1.5,
    "sbir_phase_3_transition": 2.0,
    "pae_portfolio": 2.0,
    "multi_agency_interest": 1.5,
    "high_priority_technology": 1.0,
    "first_dod_contract": 1.0,
    "sbir_graduation_speed": 1.5,
    "time_to_contract": 2.0,
    "funding_velocity": 1.5,
    "commercial_pathway_fit": 1.5,
}

NEGATIVE_WEIGHTS = {
    "sbir_stalled": -2.0,
    "customer_concentration": -1.5,
    "gone_stale": -1.5,
    "sbir_lapse_risk": -1.5,
}

ALL_WEIGHTS = {**POSITIVE_WEIGHTS, **NEGATIVE_WEIGHTS}
POSITIVE_SIGNAL_TYPES = set(POSITIVE_WEIGHTS.keys())

# ---------------------------------------------------------------------------
# Freshness decay profiles (mirrors calculate_composite_scores.py)
# ---------------------------------------------------------------------------
FAST_DECAY = [(182, 1.0), (365, 0.7), (730, 0.4), (None, 0.2)]
SLOW_DECAY = [(365, 1.0), (730, 0.85), (1095, 0.65), (None, 0.4)]
NO_DECAY = [(None, 1.0)]

SIGNAL_DECAY_PROFILES = {
    "funding_velocity": FAST_DECAY,
    "rapid_contract_growth": FAST_DECAY,
    "first_dod_contract": FAST_DECAY,
    "meia_experimentation": FAST_DECAY,
    "sbir_lapse_risk": FAST_DECAY,
    "sbir_phase_2_transition": SLOW_DECAY,
    "sbir_phase_3_transition": SLOW_DECAY,
    "sbir_to_contract_transition": SLOW_DECAY,
    "sbir_to_vc_raise": SLOW_DECAY,
    "sbir_graduation_speed": SLOW_DECAY,
    "time_to_contract": SLOW_DECAY,
    "outsized_award": SLOW_DECAY,
    "sbir_validated_raise": SLOW_DECAY,
    "jar_funding": SLOW_DECAY,
    "customer_concentration": NO_DECAY,
    "multi_agency_interest": NO_DECAY,
    "high_priority_technology": NO_DECAY,
    "sbir_stalled": NO_DECAY,
    "gone_stale": NO_DECAY,
    "kop_alignment": NO_DECAY,
    "pae_portfolio": NO_DECAY,
    "commercial_pathway_fit": NO_DECAY,
}

# ---------------------------------------------------------------------------
# Domain preference — sectors where a Marine pilot/JTAC has direct credibility
# ---------------------------------------------------------------------------
PREFERRED_DOMAINS = {
    "jadc2",                 # kill chain integration, battle management, C2
    "autonomous_systems",    # CCA, autonomous wingman, UAS-enabled CAS, HMT
    "electronic_warfare",    # contested/denied comms, anti-jam, GPS-denied nav
    "space_resilience",      # ISR, PNT alternatives, sensor fusion
}
DOMAIN_MULTIPLIER = 1.15

# FY26 budget growth for display
DOMAIN_GROWTH = {
    "jadc2": "+10%",
    "autonomous_systems": "+10%",
    "electronic_warfare": "+10%",
    "space_resilience": "+38%",
    "contested_logistics": "+10%",
    "nuclear_modernization": "+17%",
    "supply_chain_resilience": "+7%",
    "border_homeland": "+10%",
    "cyber_offense_defense": "+10%",
    "hypersonics": "-43%",
}

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------
W_COMPOSITE = 0.30
W_SIGNAL_DIVERSITY = 0.25
W_POLICY_TAILWIND = 0.20
W_MOMENTUM_RECENCY = 0.15
W_KOP_ALIGNMENT = 0.10

# Friendly signal names
SIGNAL_DISPLAY = {
    "sbir_to_contract_transition": "SBIR→Contract",
    "rapid_contract_growth": "Rapid Growth",
    "sbir_validated_raise": "Validated Raise",
    "sbir_to_vc_raise": "SBIR→VC Raise",
    "outsized_award": "Outsized Award",
    "sbir_phase_2_transition": "Phase II Transition",
    "multi_agency_interest": "Multi-Agency",
    "high_priority_technology": "Priority Tech",
    "first_dod_contract": "First DoD Contract",
    "sbir_graduation_speed": "Fast Graduation",
    "time_to_contract": "Time→Contract",
    "funding_velocity": "Funding Velocity",
    "kop_alignment": "KOP Aligned",
    "commercial_pathway_fit": "Commercial Pathway",
    "jar_funding": "JAR Funding",
    "meia_experimentation": "MEIA Experimentation",
    "pae_portfolio": "PAE Portfolio",
    "sbir_phase_3_transition": "Phase III",
    "customer_concentration": "Customer Concentration",
    "gone_stale": "Gone Stale",
    "sbir_stalled": "SBIR Stalled",
    "sbir_lapse_risk": "Lapse Risk",
}


def calc_freshness_weight(detected_date_str: str, signal_type: str) -> float:
    if not detected_date_str:
        return 0.5
    detected = datetime.strptime(detected_date_str, "%Y-%m-%d").date()
    days_old = (date.today() - detected).days
    profile = SIGNAL_DECAY_PROFILES.get(signal_type, SLOW_DECAY)
    for threshold, weight in profile:
        if threshold is None or days_old <= threshold:
            return weight
    return profile[-1][1]


def momentum_recency_score(latest_signal_date: str) -> float:
    """1.0 if <6mo, 0.7 if 6-12mo, 0.4 if 12-24mo, 0.0 otherwise."""
    if not latest_signal_date:
        return 0.0
    latest = datetime.strptime(latest_signal_date, "%Y-%m-%d").date()
    days_ago = (date.today() - latest).days
    if days_ago <= 182:
        return 1.0
    elif days_ago <= 365:
        return 0.7
    elif days_ago <= 730:
        return 0.4
    return 0.0


def composite_tier(raw_score: float) -> int:
    if raw_score >= 7.0:
        return 1
    elif raw_score >= 4.0:
        return 2
    return 3


def fmt(amount):
    if amount is None or amount == 0:
        return "$0"
    if abs(amount) >= 1_000_000_000:
        return f"${amount/1e9:.1f}B"
    if abs(amount) >= 1_000_000:
        return f"${amount/1e6:.1f}M"
    if abs(amount) >= 1_000:
        return f"${amount/1e3:.0f}K"
    return f"${amount:,.0f}"


def evidence_summary(evidence_json, signal_type: str) -> str:
    """Extract a 1-line summary from signal evidence JSON."""
    if not evidence_json:
        return ""
    try:
        ev = json.loads(evidence_json) if isinstance(evidence_json, str) else evidence_json
    except (json.JSONDecodeError, TypeError):
        return ""

    if signal_type == "kop_alignment":
        name = ev.get("kop_name", "")
        rank = ev.get("kop_rank", "?")
        indicators = ev.get("matching_indicators", [])
        return f"{name} (est. rank #{rank}) — matches: {', '.join(indicators[:3])}"
    elif signal_type == "sbir_to_contract_transition":
        ratio = ev.get("contract_to_sbir_ratio", 0)
        n_contracts = ev.get("post_sbir_contract_count", 0)
        return f"{n_contracts} post-SBIR contracts, {ratio:.1f}x SBIR-to-contract ratio"
    elif signal_type == "sbir_validated_raise":
        amt = ev.get("raise_amount_post_sbir", 0)
        seq = ev.get("sequence", "")
        return f"{fmt(amt)} raised post-SBIR ({seq.replace('_', ' ')})"
    elif signal_type == "multi_agency_interest":
        agencies = ev.get("agencies", [])
        return f"{len(agencies)} agencies: {', '.join(agencies[:4])}"
    elif signal_type == "rapid_contract_growth":
        growth = ev.get("growth_rate", ev.get("contract_growth_rate", 0))
        return f"{growth:.0%} contract value growth" if growth else "rapid growth detected"
    elif signal_type == "sbir_to_vc_raise":
        amt = ev.get("raise_amount_post_sbir", ev.get("total_raise_amount", 0))
        return f"{fmt(amt)} VC/private raise after SBIR activity"
    elif signal_type == "outsized_award":
        val = ev.get("contract_value", ev.get("award_value", 0))
        return f"{fmt(val)} award — significantly above peer median"
    elif signal_type == "funding_velocity":
        count = ev.get("filing_count", ev.get("regd_count", 0))
        return f"{count} Reg D filings in 18-month window"
    elif signal_type == "sbir_graduation_speed":
        months = ev.get("months_to_phase2", ev.get("graduation_months", 0))
        return f"Phase I→II in {months:.0f} months" if months else "fast SBIR graduation"
    elif signal_type == "time_to_contract":
        months = ev.get("months_sbir_to_contract", ev.get("months_to_contract", 0))
        return f"SBIR to production contract in {months:.0f} months" if months else "fast SBIR→contract"
    elif signal_type == "first_dod_contract":
        agency = ev.get("agency", ev.get("contracting_agency", ""))
        return f"first DoD contract from {agency}" if agency else "new DoD entrant"
    elif signal_type == "high_priority_technology":
        areas = ev.get("priority_areas", ev.get("matching_priorities", []))
        if isinstance(areas, list):
            return f"aligned to: {', '.join(areas[:3])}"
        return str(areas)[:80]
    elif signal_type == "commercial_pathway_fit":
        return ev.get("reasoning", ev.get("description", ""))[:80]
    elif signal_type == "customer_concentration":
        pct = ev.get("concentration_pct", ev.get("top_agency_pct", 0))
        agency = ev.get("top_agency", "")
        return f"{pct:.0%} revenue from {agency}" if agency else f"{pct:.0%} single-agency"
    elif signal_type == "sbir_lapse_risk":
        return ev.get("reason", ev.get("description", "SBIR-dependent, no diversification"))[:80]

    # Fallback: try to find any descriptive field
    for key in ("description", "reason", "reasoning", "summary", "entity_name"):
        if key in ev and ev[key]:
            return str(ev[key])[:80]
    return ""


def generate_domain_fit(entity: dict) -> str:
    """Generate a specific domain fit narrative for a Marine aviator/JTAC."""
    pa = entity["pa_scores"]
    cb = entity["core_business"]
    tags = entity["tech_tags"]
    sbir_titles = [s["title"].lower() for s in entity["sbir_titles"]]
    all_text = " ".join(sbir_titles + [t.lower() for t in tags] + [cb.lower()])

    parts = []

    # JADC2 / kill chain / C2
    if pa.get("jadc2", 0) >= 0.3 or any(
        kw in all_text
        for kw in ["command and control", "c2", "battle management", "kill chain",
                    "sensor-to-shooter", "targeting", "fire control", "decision",
                    "jadc2", "mission planning", "tactical data"]
    ):
        parts.append(
            "JADC2/C2 alignment — your experience coordinating kill chains, "
            "managing sensor-to-shooter timelines, and integrating joint fires "
            "maps directly to this company's battle management technology"
        )

    # Autonomous systems / UAS / CCA
    if pa.get("autonomous_systems", 0) >= 0.3 or any(
        kw in all_text
        for kw in ["autonomous", "uas", "uav", "drone", "unmanned", "wingman",
                    "human-machine", "swarm", "attritable", "cca", "robotic"]
    ):
        parts.append(
            "Autonomous systems — as a pilot who understands cockpit workload "
            "and manned-unmanned teaming, you bring operator perspective to "
            "human-machine interface design, autonomous CAS concepts, and "
            "UAS integration into existing kill chains"
        )

    # EW / denied/degraded comms
    if pa.get("electronic_warfare", 0) >= 0.3 or any(
        kw in all_text
        for kw in ["electronic warfare", "ew", "anti-jam", "gps-denied",
                    "spectrum", "contested", "denied", "degraded", "comms",
                    "communications", "rf", "signal", "jammer", "sigint"]
    ):
        parts.append(
            "EW/contested comms — ANGLICO operates daily in degraded/denied "
            "environments; your real-world experience with comm-degraded CAS, "
            "anti-jam operations, and GPS-denied navigation is exactly what "
            "these companies need for requirements validation"
        )

    # Space / ISR / PNT
    if pa.get("space_resilience", 0) >= 0.3 or any(
        kw in all_text
        for kw in ["satellite", "space", "isr", "pnt", "navigation",
                    "sensor fusion", "imaging", "reconnaissance", "overhead"]
    ):
        parts.append(
            "Space/ISR — the front end of the kill chain; your experience as "
            "a JTAC consuming ISR feeds, managing PNT dependencies, and "
            "coordinating sensor-to-shooter in real time makes you a credible "
            "voice for operational requirements"
        )

    # Targeting / fire support
    if any(
        kw in all_text
        for kw in ["targeting", "fire support", "close air", "cas",
                    "strike", "fires", "weapon", "munition", "guided",
                    "precision", "terminal guidance", "laser"]
    ):
        if not any("kill chain" in p for p in parts):
            parts.append(
                "Fires/targeting — direct CAS and JTAC experience gives you "
                "credibility with companies building targeting solutions, "
                "precision engagement tools, and fire support coordination systems"
            )

    # Coalition / multi-domain
    if any(
        kw in all_text
        for kw in ["coalition", "multi-domain", "interoperability", "joint",
                    "nato", "allied", "partner"]
    ):
        parts.append(
            "Joint/coalition interoperability — 1st ANGLICO's mission is "
            "integrating fires across joint and partner forces; direct "
            "experience with coalition interoperability challenges"
        )

    # Hardware/components fit
    if cb in ("RF_HARDWARE", "COMPONENTS", "SYSTEMS_INTEGRATOR"):
        if not any("RF" in p or "EW" in p for p in parts):
            parts.append(
                f"{cb} company — small hardware teams value operators who "
                "understand how their systems perform in real tactical environments"
            )

    if not parts:
        parts.append(
            "General defense technology — military aviation and fires "
            "experience, security clearance eligibility, and operational "
            "credibility are assets at any early-stage defense company"
        )

    return parts


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    today = date.today()
    cutoff_24mo = today.replace(year=today.year - 2).isoformat()

    # ------------------------------------------------------------------
    # Step 1: Get candidates passing hard filters
    # ------------------------------------------------------------------
    c.execute("""
        WITH positive_signals AS (
            SELECT
                entity_id,
                COUNT(DISTINCT signal_type) AS n_positive,
                COUNT(DISTINCT CASE WHEN signal_type != 'high_priority_technology'
                                    THEN signal_type END) AS n_non_hpt,
                MAX(detected_date) AS latest_signal
            FROM signals
            WHERE status = 'ACTIVE'
              AND signal_type NOT IN ('gone_stale', 'sbir_stalled',
                                      'customer_concentration', 'sbir_lapse_risk')
            GROUP BY entity_id
        ),
        negative_check AS (
            SELECT DISTINCT entity_id FROM signals
            WHERE status = 'ACTIVE'
              AND signal_type IN ('gone_stale', 'sbir_stalled')
        ),
        sbir_p2 AS (
            SELECT entity_id, COUNT(*) AS p2_count FROM funding_events
            WHERE event_type = 'SBIR_PHASE_2'
            GROUP BY entity_id
        ),
        sbir_p1 AS (
            SELECT entity_id, COUNT(*) AS p1_count FROM funding_events
            WHERE event_type = 'SBIR_PHASE_1'
            GROUP BY entity_id
        ),
        regd_total AS (
            SELECT entity_id, SUM(amount) AS total_regd,
                   COUNT(*) AS regd_count FROM funding_events
            WHERE event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
            GROUP BY entity_id
        ),
        regd_recent AS (
            SELECT entity_id, amount AS recent_regd_amount,
                   event_date AS recent_regd_date
            FROM funding_events
            WHERE event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
              AND id IN (
                  SELECT id FROM funding_events f2
                  WHERE f2.entity_id = funding_events.entity_id
                    AND f2.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
                  ORDER BY f2.event_date DESC LIMIT 1
              )
        ),
        contract_total AS (
            SELECT entity_id, SUM(contract_value) AS total_contracts,
                   COUNT(*) AS contract_count
            FROM contracts
            GROUP BY entity_id
        ),
        largest_contract AS (
            SELECT entity_id, contract_value AS largest_value,
                   contracting_agency AS largest_agency,
                   award_date AS largest_date
            FROM contracts c1
            WHERE contract_value = (
                SELECT MAX(contract_value) FROM contracts c2
                WHERE c2.entity_id = c1.entity_id
            )
        )
        SELECT
            e.id, e.canonical_name, e.core_business,
            e.policy_alignment, e.technology_tags,
            ps.n_positive, ps.n_non_hpt, ps.latest_signal,
            COALESCE(sp1.p1_count, 0)         AS sbir_p1_count,
            COALESCE(sp.p2_count, 0)          AS sbir_p2_count,
            COALESCE(rd.total_regd, 0)        AS total_regd,
            COALESCE(rd.regd_count, 0)        AS regd_count,
            rr.recent_regd_amount, rr.recent_regd_date,
            COALESCE(ct.total_contracts, 0)   AS total_contracts,
            COALESCE(ct.contract_count, 0)    AS contract_count,
            lc.largest_value, lc.largest_agency, lc.largest_date
        FROM entities e
        JOIN positive_signals ps ON e.id = ps.entity_id
        JOIN sbir_p2 sp           ON e.id = sp.entity_id
        LEFT JOIN sbir_p1 sp1     ON e.id = sp1.entity_id
        LEFT JOIN negative_check nc ON e.id = nc.entity_id
        LEFT JOIN regd_total rd     ON e.id = rd.entity_id
        LEFT JOIN regd_recent rr    ON e.id = rr.entity_id
        LEFT JOIN contract_total ct ON e.id = ct.entity_id
        LEFT JOIN largest_contract lc ON e.id = lc.entity_id
        WHERE e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND ps.n_positive >= 2
          AND ps.n_non_hpt >= 1
          AND nc.entity_id IS NULL
          AND ps.latest_signal >= ?
          AND COALESCE(rd.total_regd, 0)      < 100000000
          AND COALESCE(ct.total_contracts, 0) < 200000000
    """, (cutoff_24mo,))

    candidates = c.fetchall()

    # ------------------------------------------------------------------
    # Step 2: Fetch signals (with evidence) for candidates
    # ------------------------------------------------------------------
    candidate_ids = [r["id"] for r in candidates]
    entity_signals = defaultdict(list)

    for i in range(0, len(candidate_ids), 500):
        chunk = candidate_ids[i : i + 500]
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f"""SELECT entity_id, signal_type, confidence_score,
                       detected_date, evidence
                FROM signals
                WHERE status = 'ACTIVE' AND entity_id IN ({placeholders})""",
            chunk,
        )
        for row in c.fetchall():
            entity_signals[row["entity_id"]].append(dict(row))

    # ------------------------------------------------------------------
    # Step 3: Fetch SBIR Phase II award titles
    # ------------------------------------------------------------------
    entity_sbir_titles = defaultdict(list)
    for i in range(0, len(candidate_ids), 500):
        chunk = candidate_ids[i : i + 500]
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f"""SELECT entity_id,
                       json_extract(raw_data, '$."Award Title"') AS title,
                       event_date
                FROM funding_events
                WHERE event_type = 'SBIR_PHASE_2'
                  AND entity_id IN ({placeholders})
                ORDER BY event_date DESC""",
            chunk,
        )
        for row in c.fetchall():
            if row["title"]:
                entity_sbir_titles[row["entity_id"]].append(
                    {"title": row["title"], "date": row["event_date"]}
                )

    # ------------------------------------------------------------------
    # Step 4: Fetch contracting agencies
    # ------------------------------------------------------------------
    entity_agencies = defaultdict(list)
    for i in range(0, len(candidate_ids), 500):
        chunk = candidate_ids[i : i + 500]
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f"""SELECT entity_id, contracting_agency,
                       SUM(contract_value) AS agency_total,
                       COUNT(*) AS n_contracts
                FROM contracts
                WHERE entity_id IN ({placeholders})
                  AND contracting_agency IS NOT NULL
                GROUP BY entity_id, contracting_agency
                ORDER BY entity_id, agency_total DESC""",
            chunk,
        )
        for row in c.fetchall():
            entity_agencies[row["entity_id"]].append(dict(row))

    # ------------------------------------------------------------------
    # Step 5: Score each candidate
    # ------------------------------------------------------------------
    scored = []

    for cand in candidates:
        eid = cand["id"]
        signals = entity_signals.get(eid, [])

        # Compute freshness-adjusted composite score
        composite = 0.0
        positive_types_seen = set()
        has_kop = False
        kop_evidence = None
        negative_signals = []
        latest_signal_date = cand["latest_signal"]

        for sig in signals:
            st = sig["signal_type"]
            weight = ALL_WEIGHTS.get(st, 0.0)
            conf = float(sig["confidence_score"] or 0)
            fw = calc_freshness_weight(sig["detected_date"], st)
            composite += weight * conf * fw

            if st in POSITIVE_SIGNAL_TYPES:
                positive_types_seen.add(st)
            if st == "kop_alignment":
                has_kop = True
                kop_evidence = sig.get("evidence")
            if weight < 0:
                negative_signals.append(sig)

        # Normalize composite to 0-1 (cap raw at 10)
        composite_norm = min(max(composite, 0), 10.0) / 10.0

        # Signal diversity: normalized 0-1, max at 6+ distinct positive types
        diversity_count = len(positive_types_seen)
        signal_diversity = min(diversity_count, 6) / 6.0

        # Policy tailwind (0-1)
        policy_tailwind = 0.0
        top_priorities = []
        pa_scores = {}
        if cand["policy_alignment"]:
            try:
                pa = json.loads(cand["policy_alignment"])
                policy_tailwind = float(pa.get("policy_tailwind_score", 0) or 0)
                top_priorities = pa.get("top_priorities", [])
                pa_scores = pa.get("scores", {})
            except (json.JSONDecodeError, TypeError):
                pass

        # Momentum recency
        momentum = momentum_recency_score(latest_signal_date)

        # KOP alignment bonus
        kop_bonus = 1.0 if has_kop else 0.0

        # Weighted employment score
        emp_score = (
            W_COMPOSITE * composite_norm
            + W_SIGNAL_DIVERSITY * signal_diversity
            + W_POLICY_TAILWIND * policy_tailwind
            + W_MOMENTUM_RECENCY * momentum
            + W_KOP_ALIGNMENT * kop_bonus
        )

        # Domain preference multiplier — check if TOP priority is preferred
        top_priority = top_priorities[0] if top_priorities else None
        domain_match = top_priority in PREFERRED_DOMAINS if top_priority else False
        if domain_match:
            emp_score *= DOMAIN_MULTIPLIER

        # Technology tags
        tech_tags = []
        if cand["technology_tags"]:
            try:
                tech_tags = json.loads(cand["technology_tags"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Unique agencies from contracts
        unique_agencies = [
            a["contracting_agency"]
            for a in entity_agencies.get(eid, [])
        ]

        scored.append({
            "id": eid,
            "name": cand["canonical_name"],
            "core_business": cand["core_business"] or "UNCLASSIFIED",
            "employment_score": round(emp_score, 4),
            "composite_raw": round(composite, 2),
            "composite_norm": round(composite_norm, 4),
            "composite_tier": composite_tier(composite),
            "signal_diversity": round(signal_diversity, 4),
            "diversity_count": diversity_count,
            "policy_tailwind": round(policy_tailwind, 3),
            "momentum": round(momentum, 2),
            "kop_aligned": has_kop,
            "kop_evidence": kop_evidence,
            "domain_match": domain_match,
            "top_priority": top_priority,
            "n_positive_signals": diversity_count,
            "signals": signals,
            "negative_signals": negative_signals,
            "latest_signal": latest_signal_date,
            "sbir_p1_count": cand["sbir_p1_count"],
            "sbir_p2_count": cand["sbir_p2_count"],
            "total_regd": cand["total_regd"],
            "regd_count": cand["regd_count"],
            "recent_regd_amount": cand["recent_regd_amount"],
            "recent_regd_date": cand["recent_regd_date"],
            "total_contracts": cand["total_contracts"],
            "contract_count": cand["contract_count"],
            "largest_value": cand["largest_value"],
            "largest_agency": cand["largest_agency"],
            "largest_date": cand["largest_date"],
            "top_priorities": top_priorities,
            "pa_scores": pa_scores,
            "tech_tags": tech_tags,
            "sbir_titles": entity_sbir_titles.get(eid, [])[:5],
            "unique_agencies": unique_agencies,
        })

    scored.sort(key=lambda x: -x["employment_score"])

    # ------------------------------------------------------------------
    # Step 6: Build output
    # ------------------------------------------------------------------
    top_20 = scored[:20]

    # Dark horses: #21-25 that narrowly missed
    dark_horses = scored[20:25]

    lines = []

    def out(line=""):
        lines.append(line)
        print(line)

    out("=" * 55)
    out("APERTURE SIGNALS — EMPLOYMENT TARGET REPORT")
    out(f"Generated: {today.isoformat()}")
    out("Profile: Marine Corps Helicopter Pilot/Instructor,")
    out("         JTAC — 1st ANGLICO (transitioning)")
    out("=" * 55)
    out()
    out(f"Universe: {len(candidates):,} companies passed hard filters")
    out(f"Scored & ranked: {len(scored):,} companies")
    out()

    # ------------------------------------------------------------------
    # Top 20 profiles
    # ------------------------------------------------------------------
    for rank, e in enumerate(top_20, 1):
        out("=" * 55)
        out(f"#{rank} — {e['name']}")
        out("=" * 55)

        # Top priority display
        tp = e["top_priority"] or "none"
        tp_growth = DOMAIN_GROWTH.get(tp, "")
        tp_display = f"{tp} ({tp_growth})" if tp_growth else tp

        out(f"Core Business:     {e['core_business']}")
        out(f"Employment Score:  {e['employment_score']:.2f}"
            f"{'  [1.15x DOMAIN FIT]' if e['domain_match'] else ''}")
        out(f"Composite Score:   {e['composite_raw']:.2f} (Tier {e['composite_tier']})")
        out(f"Policy Tailwind:   {e['policy_tailwind']:.2f} — "
            f"Top priority: {tp_display}")
        out()

        # Signals
        positive_sigs = [
            s for s in e["signals"]
            if ALL_WEIGHTS.get(s["signal_type"], 0) > 0
        ]
        positive_sigs.sort(key=lambda s: -ALL_WEIGHTS.get(s["signal_type"], 0))
        neg_sigs = e["negative_signals"]

        total_active = len(positive_sigs) + len(neg_sigs)
        out(f"SIGNALS ({total_active} active):")
        for sig in positive_sigs:
            st = sig["signal_type"]
            display = SIGNAL_DISPLAY.get(st, st)
            conf = float(sig["confidence_score"] or 0)
            ev_line = evidence_summary(sig.get("evidence"), st)
            ev_part = f" — {ev_line}" if ev_line else ""
            out(f"  ✦ {display} — confidence {conf:.2f}{ev_part}")
        for sig in neg_sigs:
            st = sig["signal_type"]
            display = SIGNAL_DISPLAY.get(st, st)
            ev_line = evidence_summary(sig.get("evidence"), st)
            ev_part = f" — {ev_line}" if ev_line else ""
            out(f"  ✗ {display}{ev_part}")
        out()

        # Government traction
        out("GOVERNMENT TRACTION:")
        out(f"  SBIRs: {e['sbir_p1_count'] + e['sbir_p2_count']} awards "
            f"(Phase I: {e['sbir_p1_count']}, Phase II: {e['sbir_p2_count']})")
        agencies_str = ", ".join(e["unique_agencies"][:5]) if e["unique_agencies"] else "none"
        out(f"  Contracts: {e['contract_count']} totaling "
            f"{fmt(e['total_contracts'])} — Agencies: {agencies_str}")
        if e["largest_value"] and e["largest_value"] > 0:
            out(f"  Largest contract: {fmt(e['largest_value'])} from "
                f"{e['largest_agency'] or 'unknown'} ({e['largest_date'] or 'unknown date'})")
        out()

        # Private capital
        out("PRIVATE CAPITAL:")
        out(f"  Reg D filings: {e['regd_count']} totaling {fmt(e['total_regd'])}")
        if e["recent_regd_amount"]:
            out(f"  Most recent: {fmt(e['recent_regd_amount'])} on "
                f"{e['recent_regd_date'] or 'unknown date'}")
        out()

        # KOP alignment
        if e["kop_aligned"] and e["kop_evidence"]:
            ev_line = evidence_summary(e["kop_evidence"], "kop_alignment")
            out(f"KOP ALIGNMENT: {ev_line}")
        else:
            out("KOP ALIGNMENT: None detected")
        out()

        # Domain fit
        out("DOMAIN FIT:")
        fit_parts = generate_domain_fit(e)
        for part in fit_parts[:3]:
            out(f"  {part}")
        out()

        # SBIR titles
        if e["sbir_titles"]:
            out("SBIR TITLES (most recent 3):")
            for sb in e["sbir_titles"][:3]:
                out(f"  - {sb['title']}")
            out()

        out("─" * 55)
        out()

    # ------------------------------------------------------------------
    # Signal heatmap
    # ------------------------------------------------------------------
    out()
    out("=" * 55)
    out("SIGNAL HEATMAP — TOP 20")
    out("=" * 55)
    out()

    # Determine which positive signal types appear across top 20
    type_counts = Counter()
    for e in top_20:
        seen = set()
        for sig in e["signals"]:
            if ALL_WEIGHTS.get(sig["signal_type"], 0) > 0:
                seen.add(sig["signal_type"])
        for st in seen:
            type_counts[st] += 1
    heatmap_types = sorted(type_counts.keys(), key=lambda t: (-type_counts[t], t))

    abbrev = {
        "sbir_to_contract_transition": "S→C",
        "rapid_contract_growth": "RCG",
        "sbir_validated_raise": "SVR",
        "sbir_to_vc_raise": "S→V",
        "outsized_award": "OUT",
        "sbir_phase_2_transition": "P2",
        "multi_agency_interest": "MAI",
        "high_priority_technology": "HPT",
        "first_dod_contract": "1st",
        "sbir_graduation_speed": "FGR",
        "time_to_contract": "T→C",
        "funding_velocity": "FV",
        "kop_alignment": "KOP",
        "commercial_pathway_fit": "COM",
        "jar_funding": "JAR",
        "meia_experimentation": "MEI",
        "pae_portfolio": "PAE",
        "sbir_phase_3_transition": "P3",
    }

    name_w = 28
    header = f"{'Company':<{name_w}}"
    for st in heatmap_types:
        header += f" {abbrev.get(st, st[:3]):>3}"
    out(header)
    out("-" * len(header))

    for e in top_20:
        sig_types = {
            s["signal_type"] for s in e["signals"]
            if ALL_WEIGHTS.get(s["signal_type"], 0) > 0
        }
        row = f"{e['name'][:name_w]:<{name_w}}"
        for st in heatmap_types:
            row += f"{'  ✓' if st in sig_types else '   '}"
        out(row)

    out()
    legend_parts = [f"{abbrev.get(t, t[:3])}={SIGNAL_DISPLAY.get(t, t)}" for t in heatmap_types]
    out("Legend:")
    # Print legend in rows of 4
    for i in range(0, len(legend_parts), 4):
        out("  " + "  |  ".join(legend_parts[i : i + 4]))
    out()
    out(f"Coverage: {' / '.join(f'{abbrev.get(t, t[:3])}:{type_counts[t]}' for t in heatmap_types[:8])}")

    # ------------------------------------------------------------------
    # Sector concentration
    # ------------------------------------------------------------------
    out()
    out("=" * 55)
    out("SECTOR CONCENTRATION — TOP 20")
    out("=" * 55)
    out()

    # By core_business
    out("By Core Business:")
    sector_counts = Counter()
    for e in top_20:
        sector_counts[e["core_business"]] += 1
    for sector, count in sector_counts.most_common():
        companies = [e["name"] for e in top_20 if e["core_business"] == sector]
        out(f"  {sector:<25} {count:>2}  —  {', '.join(companies)}")

    out()

    # By top policy priority
    out("By Top Policy Priority:")
    priority_counts = Counter()
    for e in top_20:
        if e["top_priority"]:
            priority_counts[e["top_priority"]] += 1
    for pri, count in priority_counts.most_common():
        growth = DOMAIN_GROWTH.get(pri, "")
        domain_tag = " ★" if pri in PREFERRED_DOMAINS else ""
        out(f"  {pri:<25} {count:>2}  FY26: {growth}{domain_tag}")

    # ------------------------------------------------------------------
    # Dark horse list
    # ------------------------------------------------------------------
    out()
    out("=" * 55)
    out("DARK HORSE LIST — 5 Near-Misses Worth Watching")
    out("=" * 55)
    out()

    for i, e in enumerate(dark_horses, 1):
        # Figure out what criterion was weakest
        weaknesses = []
        if e["composite_raw"] < 5.0:
            weaknesses.append(f"composite only {e['composite_raw']:.1f} (Tier {e['composite_tier']})")
        if e["n_positive_signals"] < 4:
            weaknesses.append(f"only {e['n_positive_signals']} signal types")
        if e["policy_tailwind"] < 0.4:
            weaknesses.append(f"low policy tailwind ({e['policy_tailwind']:.2f})")
        if not e["kop_aligned"]:
            weaknesses.append("no KOP alignment")
        if not e["domain_match"]:
            weaknesses.append("top priority not in preferred domains")

        weakness_str = weaknesses[0] if weaknesses else "marginal overall score"

        out(f"  #{i}  {e['name']}")
        out(f"      Score: {e['employment_score']:.3f}  |  "
            f"{e['core_business']}  |  {e['n_positive_signals']} signals")
        out(f"      Near-miss reason: {weakness_str}")
        if e["sbir_titles"]:
            out(f"      Latest SBIR: {e['sbir_titles'][0]['title'][:65]}")
        out()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    out("=" * 55)
    out("SUMMARY")
    out("=" * 55)
    out()
    out(f"  Universe after hard filters:  {len(candidates):,}")
    out(f"  Top 20 score range:           "
        f"{top_20[-1]['employment_score']:.3f} – {top_20[0]['employment_score']:.3f}")
    kop_count = sum(1 for e in top_20 if e["kop_aligned"])
    domain_count = sum(1 for e in top_20 if e["domain_match"])
    out(f"  KOP-aligned in top 20:        {kop_count}/20")
    out(f"  Domain-fit in top 20:         {domain_count}/20")
    avg_comp = sum(e["composite_raw"] for e in top_20) / 20
    avg_policy = sum(e["policy_tailwind"] for e in top_20) / 20
    out(f"  Avg composite (raw):          {avg_comp:.1f}")
    out(f"  Avg policy tailwind:          {avg_policy:.3f}")

    # ------------------------------------------------------------------
    # Save report
    # ------------------------------------------------------------------
    report_path = REPORT_DIR / "employment_targets.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    out()
    out(f"Report saved to: {report_path}")

    conn.close()


if __name__ == "__main__":
    run()
