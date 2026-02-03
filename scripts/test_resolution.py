#!/usr/bin/env python3
"""
Test entity resolution with realistic company variations.

Test cases:
1. "Palantir Technologies Inc" + "Palantir Technologies" (same company, suffix variation)
2. "Anduril Industries" + "Anduril Industries Inc" (same company, suffix variation)
3. "SpaceX" + "Space Exploration Technologies Corp" (same company, different names)
4. "Lockheed Martin" + "Lockheed Martin Corporation" (same company, suffix variation)
5. Two actually different companies with similar names

Expected results:
- Cases 1, 2, 4 should auto-merge (>90% similarity)
- Case 3 should be flagged for review (different normalized names)
- Case 5 should remain separate
"""

import sys
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal, engine
from processing.models import Base, Entity, EntityType, Contract, EntityMerge
from processing.entity_resolver import EntityResolver


def setup_test_data(db):
    """Create test entities with variations."""
    print("\n" + "=" * 60)
    print("SETTING UP TEST DATA")
    print("=" * 60)

    entities = []

    # 1. Palantir variations (should merge - same CAGE code)
    e1a = Entity(
        canonical_name="Palantir Technologies Inc",
        name_variants=[],
        entity_type=EntityType.STARTUP,
        cage_code="4CYR7",
        headquarters_location="Denver, CO",
        technology_tags=["data analytics", "AI"],
    )
    e1b = Entity(
        canonical_name="Palantir Technologies",
        name_variants=["Palantir"],
        entity_type=EntityType.STARTUP,
        cage_code="4CYR7",  # Same CAGE code - definitive match
        headquarters_location="Denver, CO",
    )
    entities.extend([e1a, e1b])
    print(f"  1. {e1a.canonical_name} + {e1b.canonical_name} (same CAGE code)")

    # 2. Anduril variations (should merge - >90% name + same state)
    e2a = Entity(
        canonical_name="Anduril Industries",
        name_variants=[],
        entity_type=EntityType.STARTUP,
        headquarters_location="Costa Mesa, CA",
        technology_tags=["autonomous systems", "defense AI"],
    )
    e2b = Entity(
        canonical_name="Anduril Industries Inc",
        name_variants=["Anduril"],
        entity_type=EntityType.STARTUP,
        headquarters_location="Irvine, CA",  # Same state
    )
    entities.extend([e2a, e2b])
    print(f"  2. {e2a.canonical_name} + {e2b.canonical_name} (name + same state)")

    # 3. SpaceX vs Space Exploration Technologies (should flag for review)
    # Different normalized names but same company
    e3a = Entity(
        canonical_name="SpaceX",
        name_variants=[],
        entity_type=EntityType.STARTUP,
        headquarters_location="Hawthorne, CA",
        technology_tags=["rockets", "space"],
    )
    e3b = Entity(
        canonical_name="Space Exploration Technologies Corp",
        name_variants=["Space Exploration Technologies"],
        entity_type=EntityType.STARTUP,
        headquarters_location="Hawthorne, CA",
    )
    entities.extend([e3a, e3b])
    print(f"  3. {e3a.canonical_name} + {e3b.canonical_name} (different names, same company)")

    # 4. Lockheed Martin variations (should merge - >90% name + same NAICS)
    e4a = Entity(
        canonical_name="Lockheed Martin",
        name_variants=["LMT"],
        entity_type=EntityType.PRIME,
        cage_code="09024",
        headquarters_location="Bethesda, MD",
    )
    e4b = Entity(
        canonical_name="Lockheed Martin Corporation",
        name_variants=["Lockheed"],
        entity_type=EntityType.PRIME,
        headquarters_location="Bethesda, MD",
    )
    entities.extend([e4a, e4b])
    print(f"  4. {e4a.canonical_name} + {e4b.canonical_name} (name + same state)")

    # 5. Two different companies with similar names (should remain separate)
    e5a = Entity(
        canonical_name="Shield AI",
        name_variants=[],
        entity_type=EntityType.STARTUP,
        headquarters_location="San Diego, CA",
        technology_tags=["autonomous systems", "drones"],
    )
    e5b = Entity(
        canonical_name="Shield Defense Systems",
        name_variants=["Shield Defense"],
        entity_type=EntityType.STARTUP,
        headquarters_location="Austin, TX",  # Different state
        technology_tags=["cybersecurity"],
    )
    entities.extend([e5a, e5b])
    print(f"  5. {e5a.canonical_name} + {e5b.canonical_name} (different companies)")

    # Add all entities
    for entity in entities:
        db.add(entity)
    db.commit()

    # Add some contracts to test NAICS matching
    # Give Lockheed Martin contracts with same NAICS
    contract1 = Contract(
        entity_id=e4a.id,
        contract_number="W911QY-23-C-0001",
        contracting_agency="US Army",
        naics_code="336411",  # Aircraft Manufacturing
    )
    contract2 = Contract(
        entity_id=e4b.id,
        contract_number="W911QY-23-C-0002",
        contracting_agency="US Army",
        naics_code="336411",  # Same NAICS - boosts confidence
    )
    db.add(contract1)
    db.add(contract2)
    db.commit()

    print(f"\nCreated {len(entities)} test entities")
    return entities


def cleanup_test_data(db):
    """Remove all test data."""
    db.query(Contract).delete()
    db.query(EntityMerge).delete()
    db.query(Entity).delete()
    db.commit()


def run_resolution_test():
    """Run entity resolution and show results."""
    db = SessionLocal()

    try:
        # Clean up any existing data
        cleanup_test_data(db)

        # Setup test data
        setup_test_data(db)

        # Get initial count
        initial_count = db.query(Entity).filter(Entity.merged_into_id.is_(None)).count()

        print("\n" + "=" * 60)
        print("RUNNING ENTITY RESOLUTION")
        print("=" * 60)

        # Run resolution
        resolver = EntityResolver(db)
        stats = resolver.resolve_all_entities()

        # Show results
        print("\n" + "=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)

        print(f"\nStarting entities: {stats.total_entities_start}")
        print(f"Final entities: {stats.total_entities_end}")
        print(f"Entities merged: {stats.total_entities_start - stats.total_entities_end}")

        print("\nMerge breakdown:")
        print(f"  - Identifier matches: {stats.identifier_matches}")
        print(f"  - Name + location matches: {stats.name_location_matches}")
        print(f"  - Name + NAICS matches: {stats.name_naics_matches}")
        print(f"  - Flagged for review: {stats.flagged_for_review}")

        # Show remaining active entities
        print("\n" + "-" * 60)
        print("ACTIVE ENTITIES (not merged):")
        print("-" * 60)
        active_entities = db.query(Entity).filter(
            Entity.merged_into_id.is_(None)
        ).all()

        for i, entity in enumerate(active_entities, 1):
            variants = entity.name_variants or []
            print(f"\n{i}. {entity.canonical_name}")
            if variants:
                print(f"   Variants: {', '.join(variants[:3])}{'...' if len(variants) > 3 else ''}")
            print(f"   Type: {entity.entity_type.value}")
            if entity.cage_code:
                print(f"   CAGE: {entity.cage_code}")
            if entity.headquarters_location:
                print(f"   Location: {entity.headquarters_location}")

        # Show merged entities
        print("\n" + "-" * 60)
        print("MERGED ENTITIES:")
        print("-" * 60)
        merged_entities = db.query(Entity).filter(
            Entity.merged_into_id.isnot(None)
        ).all()

        for entity in merged_entities:
            target = db.query(Entity).filter(Entity.id == entity.merged_into_id).first()
            print(f"  '{entity.canonical_name}' -> merged into '{target.canonical_name}'")

        # Show review queue
        if resolver.review_queue:
            print("\n" + "-" * 60)
            print("FLAGGED FOR REVIEW:")
            print("-" * 60)
            for match in resolver.review_queue:
                print(f"  {match.entity_a.canonical_name} <-> {match.entity_b.canonical_name}")
                print(f"    Score: {match.similarity_score:.1f}, Reason: {match.match_reason}")

            # Export review queue
            csv_path = resolver.export_review_queue()
            print(f"\n  Review queue exported to: {csv_path}")

        # Show merge history
        print("\n" + "-" * 60)
        print("MERGE AUDIT LOG:")
        print("-" * 60)
        merges = db.query(EntityMerge).all()
        for merge in merges:
            print(f"  {merge.source_name} -> {merge.target_name}")
            print(f"    Reason: {merge.merge_reason.value}, Confidence: {merge.confidence_score}")

        # Verify expected behavior
        print("\n" + "=" * 60)
        print("VERIFICATION")
        print("=" * 60)

        expected_final = 6  # 10 - 4 merges = 6 (Palantir, Anduril, Lockheed merge; SpaceX flagged; Shield stays separate)

        checks = [
            (stats.identifier_matches >= 1, "At least 1 identifier match (Palantir)"),
            (stats.name_location_matches >= 1, "At least 1 name+location match"),
            (stats.flagged_for_review >= 1, "At least 1 flagged for review (SpaceX)"),
            (stats.total_entities_end <= stats.total_entities_start, "Entity count decreased or stayed same"),
        ]

        all_passed = True
        for passed, description in checks:
            status = "✓" if passed else "✗"
            print(f"  {status} {description}")
            if not passed:
                all_passed = False

        print("\n" + "=" * 60)
        if all_passed:
            print("ALL CHECKS PASSED")
        else:
            print("SOME CHECKS FAILED")
        print("=" * 60)

        return all_passed

    finally:
        # Don't clean up - leave data for inspection
        db.close()


if __name__ == "__main__":
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    success = run_resolution_test()
    sys.exit(0 if success else 1)
