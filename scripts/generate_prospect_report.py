#!/usr/bin/env python3
"""
Generate targeted prospect reports using semantic search + signal scoring.

Combines SBIR embedding similarity, composite signal scores, and funding/contract
data to produce ranked prospect lists for specific technology verticals.

Usage:
    python scripts/generate_prospect_report.py \
        --query "RF antenna radio tactical communications mesh networking spectrum" \
        --title "RF & Communications Emerging Company Report" \
        --output reports/rf_comms_prospects.md \
        --top 20
"""

import argparse
import struct
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from processing.database import SessionLocal
from processing.models import (
    Entity, EntityType, FundingEvent, FundingEventType,
    Contract, Signal, SignalStatus, SbirEmbedding,
)
from processing.signal_detector import (
    SIGNAL_SBIR_TO_CONTRACT, SIGNAL_RAPID_GROWTH, SIGNAL_SBIR_TO_VC,
    SIGNAL_OUTSIZED_AWARD, SIGNAL_SBIR_PHASE_2, SIGNAL_SBIR_PHASE_3,
    SIGNAL_MULTI_AGENCY, SIGNAL_HIGH_PRIORITY_TECH, SIGNAL_FIRST_DOD_CONTRACT,
    SIGNAL_SBIR_STALLED, SIGNAL_CUSTOMER_CONCENTRATION,
    SIGNAL_SBIR_GRADUATION_SPEED, SIGNAL_TIME_TO_CONTRACT, SIGNAL_FUNDING_VELOCITY,
)

EMBEDDING_DIM = 384

POSITIVE_WEIGHTS = {
    SIGNAL_SBIR_TO_CONTRACT: 3.0,
    SIGNAL_RAPID_GROWTH: 2.5,
    SIGNAL_SBIR_TO_VC: 2.0,
    SIGNAL_OUTSIZED_AWARD: 2.0,
    SIGNAL_SBIR_PHASE_2: 1.5,
    SIGNAL_SBIR_PHASE_3: 2.0,
    SIGNAL_MULTI_AGENCY: 1.5,
    SIGNAL_HIGH_PRIORITY_TECH: 1.0,
    SIGNAL_FIRST_DOD_CONTRACT: 1.0,
    SIGNAL_SBIR_GRADUATION_SPEED: 1.5,
    SIGNAL_TIME_TO_CONTRACT: 2.0,
    SIGNAL_FUNDING_VELOCITY: 1.5,
}

NEGATIVE_WEIGHTS = {
    SIGNAL_SBIR_STALLED: -2.0,
    SIGNAL_CUSTOMER_CONCENTRATION: -1.5,
}

ALL_WEIGHTS = {**POSITIVE_WEIGHTS, **NEGATIVE_WEIGHTS}

# Exclude large primes / well-known names from prospect lists
EXCLUDE_NAMES = {
    "anduril", "l3harris", "l3 harris", "rtx", "raytheon", "northrop grumman",
    "lockheed martin", "boeing", "general dynamics", "bae systems", "leidos",
    "saic", "booz allen", "palantir", "general atomics", "textron",
}

SIGNAL_DISPLAY_NAMES = {
    SIGNAL_SBIR_TO_CONTRACT: "SBIR→Contract",
    SIGNAL_RAPID_GROWTH: "Rapid Growth",
    SIGNAL_SBIR_TO_VC: "SBIR + VC Raise",
    SIGNAL_OUTSIZED_AWARD: "Outsized Award",
    SIGNAL_SBIR_PHASE_2: "SBIR Phase II",
    SIGNAL_SBIR_PHASE_3: "SBIR Phase III",
    SIGNAL_MULTI_AGENCY: "Multi-Agency",
    SIGNAL_HIGH_PRIORITY_TECH: "High-Priority Tech",
    SIGNAL_FIRST_DOD_CONTRACT: "First DoD Contract",
    SIGNAL_SBIR_GRADUATION_SPEED: "Fast SBIR Graduation",
    SIGNAL_TIME_TO_CONTRACT: "Fast Time-to-Contract",
    SIGNAL_FUNDING_VELOCITY: "Funding Velocity",
    SIGNAL_SBIR_STALLED: "SBIR Stalled",
    SIGNAL_CUSTOMER_CONCENTRATION: "Customer Concentration",
}


def deserialize_embedding(data: bytes) -> np.ndarray:
    n = len(data) // 4
    return np.array(struct.unpack(f"{n}f", data), dtype=np.float32)


def load_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def semantic_search(db, model, query: str, top_n: int = 200):
    """Return top_n entity_ids ranked by semantic similarity to query."""
    query_vec = model.encode([query])[0]
    query_vec = query_vec / np.linalg.norm(query_vec)

    rows = db.query(SbirEmbedding).all()
    if not rows:
        return {}

    embeddings = np.zeros((len(rows), EMBEDDING_DIM), dtype=np.float32)
    meta = []
    for i, row in enumerate(rows):
        embeddings[i] = deserialize_embedding(row.embedding)
        meta.append({"entity_id": row.entity_id, "award_title": row.award_title})

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    similarities = embeddings @ query_vec

    # Group by entity: take max sim, collect all titles
    entity_scores = {}
    entity_titles = defaultdict(list)
    for i, m in enumerate(meta):
        eid = m["entity_id"]
        sim = float(similarities[i])
        entity_titles[eid].append((sim, m["award_title"]))
        if eid not in entity_scores or sim > entity_scores[eid]:
            entity_scores[eid] = sim

    ranked = sorted(entity_scores.items(), key=lambda x: -x[1])[:top_n]
    return {eid: score for eid, score in ranked}, entity_titles


def compute_composite(db, entity_id):
    """Compute composite score and signal list for one entity."""
    signals = db.query(Signal).filter(
        Signal.entity_id == entity_id,
        Signal.status == SignalStatus.ACTIVE,
    ).all()

    positive_score = 0.0
    negative_score = 0.0
    positive_signals = []
    negative_signals = []

    for sig in signals:
        weight = ALL_WEIGHTS.get(sig.signal_type, 0.0)
        confidence = float(sig.confidence_score or 0)
        weighted = weight * confidence
        display = SIGNAL_DISPLAY_NAMES.get(sig.signal_type, sig.signal_type)

        entry = {"name": display, "type": sig.signal_type, "score": round(weighted, 2),
                 "confidence": confidence, "evidence": sig.evidence}

        if weight > 0:
            positive_score += weighted
            positive_signals.append(entry)
        elif weight < 0:
            negative_score += weighted
            negative_signals.append(entry)

    positive_signals.sort(key=lambda x: -x["score"])
    return {
        "composite": round(positive_score + negative_score, 2),
        "positive": round(positive_score, 2),
        "negative": round(negative_score, 2),
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
    }


def get_entity_activity(db, entity_id):
    """Get latest activity dates and financial summary."""
    # Latest SBIR
    latest_sbir = db.query(func.max(FundingEvent.event_date)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type.in_([
            FundingEventType.SBIR_PHASE_1, FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]),
    ).scalar()

    total_sbir = db.query(func.sum(FundingEvent.amount)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type.in_([
            FundingEventType.SBIR_PHASE_1, FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]),
    ).scalar() or Decimal(0)

    sbir_count = db.query(func.count(FundingEvent.id)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type.in_([
            FundingEventType.SBIR_PHASE_1, FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]),
    ).scalar() or 0

    # Latest contract
    latest_contract = db.query(func.max(Contract.award_date)).filter(
        Contract.entity_id == entity_id,
    ).scalar()

    total_contract = db.query(func.sum(Contract.contract_value)).filter(
        Contract.entity_id == entity_id,
    ).scalar() or Decimal(0)

    contract_count = db.query(func.count(Contract.id)).filter(
        Contract.entity_id == entity_id,
    ).scalar() or 0

    # Latest Reg D
    latest_regd = db.query(func.max(FundingEvent.event_date)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type == FundingEventType.REG_D_FILING,
    ).scalar()

    total_regd = db.query(func.sum(FundingEvent.amount)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type == FundingEventType.REG_D_FILING,
    ).scalar() or Decimal(0)

    # Most recent activity
    dates = [d for d in [latest_sbir, latest_contract, latest_regd] if d]
    latest_activity = max(dates) if dates else None

    # Estimate stage
    total_value = float(total_sbir) + float(total_contract) + float(total_regd)
    if total_value > 100_000_000:
        stage = "Growth / Scale-up"
    elif total_value > 20_000_000:
        stage = "Series B+"
    elif total_value > 5_000_000:
        stage = "Series A"
    elif total_value > 1_000_000:
        stage = "Seed / Early"
    else:
        stage = "Pre-seed / SBIR"

    return {
        "latest_sbir": latest_sbir,
        "latest_contract": latest_contract,
        "latest_regd": latest_regd,
        "latest_activity": latest_activity,
        "total_sbir": float(total_sbir),
        "total_contract": float(total_contract),
        "total_regd": float(total_regd),
        "total_value": total_value,
        "sbir_count": sbir_count,
        "contract_count": contract_count,
        "stage": stage,
    }


def is_excluded(name: str) -> bool:
    lower = name.lower()
    return any(exc in lower for exc in EXCLUDE_NAMES)


def build_prospects(db, model, queries: list[str], min_composite: float = 0.0,
                    min_similarity: float = 0.35, top_n: int = 20):
    """Build ranked prospect list from multiple semantic queries."""
    # Run all queries and merge scores
    merged_sim = {}
    all_titles = defaultdict(list)

    for q in queries:
        print(f"  Searching: \"{q}\"")
        scores, titles = semantic_search(db, model, q, top_n=300)
        for eid, sim in scores.items():
            if eid not in merged_sim or sim > merged_sim[eid]:
                merged_sim[eid] = sim
        for eid, tlist in titles.items():
            all_titles[eid].extend(tlist)

    print(f"  Semantic matches: {len(merged_sim)} entities")

    # Filter and enrich
    prospects = []
    for eid, sim_score in merged_sim.items():
        # Enforce minimum relevance to stay on-topic
        if sim_score < min_similarity:
            continue

        entity = db.query(Entity).filter(Entity.id == eid).first()
        if not entity or entity.merged_into_id:
            continue
        if entity.entity_type != EntityType.STARTUP:
            continue
        if is_excluded(entity.canonical_name):
            continue

        scoring = compute_composite(db, eid)
        if scoring["composite"] <= min_composite:
            continue
        if not scoring["positive_signals"]:
            continue

        activity = get_entity_activity(db, eid)

        # Dedupe and sort titles by sim
        seen = set()
        unique_titles = []
        for sim, title in sorted(all_titles.get(eid, []), key=lambda x: -x[0]):
            if title not in seen:
                seen.add(title)
                unique_titles.append((sim, title))

        # Combined ranking: relevance-weighted
        # High relevance companies with moderate signals beat
        # low relevance companies with high signals
        max_composite = 6.0
        norm_composite = min(scoring["composite"] / max_composite, 1.0)
        norm_sim = sim_score  # already 0-1
        rank_score = 0.55 * norm_sim + 0.45 * norm_composite

        prospects.append({
            "entity_id": eid,
            "name": entity.canonical_name,
            "location": entity.headquarters_location or "",
            "sim_score": sim_score,
            "composite": scoring["composite"],
            "positive": scoring["positive"],
            "negative": scoring["negative"],
            "positive_signals": scoring["positive_signals"],
            "negative_signals": scoring["negative_signals"],
            "activity": activity,
            "titles": unique_titles,
            "rank_score": round(rank_score, 4),
        })

    prospects.sort(key=lambda x: -x["rank_score"])
    print(f"  Qualified prospects (sim >= {min_similarity}): {len(prospects)}")
    return prospects[:top_n]


def format_currency(val: float) -> str:
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:.0f}"


def generate_markdown(prospects: list, title: str, queries: list[str]) -> str:
    """Generate markdown report from prospect list."""
    today = date.today().strftime("%B %d, %Y")

    lines = []
    lines.append(f"# Defense Alpha: {title}")
    lines.append(f"")
    lines.append(f"**Generated:** {today}")
    lines.append(f"**Prospects:** {len(prospects)} companies")
    lines.append(f"**Methodology:** Semantic similarity search over {len(queries)} technology queries, "
                 f"filtered for startups with positive intelligence signals and net-positive composite scores.")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # Summary table
    lines.append(f"## Ranked Prospect List")
    lines.append(f"")
    lines.append(f"| # | Company | Stage | Composite | Relevance | Key Signal | Latest Activity |")
    lines.append(f"|---|---------|-------|-----------|-----------|------------|-----------------|")

    for i, p in enumerate(prospects, 1):
        top_signal = p["positive_signals"][0]["name"] if p["positive_signals"] else "-"
        latest = str(p["activity"]["latest_activity"]) if p["activity"]["latest_activity"] else "N/A"
        lines.append(
            f"| {i} | **{p['name']}** | {p['activity']['stage']} | "
            f"{p['composite']:.2f} | {p['sim_score']:.3f} | {top_signal} | {latest} |"
        )

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # Detailed profiles
    lines.append(f"## Detailed Prospect Profiles")
    lines.append(f"")

    for i, p in enumerate(prospects, 1):
        act = p["activity"]
        lines.append(f"### {i}. {p['name']}")
        lines.append(f"")

        if p["location"]:
            lines.append(f"**Location:** {p['location']}")

        lines.append(f"**Estimated Stage:** {act['stage']}  ")
        lines.append(f"**Composite Score:** {p['composite']:.2f} "
                     f"(+{p['positive']:.1f} / {p['negative']:.1f})  ")
        lines.append(f"**Technology Relevance:** {p['sim_score']:.3f}")
        lines.append(f"")

        # Technology summary
        lines.append(f"**Technology Focus:**")
        for sim, title in p["titles"][:3]:
            lines.append(f"- {title}")
        lines.append(f"")

        # Signals
        lines.append(f"**Intelligence Signals:**")
        for sig in p["positive_signals"]:
            lines.append(f"- :white_check_mark: {sig['name']} (score: {sig['score']:.2f})")
        for sig in p["negative_signals"]:
            lines.append(f"- :warning: {sig['name']} (score: {sig['score']:.2f})")
        lines.append(f"")

        # Financial summary
        lines.append(f"**Financial Summary:**")
        parts = []
        if act["sbir_count"]:
            parts.append(f"{act['sbir_count']} SBIR awards ({format_currency(act['total_sbir'])})")
        if act["contract_count"]:
            parts.append(f"{act['contract_count']} contracts ({format_currency(act['total_contract'])})")
        if act["total_regd"] > 0:
            parts.append(f"Private capital: {format_currency(act['total_regd'])}")
        if parts:
            for part in parts:
                lines.append(f"- {part}")
        else:
            lines.append(f"- No financial data available")
        lines.append(f"")

        # Activity timeline
        lines.append(f"**Recent Activity:**")
        if act["latest_sbir"]:
            lines.append(f"- Latest SBIR: {act['latest_sbir']}")
        if act["latest_contract"]:
            lines.append(f"- Latest contract: {act['latest_contract']}")
        if act["latest_regd"]:
            lines.append(f"- Latest Reg D filing: {act['latest_regd']}")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    # Methodology
    lines.append(f"## Methodology")
    lines.append(f"")
    lines.append(f"This report was generated by the Defense Alpha Intelligence Engine using:")
    lines.append(f"")
    lines.append(f"1. **Semantic Search:** SBIR award titles embedded with `all-MiniLM-L6-v2` "
                 f"sentence-transformer (384-dim vectors). Cosine similarity against technology queries.")
    lines.append(f"2. **Signal Scoring:** Composite score from {len(ALL_WEIGHTS)} signal types "
                 f"including SBIR progression, contract wins, VC fundraising, multi-agency interest, "
                 f"and risk indicators (customer concentration, SBIR stalling).")
    lines.append(f"3. **Ranking:** 40% technology relevance + 60% composite signal score.")
    lines.append(f"4. **Filtering:** Startups only, net-positive composite score, at least one positive signal, "
                 f"excluding major defense primes.")
    lines.append(f"")
    lines.append(f"**Search Queries:**")
    for q in queries:
        lines.append(f'- "{q}"')
    lines.append(f"")
    lines.append(f"**Data Sources:** USASpending (DoD contracts), SBIR.gov (SBIR/STTR awards), "
                 f"SEC EDGAR (Reg D filings)")
    lines.append(f"")
    lines.append(f"*Defense Alpha Intelligence Engine v1.0 | {today}*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate prospect report")
    parser.add_argument("--query", type=str, nargs="+", required=True,
                        help="One or more semantic search queries")
    parser.add_argument("--title", type=str, default="Emerging Company Report",
                        help="Report title")
    parser.add_argument("--output", type=str, default="reports/prospect_report.md",
                        help="Output file path")
    parser.add_argument("--top", type=int, default=20, help="Number of prospects")
    parser.add_argument("--min-composite", type=float, default=0.0,
                        help="Minimum composite score")
    args = parser.parse_args()

    db = SessionLocal()

    print(f"Loading embedding model...")
    model = load_model()

    print(f"Building prospect list...")
    prospects = build_prospects(
        db, model,
        queries=args.query,
        min_composite=args.min_composite,
        top_n=args.top,
    )

    if not prospects:
        print("No qualifying prospects found.")
        db.close()
        return

    print(f"\nGenerating report: {args.output}")
    md = generate_markdown(prospects, args.title, args.query)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md)

    print(f"Report saved: {output_path} ({len(md):,} bytes)")

    # Print summary to console
    print(f"\n{'='*80}")
    print(f"  TOP {len(prospects)} PROSPECTS")
    print(f"{'='*80}")
    print(f"\n{'#':>2} {'Company':<40} {'Score':>6} {'Sim':>5} {'Stage':<18} {'Top Signal'}")
    print("-" * 100)
    for i, p in enumerate(prospects, 1):
        top_sig = p["positive_signals"][0]["name"] if p["positive_signals"] else "-"
        name = p["name"][:38]
        print(f"{i:>2} {name:<40} {p['composite']:>6.2f} {p['sim_score']:>5.3f} "
              f"{p['activity']['stage']:<18} {top_sig}")

    db.close()


if __name__ == "__main__":
    main()
