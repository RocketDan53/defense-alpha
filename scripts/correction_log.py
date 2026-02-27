#!/usr/bin/env python3
"""
Correction Log — Query and export entity resolution correction history.

Usage:
    python scripts/correction_log.py --stats
    python scripts/correction_log.py --export corrections.csv
    python scripts/correction_log.py --entity "Scout Space"
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from processing.database import SessionLocal
from processing.models import EntityCorrection, Entity


def show_stats(db):
    """Show correction statistics grouped by type and source."""
    total = db.query(EntityCorrection).count()
    print(f"\nTotal corrections: {total}")

    if total == 0:
        print("No corrections recorded yet.")
        return

    # By type
    by_type = db.query(
        EntityCorrection.correction_type,
        func.count(EntityCorrection.id),
    ).group_by(EntityCorrection.correction_type).all()

    print("\nBy correction type:")
    for ctype, count in by_type:
        print(f"  {ctype:<25} {count:>6}")

    # By source
    by_source = db.query(
        EntityCorrection.correction_source,
        func.count(EntityCorrection.id),
    ).group_by(EntityCorrection.correction_source).all()

    print("\nBy correction source:")
    for source, count in by_source:
        print(f"  {source or 'unknown':<25} {count:>6}")

    # By decided_by
    by_decider = db.query(
        EntityCorrection.decided_by,
        func.count(EntityCorrection.id),
    ).group_by(EntityCorrection.decided_by).all()

    print("\nBy decider:")
    for decider, count in by_decider:
        print(f"  {decider:<25} {count:>6}")


def export_corrections(db, output_path: str):
    """Export all corrections to CSV."""
    corrections = db.query(EntityCorrection).order_by(
        EntityCorrection.decided_at.desc()
    ).all()

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "correction_type", "entity_a_id", "source_name_a",
            "entity_b_id", "source_name_b", "decision",
            "confidence_before", "confidence_after", "reasoning",
            "decided_by", "decided_at", "correction_source",
        ])
        for c in corrections:
            writer.writerow([
                c.id, c.correction_type, c.entity_a_id, c.source_name_a,
                c.entity_b_id, c.source_name_b, c.decision,
                c.confidence_before, c.confidence_after, c.reasoning,
                c.decided_by, c.decided_at, c.correction_source,
            ])

    print(f"Exported {len(corrections)} corrections to {output_path}")


def show_entity_history(db, entity_name: str):
    """Show correction history for an entity."""
    # Find entity
    entity = db.query(Entity).filter(
        Entity.canonical_name.ilike(f"%{entity_name}%")
    ).first()

    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return

    print(f"\nCorrection history for: {entity.canonical_name} ({entity.id})")

    corrections = db.query(EntityCorrection).filter(
        (EntityCorrection.entity_a_id == entity.id) |
        (EntityCorrection.entity_b_id == entity.id)
    ).order_by(EntityCorrection.decided_at.desc()).all()

    if not corrections:
        print("  No corrections found.")
        return

    for c in corrections:
        print(f"\n  [{c.decided_at}] {c.correction_type} — {c.decision}")
        print(f"    A: {c.source_name_a}")
        if c.source_name_b:
            print(f"    B: {c.source_name_b}")
        if c.reasoning:
            print(f"    Reason: {c.reasoning}")
        print(f"    Decided by: {c.decided_by} via {c.correction_source}")


def main():
    parser = argparse.ArgumentParser(
        description="Query entity resolution correction history"
    )
    parser.add_argument("--stats", action="store_true", help="Show correction statistics")
    parser.add_argument("--export", type=str, metavar="PATH", help="Export corrections to CSV")
    parser.add_argument("--entity", type=str, help="Show history for entity")

    args = parser.parse_args()

    if not any([args.stats, args.export, args.entity]):
        parser.print_help()
        return

    db = SessionLocal()
    try:
        if args.stats:
            show_stats(db)
        if args.export:
            export_corrections(db, args.export)
        if args.entity:
            show_entity_history(db, args.entity)
    finally:
        db.close()


if __name__ == "__main__":
    main()
