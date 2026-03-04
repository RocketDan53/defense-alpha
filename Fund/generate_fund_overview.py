#!/usr/bin/env python3
"""Generate a branded one-sheeter PDF summarizing the Aperture Signals Fund.

Produces a client-facing document showing fund strategies, portfolio companies,
entry-state differentials, and benchmark methodology.

Usage:
    python Fund/generate_fund_overview.py
    python Fund/generate_fund_overview.py --vintage 2026-Q1
    python Fund/generate_fund_overview.py --output reports/fund_overview.pdf
"""

import argparse
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    KeepTogether, HRFlowable, PageBreak,
)
from reportlab.pdfgen import canvas

from sqlalchemy import func
from processing.database import SessionLocal
from processing.models import (
    Entity, FundStrategy, FundCohort, FundPosition, FundMilestone,
    FundingEvent, FundingEventType, Contract, Signal, SignalStatus,
    StrategyStatus, CohortType, PositionStatus, MilestoneType,
)


# ── Aperture Brand Palette ──────────────────────────────────────────────

DARK_BG = HexColor("#0F1923")
ACCENT = HexColor("#3B82F6")
ACCENT_LIGHT = HexColor("#60A5FA")
ACCENT_DIM = HexColor("#1E3A5F")
TEXT_PRIMARY = HexColor("#F1F5F9")
TEXT_SECONDARY = HexColor("#94A3B8")
TEXT_DARK = HexColor("#1E293B")
WHITE = colors.white
BORDER_SUBTLE = HexColor("#334155")
GREEN = HexColor("#059669")
AMBER = HexColor("#D97706")
RED = HexColor("#DC2626")

STRATEGY_COLORS = {
    "Next Wave": HexColor("#8B5CF6"),       # Purple
    "Policy Tailwind": HexColor("#059669"),  # Green
    "Signal Momentum": HexColor("#3B82F6"),  # Blue
}


# ── Styles ──────────────────────────────────────────────────────────────

def _styles():
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
        "footer": ParagraphStyle(
            "Footer", fontName="Helvetica", fontSize=6,
            textColor=TEXT_SECONDARY, leading=8,
        ),
        "disclaimer": ParagraphStyle(
            "Disclaimer", fontName="Helvetica-Oblique", fontSize=5.5,
            textColor=TEXT_SECONDARY, leading=7, spaceAfter=0,
        ),
    }


# ── Page Template ───────────────────────────────────────────────────────

class AperturePageTemplate:
    """Dark-background page with header and footer."""

    def __init__(self, vintage: str):
        self.vintage = vintage

    def __call__(self, canvas_obj, doc):
        canvas_obj.saveState()
        w, h = letter

        # Full dark background
        canvas_obj.setFillColor(DARK_BG)
        canvas_obj.rect(0, 0, w, h, fill=True, stroke=False)

        # Top accent bar
        canvas_obj.setFillColor(ACCENT)
        canvas_obj.rect(0, h - 3, w, 3, fill=True, stroke=False)

        # Header line
        canvas_obj.setStrokeColor(BORDER_SUBTLE)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(40, h - 48, w - 40, h - 48)

        # Header text
        canvas_obj.setFont("Helvetica-Bold", 8)
        canvas_obj.setFillColor(ACCENT_LIGHT)
        canvas_obj.drawString(40, h - 42, "APERTURE SIGNALS")

        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.setFillColor(TEXT_SECONDARY)
        canvas_obj.drawRightString(w - 40, h - 42, f"NOTIONAL FUND  |  {self.vintage}  |  PROPRIETARY & CONFIDENTIAL")

        # Footer
        canvas_obj.setStrokeColor(BORDER_SUBTLE)
        canvas_obj.line(40, 32, w - 40, 32)
        canvas_obj.setFont("Helvetica", 6)
        canvas_obj.setFillColor(TEXT_SECONDARY)
        canvas_obj.drawString(40, 22, f"Generated {date.today().isoformat()}  |  aperturesignals.com")
        canvas_obj.drawRightString(w - 40, 22, f"Page {doc.page}")

        canvas_obj.restoreState()


# ── Data Queries ────────────────────────────────────────────────────────

def gather_fund_data(db, vintage: str) -> dict:
    """Pull all fund data for a given vintage."""
    strategies = db.query(FundStrategy).filter(
        FundStrategy.status.in_([StrategyStatus.ACTIVE, StrategyStatus.PAUSED]),
    ).order_by(FundStrategy.created_at).all()

    fund_data = {
        "vintage": vintage,
        "strategies": [],
        "total_positions": 0,
        "unique_companies": set(),
    }

    for strategy in strategies:
        signal_cohort = db.query(FundCohort).filter(
            FundCohort.strategy_id == strategy.id,
            FundCohort.vintage_label == vintage,
            FundCohort.cohort_type == CohortType.SIGNAL,
        ).first()

        if not signal_cohort:
            continue

        benchmark_cohort = db.query(FundCohort).filter(
            FundCohort.id == signal_cohort.paired_cohort_id,
        ).first() if signal_cohort.paired_cohort_id else None

        # Get positions
        signal_positions = db.query(FundPosition).filter(
            FundPosition.cohort_id == signal_cohort.id,
        ).order_by(FundPosition.selection_rank).all()

        benchmark_positions = db.query(FundPosition).filter(
            FundPosition.cohort_id == benchmark_cohort.id,
        ).all() if benchmark_cohort else []

        # Build portco details
        portcos = []
        for pos in signal_positions:
            entity = db.query(Entity).filter(Entity.id == pos.entity_id).first()
            if not entity:
                continue

            fund_data["unique_companies"].add(entity.id)

            # Current signals
            active_signals = db.query(Signal).filter(
                Signal.entity_id == entity.id,
                Signal.status == SignalStatus.ACTIVE,
            ).all()
            signal_types = [s.signal_type for s in active_signals]

            # Top policy areas
            top_policy = []
            if entity.policy_alignment and isinstance(entity.policy_alignment, dict):
                scores = entity.policy_alignment.get("scores", {})
                sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                top_policy = [(k, v) for k, v in sorted_scores[:2] if v > 0.2]

            # Milestones since entry
            milestones = db.query(FundMilestone).filter(
                FundMilestone.position_id == pos.id,
            ).all()

            portcos.append({
                "rank": pos.selection_rank,
                "name": entity.canonical_name,
                "core_business": str(entity.core_business).replace("CoreBusiness.", "").replace("_", " ").title() if entity.core_business else "—",
                "lifecycle": pos.entry_lifecycle_stage or "—",
                "adj_score": float(pos.entry_freshness_adjusted_score or 0),
                "raw_score": float(pos.entry_composite_score or 0),
                "policy_tailwind": float(pos.entry_policy_tailwind or 0),
                "sbir_count": int(pos.entry_sbir_count or 0),
                "contract_count": int(pos.entry_contract_count or 0),
                "contract_value": float(pos.entry_contract_value or 0),
                "regd_count": int(pos.entry_regd_count or 0),
                "regd_value": float(pos.entry_regd_value or 0),
                "signal_count": len(signal_types),
                "top_signals": signal_types[:3],
                "top_policy": top_policy,
                "milestone_count": len(milestones),
            })

        # Compute entry-state differentials
        def _avg(positions, attr):
            vals = [float(getattr(p, attr, 0) or 0) for p in positions]
            return sum(vals) / len(vals) if vals else 0

        sig_adj = _avg(signal_positions, "entry_freshness_adjusted_score")
        bench_adj = _avg(benchmark_positions, "entry_freshness_adjusted_score")
        sig_raw = _avg(signal_positions, "entry_composite_score")
        bench_raw = _avg(benchmark_positions, "entry_composite_score")
        sig_policy = _avg(signal_positions, "entry_policy_tailwind")
        bench_policy = _avg(benchmark_positions, "entry_policy_tailwind")
        sig_sbir = _avg(signal_positions, "entry_sbir_count")
        bench_sbir = _avg(benchmark_positions, "entry_sbir_count")

        # Bootstrap info
        meta = signal_cohort.selection_metadata or {}
        bootstrap = meta.get("bootstrap_baselines", {})
        match_vars = meta.get("match_variables", [])
        benchmark_method = meta.get("benchmark_method", "random")

        strat_data = {
            "name": strategy.name,
            "description": strategy.description,
            "deployed_at": signal_cohort.deployed_at,
            "signal_count": len(signal_positions),
            "benchmark_count": len(benchmark_positions),
            "portcos": portcos,
            "differentials": {
                "adj_score": (sig_adj, bench_adj),
                "raw_score": (sig_raw, bench_raw),
                "policy_tailwind": (sig_policy, bench_policy),
                "sbir_count": (sig_sbir, bench_sbir),
            },
            "benchmark_method": benchmark_method,
            "match_variables": match_vars,
            "bootstrap": bootstrap,
        }

        fund_data["strategies"].append(strat_data)
        fund_data["total_positions"] += len(signal_positions)

    fund_data["unique_count"] = len(fund_data["unique_companies"])
    return fund_data


# ── PDF Builder ─────────────────────────────────────────────────────────

def build_pdf(fund_data: dict, output_path: str):
    """Build the branded one-sheeter PDF."""
    s = _styles()
    vintage = fund_data["vintage"]

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=58, bottomMargin=42,
        leftMargin=40, rightMargin=40,
    )

    story = []
    page_w = letter[0] - 80  # usable width

    # ── Title Block ──
    story.append(Spacer(1, 4))
    story.append(Paragraph("Aperture Signals Notional Fund", s["title"]))
    story.append(Paragraph(
        f"{vintage} Vintage  |  {fund_data['total_positions']} signal positions across "
        f"{len(fund_data['strategies'])} strategies  |  "
        f"{fund_data['unique_count']} unique companies",
        s["subtitle"],
    ))

    # ── Top-Level Metrics Row ──
    strat_count = len(fund_data["strategies"])
    metrics_data = [
        [
            Paragraph("STRATEGIES", s["metric_label"]),
            Paragraph("SIGNAL POSITIONS", s["metric_label"]),
            Paragraph("UNIQUE COMPANIES", s["metric_label"]),
            Paragraph("BENCHMARK METHOD", s["metric_label"]),
        ],
        [
            Paragraph(str(strat_count), s["metric_value"]),
            Paragraph(str(fund_data["total_positions"]), s["metric_value"]),
            Paragraph(str(fund_data["unique_count"]), s["metric_value"]),
            Paragraph("Matched-Pair", s["metric_value"]),
        ],
    ]
    col_w = page_w / 4
    metrics_table = Table(metrics_data, colWidths=[col_w]*4, rowHeights=[12, 20])
    metrics_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEBELOW", (0, 0), (-1, 0), 0, DARK_BG),
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, BORDER_SUBTLE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDER_SUBTLE),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 6))

    # ── Fund Thesis ──
    story.append(Paragraph(
        "This notional fund tests whether Aperture's signal detection, policy alignment scoring, "
        "and composite ranking systems can identify defense startups that will achieve subsequent "
        "milestones — funding raises, contract wins, and SBIR advances — at higher rates than "
        "observably similar companies selected via matched-pair benchmarks. Each strategy isolates "
        "a different signal dimension.",
        s["body"],
    ))

    # ── Strategy Sections ──
    for strat in fund_data["strategies"]:
        color = STRATEGY_COLORS.get(strat["name"], ACCENT)
        portcos = strat["portcos"]

        # Strategy header with color bar
        header_data = [[
            Paragraph("", s["body"]),  # color bar cell
            Paragraph(f"{strat['name'].upper()}  —  {strat['signal_count']} positions", s["strategy_name"]),
        ]]
        header_table = Table(header_data, colWidths=[4, page_w - 4])
        header_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), color),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 8),
        ]))
        story.append(header_table)

        # Thesis
        story.append(Paragraph(strat["description"][:200] + ("..." if len(strat["description"]) > 200 else ""), s["body"]))

        # Entry-state differentials (compact)
        diffs = strat["differentials"]
        diff_items = []
        for label, key in [("Adj Score", "adj_score"), ("Raw Composite", "raw_score"),
                           ("Policy Tailwind", "policy_tailwind"), ("Avg SBIRs", "sbir_count")]:
            sig_val, bench_val = diffs[key]
            delta = sig_val - bench_val
            sign = "+" if delta > 0 else ""
            fmt = ".2f" if key != "sbir_count" else ".0f"
            diff_items.append(f"{label}: {sig_val:{fmt}} vs {bench_val:{fmt}} ({sign}{delta:{fmt}})")

        story.append(Paragraph(
            f"<b>Entry Differentials</b>  |  " + "  |  ".join(diff_items),
            s["body"],
        ))

        # Portfolio table
        table_data = [
            [
                Paragraph("#", s["table_header"]),
                Paragraph("COMPANY", s["table_header"]),
                Paragraph("SECTOR", s["table_header"]),
                Paragraph("STAGE", s["table_header"]),
                Paragraph("ADJ", s["table_header"]),
                Paragraph("POLICY", s["table_header"]),
                Paragraph("SBIRs", s["table_header"]),
                Paragraph("CONTRACTS", s["table_header"]),
                Paragraph("SIGNALS", s["table_header"]),
            ]
        ]

        for p in portcos:
            contract_str = f"{p['contract_count']}"
            if p["contract_value"] > 0:
                if p["contract_value"] >= 1_000_000:
                    contract_str += f" (${p['contract_value']/1e6:.1f}M)"
                else:
                    contract_str += f" (${p['contract_value']/1e3:.0f}K)"

            table_data.append([
                Paragraph(str(p["rank"]), s["table_cell_dim"]),
                Paragraph(p["name"][:32], s["table_cell"]),
                Paragraph(p["core_business"][:18], s["table_cell_dim"]),
                Paragraph(p["lifecycle"][:12], s["table_cell_dim"]),
                Paragraph(f"{p['adj_score']:.1f}", s["table_cell"]),
                Paragraph(f"{p['policy_tailwind']:.2f}", s["table_cell"]),
                Paragraph(str(p["sbir_count"]), s["table_cell"]),
                Paragraph(contract_str, s["table_cell_dim"]),
                Paragraph(str(p["signal_count"]), s["table_cell"]),
            ])

        col_widths = [18, 130, 72, 50, 30, 38, 32, 72, 38]
        # Adjust to fit page
        total = sum(col_widths)
        scale = page_w / total
        col_widths = [w * scale for w in col_widths]

        ptable = Table(table_data, colWidths=col_widths, repeatRows=1)

        style_cmds = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, BORDER_SUBTLE),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDER_SUBTLE),
        ]

        # Alternating row backgrounds
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                style_cmds.append(("BACKGROUND", (0, i), (-1, i), HexColor("#141F2C")))

        ptable.setStyle(TableStyle(style_cmds))
        story.append(ptable)
        story.append(Spacer(1, 4))

    # ── Methodology Note ──
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_SUBTLE))
    story.append(Spacer(1, 4))
    story.append(Paragraph("METHODOLOGY", s["section_head"]))

    method = fund_data["strategies"][0] if fund_data["strategies"] else {}
    match_vars = method.get("match_variables", [])
    bootstrap = method.get("bootstrap", {})
    n_draws = bootstrap.get("n_draws", 100)

    story.append(Paragraph(
        f"<b>Benchmark selection:</b> Matched-pair nearest-neighbor. For each signal company, "
        f"the benchmark company is selected from the same eligible universe as the closest match on "
        f"observable characteristics ({', '.join(v.replace('_', ' ') for v in match_vars) if match_vars else 'SBIR count, contracts, sector'}), "
        f"excluding the test variable. This isolates the signal dimension being tested.",
        s["body"],
    ))
    story.append(Paragraph(
        f"<b>Bootstrap baselines:</b> {n_draws} random benchmark draws computed at deploy time. "
        f"Performance reports compare the matched benchmark against this distribution to confirm "
        f"the matched cohort is representative and to compute confidence intervals on hit rate differentials.",
        s["body"],
    ))
    story.append(Paragraph(
        f"<b>Milestones tracked:</b> Funding raises (Reg D / private round), new contracts, SBIR phase advances, "
        f"composite score increases, lifecycle advances, new agency relationships, gone-stale detection. "
        f"All milestones require the event to occur <i>after</i> cohort entry date.",
        s["body"],
    ))

    # ── Disclaimer ──
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "DISCLAIMER: This is a notional (paper) fund for signal validation purposes only. "
        "No actual capital is deployed. Portfolio positions represent tracked companies, not investments. "
        "Past signal performance does not guarantee future predictive accuracy. "
        "All data sourced from public records (SBIR.gov, USASpending, SEC EDGAR, SAM.gov).",
        s["disclaimer"],
    ))

    # Build
    template = AperturePageTemplate(vintage)
    doc.build(story, onFirstPage=template, onLaterPages=template)
    print(f"\n  Generated: {output_path}")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate Aperture Signals fund one-sheeter PDF"
    )
    parser.add_argument("--vintage", type=str, default="2026-Q1", help="Vintage label")
    parser.add_argument("--output", type=str, default=None, help="Output PDF path")
    args = parser.parse_args()

    output = args.output or f"reports/fund_overview_{args.vintage.replace('-','_').lower()}.pdf"

    db = SessionLocal()
    try:
        print(f"Gathering fund data for {args.vintage}...")
        fund_data = gather_fund_data(db, args.vintage)

        if not fund_data["strategies"]:
            print(f"No deployed strategies found for vintage {args.vintage}.")
            sys.exit(1)

        print(f"  {len(fund_data['strategies'])} strategies, "
              f"{fund_data['total_positions']} positions, "
              f"{fund_data['unique_count']} unique companies")

        Path(output).parent.mkdir(parents=True, exist_ok=True)
        build_pdf(fund_data, output)

    finally:
        db.close()


if __name__ == "__main__":
    main()
