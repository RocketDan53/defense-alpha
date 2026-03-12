"""
Aperture Signals — shared reportlab flowables for branded PDF output.

Higher-level building blocks that sit on top of aperture_style.  All
multi-page Aperture PDFs should use these helpers for consistent cover
pages, markdown rendering, branded tables, and section structure.

Usage:
    from reporting.aperture_flowables import (
        build_cover_page, markdown_to_flowables, branded_table,
        signal_bullet_para, label_value_para, section_divider,
    )
"""

import re

from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak,
    KeepTogether,
)

from reporting.aperture_style import (
    DARK_BG, ACCENT, ACCENT_DIM, TEXT_PRIMARY, TEXT_SECONDARY, WHITE,
    BORDER_SUBTLE, ROW_ALT, CARD_BG, GREEN, RED,
    PAGE, FONTS, paragraph_styles, data_table_style, safe_text,
)


# ── Cover Page ────────────────────────────────────────────────────────────

def build_cover_page(story, report_type, title, date_str,
                     meta_lines=None, confidential=True):
    """Append cover page flowables + PageBreak to *story*.

    Args:
        story: List of flowables to append to.
        report_type: e.g. "DEAL INTELLIGENCE BRIEF" — shown below APERTURE.
        title: Main title text (e.g. entity name or report title).
        date_str: Date line displayed on cover.
        meta_lines: Optional list of strings for metadata below the date.
        confidential: Whether to show the confidential marking.
    """
    s = paragraph_styles()

    story.append(Spacer(1, 80))
    story.append(Paragraph("APERTURE", s["cover_title"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(safe_text(report_type.upper()), s["cover_subtitle"]))
    story.append(Spacer(1, 8))

    # Accent divider line (centered)
    story.append(HRFlowable(
        width="40%", thickness=0.5, color=ACCENT,
        spaceAfter=12, spaceBefore=4,
    ))

    # Title
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle
    title_style = ParagraphStyle(
        "CoverEntityTitle", fontName="Helvetica-Bold", fontSize=18,
        textColor=ACCENT, leading=22, alignment=TA_CENTER,
    )
    story.append(Paragraph(safe_text(title), title_style))
    story.append(Spacer(1, 8))

    # Date
    date_style = ParagraphStyle(
        "CoverDate", fontName="Helvetica", fontSize=11,
        textColor=TEXT_SECONDARY, leading=14, alignment=TA_CENTER,
    )
    story.append(Paragraph(safe_text(date_str), date_style))

    if confidential:
        story.append(Paragraph(
            "Proprietary &amp; Confidential", date_style,
        ))

    # Meta lines
    if meta_lines:
        story.append(Spacer(1, 20))
        meta_style = ParagraphStyle(
            "CoverMeta", fontName="Helvetica", fontSize=9,
            textColor=TEXT_SECONDARY, leading=12, alignment=TA_CENTER,
        )
        for ml in meta_lines:
            story.append(Paragraph(safe_text(ml), meta_style))

    story.append(PageBreak())


# ── Markdown → Flowables ──────────────────────────────────────────────────

def _parse_md_table(lines):
    """Parse markdown table lines into (headers, rows)."""
    table_lines = [l for l in lines if l.strip().startswith("|")]
    if not table_lines:
        return None, None
    rows = []
    for line in table_lines:
        line = line.strip()
        if re.match(r'^\|[-:\s|]+\|$', line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        rows.append(cells)
    if len(rows) < 1:
        return None, None
    return rows[0], rows[1:]


def markdown_to_flowables(md_text, styles=None):
    """Convert simple markdown text to a list of reportlab flowables.

    Supported syntax:
        ### headers          → subsection_head
        | tables             → branded_table
        [+] / [-] bullets    → signal_bullet_para (green/red)
        - bullets            → bullet paragraph
        **bold** labels      → label_value_para or bold body
        *italic*             → body_italic
        > blockquotes        → blockquote
        plain text           → body paragraph

    Args:
        md_text: Markdown-formatted string.
        styles: Optional pre-built styles dict; created if None.

    Returns:
        List of reportlab flowables.
    """
    if not md_text or not md_text.strip():
        return []

    s = styles or paragraph_styles()
    flowables = []
    lines = md_text.strip().split("\n")

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Skip top-level markdown headers (## rendered by caller as section_title)
        if stripped.startswith("##") and not stripped.startswith("###"):
            i += 1
            continue

        # Sub-headers (### level) — keep with following content block
        if stripped.startswith("### "):
            heading_para = Paragraph(
                safe_text(stripped.lstrip("# ")), s["subsection_head"],
            )
            # Peek ahead: if next non-blank line is a table, keep them together
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip().startswith("|"):
                # Gather table lines
                table_lines = []
                while j < len(lines) and lines[j].strip().startswith("|"):
                    table_lines.append(lines[j])
                    j += 1
                headers, rows = _parse_md_table(table_lines)
                if headers and rows is not None:
                    flowables.append(KeepTogether([
                        heading_para,
                        branded_table(headers, rows),
                        Spacer(1, 4),
                    ]))
                else:
                    flowables.append(heading_para)
                i = j
            else:
                flowables.append(heading_para)
                i += 1
            continue

        # Table block: accumulate contiguous | lines
        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            headers, rows = _parse_md_table(table_lines)
            if headers and rows is not None:
                flowables.append(branded_table(headers, rows))
                flowables.append(Spacer(1, 4))
            continue

        # Empty line → small spacer
        if not stripped:
            flowables.append(Spacer(1, 3))
            i += 1
            continue

        # Signal bullets [+] / [-]
        if stripped.startswith("[+]") or stripped.startswith("- [+]"):
            text = re.sub(r'^-?\s*\[\+\]\s*', '', stripped)
            flowables.append(signal_bullet_para(text, positive=True, styles=s))
            i += 1
            continue
        if stripped.startswith("[-]") or stripped.startswith("- [-]"):
            text = re.sub(r'^-?\s*\[-\]\s*', '', stripped)
            flowables.append(signal_bullet_para(text, positive=False, styles=s))
            i += 1
            continue

        # Regular bullets
        if stripped.startswith("- "):
            bullet_text = stripped[2:]
            # Handle inline bold in bullets
            bullet_text = re.sub(
                r'\*\*(.+?)\*\*', r'<b>\1</b>',
                safe_text(bullet_text),
            )
            flowables.append(Paragraph(
                f"\u2022 {bullet_text}", s["bullet"],
            ))
            i += 1
            continue

        # Bold labels: **Label:** value
        bold_match = re.match(r'\*\*(.+?)\*\*\s*(.*)', stripped)
        if bold_match:
            label = bold_match.group(1)
            value = bold_match.group(2)
            if value:
                flowables.append(label_value_para(label, value, styles=s))
            else:
                flowables.append(Paragraph(
                    f"<b>{safe_text(label)}</b>", s["subsection_head"],
                ))
            i += 1
            continue

        # Italic note blocks
        if stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2:
            inner = stripped.strip("*")
            flowables.append(Paragraph(safe_text(inner), s["body_italic"]))
            i += 1
            continue

        # Block quotes
        if stripped.startswith(">"):
            quote_text = stripped.lstrip("> ")
            flowables.append(Paragraph(safe_text(quote_text), s["blockquote"]))
            i += 1
            continue

        # Regular body text — handle inline bold/italic
        body_text = safe_text(stripped)
        body_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', body_text)
        body_text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', body_text)
        flowables.append(Paragraph(body_text, s["body"]))
        i += 1

    return flowables


# ── Branded Table ─────────────────────────────────────────────────────────

def branded_table(headers, rows, col_widths=None):
    """Return a styled Table with dark header, alternating rows.

    Args:
        headers: List of header strings.
        rows: List of row lists (strings).
        col_widths: Optional list of column widths in points.
                    If None, widths are distributed evenly across CONTENT_WIDTH.

    Returns:
        A reportlab Table flowable.
    """
    s = paragraph_styles()

    if col_widths is None:
        n = len(headers)
        w = PAGE["content_width"] / n
        col_widths = [w] * n

    # Build header row
    header_row = [Paragraph(safe_text(h), s["table_header"]) for h in headers]
    table_data = [header_row]

    # Build data rows, stripping markdown bold
    for row in rows:
        table_data.append([
            Paragraph(safe_text(cell.replace("**", "")), s["table_cell"])
            for cell in row
        ])

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(data_table_style(len(table_data)))
    return tbl


# ── Signal Bullet ─────────────────────────────────────────────────────────

def signal_bullet_para(text, positive=True, styles=None):
    """Return a colored [+] or [-] Paragraph."""
    s = styles or paragraph_styles()
    color = GREEN if positive else RED
    marker = "[+]" if positive else "[-]"

    from reportlab.lib.styles import ParagraphStyle
    sig_style = ParagraphStyle(
        f"Signal{'Pos' if positive else 'Neg'}",
        parent=s["bullet"],
        textColor=color,
    )
    return Paragraph(f"{marker} {safe_text(text)}", sig_style)


# ── Label : Value ─────────────────────────────────────────────────────────

def label_value_para(label, value, styles=None):
    """Return a ``<b>Label:</b> value`` Paragraph."""
    s = styles or paragraph_styles()
    return Paragraph(
        f"<b>{safe_text(label)}</b> {safe_text(value)}", s["label_value"],
    )


# ── Section Divider ───────────────────────────────────────────────────────

def section_divider():
    """Return an HRFlowable styled as a subtle section divider."""
    return HRFlowable(
        width="100%", thickness=0.5, color=BORDER_SUBTLE,
        spaceBefore=6, spaceAfter=6,
    )
