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
from datetime import date
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
    SIGNAL_GONE_STALE,
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
    SIGNAL_GONE_STALE: -1.5,
}

ALL_WEIGHTS = {**POSITIVE_WEIGHTS, **NEGATIVE_WEIGHTS}


# ---------------------------------------------------------------------------
# Signal-type-specific freshness decay profiles
# ---------------------------------------------------------------------------
# Each profile is a list of (max_days, weight) tuples.
# The first matching threshold is used; final entry has None = catch-all.

# FAST_DECAY: momentum signals — stale quickly, relevance drops after 12mo
FAST_DECAY = [
    (182, 1.0),    # 0-6 months: full value
    (365, 0.7),    # 6-12 months: 70%
    (730, 0.4),    # 12-24 months: 40%
    (None, 0.2),   # 24+ months: 20%
]

# SLOW_DECAY: milestone signals — represent real achievements, relevant for years
SLOW_DECAY = [
    (365, 1.0),    # 0-12 months: full value
    (730, 0.85),   # 12-24 months: 85%
    (1095, 0.65),  # 24-36 months: 65%
    (None, 0.4),   # 36+ months: 40%
]

# NO_DECAY: structural signals — true until explicitly contradicted
NO_DECAY = [
    (None, 1.0),   # Always full value
]

# Map each signal type to its decay profile
SIGNAL_DECAY_PROFILES = {
    # Fast decay — momentum signals
    SIGNAL_FUNDING_VELOCITY: FAST_DECAY,
    SIGNAL_RAPID_GROWTH: FAST_DECAY,
    SIGNAL_FIRST_DOD_CONTRACT: FAST_DECAY,

    # Slow decay — milestone signals
    SIGNAL_SBIR_PHASE_2: SLOW_DECAY,
    SIGNAL_SBIR_PHASE_3: SLOW_DECAY,
    SIGNAL_SBIR_TO_CONTRACT: SLOW_DECAY,
    SIGNAL_SBIR_TO_VC: SLOW_DECAY,
    SIGNAL_SBIR_GRADUATION_SPEED: SLOW_DECAY,
    SIGNAL_TIME_TO_CONTRACT: SLOW_DECAY,
    SIGNAL_OUTSIZED_AWARD: SLOW_DECAY,

    # No decay — structural signals
    SIGNAL_CUSTOMER_CONCENTRATION: NO_DECAY,
    SIGNAL_MULTI_AGENCY: NO_DECAY,
    SIGNAL_HIGH_PRIORITY_TECH: NO_DECAY,
    SIGNAL_SBIR_STALLED: NO_DECAY,
    SIGNAL_GONE_STALE: NO_DECAY,
}

# Default profile for unknown signal types
DEFAULT_DECAY = SLOW_DECAY


def calculate_freshness_weight(detected_date: date, signal_type: str = "") -> float:
    """
    Calculate freshness decay factor based on signal age and type.

    Args:
        detected_date: When the signal was detected
        signal_type: Signal type string to look up decay profile

    Returns:
        Decay multiplier between 0.0 and 1.0
    """
    if detected_date is None:
        return 0.5  # Unknown date gets middle value

    profile = SIGNAL_DECAY_PROFILES.get(signal_type, DEFAULT_DECAY)
    days_old = (date.today() - detected_date).days

    for threshold, weight in profile:
        if threshold is None or days_old <= threshold:
            return weight
    return profile[-1][1]  # Fallback to last entry


def calculate_scores(db, persist_freshness=False):
    """
    Calculate composite scores for all entities with active signals.

    Computes two scores per entity:
    - composite_score: raw weight * confidence (no decay)
    - freshness_adjusted_score: weight * confidence * freshness_decay

    Args:
        db: Database session
        persist_freshness: If True, update signal.freshness_weight in DB
    """
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
        adj_positive_score = 0.0
        adj_negative_score = 0.0
        signal_breakdown = []

        for sig in entity_sigs:
            weight = ALL_WEIGHTS.get(sig.signal_type, 0.0)
            confidence = float(sig.confidence_score or 0)
            freshness = calculate_freshness_weight(sig.detected_date, sig.signal_type)
            weighted = weight * confidence
            adj_weighted = weight * confidence * freshness

            # Persist freshness weight on the signal row
            if persist_freshness:
                sig.freshness_weight = Decimal(str(round(freshness, 2)))

            signal_breakdown.append({
                "type": sig.signal_type,
                "weight": weight,
                "confidence": confidence,
                "freshness": freshness,
                "weighted_score": round(weighted, 2),
                "adjusted_score": round(adj_weighted, 2),
                "detected_date": str(sig.detected_date) if sig.detected_date else None,
                "evidence": sig.evidence,
            })

            if weight > 0:
                positive_score += weighted
                adj_positive_score += adj_weighted
            else:
                negative_score += weighted
                adj_negative_score += adj_weighted

        composite = positive_score + negative_score
        freshness_adjusted = adj_positive_score + adj_negative_score

        scores.append({
            "entity_id": entity_id,
            "entity_name": entity.canonical_name,
            "entity_type": entity.entity_type.value,
            "composite_score": round(composite, 2),
            "freshness_adjusted_score": round(freshness_adjusted, 2),
            "positive_score": round(positive_score, 2),
            "negative_score": round(negative_score, 2),
            "signal_count": len(entity_sigs),
            "positive_count": sum(1 for s in signal_breakdown if s["weight"] > 0),
            "negative_count": sum(1 for s in signal_breakdown if s["weight"] < 0),
            "breakdown": sorted(signal_breakdown, key=lambda x: -abs(x["adjusted_score"])),
        })

    if persist_freshness:
        db.commit()

    scores.sort(key=lambda x: -x["freshness_adjusted_score"])
    return scores


def print_top_companies(scores, top_n):
    """Print top N companies by freshness-adjusted composite score."""
    print("\n" + "=" * 90)
    print(f"  TOP {top_n} COMPANIES BY COMPOSITE SIGNAL SCORE (FRESHNESS-ADJUSTED)")
    print("=" * 90)
    print(f"\n{'Rank':<5} {'Company':<38} {'Adj':>7} {'Raw':>7} {'Pos':>5} {'Neg':>5} {'Signals':>7}")
    print("-" * 90)

    for i, s in enumerate(scores[:top_n], 1):
        name = s["entity_name"][:36]
        neg_str = f"{s['negative_score']:>5.1f}" if s["negative_score"] < 0 else "    -"
        print(
            f"{i:<5} {name:<38} {s['freshness_adjusted_score']:>7.2f} "
            f"{s['composite_score']:>7.2f} "
            f"{s['positive_score']:>5.1f} {neg_str} "
            f"{s['signal_count']:>4}"
        )

    # Show detailed breakdown of top 5
    print("\n" + "=" * 90)
    print("  DETAILED BREAKDOWN — TOP 5")
    print("=" * 90)

    for i, s in enumerate(scores[:5], 1):
        print(
            f"\n{i}. {s['entity_name']}  "
            f"(Adjusted: {s['freshness_adjusted_score']:.2f}  "
            f"Raw: {s['composite_score']:.2f})"
        )
        print(f"   Type: {s['entity_type']}")
        for sig in s["breakdown"]:
            marker = "+" if sig["weight"] > 0 else "-"
            decay_str = f"x{sig['freshness']:.2f}" if sig["freshness"] < 1.0 else "     "
            print(
                f"   {marker} {sig['type']:<35} "
                f"weight={sig['weight']:>5.1f}  "
                f"conf={sig['confidence']:.2f}  "
                f"= {sig['weighted_score']:>6.2f}  "
                f"{decay_str} -> {sig['adjusted_score']:>6.2f}"
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
    avg_raw = sum(s["composite_score"] for s in scores) / total if total else 0
    avg_adj = sum(s["freshness_adjusted_score"] for s in scores) / total if total else 0
    print(f"  Average raw score:           {avg_raw:.2f}")
    print(f"  Average adjusted score:      {avg_adj:.2f}")
    print(f"  Freshness discount:          {(1 - avg_adj / avg_raw) * 100:.1f}%" if avg_raw else "")
    if scores:
        print(f"  Max adjusted score:          {scores[0]['freshness_adjusted_score']:.2f}")
        print(f"  Min adjusted score:          {scores[-1]['freshness_adjusted_score']:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Calculate composite signal scores")
    parser.add_argument("--top", type=int, default=20, help="Show top N companies (default 20)")
    parser.add_argument("--negative", action="store_true", help="Show negative signals")
    parser.add_argument("--all", action="store_true", help="Full breakdown with summary")
    parser.add_argument("--persist", action="store_true", help="Save freshness_weight to signal rows in DB")
    args = parser.parse_args()

    db = SessionLocal()
    scores = calculate_scores(db, persist_freshness=args.persist)

    if args.all:
        print_full_breakdown(scores)
    elif args.negative:
        print_negative_signals(scores)
    else:
        print_top_companies(scores, args.top)

    db.close()


if __name__ == "__main__":
    main()
