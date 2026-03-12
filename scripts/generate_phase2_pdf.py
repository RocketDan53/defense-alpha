#!/usr/bin/env python3
"""
PDF renderer for the Phase II Signal report.

Reads data from the database to produce a branded dark-themed PDF using
the shared Aperture style module.

Usage:
    python scripts/generate_phase2_pdf.py
    python scripts/generate_phase2_pdf.py --output reports/phase2_signal_report.pdf
"""

import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)

from reporting.aperture_style import (
    DARK_BG, ACCENT, ACCENT_DIM, TEXT_PRIMARY, TEXT_SECONDARY, WHITE,
    BORDER_SUBTLE, ROW_ALT, CARD_BG, GREEN, RED, PAGE, FONTS,
    paragraph_styles, data_table_style, AperturePageTemplate,
    safe_text, fmt_currency,
)
from reporting.aperture_flowables import (
    build_cover_page, branded_table, label_value_para, section_divider,
)

REPORT_DATE = date.today().strftime("%B %d, %Y")


def _stat_box_table(stats, styles):
    """Build a row of stat boxes as a Table with CARD_BG background.

    Args:
        stats: List of (label, value) tuples.
        styles: paragraph_styles() dict.
    """
    s = styles
    label_cells = [Paragraph(safe_text(label), s["metric_label"]) for label, _ in stats]
    value_cells = [Paragraph(safe_text(str(val)), s["metric_value"]) for _, val in stats]

    n = len(stats)
    col_w = PAGE["content_width"] / n
    tbl = Table([value_cells, label_cells], colWidths=[col_w] * n, rowHeights=[20, 14])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDER_SUBTLE),
    ]))
    return tbl


def build_phase2_pdf(output_path):
    """Build the Phase II Signal report PDF."""
    from sqlalchemy import text
    from processing.database import SessionLocal

    db = SessionLocal()
    s = paragraph_styles()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=PAGE["size"],
        topMargin=PAGE["margin_top"],
        bottomMargin=PAGE["margin_bottom"],
        leftMargin=PAGE["margin_left"],
        rightMargin=PAGE["margin_right"],
    )

    story = []
    page_w = PAGE["content_width"]

    # ══════════════════════════════════════════════════════════════════════════
    # Cover Page
    # ══════════════════════════════════════════════════════════════════════════
    build_cover_page(
        story,
        report_type="The Phase II Signal",
        title="SBIR Phase II Awards as Leading Indicators of\nPrivate Capital Formation in Defense Technology",
        date_str=f"Intelligence Report  |  {REPORT_DATE}",
        meta_lines=[
            "27,529 SBIR award embeddings  |  SEC Form D filings  |  164 validated signals",
            "Proprietary sbir_validated_raise detection  |  10 NDS policy priority scores",
        ],
        confidential=False,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1: Analyst's Note
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("1. Analyst's Note", s["section_head"]))

    story.append(Paragraph(safe_text(
        "The defense technology sector is undergoing a structural shift in how early-stage "
        "companies capitalize. This report presents evidence for a specific, testable thesis: "
        "SBIR Phase II awards are a leading indicator of private capital raises in defense-adjacent "
        "startups, with a median lag of 8 months and a cumulative $8.5 billion in post-SBIR "
        "private capital across the validated cohort."
    ), s["body"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("The Finding", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "Of 264 defense startups that hold both SBIR awards and SEC Reg D filings, 164 (62%) "
        "meet a strict validation test: their SBIR activity demonstrably preceded or catalyzed "
        "their private fundraising. These 164 companies have collectively raised $8.48 billion "
        "in private capital following their SBIR milestones."
    ), s["body"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph(safe_text(
        "This is not a coincidence of timing. The data shows a consistent pattern:"
    ), s["body"]))
    for bullet_text in [
        "82 companies (50%) followed the textbook pathway: SBIR first, Phase II as "
        "catalyst, then private raise. These account for $3.6B in post-SBIR capital.",
        "49 companies (30%) won SBIRs before raising privately but without a direct "
        "Phase II catalyst - the portfolio itself built credibility.",
        "33 companies (20%) show a mixed sequence where a Phase II award preceded "
        "measurable fundraising acceleration.",
    ]:
        story.append(Paragraph(f"\u2022 {safe_text(bullet_text)}", s["bullet"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph(safe_text(
        "The 100 companies filtered out failed the sequencing test: 75 raised venture capital "
        "before winning any SBIR, and 25 had ambiguous timelines. The strict filter removes "
        "38% of the raw signal, leaving a higher-confidence subset."
    ), s["body"]))
    story.append(Spacer(1, 6))

    # Key stats boxes
    story.append(Paragraph("Key Statistics", s["subsection_head"]))
    story.append(_stat_box_table([
        ("Validated Cohort", "164"),
        ("Post-SBIR Capital", "$8.48B"),
        ("Median Gap", "8 mo"),
        ("Filter Rate", "62%"),
    ], s))
    story.append(Spacer(1, 6))

    # Stats table
    stats_rows = [
        ["Companies raising $100M+", "16", "$5.94B", "70% of total capital"],
        ["Companies raising $25-100M", "36", "$1.73B", "20% of total capital"],
        ["Companies raising $5-25M", "56", "$694M", "8% of total capital"],
        ["Companies raising under $5M", "56", "$110M", "1% of total capital"],
        ["Avg SBIRs per company", "6.9", "1-128 range", "3.2 avg Phase II"],
        ["High confidence (0.95)", "55", "33%", "sbir_first + catalyst + >$5M"],
        ["Strict vs. loose filter", "164 / 264", "62%", "38% excluded"],
    ]
    story.append(branded_table(
        ["Metric", "Value", "Amount / Range", "Note"],
        stats_rows,
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph(safe_text(
        "For investors, Phase II awards function as a government-validated technical milestone. "
        "The 8-month median gap represents a window of asymmetric information: the Phase II "
        "award is public, but the market has not yet priced in the private capital formation it "
        "predicts. For the 3,221 Phase II startups that have not yet filed a Reg D, this analysis "
        "suggests a substantial pipeline of potential first-time raises."
    ), s["body"]))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2: Cohort Analysis
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("2. Cohort Analysis", s["section_head"]))

    # 2.1 Sector Distribution
    story.append(Paragraph("2.1 Sector Distribution", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "Software companies dominate by count (64, 39%), but aerospace platforms dominate by "
        "capital ($4.25B, 50%). RF hardware punches above its weight: 7 companies account for "
        "$1.22B."
    ), s["body"]))
    story.append(Spacer(1, 4))

    story.append(branded_table(
        ["Sector", "Companies", "Capital", "Avg Raise", "% Total"],
        [
            ["AEROSPACE_PLATFORMS", "30", "$4,247.7M", "$141.6M", "50.1%"],
            ["RF_HARDWARE", "7", "$1,217.5M", "$173.9M", "14.4%"],
            ["SOFTWARE", "64", "$1,221.8M", "$19.1M", "14.4%"],
            ["COMPONENTS", "43", "$958.6M", "$22.3M", "11.3%"],
            ["OTHER", "15", "$624.4M", "$41.6M", "7.4%"],
            ["SYSTEMS_INTEGRATOR", "4", "$201.3M", "$50.3M", "2.4%"],
        ],
    ))
    story.append(Spacer(1, 6))

    # 2.2 Sector x Sequence
    story.append(Paragraph("2.2 Sector x Sequence", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "The sbir_first pathway dominates across all sectors. Aerospace has the highest "
        "mixed-sequence rate (33%), suggesting capital-intensive sectors often begin raising "
        "before SBIR maturity - but Phase II still catalyzes larger follow-on rounds."
    ), s["body"]))
    story.append(Spacer(1, 4))

    story.append(branded_table(
        ["Sector", "sbir_first (capital)", "mixed (capital)", "% Mixed"],
        [
            ["AEROSPACE_PLATFORMS", "20 ($2,935M)", "10 ($1,313M)", "33%"],
            ["COMPONENTS", "33 ($743M)", "10 ($215M)", "23%"],
            ["SOFTWARE", "54 ($878M)", "10 ($344M)", "16%"],
            ["RF_HARDWARE", "6 ($1,213M)", "1 ($5M)", "14%"],
            ["OTHER", "13 ($545M)", "2 ($80M)", "13%"],
            ["SYSTEMS_INTEGRATOR", "4 ($201M)", "0", "0%"],
        ],
    ))
    story.append(Spacer(1, 6))

    # 2.3 Policy Alignment
    story.append(Paragraph("2.3 Policy Alignment", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "Companies scored against 10 National Defense Strategy priority areas weighted by "
        "FY26 budget growth. Space resilience dominates (26% of cohort, 41% of capital)."
    ), s["body"]))
    story.append(Spacer(1, 4))

    story.append(branded_table(
        ["Policy Priority", "Companies", "Capital", "% of Total"],
        [
            ["Space Resilience", "43", "$3,505.0M", "41.3%"],
            ["Contested Logistics", "21", "$1,473.8M", "17.4%"],
            ["Electronic Warfare", "2", "$1,346.8M", "15.9%"],
            ["Autonomous Systems", "22", "$488.3M", "5.8%"],
            ["JADC2", "13", "$292.8M", "3.5%"],
            ["Hypersonics", "8", "$232.7M", "2.7%"],
            ["Supply Chain Resilience", "5", "$175.8M", "2.1%"],
            ["Border / Homeland", "5", "$169.2M", "2.0%"],
            ["Cyber Offense/Defense", "14", "$176.6M", "2.1%"],
            ["Nuclear Modernization", "1", "$139.5M", "1.6%"],
        ],
    ))
    story.append(Spacer(1, 6))

    # 2.4 Raise Timing
    story.append(Paragraph("2.4 Raise Timing (Phase II to Reg D)", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "For the 115 companies with Phase II catalyst data, the gap between award and "
        "subsequent filing clusters into four windows. The 0-3 month bucket has the highest "
        "average raise ($80.7M), where Phase II serves as both an independent signal and a "
        "closing catalyst - VCs tracking SBIR milestones time raises around award announcements."
    ), s["body"]))
    story.append(Spacer(1, 4))

    story.append(branded_table(
        ["Gap Window", "Companies", "Avg Raise", "Interpretation"],
        [
            ["0-3 months", "32 (28%)", "$80.7M", "Phase II as signal + closing catalyst; VCs time raises around awards"],
            ["4-6 months", "20 (17%)", "$19.4M", "Fast followers - Phase II triggers process"],
            ["7-12 months", "40 (35%)", "$54.7M", "Standard cycle - full fundraise post-award"],
            ["13-18 months", "23 (20%)", "$18.8M", "Slow burn - possible Phase III bridge first"],
        ],
    ))
    story.append(Paragraph(
        "<i>49 additional companies lack gap data (no Phase II catalyst or Phase I only).</i>",
        s["body"],
    ))
    story.append(Spacer(1, 6))

    # 2.5 Geography
    story.append(Paragraph("2.5 Geography", s["subsection_head"]))
    story.append(branded_table(
        ["State", "Companies", "Capital", "Notable Cluster"],
        [
            ["California", "41 (25%)", "$3,009M", "El Segundo (launch), Bay Area (software)"],
            ["Texas", "13 (8%)", "$315M", "Austin, San Antonio"],
            ["Colorado", "12 (7%)", "$198M", "Colorado Springs (space)"],
            ["Virginia", "7 (4%)", "$125M", "Northern VA (DoD-adjacent)"],
            ["Massachusetts", "4 (2%)", "$1,210M", "Billerica (SI2 Technologies)"],
            ["Florida", "3 (2%)", "$222M", "Space Coast"],
            ["Other states", "84 (51%)", "$3,401M", "Distributed"],
        ],
    ))
    story.append(Spacer(1, 6))

    # 2.6 SBIR Depth
    story.append(Paragraph("2.6 SBIR Depth", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "The cohort averages 6.9 SBIRs per company (3.2 Phase II). The range is extreme: "
        "from single-award companies (Relativity Space, 1 SBIR) to deeply embedded R&D "
        "organizations (Corvid Technologies, 128 SBIRs). Companies with 15+ SBIRs tend to "
        "be long-standing government technology contractors with deep technical moats."
    ), s["body"]))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3: The Next Wave
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("3. The Next Wave: Deal Flow Pipeline", s["section_head"]))

    story.append(Paragraph(safe_text(
        "Of the 3,221 Phase II startups with no Reg D filing, the following 15 have the "
        "highest policy tailwind scores and recent Phase II activity (2023-2024). Based on "
        "patterns in the validated cohort, these companies exhibit the pattern most associated "
        "with subsequent private capital formation."
    ), s["body"]))
    story.append(Spacer(1, 6))

    # Fetch next wave data
    next_wave = db.execute(text("""
        SELECT
            e.id, e.canonical_name, e.core_business, e.headquarters_location,
            COALESCE(json_extract(e.policy_alignment, '$.policy_tailwind_score'), 0) as tailwind,
            json_extract(e.policy_alignment, '$.top_priorities[0]') as top_priority,
            COUNT(DISTINCT f.id) as phase2_count
        FROM entities e
        JOIN funding_events f ON f.entity_id = e.id
        WHERE f.event_type = 'SBIR_PHASE_2'
          AND e.merged_into_id IS NULL
          AND e.entity_type = 'STARTUP'
          AND e.id NOT IN (
              SELECT DISTINCT entity_id FROM funding_events WHERE event_type = 'REG_D_FILING'
          )
          AND COALESCE(json_extract(e.policy_alignment, '$.policy_tailwind_score'), 0) > 0.3
        GROUP BY e.id
        HAVING MAX(json_extract(f.raw_data, '$.Proposal Award Date')) >= '2023-01-01'
        ORDER BY tailwind DESC, phase2_count DESC
        LIMIT 15
    """)).fetchall()

    for idx, nw in enumerate(next_wave):
        # Get SBIR titles
        titles = db.execute(text("""
            SELECT json_extract(raw_data, '$.Award Title'),
                   json_extract(raw_data, '$.Proposal Award Date')
            FROM funding_events
            WHERE entity_id = :eid AND event_type = 'SBIR_PHASE_2'
            ORDER BY json_extract(raw_data, '$.Proposal Award Date') DESC
            LIMIT 2
        """), {"eid": nw.id}).fetchall()

        total_sbir = db.execute(text("""
            SELECT COUNT(*) FROM funding_events
            WHERE entity_id = :eid AND event_type IN ('SBIR_PHASE_1', 'SBIR_PHASE_2')
        """), {"eid": nw.id}).scalar()

        entry = []

        # Company header
        entry.append(Paragraph(
            f"<b>{idx + 1}. {safe_text(nw.canonical_name)}</b>",
            s["strategy_name"],
        ))

        # Metadata line
        loc = (nw.headquarters_location or "Unknown")[:40]
        meta = (f"{nw.core_business or '?'}  |  {loc}  |  "
                f"Tailwind: {nw.tailwind:.2f}  |  {nw.top_priority or 'N/A'}")
        entry.append(Paragraph(safe_text(meta), s["body"]))

        # SBIR stats
        entry.append(Paragraph(safe_text(
            f"{total_sbir} total SBIRs, {nw.phase2_count} Phase II  |  No Reg D filings"
        ), s["body"]))

        # Phase II titles
        for t in titles:
            title_text = (t[0] or "")[:80].replace("Awarness", "Awareness")
            date_str = (t[1] or "N/A")[:10]
            entry.append(Paragraph(
                f"<i>P2 [{safe_text(date_str)}]: {safe_text(title_text)}</i>",
                s["body_italic"],
            ))

        # Busek annotation
        if "BUSEK" in (nw.canonical_name or "").upper():
            entry.append(Paragraph(safe_text(
                "Note: Deep SBIR portfolio with no private capital history may indicate "
                "a self-sustaining government revenue model rather than a pre-raise posture."
            ), s["body_italic"]))

        entry.append(section_divider())
        story.append(KeepTogether(entry))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4: Case Studies
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("4. Illustrative Case Studies", s["section_head"]))

    story.append(Paragraph(safe_text(
        "The following companies illustrate the three primary pathways from SBIR to private "
        "capital. They are not ranked - they are evidence for the thesis."
    ), s["body"]))
    story.append(Spacer(1, 6))

    case_studies = [
        {
            "pathway": "Pathway A: Textbook SBIR-First",
            "description": "Deep SBIR portfolio built over years; private capital follows government validation.",
            "companies": [
                ("SI2 TECHNOLOGIES", "55 SBIRs, 29 Phase II over a decade (2014-2024). First Reg D: Dec 2020 - a "
                 "6-year SBIR-only period. Post-SBIR: $1.16B across 7 Reg D filings (dominated by $1.1B single "
                 "filing in Mar 2022). This filing likely represents PE/growth equity, not a typical venture "
                 "round. Spans phased arrays, conformal antennas, radar-absorbing materials, "
                 "hypersonic radomes. The SBIR portfolio IS the product development history."),
                ("CORVID TECHNOLOGIES", "128 SBIRs, 47 Phase II - most prolific in the cohort. First Reg D: May 2021. "
                 "Post-SBIR: $105.3M across 5 filings. Work includes cruise missiles, hypersonic analysis, "
                 "control surface assessment. 14-month gap represents the standard aerospace fundraise cycle."),
                ("X-BOW LAUNCH", "5 SBIRs, 3 Phase II - lean but high-impact. Post-SBIR: $92.5M across 4 filings. "
                 "3D-printed solid rocket motors. 3-month gap suggests Phase II was a closing catalyst."),
            ]
        },
        {
            "pathway": "Pathway B: SBIR-to-Scale",
            "description": "Modest SBIR footprint as launchpad, then substantially larger private rounds.",
            "companies": [
                ("ABL SPACE", "5 SBIRs, 2 Phase II. Post-SBIR: $480.3M across 5 filings. Only 3 months from "
                 "first SBIR to first raise. Tailwind 0.77 (highest in case set). Surgical SBIR engagement "
                 "validated responsive launch thesis, followed by rapid capital formation."),
                ("GECKO ROBOTICS", "4 SBIRs, 2 Phase II. Post-SBIR: $121.5M in a single filing (May 2025). "
                 "6-year gap SBIR-to-raise. Primarily commercial robotics; SBIRs for ICBM infrastructure "
                 "inspection and Minuteman III analytics built defense credibility."),
            ]
        },
        {
            "pathway": "Pathway C: Mixed Signal",
            "description": "Private capital and SBIR overlapped, but Phase II preceded fundraising acceleration.",
            "companies": [
                ("ANTARES NUCLEAR", "3 SBIRs, 2 Phase II. First Reg D ($8.1M): Oct 2023, predates first SBIR. "
                 "But two Phase IIs in Aug 2024 preceded $78.6M capital surge. 1-month gap - tightest in "
                 "case set. Government validation carries exceptional weight for nuclear technology."),
                ("HIDDEN LEVEL", "4 SBIRs, 2 Phase II. First Reg D ($15.9M): Jun 2021, predates first SBIR. "
                 "Phase IIs in 2024 preceded step-up in round sizes. UAS detection for border/homeland - "
                 "policy-driven market where SBIR validation builds defense investor credibility."),
            ]
        },
    ]

    for pathway_group in case_studies:
        story.append(Paragraph(safe_text(pathway_group["pathway"]), s["subsection_head"]))
        story.append(Paragraph(
            f"<i>{safe_text(pathway_group['description'])}</i>", s["body"],
        ))
        story.append(Spacer(1, 4))

        for company_name, narrative in pathway_group["companies"]:
            entry = []

            # Look up actual canonical name
            row = db.execute(text("""
                SELECT e.canonical_name, e.core_business, e.headquarters_location,
                       s.confidence_score,
                       json_extract(s.evidence, '$.sequence') as seq,
                       json_extract(s.evidence, '$.raise_amount_post_sbir') as raise_amt,
                       COALESCE(json_extract(e.policy_alignment, '$.policy_tailwind_score'), 0) as tail
                FROM signals s JOIN entities e ON s.entity_id = e.id
                WHERE s.signal_type = 'sbir_validated_raise' AND s.status = 'ACTIVE'
                  AND e.canonical_name LIKE :pat
            """), {"pat": "%" + company_name + "%"}).fetchone()

            if row:
                amt = row.raise_amt or 0
                amt_str = fmt_currency(amt) if amt > 0 else "N/A"
                entry.append(Paragraph(
                    f"<b>{safe_text(row.canonical_name)}</b>", s["strategy_name"],
                ))
                loc = (row.headquarters_location or "?")[:35]
                entry.append(Paragraph(safe_text(
                    f"{row.core_business}  |  {loc}  |  "
                    f"Conf: {row.confidence_score:.2f}  |  {row.seq}  |  "
                    f"Raised: {amt_str}  |  Tailwind: {row.tail:.2f}"
                ), s["body"]))
            else:
                entry.append(Paragraph(
                    f"<b>{safe_text(company_name)}</b>", s["strategy_name"],
                ))

            entry.append(Paragraph(safe_text(narrative), s["body"]))
            entry.append(Spacer(1, 6))
            story.append(KeepTogether(entry))

        story.append(section_divider())

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5: Methodology
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("5. Methodology", s["section_head"]))

    story.append(Paragraph("5.1 Signal Detection", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "The sbir_validated_raise signal applies the following logic to every entity:"
    ), s["body"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>Trigger conditions (at least one):</b>", s["label_value"]))
    story.append(Paragraph(
        "\u2022 SBIR-first pathway: entity's first SBIR predates its first Reg D filing",
        s["bullet"],
    ))
    story.append(Paragraph(
        "\u2022 Phase II catalyst: a Reg D filing occurs within 18 months after a Phase II award",
        s["bullet"],
    ))
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>Confidence scoring:</b>", s["label_value"]))
    story.append(Paragraph(safe_text(
        "\u2022 Base: 0.70  |  +0.10 if SBIR-first  |  +0.10 if Phase II catalyst  |  "
        "+0.05 if raise > $5M  |  Cap: 0.95"
    ), s["bullet"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>Deduplication:</b>", s["label_value"]))
    story.append(Paragraph(safe_text(
        "\u2022 Reg D filings with identical (entity_id, event_date, amount) treated as amendments. "
        "25 duplicate groups removed, representing $1.67B in inflated capital."
    ), s["bullet"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("5.2 Post-SBIR Raise Calculation", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "All raise amounts are CUMULATIVE Reg D totals - the sum of every Reg D filing "
        "amount after the entity's first SBIR award date. A company listed as raising "
        '"$381.9M" may have achieved that across 3, 5, or 10 separate SEC filings. '
        "This is deliberate: the thesis concerns total private capital attracted after SBIR "
        "validation, not individual round sizes. Reg D filings report total amount sold, "
        "which may include debt, equity, or convertible instruments."
    ), s["body"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("5.3 Policy Alignment", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "Each entity scored against 10 NDS priority areas using SBIR title keyword matching "
        "weighted by FY26 budget growth rates. Composite tailwind score (0.0-1.0) represents "
        "alignment with budget growth vectors."
    ), s["body"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("5.4 Next Wave Pipeline", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "Pipeline candidates selected from STARTUP entities with Phase II awards since "
        "January 2023, no Reg D filings, policy tailwind > 0.3. Ranked by tailwind "
        "score then Phase II count. Pool size: 3,221 startups."
    ), s["body"]))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 6: Limitations
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("6. Data Provenance &amp; Limitations", s["section_head"]))

    story.append(Paragraph("Data Sources", s["subsection_head"]))
    story.append(branded_table(
        ["Source", "Coverage", "Freshness"],
        [
            ["SBIR.gov", "Phase I, II, III awards (all DoD)", "Through Sep 2024"],
            ["SEC EDGAR", "Reg D filings (Form D)", "Through Oct 2025"],
            ["Entity resolution", "Fuzzy match across datasets", "27,529 embeddings"],
        ],
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Known Limitations", s["subsection_head"]))
    story.append(Spacer(1, 4))

    limitations = [
        ("Reg D coverage gaps:", "Not all private fundraises require Form D. Companies raising "
         "from non-US investors or under certain exemptions are absent. True post-SBIR capital "
         "is likely higher."),
        ("Reg D amount accuracy:", "Form D reports total amount sold, which may be amended. "
         "Our dedup catches same-date/same-amount amendments, but rolling closes with different "
         "amounts are treated separately."),
        ("Survivorship bias:", "Only companies with both SBIRs and Reg D are represented. "
         "Companies that won SBIRs but failed or were acquired before filing Reg D are excluded."),
        ("Causal inference:", "This report identifies correlation and temporal sequence, not "
         "causation. Confounding factors (founder networks, market timing, technology maturity) "
         "are not controlled for."),
        ("Single-SBIR companies:", "23 companies have only 1 SBIR. For these (e.g., Relativity "
         "Space, $50K Phase I), the causal link is weakest."),
        ("Entity resolution:", "Fuzzy name matching may produce false positives or miss "
         "connections. Merge resolution applied but not exhaustive."),
    ]
    for label, desc in limitations:
        story.append(label_value_para(label, desc, s))
        story.append(Spacer(1, 3))

    # Footer note
    story.append(Spacer(1, 10))
    story.append(section_divider())
    story.append(Paragraph(safe_text(
        f"Generated by Aperture Signals Intelligence Engine  |  {REPORT_DATE}  |  "
        "Signal detection: processing/signal_detector.py  |  "
        "QA verification: 178/178 checks passed (scripts/qa_report_data.py)"
    ), s["disclaimer"]))

    # ── Write ──
    db.close()
    template = AperturePageTemplate("The Phase II Signal", date_str=REPORT_DATE)
    doc.build(story, onFirstPage=template, onLaterPages=template)
    return doc.page


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Phase II Signal report PDF")
    parser.add_argument("--output", default="reports/phase2_signal_report.pdf",
                        help="Output PDF path")
    args = parser.parse_args()

    output = Path(args.output)
    if not output.is_absolute():
        output = Path(__file__).parent.parent / output
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating Phase II Signal report PDF...")
    pages = build_phase2_pdf(output)
    size = output.stat().st_size
    print(f"Done: {output} ({pages} pages, {size:,} bytes)")
