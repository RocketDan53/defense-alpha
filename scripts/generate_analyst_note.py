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


if __name__ == "__main__":
    path = build_firestorm_note("reports/firestorm_drone_dominance.pdf")
    print(f"Analyst note written to: {path}")
