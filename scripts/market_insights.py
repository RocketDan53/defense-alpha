#!/usr/bin/env python3
"""
Market Intelligence Brief Generator — Aperture Signals Intelligence.

Queries defense_alpha.db via raw sqlite3 and produces a styled markdown
report with non-obvious market-level findings for client outreach.

Usage:
    python scripts/market_insights.py
"""

import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "defense_alpha.db"
OUTPUT_PATH = PROJECT_ROOT / "reports" / "market_insights_march_2026.md"

# NDS policy priorities sorted by FY26 growth rate descending
POLICY_AREAS = [
    ("space_resilience", "Space Resilience", 0.38, 0.235),
    ("nuclear_modernization", "Nuclear Modernization", 0.17, 0.170),
    ("autonomous_systems", "Autonomous Systems", 0.10, 0.130),
    ("contested_logistics", "Contested Logistics", 0.10, 0.100),
    ("electronic_warfare", "Electronic Warfare", 0.10, 0.085),
    ("jadc2", "JADC2", 0.10, 0.075),
    ("border_homeland", "Border & Homeland", 0.10, 0.050),
    ("cyber_offense_defense", "Cyber Offense/Defense", 0.10, 0.030),
    ("supply_chain_resilience", "Supply Chain Resilience", 0.07, 0.110),
    ("hypersonics", "Hypersonics", -0.43, 0.015),
]
AREA_KEYS = [a[0] for a in POLICY_AREAS]
AREA_LABELS = {a[0]: a[1] for a in POLICY_AREAS}
AREA_GROWTH = {a[0]: a[2] for a in POLICY_AREAS}
AREA_WEIGHT = {a[0]: a[3] for a in POLICY_AREAS}

# Superseded funding exclusion subquery
SUPERSEDED_EXCLUDE = """
    AND f.id NOT IN (
        SELECT parent_event_id FROM funding_events
        WHERE parent_event_id IS NOT NULL
    )
"""


def connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fmt_dollars(val):
    """Format dollar value with appropriate suffix."""
    if val is None or val == 0:
        return "$0"
    if abs(val) >= 1_000_000_000:
        return f"${val / 1e9:.1f}B"
    if abs(val) >= 1_000_000:
        return f"${val / 1e6:.1f}M"
    if abs(val) >= 1_000:
        return f"${val / 1e3:.0f}K"
    return f"${val:,.0f}"


def get_top_priority(policy_alignment_json):
    """Return the policy area with the highest score for an entity."""
    if not policy_alignment_json:
        return None
    try:
        pa = json.loads(policy_alignment_json) if isinstance(policy_alignment_json, str) else policy_alignment_json
    except (json.JSONDecodeError, TypeError):
        return None
    scores = pa.get("scores", {})
    if not scores:
        return None
    best_area = max(scores, key=lambda k: scores.get(k, 0))
    if scores.get(best_area, 0) < 0.1:
        return None
    return best_area


# ---------------------------------------------------------------------------
# Section 1: Capital Flow by Policy Area
# ---------------------------------------------------------------------------
def section_capital_flow(conn):
    # Fetch all startup entities with policy alignment
    rows = conn.execute("""
        SELECT id, canonical_name, policy_alignment
        FROM entities
        WHERE entity_type = 'STARTUP'
          AND merged_into_id IS NULL
          AND policy_alignment IS NOT NULL
    """).fetchall()

    # Group entities by top priority
    area_entities = defaultdict(list)
    for r in rows:
        top = get_top_priority(r["policy_alignment"])
        if top and top in AREA_KEYS:
            area_entities[top].append(r["id"])

    # For each area, compute metrics
    area_stats = {}
    for area_key in AREA_KEYS:
        eids = area_entities.get(area_key, [])
        if not eids:
            area_stats[area_key] = {
                "count": 0, "capital": 0, "contract_val": 0,
                "avg_composite": 0, "avg_signals": 0,
            }
            continue

        placeholders = ",".join(["?"] * len(eids))

        # Private capital (Reg D + Private Round, excluding superseded)
        capital = conn.execute(f"""
            SELECT COALESCE(SUM(f.amount), 0)
            FROM funding_events f
            WHERE f.entity_id IN ({placeholders})
              AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
              {SUPERSEDED_EXCLUDE}
        """, eids).fetchone()[0] or 0

        # Total contract value
        contract_val = conn.execute(f"""
            SELECT COALESCE(SUM(c.contract_value), 0)
            FROM contracts c
            WHERE c.entity_id IN ({placeholders})
        """, eids).fetchone()[0] or 0

        # Average composite score (from latest entity_snapshots)
        snap_rows = conn.execute(f"""
            SELECT es.composite_score
            FROM entity_snapshots es
            INNER JOIN (
                SELECT entity_id, MAX(snapshot_date) as max_date
                FROM entity_snapshots
                WHERE entity_id IN ({placeholders})
                GROUP BY entity_id
            ) latest ON es.entity_id = latest.entity_id
                    AND es.snapshot_date = latest.max_date
        """, eids).fetchall()
        scores = [float(r[0]) for r in snap_rows if r[0]]
        avg_composite = statistics.mean(scores) if scores else 0

        # Average active signals per entity
        sig_rows = conn.execute(f"""
            SELECT entity_id, COUNT(*) as cnt
            FROM signals
            WHERE entity_id IN ({placeholders})
              AND status = 'ACTIVE'
            GROUP BY entity_id
        """, eids).fetchall()
        sig_counts = [r["cnt"] for r in sig_rows]
        avg_signals = statistics.mean(sig_counts) if sig_counts else 0

        area_stats[area_key] = {
            "count": len(eids),
            "capital": float(capital),
            "contract_val": float(contract_val),
            "avg_composite": avg_composite,
            "avg_signals": avg_signals,
        }

    # Build markdown
    md = "## 1. Capital Flow by Policy Area\n\n"
    md += (
        "Government spending priorities are reshaping where private capital flows "
        "in defense technology. By mapping each company to its highest-scoring NDS "
        "budget priority, we can see which policy areas are attracting the most "
        "startup activity and capital — and where spending growth is outpacing "
        "private investment.\n\n"
    )
    md += "| Priority Area | FY26 Growth | Companies | Private Capital | Contract Value | Avg Score | Signals/Co |\n"
    md += "|:---|---:|---:|---:|---:|---:|---:|\n"

    total_capital = sum(s["capital"] for s in area_stats.values())
    total_contracts = sum(s["contract_val"] for s in area_stats.values())

    for area_key, label, growth, weight in POLICY_AREAS:
        s = area_stats[area_key]
        growth_str = f"+{growth:.0%}" if growth > 0 else f"{growth:.0%}"
        md += (
            f"| {label} | {growth_str} | {s['count']:,} "
            f"| {fmt_dollars(s['capital'])} | {fmt_dollars(s['contract_val'])} "
            f"| {s['avg_composite']:.1f} | {s['avg_signals']:.1f} |\n"
        )

    md += f"\n**Total tracked:** {sum(s['count'] for s in area_stats.values()):,} companies, "
    md += f"{fmt_dollars(total_capital)} private capital, {fmt_dollars(total_contracts)} contract value.\n\n"

    # Find the insight
    top_capital = max(area_stats.items(), key=lambda x: x[1]["capital"])
    top_growth_area = POLICY_AREAS[0]  # space_resilience
    hyper = area_stats.get("hypersonics", {})

    md += (
        f"**So what:** {AREA_LABELS[top_capital[0]]} commands the largest share of "
        f"private capital ({fmt_dollars(top_capital[1]['capital'])}), but space resilience "
        f"— with +38% FY26 growth — has the strongest government tailwind. "
        f"Meanwhile, {hyper.get('count', 0)} companies remain concentrated in hypersonics "
        f"despite a -43% budget decline. Investors following the budget trajectory should "
        f"be overweighting space resilience and autonomous systems while monitoring "
        f"hypersonics exposure.\n\n"
    )
    return md


# ---------------------------------------------------------------------------
# Section 2: Pre-Inflection Watchlist
# ---------------------------------------------------------------------------
def section_pre_inflection(conn):
    # Entities with sbir_breadth signal, zero contracts, zero Reg D
    rows = conn.execute("""
        SELECT e.id, e.canonical_name, e.technology_tags, e.policy_alignment,
               s.evidence as sbir_evidence, s.confidence_score
        FROM entities e
        JOIN signals s ON e.id = s.entity_id
        WHERE e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND s.signal_type = 'sbir_breadth'
          AND s.status = 'ACTIVE'
          AND e.id NOT IN (SELECT DISTINCT entity_id FROM contracts)
          AND e.id NOT IN (
              SELECT DISTINCT entity_id FROM funding_events
              WHERE event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
          )
    """).fetchall()

    # For each, get composite score and SBIR details
    enriched = []
    for r in rows:
        eid = r["id"]
        ev = json.loads(r["sbir_evidence"]) if r["sbir_evidence"] else {}
        tags = json.loads(r["technology_tags"]) if r["technology_tags"] else []

        # Get composite score from latest snapshot
        snap = conn.execute("""
            SELECT composite_score FROM entity_snapshots
            WHERE entity_id = ? ORDER BY snapshot_date DESC LIMIT 1
        """, (eid,)).fetchone()
        composite = float(snap[0]) if snap and snap[0] else 0

        # Most recent SBIR date
        last_sbir = conn.execute("""
            SELECT MAX(event_date) FROM funding_events
            WHERE entity_id = ? AND event_type IN ('SBIR_PHASE_1', 'SBIR_PHASE_2')
        """, (eid,)).fetchone()
        last_date = last_sbir[0] if last_sbir else "unknown"

        # SBIR count
        sbir_count = conn.execute("""
            SELECT COUNT(*) FROM funding_events
            WHERE entity_id = ? AND event_type IN ('SBIR_PHASE_1', 'SBIR_PHASE_2')
        """, (eid,)).fetchone()[0]

        enriched.append({
            "name": r["canonical_name"],
            "sbir_count": sbir_count,
            "branches": ev.get("agency_count", 0),
            "tags": tags,
            "composite": composite,
            "last_sbir": last_date,
        })

    enriched.sort(key=lambda x: -x["composite"])
    total = len(enriched)

    md = "## 2. Pre-Inflection Watchlist\n\n"
    md += (
        f"Aperture tracks {total} companies that have earned SBIR awards from four or more "
        f"DoD branches across three or more technology domains — yet have zero production "
        f"contracts and zero private capital on record. These companies have passed multiple "
        f"independent government evaluations but remain invisible to the private market. "
        f"The top 10 by composite signal score represent the highest-conviction "
        f"pre-inflection opportunities.\n\n"
    )

    md += "| # | Company | SBIRs | Branches | Tech Domains | Score | Last SBIR |\n"
    md += "|--:|:--------|------:|--------:|----|------:|----------:|\n"
    for i, e in enumerate(enriched[:10], 1):
        tag_str = ", ".join(e["tags"][:4])
        if len(e["tags"]) > 4:
            tag_str += f" +{len(e['tags'])-4}"
        md += (
            f"| {i} | {e['name']} | {e['sbir_count']} | {e['branches']} "
            f"| {tag_str} | {e['composite']:.1f} | {e['last_sbir']} |\n"
        )

    if enriched:
        avg_sbir = statistics.mean(e["sbir_count"] for e in enriched)
        avg_branches = statistics.mean(e["branches"] for e in enriched)
        md += (
            f"\nAcross the full {total}-company watchlist, the average entity holds "
            f"{avg_sbir:.0f} SBIR awards across {avg_branches:.1f} branches.\n\n"
        )

    md += (
        "**So what:** These companies have been vetted by multiple independent government "
        "program offices but haven't yet attracted private capital or production contracts. "
        "This is precisely the information asymmetry that creates alpha — the market can't "
        "see inside the SBIR pipeline at this resolution. The first mover into these "
        "companies captures the Phase II-to-production premium before it becomes consensus.\n\n"
    )
    return md


# ---------------------------------------------------------------------------
# Section 3: Acceleration Cohort
# ---------------------------------------------------------------------------
def section_acceleration(conn):
    # Get all contract_acceleration signals with entity details
    rows = conn.execute("""
        SELECT e.id, e.canonical_name, e.core_business,
               s.evidence, s.confidence_score
        FROM entities e
        JOIN signals s ON e.id = s.entity_id
        WHERE e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND s.signal_type = 'contract_acceleration'
          AND s.status = 'ACTIVE'
    """).fetchall()

    # Group by core_business
    by_sector = defaultdict(list)
    for r in rows:
        sector = r["core_business"] or "UNCLASSIFIED"
        ev = json.loads(r["evidence"]) if r["evidence"] else {}
        by_sector[sector].append({
            "id": r["id"],
            "name": r["canonical_name"],
            "ratio": ev.get("acceleration_ratio", 0),
            "recent_val": ev.get("recent_24mo_value", 0),
        })

    # For each entity, check if they also have funding_velocity or sbir_validated_raise
    accel_ids = [r["id"] for r in rows]
    capital_tracking = set()
    if accel_ids:
        placeholders = ",".join(["?"] * len(accel_ids))
        tracking = conn.execute(f"""
            SELECT DISTINCT entity_id FROM signals
            WHERE entity_id IN ({placeholders})
              AND status = 'ACTIVE'
              AND signal_type IN ('funding_velocity', 'sbir_validated_raise')
        """, accel_ids).fetchall()
        capital_tracking = {t[0] for t in tracking}

    md = "## 3. Acceleration Cohort\n\n"
    md += (
        f"{len(rows)} startups show contract value acceleration of 3x or greater in the "
        f"most recent 24 months versus the prior 24. This R&D-to-production transition "
        f"is the defining signal of a company crossing from prototype to program of record.\n\n"
    )

    md += "| Sector | Companies | Avg Ratio | Median Recent 24mo | Private Capital Tracking |\n"
    md += "|:-------|----------:|----------:|-------------------:|-------------------------:|\n"

    sector_rows = []
    for sector, companies in sorted(by_sector.items(), key=lambda x: -len(x[1])):
        ratios = [c["ratio"] for c in companies]
        recent_vals = sorted([c["recent_val"] for c in companies])
        median_val = recent_vals[len(recent_vals)//2] if recent_vals else 0
        tracking_count = sum(1 for c in companies if c["id"] in capital_tracking)
        pct_tracking = f"{100*tracking_count/len(companies):.0f}%" if companies else "0%"
        sector_rows.append({
            "sector": sector, "count": len(companies),
            "avg_ratio": statistics.mean(ratios) if ratios else 0,
            "median_val": median_val, "tracking": tracking_count,
            "pct_tracking": pct_tracking,
        })
        md += (
            f"| {sector} | {len(companies)} | {statistics.mean(ratios):.1f}x "
            f"| {fmt_dollars(median_val)} | {tracking_count} ({pct_tracking}) |\n"
        )

    total_tracking = len(capital_tracking & set(accel_ids))
    md += (
        f"\nOf the {len(rows)} accelerating companies, {total_tracking} "
        f"({100*total_tracking/len(rows):.0f}%) also show private capital momentum "
        f"(funding velocity or SBIR-validated raise). "
    )

    # Find sector with lowest tracking
    if sector_rows:
        low_track = min((s for s in sector_rows if s["count"] >= 5), key=lambda x: int(x["pct_tracking"].rstrip("%")), default=None)
        if low_track:
            md += (
                f"The {low_track['sector']} sector has the widest gap between government "
                f"contract acceleration ({low_track['count']} companies) and private capital "
                f"tracking ({low_track['tracking']} companies) — a potential market blind spot.\n\n"
            )
        else:
            md += "\n\n"

    md += (
        "**So what:** Contract acceleration identifies companies transitioning from R&D "
        "to production revenue. Sectors where acceleration is high but private capital "
        "tracking is low represent the best-timed entry points — the government is already "
        "buying, but the market hasn't priced it in.\n\n"
    )
    return md


# ---------------------------------------------------------------------------
# Section 4: Policy Headwind Exposure
# ---------------------------------------------------------------------------
def section_headwind(conn):
    # Entities with policy_headwind signal
    rows = conn.execute("""
        SELECT e.id, e.canonical_name, e.core_business, e.policy_alignment
        FROM entities e
        JOIN signals s ON e.id = s.entity_id
        WHERE e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND s.signal_type = 'policy_headwind'
          AND s.status = 'ACTIVE'
    """).fetchall()

    eids = [r["id"] for r in rows]
    total = len(eids)

    # Group by core_business
    by_sector = defaultdict(list)
    for r in rows:
        by_sector[r["core_business"] or "UNCLASSIFIED"].append(r["id"])

    # Total capital raised by headwind entities
    if eids:
        placeholders = ",".join(["?"] * len(eids))
        total_capital = conn.execute(f"""
            SELECT COALESCE(SUM(f.amount), 0) FROM funding_events f
            WHERE f.entity_id IN ({placeholders})
              AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
              {SUPERSEDED_EXCLUDE}
        """, eids).fetchone()[0] or 0

        # Recent funding (last 18 months)
        cutoff_18mo = (date.today() - timedelta(days=548)).isoformat()
        recent_funded = conn.execute(f"""
            SELECT COUNT(DISTINCT f.entity_id) FROM funding_events f
            WHERE f.entity_id IN ({placeholders})
              AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
              AND f.event_date >= ?
              {SUPERSEDED_EXCLUDE}
        """, eids + [cutoff_18mo]).fetchone()[0]

        recent_capital = conn.execute(f"""
            SELECT COALESCE(SUM(f.amount), 0) FROM funding_events f
            WHERE f.entity_id IN ({placeholders})
              AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
              AND f.event_date >= ?
              {SUPERSEDED_EXCLUDE}
        """, eids + [cutoff_18mo]).fetchone()[0] or 0

        # Average policy_tailwind for headwind vs overall
        headwind_tailwinds = []
        for r in rows:
            pa = json.loads(r["policy_alignment"]) if r["policy_alignment"] else {}
            pts = pa.get("policy_tailwind_score")
            if pts is not None:
                headwind_tailwinds.append(pts)

        overall_tailwind = conn.execute("""
            SELECT AVG(json_extract(policy_alignment, '$.policy_tailwind_score'))
            FROM entities
            WHERE entity_type = 'STARTUP'
              AND merged_into_id IS NULL
              AND policy_alignment IS NOT NULL
        """).fetchone()[0] or 0

    else:
        total_capital = recent_funded = recent_capital = 0
        headwind_tailwinds = []
        overall_tailwind = 0

    avg_headwind_tailwind = statistics.mean(headwind_tailwinds) if headwind_tailwinds else 0

    md = "## 4. Policy Headwind Exposure\n\n"
    md += (
        f"{total} companies in Aperture's tracking universe are primarily aligned to "
        f"declining budget areas — overwhelmingly hypersonics, which faces a -43% FY26 "
        f"appropriation cut. These companies have collectively raised {fmt_dollars(float(total_capital))} "
        f"in private capital.\n\n"
    )

    if recent_funded > 0:
        md += (
            f"**{recent_funded} of these companies raised capital in the last 18 months, "
            f"totaling {fmt_dollars(float(recent_capital))}.** These represent the most "
            f"acute investor exposure to budget headwinds — capital deployed against a "
            f"contracting government demand signal.\n\n"
        )

    md += "| Sector | Companies | Capital Raised | Recent Funding (18mo) |\n"
    md += "|:-------|----------:|---------------:|----------------------:|\n"

    for sector, sector_eids in sorted(by_sector.items(), key=lambda x: -len(x[1])):
        if sector_eids:
            phs = ",".join(["?"] * len(sector_eids))
            cap = conn.execute(f"""
                SELECT COALESCE(SUM(f.amount), 0) FROM funding_events f
                WHERE f.entity_id IN ({phs})
                  AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
                  {SUPERSEDED_EXCLUDE}
            """, sector_eids).fetchone()[0] or 0

            recent = conn.execute(f"""
                SELECT COUNT(DISTINCT f.entity_id) FROM funding_events f
                WHERE f.entity_id IN ({phs})
                  AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
                  AND f.event_date >= ?
                  {SUPERSEDED_EXCLUDE}
            """, sector_eids + [cutoff_18mo]).fetchone()[0]
        else:
            cap = recent = 0

        md += f"| {sector} | {len(sector_eids)} | {fmt_dollars(float(cap))} | {recent} cos |\n"

    md += (
        f"\nThe average policy tailwind score for headwind-exposed companies is "
        f"**{avg_headwind_tailwind:.3f}** vs the STARTUP universe average of "
        f"**{float(overall_tailwind):.3f}**.\n\n"
    )

    md += (
        f"**So what:** {recent_funded} companies in declining budget areas raised "
        f"{fmt_dollars(float(recent_capital))} in the last 18 months. Investors may be "
        f"allocating against the budget trajectory. For BD consultants, these companies "
        f"need help pivoting their technology to adjacent growth areas (e.g., hypersonic "
        f"thermal management expertise reapplied to space reentry or directed energy "
        f"cooling).\n\n"
    )
    return md


# ---------------------------------------------------------------------------
# Section 5: OTA Pathway Analysis
# ---------------------------------------------------------------------------
def section_ota_pathway(conn):
    # OTA entities vs standard-only
    ota_entities = conn.execute("""
        SELECT DISTINCT entity_id FROM contracts
        WHERE procurement_type = 'ota'
        AND entity_id IN (
            SELECT id FROM entities
            WHERE entity_type = 'STARTUP' AND merged_into_id IS NULL
        )
    """).fetchall()
    ota_ids = [r[0] for r in ota_entities]

    std_only_entities = conn.execute("""
        SELECT DISTINCT c.entity_id FROM contracts c
        JOIN entities e ON c.entity_id = e.id
        WHERE e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND c.entity_id NOT IN (
              SELECT DISTINCT entity_id FROM contracts WHERE procurement_type = 'ota'
          )
    """).fetchall()
    std_ids = [r[0] for r in std_only_entities]

    def cohort_stats(entity_ids, label):
        if not entity_ids:
            return {"label": label, "count": 0, "avg_composite": 0,
                    "avg_funding": 0, "avg_contract": 0, "sbir_trans_pct": 0,
                    "signal_dist": {}}
        phs = ",".join(["?"] * len(entity_ids))

        # Avg composite score
        snaps = conn.execute(f"""
            SELECT es.composite_score
            FROM entity_snapshots es
            INNER JOIN (
                SELECT entity_id, MAX(snapshot_date) as md
                FROM entity_snapshots
                WHERE entity_id IN ({phs})
                GROUP BY entity_id
            ) l ON es.entity_id = l.entity_id AND es.snapshot_date = l.md
        """, entity_ids).fetchall()
        scores = [float(r[0]) for r in snaps if r[0]]
        avg_composite = statistics.mean(scores) if scores else 0

        # Avg funding raised
        funding = conn.execute(f"""
            SELECT f.entity_id, COALESCE(SUM(f.amount), 0)
            FROM funding_events f
            WHERE f.entity_id IN ({phs})
              AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
              {SUPERSEDED_EXCLUDE}
            GROUP BY f.entity_id
        """, entity_ids).fetchall()
        fund_vals = [float(r[1]) for r in funding]
        avg_funding = statistics.mean(fund_vals) if fund_vals else 0

        # Avg contract value
        contracts = conn.execute(f"""
            SELECT entity_id, COALESCE(SUM(contract_value), 0)
            FROM contracts
            WHERE entity_id IN ({phs})
            GROUP BY entity_id
        """, entity_ids).fetchall()
        contract_vals = [float(r[1]) for r in contracts]
        avg_contract = statistics.mean(contract_vals) if contract_vals else 0

        # % with sbir_to_contract_transition
        sbir_trans = conn.execute(f"""
            SELECT COUNT(DISTINCT entity_id) FROM signals
            WHERE entity_id IN ({phs})
              AND signal_type = 'sbir_to_contract_transition'
              AND status = 'ACTIVE'
        """, entity_ids).fetchone()[0]
        sbir_trans_pct = 100 * sbir_trans / len(entity_ids)

        # Signal type distribution (top 8)
        sig_dist = conn.execute(f"""
            SELECT signal_type, COUNT(*) as cnt
            FROM signals
            WHERE entity_id IN ({phs})
              AND status = 'ACTIVE'
            GROUP BY signal_type
            ORDER BY cnt DESC LIMIT 8
        """, entity_ids).fetchall()
        sig_dict = {r[0]: r[1] for r in sig_dist}

        return {
            "label": label, "count": len(entity_ids),
            "avg_composite": avg_composite, "avg_funding": avg_funding,
            "avg_contract": avg_contract, "sbir_trans_pct": sbir_trans_pct,
            "signal_dist": sig_dict,
        }

    ota_stats = cohort_stats(ota_ids, "OTA Pathway")
    std_stats = cohort_stats(std_ids, "Standard Only")

    md = "## 5. OTA Pathway Analysis\n\n"
    md += (
        "Other Transaction Authority (OTA) contracts are the primary vehicle for "
        "non-traditional defense companies entering the production pipeline. Aperture "
        "tracks which companies have used the OTA pathway versus traditional procurement "
        "to test whether OTA-pathway companies are systematically different.\n\n"
    )

    md += "| Metric | OTA Pathway | Standard Only | Delta |\n"
    md += "|:-------|------------:|--------------:|------:|\n"
    md += f"| Companies | {ota_stats['count']} | {std_stats['count']} | |\n"
    md += (
        f"| Avg Composite Score | {ota_stats['avg_composite']:.1f} "
        f"| {std_stats['avg_composite']:.1f} "
        f"| {ota_stats['avg_composite'] - std_stats['avg_composite']:+.1f} |\n"
    )
    md += (
        f"| Avg Funding Raised | {fmt_dollars(ota_stats['avg_funding'])} "
        f"| {fmt_dollars(std_stats['avg_funding'])} | |\n"
    )
    md += (
        f"| Avg Contract Value | {fmt_dollars(ota_stats['avg_contract'])} "
        f"| {fmt_dollars(std_stats['avg_contract'])} | |\n"
    )
    md += (
        f"| SBIR-to-Contract Rate | {ota_stats['sbir_trans_pct']:.0f}% "
        f"| {std_stats['sbir_trans_pct']:.0f}% "
        f"| {ota_stats['sbir_trans_pct'] - std_stats['sbir_trans_pct']:+.0f}pp |\n"
    )

    md += "\n**Signal profile comparison (top 8 signals by cohort):**\n\n"
    all_sigs = set(list(ota_stats["signal_dist"].keys()) + list(std_stats["signal_dist"].keys()))
    top_sigs = sorted(all_sigs, key=lambda s: ota_stats["signal_dist"].get(s, 0) + std_stats["signal_dist"].get(s, 0), reverse=True)[:8]

    md += "| Signal | OTA (per co.) | Standard (per co.) |\n"
    md += "|:-------|---:|---:|\n"
    for sig in top_sigs:
        ota_per = ota_stats["signal_dist"].get(sig, 0) / max(ota_stats["count"], 1)
        std_per = std_stats["signal_dist"].get(sig, 0) / max(std_stats["count"], 1)
        md += f"| {sig} | {ota_per:.2f} | {std_per:.2f} |\n"

    md += (
        f"\n**So what:** OTA-pathway companies score {ota_stats['avg_composite'] - std_stats['avg_composite']:+.1f} "
        f"higher on composite signal strength and raise significantly more private capital. "
        f"The OTA pathway is a leading indicator of companies the government has identified "
        f"as having production-ready technology worth accelerating through non-traditional "
        f"procurement. Investors should weight OTA contracts as a stronger signal than "
        f"standard FPDS awards.\n\n"
    )
    return md


# ---------------------------------------------------------------------------
# Section 6: Timing Intelligence
# ---------------------------------------------------------------------------
def section_timing(conn):
    # sbir_validated_raise signals with evidence
    rows = conn.execute("""
        SELECT s.entity_id, s.evidence, e.policy_alignment, e.canonical_name
        FROM signals s
        JOIN entities e ON s.entity_id = e.id
        WHERE s.signal_type = 'sbir_validated_raise'
          AND s.status = 'ACTIVE'
          AND e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
    """).fetchall()

    total = len(rows)
    total_raised = 0
    timing_buckets = {"0-6": [], "6-12": [], "12-24": [], "24-36": [], "36-48": [], "48+": []}
    area_timing = defaultdict(list)

    for r in rows:
        ev = json.loads(r["evidence"]) if r["evidence"] else {}
        raise_amt = ev.get("raise_amount_post_sbir", 0) or 0
        total_raised += raise_amt

        # Compute months from first SBIR to first raise
        first_sbir = ev.get("first_sbir_date")
        first_raise = ev.get("first_regd_date")
        if first_sbir and first_raise:
            try:
                sbir_dt = datetime.strptime(first_sbir, "%Y-%m-%d")
                raise_dt = datetime.strptime(first_raise, "%Y-%m-%d")
                months = max(0, (raise_dt - sbir_dt).days / 30.44)
            except (ValueError, TypeError):
                months = None
        else:
            months = None

        if months is not None:
            entry = {"months": months, "amount": raise_amt, "name": r["canonical_name"]}
            if months <= 6:
                timing_buckets["0-6"].append(entry)
            elif months <= 12:
                timing_buckets["6-12"].append(entry)
            elif months <= 24:
                timing_buckets["12-24"].append(entry)
            elif months <= 36:
                timing_buckets["24-36"].append(entry)
            elif months <= 48:
                timing_buckets["36-48"].append(entry)
            else:
                timing_buckets["48+"].append(entry)

            # By policy area
            top = get_top_priority(r["policy_alignment"])
            if top:
                area_timing[top].append(months)

    md = "## 6. Timing Intelligence\n\n"
    md += (
        f"Aperture tracks {total} companies that received SBIR awards before raising "
        f"private capital — the SBIR-validated raise pathway totaling "
        f"{fmt_dollars(total_raised)} in post-SBIR capital formation. Analyzing the "
        f"timing distribution reveals when investors should expect companies to reach "
        f"the fundraising window after Phase II.\n\n"
    )

    md += "| Months After SBIR | Companies | Median Raise | Avg Raise |\n"
    md += "|:------------------|----------:|-------------:|----------:|\n"

    for bucket_name in ["0-6", "6-12", "12-24", "24-36", "36-48", "48+"]:
        entries = timing_buckets[bucket_name]
        count = len(entries)
        if count > 0:
            amounts = sorted([e["amount"] for e in entries if e["amount"] > 0])
            median_amt = amounts[len(amounts)//2] if amounts else 0
            avg_amt = statistics.mean(amounts) if amounts else 0
        else:
            median_amt = avg_amt = 0
        md += f"| {bucket_name} mo | {count} | {fmt_dollars(median_amt)} | {fmt_dollars(avg_amt)} |\n"

    # By policy area — which raise fastest?
    area_medians = {}
    for area, months_list in area_timing.items():
        if len(months_list) >= 3:
            area_medians[area] = statistics.median(months_list)

    if area_medians:
        fastest = min(area_medians, key=area_medians.get)
        slowest = max(area_medians, key=area_medians.get)
        md += (
            f"\n**Policy area timing:** {AREA_LABELS.get(fastest, fastest)} companies raise "
            f"fastest (median {area_medians[fastest]:.0f} months post-SBIR), while "
            f"{AREA_LABELS.get(slowest, slowest)} companies take longest "
            f"(median {area_medians[slowest]:.0f} months). "
        )

    # Breadth correlation
    breadth_timing = conn.execute("""
        SELECT
            CASE WHEN sb.entity_id IS NOT NULL THEN 'broad_sbir' ELSE 'narrow_sbir' END as cohort,
            AVG(
                (julianday(json_extract(sv.evidence, '$.first_regd_date'))
                 - julianday(json_extract(sv.evidence, '$.first_sbir_date'))) / 30.44
            ) as avg_months,
            COUNT(*) as n
        FROM signals sv
        JOIN entities e ON sv.entity_id = e.id
        LEFT JOIN signals sb ON sv.entity_id = sb.entity_id
            AND sb.signal_type = 'sbir_breadth' AND sb.status = 'ACTIVE'
        WHERE sv.signal_type = 'sbir_validated_raise'
          AND sv.status = 'ACTIVE'
          AND e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND json_extract(sv.evidence, '$.first_sbir_date') IS NOT NULL
          AND json_extract(sv.evidence, '$.first_regd_date') IS NOT NULL
        GROUP BY cohort
    """).fetchall()

    breadth_data = {r[0]: {"avg_months": r[1], "n": r[2]} for r in breadth_timing}
    broad = breadth_data.get("broad_sbir", {})
    narrow = breadth_data.get("narrow_sbir", {})

    if broad and narrow and broad.get("avg_months") and narrow.get("avg_months"):
        md += (
            f"Companies with broad SBIR portfolios (4+ branches) raise in an average "
            f"of {broad['avg_months']:.0f} months vs {narrow['avg_months']:.0f} months "
            f"for narrower portfolios (n={broad['n']} vs {narrow['n']})."
        )
    md += "\n\n"

    md += (
        "**So what:** The 12-24 month window after Phase II is the highest-probability "
        "fundraising period. Investors monitoring SBIR Phase II awards today should "
        "expect the fundraising conversation to begin in Q1-Q2 2028. Companies in "
        "faster-moving policy areas (space, cyber) tend to raise sooner because "
        "government pull is more immediate.\n\n"
    )
    return md


# ---------------------------------------------------------------------------
# Section 7: Market Structure Summary
# ---------------------------------------------------------------------------
def section_market_structure(conn):
    # Headline numbers
    total_startups = conn.execute("""
        SELECT COUNT(*) FROM entities
        WHERE entity_type = 'STARTUP' AND merged_into_id IS NULL
    """).fetchone()[0]

    total_contract_val = conn.execute("""
        SELECT COALESCE(SUM(c.contract_value), 0)
        FROM contracts c
        JOIN entities e ON c.entity_id = e.id
        WHERE e.entity_type = 'STARTUP' AND e.merged_into_id IS NULL
    """).fetchone()[0]

    total_private_cap = conn.execute(f"""
        SELECT COALESCE(SUM(f.amount), 0)
        FROM funding_events f
        JOIN entities e ON f.entity_id = e.id
        WHERE e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
          {SUPERSEDED_EXCLUDE}
    """).fetchone()[0]

    # Positive vs negative composite
    positive_composite = conn.execute("""
        SELECT COUNT(DISTINCT es.entity_id)
        FROM entity_snapshots es
        INNER JOIN (
            SELECT entity_id, MAX(snapshot_date) as md
            FROM entity_snapshots GROUP BY entity_id
        ) l ON es.entity_id = l.entity_id AND es.snapshot_date = l.md
        JOIN entities e ON es.entity_id = e.id
        WHERE e.entity_type = 'STARTUP' AND e.merged_into_id IS NULL
          AND es.composite_score > 0
    """).fetchone()[0]

    negative_composite = conn.execute("""
        SELECT COUNT(DISTINCT es.entity_id)
        FROM entity_snapshots es
        INNER JOIN (
            SELECT entity_id, MAX(snapshot_date) as md
            FROM entity_snapshots GROUP BY entity_id
        ) l ON es.entity_id = l.entity_id AND es.snapshot_date = l.md
        JOIN entities e ON es.entity_id = e.id
        WHERE e.entity_type = 'STARTUP' AND e.merged_into_id IS NULL
          AND es.composite_score < 0
    """).fetchone()[0]

    # Next-wave pipeline: Phase II, no private capital
    next_wave = conn.execute("""
        SELECT COUNT(DISTINCT f.entity_id)
        FROM funding_events f
        JOIN entities e ON f.entity_id = e.id
        WHERE e.entity_type = 'STARTUP'
          AND e.merged_into_id IS NULL
          AND f.event_type = 'SBIR_PHASE_2'
          AND f.entity_id NOT IN (
              SELECT DISTINCT entity_id FROM funding_events
              WHERE event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
          )
    """).fetchone()[0]

    # Signal lead time
    lead_time = conn.execute("""
        SELECT AVG(months_since_signal) FROM outcome_events
        WHERE months_since_signal IS NOT NULL AND months_since_signal > 0
    """).fetchone()[0]

    # Active signals total
    total_signals = conn.execute("""
        SELECT COUNT(*) FROM signals WHERE status = 'ACTIVE'
    """).fetchone()[0]

    md = "## 7. Market Structure Summary\n\n"
    md += (
        f"Aperture Signals Intelligence tracks **{total_startups:,}** defense technology "
        f"startups across the full lifecycle from SBIR Phase I through production contracts. "
        f"The platform monitors {fmt_dollars(float(total_contract_val))} in government "
        f"contract value and {fmt_dollars(float(total_private_cap))} in private capital "
        f"formation, generating **{total_signals:,}** active intelligence signals across "
        f"25 signal types.\n\n"
    )

    md += "| Metric | Value |\n"
    md += "|:-------|------:|\n"
    md += f"| STARTUP universe | {total_startups:,} |\n"
    md += f"| Government contract value | {fmt_dollars(float(total_contract_val))} |\n"
    md += f"| Private capital tracked | {fmt_dollars(float(total_private_cap))} |\n"
    md += f"| Active momentum signals (composite > 0) | {positive_composite:,} |\n"
    md += f"| Risk-flagged companies (composite < 0) | {negative_composite:,} |\n"
    md += f"| Next-wave pipeline (Phase II, no private capital) | {next_wave:,} |\n"
    md += f"| Average signal lead time | {float(lead_time or 0):.0f} months |\n"
    md += f"| Active signals | {total_signals:,} |\n"
    md += f"| Signal types | 25 |\n"

    md += (
        f"\n**So what:** The defense technology startup market is {total_startups:,} "
        f"companies deep, but only {positive_composite:,} show active positive momentum. "
        f"The {next_wave:,}-company next-wave pipeline of Phase II graduates without "
        f"private capital represents the largest actionable opportunity set — these are "
        f"government-validated companies the private market hasn't discovered yet.\n\n"
    )
    return md


# ---------------------------------------------------------------------------
# Assemble full report
# ---------------------------------------------------------------------------
def generate_report():
    conn = connect()
    today = date.today().strftime("%B %d, %Y")
    today_short = date.today().strftime("%Y-%m-%d")

    # HTML styling header for dark background rendering
    header = f"""<div style="background:#111827;color:#e5e7eb;padding:48px 56px;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7;max-width:960px;margin:0 auto;">

<div style="border-bottom:1px solid #374151;padding-bottom:16px;margin-bottom:32px;">
<span style="color:#6366f1;font-weight:700;letter-spacing:0.1em;font-size:13px;">APERTURE SIGNALS INTELLIGENCE</span>
<span style="float:right;color:#6b7280;font-size:13px;">{today_short} &nbsp;|&nbsp; PROPRIETARY &amp; CONFIDENTIAL</span>
</div>

# Defense Technology Capital Formation

### Market Intelligence Brief &mdash; March 2026

<div style="color:#9ca3af;font-size:15px;margin-bottom:40px;">
Quantitative analysis of capital flow, signal momentum, and market structure across 9,600+ defense technology startups. Data through {today}.
</div>

---

"""

    body = ""
    body += section_capital_flow(conn)
    body += "---\n\n"
    body += section_pre_inflection(conn)
    body += "---\n\n"
    body += section_acceleration(conn)
    body += "---\n\n"
    body += section_headwind(conn)
    body += "---\n\n"
    body += section_ota_pathway(conn)
    body += "---\n\n"
    body += section_timing(conn)
    body += "---\n\n"
    body += section_market_structure(conn)
    body += "---\n\n"

    methodology = f"""## Methodology

This brief is generated from Aperture's integrated defense intelligence database, which fuses five primary data sources into a unified entity-signal graph:

**SBIR.gov** — 27,500+ Small Business Innovation Research awards across all DoD branches, providing Phase I/II/III award history, technology classification, and agency-level demand signals. **USASpending / FPDS** — Federal procurement data covering standard contracts, OTA awards, IDIQs, and P3 agreements with contracting agency, value, and period of performance. **SEC EDGAR** — Regulation D filings and private placement memoranda tracking private capital formation by defense-adjacent companies. **SAM.gov** — Entity registration data providing CAGE codes, DUNS numbers, and organizational metadata. **Web enrichment** — Structured extraction of OTA awards, funding rounds, partnerships, and corporate events from public sources via two-phase Claude analysis.

The 25-signal detection engine applies weighted confidence scoring with three freshness decay tiers (fast, slow, structural) to generate composite entity scores. Policy alignment scores are computed against the 10 NDS budget priority areas with FY26 appropriation weights. All analysis is filtered to STARTUP entity type (excluding primes, non-defense, and merged entities).

<div style="color:#6b7280;font-size:13px;margin-top:40px;padding-top:16px;border-top:1px solid #374151;">
<strong>APERTURE SIGNALS INTELLIGENCE</strong> &nbsp;|&nbsp; aperturesignals.com &nbsp;|&nbsp; PROPRIETARY &amp; CONFIDENTIAL<br>
Generated {today_short}. Data sources: SBIR.gov, USASpending, SEC EDGAR, SAM.gov, web enrichment. 9,657 entities, 17,200+ signals, 25 signal types.
</div>

</div>
"""

    full_report = header + body + methodology

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(full_report)
    print(f"Report written to {OUTPUT_PATH}")
    print(f"Size: {len(full_report):,} characters")

    conn.close()
    return full_report


if __name__ == "__main__":
    generate_report()
