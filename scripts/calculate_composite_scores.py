#!/usr/bin/env python3
"""
Calculate composite signal scores for defense entities.

Aggregates all active signals per entity with weighted scoring to produce
a single "investment readiness" composite score.

Usage:
    python scripts/calculate_composite_scores.py                # Top 20 companies
    python scripts/calculate_composite_scores.py --top 50       # Top 50
    python scripts/calculate_composite_scores.py --negative     # Show negative signals
    python scripts/calculate_composite_scores.py --all          # Full breakdown
"""

import argparse
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func

from processing.database import SessionLocal
from processing.models import Entity, Signal, SignalStatus, Contract, FundingEvent
from processing.signal_detector import (
    SIGNAL_SBIR_TO_CONTRACT,
    SIGNAL_RAPID_GROWTH,
    SIGNAL_SBIR_TO_VC,
    SIGNAL_OUTSIZED_AWARD,
    SIGNAL_SBIR_PHASE_2,
    SIGNAL_SBIR_PHASE_3,
    SIGNAL_MULTI_AGENCY,
    SIGNAL_HIGH_PRIORITY_TECH,
    SIGNAL_FIRST_DOD_CONTRACT,
    SIGNAL_SBIR_STALLED,
    SIGNAL_CUSTOMER_CONCENTRATION,
    SIGNAL_SBIR_GRADUATION_SPEED,
    SIGNAL_TIME_TO_CONTRACT,
    SIGNAL_FUNDING_VELOCITY,
)

# Positive signal weights
POSITIVE_WEIGHTS = {
    SIGNAL_SBIR_TO_CONTRACT: 3.0,
    SIGNAL_RAPID_GROWTH: 2.5,
    SIGNAL_SBIR_TO_VC: 2.0,
    SIGNAL_OUTSIZED_AWARD: 2.0,
    SIGNAL_SBIR_PHASE_2: 1.5,
    SIGNAL_SBIR_PHASE_3: 2.0,  # Phase III is rarer/more valuable than Phase II
    SIGNAL_MULTI_AGENCY: 1.5,
    SIGNAL_HIGH_PRIORITY_TECH: 1.0,
    SIGNAL_FIRST_DOD_CONTRACT: 1.0,
    SIGNAL_SBIR_GRADUATION_SPEED: 1.5,
    SIGNAL_TIME_TO_CONTRACT: 2.0,
    SIGNAL_FUNDING_VELOCITY: 1.5,
}

# Negative signal weights (subtracted from score)
NEGATIVE_WEIGHTS = {
    SIGNAL_SBIR_STALLED: -2.0,
    SIGNAL_CUSTOMER_CONCENTRATION: -1.5,
}

ALL_WEIGHTS = {**POSITIVE_WEIGHTS, **NEGATIVE_WEIGHTS}


def calculate_scores(db):
    """Calculate composite scores for all entities with active signals."""
    # Get all active signals grouped by entity
    signals = db.query(Signal).filter(
        Signal.status == SignalStatus.ACTIVE
    ).all()

    entity_signals = defaultdict(list)
    for s in signals:
        entity_signals[s.entity_id].append(s)

    # Calculate composite score per entity
    scores = []
    for entity_id, entity_sigs in entity_signals.items():
        entity = db.query(Entity).filter(Entity.id == entity_id).first()
        if not entity or entity.merged_into_id:
            continue

        positive_score = 0.0
        negative_score = 0.0
        signal_breakdown = []

        for sig in entity_sigs:
            weight = ALL_WEIGHTS.get(sig.signal_type, 0.0)
            confidence = float(sig.confidence_score or 0)
            weighted = weight * confidence

            signal_breakdown.append({
                "type": sig.signal_type,
                "weight": weight,
                "confidence": confidence,
                "weighted_score": round(weighted, 2),
                "evidence": sig.evidence,
            })

            if weight > 0:
                positive_score += weighted
            else:
                negative_score += weighted

        composite = positive_score + negative_score

        scores.append({
            "entity_id": entity_id,
            "entity_name": entity.canonical_name,
            "entity_type": entity.entity_type.value,
            "composite_score": round(composite, 2),
            "positive_score": round(positive_score, 2),
            "negative_score": round(negative_score, 2),
            "signal_count": len(entity_sigs),
            "positive_count": sum(1 for s in signal_breakdown if s["weight"] > 0),
            "negative_count": sum(1 for s in signal_breakdown if s["weight"] < 0),
            "breakdown": sorted(signal_breakdown, key=lambda x: -abs(x["weighted_score"])),
        })

    scores.sort(key=lambda x: -x["composite_score"])
    return scores


def print_top_companies(scores, top_n):
    """Print top N companies by composite score."""
    print("\n" + "=" * 80)
    print(f"  TOP {top_n} COMPANIES BY COMPOSITE SIGNAL SCORE")
    print("=" * 80)
    print(f"\n{'Rank':<5} {'Company':<40} {'Score':>7} {'Pos':>5} {'Neg':>5} {'Signals':>7}")
    print("-" * 80)

    for i, s in enumerate(scores[:top_n], 1):
        name = s["entity_name"][:38]
        neg_str = f"{s['negative_score']:>5.1f}" if s["negative_score"] < 0 else "    -"
        print(
            f"{i:<5} {name:<40} {s['composite_score']:>7.2f} "
            f"{s['positive_score']:>5.1f} {neg_str} "
            f"{s['signal_count']:>4}"
        )

    # Show detailed breakdown of top 5
    print("\n" + "=" * 80)
    print("  DETAILED BREAKDOWN — TOP 5")
    print("=" * 80)

    for i, s in enumerate(scores[:5], 1):
        print(f"\n{i}. {s['entity_name']}  (Score: {s['composite_score']:.2f})")
        print(f"   Type: {s['entity_type']}")
        for sig in s["breakdown"]:
            marker = "+" if sig["weight"] > 0 else "-"
            print(
                f"   {marker} {sig['type']:<35} "
                f"weight={sig['weight']:>5.1f}  "
                f"conf={sig['confidence']:.2f}  "
                f"= {sig['weighted_score']:>6.2f}"
            )


def print_negative_signals(scores):
    """Print entities with negative signals."""
    negative = [s for s in scores if s["negative_count"] > 0]

    print("\n" + "=" * 80)
    print(f"  ENTITIES WITH NEGATIVE SIGNALS ({len(negative)} companies)")
    print("=" * 80)

    # Group by negative signal type
    stalled = []
    concentrated = []

    for s in negative:
        for sig in s["breakdown"]:
            if sig["type"] == SIGNAL_SBIR_STALLED:
                stalled.append((s, sig))
            elif sig["type"] == SIGNAL_CUSTOMER_CONCENTRATION:
                concentrated.append((s, sig))

    if stalled:
        print(f"\n--- SBIR STALLED ({len(stalled)} companies) ---")
        print("Companies with 2+ Phase I awards but zero Phase II advancement\n")
        for s, sig in sorted(stalled, key=lambda x: -x[1]["confidence"]):
            ev = sig["evidence"] or {}
            print(
                f"  {s['entity_name']:<40} "
                f"Phase I: {ev.get('phase_1_count', '?')}  "
                f"Value: ${ev.get('total_phase_1_value', 0):>12,.0f}  "
                f"Composite: {s['composite_score']:>6.2f}"
            )

    if concentrated:
        print(f"\n--- CUSTOMER CONCENTRATION ({len(concentrated)} companies) ---")
        print("Companies with >80% of contract value from a single agency\n")
        for s, sig in sorted(concentrated, key=lambda x: -x[1]["confidence"]):
            ev = sig["evidence"] or {}
            print(
                f"  {s['entity_name']:<40} "
                f"{ev.get('dominant_agency', '?'):<25} "
                f"{ev.get('concentration_pct', 0):>5.1f}%  "
                f"Composite: {s['composite_score']:>6.2f}"
            )


def print_full_breakdown(scores):
    """Print all companies with signal breakdown."""
    print_top_companies(scores, min(20, len(scores)))
    print_negative_signals(scores)

    # Summary stats
    total = len(scores)
    positive_only = sum(1 for s in scores if s["negative_count"] == 0 and s["positive_count"] > 0)
    mixed = sum(1 for s in scores if s["negative_count"] > 0 and s["positive_count"] > 0)
    negative_only = sum(1 for s in scores if s["negative_count"] > 0 and s["positive_count"] == 0)

    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  Total entities with signals: {total}")
    print(f"  Positive signals only:       {positive_only}")
    print(f"  Mixed (positive + negative): {mixed}")
    print(f"  Negative signals only:       {negative_only}")
    avg = sum(s["composite_score"] for s in scores) / total if total else 0
    print(f"  Average composite score:     {avg:.2f}")
    print(f"  Max composite score:         {scores[0]['composite_score']:.2f}" if scores else "")
    print(f"  Min composite score:         {scores[-1]['composite_score']:.2f}" if scores else "")


def main():
    parser = argparse.ArgumentParser(description="Calculate composite signal scores")
    parser.add_argument("--top", type=int, default=20, help="Show top N companies (default 20)")
    parser.add_argument("--negative", action="store_true", help="Show negative signals")
    parser.add_argument("--all", action="store_true", help="Full breakdown with summary")
    args = parser.parse_args()

    db = SessionLocal()
    scores = calculate_scores(db)

    if args.all:
        print_full_breakdown(scores)
    elif args.negative:
        print_negative_signals(scores)
    else:
        print_top_companies(scores, args.top)

    db.close()


if __name__ == "__main__":
    main()
