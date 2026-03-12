"""
Aperture Signals — canonical brand style for all PDF output.

Exports page setup, color palette, font configuration, table styles,
paragraph styles, utility helpers, and drawing helpers for dark-background
branded PDFs.

All branded PDF scripts should import from this module for visual consistency.

Usage:
    from reporting.aperture_style import (
        DARK_BG, ACCENT, TEXT_PRIMARY, TEXT_SECONDARY, WHITE,
        BORDER_SUBTLE, STRATEGY_COLORS, PAGE, FONTS,
        paragraph_styles, data_table_style,
        draw_background, draw_header, draw_footer, draw_section_header,
        draw_divider, AperturePageTemplate,
        safe_text, fmt_currency,
    )
"""

import re
from datetime import date

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import TableStyle


# ── Utility Helpers ──────────────────────────────────────────────────────

def safe_text(text):
    """XML-escape text for use in reportlab Paragraph markup.

    ReportLab handles UTF-8 natively, so we only need to escape the three
    XML special characters that would break Paragraph's mini-HTML parser.
    """
    if not isinstance(text, str):
        text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_currency(v):
    """Format a numeric value as a compact currency string."""
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:.0f}"


# ── Page Setup ────────────────────────────────────────────────────────────

PAGE_SIZE = letter  # 612 x 792 pt
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
MARGIN_TOP = 58
MARGIN_BOTTOM = 42
MARGIN_LEFT = 40
MARGIN_RIGHT = 40
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT  # 532 pt

PAGE = {
    "size": PAGE_SIZE,
    "width": PAGE_WIDTH,
    "height": PAGE_HEIGHT,
    "margin_top": MARGIN_TOP,
    "margin_bottom": MARGIN_BOTTOM,
    "margin_left": MARGIN_LEFT,
    "margin_right": MARGIN_RIGHT,
    "content_width": CONTENT_WIDTH,
}


# ── Color Palette ─────────────────────────────────────────────────────────

DARK_BG = HexColor("#0F1923")          # page background
ACCENT = HexColor("#3B82F6")           # primary accent (blue)
ACCENT_LIGHT = HexColor("#60A5FA")     # lighter accent (header brand text)
ACCENT_DIM = HexColor("#1E3A5F")       # muted accent (subtle highlights)
TEXT_PRIMARY = HexColor("#F1F5F9")      # primary text (light on dark)
TEXT_SECONDARY = HexColor("#94A3B8")    # secondary text (muted)
TEXT_DARK = HexColor("#1E293B")         # dark text (for light backgrounds)
WHITE = colors.white
BORDER_SUBTLE = HexColor("#334155")    # dividers, table borders
ROW_ALT = HexColor("#141F2C")          # alternating table row background
CARD_BG = HexColor("#141F2C")          # stats card / highlight box background
GREEN = HexColor("#059669")            # positive / success
AMBER = HexColor("#D97706")            # warning / caution
RED = HexColor("#DC2626")              # negative / error

STRATEGY_COLORS = {
    "Next Wave": HexColor("#8B5CF6"),       # Purple
    "Policy Tailwind": HexColor("#059669"),  # Green
    "Signal Momentum": HexColor("#3B82F6"),  # Blue
}


# ── Font Configuration ────────────────────────────────────────────────────

FONTS = {
    "family": "Helvetica",
    "family_bold": "Helvetica-Bold",
    "family_italic": "Helvetica-Oblique",
    # Size presets (pt)
    "title": 18,
    "section_head": 11,
    "strategy_name": 10,
    "subtitle": 9,
    "body": 7.5,
    "caption": 7,
    "table_header": 6.5,
    "table_cell": 6.5,
    "footer": 6,
    "disclaimer": 5.5,
    "metric_label": 7,
    "metric_value": 12,
    "header_brand": 8,
    "header_meta": 7,
}


# ── Paragraph Styles (for platypus-based documents) ───────────────────────

def paragraph_styles():
    """Return a dict of ParagraphStyle objects matching the Aperture brand.

    Creates fresh instances each call (reportlab can mutate styles during render).
    """
    return {
        "title": ParagraphStyle(
            "Title", fontName="Helvetica-Bold", fontSize=18,
            textColor=WHITE, leading=22, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", fontName="Helvetica", fontSize=9,
            textColor=TEXT_SECONDARY, leading=12, spaceAfter=8,
        ),
        "section_head": ParagraphStyle(
            "SectionHead", fontName="Helvetica-Bold", fontSize=11,
            textColor=WHITE, leading=14, spaceBefore=10, spaceAfter=4,
            alignment=TA_LEFT,
        ),
        "strategy_name": ParagraphStyle(
            "StrategyName", fontName="Helvetica-Bold", fontSize=10,
            textColor=WHITE, leading=13, spaceBefore=6, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "Body", fontName="Helvetica", fontSize=7.5,
            textColor=TEXT_SECONDARY, leading=10, spaceAfter=4,
        ),
        "body_white": ParagraphStyle(
            "BodyWhite", fontName="Helvetica", fontSize=7.5,
            textColor=WHITE, leading=10,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel", fontName="Helvetica", fontSize=7,
            textColor=TEXT_SECONDARY, leading=9,
        ),
        "metric_value": ParagraphStyle(
            "MetricValue", fontName="Helvetica-Bold", fontSize=12,
            textColor=WHITE, leading=14,
        ),
        "table_header": ParagraphStyle(
            "TableHeader", fontName="Helvetica-Bold", fontSize=6.5,
            textColor=TEXT_SECONDARY, leading=8,
        ),
        "table_cell": ParagraphStyle(
            "TableCell", fontName="Helvetica", fontSize=6.5,
            textColor=TEXT_PRIMARY, leading=8,
        ),
        "table_cell_dim": ParagraphStyle(
            "TableCellDim", fontName="Helvetica", fontSize=6.5,
            textColor=TEXT_SECONDARY, leading=8,
        ),
        "subsection_head": ParagraphStyle(
            "SubsectionHead", fontName="Helvetica-Bold", fontSize=9.5,
            textColor=WHITE, leading=12, spaceBefore=6, spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            "Bullet", fontName="Helvetica", fontSize=7.5,
            textColor=TEXT_SECONDARY, leading=10, spaceAfter=2,
            leftIndent=12, bulletIndent=4, bulletFontName="Helvetica",
        ),
        "body_italic": ParagraphStyle(
            "BodyItalic", fontName="Helvetica-Oblique", fontSize=7.5,
            textColor=TEXT_SECONDARY, leading=10, spaceAfter=4,
        ),
        "blockquote": ParagraphStyle(
            "Blockquote", fontName="Helvetica-Oblique", fontSize=7.5,
            textColor=TEXT_SECONDARY, leading=10, spaceAfter=4,
            leftIndent=12, rightIndent=12,
        ),
        "label_value": ParagraphStyle(
            "LabelValue", fontName="Helvetica", fontSize=7.5,
            textColor=TEXT_PRIMARY, leading=10, spaceAfter=1,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle", fontName="Helvetica-Bold", fontSize=28,
            textColor=ACCENT, leading=32, alignment=TA_CENTER,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle", fontName="Helvetica", fontSize=16,
            textColor=TEXT_SECONDARY, leading=20, alignment=TA_CENTER,
        ),
        "footer": ParagraphStyle(
            "Footer", fontName="Helvetica", fontSize=6,
            textColor=TEXT_SECONDARY, leading=8,
        ),
        "disclaimer": ParagraphStyle(
            "Disclaimer", fontName="Helvetica-Oblique", fontSize=5.5,
            textColor=TEXT_SECONDARY, leading=7, spaceAfter=0,
        ),
    }


# ── Table Style ───────────────────────────────────────────────────────────

def data_table_style(row_count, *, header_line=True, alt_rows=True):
    """Build a TableStyle matching the Aperture brand for data tables.

    Args:
        row_count: Total rows including header (needed for alternating bg).
        header_line: Draw a bottom border under the header row.
        alt_rows: Apply alternating row backgrounds (ROW_ALT on even rows).
    """
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    if header_line:
        cmds.append(("LINEBELOW", (0, 0), (-1, 0), 0.5, BORDER_SUBTLE))
    cmds.append(("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDER_SUBTLE))

    if alt_rows:
        for i in range(1, row_count):
            if i % 2 == 0:
                cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))

    return TableStyle(cmds)


# ── Drawing Helpers (work on any reportlab canvas) ────────────────────────

def draw_background(canvas_obj):
    """Paint the full-page dark background and top accent bar (3 pt blue)."""
    w, h = PAGE_SIZE
    canvas_obj.setFillColor(DARK_BG)
    canvas_obj.rect(0, 0, w, h, fill=True, stroke=False)
    canvas_obj.setFillColor(ACCENT)
    canvas_obj.rect(0, h - 3, w, 3, fill=True, stroke=False)


def draw_header(canvas_obj, report_type, date_str=None, confidential_text="Proprietary & Confidential"):
    """Draw the page header.

    Format: APERTURE (left) | [REPORT TYPE] | [DATE] | [CONFIDENTIAL TEXT] (right)

    Args:
        canvas_obj: reportlab canvas.
        report_type: e.g. "NOTIONAL FUND", "Market Intelligence".
        date_str: optional; defaults to current month/year.
        confidential_text: right-side marking.
    """
    w, h = PAGE_SIZE
    if date_str is None:
        date_str = date.today().strftime("%B %Y")

    # Brand name (left)
    canvas_obj.setFont("Helvetica-Bold", FONTS["header_brand"])
    canvas_obj.setFillColor(ACCENT_LIGHT)
    canvas_obj.drawString(MARGIN_LEFT, h - 42, "APERTURE")

    # Report type + date + confidentiality (right)
    canvas_obj.setFont("Helvetica", FONTS["header_meta"])
    canvas_obj.setFillColor(TEXT_SECONDARY)
    right_text = f"{report_type}  |  {date_str}  |  {confidential_text}"
    canvas_obj.drawRightString(w - MARGIN_RIGHT, h - 42, right_text)

    # Header divider line
    canvas_obj.setStrokeColor(BORDER_SUBTLE)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(MARGIN_LEFT, h - 48, w - MARGIN_RIGHT, h - 48)


def draw_footer(canvas_obj, page_num=1):
    """Draw the page footer: generation date + page number.

    Format: Generated YYYY-MM-DD | aperturesignals.com (left) | Page N (right)
    """
    w = PAGE_WIDTH
    canvas_obj.setStrokeColor(BORDER_SUBTLE)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(MARGIN_LEFT, 32, w - MARGIN_RIGHT, 32)

    canvas_obj.setFont("Helvetica", FONTS["footer"])
    canvas_obj.setFillColor(TEXT_SECONDARY)
    canvas_obj.drawString(MARGIN_LEFT, 22, f"Generated {date.today().isoformat()}  |  aperturesignals.com")
    canvas_obj.drawRightString(w - MARGIN_RIGHT, 22, f"Page {page_num}")


def draw_section_header(canvas_obj, y, text, x=None):
    """Draw a section title (bold, white, 11 pt). Returns Y below the header."""
    if x is None:
        x = MARGIN_LEFT
    canvas_obj.setFont("Helvetica-Bold", FONTS["section_head"])
    canvas_obj.setFillColor(WHITE)
    canvas_obj.drawString(x, y, text)
    return y - (FONTS["section_head"] + 6)


def draw_divider(canvas_obj, y):
    """Draw a horizontal rule across the content area at the given Y."""
    canvas_obj.setStrokeColor(BORDER_SUBTLE)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(MARGIN_LEFT, y, PAGE_WIDTH - MARGIN_RIGHT, y)
    return y


# ── Platypus Page Template ────────────────────────────────────────────────

class AperturePageTemplate:
    """Drop-in onFirstPage / onLaterPages callback for SimpleDocTemplate.

    Usage:
        template = AperturePageTemplate("NOTIONAL FUND", date_str="2026-Q1")
        doc.build(story, onFirstPage=template, onLaterPages=template)
    """

    def __init__(self, report_type, date_str=None, confidential_text="Proprietary & Confidential"):
        self.report_type = report_type
        self.date_str = date_str
        self.confidential_text = confidential_text

    def __call__(self, canvas_obj, doc):
        canvas_obj.saveState()
        draw_background(canvas_obj)
        draw_header(canvas_obj, self.report_type, self.date_str, self.confidential_text)
        draw_footer(canvas_obj, page_num=doc.page)
        canvas_obj.restoreState()
