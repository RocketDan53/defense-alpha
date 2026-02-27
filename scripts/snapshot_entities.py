#!/usr/bin/env python3
"""
Entity Snapshot — Capture point-in-time state of entities for trajectory analysis.

Usage:
    python scripts/snapshot_entities.py                               # All entities
    python scripts/snapshot_entities.py --entities "Scout Space" "Shield AI"
    python scripts/snapshot_entities.py --trajectory "Scout Space"    # Show timeline
"""

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func, text
from processing.database import SessionLocal
from processing.lifecycle import classify_lifecycle
from processing.models import (
    Entity, EntitySnapshot, Signal, SignalStatus,
    FundingEvent, FundingEventType, Contract,
)


def snapshot_entity(db, entity: Entity, snapshot_date: date) -> EntitySnapshot | None:
    """Create a snapshot for a single entity. Returns None if already exists."""
    # Check for existing snapshot
    existing = db.query(EntitySnapshot).filter(
        EntitySnapshot.entity_id == entity.id,
        EntitySnapshot.snapshot_date == snapshot_date,
    ).first()

    if existing:
        return None

    # Compute aggregate metrics
    # SBIR per-phase counts and total value
    sbir_phase_counts = {}
    for phase in (FundingEventType.SBIR_PHASE_1, FundingEventType.SBIR_PHASE_2, FundingEventType.SBIR_PHASE_3):
        cnt = db.query(func.count(FundingEvent.id)).filter(
            FundingEvent.entity_id == entity.id,
            FundingEvent.event_type == phase,
        ).scalar() or 0
        sbir_phase_counts[phase] = cnt

    sbir_total_count = sum(sbir_phase_counts.values())
    sbir_total_value = db.query(
        func.coalesce(func.sum(FundingEvent.amount), 0),
    ).filter(
        FundingEvent.entity_id == entity.id,
        FundingEvent.event_type.in_([
            FundingEventType.SBIR_PHASE_1,
            FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]),
    ).scalar() or 0

    # Contract counts/values/max
    contract_stats = db.query(
        func.count(Contract.id),
        func.coalesce(func.sum(Contract.contract_value), 0),
    ).filter(
        Contract.entity_id == entity.id,
    ).first()

    max_contract_value = db.query(
        func.coalesce(func.max(Contract.contract_value), 0),
    ).filter(
        Contract.entity_id == entity.id,
    ).scalar() or 0

    # Reg D counts/values
    regd_stats = db.query(
        func.count(FundingEvent.id),
        func.coalesce(func.sum(FundingEvent.amount), 0),
    ).filter(
        FundingEvent.entity_id == entity.id,
        FundingEvent.event_type == FundingEventType.REG_D_FILING,
    ).first()

    # Active signals
    active_signals = db.query(Signal).filter(
        Signal.entity_id == entity.id,
        Signal.status == SignalStatus.ACTIVE,
    ).all()

    signal_data = [
        {"id": s.id, "type": s.signal_type, "confidence": float(s.confidence_score or 0)}
        for s in active_signals
    ]

    # Policy tailwind score
    pa = entity.policy_alignment or {}
    policy_tailwind = pa.get("policy_tailwind_score")

    # Compute composite score (sum of active signal confidences)
    composite = sum(float(s.confidence_score or 0) for s in active_signals)

    # Freshness-adjusted: use freshness_weight from signals
    freshness_adjusted = sum(
        float(s.confidence_score or 0) * float(s.freshness_weight or 1.0)
        for s in active_signals
    )

    snapshot = EntitySnapshot(
        entity_id=entity.id,
        snapshot_date=snapshot_date,
        entity_type=entity.entity_type.value if entity.entity_type else None,
        core_business=entity.core_business.value if entity.core_business else None,
        composite_score=Decimal(str(round(composite, 2))),
        freshness_adjusted_score=Decimal(str(round(freshness_adjusted, 2))),
        policy_tailwind_score=Decimal(str(policy_tailwind)) if policy_tailwind else None,
        sbir_count=sbir_total_count,
        sbir_total_value=sbir_total_value,
        contract_count=contract_stats[0],
        contract_total_value=contract_stats[1],
        regd_count=regd_stats[0],
        regd_total_value=regd_stats[1],
        active_signals=signal_data,
        lifecycle_stage=classify_lifecycle(
            sbir_p1_count=sbir_phase_counts[FundingEventType.SBIR_PHASE_1],
            sbir_p2_count=sbir_phase_counts[FundingEventType.SBIR_PHASE_2],
            sbir_p3_count=sbir_phase_counts[FundingEventType.SBIR_PHASE_3],
            contract_count=contract_stats[0],
            max_contract_value=float(max_contract_value),
            regd_count=regd_stats[0],
            regd_total=float(regd_stats[1] or 0),
        ),
    )
    db.add(snapshot)
    return snapshot


def detect_deltas(db, entity_id: str, current_snapshot: EntitySnapshot) -> list[dict]:
    """Compare current snapshot to previous and return meaningful changes."""
    previous = db.query(EntitySnapshot).filter(
        EntitySnapshot.entity_id == entity_id,
        EntitySnapshot.snapshot_date < current_snapshot.snapshot_date,
    ).order_by(EntitySnapshot.snapshot_date.desc()).first()

    if not previous:
        return []

    deltas = []

    # Lifecycle stage change
    if previous.lifecycle_stage != current_snapshot.lifecycle_stage:
        deltas.append({
            "type": "lifecycle_change",
            "from": previous.lifecycle_stage,
            "to": current_snapshot.lifecycle_stage,
            "date": str(current_snapshot.snapshot_date),
        })

    # Composite score change (>10% relative or >1.0 absolute)
    prev_score = float(previous.composite_score or 0)
    curr_score = float(current_snapshot.composite_score or 0)
    if prev_score > 0:
        pct_change = (curr_score - prev_score) / prev_score
        if abs(pct_change) > 0.10 or abs(curr_score - prev_score) > 1.0:
            deltas.append({
                "type": "composite_score_shift",
                "from": prev_score,
                "to": curr_score,
                "pct_change": round(pct_change * 100, 1),
                "date": str(current_snapshot.snapshot_date),
            })

    # New signals (IDs in current but not previous)
    prev_signal_ids = {s["id"] for s in (previous.active_signals or [])}
    curr_signal_ids = {s["id"] for s in (current_snapshot.active_signals or [])}
    new_signals = curr_signal_ids - prev_signal_ids
    lost_signals = prev_signal_ids - curr_signal_ids

    if new_signals:
        new_types = [s["type"] for s in current_snapshot.active_signals if s["id"] in new_signals]
        deltas.append({
            "type": "new_signals",
            "signal_types": new_types,
            "count": len(new_signals),
            "date": str(current_snapshot.snapshot_date),
        })

    if lost_signals:
        lost_types = [s["type"] for s in previous.active_signals if s["id"] in lost_signals]
        deltas.append({
            "type": "lost_signals",
            "signal_types": lost_types,
            "count": len(lost_signals),
            "date": str(current_snapshot.snapshot_date),
        })

    # SBIR count increase
    if (current_snapshot.sbir_count or 0) > (previous.sbir_count or 0):
        deltas.append({
            "type": "new_sbir_awards",
            "from": previous.sbir_count,
            "to": current_snapshot.sbir_count,
            "date": str(current_snapshot.snapshot_date),
        })

    # Contract count increase
    if (current_snapshot.contract_count or 0) > (previous.contract_count or 0):
        deltas.append({
            "type": "new_contracts",
            "from": previous.contract_count,
            "to": current_snapshot.contract_count,
            "date": str(current_snapshot.snapshot_date),
        })

    return deltas


def show_trajectory(db, entity_name: str):
    """Show snapshots over time for an entity."""
    entity = db.query(Entity).filter(
        Entity.canonical_name.ilike(f"%{entity_name}%"),
        Entity.merged_into_id.is_(None),
    ).first()

    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return

    snapshots = db.query(EntitySnapshot).filter(
        EntitySnapshot.entity_id == entity.id,
    ).order_by(EntitySnapshot.snapshot_date).all()

    if not snapshots:
        print(f"No snapshots found for {entity.canonical_name}.")
        return

    print(f"\nTrajectory for: {entity.canonical_name}")
    print(f"{'Date':<12} {'Composite':>10} {'Freshness':>10} {'Signals':>8} {'SBIRs':>6} {'Contracts':>10} {'Stage':<12}")
    print("-" * 75)

    for s in snapshots:
        signals_count = len(s.active_signals or [])
        print(
            f"{s.snapshot_date!s:<12} "
            f"{float(s.composite_score or 0):>10.2f} "
            f"{float(s.freshness_adjusted_score or 0):>10.2f} "
            f"{signals_count:>8} "
            f"{int(s.sbir_count or 0):>6} "
            f"{int(s.contract_count or 0):>10} "
            f"{s.lifecycle_stage or '?':<12}"
        )


def main():
    parser = argparse.ArgumentParser(description="Capture entity state snapshots")
    parser.add_argument("--entities", nargs="+", help="Snapshot specific entities by name")
    parser.add_argument("--trajectory", type=str, help="Show trajectory for entity")

    args = parser.parse_args()

    db = SessionLocal()
    today = date.today()

    try:
        if args.trajectory:
            show_trajectory(db, args.trajectory)
            return

        # Determine entities to snapshot
        if args.entities:
            entities = []
            for name in args.entities:
                e = db.query(Entity).filter(
                    Entity.canonical_name.ilike(f"%{name}%"),
                    Entity.merged_into_id.is_(None),
                ).first()
                if e:
                    entities.append(e)
                else:
                    print(f"  Entity not found: {name}")
        else:
            entities = db.query(Entity).filter(
                Entity.merged_into_id.is_(None),
            ).all()

        print(f"Snapshotting {len(entities)} entities for {today}...")

        created = 0
        skipped = 0
        total_deltas = 0
        for entity in entities:
            result = snapshot_entity(db, entity, today)
            if result:
                created += 1
                deltas = detect_deltas(db, entity.id, result)
                if deltas:
                    total_deltas += len(deltas)
                    print(f"  {entity.canonical_name}: {len(deltas)} change(s) detected")
                    for d in deltas:
                        print(f"      {d['type']}: {d}")
            else:
                skipped += 1

        db.commit()
        print(f"Done: {created} snapshots created, {skipped} already existed, {total_deltas} deltas detected")

    finally:
        db.close()


if __name__ == "__main__":
    main()
