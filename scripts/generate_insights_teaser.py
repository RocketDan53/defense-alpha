#!/usr/bin/env python3
"""
Generate a one-page PDF teaser of the Market Intelligence Brief.

Produces a dark-themed, branded PDF designed for email outreach —
readable in 60 seconds, designed to make the reader want the full report.

Uses the shared Aperture style module for consistent branding across
all PDF output (matches fund overview, deal briefs, etc.).

Usage:
    python scripts/generate_insights_teaser.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from reporting.aperture_style import (
    ACCENT, TEXT_PRIMARY, TEXT_SECONDARY, WHITE, CARD_BG,
    BORDER_SUBTLE, PAGE, FONTS,
    draw_background, draw_header, draw_footer, draw_divider,
)

OUTPUT_PATH = PROJECT_ROOT / "reports" / "market_insights_teaser_march_2026.pdf"

ML = PAGE["margin_left"]
CW = PAGE["content_width"]


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


def _draw_finding(c, y, number, headline, body):
    """Draw a numbered finding block (pill + headline + body). Returns Y after."""
    pill_r = 11
    pill_x = ML + pill_r
    pill_y = y - 2
    c.setFillColor(ACCENT)
    c.circle(pill_x, pill_y, pill_r, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(pill_x, pill_y - 4, str(number))

    text_x = ML + 32
    text_w = CW - 32
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(text_x, y, headline)
    y -= 18

    y = _wrap_text(c, body, text_x, y, text_w,
                   "Helvetica", 8.5, TEXT_SECONDARY, leading=13)
    return y - 6


def _draw_stat_line(c, y, label, value):
    """Draw a stat line: bold value followed by label text, with subtle separator."""
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(WHITE)
    c.drawString(ML + 12, y, value)

    value_w = pdfmetrics.stringWidth(value, "Helvetica-Bold", 10)
    c.setFont("Helvetica", 9)
    c.setFillColor(TEXT_SECONDARY)
    c.drawString(ML + 12 + value_w + 8, y, label)

    # Subtle separator line between stats
    c.setStrokeColor(BORDER_SUBTLE)
    c.setLineWidth(0.25)
    c.line(ML + 8, y - 9, ML + CW - 8, y - 9)

    return y - 20


def generate_teaser():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    w, h = PAGE["size"]
    c = Canvas(str(OUTPUT_PATH), pagesize=PAGE["size"])

    # ── Page chrome ───────────────────────────────────────────────────────
    draw_background(c)
    draw_header(c, "Market Intelligence", date_str="March 2026",
                confidential_text="Proprietary & Confidential")
    draw_footer(c, page_num=1)

    # Content starts below header line (h-48) with clearance
    y = h - 70

    # ── Title Block ───────────────────────────────────────────────────────
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(ML, y, "Defense Technology Market Snapshot")
    y -= 14

    c.setFillColor(TEXT_SECONDARY)
    c.setFont("Helvetica", 9.5)
    c.drawString(ML, y, "Quantitative signals from 9,600+ defense startups, "
                 "$61B in contracts, $67B in private capital")
    y -= 16

    y = draw_divider(c, y)
    y -= 24

    # ── 3 Standout Findings ───────────────────────────────────────────────
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(ML, y, "3 Standout Findings")
    y -= 26

    y = _draw_finding(c, y,
        1,
        "$209M deployed against a \u201343% budget cut",
        "8 companies primarily aligned to hypersonics raised $209.9M in the last "
        "18 months. The FY26 budget cuts hypersonics funding by 43%. These "
        "investors may be allocating against the government\u2019s revealed "
        "spending trajectory."
    )
    y -= 2

    y = _draw_finding(c, y,
        2,
        "250 companies positioned for private investment",
        "250 startups have earned SBIR awards from 4+ DoD branches across 3+ "
        "technology domains \u2014 broad, independent government validation \u2014 "
        "but have zero production contracts and zero private capital on record."
    )
    y -= 2

    y = _draw_finding(c, y,
        3,
        "OTA-pathway companies are a different species",
        "Companies that entered defense through Other Transaction Authority "
        "contracts score 3.2 points higher on composite signal strength, raise "
        "68% more private capital, and convert SBIRs to production contracts at "
        "4x the rate of traditional-pathway companies. OTAs are a stronger "
        "signal than standard procurement awards."
    )
    y -= 6

    y = draw_divider(c, y)
    y -= 22

    # ── By the Numbers ────────────────────────────────────────────────────
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(ML, y, "By the Numbers")
    y -= 22

    # Stats card background
    card_h = 132
    c.setFillColor(CARD_BG)
    c.roundRect(ML - 4, y - card_h + 14, CW + 8, card_h, 6, fill=1, stroke=0)

    y = _draw_stat_line(c, y, "defense startups tracked", "9,657")
    y = _draw_stat_line(c, y, "government contract value monitored", "$61.1B")
    y = _draw_stat_line(c, y, "signal types across 6 detection categories", "25")
    y = _draw_stat_line(c, y, "Phase II graduates with no private capital (next-wave pipeline)", "2,827")
    y = _draw_stat_line(c, y, "\u2014 signals precede private raises", "80%")
    y = _draw_stat_line(c, y, "median lead time from signal to capital event", "~3 years")

    y -= 12

    y = draw_divider(c, y)
    y -= 18

    # ── CTA ───────────────────────────────────────────────────────────────
    cta = (
        "This is a sample from Aperture\u2019s March 2026 Market Intelligence Brief. "
        "Full report available on request \u2014 daniel@aperturesignals.com"
    )
    y = _wrap_text(c, cta, ML, y, CW,
                   "Helvetica-Oblique", 8.5, TEXT_SECONDARY, leading=13)

    c.save()
    print(f"Teaser PDF written to {OUTPUT_PATH}")
    print(f"  File size: {OUTPUT_PATH.stat().st_size:,} bytes")


if __name__ == "__main__":
    generate_teaser()
