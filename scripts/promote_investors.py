#!/usr/bin/env python3
"""
Promote Investors — Create Entity and Relationship records from Reg D investor data.

Extracts investors from Reg D filings, creates INVESTOR entities for each unique
fund/firm, and creates INVESTED_IN_BY relationships linking them to portfolio companies.

Usage:
    python scripts/promote_investors.py
    python scripts/promote_investors.py --dry-run
    python scripts/promote_investors.py --top 20
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Entity, EntityType, Relationship, RelationshipType
from scripts.extract_investors import extract_investors_from_regd, _normalize_investor_name


def promote_investors(db, dry_run: bool = False, top_n: int | None = None):
    """Extract investors and promote to Entity + Relationship records."""
    data = extract_investors_from_regd(db)
    investor_map = data["investor_map"]

    if top_n:
        # Only promote investors with >= top_n portfolio companies
        investor_map = {
            k: v for k, v in investor_map.items()
            if len(set(inv["entity_id"] for inv in v)) >= 2
        }

    print(f"\nPromoting {len(investor_map)} investors to entities...")

    entities_created = 0
    relationships_created = 0

    for investor_name, investments in investor_map.items():
        normalized = _normalize_investor_name(investor_name)
        if not normalized:
            continue

        # Check if entity already exists
        existing = db.query(Entity).filter(
            Entity.canonical_name.ilike(f"%{normalized}%"),
            Entity.entity_type == EntityType.INVESTOR,
            Entity.merged_into_id.is_(None),
        ).first()

        if existing:
            investor_entity = existing
        else:
            if dry_run:
                print(f"  WOULD CREATE entity: {normalized}")
                entities_created += 1
                continue

            investor_entity = Entity(
                canonical_name=normalized,
                entity_type=EntityType.INVESTOR,
            )
            db.add(investor_entity)
            db.flush()  # Get the ID
            entities_created += 1

        # Create relationships
        unique_companies = {}
        for inv in investments:
            eid = inv["entity_id"]
            if eid not in unique_companies or (inv["amount"] or 0) > (unique_companies[eid].get("amount") or 0):
                unique_companies[eid] = inv

        for entity_id, inv_data in unique_companies.items():
            if entity_id == investor_entity.id:
                continue

            # Check for existing relationship
            existing_rel = db.query(Relationship).filter(
                Relationship.source_entity_id == entity_id,
                Relationship.target_entity_id == investor_entity.id,
                Relationship.relationship_type == RelationshipType.INVESTED_IN_BY,
            ).first()

            if existing_rel:
                continue

            if dry_run:
                print(f"  WOULD CREATE rel: {inv_data['entity_name']} --INVESTED_IN_BY--> {normalized}")
                relationships_created += 1
                continue

            rel = Relationship(
                source_entity_id=entity_id,
                relationship_type=RelationshipType.INVESTED_IN_BY,
                target_entity_id=investor_entity.id,
                target_name=normalized,
                weight=Decimal(str(inv_data["amount"])) if inv_data.get("amount") else None,
                properties={
                    "role": inv_data.get("role"),
                    "date": inv_data.get("date"),
                    "amount": inv_data.get("amount"),
                },
            )
            db.add(rel)
            relationships_created += 1

    if not dry_run:
        db.commit()

    tag = " (dry run)" if dry_run else ""
    print(f"\nDone{tag}:")
    print(f"  Investor entities created: {entities_created}")
    print(f"  Relationships created: {relationships_created}")


def main():
    parser = argparse.ArgumentParser(description="Promote investors to Entity + Relationship records")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created")
    parser.add_argument("--top", type=int, help="Only promote investors with >= N portfolio companies")

    args = parser.parse_args()

    db = SessionLocal()
    try:
        promote_investors(db, dry_run=args.dry_run, top_n=args.top)
    finally:
        db.close()


if __name__ == "__main__":
    main()
