#!/usr/bin/env python3
"""
Analyst note PDF generator — dark-themed, branded output.

One-page notes use Canvas directly (like generate_insights_teaser.py).
Multi-page investor leads note uses SimpleDocTemplate + platypus.

Usage:
    python scripts/generate_analyst_note.py
"""

import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)

from reporting.aperture_style import (
    DARK_BG, ACCENT, ACCENT_LIGHT, TEXT_PRIMARY, TEXT_SECONDARY, WHITE,
    BORDER_SUBTLE, CARD_BG, PAGE, FONTS,
    paragraph_styles, data_table_style, AperturePageTemplate,
    draw_background, draw_header, draw_footer, draw_divider,
    safe_text,
)
from reporting.aperture_flowables import (
    branded_table, label_value_para, section_divider,
)

ML = PAGE["margin_left"]
CW = PAGE["content_width"]


# ── Canvas Helpers ─────────────────────────────────────────────────────────

def _wrap_text(c, text, x, y, max_width, font_name, font_size, color, leading=None):
    """Draw text with word wrapping. Returns Y position after the last line."""
    if leading is None:
        leading = font_size * 1.45
    c.setFont(font_name, font_size)
    c.setFillColor(color)

    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _section_heading(c, y, text):
    """Draw a section heading and return Y below it."""
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(ACCENT_LIGHT)
    c.drawString(ML, y, text.upper())
    return y - 13


def _body_text(c, y, text, size=8, max_width=None):
    """Draw wrapped body text. Returns Y after text."""
    if max_width is None:
        max_width = CW
    return _wrap_text(c, text, ML, y, max_width,
                      "Helvetica", size, TEXT_SECONDARY, leading=size * 1.45)


# ── Build Functions ────────────────────────────────────────────────────────

def build_firestorm_note(output_path):
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = PAGE["size"]
    c = Canvas(str(out), pagesize=PAGE["size"])

    # Page chrome
    draw_background(c)
    draw_header(c, "Analyst Note", date_str="February 2026")
    draw_footer(c, page_num=1)

    y = h - 70

    # Title block
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(ML, y, "Firestorm Labs: Drone Dominance Competitive Positioning")
    y -= 14
    c.setFillColor(TEXT_SECONDARY)
    c.setFont("Helvetica", 8)
    c.drawString(ML, y, "February 24, 2026")
    y -= 8

    y = draw_divider(c, y)
    y -= 14

    # PROGRAM CONTEXT
    y = _section_heading(c, y, "Program Context")
    y = _body_text(c, y,
        "The Drone Dominance Program is a $1.1B, four-phase DoD initiative to field "
        "200,000+ low-cost one-way attack drones by 2027. Twenty-five vendors are "
        "competing in the Phase I \"Gauntlet\" at Fort Benning through early March, "
        "with $150M in prototype delivery orders at stake."
    )
    y -= 6

    # WHAT THE PROGRAM REWARDS
    y = _section_heading(c, y, "What the Program Rewards")
    y = _body_text(c, y,
        "DIU is executing. Military operators fly and evaluate - this is a field "
        "performance test, not a paper competition. The program explicitly drives "
        "unit costs down across phases while scaling production volume. The winning "
        "profile is not the most sophisticated drone - it is the most scalable, "
        "reliable, and affordable one. Companies that can demonstrate manufacturing "
        "throughput and rapid delivery have a structural advantage."
    )
    y -= 6

    # FIRESTORM'S ADVANTAGES
    y = _section_heading(c, y, "Firestorm's Advantages")
    y = _body_text(c, y,
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
    y -= 6

    # COMPETITIVE RISKS
    y = _section_heading(c, y, "Competitive Risks")
    y = _body_text(c, y,
        "Firestorm has zero production contracts to date - no demonstrated ability "
        "to deliver at scale. Kratos SRE is a publicly traded defense company with "
        "established UAS production lines and an existing DoD delivery track record. "
        "Griffon Aerospace holds a confirmed $6.1M Army contract (2020) and several "
        "other competitors bring existing DoD production track records. Ukrainian "
        "Defense Drones Tech Corp brings combat-tested, battlefield-proven systems. "
        "Capital does not fly drones at the Gauntlet - the product does."
    )
    y -= 6

    # HISTORICAL PATTERN
    y = _section_heading(c, y, "Historical Pattern")
    y = _body_text(c, y,
        "Across Aperture's knowledge graph of 11,000+ defense technology entities, "
        "companies with production contract traction raised 3.4x more capital than "
        "those without (median $14.4M vs $3.8M in comparable aerospace companies). "
        "The Gauntlet is the inflection event - a prototype delivery order would "
        "validate Firestorm's transition from R&D to production and historically "
        "correlates with accelerated private capital formation. Without it, the "
        "17-month gap since Phase II without a production contract enters the risk "
        "zone where comparable companies begin to stall."
    )
    y -= 6

    # WHAT TO WATCH
    y = _section_heading(c, y, "What to Watch")
    y = _body_text(c, y,
        "Gauntlet results are expected in early March. Key indicators: which vendors "
        "receive prototype orders, order sizes relative to the $150M pool, and "
        "delivery timeline requirements. A Firestorm selection with a meaningful "
        "order share would be the strongest validation signal to date."
    )

    c.save()
    return str(out)


def build_firestorm_note_v2(output_path):
    """V2 analyst note: updated Feb 25, 2026 with deal brief data."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = PAGE["size"]
    c = Canvas(str(out), pagesize=PAGE["size"])

    # Page chrome
    draw_background(c)
    draw_header(c, "Analyst Note", date_str="February 2026")
    draw_footer(c, page_num=1)

    y = h - 70

    # Title block
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 12.5)
    c.drawString(ML, y, "Firestorm Labs | Drone Dominance Positioning")
    y -= 14
    c.setFillColor(TEXT_SECONDARY)
    c.setFont("Helvetica", 8)
    c.drawString(ML, y, "February 25, 2026")
    y -= 8

    y = draw_divider(c, y)
    y -= 14

    body_size = 8.5
    line_h = body_size * 1.45

    # Bottom Line
    y = _section_heading(c, y, "Bottom Line")
    y = _wrap_text(c,
        "Firestorm enters the Phase I Gauntlet as one of the strongest positioned "
        "vendors in the 25-company field. A $100M Air Force IDIQ, $45.2M in private "
        "capital, and deployable manufacturing capability place them in the top tier "
        "- one of only a handful of participants with both production-scale government "
        "validation and significant private backing.",
        ML, y, CW, "Helvetica", body_size, TEXT_SECONDARY, leading=line_h,
    )
    y -= 8

    # Firestorm's Edge
    y = _section_heading(c, y, "Firestorm's Edge")
    y = _wrap_text(c,
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
        "to Phase II graduation in its cohort at four months.",
        ML, y, CW, "Helvetica", body_size, TEXT_SECONDARY, leading=line_h,
    )
    y -= 8

    # Competitive Threats
    y = _section_heading(c, y, "Competitive Threats")
    y = _wrap_text(c,
        "Kratos SRE is the most dangerous competitor - publicly traded, established UAS "
        "production lines, and a DoD delivery track record that Firestorm cannot yet "
        "match. Auterion's $87.7M war chest and strong autonomy software platform make "
        "them the best-capitalized private entrant. Ukrainian Defense Drones Tech Corp "
        "brings combat-tested, battlefield-proven systems with real-world performance "
        "data no domestic vendor can replicate. Beyond the headliners, several lean "
        "competitors may undercut on unit cost as the program deliberately drives "
        "prices down across phases - the Gauntlet rewards affordability and scale, "
        "not just capability.",
        ML, y, CW, "Helvetica", body_size, TEXT_SECONDARY, leading=line_h,
    )
    y -= 8

    # The Data (stat table in dark card)
    y = _section_heading(c, y, "The Data")
    table_data = [
        ("Signal Score", "7.60 (Tier 1)"),
        ("Private Capital", "$45.2M (6 rounds)"),
        ("Gov Contracts", "$100M IDIQ + $1.4M SBIR"),
        ("Policy Tailwind", "0.737"),
        ("Lifecycle Stage", "Production"),
        ("Gauntlet Field Rank (Capital)", "#2 of 25"),
    ]

    card_h = len(table_data) * 14 + 6
    c.setFillColor(CARD_BG)
    c.roundRect(ML - 2, y - card_h + 6, CW + 4, card_h, 4, fill=1, stroke=0)

    for metric, value in table_data:
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(TEXT_SECONDARY)
        c.drawString(ML + 4, y, metric)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(TEXT_PRIMARY)
        c.drawString(ML + 150, y, value)
        y -= 14
    y -= 4

    # Historical Pattern
    y = _section_heading(c, y, "Historical Pattern")
    y = _wrap_text(c,
        "Across Aperture's knowledge graph of 11,000+ defense entities, companies with "
        "production contract traction raised 3.4x more capital than those without. "
        "Firestorm already has that traction. The Gauntlet isn't about proving they "
        "belong - it's about securing order share that accelerates a trajectory "
        "already underway.",
        ML, y, CW, "Helvetica", body_size, TEXT_SECONDARY, leading=line_h,
    )
    y -= 8

    # What to Watch
    y = _section_heading(c, y, "What to Watch")
    y = _wrap_text(c,
        "Gauntlet results expected early March. The key metric is Firestorm's share "
        "of the $150M prototype pool relative to Kratos and Auterion.",
        ML, y, CW, "Helvetica", body_size, TEXT_SECONDARY, leading=line_h,
    )

    # Data provenance line
    prov_y = 42
    c.setStrokeColor(BORDER_SUBTLE)
    c.setLineWidth(0.25)
    c.line(ML, prov_y, PAGE["width"] - PAGE["margin_right"], prov_y)
    c.setFont("Helvetica-Oblique", 6)
    c.setFillColor(TEXT_SECONDARY)
    c.drawString(ML, prov_y - 10,
        "Data sourced from SBIR.gov, SEC EDGAR, USASpending.gov, and public reporting. "
        "Verified February 25, 2026.")

    c.save()
    return str(out)


def build_investor_leads_note(output_path):
    """Investor leads PDF for anti-jam GPS antenna raise — multi-page."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    s = paragraph_styles()

    doc = SimpleDocTemplate(
        str(out),
        pagesize=PAGE["size"],
        topMargin=PAGE["margin_top"],
        bottomMargin=PAGE["margin_bottom"],
        leftMargin=PAGE["margin_left"],
        rightMargin=PAGE["margin_right"],
    )

    story = []

    # Title block
    story.append(Paragraph(
        "Investor List: Anti-Jam GPS Antenna ($2.5M Raise)", s["section_head"],
    ))
    story.append(Paragraph(
        "February 25, 2026  |  Prepared for Don Novotny", s["body"],
    ))
    story.append(Spacer(1, 4))

    # Source and caveat
    story.append(Paragraph("Source: SEC EDGAR Form D filings", s["body"]))
    story.append(Paragraph(
        "<i>Note: These individuals appear as directors on SEC Form D filings for "
        "relevant companies. Some may be investors, others may be board advisors "
        "or operators. Recommend verifying investment role before outreach.</i>",
        s["disclaimer"],
    ))
    story.append(Spacer(1, 4))
    story.append(section_divider())

    # Lead data
    leads = [
        ("Tier 1: Active GPS/PNT Thesis Investors", [
            ("1. Jamie Goldstein - Pillar VC", "Very High - GPS/PNT thesis, recent, right size", [
                "Director at Tycho AI ($9.8M Series A, March 2025) - autonomous navigation / high-precision PNT",
                "Only 11 months ago - active and deploying",
                'Tycho SBIR: "High-precision Low-SWAP Robust Autonomy & Navigation" - direct technology overlap',
                "Deal size ($9.8M Series A) indicates comfort with early-stage defense GPS companies",
            ]),
            ("2. Richard Clarke - Strategic Advisor, IVP", "Very High - Same deal as Goldstein", [
                "Co-director at Tycho AI ($9.8M, March 2025) alongside Goldstein",
                "Likely represents a different fund or is an independent board member",
                "Same thesis fit and recency as Goldstein",
            ]),
            ("3. Ryan Johnson - Subutai Capital Partners", "Very High - GPS/PNT thesis, multi-board, very recent", [
                "Director at Xona Space Systems ($74.6M, June 2025) - commercial GNSS alternative constellation",
                "Also director at Hydrosat ($17.9M, Aug 2025) - two active boards in 2025",
                'Xona SBIR: "GNSS Health and Operational Status Tracking" - directly adjacent to anti-jam GPS',
                "Multi-board presence signals active, high-velocity deployer",
            ]),
            ("4. Karim Faris - Google Ventures", "High - GPS/PNT thesis, multi-board, GV partner", [
                "Director at OneNav ($16.1M, March 2023) - GPS/PNT positioning technology",
                "Also director at Premise Data Corporation ($50M, 2015)",
                "OneNav is one of the closest technology matches to anti-jam GPS in the dataset",
            ]),
            ("5. Manu Kumar - K9 Ventures", "High - Navigation thesis, recent, right size", [
                "Director at Compound Eye ($12.8M, March 2025) - passive 3D sensor for autonomous aerial navigation",
                'SBIR: "Passive 3D Sensor for Autonomous Aerial Navigation" - GPS-denied navigation overlap',
                "Very recent (March 2025) and deal size range ($12.8M) indicates willingness to lead early rounds",
            ]),
            ("6. Sven Strohband - Khosla Ventures", "High - Same deal as Kumar", [
                "Co-director at Compound Eye ($12.8M, March 2025) alongside Kumar",
                "Same navigation thesis and recency",
            ]),
        ]),
        ("Tier 2: RF/EW Adjacent with Defense Pattern", [
            ("7. Jonathan Hodock - CesiumAstro", "High - Antenna/RF thesis, exact technology match", [
                "Director at CesiumAstro ($8.5M Series A, Jan 2019) - open phased array antenna systems",
                'CesiumAstro SBIR: "Sequential TACFI SBIR Phase II Open Phased Array Antenna"',
                "Closest pure antenna/RF hardware match in the dataset",
                "Older deal (2019) but CesiumAstro has since raised $100M+ total - thesis was validated",
            ]),
            ("8. Mark Spoto - Razor's Edge Ventures", "High - Most connected, defense pattern, RF/EW", [
                "3 boards - most connected person in the dataset",
                "Director at X-Bow Launch Systems ($46.5M, 2024), HawkEye 360 ($58M, 2023), 3DEO ($14M, 2018)",
                "HawkEye 360 is RF geolocation / spectrum monitoring - adjacent to GPS/EW",
                "Pattern: defense hardware companies at various stages, active through 2024",
            ]),
            ("9. Joseph Pignato - Shield Capital", "Moderate-High - RF/spectrum thesis, multi-board", [
                "Director at Federated Wireless ($51.3M, 2019) AND HawkEye 360 ($35M, 2019)",
                "Both companies operate in RF spectrum management / geolocation",
                "RF spectrum expertise is directly relevant to GPS anti-jamming",
                "Two defense RF boards signals committed thesis in the space",
            ]),
            ("10. Chris Alliegro - Meta Venture Partners", "Moderate-High - Antenna thesis, recent, right size", [
                "Director at Kapta Space Corp ($4.9M Series A, Dec 2024)",
                'Kapta SBIR: "Steerable X-Band Metasurface Antenna for Spaceborne Radar"',
                "Very recent (Dec 2024), deal size ($4.9M) is closest match to the $2.5M raise",
                "Antenna-specific investor at the seed/Series A stage",
            ]),
        ]),
        ("Tier 3: Worth a Conversation", [
            ("11. Kevin Fong - MVP Ventures", "Moderate - GPS/PNT thesis, complements Faris", [
                "Director at OneNav ($16.1M, March 2023) alongside Karim Faris (#4)",
                "OneNav builds GPS/PNT positioning technology - direct thesis match",
                "Separate fund from Faris, expanding the reach into OneNav's investor syndicate",
                "If Faris doesn't bite, Fong is an alternate path into the same GPS-thesis network",
            ]),
            ("12. Trae Stephens - Anduril", "Moderate - Defense thesis, Founders Fund network", [
                "Director at Gecko Robotics ($121.5M, May 2025) and Varda Space Industries ($42.2M, 2021)",
                "Known Founders Fund partner with deep defense tech portfolio (Anduril co-founder)",
                "Not GPS-specific, but broad defense autonomy thesis and strongest network for syndicate intros",
            ]),
        ]),
    ]

    for tier_name, tier_leads in leads:
        story.append(Paragraph(safe_text(tier_name), s["subsection_head"]))

        for lead_name, priority, bullets in tier_leads:
            block = []
            block.append(Paragraph(f"<b>{safe_text(lead_name)}</b>", s["strategy_name"]))
            block.append(Paragraph(f"<i>{safe_text(priority)}</i>", s["body_italic"]))
            for b in bullets:
                block.append(Paragraph(f"\u2022 {safe_text(b)}", s["bullet"]))
            block.append(Spacer(1, 6))
            story.append(KeepTogether(block))

    # Summary
    story.append(section_divider())
    story.append(Paragraph("Summary", s["subsection_head"]))
    story.append(Paragraph(safe_text(
        "The strongest leads are Goldstein and Clarke at Tycho AI - a March 2025 "
        "GPS/PNT navigation deal at the right stage with direct SBIR overlap. "
        "Ryan Johnson is the most active deployer with two 2025 boards including "
        "Xona (GNSS). On the RF/antenna side, Hodock at CesiumAstro has the closest "
        "hardware-level technology match. Alliegro at Kapta Space is the best fit on "
        "deal size ($4.9M, Dec 2024) for a $2.5M raise."
    ), s["body"]))

    # Provenance
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Synthesized from SEC EDGAR Form D filings across 182 defense companies. "
        "Generated February 25, 2026.",
        s["disclaimer"],
    ))

    # Build
    template = AperturePageTemplate("Investor Intelligence", date_str="February 2026")
    doc.build(story, onFirstPage=template, onLaterPages=template)
    return str(out)


if __name__ == "__main__":
    path = build_firestorm_note("reports/firestorm_drone_dominance.pdf")
    print(f"Analyst note written to: {path}")
