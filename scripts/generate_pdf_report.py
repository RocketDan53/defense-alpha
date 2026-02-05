#!/usr/bin/env python3
"""
PDF rendering module for Defense Alpha prospect reports.

Called by generate_prospect_report.py when output path ends in .pdf.
Can also be run standalone for testing.

Usage (standalone):
    python scripts/generate_pdf_report.py

Usage (from generate_prospect_report.py):
    from generate_pdf_report import build_pdf
    build_pdf(prospects, title, queries, output_path)
"""

import re
from datetime import date
from pathlib import Path

from fpdf import FPDF

REPORT_DATE = date.today().strftime("%B %d, %Y")
FOOTER_TEXT = f"Defense Alpha  |  Proprietary & Confidential  |  {REPORT_DATE}"

# Dark navy brand color: #1B2A4A
BRAND_R, BRAND_G, BRAND_B = 27, 42, 74


def safe_text(text):
    """Sanitize text for latin-1 compatible PDF fonts."""
    if not isinstance(text, str):
        text = str(text)
    # Replace common Unicode characters with latin-1 safe equivalents
    text = text.replace("\u2014", " - ")   # em-dash
    text = text.replace("\u2013", "-")      # en-dash
    text = text.replace("\u2018", "'")      # left single quote
    text = text.replace("\u2019", "'")      # right single quote
    text = text.replace("\u201c", '"')      # left double quote
    text = text.replace("\u201d", '"')      # right double quote
    text = text.replace("\u2026", "...")     # ellipsis
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return text.encode("latin-1", errors="replace").decode("latin-1")


def clean_title(title):
    """Strip leading junk characters (?, replacement chars) from SBIR titles."""
    title = re.sub(r'^[?\s\x00-\x1f\ufffd]+', '', title)
    return title.strip()


def fmt_currency(v):
    if v >= 1e9: return f"${v/1e9:.1f}B"
    if v >= 1e6: return f"${v/1e6:.1f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


class ReportPDF(FPDF):

    def __init__(self, report_title="Emerging Company Report", **kwargs):
        super().__init__(**kwargs)
        self._report_title = report_title

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        self.cell(0, 6, safe_text(f"DEFENSE ALPHA  |  {self._report_title}"),
                  align="L", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
        self.set_line_width(0.4)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, FOOTER_TEXT, align="C")

    # ── helpers ──

    def section_title(self, text):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        self.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def subsection_title(self, text):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        self.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 4.5, safe_text(text))
        self.ln(1)

    def label_value(self, label, value, bold_value=False):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(60, 60, 60)
        lw = self.get_string_width(label + "  ")
        self.cell(lw, 4.5, label + "  ")
        self.set_font("Helvetica", "B" if bold_value else "", 9)
        self.set_text_color(40, 40, 40)
        self.cell(0, 4.5, safe_text(str(value)), new_x="LMARGIN", new_y="NEXT")

    def bullet(self, text, indent=12):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(40, 40, 40)
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, 4.5, safe_text("- " + text))

    def signal_bullet(self, text, positive=True):
        self.set_font("Helvetica", "", 9)
        if positive:
            marker = "[+] "
            self.set_text_color(0, 120, 60)
        else:
            marker = "[-] "
            self.set_text_color(180, 60, 30)
        self.set_x(self.l_margin + 12)
        self.multi_cell(0, 4.5, safe_text(marker + text))
        self.set_text_color(40, 40, 40)

    def check_page_break(self, height=50):
        if self.get_y() + height > 270:
            self.add_page()


# ── Build PDF ───────────────────────────────────────────────────────────────

def build_pdf(prospects, title, queries, output_path, analyst_note=None):
    """
    Render prospects to a polished PDF report.

    Args:
        prospects: List of prospect dicts from generate_prospect_report.build_prospects()
        title: Report title string
        queries: List of search query strings
        output_path: Path to write PDF
        analyst_note: Optional list of paragraph strings for the Analyst's Note section

    Returns:
        Number of pages
    """
    count = len(prospects)
    pdf = ReportPDF(report_title=title, orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)

    # ── PAGE 1: Title page ──────────────────────────────────────────────────
    pdf.add_page()

    pdf.ln(30)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 14, "DEFENSE ALPHA", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(80, 80, 80)
    # Split long titles across two lines
    if len(title) > 30:
        parts = title.rsplit(" ", 1)
        for part in parts:
            pdf.cell(0, 10, safe_text(part), align="C", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 10, safe_text(title), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_line_width(0.5)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(8)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, REPORT_DATE, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"{count} Prospects  |  Proprietary & Confidential",
             align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(15)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    sources = [
        "Data Sources:",
        "5,147 DoD contracts from USASpending.gov (2020-2025)",
        "1,653 SBIR awards with semantic embeddings",
        "1,979 SEC Form D filings",
        "Proprietary composite scoring across 13 signal types",
    ]
    for i, ln in enumerate(sources):
        if i == 0:
            pdf.set_font("Helvetica", "B", 9)
        else:
            pdf.set_font("Helvetica", "", 9)
            ln = "-  " + ln
        pdf.cell(0, 5, ln, align="C", new_x="LMARGIN", new_y="NEXT")

    # ── PAGE 2: Executive Summary ───────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Executive Summary")

    n_queries = len(queries)
    query_word = "query" if n_queries == 1 else "queries"
    pdf.body_text(
        f"This report identifies the {count} most promising emerging companies in the "
        "target technology sector of the U.S. defense industrial base. "
        f"Companies were surfaced through semantic search over {n_queries} technology "
        f"{query_word} against 1,653 SBIR award titles, then "
        "filtered and ranked using Defense Alpha's composite scoring system, which "
        "weighs 13 intelligence signal types including SBIR phase progression, contract wins, "
        "private capital raises, multi-agency interest, and risk indicators."
    )
    pdf.ln(2)

    # ── Scoring Methodology Box ──
    box_y = pdf.get_y()
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_x(pdf.l_margin + 4)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 5.5, "Scoring Methodology", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(0.5)

    methodology_items = [
        ("Composite Score:", "Weighted sum of 13 signals (SBIR advancement, contract wins, "
         "VC raises, agency breadth, risk factors). Higher = stronger momentum."),
        ("Relevance Score:", "Semantic similarity between company R&D portfolio and target "
         "technology (0-1 scale)."),
        ("Final Rank:", "65% relevance + 35% normalized composite score."),
    ]
    for label, desc in methodology_items:
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(40, 40, 40)
        lw = pdf.get_string_width(label + " ")
        pdf.cell(lw, 4.5, label + " ")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(0, 4.5, desc)
        pdf.ln(0.5)

    box_end_y = pdf.get_y() + 1

    # Draw border around methodology box
    pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_line_width(0.3)
    pdf.rect(pdf.l_margin, box_y - 1, usable_w, box_end_y - box_y + 2, style="D")

    pdf.set_y(box_end_y + 4)

    # ── Top N Recommended Prospects ──
    top_count = min(5, count)
    pdf.subsection_title(f"Top {top_count} Recommended Prospects")
    pdf.ln(1)

    for i, p in enumerate(prospects[:top_count]):
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.cell(8, 5.5, f"{i+1}.")
        pdf.cell(0, 5.5, safe_text(p["name"]), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(60, 60, 60)
        act = p["activity"]
        meta = (f"    {act['stage']}  |  Composite: {p['composite']:.2f}  |  "
                f"Relevance: {p['sim_score']:.3f}")
        pdf.cell(0, 4.5, safe_text(meta), new_x="LMARGIN", new_y="NEXT")

        if p.get("website_url"):
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(8, 4, "")
            pdf.cell(0, 4, safe_text(p["website_url"]), new_x="LMARGIN", new_y="NEXT")

        # Dynamic rationale from top signals and lead title
        top_sigs = [s["name"] for s in p["positive_signals"][:3]]
        titles = p.get("titles", [])
        lead_title = ""
        if titles:
            t = titles[0]
            lead_title = clean_title(t[1] if isinstance(t, tuple) else t)

        pdf.set_font("Helvetica", "I", 8.5)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(8, 4.5, "")
        rationale_parts = []
        if lead_title:
            rationale_parts.append(lead_title)
        if top_sigs:
            rationale_parts.append("Signals: " + ", ".join(top_sigs))
        pdf.multi_cell(0, 4.5, safe_text(" | ".join(rationale_parts)))
        pdf.ln(3)

    # ── Analyst's Note ────────────────────────────────────────────────────
    if analyst_note:
        pdf.check_page_break(50)
        pdf.ln(2)
        pdf.subsection_title("Analyst's Note")
        pdf.ln(1)
        for para in analyst_note:
            pdf.body_text(para)
            pdf.ln(1)

    # ── PAGE 3+: Ranked Summary Table ───────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Ranked Prospect List")

    # Table header — widths sum to 180mm (usable width with 15mm margins)
    col_w = [8, 62, 26, 18, 18, 28, 20]
    headers = ["#", "Company", "Stage", "Score", "Relev.", "Key Signal", "Latest"]

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_text_color(255, 255, 255)
    for j, h in enumerate(headers):
        pdf.cell(col_w[j], 6, h, border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_text_color(40, 40, 40)
    for i, p in enumerate(prospects):
        pdf.set_font("Helvetica", "", 7.5)
        if i % 2 == 0:
            pdf.set_fill_color(240, 245, 250)
        else:
            pdf.set_fill_color(255, 255, 255)
        top_sig = p["positive_signals"][0]["name"] if p["positive_signals"] else "-"
        latest = str(p["activity"]["latest_activity"]) if p["activity"]["latest_activity"] else "N/A"
        # Fit company name to column width (~36 chars at 7.5pt in 62mm)
        name = p["name"][:36]

        row = [str(i+1), name, p["activity"]["stage"],
               f"{p['composite']:.2f}", f"{p['sim_score']:.3f}", top_sig, latest]
        for j, val in enumerate(row):
            align = "C" if j in (0, 3, 4, 6) else "L"
            pdf.cell(col_w[j], 5.5, safe_text(val), border=1, fill=True, align=align)
        pdf.ln()

    # ── Detailed Profiles ───────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Detailed Prospect Profiles")

    for i, p in enumerate(prospects):
        pdf.check_page_break(65)

        # Company header — full name, no truncation
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.cell(0, 7, safe_text(f"{i+1}. {p['name']}"), new_x="LMARGIN", new_y="NEXT")

        # Location, website, stage
        act = p["activity"]
        if p.get("location"):
            pdf.label_value("Location:", p["location"])
        if p.get("website_url"):
            pdf.label_value("Website:", p["website_url"])
        pdf.label_value("Stage:", act["stage"])
        pdf.label_value("Composite Score:",
                        f"{p['composite']:.2f}  (+{p['positive']:.1f} / {p['negative']:.1f})")
        pdf.label_value("Technology Relevance:", f"{p['sim_score']:.3f}")
        pdf.ln(2)

        # Technology focus — full titles, no truncation (multi_cell wraps)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 4.5, "Technology Focus:", new_x="LMARGIN", new_y="NEXT")
        titles = p.get("titles", [])
        for t in titles[:3]:
            title_text = clean_title(t[1] if isinstance(t, tuple) else t)
            pdf.bullet(title_text)
        pdf.ln(1)

        # Signals
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 4.5, "Intelligence Signals:", new_x="LMARGIN", new_y="NEXT")
        for sig in p["positive_signals"]:
            pdf.signal_bullet(f"{sig['name']} ({sig['score']:+.2f})", positive=True)
        for sig in p["negative_signals"]:
            pdf.signal_bullet(f"{sig['name']} ({sig['score']:+.2f})", positive=False)
        pdf.ln(1)

        # Financials
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 4.5, "Financial Summary:", new_x="LMARGIN", new_y="NEXT")
        if act["sbir_count"]:
            pdf.bullet(f"{act['sbir_count']} SBIR awards ({fmt_currency(act['total_sbir'])})")
        if act["contract_count"]:
            pdf.bullet(f"{act['contract_count']} contracts ({fmt_currency(act['total_contract'])})")
        if act["total_regd"] > 0:
            pdf.bullet(f"Private capital: {fmt_currency(act['total_regd'])}")
        pdf.ln(1)

        # Activity
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 4.5, "Recent Activity:", new_x="LMARGIN", new_y="NEXT")
        if act["latest_sbir"]:
            pdf.bullet(f"Latest SBIR: {act['latest_sbir']}")
        if act["latest_contract"]:
            pdf.bullet(f"Latest contract: {act['latest_contract']}")
        if act["latest_regd"]:
            pdf.bullet(f"Latest Reg D filing: {act['latest_regd']}")

        # Divider
        pdf.ln(3)
        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.2)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(4)

    # ── Final page: Methodology ─────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Methodology")

    pdf.body_text(
        "This report was generated by the Defense Alpha Intelligence Engine using the "
        "following pipeline:"
    )
    pdf.ln(1)

    steps = [
        ("Semantic Search:", "SBIR award titles embedded with all-MiniLM-L6-v2 "
         "sentence-transformer (384-dimensional vectors). Cosine similarity measured "
         "against technology-specific queries."),
        ("Signal Scoring:", "Composite score computed from 13 signal types including "
         "SBIR progression, contract wins, VC fundraising, multi-agency interest, "
         "and risk indicators (customer concentration, SBIR stalling)."),
        ("Ranking:", "65% technology relevance + 35% composite signal score."),
        ("Filtering:", "Startups only, net-positive composite score, at least one positive "
         "signal, minimum 0.40 relevance score, excluding major defense primes."),
    ]
    for label, desc in steps:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        lw = pdf.get_string_width(label + " ")
        pdf.cell(lw, 4.5, label + " ")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 4.5, desc)
        pdf.ln(2)

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 5, "Search Queries:", new_x="LMARGIN", new_y="NEXT")
    for q in queries:
        pdf.bullet(f'"{q}"')
    pdf.ln(4)

    pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_line_width(0.3)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 5, "Data Sources:", new_x="LMARGIN", new_y="NEXT")
    data_sources = [
        "5,147 DoD contracts from USASpending.gov (2020-2025)",
        "1,653 SBIR awards with semantic embeddings",
        "1,979 SEC Form D filings",
        "Proprietary composite scoring across 13 signal types",
    ]
    for s in data_sources:
        pdf.bullet(s)
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"Defense Alpha Intelligence Engine v1.0  |  {REPORT_DATE}",
             new_x="LMARGIN", new_y="NEXT")

    # ── Write ───────────────────────────────────────────────────────────────
    pdf.output(str(output_path))
    return pdf.pages_count
