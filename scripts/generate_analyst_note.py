#!/usr/bin/env python3
"""
One-page analyst note PDF generator.

Usage:
    python scripts/generate_analyst_note.py
"""

from datetime import date
from pathlib import Path

from fpdf import FPDF

# Dark navy brand color: #1B2A4A
BRAND_R, BRAND_G, BRAND_B = 27, 42, 74


def safe_text(text):
    """Sanitize text for latin-1 compatible PDF fonts."""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\u2014", " - ")
    text = text.replace("\u2013", "-")
    text = text.replace("\u2018", "'")
    text = text.replace("\u2019", "'")
    text = text.replace("\u201c", '"')
    text = text.replace("\u201d", '"')
    text = text.replace("\u2026", "...")
    text = text.replace("\u2192", "->")
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return text.encode("latin-1", errors="replace").decode("latin-1")


class AnalystNotePDF(FPDF):

    def __init__(self, note_date=None, **kwargs):
        super().__init__(**kwargs)
        self._note_date = note_date or date.today().strftime("%B %d, %Y")

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        self.cell(0, 5, "APERTURE", align="L")
        self.cell(0, 5, "Analyst Note", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica", "I", 6.5)
        self.set_text_color(120, 120, 120)
        usable = self.w - self.l_margin - self.r_margin
        third = usable / 3
        self.cell(third, 5, "Aperture | Proprietary & Confidential", align="L")
        self.cell(third, 5, "contact@aperturesignals.com", align="C")
        self.cell(third, 5, "", align="R")

    def section_heading(self, text):
        self.set_font("Helvetica", "B", 8.5)
        self.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        self.cell(0, 4.5, text.upper(), new_x="LMARGIN", new_y="NEXT")
        self.ln(0.5)

    def prose(self, text, size=8):
        self.set_font("Helvetica", "", size)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 3.6, safe_text(text))
        self.ln(1.2)


def build_firestorm_note(output_path):
    pdf = AnalystNotePDF(
        note_date="February 24, 2026",
        orientation="P", unit="mm", format="A4",
    )
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(15, 12, 15)
    pdf.add_page()

    # Title block
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 6, safe_text("Firestorm Labs: Drone Dominance Competitive Positioning"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "February 24, 2026", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2.5)

    # Thin divider
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)

    # PROGRAM CONTEXT
    pdf.section_heading("Program Context")
    pdf.prose(
        "The Drone Dominance Program is a $1.1B, four-phase DoD initiative to field "
        "200,000+ low-cost one-way attack drones by 2027. Twenty-five vendors are "
        "competing in the Phase I \"Gauntlet\" at Fort Benning through early March, "
        "with $150M in prototype delivery orders at stake."
    )

    # WHAT THE PROGRAM REWARDS
    pdf.section_heading("What the Program Rewards")
    pdf.prose(
        "DIU is executing. Military operators fly and evaluate - this is a field "
        "performance test, not a paper competition. The program explicitly drives "
        "unit costs down across phases while scaling production volume. The winning "
        "profile is not the most sophisticated drone - it is the most scalable, "
        "reliable, and affordable one. Companies that can demonstrate manufacturing "
        "throughput and rapid delivery have a structural advantage."
    )

    # FIRESTORM'S ADVANTAGES
    pdf.section_heading("Firestorm's Advantages")
    pdf.prose(
        "$45.2M in private capital across 6 rounds positions Firestorm as "
        "the second-best capitalized private company in the Drone Dominance "
        "field, behind only Auterion ($87.7M), and well-resourced to absorb "
        "the working capital demands of a $150M prototype order. The company's "
        "Expeditionary Manufacturing Cell (xCell) "
        "SBIR ($1.2M Phase II) is directly aligned with the program's distributed "
        "production requirement. Firestorm achieved the fastest Phase I to Phase II "
        "graduation in its cohort at 4 months, signaling execution speed. A Tier 1 "
        "composite signal score of 7.60 with strong funding velocity confirms "
        "sustained investor and government confidence."
    )

    # COMPETITIVE RISKS
    pdf.section_heading("Competitive Risks")
    pdf.prose(
        "Firestorm has zero production contracts to date - no demonstrated ability "
        "to deliver at scale. Kratos SRE is a publicly traded defense company with "
        "established UAS production lines and an existing DoD delivery track record. "
        "Griffon Aerospace holds a confirmed $6.1M Army contract (2020) and several "
        "other competitors bring existing DoD production track records. Ukrainian "
        "Defense Drones Tech Corp brings combat-tested, battlefield-proven systems. "
        "Capital does not fly drones at the Gauntlet - the product does."
    )

    # HISTORICAL PATTERN
    pdf.section_heading("Historical Pattern")
    pdf.prose(
        "Across Aperture's knowledge graph of 11,000+ defense technology entities, "
        "companies with production contract traction raised 3.4x more capital than "
        "those without (median $14.4M vs $3.8M in comparable aerospace companies). "
        "The Gauntlet is the inflection event - a prototype delivery order would "
        "validate Firestorm's transition from R&D to production and historically "
        "correlates with accelerated private capital formation. Without it, the "
        "17-month gap since Phase II without a production contract enters the risk "
        "zone where comparable companies begin to stall."
    )

    # WHAT TO WATCH
    pdf.section_heading("What to Watch")
    pdf.prose(
        "Gauntlet results are expected in early March. Key indicators: which vendors "
        "receive prototype orders, order sizes relative to the $150M pool, and "
        "delivery timeline requirements. A Firestorm selection with a meaningful "
        "order share would be the strongest validation signal to date."
    )

    # Write
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return str(out)


def build_firestorm_note_v2(output_path):
    """V2 analyst note: updated Feb 25, 2026 with deal brief data."""
    pdf = AnalystNotePDF(
        note_date="February 25, 2026",
        orientation="P", unit="mm", format="A4",
    )
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(15, 12, 15)
    pdf.add_page()

    # Title block
    pdf.set_font("Helvetica", "B", 12.5)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 6, safe_text("Firestorm Labs | Drone Dominance Positioning"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "February 25, 2026", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Thin divider
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2.5)

    # --- Helper for mixed-case section headings ---
    def section(title):
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.cell(0, 4.5, safe_text(title), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)

    body_size = 8.5
    line_h = 3.5

    # 1. Bottom Line
    section("Bottom Line")
    pdf.set_font("Helvetica", "", body_size)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, line_h, safe_text(
        "Firestorm enters the Phase I Gauntlet as one of the strongest positioned "
        "vendors in the 25-company field. A $100M Air Force IDIQ, $45.2M in private "
        "capital, and deployable manufacturing capability place them in the top tier "
        "- one of only a handful of participants with both production-scale government "
        "validation and significant private backing."
    ))
    pdf.ln(1.5)

    # 2. Firestorm's Edge
    section("Firestorm's Edge")
    pdf.set_font("Helvetica", "", body_size)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, line_h, safe_text(
        "Firestorm's government traction anchors on a $100M Air Force IDIQ awarded "
        "through the AFWERX Prime Proving Ground, which validates production-scale "
        "confidence from the service branch most invested in small UAS. The company "
        "has raised $45.2M across six Reg D rounds - second only to Auterion's $87.7M "
        "among private competitors in the Gauntlet field - with the most recent "
        "capital coming in October 2025 ($2.5M) on top of a $20M Series B in September "
        "2024. Their Expeditionary Manufacturing Cell (xCell), funded by a $1.2M Phase II "
        "SBIR, is a factory-in-a-box concept that aligns directly with the program's "
        "distributed production requirement. Manufacturing partnerships with HP for "
        "Multi Jet Fusion 3D printing and a Lockheed Martin consortium add industrial "
        "depth, while an Orqa partnership delivers an NDAA-compliant FPV quadcopter. "
        "Aperture scores Firestorm at 7.60 composite (Tier 1) with the fastest Phase I "
        "to Phase II graduation in its cohort at four months."
    ))
    pdf.ln(1.5)

    # 3. Competitive Threats
    section("Competitive Threats")
    pdf.set_font("Helvetica", "", body_size)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, line_h, safe_text(
        "Kratos SRE is the most dangerous competitor - publicly traded, established UAS "
        "production lines, and a DoD delivery track record that Firestorm cannot yet "
        "match. Auterion's $87.7M war chest and strong autonomy software platform make "
        "them the best-capitalized private entrant. Ukrainian Defense Drones Tech Corp "
        "brings combat-tested, battlefield-proven systems with real-world performance "
        "data no domestic vendor can replicate. Beyond the headliners, several lean "
        "competitors may undercut on unit cost as the program deliberately drives "
        "prices down across phases - the Gauntlet rewards affordability and scale, "
        "not just capability."
    ))
    pdf.ln(1.5)

    # 4. The Data (table)
    section("The Data")
    pdf.ln(0.5)

    tbl_font = 7.5
    row_h = 4.0
    col_w_label = 48
    col_w_value = pdf.w - pdf.l_margin - pdf.r_margin - col_w_label

    table_data = [
        ("Signal Score", "7.60 (Tier 1)"),
        ("Private Capital", "$45.2M (6 rounds)"),
        ("Gov Contracts", "$100M IDIQ + $1.4M SBIR"),
        ("Policy Tailwind", "0.737"),
        ("Lifecycle Stage", "Production"),
        ("Gauntlet Field Rank (Capital)", "#2 of 25"),
    ]

    # Header row
    pdf.set_font("Helvetica", "B", tbl_font)
    pdf.set_fill_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(col_w_label, row_h, "  Metric", border=1, fill=True)
    pdf.cell(col_w_value, row_h, "  Value", border=1, fill=True,
             new_x="LMARGIN", new_y="NEXT")

    # Data rows
    pdf.set_font("Helvetica", "", tbl_font)
    pdf.set_text_color(40, 40, 40)
    for i, (metric, value) in enumerate(table_data):
        if i % 2 == 0:
            pdf.set_fill_color(245, 245, 250)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.cell(col_w_label, row_h, safe_text(f"  {metric}"), border="LRB", fill=True)
        pdf.cell(col_w_value, row_h, safe_text(f"  {value}"), border="RB", fill=True,
                 new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)

    # 5. Historical Pattern
    section("Historical Pattern")
    pdf.set_font("Helvetica", "", body_size)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, line_h, safe_text(
        "Across Aperture's knowledge graph of 11,000+ defense entities, companies with "
        "production contract traction raised 3.4x more capital than those without. "
        "Firestorm already has that traction. The Gauntlet isn't about proving they "
        "belong - it's about securing order share that accelerates a trajectory "
        "already underway."
    ))
    pdf.ln(1.5)

    # 6. What to Watch
    section("What to Watch")
    pdf.set_font("Helvetica", "", body_size)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, line_h, safe_text(
        "Gauntlet results expected early March. The key metric is Firestorm's share "
        "of the $150M prototype pool relative to Kratos and Auterion."
    ))

    # Data provenance line (above footer)
    pdf.set_y(-16)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.15)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 6)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 3.5, safe_text(
        "Data sourced from SBIR.gov, SEC EDGAR, USASpending.gov, and public reporting. "
        "Verified February 25, 2026."
    ), align="L")

    # Write
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return str(out)


class InvestorIntelPDF(FPDF):
    """PDF with 'Investor Intelligence' header instead of 'Analyst Note'."""

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        self.cell(0, 5, "APERTURE", align="L")
        self.cell(0, 5, "Investor Intelligence", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica", "I", 6.5)
        self.set_text_color(120, 120, 120)
        usable = self.w - self.l_margin - self.r_margin
        third = usable / 3
        self.cell(third, 5, "Aperture | Proprietary & Confidential", align="L")
        self.cell(third, 5, "contact@aperturesignals.com", align="C")
        self.cell(third, 5, f"Page {self.page_no()}", align="R")


def build_investor_leads_note(output_path):
    """Investor leads PDF for anti-jam GPS antenna raise."""
    pdf = InvestorIntelPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 12, 15)
    pdf.add_page()

    body = 7.5
    line_h = 3.3
    bullet_h = 3.2

    def section(title):
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.cell(0, 4.5, safe_text(title), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)

    def lead_heading(text):
        pdf.set_font("Helvetica", "B", body)
        pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.cell(0, 3.8, safe_text(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.3)

    def priority_line(text):
        pdf.set_font("Helvetica", "BI", body)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 3.2, safe_text(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.3)

    def bullet(text):
        pdf.set_font("Helvetica", "", body)
        pdf.set_text_color(40, 40, 40)
        x = pdf.get_x()
        pdf.cell(4, bullet_h, safe_text("\x95"))
        pdf.multi_cell(0, bullet_h, safe_text(text))
        pdf.ln(0.2)

    # Title block
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 6, safe_text("Investor List: Anti-Jam GPS Antenna ($2.5M Raise)"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "February 25, 2026  |  Prepared for Don Novotny",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # Source and caveat
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 3, "Source: SEC EDGAR Form D filings", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(0.5)
    pdf.set_font("Helvetica", "I", 6.5)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 2.8, safe_text(
        "Note: These individuals appear as directors on SEC Form D filings for "
        "relevant companies. Some may be investors, others may be board advisors "
        "or operators. Recommend verifying investment role before outreach."
    ))
    pdf.ln(1.5)

    # Thin divider
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2.5)

    # --- TIER 1 ---
    section("Tier 1: Active GPS/PNT Thesis Investors")

    lead_heading("1. Jamie Goldstein - Pillar VC")
    priority_line("Very High - GPS/PNT thesis, recent, right size")
    bullet("Director at Tycho AI ($9.8M Series A, March 2025) - autonomous navigation / high-precision PNT")
    bullet("Only 11 months ago - active and deploying")
    bullet('Tycho SBIR: "High-precision Low-SWAP Robust Autonomy & Navigation" - direct technology overlap')
    bullet("Deal size ($9.8M Series A) indicates comfort with early-stage defense GPS companies")
    pdf.ln(1)

    lead_heading("2. Richard Clarke - Strategic Advisor, IVP")
    priority_line("Very High - Same deal as Goldstein")
    bullet("Co-director at Tycho AI ($9.8M, March 2025) alongside Goldstein")
    bullet("Likely represents a different fund or is an independent board member")
    bullet("Same thesis fit and recency as Goldstein")
    pdf.ln(1)

    lead_heading("3. Ryan Johnson - Subutai Capital Partners")
    priority_line("Very High - GPS/PNT thesis, multi-board, very recent")
    bullet("Director at Xona Space Systems ($74.6M, June 2025) - commercial GNSS alternative constellation")
    bullet("Also director at Hydrosat ($17.9M, Aug 2025) - two active boards in 2025")
    bullet('Xona SBIR: "GNSS Health and Operational Status Tracking" - directly adjacent to anti-jam GPS')
    bullet("Multi-board presence signals active, high-velocity deployer")
    pdf.ln(1)

    lead_heading("4. Karim Faris - Google Ventures")
    priority_line("High - GPS/PNT thesis, multi-board, GV partner")
    bullet("Director at OneNav ($16.1M, March 2023) - GPS/PNT positioning technology")
    bullet("Also director at Premise Data Corporation ($50M, 2015)")
    bullet("OneNav is one of the closest technology matches to anti-jam GPS in the dataset")
    pdf.ln(1)

    lead_heading("5. Manu Kumar - K9 Ventures")
    priority_line("High - Navigation thesis, recent, right size")
    bullet("Director at Compound Eye ($12.8M, March 2025) - passive 3D sensor for autonomous aerial navigation")
    bullet('SBIR: "Passive 3D Sensor for Autonomous Aerial Navigation" - GPS-denied navigation overlap')
    bullet("Very recent (March 2025) and deal size range ($12.8M) indicates willingness to lead early rounds")
    pdf.ln(1)

    lead_heading("6. Sven Strohband - Khosla Ventures")
    priority_line("High - Same deal as Kumar")
    bullet("Co-director at Compound Eye ($12.8M, March 2025) alongside Kumar")
    bullet("Same navigation thesis and recency")
    pdf.ln(2)

    # --- TIER 2 ---
    section("Tier 2: RF/EW Adjacent with Defense Pattern")

    lead_heading("7. Jonathan Hodock - CesiumAstro")
    priority_line("High - Antenna/RF thesis, exact technology match")
    bullet("Director at CesiumAstro ($8.5M Series A, Jan 2019) - open phased array antenna systems")
    bullet('CesiumAstro SBIR: "Sequential TACFI SBIR Phase II Open Phased Array Antenna"')
    bullet("Closest pure antenna/RF hardware match in the dataset")
    bullet("Older deal (2019) but CesiumAstro has since raised $100M+ total - thesis was validated")
    pdf.ln(1)

    lead_heading("8. Mark Spoto - Razor's Edge Ventures")
    priority_line("High - Most connected, defense pattern, RF/EW")
    bullet("3 boards - most connected person in the dataset")
    bullet("Director at X-Bow Launch Systems ($46.5M, 2024), HawkEye 360 ($58M, 2023), 3DEO ($14M, 2018)")
    bullet("HawkEye 360 is RF geolocation / spectrum monitoring - adjacent to GPS/EW")
    bullet("Pattern: defense hardware companies at various stages, active through 2024")
    pdf.ln(1)

    lead_heading("9. Joseph Pignato - Shield Capital")
    priority_line("Moderate-High - RF/spectrum thesis, multi-board")
    bullet("Director at Federated Wireless ($51.3M, 2019) AND HawkEye 360 ($35M, 2019)")
    bullet("Both companies operate in RF spectrum management / geolocation")
    bullet("RF spectrum expertise is directly relevant to GPS anti-jamming")
    bullet("Two defense RF boards signals committed thesis in the space")
    pdf.ln(1)

    lead_heading("10. Chris Alliegro - Meta Venture Partners")
    priority_line("Moderate-High - Antenna thesis, recent, right size")
    bullet("Director at Kapta Space Corp ($4.9M Series A, Dec 2024)")
    bullet('Kapta SBIR: "Steerable X-Band Metasurface Antenna for Spaceborne Radar"')
    bullet("Very recent (Dec 2024), deal size ($4.9M) is closest match to the $2.5M raise")
    bullet("Antenna-specific investor at the seed/Series A stage")
    pdf.ln(2)

    # --- TIER 3 ---
    section("Tier 3: Worth a Conversation")

    lead_heading("11. Kevin Fong - MVP Ventures")
    priority_line("Moderate - GPS/PNT thesis, complements Faris")
    bullet("Director at OneNav ($16.1M, March 2023) alongside Karim Faris (#4)")
    bullet("OneNav builds GPS/PNT positioning technology - direct thesis match")
    bullet("Separate fund from Faris, expanding the reach into OneNav's investor syndicate")
    bullet("If Faris doesn't bite, Fong is an alternate path into the same GPS-thesis network")
    pdf.ln(1)

    lead_heading("12. Trae Stephens - Anduril")
    priority_line("Moderate - Defense thesis, Founders Fund network")
    bullet("Director at Gecko Robotics ($121.5M, May 2025) and Varda Space Industries ($42.2M, 2021)")
    bullet("Known Founders Fund partner with deep defense tech portfolio (Anduril co-founder)")
    bullet("Not GPS-specific, but broad defense autonomy thesis and strongest network for syndicate intros")
    pdf.ln(2)

    # --- Summary ---
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.15)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)

    section("Summary")
    pdf.set_font("Helvetica", "", body)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, line_h, safe_text(
        "The strongest leads are Goldstein and Clarke at Tycho AI - a March 2025 "
        "GPS/PNT navigation deal at the right stage with direct SBIR overlap. "
        "Ryan Johnson is the most active deployer with two 2025 boards including "
        "Xona (GNSS). On the RF/antenna side, Hodock at CesiumAstro has the closest "
        "hardware-level technology match. Alliegro at Kapta Space is the best fit on "
        "deal size ($4.9M, Dec 2024) for a $2.5M raise."
    ))

    # Provenance
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 6)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 3.5, safe_text(
        "Synthesized from SEC EDGAR Form D filings across 182 defense companies. "
        "Generated February 25, 2026."
    ), align="L")

    # Write
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return str(out)


if __name__ == "__main__":
    path = build_firestorm_note("reports/firestorm_drone_dominance.pdf")
    print(f"Analyst note written to: {path}")
