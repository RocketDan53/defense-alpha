#!/usr/bin/env python3
"""
PDF renderer for Aperture Signals deal intelligence briefs.

Uses the same branded template as generate_pdf_report.py (ReportPDF class).
Called from aperture_query.py when --pdf is passed.

Usage (from aperture_query.py):
    from scripts.generate_deal_brief_pdf import generate_deal_brief_pdf
    generate_deal_brief_pdf(sections, entity, pdf_path)
"""

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_pdf_report import ReportPDF, safe_text, BRAND_R, BRAND_G, BRAND_B, REPORT_DATE


def _parse_md_table(md_text: str) -> list[list[str]]:
    """Extract rows from a markdown table (skip separator lines)."""
    rows = []
    for line in md_text.strip().split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Skip separator lines (|---|---|)
        if re.match(r'^\|[-:\s|]+\|$', line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        rows.append(cells)
    return rows


def _strip_bold(text: str) -> str:
    """Remove markdown bold markers."""
    return text.replace("**", "")


def _section_text(md_text: str) -> str:
    """Extract plain text from markdown section, stripping headers and tables."""
    lines = []
    for line in md_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("#"):
            continue
        if line.startswith("|"):
            continue
        if line.startswith("---"):
            continue
        if not line or line.startswith("*"):
            stripped = line.strip("*_ ")
            if stripped:
                lines.append(stripped)
            continue
        lines.append(line)
    return "\n".join(lines)


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

    pdf = ReportPDF(report_title=brief_type, orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)
    usable_w = 180  # 210 - 15 - 15

    # ── Helper: render markdown table ──
    def render_md_table(md_text: str, max_cols: int = 8):
        rows = _parse_md_table(md_text)
        if not rows:
            return
        headers = rows[0]
        data_rows = rows[1:]

        n_cols = min(len(headers), max_cols)
        col_w = usable_w / n_cols

        # Header
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_fill_color(BRAND_R, BRAND_G, BRAND_B)
        pdf.set_text_color(255, 255, 255)
        for j in range(n_cols):
            pdf.cell(col_w, 5.5, safe_text(_strip_bold(headers[j])), border=1, fill=True, align="C")
        pdf.ln()

        # Rows
        pdf.set_text_color(40, 40, 40)
        for i, row in enumerate(data_rows):
            pdf.set_font("Helvetica", "", 7)
            if i % 2 == 0:
                pdf.set_fill_color(240, 245, 250)
            else:
                pdf.set_fill_color(255, 255, 255)
            for j in range(n_cols):
                val = _strip_bold(row[j]) if j < len(row) else ""
                align = "L" if j == 0 else "C"
                pdf.cell(col_w, 5, safe_text(val), border=1, fill=True, align=align)
            pdf.ln()

    # ── Helper: render section with markdown parsing ──
    def render_section(section_name: str, md_text: str):
        pdf.check_page_break(30)
        pdf.section_title(section_name)

        in_table = False
        table_lines = []

        for line in md_text.strip().split("\n"):
            stripped = line.strip()

            # Skip markdown headers (already rendered by section_title)
            if stripped.startswith("##"):
                continue

            # Table lines
            if stripped.startswith("|"):
                in_table = True
                table_lines.append(stripped)
                continue
            elif in_table:
                # Flush table
                render_md_table("\n".join(table_lines))
                table_lines = []
                in_table = False
                pdf.ln(2)

            # Empty line
            if not stripped:
                pdf.ln(1)
                continue

            # Sub-headers (### level)
            if stripped.startswith("### "):
                pdf.check_page_break(15)
                pdf.subsection_title(stripped.lstrip("# "))
                continue

            # Signal bullets [+] and [-]
            if stripped.startswith("[+]") or stripped.startswith("- [+]"):
                text = stripped.lstrip("- ")
                pdf.signal_bullet(text.lstrip("[+] "), positive=True)
                continue
            if stripped.startswith("[-]") or stripped.startswith("- [-]"):
                text = stripped.lstrip("- ")
                pdf.signal_bullet(text.lstrip("[-] "), positive=False)
                continue

            # Regular bullets
            if stripped.startswith("- "):
                pdf.bullet(stripped[2:])
                continue

            # Bold labels (e.g., **Composite Score:** 5.23)
            bold_match = re.match(r'\*\*(.+?)\*\*\s*(.*)', stripped)
            if bold_match:
                label = bold_match.group(1)
                value = bold_match.group(2)
                if value:
                    pdf.label_value(label, value)
                else:
                    pdf.set_font("Helvetica", "B", 9)
                    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
                    pdf.cell(0, 5, safe_text(label), new_x="LMARGIN", new_y="NEXT")
                continue

            # Italic note blocks
            if stripped.startswith("*") and stripped.endswith("*"):
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(100, 100, 100)
                pdf.multi_cell(0, 4, safe_text(stripped.strip("*")))
                pdf.set_text_color(40, 40, 40)
                pdf.ln(1)
                continue

            # Block quote (> text)
            if stripped.startswith(">"):
                pdf.set_font("Helvetica", "I", 8.5)
                pdf.set_text_color(80, 80, 80)
                pdf.set_x(pdf.l_margin + 6)
                pdf.multi_cell(usable_w - 12, 4.2, safe_text(stripped.lstrip("> ")))
                pdf.set_text_color(40, 40, 40)
                pdf.ln(1)
                continue

            # Regular body text
            pdf.body_text(stripped)

        # Flush any trailing table
        if table_lines:
            render_md_table("\n".join(table_lines))
            pdf.ln(2)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 1: Cover
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(30)

    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 14, "APERTURE", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, safe_text(brief_type.upper()), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_line_width(0.5)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(10)

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.cell(0, 10, safe_text(name), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, REPORT_DATE, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Proprietary & Confidential", align="C", new_x="LMARGIN", new_y="NEXT")

    # Entity metadata on cover
    pdf.ln(15)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    meta_items = []
    if entity.get("headquarters_location"):
        meta_items.append(f"Location: {entity['headquarters_location']}")
    if entity.get("core_business"):
        meta_items.append(f"Sector: {entity['core_business']}")
    if entity.get("entity_type"):
        meta_items.append(f"Type: {entity['entity_type']}")
    if meta_items:
        pdf.cell(0, 5, " | ".join(meta_items), align="C", new_x="LMARGIN", new_y="NEXT")

    # ══════════════════════════════════════════════════════════════════════════
    # CONTENT PAGES
    # ══════════════════════════════════════════════════════════════════════════
    pdf.add_page()

    for section_name, section_md in sections.items():
        if not section_md or not section_md.strip():
            continue
        render_section(section_name, section_md)

        # Divider between sections
        pdf.ln(2)
        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.2)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(4)

    # ══════════════════════════════════════════════════════════════════════════
    # FOOTER NOTE
    # ══════════════════════════════════════════════════════════════════════════
    pdf.ln(6)
    pdf.set_draw_color(BRAND_R, BRAND_G, BRAND_B)
    pdf.set_line_width(0.3)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        0, 4,
        safe_text(
            f"APERTURE SIGNALS INTELLIGENCE | PROPRIETARY & CONFIDENTIAL | {REPORT_DATE}\n"
            "Data sourced from SBIR.gov, SEC EDGAR, USASpending.gov, SAM.gov"
        ),
    )

    # Write
    pdf.output(str(output_path))
    return pdf.pages_count
