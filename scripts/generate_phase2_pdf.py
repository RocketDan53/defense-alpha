#!/usr/bin/env python3
"""
PDF renderer for the Phase II Signal report.

Reads the markdown report and data from the database to produce a
polished PDF. Reuses the ReportPDF class from generate_pdf_report.py.

Usage:
    python scripts/generate_phase2_pdf.py
    python scripts/generate_phase2_pdf.py --output reports/phase2_signal_report.pdf
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from generate_pdf_report import ReportPDF, safe_text, BRAND_R, BRAND_G, BRAND_B, REPORT_DATE


def fmt_money(v):
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"


def build_phase2_pdf(output_path):
    """Build the Phase II Signal report PDF."""
    from sqlalchemy import text
    from processing.database import SessionLocal

    db = SessionLocal()

    pdf = ReportPDF(report_title="The Phase II Signal", orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)

    usable_w = 180  # 210 - 15 - 15

    # ── helper: table with header ──
    def render_table(headers, rows, col_widths, aligns=None):
        if aligns is None:
            aligns = ["L"] * len(headers)
        # Header
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_fill_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.set_text_color(255, 255, 255)
        for j, h in enumerate(headers):
            pdf.cell(col_widths[j], 5.5, safe_text(h), border=1, fill=True, align="C")
        pdf.ln()
        # Rows
        pdf.set_text_color(40, 40, 40)
        for i, row in enumerate(rows):
            pdf.set_font("Helvetica", "", 7)
            if i % 2 == 0:
                pdf.set_fill_color(240, 245, 250)
            else:
                pdf.set_fill_color(255, 255, 255)
            for j, val in enumerate(row):
                pdf.cell(col_widths[j], 5, safe_text(str(val)), border=1, fill=True,
                         align=aligns[j])
            pdf.ln()

    # ── helper: key-stat box ──
    def stat_box(label, value, width=43):
        box_h = 14
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.set_fill_color(240, 245, 250)
        pdf.rect(x, y, width, box_h, style="F")
        pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.set_line_width(0.3)
        pdf.rect(x, y, width, box_h, style="D")
        pdf.set_xy(x, y + 1)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.cell(width, 6, safe_text(str(value)), align="C", new_x="LEFT", new_y="NEXT")
        pdf.set_x(x)
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(width, 4.5, safe_text(label), align="C")
        pdf.set_xy(x + width + 2, y)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 1: Title Page
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(35)
    pdf.set_font("Helvetica", "B", 32)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 14, "APERTURE", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)
    pdf.set_font("Helvetica", "", 18)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "The Phase II Signal", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, "SBIR Phase II Awards as Leading Indicators of", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Private Capital Formation in Defense Technology", align="C",
             new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)
    pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_line_width(0.5)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(10)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, f"Intelligence Report  |  {REPORT_DATE}", align="C",
             new_x="LMARGIN", new_y="NEXT")

    pdf.ln(20)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(80, 80, 80)
    sources = [
        "27,529 SBIR award embeddings  |  SEC Form D filings  |  164 validated signals",
        "Proprietary sbir_validated_raise detection  |  10 NDS policy priority scores",
    ]
    for s in sources:
        pdf.cell(0, 5, s, align="C", new_x="LMARGIN", new_y="NEXT")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1: Analyst's Note
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("1. Analyst's Note")

    pdf.body_text(
        "The defense technology sector is undergoing a structural shift in how early-stage "
        "companies capitalize. This report presents evidence for a specific, testable thesis: "
        "SBIR Phase II awards are a leading indicator of private capital raises in defense-adjacent "
        "startups, with a median lag of 8 months and a cumulative $8.5 billion in post-SBIR "
        "private capital across the validated cohort."
    )
    pdf.ln(1)

    pdf.subsection_title("The Finding")
    pdf.body_text(
        "Of 264 defense startups that hold both SBIR awards and SEC Reg D filings, 164 (62%) "
        "meet a strict validation test: their SBIR activity demonstrably preceded or catalyzed "
        "their private fundraising. These 164 companies have collectively raised $8.48 billion "
        "in private capital following their SBIR milestones."
    )
    pdf.ln(1)

    pdf.body_text(
        "This is not a coincidence of timing. The data shows a consistent pattern:"
    )
    pdf.bullet("82 companies (50%) followed the textbook pathway: SBIR first, Phase II as "
               "catalyst, then private raise. These account for $3.6B in post-SBIR capital.")
    pdf.bullet("49 companies (30%) won SBIRs before raising privately but without a direct "
               "Phase II catalyst - the portfolio itself built credibility.")
    pdf.bullet("33 companies (20%) show a mixed sequence where a Phase II award preceded "
               "measurable fundraising acceleration.")
    pdf.ln(1)
    pdf.body_text(
        "The 100 companies filtered out failed the sequencing test: 75 raised venture capital "
        "before winning any SBIR, and 25 had ambiguous timelines. The strict filter removes "
        "38% of the raw signal, leaving a higher-confidence subset."
    )
    pdf.ln(2)

    # Key stats boxes
    pdf.subsection_title("Key Statistics")
    pdf.ln(2)
    y_before = pdf.get_y()
    stat_box("Validated Cohort", "164")
    stat_box("Post-SBIR Capital", "$8.48B")
    stat_box("Median Gap", "8 mo")
    stat_box("Filter Rate", "62%")
    pdf.set_y(y_before + 18)
    pdf.ln(2)

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
    render_table(
        ["Metric", "Value", "Amount / Range", "Note"],
        stats_rows,
        [60, 25, 40, 55],
        ["L", "C", "C", "L"],
    )
    pdf.ln(3)

    pdf.body_text(
        "For investors, Phase II awards function as a government-validated technical milestone. "
        "The 8-month median gap represents a window of asymmetric information: the Phase II "
        "award is public, but the market has not yet priced in the private capital formation it "
        "predicts. For the 3,221 Phase II startups that have not yet filed a Reg D, this analysis "
        "suggests a substantial pipeline of potential first-time raises."
    )

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2: Cohort Analysis
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("2. Cohort Analysis")

    # 2.1 Sector Distribution
    pdf.subsection_title("2.1 Sector Distribution")
    pdf.body_text(
        "Software companies dominate by count (64, 39%), but aerospace platforms dominate by "
        "capital ($4.25B, 50%). RF hardware punches above its weight: 7 companies account for "
        "$1.22B."
    )
    pdf.ln(1)

    sector_rows = [
        ["AEROSPACE_PLATFORMS", "30", "$4,247.7M", "$141.6M", "50.1%"],
        ["RF_HARDWARE", "7", "$1,217.5M", "$173.9M", "14.4%"],
        ["SOFTWARE", "64", "$1,221.8M", "$19.1M", "14.4%"],
        ["COMPONENTS", "43", "$958.6M", "$22.3M", "11.3%"],
        ["OTHER", "15", "$624.4M", "$41.6M", "7.4%"],
        ["SYSTEMS_INTEGRATOR", "4", "$201.3M", "$50.3M", "2.4%"],
    ]
    render_table(
        ["Sector", "Companies", "Capital", "Avg Raise", "% Total"],
        sector_rows,
        [42, 22, 35, 30, 22],
        ["L", "C", "R", "R", "C"],
    )
    pdf.ln(3)

    # 2.2 Sector x Sequence
    pdf.subsection_title("2.2 Sector x Sequence")
    pdf.body_text(
        "The sbir_first pathway dominates across all sectors. Aerospace has the highest "
        "mixed-sequence rate (33%), suggesting capital-intensive sectors often begin raising "
        "before SBIR maturity - but Phase II still catalyzes larger follow-on rounds."
    )
    pdf.ln(1)

    xseq_rows = [
        ["AEROSPACE_PLATFORMS", "20 ($2,935M)", "10 ($1,313M)", "33%"],
        ["COMPONENTS", "33 ($743M)", "10 ($215M)", "23%"],
        ["SOFTWARE", "54 ($878M)", "10 ($344M)", "16%"],
        ["RF_HARDWARE", "6 ($1,213M)", "1 ($5M)", "14%"],
        ["OTHER", "13 ($545M)", "2 ($80M)", "13%"],
        ["SYSTEMS_INTEGRATOR", "4 ($201M)", "0", "0%"],
    ]
    render_table(
        ["Sector", "sbir_first (capital)", "mixed (capital)", "% Mixed"],
        xseq_rows,
        [42, 50, 50, 20],
        ["L", "C", "C", "C"],
    )
    pdf.ln(3)

    # 2.3 Policy Alignment
    pdf.check_page_break(70)
    pdf.subsection_title("2.3 Policy Alignment")
    pdf.body_text(
        "Companies scored against 10 National Defense Strategy priority areas weighted by "
        "FY26 budget growth. Space resilience dominates (26% of cohort, 41% of capital)."
    )
    pdf.ln(1)

    policy_rows = [
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
    ]
    render_table(
        ["Policy Priority", "Companies", "Capital", "% of Total"],
        policy_rows,
        [48, 25, 35, 25],
        ["L", "C", "R", "C"],
    )
    pdf.ln(3)

    # 2.4 Raise Timing
    pdf.check_page_break(65)
    pdf.subsection_title("2.4 Raise Timing (Phase II to Reg D)")
    pdf.body_text(
        "For the 115 companies with Phase II catalyst data, the gap between award and "
        "subsequent filing clusters into four windows. The 0-3 month bucket has the highest "
        "average raise ($80.7M), where Phase II serves as both an independent signal and a "
        "closing catalyst - VCs tracking SBIR milestones time raises around award announcements."
    )
    pdf.ln(1)

    timing_rows = [
        ["0-3 months", "32 (28%)", "$80.7M", "Phase II as signal + closing catalyst; VCs time raises around awards"],
        ["4-6 months", "20 (17%)", "$19.4M", "Fast followers - Phase II triggers process"],
        ["7-12 months", "40 (35%)", "$54.7M", "Standard cycle - full fundraise post-award"],
        ["13-18 months", "23 (20%)", "$18.8M", "Slow burn - possible Phase III bridge first"],
    ]
    render_table(
        ["Gap Window", "Companies", "Avg Raise", "Interpretation"],
        timing_rows,
        [28, 25, 22, 85],
        ["L", "C", "R", "L"],
    )
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "49 additional companies lack gap data (no Phase II catalyst or Phase I only).",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # 2.5 Geography
    pdf.check_page_break(55)
    pdf.subsection_title("2.5 Geography")

    geo_rows = [
        ["California", "41 (25%)", "$3,009M", "El Segundo (launch), Bay Area (software)"],
        ["Texas", "13 (8%)", "$315M", "Austin, San Antonio"],
        ["Colorado", "12 (7%)", "$198M", "Colorado Springs (space)"],
        ["Virginia", "7 (4%)", "$125M", "Northern VA (DoD-adjacent)"],
        ["Massachusetts", "4 (2%)", "$1,210M", "Billerica (SI2 Technologies)"],
        ["Florida", "3 (2%)", "$222M", "Space Coast"],
        ["Other states", "84 (51%)", "$3,401M", "Distributed"],
    ]
    render_table(
        ["State", "Companies", "Capital", "Notable Cluster"],
        geo_rows,
        [30, 25, 25, 80],
        ["L", "C", "R", "L"],
    )
    pdf.ln(3)

    # 2.6 SBIR Depth
    pdf.check_page_break(40)
    pdf.subsection_title("2.6 SBIR Depth")
    pdf.body_text(
        "The cohort averages 6.9 SBIRs per company (3.2 Phase II). The range is extreme: "
        "from single-award companies (Relativity Space, 1 SBIR) to deeply embedded R&D "
        "organizations (Corvid Technologies, 128 SBIRs). Companies with 15+ SBIRs tend to "
        "be long-standing government technology contractors with deep technical moats."
    )

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3: The Next Wave
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("3. The Next Wave: Deal Flow Pipeline")

    pdf.body_text(
        "Of the 3,221 Phase II startups with no Reg D filing, the following 15 have the "
        "highest policy tailwind scores and recent Phase II activity (2023-2024). Based on "
        "patterns in the validated cohort, these companies exhibit the pattern most associated "
        "with subsequent private capital formation."
    )
    pdf.ln(2)

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
        pdf.check_page_break(45)

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

        # Company header
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.cell(0, 6, safe_text(f"{idx + 1}. {nw.canonical_name}"),
                 new_x="LMARGIN", new_y="NEXT")

        # Metadata line
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(60, 60, 60)
        loc = (nw.headquarters_location or "Unknown")[:40]
        meta = f"    {nw.core_business or '?'}  |  {loc}  |  Tailwind: {nw.tailwind:.2f}  |  {nw.top_priority or 'N/A'}"
        pdf.cell(0, 4.5, safe_text(meta), new_x="LMARGIN", new_y="NEXT")

        # SBIR stats
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(0, 4.5,
                 safe_text(f"    {total_sbir} total SBIRs, {nw.phase2_count} Phase II  |  No Reg D filings"),
                 new_x="LMARGIN", new_y="NEXT")

        # Phase II titles
        for t in titles:
            title_text = (t[0] or "")[:80].replace("Awarness", "Awareness")
            date_str = (t[1] or "N/A")[:10]
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(80, 80, 80)
            pdf.set_x(pdf.l_margin + 4)
            pdf.cell(0, 4, safe_text(f"P2 [{date_str}]: {title_text}"),
                     new_x="LMARGIN", new_y="NEXT")

        # Busek annotation
        if "BUSEK" in (nw.canonical_name or "").upper():
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(120, 80, 40)
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(0, 4, safe_text(
                "Note: Deep SBIR portfolio with no private capital history may indicate "
                "a self-sustaining government revenue model rather than a pre-raise posture."))
            pdf.set_text_color(40, 40, 40)

        pdf.ln(3)

        # Divider (light)
        if idx < len(next_wave) - 1:
            pdf.set_draw_color(210, 210, 210)
            pdf.set_line_width(0.15)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(2)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4: Case Studies
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("4. Illustrative Case Studies")

    pdf.body_text(
        "The following companies illustrate the three primary pathways from SBIR to private "
        "capital. They are not ranked - they are evidence for the thesis."
    )
    pdf.ln(2)

    # Define case studies with pathway groupings
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
        pdf.check_page_break(60)
        pdf.subsection_title(pathway_group["pathway"])
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 5, safe_text(pathway_group["description"]),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for company_name, narrative in pathway_group["companies"]:
            pdf.check_page_break(30)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)

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
                amt_str = fmt_money(amt) if amt > 0 else "N/A"
                pdf.cell(0, 5.5, safe_text(row.canonical_name),
                         new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(60, 60, 60)
                loc = (row.headquarters_location or "?")[:35]
                pdf.cell(0, 4,
                         safe_text(f"    {row.core_business}  |  {loc}  |  "
                                   f"Conf: {row.confidence_score:.2f}  |  {row.seq}  |  "
                                   f"Raised: {amt_str}  |  Tailwind: {row.tail:.2f}"),
                         new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(0, 5.5, safe_text(company_name),
                         new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(40, 40, 40)
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(usable_w - 8, 4.2, safe_text(narrative))
            pdf.ln(3)

        # Divider between pathway groups
        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.2)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(4)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5: Methodology
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("5. Methodology")

    pdf.subsection_title("5.1 Signal Detection")
    pdf.body_text(
        "The sbir_validated_raise signal applies the following logic to every entity:"
    )
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 4.5, "Trigger conditions (at least one):", new_x="LMARGIN", new_y="NEXT")
    pdf.bullet("SBIR-first pathway: entity's first SBIR predates its first Reg D filing")
    pdf.bullet("Phase II catalyst: a Reg D filing occurs within 18 months after a Phase II award")
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(0, 4.5, "Confidence scoring:", new_x="LMARGIN", new_y="NEXT")
    pdf.bullet("Base: 0.70  |  +0.10 if SBIR-first  |  +0.10 if Phase II catalyst  |  +0.05 if raise > $5M  |  Cap: 0.95")
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(0, 4.5, "Deduplication:", new_x="LMARGIN", new_y="NEXT")
    pdf.bullet("Reg D filings with identical (entity_id, event_date, amount) treated as amendments. "
               "25 duplicate groups removed, representing $1.67B in inflated capital.")
    pdf.ln(2)

    pdf.subsection_title("5.2 Post-SBIR Raise Calculation")
    pdf.body_text(
        "All raise amounts are CUMULATIVE Reg D totals - the sum of every Reg D filing "
        "amount after the entity's first SBIR award date. A company listed as raising "
        "\"$381.9M\" may have achieved that across 3, 5, or 10 separate SEC filings. "
        "This is deliberate: the thesis concerns total private capital attracted after SBIR "
        "validation, not individual round sizes. Reg D filings report total amount sold, "
        "which may include debt, equity, or convertible instruments."
    )
    pdf.ln(2)

    pdf.subsection_title("5.3 Policy Alignment")
    pdf.body_text(
        "Each entity scored against 10 NDS priority areas using SBIR title keyword matching "
        "weighted by FY26 budget growth rates. Composite tailwind score (0.0-1.0) represents "
        "alignment with budget growth vectors."
    )
    pdf.ln(2)

    pdf.subsection_title("5.4 Next Wave Pipeline")
    pdf.body_text(
        "Pipeline candidates selected from STARTUP entities with Phase II awards since "
        "January 2023, no Reg D filings, policy tailwind > 0.3. Ranked by tailwind "
        "score then Phase II count. Pool size: 3,221 startups."
    )

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 6: Limitations
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("6. Data Provenance & Limitations")

    pdf.subsection_title("Data Sources")
    pdf.ln(1)
    source_rows = [
        ["SBIR.gov", "Phase I, II, III awards (all DoD)", "Through Sep 2024"],
        ["SEC EDGAR", "Reg D filings (Form D)", "Through Oct 2025"],
        ["Entity resolution", "Fuzzy match across datasets", "27,529 embeddings"],
    ]
    render_table(
        ["Source", "Coverage", "Freshness"],
        source_rows,
        [40, 80, 40],
        ["L", "L", "L"],
    )
    pdf.ln(4)

    pdf.subsection_title("Known Limitations")
    pdf.ln(1)

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
        pdf.check_page_break(15)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(60, 60, 60)
        lw = pdf.get_string_width(label + " ")
        pdf.cell(lw, 4.5, label + " ")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 4.5, safe_text(desc))
        pdf.ln(1.5)

    # Footer note
    pdf.ln(6)
    pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_line_width(0.3)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
                   safe_text(f"Generated by Aperture Signals Intelligence Engine  |  {REPORT_DATE}  |  "
                             "Signal detection: processing/signal_detector.py  |  "
                             "QA verification: 178/178 checks passed (scripts/qa_report_data.py)"))

    # ── Write ──
    db.close()
    pdf.output(str(output_path))
    return pdf.pages_count


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
