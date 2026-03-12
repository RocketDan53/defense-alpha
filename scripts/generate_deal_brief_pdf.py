#!/usr/bin/env python3
"""
PDF renderer for Aperture Signals deal intelligence briefs.

Uses the shared Aperture dark style (reportlab) for branded output.
Called from aperture_query.py when --pdf is passed.

Usage (from aperture_query.py):
    from scripts.generate_deal_brief_pdf import generate_deal_brief_pdf
    generate_deal_brief_pdf(sections, entity, pdf_path)
"""

import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from reporting.aperture_style import (
    PAGE, ACCENT, TEXT_SECONDARY,
    paragraph_styles, safe_text, AperturePageTemplate,
)
from reporting.aperture_flowables import (
    build_cover_page, markdown_to_flowables, section_divider,
)

REPORT_DATE = date.today().strftime("%B %d, %Y")


def generate_deal_brief_pdf(
    sections: dict[str, str],
    entity: dict,
    output_path: Path,
    client_facing: bool = False,
) -> int:
    """
    Render deal brief sections to a branded PDF.

    Args:
        sections: Dict of section_name -> markdown content
        entity: Entity dict from database
        output_path: Path to write PDF
        client_facing: If True, use client-facing header

    Returns:
        Number of pages
    """
    name = entity["canonical_name"]
    brief_type = "Intelligence Brief" if client_facing else "Deal Intelligence Brief"
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

    # ── Cover Page ──
    meta_lines = []
    if entity.get("headquarters_location"):
        meta_lines.append(f"Location: {entity['headquarters_location']}")
    if entity.get("core_business"):
        meta_lines.append(f"Sector: {entity['core_business']}")
    if entity.get("entity_type"):
        meta_lines.append(f"Type: {entity['entity_type']}")

    build_cover_page(
        story,
        report_type=brief_type,
        title=name,
        date_str=REPORT_DATE,
        meta_lines=[" | ".join(meta_lines)] if meta_lines else None,
        confidential=True,
    )

    # ── Content Pages ──
    for section_name, section_md in sections.items():
        if not section_md or not section_md.strip():
            continue

        # Section heading
        story.append(Paragraph(safe_text(section_name), s["section_head"]))
        story.extend(markdown_to_flowables(section_md, styles=s))
        story.append(section_divider())

    # ── Footer Note ──
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Aperture Signals Intelligence | Proprietary &amp; Confidential | {safe_text(REPORT_DATE)}<br/>"
        "Data sourced from SBIR.gov, SEC EDGAR, USASpending.gov, SAM.gov",
        s["disclaimer"],
    ))

    # ── Build ──
    template = AperturePageTemplate(brief_type, date_str=REPORT_DATE)
    doc.build(story, onFirstPage=template, onLaterPages=template)
    return doc.page
