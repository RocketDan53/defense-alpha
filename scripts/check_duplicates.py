#!/usr/bin/env python3
"""
Duplicate Entity Diagnostic Script

Finds potential duplicate entities that may have been missed by entity resolution.
Groups entities by normalized name and shows what data each has.

Usage:
    python scripts/check_duplicates.py
    python scripts/check_duplicates.py --threshold 80
    python scripts/check_duplicates.py --min-group-size 3
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Entity, Contract, FundingEvent

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print("Warning: rapidfuzz not installed, using exact matching only")


# Corporate suffixes to normalize
CORPORATE_SUFFIXES = [
    r'\s+incorporated$',
    r'\s+inc\.?$',
    r'\s+llc\.?$',
    r'\s+l\.l\.c\.?$',
    r'\s+ltd\.?$',
    r'\s+limited$',
    r'\s+corp\.?$',
    r'\s+corporation$',
    r'\s+co\.?$',
    r'\s+company$',
    r'\s+lp\.?$',
    r'\s+l\.p\.?$',
    r'\s+plc\.?$',
    r'\s+pllc\.?$',
    r'\s+pc\.?$',
    r'\s+p\.c\.?$',
    r',?\s*llc\.?$',
    r',?\s*inc\.?$',
]


def normalize_name(name: str) -> str:
    """Normalize company name for comparison."""
    if not name:
        return ""

    # Lowercase
    normalized = name.lower().strip()

    # Remove corporate suffixes
    for suffix in CORPORATE_SUFFIXES:
        normalized = re.sub(suffix, '', normalized, flags=re.IGNORECASE)

    # Remove extra whitespace
    normalized = ' '.join(normalized.split())

    # Remove common punctuation
    normalized = re.sub(r'[,\.\-\'\"&]', ' ', normalized)
    normalized = ' '.join(normalized.split())

    return normalized


def get_entity_stats(db, entity_id: str) -> dict:
    """Get statistics for an entity."""
    contract_count = db.query(Contract).filter(Contract.entity_id == entity_id).count()

    sbir_count = db.query(FundingEvent).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.source.like('sbir:%')
    ).count()

    other_funding = db.query(FundingEvent).filter(
        FundingEvent.entity_id == entity_id,
        ~FundingEvent.source.like('sbir:%')
    ).count()

    return {
        'contracts': contract_count,
        'sbir_awards': sbir_count,
        'other_funding': other_funding,
    }


def find_exact_duplicates(db) -> list:
    """Find entities with exactly matching normalized names."""
    entities = db.query(Entity).filter(Entity.merged_into_id.is_(None)).all()

    # Group by normalized name
    name_groups = defaultdict(list)
    for entity in entities:
        normalized = normalize_name(entity.canonical_name)
        if normalized:
            name_groups[normalized].append(entity)

    # Filter to groups with multiple entities
    duplicates = []
    for normalized_name, group in name_groups.items():
        if len(group) > 1:
            duplicates.append({
                'normalized_name': normalized_name,
                'entities': group,
            })

    return duplicates


def find_fuzzy_duplicates(db, threshold: int = 85) -> list:
    """Find entities with similar (but not exact) names using fuzzy matching."""
    if not HAS_RAPIDFUZZ:
        return []

    entities = db.query(Entity).filter(Entity.merged_into_id.is_(None)).all()

    # Build list of (entity, normalized_name) tuples
    entity_names = [(e, normalize_name(e.canonical_name)) for e in entities]
    entity_names = [(e, n) for e, n in entity_names if n]  # Filter empty

    # Find similar pairs
    seen_pairs = set()
    similar_groups = defaultdict(set)

    print(f"Checking {len(entity_names)} entities for fuzzy matches (threshold={threshold})...")

    for i, (entity1, name1) in enumerate(entity_names):
        if i % 500 == 0 and i > 0:
            print(f"  Progress: {i}/{len(entity_names)}")

        for j, (entity2, name2) in enumerate(entity_names[i+1:], i+1):
            # Skip if already processed
            pair_key = tuple(sorted([entity1.id, entity2.id]))
            if pair_key in seen_pairs:
                continue

            # Calculate similarity
            similarity = fuzz.token_sort_ratio(name1, name2)

            if similarity >= threshold:
                seen_pairs.add(pair_key)
                # Group similar entities together
                group_key = min(entity1.id, entity2.id)
                similar_groups[group_key].add((entity1, similarity))
                similar_groups[group_key].add((entity2, similarity))

    # Convert to list format
    duplicates = []
    processed_entities = set()

    for group_key, entity_set in similar_groups.items():
        group_entities = [e for e, _ in entity_set]

        # Skip if all entities already processed
        if all(e.id in processed_entities for e in group_entities):
            continue

        for e in group_entities:
            processed_entities.add(e.id)

        duplicates.append({
            'entities': group_entities,
            'match_type': 'fuzzy',
        })

    return duplicates


def print_duplicate_group(db, group: dict, group_num: int):
    """Print details about a potential duplicate group."""
    entities = group['entities']
    match_type = group.get('match_type', 'exact')
    normalized = group.get('normalized_name', '')

    print(f"\n{'='*70}")
    print(f"Potential Duplicate Group #{group_num} ({match_type} match)")
    if normalized:
        print(f"Normalized name: '{normalized}'")
    print(f"{'='*70}")

    for entity in entities:
        stats = get_entity_stats(db, entity.id)

        # Get identifiers
        identifiers = []
        if entity.duns_number:
            identifiers.append(f"DUNS: {entity.duns_number}")
        if entity.cage_code:
            identifiers.append(f"CAGE: {entity.cage_code}")
        if entity.ein:
            identifiers.append(f"EIN: {entity.ein}")

        id_str = ", ".join(identifiers) if identifiers else "No identifiers"

        print(f"\n  Entity {entity.id[:8]}...")
        print(f"    Name: \"{entity.canonical_name}\"")
        print(f"    Type: {entity.entity_type.value}")
        print(f"    Location: {entity.headquarters_location or 'Unknown'}")
        print(f"    Identifiers: {id_str}")
        print(f"    Data: {stats['contracts']} contracts, {stats['sbir_awards']} SBIR awards, {stats['other_funding']} other funding")

        if entity.technology_tags:
            print(f"    Tech tags: {', '.join(entity.technology_tags)}")

    # Calculate similarity if fuzzy
    if HAS_RAPIDFUZZ and len(entities) >= 2:
        name1 = normalize_name(entities[0].canonical_name)
        name2 = normalize_name(entities[1].canonical_name)
        similarity = fuzz.token_sort_ratio(name1, name2)
        print(f"\n  Similarity: {similarity}%")

        # Recommendation
        if similarity >= 90:
            print("  Recommendation: LIKELY DUPLICATE - should merge")
        elif similarity >= 80:
            print("  Recommendation: POSSIBLE DUPLICATE - review manually")
        else:
            print("  Recommendation: UNCERTAIN - different companies?")


def main():
    parser = argparse.ArgumentParser(description="Find potential duplicate entities")
    parser.add_argument(
        "--threshold",
        type=int,
        default=80,
        help="Fuzzy match threshold (0-100, default: 80)",
    )
    parser.add_argument(
        "--min-group-size",
        type=int,
        default=2,
        help="Minimum entities in a duplicate group (default: 2)",
    )
    parser.add_argument(
        "--exact-only",
        action="store_true",
        help="Only check for exact matches (faster)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of duplicate groups to show (default: 20)",
    )

    args = parser.parse_args()

    db = SessionLocal()

    try:
        # Get total entity count
        total_entities = db.query(Entity).filter(Entity.merged_into_id.is_(None)).count()
        merged_entities = db.query(Entity).filter(Entity.merged_into_id.isnot(None)).count()

        print("="*70)
        print("DUPLICATE ENTITY DIAGNOSTIC")
        print("="*70)
        print(f"Total active entities: {total_entities}")
        print(f"Merged entities: {merged_entities}")
        print()

        # Find exact duplicates
        print("Checking for exact matches (normalized names)...")
        exact_duplicates = find_exact_duplicates(db)
        print(f"Found {len(exact_duplicates)} exact duplicate groups")

        # Find fuzzy duplicates
        fuzzy_duplicates = []
        if not args.exact_only and HAS_RAPIDFUZZ:
            print()
            fuzzy_duplicates = find_fuzzy_duplicates(db, threshold=args.threshold)
            print(f"Found {len(fuzzy_duplicates)} fuzzy duplicate groups")

        # Combine and sort by group size
        all_duplicates = exact_duplicates + fuzzy_duplicates
        all_duplicates = [d for d in all_duplicates if len(d['entities']) >= args.min_group_size]
        all_duplicates.sort(key=lambda x: len(x['entities']), reverse=True)

        if not all_duplicates:
            print("\n" + "="*70)
            print("NO POTENTIAL DUPLICATES FOUND")
            print("="*70)
            print("Entity resolution appears to be working correctly.")
            return

        print(f"\n{'='*70}")
        print(f"FOUND {len(all_duplicates)} POTENTIAL DUPLICATE GROUPS")
        print(f"{'='*70}")

        # Print details for each group
        for i, group in enumerate(all_duplicates[:args.limit], 1):
            print_duplicate_group(db, group, i)

        if len(all_duplicates) > args.limit:
            print(f"\n... and {len(all_duplicates) - args.limit} more groups (use --limit to see more)")

        # Summary
        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        print(f"Exact match groups: {len(exact_duplicates)}")
        print(f"Fuzzy match groups: {len(fuzzy_duplicates)}")
        print(f"Total entities in duplicate groups: {sum(len(d['entities']) for d in all_duplicates)}")

        # Actionable next steps
        print(f"\n{'='*70}")
        print("NEXT STEPS")
        print(f"{'='*70}")
        print("1. Review the duplicate groups above")
        print("2. Run entity resolution to merge duplicates:")
        print("   python scripts/run_entity_resolution.py")
        print("3. For manual review, export to CSV:")
        print("   python scripts/run_entity_resolution.py --export-only")
        print("4. Check data/review_queue.csv for ambiguous cases")

    finally:
        db.close()


if __name__ == "__main__":
    main()
