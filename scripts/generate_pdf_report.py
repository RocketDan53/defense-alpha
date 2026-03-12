#!/usr/bin/env python3
"""
PDF rendering module for Aperture Signals prospect reports.

Called by generate_prospect_report.py when output path ends in .pdf.
Can also be run standalone for testing.

Usage (standalone):
    python scripts/generate_pdf_report.py

Usage (from generate_prospect_report.py):
    from generate_pdf_report import build_pdf
    build_pdf(prospects, title, queries, output_path)
"""

import re
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
    build_cover_page, branded_table, signal_bullet_para,
    label_value_para, section_divider,
)

REPORT_DATE = date.today().strftime("%B %d, %Y")


def clean_title(title):
    """Strip leading junk characters (?, replacement chars) from SBIR titles."""
    title = re.sub(r'^[?\s\x00-\x1f\ufffd]+', '', title)
    return title.strip()


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

    # ── Cover Page ──
    cover_meta = [
        f"{count} Prospects  |  Proprietary & Confidential",
        "",
        "Data Sources:",
        "- 5,147 DoD contracts from USASpending.gov (2020-2025)",
        "- 1,653 SBIR awards with semantic embeddings",
        "- 1,979 SEC Form D filings",
        "- Proprietary composite scoring across 13 signal types",
    ]
    build_cover_page(
        story,
        report_type="Emerging Company Report",
        title=title,
        date_str=REPORT_DATE,
        meta_lines=cover_meta,
        confidential=False,  # already in meta_lines
    )

    # ── Executive Summary ──
    story.append(Paragraph("Executive Summary", s["section_head"]))

    n_queries = len(queries)
    query_word = "query" if n_queries == 1 else "queries"
    story.append(Paragraph(safe_text(
        f"This report identifies the {count} most promising emerging companies in the "
        "target technology sector of the U.S. defense industrial base. "
        f"Companies were surfaced through semantic search over {n_queries} technology "
        f"{query_word} against 1,653 SBIR award titles, then "
        "filtered and ranked using Aperture Signals' composite scoring system, which "
        "weighs 13 intelligence signal types including SBIR phase progression, contract wins, "
        "private capital raises, multi-agency interest, and risk indicators."
    ), s["body"]))
    story.append(Spacer(1, 6))

    # ── Scoring Methodology Box ──
    meth_items = [
        ("Composite Score:", "Weighted sum of 13 signals (SBIR advancement, contract wins, "
         "VC raises, agency breadth, risk factors). Higher = stronger momentum."),
        ("Relevance Score:", "Semantic similarity between company R&amp;D portfolio and target "
         "technology (0-1 scale)."),
        ("Final Rank:", "65% relevance + 35% normalized composite score."),
    ]
    meth_paras = [Paragraph("<b>Scoring Methodology</b>", s["subsection_head"])]
    for label, desc in meth_items:
        meth_paras.append(Paragraph(
            f"<b>{safe_text(label)}</b> {safe_text(desc)}", s["body"],
        ))
    # Wrap in a card-bg table for visual distinction
    meth_cell = [meth_paras]
    meth_table = Table([[meth_paras]], colWidths=[page_w - 8])
    meth_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(meth_table)
    story.append(Spacer(1, 8))

    # ── Top N Recommended Prospects ──
    top_count = min(5, count)
    story.append(Paragraph(
        f"Top {top_count} Recommended Prospects", s["subsection_head"],
    ))
    story.append(Spacer(1, 2))

    for i, p in enumerate(prospects[:top_count]):
        lines = []
        act = p["activity"]
        lines.append(Paragraph(
            f"<b>{i+1}. {safe_text(p['name'])}</b>", s["body_white"],
        ))
        meta = (f"{act['stage']}  |  Composite: {p['composite']:.2f}  |  "
                f"Relevance: {p['sim_score']:.3f}")
        lines.append(Paragraph(safe_text(meta), s["body"]))

        if p.get("website_url"):
            lines.append(Paragraph(safe_text(p["website_url"]), s["body"]))

        # Dynamic rationale
        top_sigs = [sg["name"] for sg in p["positive_signals"][:3]]
        titles = p.get("titles", [])
        lead_title = ""
        if titles:
            t = titles[0]
            lead_title = clean_title(t[1] if isinstance(t, tuple) else t)

        rationale_parts = []
        if lead_title:
            rationale_parts.append(lead_title)
        if top_sigs:
            rationale_parts.append("Signals: " + ", ".join(top_sigs))
        if rationale_parts:
            lines.append(Paragraph(
                f"<i>{safe_text(' | '.join(rationale_parts))}</i>", s["body"],
            ))
        lines.append(Spacer(1, 6))
        story.append(KeepTogether(lines))

    # ── Analyst's Note ──
    if analyst_note:
        story.append(Spacer(1, 4))
        story.append(Paragraph("Analyst's Note", s["subsection_head"]))
        for para in analyst_note:
            story.append(Paragraph(safe_text(para), s["body"]))
            story.append(Spacer(1, 2))

    # ── Ranked Summary Table ──
    story.append(PageBreak())
    story.append(Paragraph("Ranked Prospect List", s["section_head"]))

    headers = ["#", "Company", "Stage", "Score", "Relev.", "Key Signal", "Latest"]
    col_widths = [20, 160, 65, 50, 50, 90, 55]
    # Scale to fit
    total = sum(col_widths)
    scale = page_w / total
    col_widths = [w * scale for w in col_widths]

    table_data = [[Paragraph(h, s["table_header"]) for h in headers]]
    for i, p in enumerate(prospects):
        top_sig = p["positive_signals"][0]["name"] if p["positive_signals"] else "-"
        latest = str(p["activity"]["latest_activity"]) if p["activity"]["latest_activity"] else "N/A"
        name_str = p["name"][:36]
        row = [
            Paragraph(str(i + 1), s["table_cell_dim"]),
            Paragraph(safe_text(name_str), s["table_cell"]),
            Paragraph(safe_text(p["activity"]["stage"]), s["table_cell_dim"]),
            Paragraph(f"{p['composite']:.2f}", s["table_cell"]),
            Paragraph(f"{p['sim_score']:.3f}", s["table_cell"]),
            Paragraph(safe_text(top_sig), s["table_cell_dim"]),
            Paragraph(safe_text(latest), s["table_cell_dim"]),
        ]
        table_data.append(row)

    ranked_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    ranked_table.setStyle(data_table_style(len(table_data)))
    story.append(ranked_table)

    # ── Detailed Profiles ──
    story.append(PageBreak())
    story.append(Paragraph("Detailed Prospect Profiles", s["section_head"]))

    for i, p in enumerate(prospects):
        act = p["activity"]
        profile = []

        # Company header
        profile.append(Paragraph(
            f"<b>{i+1}. {safe_text(p['name'])}</b>", s["strategy_name"],
        ))

        # Metadata
        if p.get("location"):
            profile.append(label_value_para("Location:", p["location"], s))
        if p.get("website_url"):
            profile.append(label_value_para("Website:", p["website_url"], s))
        profile.append(label_value_para("Stage:", act["stage"], s))
        profile.append(label_value_para(
            "Composite Score:",
            f"{p['composite']:.2f}  (+{p['positive']:.1f} / {p['negative']:.1f})",
            s,
        ))
        profile.append(label_value_para(
            "Technology Relevance:", f"{p['sim_score']:.3f}", s,
        ))
        profile.append(Spacer(1, 4))

        # Technology focus
        profile.append(Paragraph("<b>Technology Focus:</b>", s["label_value"]))
        for t in p.get("titles", [])[:3]:
            title_text = clean_title(t[1] if isinstance(t, tuple) else t)
            profile.append(Paragraph(
                f"\u2022 {safe_text(title_text)}", s["bullet"],
            ))
        profile.append(Spacer(1, 2))

        # Signals
        profile.append(Paragraph("<b>Intelligence Signals:</b>", s["label_value"]))
        for sig in p["positive_signals"]:
            profile.append(signal_bullet_para(
                f"{sig['name']} ({sig['score']:+.2f})", positive=True, styles=s,
            ))
        for sig in p["negative_signals"]:
            profile.append(signal_bullet_para(
                f"{sig['name']} ({sig['score']:+.2f})", positive=False, styles=s,
            ))
        profile.append(Spacer(1, 2))

        # Financials
        profile.append(Paragraph("<b>Financial Summary:</b>", s["label_value"]))
        if act["sbir_count"]:
            profile.append(Paragraph(
                f"\u2022 {act['sbir_count']} SBIR awards ({fmt_currency(act['total_sbir'])})",
                s["bullet"],
            ))
        if act["contract_count"]:
            profile.append(Paragraph(
                f"\u2022 {act['contract_count']} contracts ({fmt_currency(act['total_contract'])})",
                s["bullet"],
            ))
        if act["total_regd"] > 0:
            profile.append(Paragraph(
                f"\u2022 Private capital: {fmt_currency(act['total_regd'])}",
                s["bullet"],
            ))
        profile.append(Spacer(1, 2))

        # Activity
        profile.append(Paragraph("<b>Recent Activity:</b>", s["label_value"]))
        if act["latest_sbir"]:
            profile.append(Paragraph(
                f"\u2022 Latest SBIR: {safe_text(str(act['latest_sbir']))}", s["bullet"],
            ))
        if act["latest_contract"]:
            profile.append(Paragraph(
                f"\u2022 Latest contract: {safe_text(str(act['latest_contract']))}", s["bullet"],
            ))
        if act["latest_regd"]:
            profile.append(Paragraph(
                f"\u2022 Latest Reg D filing: {safe_text(str(act['latest_regd']))}", s["bullet"],
            ))

        profile.append(section_divider())
        story.append(KeepTogether(profile))

    # ── Methodology ──
    story.append(PageBreak())
    story.append(Paragraph("Methodology", s["section_head"]))

    story.append(Paragraph(safe_text(
        "This report was generated by the Aperture Signals Intelligence Engine using the "
        "following pipeline:"
    ), s["body"]))
    story.append(Spacer(1, 4))

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
        story.append(label_value_para(label, desc, s))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Search Queries:</b>", s["label_value"]))
    for q in queries:
        story.append(Paragraph(f'\u2022 "{safe_text(q)}"', s["bullet"]))
    story.append(Spacer(1, 8))

    story.append(section_divider())

    story.append(Paragraph("<b>Data Sources:</b>", s["label_value"]))
    for src in [
        "5,147 DoD contracts from USASpending.gov (2020-2025)",
        "1,653 SBIR awards with semantic embeddings",
        "1,979 SEC Form D filings",
        "Proprietary composite scoring across 13 signal types",
    ]:
        story.append(Paragraph(f"\u2022 {safe_text(src)}", s["bullet"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph(safe_text(
        f"Aperture Signals Intelligence Engine v1.0  |  {REPORT_DATE}"
    ), s["body"]))

    # ── Build ──
    template = AperturePageTemplate("Emerging Company Report", date_str=REPORT_DATE)
    doc.build(story, onFirstPage=template, onLaterPages=template)
    return doc.page
