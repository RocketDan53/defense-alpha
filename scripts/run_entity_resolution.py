#!/usr/bin/env python3
"""
Run entity resolution on all entities in the database.

Usage:
    python scripts/run_entity_resolution.py
    python scripts/run_entity_resolution.py --dry-run
    python scripts/run_entity_resolution.py --export-only
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Entity, Contract
from processing.entity_resolver import EntityResolver


def main():
    parser = argparse.ArgumentParser(
        description="Run entity resolution to deduplicate companies"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be merged without actually merging",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Only export review queue, don't auto-merge anything",
    )

    args = parser.parse_args()

    db = SessionLocal()

    try:
        # Show current state
        entity_count = db.query(Entity).filter(Entity.merged_into_id.is_(None)).count()
        contract_count = db.query(Contract).count()

        print("=" * 60)
        print("ENTITY RESOLUTION")
        print("=" * 60)
        print(f"Active entities: {entity_count}")
        print(f"Total contracts: {contract_count}")
        print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
        print("=" * 60)

        resolver = EntityResolver(db)

        if args.export_only:
            # Just find duplicates and export
            print("\nFinding potential duplicates...")
            stats = resolver.resolve_all_entities(dry_run=True)
            if resolver.review_queue:
                csv_path = resolver.export_review_queue()
                print(f"\nExported {len(resolver.review_queue)} potential matches to:")
                print(f"  {csv_path}")
        else:
            # Run full resolution
            stats = resolver.resolve_all_entities(dry_run=args.dry_run)

            # Export review queue if there are items
            if resolver.review_queue:
                csv_path = resolver.export_review_queue()
                print(f"\nReview queue exported to: {csv_path}")

        # Show final state
        if not args.dry_run:
            final_entity_count = db.query(Entity).filter(
                Entity.merged_into_id.is_(None)
            ).count()
            print(f"\nFinal active entities: {final_entity_count}")
            print(f"Entities merged: {entity_count - final_entity_count}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
