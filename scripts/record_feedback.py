#!/usr/bin/env python3
"""
Record Feedback — Log report feedback and signal validation outcomes.

Usage:
    python scripts/record_feedback.py \
        --report "brief_firestorm_labs" --recipient don --rating valuable \
        --notes "Confirmed Firestorm's Phase II trajectory"

    python scripts/record_feedback.py \
        --validate --entity "Scout Space" --signal sbir_to_contract_transition \
        --type confirmed

    python scripts/record_feedback.py --stats
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from processing.database import SessionLocal
from processing.models import (
    Entity, ReportDelivery, Signal, SignalValidation,
)


def record_report_feedback(db, report_slug: str, recipient: str,
                           rating: str, notes: str | None):
    """Record feedback on a delivered report."""
    delivery = db.query(ReportDelivery).filter(
        ReportDelivery.report_slug == report_slug,
    ).order_by(ReportDelivery.delivered_at.desc()).first()

    if not delivery:
        print(f"No delivery found for report slug '{report_slug}'.")
        print("Tip: use --stats to see all deliveries.")
        return

    delivery.feedback_rating = rating
    delivery.feedback_notes = notes
    delivery.feedback_date = datetime.utcnow()
    if recipient:
        delivery.recipient = recipient
    db.commit()

    entity = db.query(Entity).filter(Entity.id == delivery.entity_id).first()
    print(f"Feedback recorded for '{report_slug}' (entity: {entity.canonical_name if entity else 'unknown'})")
    print(f"  Rating: {rating}")
    if notes:
        print(f"  Notes: {notes}")


def validate_signal(db, entity_name: str, signal_type: str,
                    validation_type: str, notes: str | None):
    """Record validation for a signal."""
    entity = db.query(Entity).filter(
        Entity.canonical_name.ilike(f"%{entity_name}%"),
        Entity.merged_into_id.is_(None),
    ).first()

    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return

    signal = db.query(Signal).filter(
        Signal.entity_id == entity.id,
        Signal.signal_type == signal_type,
    ).order_by(Signal.detected_date.desc()).first()

    if not signal:
        print(f"No signal of type '{signal_type}' found for {entity.canonical_name}.")
        return

    validation = SignalValidation(
        signal_id=signal.id,
        entity_id=entity.id,
        signal_type=signal_type,
        validation_type=validation_type,
        validation_source="manual",
        actual_outcome=notes,
    )
    db.add(validation)
    db.commit()

    print(f"Signal validation recorded:")
    print(f"  Entity: {entity.canonical_name}")
    print(f"  Signal: {signal_type} (detected {signal.detected_date})")
    print(f"  Validation: {validation_type}")


def show_stats(db):
    """Show validation rates by signal type."""
    # Delivery stats
    delivery_count = db.query(ReportDelivery).count()
    feedback_count = db.query(ReportDelivery).filter(
        ReportDelivery.feedback_rating.isnot(None)
    ).count()

    print(f"\nReport Deliveries: {delivery_count}")
    print(f"  With feedback: {feedback_count}")

    if feedback_count > 0:
        by_rating = db.query(
            ReportDelivery.feedback_rating,
            func.count(ReportDelivery.id),
        ).filter(
            ReportDelivery.feedback_rating.isnot(None)
        ).group_by(ReportDelivery.feedback_rating).all()

        print("\n  Feedback breakdown:")
        for rating, count in by_rating:
            print(f"    {rating:<20} {count:>4}")

    # Validation stats
    val_count = db.query(SignalValidation).count()
    print(f"\nSignal Validations: {val_count}")

    if val_count > 0:
        by_type = db.query(
            SignalValidation.signal_type,
            SignalValidation.validation_type,
            func.count(SignalValidation.id),
        ).group_by(
            SignalValidation.signal_type,
            SignalValidation.validation_type,
        ).all()

        print("\n  By signal type and outcome:")
        print(f"  {'Signal Type':<40} {'Outcome':<20} {'Count':>5}")
        print(f"  {'-'*40} {'-'*20} {'-'*5}")
        for sig_type, val_type, count in by_type:
            print(f"  {sig_type:<40} {val_type:<20} {count:>5}")


def main():
    parser = argparse.ArgumentParser(
        description="Record report feedback and signal validation outcomes"
    )

    # Feedback mode
    parser.add_argument("--report", type=str, help="Report slug to record feedback for")
    parser.add_argument("--recipient", type=str, help="Recipient name")
    parser.add_argument("--rating", type=str,
                        choices=["valuable", "somewhat_useful", "not_useful", "actionable"],
                        help="Feedback rating")
    parser.add_argument("--notes", type=str, help="Feedback notes or outcome description")

    # Validation mode
    parser.add_argument("--validate", action="store_true", help="Record signal validation")
    parser.add_argument("--entity", type=str, help="Entity name for validation")
    parser.add_argument("--signal", type=str, help="Signal type to validate")
    parser.add_argument("--type", type=str, dest="val_type",
                        choices=["confirmed", "false_positive", "pending", "partial"],
                        help="Validation type")

    # Stats
    parser.add_argument("--stats", action="store_true", help="Show validation statistics")

    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.stats:
            show_stats(db)
        elif args.report and args.rating:
            record_report_feedback(db, args.report, args.recipient, args.rating, args.notes)
        elif args.validate and args.entity and args.signal and args.val_type:
            validate_signal(db, args.entity, args.signal, args.val_type, args.notes)
        else:
            parser.print_help()
    finally:
        db.close()


if __name__ == "__main__":
    main()
