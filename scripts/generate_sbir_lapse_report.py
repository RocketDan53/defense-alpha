#!/usr/bin/env python3
"""Generate SBIR Lapse Exposure Report.

Analyzes defense startups exposed to the SBIR/STTR authorization lapse
(Oct 1, 2025) and produces a branded intelligence report.

Usage:
    python scripts/generate_sbir_lapse_report.py
    python scripts/generate_sbir_lapse_report.py --pdf
    python scripts/generate_sbir_lapse_report.py --output reports/custom_name.md --pdf
"""

import sqlite3
import json
import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))
DB_PATH = PROJECT_DIR / "data" / "defense_alpha.db"
REPORTS_DIR = PROJECT_DIR / "reports"

LAPSE_DATE = date(2025, 10, 1)
NDAA_SIGNED = date(2025, 12, 18)

SECTOR_NAMES = {
    "RF_HARDWARE": "RF & Communications Hardware",
    "SOFTWARE": "Defense Software & AI",
    "AEROSPACE_PLATFORMS": "Aerospace & Unmanned Systems",
    "COMPONENTS": "Defense Components & Materials",
    "SYSTEMS_INTEGRATOR": "Systems Integration",
    "SERVICES": "Defense Services",
    "OTHER": "Other Defense Technology",
    "unclassified": "Unclassified",
}

SECTOR_CONTEXT = {
    "RF_HARDWARE": (
        "RF and communications hardware companies typically require 3-5 years of "
        "SBIR-funded R&D to develop defense-grade prototypes. Disruption at the Phase I "
        "to Phase II transition point delays technology maturation for tactical radios, "
        "antenna systems, and electronic warfare components."
    ),
    "SOFTWARE": (
        "Defense software companies often use SBIR to fund initial DoD-specific integration "
        "and security certification. Companies in this sector may have commercial products "
        "that can sustain operations, but those without commercial revenue face immediate "
        "development pipeline freezes."
    ),
    "AEROSPACE_PLATFORMS": (
        "Aerospace and unmanned systems companies have among the highest capital requirements "
        "in defense tech. SBIR-funded flight testing, airworthiness certification, and "
        "prototype iterations cannot easily be replaced by private capital alone, particularly "
        "for hardware-intensive programs."
    ),
    "COMPONENTS": (
        "Defense component manufacturers -- including materials science, energetics, and "
        "subsystem providers -- rely on SBIR to bridge the gap between lab-scale innovation "
        "and production-ready qualification. Disruption here cascades to prime contractor "
        "supply chains."
    ),
    "SYSTEMS_INTEGRATOR": (
        "Systems integrators use SBIR funding to develop novel integration approaches and "
        "prototype multi-system architectures. These companies often have existing contract "
        "revenue but depend on SBIR for next-generation R&D."
    ),
    "SERVICES": (
        "Defense services companies typically have lower capital intensity and may be less "
        "disrupted by the SBIR lapse. However, companies developing proprietary tools or "
        "capabilities through SBIR face gaps in their technology differentiation pipeline."
    ),
    "OTHER": (
        "This category includes cross-domain companies and emerging technology areas not "
        "captured by standard defense sector classifications."
    ),
    "unclassified": (
        "These companies have not yet been classified by Aperture's analysis pipeline. "
        "SBIR data is available but full sector context is pending."
    ),
}


def _title_case_entity(name: str) -> str:
    """Convert ALL CAPS entity names to readable title case."""
    name = name.strip()
    result = name.title()
    # Fix common suffixes
    suffix_fixes = {
        " Inc": " Inc.", " Llc": " LLC", " Corp": " Corp.",
        " Ltd": " Ltd.", " Lp": " LP", " Pllc": " PLLC",
        ",Inc.": ", Inc.", ", Inc": ", Inc.", ",Llc": ", LLC",
        ", Llc": ", LLC",
    }
    for wrong, right in suffix_fixes.items():
        if result.endswith(wrong):
            result = result[:-len(wrong)] + right
    # Fix known abbreviations that title() mangles
    fixes = {
        "Ai ": "AI ", "Rf ": "RF ", "Uas ": "UAS ", "Uav ": "UAV ",
        "Ew ": "EW ", "Isr ": "ISR ", "Gps ": "GPS ", "Pnt ": "PNT ",
        " Ii ": " II ", " Iii ": " III ", " Iv ": " IV ",
        "Usa ": "USA ", "Us ": "US ", " Llc": " LLC",
        "Dba ": "DBA ", "Dod ": "DoD ", " Ar ": " AR ",
        "Hq ": "HQ ", " De ": " de ", " Of ": " of ",
        " And ": " and ", " The ": " the ", " For ": " for ",
    }
    for wrong, right in fixes.items():
        result = result.replace(wrong, right)
    return result


def _fmt_dollars(amount, unit="K"):
    """Format dollar amount in specified unit."""
    if amount is None or amount == 0:
        return "None" if unit == "M" else "$0"
    if unit == "M":
        return f"${amount / 1_000_000:.1f}M"
    elif unit == "K":
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def _get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _query_exposed_companies(conn):
    """Get all sbir_lapse_risk flagged companies with entity data."""
    rows = conn.execute("""
        SELECT
            e.id,
            e.canonical_name,
            e.core_business,
            e.technology_tags,
            s.evidence,
            s.confidence_score
        FROM signals s
        JOIN entities e ON s.entity_id = e.id
        WHERE s.signal_type = 'sbir_lapse_risk'
        AND s.status = 'ACTIVE'
        AND e.entity_type = 'STARTUP'
        ORDER BY s.confidence_score DESC
    """).fetchall()

    companies = []
    entity_ids = []
    for r in rows:
        evidence = json.loads(r["evidence"]) if r["evidence"] else {}
        companies.append({
            "id": r["id"],
            "name": r["canonical_name"],
            "display_name": _title_case_entity(r["canonical_name"]),
            "sector": r["core_business"] if r["core_business"] else "unclassified",
            "technology_tags": r["technology_tags"],
            "sbir_total": evidence.get("sbir_total", 0),
            "contract_total": evidence.get("contract_total", 0),
            "regd_total": evidence.get("regd_total", 0),
            "sbir_dependency_pct": evidence.get("sbir_dependency_pct", 0),
            "total_gov_funding": evidence.get("total_gov_funding", 0),
            "risk_level": evidence.get("risk_level", "unknown"),
            "confidence": float(r["confidence_score"]),
        })
        entity_ids.append(r["id"])

    return companies, entity_ids


def _query_phases(conn, entity_ids):
    """Get highest SBIR phase per entity."""
    if not entity_ids:
        return {}
    placeholders = ",".join("?" * len(entity_ids))
    rows = conn.execute(f"""
        SELECT
            entity_id,
            MAX(CASE
                WHEN event_type = 'SBIR_PHASE_3' THEN 3
                WHEN event_type = 'SBIR_PHASE_2' THEN 2
                ELSE 1
            END) as max_phase
        FROM funding_events
        WHERE event_type LIKE 'SBIR_%'
        AND entity_id IN ({placeholders})
        GROUP BY entity_id
    """, entity_ids).fetchall()
    return {r["entity_id"]: r["max_phase"] for r in rows}


def _query_agencies(conn, entity_ids):
    """Get distinct SBIR funding agencies per entity."""
    if not entity_ids:
        return {}
    placeholders = ",".join("?" * len(entity_ids))
    # Use Branch field (Agency is always "Department of Defense")
    rows = conn.execute(f"""
        SELECT
            entity_id,
            GROUP_CONCAT(DISTINCT
                COALESCE(
                    json_extract(raw_data, '$.Branch'),
                    json_extract(raw_data, '$."Branch"')
                )
            ) as agencies
        FROM funding_events
        WHERE event_type LIKE 'SBIR_%'
        AND entity_id IN ({placeholders})
        GROUP BY entity_id
    """, entity_ids).fetchall()

    result = {}
    for r in rows:
        agencies_str = r["agencies"] or ""
        # Deduplicate and clean
        agencies = set()
        for a in agencies_str.split(","):
            a = a.strip()
            if a and a != "None":
                agencies.add(a)
        result[r["entity_id"]] = sorted(agencies)
    return result


def _query_diversified(conn):
    """Get companies with significant SBIR but NOT lapse-risk flagged."""
    rows = conn.execute("""
        SELECT
            e.id,
            e.canonical_name,
            e.core_business,
            COALESCE((SELECT SUM(amount) FROM funding_events
                      WHERE entity_id = e.id AND event_type LIKE 'SBIR_%'), 0) as sbir_total,
            COALESCE((SELECT SUM(amount) FROM funding_events
                      WHERE entity_id = e.id
                      AND event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
                      AND id NOT IN (SELECT parent_event_id FROM funding_events WHERE parent_event_id IS NOT NULL)
                      ), 0) as regd_total,
            COALESCE((SELECT SUM(contract_value) FROM contracts
                      WHERE entity_id = e.id), 0) as contract_total
        FROM entities e
        WHERE e.entity_type = 'STARTUP'
        AND e.id NOT IN (SELECT entity_id FROM signals WHERE signal_type = 'sbir_lapse_risk' AND status = 'ACTIVE')
        AND COALESCE((SELECT SUM(amount) FROM funding_events
                      WHERE entity_id = e.id AND event_type LIKE 'SBIR_%'), 0) >= 500000
        AND (SELECT COUNT(*) FROM funding_events
             WHERE entity_id = e.id AND event_type LIKE 'SBIR_%') >= 2
        ORDER BY regd_total DESC
        LIMIT 10
    """).fetchall()

    return [{
        "name": r["canonical_name"],
        "display_name": _title_case_entity(r["canonical_name"]),
        "sector": r["core_business"] or "unclassified",
        "sbir_total": r["sbir_total"],
        "regd_total": r["regd_total"],
        "contract_total": r["contract_total"],
        "sbir_dependency": round(r["sbir_total"] / max(r["sbir_total"] + r["contract_total"], 1) * 100, 1),
    } for r in rows]


def _query_universe_stats(conn):
    """Get overall database stats for About section."""
    return {
        "total_entities": conn.execute(
            "SELECT COUNT(*) FROM entities WHERE entity_type = 'STARTUP'"
        ).fetchone()[0],
        "total_sbir": conn.execute(
            "SELECT COUNT(*) FROM funding_events WHERE event_type LIKE 'SBIR_%'"
        ).fetchone()[0],
        "total_contracts": conn.execute(
            "SELECT COUNT(*) FROM contracts"
        ).fetchone()[0],
        "total_funding": conn.execute(
            "SELECT COUNT(*) FROM funding_events"
        ).fetchone()[0],
    }


def _query_diversified_totals(conn):
    """Get aggregate stats for the diversified comparison cohort."""
    row = conn.execute("""
        SELECT
            COUNT(*) as cnt,
            COALESCE(SUM(regd_total), 0) as total_regd,
            COALESCE(SUM(contract_total), 0) as total_contracts
        FROM (
            SELECT
                e.id,
                COALESCE((SELECT SUM(amount) FROM funding_events
                          WHERE entity_id = e.id AND event_type LIKE 'SBIR_%'), 0) as sbir_total,
                COALESCE((SELECT SUM(amount) FROM funding_events
                          WHERE entity_id = e.id
                          AND event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
                          AND id NOT IN (SELECT parent_event_id FROM funding_events WHERE parent_event_id IS NOT NULL)
                          ), 0) as regd_total,
                COALESCE((SELECT SUM(contract_value) FROM contracts
                          WHERE entity_id = e.id), 0) as contract_total
            FROM entities e
            WHERE e.entity_type = 'STARTUP'
            AND e.id NOT IN (SELECT entity_id FROM signals WHERE signal_type = 'sbir_lapse_risk' AND status = 'ACTIVE')
            AND COALESCE((SELECT SUM(amount) FROM funding_events
                          WHERE entity_id = e.id AND event_type LIKE 'SBIR_%'), 0) >= 500000
            AND (SELECT COUNT(*) FROM funding_events
                 WHERE entity_id = e.id AND event_type LIKE 'SBIR_%') >= 2
        )
    """).fetchone()
    return {
        "count": row["cnt"],
        "total_regd": row["total_regd"],
        "total_contracts": row["total_contracts"],
    }


def _build_sector_data(companies, phases, agencies):
    """Group companies by sector and compute sector-level stats."""
    sectors = defaultdict(list)
    for c in companies:
        sector = c["sector"]
        if not sector or sector == "None":
            sector = "unclassified"
        elif sector not in SECTOR_NAMES:
            sector = "OTHER"
        c["max_phase"] = phases.get(c["id"], 1)
        c["agencies"] = agencies.get(c["id"], [])
        sectors[sector].append(c)

    # Sort companies within each sector by SBIR total descending
    for sector in sectors:
        sectors[sector].sort(key=lambda x: x["sbir_total"], reverse=True)

    # Build summary stats per sector
    sector_stats = {}
    for sector, comps in sectors.items():
        sbir_total = sum(c["sbir_total"] for c in comps)
        phase2_plus = sum(1 for c in comps if c["max_phase"] >= 2)
        with_private = sum(1 for c in comps if c["regd_total"] > 0)
        fully_dependent = sum(1 for c in comps if c["regd_total"] == 0)
        sector_stats[sector] = {
            "name": SECTOR_NAMES.get(sector, sector.replace("_", " ").title()),
            "count": len(comps),
            "sbir_total": sbir_total,
            "phase2_plus": phase2_plus,
            "with_private": with_private,
            "fully_dependent": fully_dependent,
            "companies": comps,
        }

    # Sort sectors by total SBIR dollars descending
    sorted_sectors = sorted(sector_stats.items(), key=lambda x: x[1]["sbir_total"], reverse=True)
    return sorted_sectors


def _phase_label(phase_num):
    return {1: "I", 2: "II", 3: "III"}.get(phase_num, str(phase_num))


# =============================================================================
# Markdown Report
# =============================================================================

def generate_markdown(companies, phases, agencies, diversified, diversified_totals, stats, report_date):
    """Generate the full markdown report."""
    lines = []

    months_since = (report_date.year - LAPSE_DATE.year) * 12 + report_date.month - LAPSE_DATE.month
    total_exposed = len(companies)
    sbir_dollars = sum(c["sbir_total"] for c in companies) / 1_000_000
    agency_set = set()
    for c in companies:
        agency_set.update(agencies.get(c["id"], []))
    phase2_count = sum(1 for c in companies if phases.get(c["id"], 1) >= 2)
    pct_no_private = round(sum(1 for c in companies if c["regd_total"] == 0) / max(total_exposed, 1) * 100, 0)

    # Cover
    lines.append("# APERTURE SIGNALS INTELLIGENCE")
    lines.append("")
    lines.append("## SBIR PIPELINE DISRUPTION REPORT")
    lines.append("### Defense Startups Exposed to the SBIR/STTR Authorization Lapse")
    lines.append("")
    lines.append(f"**Date:** {report_date.strftime('%B %d, %Y')}")
    lines.append("")
    lines.append("**PROPRIETARY & CONFIDENTIAL**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 1: Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(
        f"On October 1, 2025, SBIR/STTR program authorizations lapsed. The FY2026 NDAA, "
        f"signed December 18, 2025, did not reauthorize the program. As of "
        f"{report_date.strftime('%B %d, %Y')}, {months_since} months into the lapse, "
        f"Aperture Signals has identified {total_exposed:,} defense technology companies "
        f"with active SBIR pipelines and limited alternative funding. These companies hold "
        f"a combined ${sbir_dollars:,.1f}M in SBIR awards across {len(agency_set)} federal "
        f"agencies. {phase2_count:,} companies have reached Phase II -- indicating validated "
        f"technology that was on track for transition to production. {pct_no_private:.0f}% "
        f"have raised no private capital, making them entirely dependent on government R&D "
        f"funding that is now disrupted."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 2: Impact by Sector
    sorted_sectors = _build_sector_data(companies, phases, agencies)

    lines.append("## Impact by Sector")
    lines.append("")
    lines.append("| Sector | Companies | Total SBIR ($M) | Phase II+ | With Private Capital | Fully Dependent |")
    lines.append("|--------|-----------|-----------------|-----------|---------------------|-----------------|")
    for sector_key, sdata in sorted_sectors:
        lines.append(
            f"| {sdata['name']} | {sdata['count']} | "
            f"${sdata['sbir_total'] / 1_000_000:.1f}M | "
            f"{sdata['phase2_plus']} | "
            f"{sdata['with_private']} | "
            f"{sdata['fully_dependent']} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 3: Sector Deep Dives
    lines.append("## Sector Analysis")
    lines.append("")
    for sector_key, sdata in sorted_sectors:
        if sdata["count"] < 5:
            continue

        lines.append(f"### {sdata['name']}")
        lines.append(
            f"**{sdata['count']} companies** | "
            f"**${sdata['sbir_total'] / 1_000_000:.1f}M** in SBIR awards | "
            f"**{sdata['phase2_plus']}** at Phase II+"
        )
        lines.append("")
        context = SECTOR_CONTEXT.get(sector_key, SECTOR_CONTEXT.get("other"))
        lines.append(context)
        lines.append("")

        # Company table
        lines.append("| Company | SBIR Awards ($K) | Phase | Agencies | Private Capital | Dependency |")
        lines.append("|---------|-----------------|-------|----------|-----------------|------------|")

        display_comps = sdata["companies"][:25]
        remaining = len(sdata["companies"]) - 25

        for c in display_comps:
            agency_str = ", ".join(c["agencies"][:3])
            if len(c["agencies"]) > 3:
                agency_str += f" +{len(c['agencies']) - 3}"
            private = _fmt_dollars(c["regd_total"], "K") if c["regd_total"] > 0 else "None"
            lines.append(
                f"| {c['display_name']} | "
                f"${c['sbir_total'] / 1_000:,.0f}K | "
                f"{_phase_label(c['max_phase'])} | "
                f"{agency_str} | "
                f"{private} | "
                f"{c['sbir_dependency_pct']:.0f}% |"
            )

        if remaining > 0:
            lines.append("")
            lines.append(
                f"*{remaining} additional companies not shown. "
                f"Contact Aperture Signals for the complete dataset.*"
            )

        lines.append("")
        lines.append("---")
        lines.append("")

    # Section 4: Diversified Comparison
    lines.append("## The Diversified Comparison")
    lines.append("")
    lines.append(
        f"For comparison, {diversified_totals['count']:,} companies in the Aperture dataset "
        f"have significant SBIR pipelines ($500K+) but are NOT heavily dependent on SBIR "
        f"funding. These companies raised a combined "
        f"${diversified_totals['total_regd'] / 1_000_000:,.1f}M in private capital and hold "
        f"${diversified_totals['total_contracts'] / 1_000_000:,.1f}M in production contracts, "
        f"demonstrating successful transition from R&D to commercial viability."
    )
    lines.append("")

    if diversified:
        lines.append("**Top Diversified Companies by Private Capital Raised:**")
        lines.append("")
        lines.append("| Company | SBIR ($K) | Private Capital ($M) | Contracts ($M) | SBIR Dependency |")
        lines.append("|---------|-----------|---------------------|----------------|-----------------|")
        for d in diversified:
            lines.append(
                f"| {d['display_name']} | "
                f"${d['sbir_total'] / 1_000:,.0f}K | "
                f"${d['regd_total'] / 1_000_000:.1f}M | "
                f"${d['contract_total'] / 1_000_000:.1f}M | "
                f"{d['sbir_dependency']:.0f}% |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")

    # Section 5: Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "This report is based on Aperture Signals' cross-reference of SBIR.gov award "
        "data, SEC EDGAR Form D filings, and USASpending.gov contract records. "
        "Companies are flagged as exposed when SBIR awards represent more than 70% "
        "of their total government funding and they have raised less than $1M in "
        "private capital. SBIR data includes awards through Q4 2025 (pre-lapse). "
        "Private capital data is sourced from SEC Form D filings, which capture "
        "Regulation D exemptions but may undercount total fundraising for companies "
        "that raised capital through other structures."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 6: About
    lines.append("## About Aperture Signals")
    lines.append("")
    lines.append(
        f"Aperture Signals tracks {stats['total_entities']:,} defense technology companies "
        f"across {stats['total_sbir']:,} SBIR awards, {stats['total_contracts']:,} production "
        f"contracts, and {stats['total_funding']:,} private funding events. For deal "
        f"intelligence briefs, sector reports, and investor lead analysis, contact "
        f"info@aperturesignals.com."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"*Analysis generated from Aperture Signals knowledge graph. "
        f"Data sourced from SBIR.gov, SEC EDGAR, and USASpending.gov.*"
    )

    return "\n".join(lines)


# =============================================================================
# PDF Report
# =============================================================================

def generate_pdf(md_content, companies, phases, agencies, diversified,
                 diversified_totals, stats, report_date, output_path):
    """Generate branded PDF version of the report."""
    from generate_pdf_report import ReportPDF, safe_text, BRAND_R, BRAND_G, BRAND_B

    sorted_sectors = _build_sector_data(companies, phases, agencies)

    months_since = (report_date.year - LAPSE_DATE.year) * 12 + report_date.month - LAPSE_DATE.month
    total_exposed = len(companies)
    sbir_dollars = sum(c["sbir_total"] for c in companies) / 1_000_000
    agency_set = set()
    for c in companies:
        agency_set.update(agencies.get(c["id"], []))
    phase2_count = sum(1 for c in companies if phases.get(c["id"], 1) >= 2)
    pct_no_private = round(sum(1 for c in companies if c["regd_total"] == 0) / max(total_exposed, 1) * 100, 0)

    pdf = ReportPDF(report_title="SBIR Pipeline Disruption Report", orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(12, 15, 12)

    # Cover page
    pdf.add_page()
    pdf.ln(35)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 7, "APERTURE SIGNALS INTELLIGENCE", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 12, "SBIR PIPELINE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 12, "DISRUPTION REPORT", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, safe_text("Defense Startups Exposed to the SBIR/STTR Authorization Lapse"),
             align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, report_date.strftime("%B %d, %Y"), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(20)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 6, "PROPRIETARY & CONFIDENTIAL", align="C", new_x="LMARGIN", new_y="NEXT")

    # Executive Summary
    pdf.add_page()
    pdf.section_title("Executive Summary")
    exec_summary = (
        f"On October 1, 2025, SBIR/STTR program authorizations lapsed. The FY2026 NDAA, "
        f"signed December 18, 2025, did not reauthorize the program. As of "
        f"{report_date.strftime('%B %d, %Y')}, {months_since} months into the lapse, "
        f"Aperture Signals has identified {total_exposed:,} defense technology companies "
        f"with active SBIR pipelines and limited alternative funding. These companies hold "
        f"a combined ${sbir_dollars:,.1f}M in SBIR awards across {len(agency_set)} federal "
        f"agencies. {phase2_count:,} companies have reached Phase II - indicating validated "
        f"technology that was on track for transition to production. {pct_no_private:.0f}% "
        f"have raised no private capital, making them entirely dependent on government R&D "
        f"funding that is now disrupted."
    )
    pdf.body_text(exec_summary)
    pdf.ln(5)

    # Section 2: Impact by Sector table
    pdf.section_title("Impact by Sector")

    col_widths = [52, 22, 28, 20, 32, 32]
    headers = ["Sector", "Companies", "Total SBIR", "Phase II+", "With Private Cap", "Fully Dependent"]

    # Header row
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_text_color(255, 255, 255)
    for i, (h, w) in enumerate(zip(headers, col_widths)):
        pdf.cell(w, 6, safe_text(h), border=1, fill=True, align="C")
    pdf.ln()

    # Data rows
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(40, 40, 40)
    for idx, (sector_key, sdata) in enumerate(sorted_sectors):
        if idx % 2 == 0:
            pdf.set_fill_color(245, 245, 248)
        else:
            pdf.set_fill_color(255, 255, 255)
        fill = True
        row = [
            sdata["name"],
            str(sdata["count"]),
            f"${sdata['sbir_total'] / 1_000_000:.1f}M",
            str(sdata["phase2_plus"]),
            str(sdata["with_private"]),
            str(sdata["fully_dependent"]),
        ]
        for val, w in zip(row, col_widths):
            align = "L" if val == row[0] else "C"
            pdf.cell(w, 5.5, safe_text(val), border=1, fill=fill, align=align)
        pdf.ln()

    pdf.ln(5)

    # Section 3: Sector Deep Dives
    pdf.section_title("Sector Analysis")

    for sector_key, sdata in sorted_sectors:
        if sdata["count"] < 5:
            continue

        pdf.check_page_break(60)

        pdf.subsection_title(sdata["name"])
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, safe_text(
            f"{sdata['count']} companies  |  ${sdata['sbir_total'] / 1_000_000:.1f}M in SBIR awards  |  "
            f"{sdata['phase2_plus']} at Phase II+"
        ), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        context = SECTOR_CONTEXT.get(sector_key, SECTOR_CONTEXT.get("other"))
        pdf.body_text(context)
        pdf.ln(1)

        # Company table
        comp_widths = [48, 24, 14, 40, 28, 22]
        comp_headers = ["Company", "SBIR ($K)", "Phase", "Agencies", "Private Cap", "Dep."]

        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.set_text_color(255, 255, 255)
        for h, w in zip(comp_headers, comp_widths):
            pdf.cell(w, 5, safe_text(h), border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(40, 40, 40)

        display_comps = sdata["companies"][:25]
        remaining = len(sdata["companies"]) - 25

        for idx, c in enumerate(display_comps):
            pdf.check_page_break(6)
            if idx % 2 == 0:
                pdf.set_fill_color(248, 248, 250)
            else:
                pdf.set_fill_color(255, 255, 255)

            agency_str = ", ".join(a[:15] for a in c["agencies"][:2])
            if len(c["agencies"]) > 2:
                agency_str += f" +{len(c['agencies']) - 2}"
            private = _fmt_dollars(c["regd_total"], "K") if c["regd_total"] > 0 else "None"

            row = [
                c["display_name"][:30],
                f"${c['sbir_total'] / 1_000:,.0f}K",
                _phase_label(c["max_phase"]),
                agency_str[:25],
                private,
                f"{c['sbir_dependency_pct']:.0f}%",
            ]
            aligns = ["L", "R", "C", "L", "R", "C"]
            for val, w, al in zip(row, comp_widths, aligns):
                pdf.cell(w, 5, safe_text(val), border=1, fill=True, align=al)
            pdf.ln()

        if remaining > 0:
            pdf.set_font("Helvetica", "I", 7)
            pdf.set_text_color(120, 120, 120)
            pdf.ln(1)
            pdf.cell(0, 4, safe_text(
                f"{remaining} additional companies not shown. "
                f"Contact Aperture Signals for the complete dataset."
            ), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(40, 40, 40)

        pdf.ln(5)

    # Section 4: Diversified Comparison
    pdf.check_page_break(80)
    pdf.section_title("The Diversified Comparison")
    pdf.body_text(
        f"For comparison, {diversified_totals['count']:,} companies in the Aperture dataset "
        f"have significant SBIR pipelines ($500K+) but are NOT heavily dependent on SBIR "
        f"funding. These companies raised a combined "
        f"${diversified_totals['total_regd'] / 1_000_000:,.1f}M in private capital and hold "
        f"${diversified_totals['total_contracts'] / 1_000_000:,.1f}M in production contracts, "
        f"demonstrating successful transition from R&D to commercial viability."
    )
    pdf.ln(3)

    if diversified:
        div_widths = [48, 26, 32, 32, 30]
        div_headers = ["Company", "SBIR ($K)", "Private Capital", "Contracts", "SBIR Dep."]

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.set_text_color(255, 255, 255)
        for h, w in zip(div_headers, div_widths):
            pdf.cell(w, 6, safe_text(h), border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(40, 40, 40)
        for idx, d in enumerate(diversified):
            if idx % 2 == 0:
                pdf.set_fill_color(245, 245, 248)
            else:
                pdf.set_fill_color(255, 255, 255)
            row = [
                d["display_name"][:30],
                f"${d['sbir_total'] / 1_000:,.0f}K",
                f"${d['regd_total'] / 1_000_000:.1f}M",
                f"${d['contract_total'] / 1_000_000:.1f}M",
                f"{d['sbir_dependency']:.0f}%",
            ]
            aligns = ["L", "R", "R", "R", "C"]
            for val, w, al in zip(row, div_widths, aligns):
                pdf.cell(w, 5.5, safe_text(val), border=1, fill=True, align=al)
            pdf.ln()

    pdf.ln(5)

    # Section 5: Methodology
    pdf.check_page_break(40)
    pdf.section_title("Methodology")
    pdf.body_text(
        "This report is based on Aperture Signals' cross-reference of SBIR.gov award "
        "data, SEC EDGAR Form D filings, and USASpending.gov contract records. "
        "Companies are flagged as exposed when SBIR awards represent more than 70% "
        "of their total government funding and they have raised less than $1M in "
        "private capital. SBIR data includes awards through Q4 2025 (pre-lapse). "
        "Private capital data is sourced from SEC Form D filings, which capture "
        "Regulation D exemptions but may undercount total fundraising for companies "
        "that raised capital through other structures."
    )
    pdf.ln(3)

    # Section 6: About
    pdf.section_title("About Aperture Signals")
    pdf.body_text(
        f"Aperture Signals tracks {stats['total_entities']:,} defense technology companies "
        f"across {stats['total_sbir']:,} SBIR awards, {stats['total_contracts']:,} production "
        f"contracts, and {stats['total_funding']:,} private funding events. For deal "
        f"intelligence briefs, sector reports, and investor lead analysis, contact "
        f"info@aperturesignals.com."
    )

    pdf.output(str(output_path))
    return pdf.page_no()


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate SBIR Lapse Exposure Report")
    parser.add_argument("--output", type=str, help="Output markdown path")
    parser.add_argument("--pdf", action="store_true", help="Also generate PDF version")
    parser.add_argument("--enrich", action="store_true",
                        help="Run enrichment on top companies per sector before generating report")
    parser.add_argument("--enrich-per-sector", type=int, default=25,
                        help="Number of top companies per sector to enrich (default: 25)")
    args = parser.parse_args()

    report_date = date.today()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.output:
        md_path = Path(args.output)
    else:
        md_path = REPORTS_DIR / f"sbir_lapse_exposure_{report_date.isoformat()}.md"

    # Run enrichment first if requested
    if args.enrich:
        print(f"Enriching top {args.enrich_per_sector} companies per sector...")
        from batch_enrich import enrich_for_report
        results = enrich_for_report(
            report_type="sbir_lapse",
            top_per_sector=args.enrich_per_sector,
        )
        print(f"  Enriched {results.get('processed', 0)} entities, "
              f"{results.get('findings', 0)} new findings")
        print(f"  Generating report with enriched data...")

    conn = _get_connection()

    print("Querying exposed companies...")
    companies, entity_ids = _query_exposed_companies(conn)
    print(f"  Found {len(companies):,} exposed companies")

    print("Querying SBIR phases...")
    phases = _query_phases(conn, entity_ids)

    print("Querying funding agencies...")
    agencies = _query_agencies(conn, entity_ids)

    print("Querying diversified comparison cohort...")
    diversified = _query_diversified(conn)
    diversified_totals = _query_diversified_totals(conn)
    print(f"  Found {diversified_totals['count']:,} diversified companies")

    print("Querying universe stats...")
    stats = _query_universe_stats(conn)

    conn.close()

    # Generate markdown
    print(f"Generating markdown report...")
    md_content = generate_markdown(
        companies, phases, agencies, diversified, diversified_totals, stats, report_date
    )
    md_path.write_text(md_content)
    print(f"  Written to {md_path}")

    # Generate PDF
    if args.pdf:
        pdf_path = md_path.with_suffix(".pdf")
        print(f"Generating PDF report...")
        pages = generate_pdf(
            md_content, companies, phases, agencies, diversified,
            diversified_totals, stats, report_date, pdf_path
        )
        print(f"  Written to {pdf_path} ({pages} pages)")

    print("Done.")


if __name__ == "__main__":
    main()
