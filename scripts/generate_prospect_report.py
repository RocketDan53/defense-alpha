#!/usr/bin/env python3
"""
Generate targeted prospect reports using semantic search + signal scoring.

Combines SBIR embedding similarity, composite signal scores, and funding/contract
data to produce ranked prospect lists for specific technology verticals.

Output formats: .md (markdown) or .pdf (polished PDF report).

Usage:
    python scripts/generate_prospect_report.py \
        --query "RF antenna radio tactical communications mesh networking spectrum" \
        --title "RF & Communications Emerging Company Report" \
        --output reports/rf_comms_prospects.pdf \
        --count 10
"""

import argparse
import re
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
    SIGNAL_SBIR_TO_CONTRACT: "SBIR->Contract",
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


def clean_title(title: str) -> str:
    """Strip leading junk characters (?, replacement chars) from SBIR titles."""
    title = re.sub(r'^[?\s\x00-\x1f\ufffd]+', '', title)
    return title.strip()


def semantic_search(db, model, query: str, top_n: int = 200):
    """Return top_n entity_ids ranked by semantic similarity to query."""
    query_vec = model.encode([query])[0]
    query_vec = query_vec / np.linalg.norm(query_vec)

    rows = db.query(SbirEmbedding).all()
    if not rows:
        return {}, defaultdict(list)

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

    latest_contract = db.query(func.max(Contract.award_date)).filter(
        Contract.entity_id == entity_id,
    ).scalar()

    total_contract = db.query(func.sum(Contract.contract_value)).filter(
        Contract.entity_id == entity_id,
    ).scalar() or Decimal(0)

    contract_count = db.query(func.count(Contract.id)).filter(
        Contract.entity_id == entity_id,
    ).scalar() or 0

    latest_regd = db.query(func.max(FundingEvent.event_date)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type == FundingEventType.REG_D_FILING,
    ).scalar()

    total_regd = db.query(func.sum(FundingEvent.amount)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type == FundingEventType.REG_D_FILING,
    ).scalar() or Decimal(0)

    dates = [d for d in [latest_sbir, latest_contract, latest_regd] if d]
    latest_activity = max(dates) if dates else None

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


def format_currency(val: float) -> str:
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:.0f}"


def generate_analyst_note(prospects, queries, title):
    """Generate data-driven analyst's note from prospect data.

    Returns list of paragraph strings (plain text).
    """
    count = len(prospects)

    # Extract vertical name from title
    vertical = title
    for suffix in ["Emerging Company Report", "Report"]:
        vertical = vertical.replace(suffix, "").strip()
    vertical = vertical.rstrip(" -:")
    if not vertical:
        vertical = "this technology sector"

    # ── Aggregate stats ──
    total_sbir_funding = sum(p["activity"]["total_sbir"] for p in prospects)
    total_private = sum(p["activity"]["total_regd"] for p in prospects)
    total_sbir_awards = sum(p["activity"]["sbir_count"] for p in prospects)
    vc_companies = [p for p in prospects if p["activity"]["total_regd"] > 0]

    # Stage distribution
    stages = defaultdict(int)
    for p in prospects:
        stages[p["activity"]["stage"]] += 1
    dominant_stage = max(stages, key=stages.get)
    dominant_count = stages[dominant_stage]

    # Sub-segment detection from SBIR titles
    segment_keywords = {
        "mesh networking": ["mesh", "networked radio"],
        "electronic warfare": ["electronic warfare", "decoy", "jamming", "ew "],
        "radar & sensing": ["radar", "sensor fusion", "parasitic radar"],
        "SATCOM & space comms": ["satellite comm", "satcom", "cubesat", "high bandwidth comm"],
        "tactical communications": ["tactical comm", "blos", "beyond line of sight",
                                    "comms backhaul", "warfighter", "wartime"],
        "beamforming & directed RF": ["beamforming", "mimo", "mmwave",
                                      "directional wireless", "antenna"],
        "network security": ["zero trust", "secure comm", "stig"],
    }
    segment_companies = defaultdict(set)
    for p in prospects:
        for _, t in p.get("titles", []):
            lower = t.lower()
            for seg, kws in segment_keywords.items():
                if any(kw in lower for kw in kws):
                    segment_companies[seg].add(p["name"])
    top_segments = sorted(segment_companies.items(), key=lambda x: -len(x[1]))

    # Signal patterns
    signal_counts = defaultdict(int)
    for p in prospects:
        for sig in p["positive_signals"]:
            signal_counts[sig["name"]] += 1

    phase2_companies = [p for p in prospects
                        if any(s["name"] == "SBIR Phase II" for s in p["positive_signals"])]
    contract_companies = [p for p in prospects
                          if any(s["name"] == "SBIR->Contract" for s in p["positive_signals"])]
    vc_sbir_companies = [p for p in prospects
                         if p["activity"]["total_regd"] > 0
                         and any(s["name"] in ("SBIR + VC Raise", "Funding Velocity")
                                 for s in p["positive_signals"])]

    # ── Paragraph 1: Market Observation ──
    p1 = (f"Aperture Signals identified {count} emerging companies with active programs "
          f"in {vertical}, backed by {total_sbir_awards} SBIR awards totaling "
          f"{format_currency(total_sbir_funding)}")
    if vc_companies:
        p1 += (f" and {format_currency(total_private)} in disclosed private capital "
               f"across {len(vc_companies)} companies")
    p1 += ". "

    active_segs = [f"{name} ({len(cos)})" for name, cos in top_segments if len(cos) >= 2]
    if active_segs:
        p1 += f"Sub-segment activity clusters around {', '.join(active_segs[:3])}. "

    p1 += f"{dominant_count} of {count} sit at {dominant_stage} stage"
    other_stages = [(s, c) for s, c in stages.items() if s != dominant_stage and c > 0]
    if other_stages:
        others = ", ".join(f"{c} at {s}" for s, c in sorted(other_stages, key=lambda x: -x[1]))
        p1 += f" ({others})"
    p1 += " - a fragmented, early-stage vertical with consolidation opportunity."

    # ── Paragraph 2: Opportunity Insight ──
    p2_parts = []
    if vc_sbir_companies:
        names = [p["name"] for p in vc_sbir_companies[:3]]
        p2_parts.append(
            f"Momentum is concentrated in companies pairing SBIR validation with "
            f"private capital: {', '.join(names)}."
        )
    if len(phase2_companies) > 0 and len(contract_companies) == 0:
        p2_parts.append(
            f"{len(phase2_companies)} companies hold Phase II awards but none have "
            "converted to production contracts - a transition gap that represents "
            "both risk and opportunity for partners who can accelerate commercialization."
        )
    elif len(phase2_companies) > len(contract_companies) > 0:
        p2_parts.append(
            f"A transition gap is visible: {len(phase2_companies)} hold Phase II awards "
            f"while only {len(contract_companies)} {'has' if len(contract_companies) == 1 else 'have'} won production contracts, "
            "suggesting the prototype-to-procurement valley of death remains a bottleneck."
        )

    inflection = []
    for p in prospects:
        sig_names = {s["name"] for s in p["positive_signals"]}
        if "Fast SBIR Graduation" in sig_names or "Funding Velocity" in sig_names:
            inflection.append(p["name"])
    if inflection:
        p2_parts.append(
            f"Watch {', '.join(inflection[:3])} for near-term movement "
            "based on acceleration signals."
        )

    p2 = " ".join(p2_parts)

    # ── Paragraph 3: Takeaway ──
    p3 = ("Engage at the SBIR Phase II inflection point, where technology is "
          "government-validated but commercialization support is scarce - these "
          "companies are most responsive to strategic partnerships and most likely "
          "to convert to program-of-record suppliers.")

    paragraphs = [p1]
    if p2:
        paragraphs.append(p2)
    paragraphs.append(p3)
    return paragraphs


def build_prospects(db, model, queries: list[str], min_composite: float = 0.0,
                    min_similarity: float = 0.35, min_relevance: float = 0.40,
                    top_n: int = 10, exclude_names: set = None):
    """Build ranked prospect list from multiple semantic queries."""
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

    prospects = []
    for eid, sim_score in merged_sim.items():
        if sim_score < min_relevance:
            continue

        entity = db.query(Entity).filter(Entity.id == eid).first()
        if not entity or entity.merged_into_id:
            continue
        if entity.entity_type != EntityType.STARTUP:
            continue
        if is_excluded(entity.canonical_name):
            continue
        if exclude_names and entity.canonical_name in exclude_names:
            continue

        scoring = compute_composite(db, eid)
        if scoring["composite"] <= min_composite:
            continue
        if not scoring["positive_signals"]:
            continue

        activity = get_entity_activity(db, eid)

        # Dedupe and sort titles by sim, clean artifacts
        seen = set()
        unique_titles = []
        for sim, title in sorted(all_titles.get(eid, []), key=lambda x: -x[0]):
            cleaned = clean_title(title)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                unique_titles.append((sim, cleaned))

        # Combined ranking: relevance-weighted
        max_composite = 6.0
        norm_composite = min(scoring["composite"] / max_composite, 1.0)
        rank_score = 0.65 * sim_score + 0.35 * norm_composite

        website_url = getattr(entity, 'website_url', None) or ""

        prospects.append({
            "entity_id": eid,
            "name": entity.canonical_name,
            "location": entity.headquarters_location or "",
            "website_url": website_url,
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
    print(f"  Qualified prospects (relevance >= {min_relevance}): {len(prospects)}")
    return prospects[:top_n]


def generate_markdown(prospects: list, title: str, queries: list[str],
                      analyst_note: list[str] = None) -> str:
    """Generate markdown report from prospect list."""
    today = date.today().strftime("%B %d, %Y")

    lines = []
    lines.append(f"# Aperture Signals: {title}")
    lines.append(f"")
    lines.append(f"**Generated:** {today}")
    lines.append(f"**Prospects:** {len(prospects)} companies")
    n_queries = len(queries)
    query_word = "query" if n_queries == 1 else "queries"
    lines.append(f"**Methodology:** Semantic similarity search over {n_queries} technology {query_word}, "
                 f"filtered for startups with positive intelligence signals and net-positive composite scores.")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # Analyst's Note
    if analyst_note:
        lines.append(f"## Analyst's Note")
        lines.append(f"")
        for para in analyst_note:
            lines.append(para)
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
        if p["website_url"]:
            lines.append(f"**Website:** {p['website_url']}")

        lines.append(f"**Estimated Stage:** {act['stage']}  ")
        lines.append(f"**Composite Score:** {p['composite']:.2f} "
                     f"(+{p['positive']:.1f} / {p['negative']:.1f})  ")
        lines.append(f"**Technology Relevance:** {p['sim_score']:.3f}")
        lines.append(f"")

        # Technology summary
        lines.append(f"**Technology Focus:**")
        for sim, title_text in p["titles"][:3]:
            lines.append(f"- {title_text}")
        lines.append(f"")

        # Signals
        lines.append(f"**Intelligence Signals:**")
        for sig in p["positive_signals"]:
            lines.append(f"- [+] {sig['name']} (score: {sig['score']:.2f})")
        for sig in p["negative_signals"]:
            lines.append(f"- [-] {sig['name']} (score: {sig['score']:.2f})")
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
    lines.append(f"**Scoring Methodology:**")
    lines.append(f"- **Composite Score:** Weighted sum of 13 signals (SBIR advancement, contract wins, "
                 f"VC raises, agency breadth, risk factors). Higher = stronger momentum.")
    lines.append(f"- **Relevance Score:** Semantic similarity between company R&D portfolio and target "
                 f"technology (0-1 scale).")
    lines.append(f"- **Final Rank:** 65% relevance + 35% normalized composite score.")
    lines.append(f"")
    lines.append(f"**Pipeline:**")
    lines.append(f"1. **Semantic Search:** SBIR award titles embedded with `all-MiniLM-L6-v2` "
                 f"sentence-transformer (384-dim vectors). Cosine similarity against technology queries.")
    lines.append(f"2. **Signal Scoring:** Composite score from {len(ALL_WEIGHTS)} signal types "
                 f"including SBIR progression, contract wins, VC fundraising, multi-agency interest, "
                 f"and risk indicators (customer concentration, SBIR stalling).")
    lines.append(f"3. **Ranking:** 65% technology relevance + 35% composite signal score.")
    lines.append(f"4. **Filtering:** Startups only, net-positive composite score, at least one positive signal, "
                 f"excluding major defense primes.")
    lines.append(f"")
    lines.append(f"**Search Queries:**")
    for q in queries:
        lines.append(f'- "{q}"')
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"**Data Sources:**")
    lines.append(f"- 5,147 DoD contracts from USASpending.gov (2020-2025)")
    lines.append(f"- 1,653 SBIR awards with semantic embeddings")
    lines.append(f"- 1,979 SEC Form D filings")
    lines.append(f"- Proprietary composite scoring across 13 signal types")
    lines.append(f"")
    lines.append(f"*Aperture Signals Intelligence Engine v1.0 | {today}*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate prospect report")
    parser.add_argument("--query", type=str, nargs="+", required=True,
                        help="One or more semantic search queries")
    parser.add_argument("--title", type=str, default="Emerging Company Report",
                        help="Report title")
    parser.add_argument("--output", type=str, default="reports/prospect_report.md",
                        help="Output file path (.md or .pdf)")
    parser.add_argument("--count", type=int, default=10,
                        help="Number of prospects (default: 10)")
    parser.add_argument("--top", type=int, default=None,
                        help="Alias for --count (deprecated)")
    parser.add_argument("--min-relevance", type=float, default=0.40,
                        help="Minimum relevance score (default: 0.40)")
    parser.add_argument("--min-composite", type=float, default=0.0,
                        help="Minimum composite score")
    parser.add_argument("--exclude", type=str, default="",
                        help="Semicolon-separated company names to exclude")
    args = parser.parse_args()

    top_n = args.top if args.top is not None else args.count
    exclude_set = set(n.strip() for n in args.exclude.split(";") if n.strip()) if args.exclude else None

    db = SessionLocal()

    print(f"Loading embedding model...")
    model = load_model()

    if exclude_set:
        print(f"  Excluding: {', '.join(exclude_set)}")

    print(f"Building prospect list...")
    prospects = build_prospects(
        db, model,
        queries=args.query,
        min_composite=args.min_composite,
        min_relevance=args.min_relevance,
        top_n=top_n,
        exclude_names=exclude_set,
    )

    if not prospects:
        print("No qualifying prospects found.")
        db.close()
        return

    analyst_note = generate_analyst_note(prospects, args.query, args.title)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.suffix == ".pdf":
        # PDF output — import rendering module
        sys.path.insert(0, str(Path(__file__).parent))
        from generate_pdf_report import build_pdf
        print(f"\nGenerating PDF: {output_path}")
        pages = build_pdf(prospects, args.title, args.query, output_path,
                          analyst_note=analyst_note)
        print(f"Report saved: {output_path} ({pages} pages, {output_path.stat().st_size:,} bytes)")
    else:
        # Markdown output
        print(f"\nGenerating report: {output_path}")
        md = generate_markdown(prospects, args.title, args.query,
                               analyst_note=analyst_note)
        output_path.write_text(md)
        print(f"Report saved: {output_path} ({len(md):,} bytes)")

    # Console summary
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
