#!/usr/bin/env python3
"""
Tests for the entity resolution module.
"""

import sys
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal, init_db
from processing.models import Entity, EntityType
from processing.entity_resolution import (
    EntityResolver,
    IdentifierMatcher,
    FuzzyNameMatcher,
    MatchType,
)
from processing.entity_resolution.resolver import EntityMerger, ResolverConfig


def setup_test_data(db):
    """Create test entities."""
    entities = [
        Entity(
            canonical_name="Anduril Industries",
            name_variants=["Anduril", "Anduril Industries Inc"],
            entity_type=EntityType.STARTUP,
            cage_code="8GNK6",
            duns_number="080250721",
            headquarters_location="Costa Mesa, CA",
            founded_date=date(2017, 1, 1),
            technology_tags=["autonomous systems", "computer vision", "defense AI"],
        ),
        Entity(
            canonical_name="Palantir Technologies",
            name_variants=["Palantir", "Palantir Tech"],
            entity_type=EntityType.STARTUP,
            cage_code="4CYR7",
            duns_number="831211268",
            headquarters_location="Denver, CO",
            technology_tags=["data analytics", "AI", "government"],
        ),
        Entity(
            canonical_name="Lockheed Martin Corporation",
            name_variants=["Lockheed Martin", "Lockheed", "LMT"],
            entity_type=EntityType.PRIME,
            cage_code="09024",
            duns_number="103695338",
            headquarters_location="Bethesda, MD",
            technology_tags=["aerospace", "defense", "missiles"],
        ),
        Entity(
            canonical_name="Andreessen Horowitz",
            name_variants=["a16z", "AH"],
            entity_type=EntityType.INVESTOR,
            headquarters_location="Menlo Park, CA",
            technology_tags=["venture capital", "defense tech"],
        ),
    ]

    for entity in entities:
        db.add(entity)
    db.commit()
    return entities


def cleanup_test_data(db):
    """Remove all test entities."""
    db.query(Entity).delete()
    db.commit()


def test_identifier_matching():
    """Test identifier-based matching."""
    print("\n=== IDENTIFIER MATCHING TESTS ===\n")
    db = SessionLocal()

    try:
        cleanup_test_data(db)
        setup_test_data(db)

        matcher = IdentifierMatcher(db)

        # Test CAGE code match
        result = matcher.match(cage_code="8GNK6")
        assert result.is_match, "Should match by CAGE code"
        assert result.entity.canonical_name == "Anduril Industries"
        assert result.confidence == 1.0
        assert result.match_type == MatchType.EXACT_IDENTIFIER
        print("✓ CAGE code matching works")

        # Test DUNS match
        result = matcher.match(duns_number="831211268")
        assert result.is_match, "Should match by DUNS"
        assert result.entity.canonical_name == "Palantir Technologies"
        print("✓ DUNS number matching works")

        # Test with dashes in DUNS
        result = matcher.match(duns_number="103-695-338")
        assert result.is_match, "Should normalize DUNS with dashes"
        assert result.entity.canonical_name == "Lockheed Martin Corporation"
        print("✓ DUNS normalization works")

        # Test no match
        result = matcher.match(cage_code="XXXXX")
        assert not result.is_match, "Should not match invalid CAGE"
        print("✓ No false positives for invalid identifiers")

        print("\nAll identifier matching tests passed!")
        return True

    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        cleanup_test_data(db)
        db.close()


def test_fuzzy_name_matching():
    """Test fuzzy name matching."""
    print("\n=== FUZZY NAME MATCHING TESTS ===\n")
    db = SessionLocal()

    try:
        cleanup_test_data(db)
        setup_test_data(db)

        matcher = FuzzyNameMatcher(db, threshold=80)

        # Test exact name match
        result = matcher.match("Anduril Industries")
        assert result.is_match, "Should match exact name"
        assert result.entity.canonical_name == "Anduril Industries"
        print(f"✓ Exact name match (confidence: {result.confidence:.2f})")

        # Test name with suffix variations
        result = matcher.match("Anduril Industries, Inc.")
        assert result.is_match, "Should match with corporate suffix"
        assert result.entity.canonical_name == "Anduril Industries"
        print(f"✓ Corporate suffix normalization (confidence: {result.confidence:.2f})")

        # Test partial name
        result = matcher.match("Lockheed Martin")
        assert result.is_match, "Should match partial name"
        assert result.entity.canonical_name == "Lockheed Martin Corporation"
        print(f"✓ Partial name match (confidence: {result.confidence:.2f})")

        # Test case insensitivity
        result = matcher.match("PALANTIR TECHNOLOGIES")
        assert result.is_match, "Should be case insensitive"
        assert result.entity.canonical_name == "Palantir Technologies"
        print(f"✓ Case insensitive matching (confidence: {result.confidence:.2f})")

        # Test location boost
        result = matcher.match("Anduril Industries", location_hint="Costa Mesa")
        original_result = matcher.match("Anduril Industries")
        # Location should boost confidence slightly
        print(f"✓ Location hint matching (base: {original_result.confidence:.2f}, with location: {result.confidence:.2f})")

        # Test no match for completely different name
        result = matcher.match("XYZ Random Company That Doesn't Exist")
        assert not result.is_match, "Should not match unrelated name"
        print("✓ No false positives for unrelated names")

        print("\nAll fuzzy name matching tests passed!")
        return True

    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        cleanup_test_data(db)
        db.close()


def test_hybrid_resolver():
    """Test the hybrid entity resolver."""
    print("\n=== HYBRID RESOLVER TESTS ===\n")
    db = SessionLocal()

    try:
        cleanup_test_data(db)
        setup_test_data(db)

        config = ResolverConfig(
            auto_accept_threshold=0.90,
            match_threshold=0.70,
            fuzzy_threshold=80,
        )
        resolver = EntityResolver(db, config)

        # Test identifier takes priority
        result = resolver.resolve(
            name="Wrong Name Corp",  # Name doesn't match
            cage_code="8GNK6",  # But CAGE code does
        )
        assert result.is_match, "Identifier should override name"
        assert result.entity.canonical_name == "Anduril Industries"
        assert result.match_type == MatchType.EXACT_IDENTIFIER
        print("✓ Identifier matching takes priority over name")

        # Test falls back to fuzzy when no identifier
        result = resolver.resolve(
            name="Palantir Tech Inc.",
        )
        assert result.is_match, "Should fall back to fuzzy match"
        assert result.entity.canonical_name == "Palantir Technologies"
        print(f"✓ Falls back to fuzzy matching (confidence: {result.confidence:.2f})")

        # Test resolve_or_create with existing entity
        entity, created = resolver.resolve_or_create(
            name="Lockheed",
            entity_type=EntityType.PRIME,
        )
        assert not created, "Should find existing entity"
        assert entity.canonical_name == "Lockheed Martin Corporation"
        print("✓ resolve_or_create finds existing entities")

        # Test resolve_or_create with new entity
        entity, created = resolver.resolve_or_create(
            name="Shield AI",
            entity_type=EntityType.STARTUP,
            location="San Diego, CA",
            technology_tags=["autonomous systems", "drones"],
        )
        assert created, "Should create new entity"
        assert entity.canonical_name == "Shield AI"
        print("✓ resolve_or_create creates new entities when no match")

        # Verify the new entity can be found
        result = resolver.resolve(name="Shield AI")
        assert result.is_match
        print("✓ Newly created entity is findable")

        print("\nAll hybrid resolver tests passed!")
        return True

    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        cleanup_test_data(db)
        db.close()


def test_entity_merger():
    """Test entity merging functionality."""
    print("\n=== ENTITY MERGER TESTS ===\n")
    db = SessionLocal()

    try:
        cleanup_test_data(db)

        # Create two entities that should be merged
        primary = Entity(
            canonical_name="SpaceX",
            name_variants=["Space Exploration Technologies"],
            entity_type=EntityType.STARTUP,
            cage_code="1ABC2",
            headquarters_location="Hawthorne, CA",
            technology_tags=["rockets", "space"],
        )
        duplicate = Entity(
            canonical_name="Space Exploration Technologies Corp",
            name_variants=["SpaceX Corp"],
            entity_type=EntityType.STARTUP,
            duns_number="123456789",
            technology_tags=["space", "satellites"],
        )
        db.add(primary)
        db.add(duplicate)
        db.commit()

        merger = EntityMerger(db)
        merged = merger.merge(primary, duplicate)

        # Verify merge results
        assert merged.canonical_name == "SpaceX"
        assert "Space Exploration Technologies Corp" in merged.name_variants
        assert "SpaceX Corp" in merged.name_variants
        assert merged.cage_code == "1ABC2"
        assert merged.duns_number == "123456789"  # Filled from duplicate
        assert "satellites" in merged.technology_tags  # Merged tags
        print("✓ Entity merger combines data correctly")

        # Verify duplicate is deleted
        remaining = db.query(Entity).filter(
            Entity.canonical_name == "Space Exploration Technologies Corp"
        ).first()
        assert remaining is None, "Duplicate should be deleted"
        print("✓ Duplicate entity is removed after merge")

        print("\nAll entity merger tests passed!")
        return True

    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        cleanup_test_data(db)
        db.close()


def test_name_normalization():
    """Test name normalization edge cases."""
    print("\n=== NAME NORMALIZATION TESTS ===\n")
    db = SessionLocal()

    try:
        matcher = FuzzyNameMatcher(db, threshold=85)

        test_cases = [
            ("Acme Inc.", "ACME"),
            ("Acme, Inc.", "ACME"),
            ("Acme Corporation", "ACME"),
            ("Acme Corp", "ACME"),
            ("ACME LLC", "ACME"),
            ("Acme L.L.C.", "ACME"),
            ("The Acme Company", "THE ACME"),
            ("  Acme   Industries  ", "ACME INDUSTRIES"),
        ]

        for input_name, expected in test_cases:
            result = matcher._normalize_name(input_name)
            assert result == expected, f"'{input_name}' should normalize to '{expected}', got '{result}'"
            print(f"✓ '{input_name}' -> '{result}'")

        print("\nAll name normalization tests passed!")
        return True

    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    # Initialize database
    init_db()

    results = []
    results.append(("Identifier Matching", test_identifier_matching()))
    results.append(("Fuzzy Name Matching", test_fuzzy_name_matching()))
    results.append(("Hybrid Resolver", test_hybrid_resolver()))
    results.append(("Entity Merger", test_entity_merger()))
    results.append(("Name Normalization", test_name_normalization()))

    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "PASSED" if passed else "FAILED"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 50)
    print(f"Overall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")

    sys.exit(0 if all_passed else 1)
