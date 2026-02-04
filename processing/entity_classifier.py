#!/usr/bin/env python3
"""
Entity Classifier

Classifies entities into types based on contract data and name patterns.

Rules:
1. If company has >$500M total contracts → "prime"
2. If company name contains known primes → "prime"
3. If company has SBIR awards but <$50M contracts → "startup"
4. Default → "startup"

Usage:
    python -m processing.entity_classifier --dry-run
    python -m processing.entity_classifier
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Contract, Entity, EntityType, FundingEvent, FundingEventType


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# Known prime contractors (partial name matches, case-insensitive)
KNOWN_PRIMES = [
    "lockheed martin",
    "raytheon",
    "rtx",
    "northrop grumman",
    "general dynamics",
    "boeing",
    "bae systems",
    "l3harris",
    "l3 harris",
    "huntington ingalls",
    "leidos",
    "saic",
    "booz allen",
    "general atomics",
    "textron",
    "harris corporation",
    "perspecta",
    "mantech",
    "caci",
    "science applications international",
    "parsons",
    "jacobs engineering",
    "amentum",
    "kbr",
    "fluor",
    "sierra nevada",
    "anduril",
    "palantir",
]

# Contract value thresholds
PRIME_THRESHOLD = Decimal("500000000")  # $500M
STARTUP_MAX_THRESHOLD = Decimal("50000000")  # $50M


@dataclass
class ClassificationResult:
    """Result of entity classification."""
    entity_id: str
    entity_name: str
    old_type: EntityType
    new_type: EntityType
    reason: str
    total_contract_value: Optional[Decimal]
    has_sbir: bool


@dataclass
class ClassifierStats:
    """Statistics from classification run."""
    total_entities: int = 0
    classified_as_prime: int = 0
    classified_as_startup: int = 0
    unchanged: int = 0
    updated: int = 0


def is_known_prime(name: str) -> bool:
    """Check if entity name matches a known prime contractor."""
    name_lower = name.lower()
    return any(prime in name_lower for prime in KNOWN_PRIMES)


def get_total_contract_value(db: Session, entity_id: str) -> Decimal:
    """Get total contract value for an entity."""
    result = db.query(func.sum(Contract.contract_value)).filter(
        Contract.entity_id == entity_id
    ).scalar()
    return result or Decimal("0")


def has_sbir_awards(db: Session, entity_id: str) -> bool:
    """Check if entity has any SBIR funding events."""
    sbir_types = [
        FundingEventType.SBIR_PHASE_1,
        FundingEventType.SBIR_PHASE_2,
        FundingEventType.SBIR_PHASE_3,
    ]
    count = db.query(FundingEvent).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type.in_(sbir_types),
    ).count()
    return count > 0


def classify_entity(db: Session, entity: Entity) -> ClassificationResult:
    """
    Classify a single entity based on rules.

    Rules (in order of priority):
    1. Known prime name → PRIME
    2. >$500M contracts → PRIME
    3. SBIR awards and <$50M contracts → STARTUP
    4. Default → STARTUP
    """
    total_value = get_total_contract_value(db, entity.id)
    has_sbir = has_sbir_awards(db, entity.id)

    # Rule 1: Known prime by name
    if is_known_prime(entity.canonical_name):
        return ClassificationResult(
            entity_id=entity.id,
            entity_name=entity.canonical_name,
            old_type=entity.entity_type,
            new_type=EntityType.PRIME,
            reason="known_prime_name",
            total_contract_value=total_value,
            has_sbir=has_sbir,
        )

    # Rule 2: High contract value
    if total_value >= PRIME_THRESHOLD:
        return ClassificationResult(
            entity_id=entity.id,
            entity_name=entity.canonical_name,
            old_type=entity.entity_type,
            new_type=EntityType.PRIME,
            reason=f"contract_value_over_500M (${total_value:,.0f})",
            total_contract_value=total_value,
            has_sbir=has_sbir,
        )

    # Rule 3: SBIR with low contracts (classic startup pattern)
    if has_sbir and total_value < STARTUP_MAX_THRESHOLD:
        return ClassificationResult(
            entity_id=entity.id,
            entity_name=entity.canonical_name,
            old_type=entity.entity_type,
            new_type=EntityType.STARTUP,
            reason="sbir_awards_under_50M",
            total_contract_value=total_value,
            has_sbir=has_sbir,
        )

    # Rule 4: Default to startup
    return ClassificationResult(
        entity_id=entity.id,
        entity_name=entity.canonical_name,
        old_type=entity.entity_type,
        new_type=EntityType.STARTUP,
        reason="default",
        total_contract_value=total_value,
        has_sbir=has_sbir,
    )


def run_classification(db: Session, dry_run: bool = False) -> ClassifierStats:
    """
    Run classification on all active entities.

    Args:
        db: Database session
        dry_run: If True, don't commit changes

    Returns:
        ClassifierStats with results
    """
    stats = ClassifierStats()

    # Get all active entities (not merged)
    entities = db.query(Entity).filter(Entity.merged_into_id.is_(None)).all()
    stats.total_entities = len(entities)

    logger.info("=" * 60)
    logger.info("ENTITY CLASSIFIER")
    logger.info("=" * 60)
    logger.info(f"Total entities: {stats.total_entities}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 60)

    primes = []
    startups = []

    for entity in entities:
        result = classify_entity(db, entity)

        if result.new_type == EntityType.PRIME:
            stats.classified_as_prime += 1
            primes.append(result)
        else:
            stats.classified_as_startup += 1
            startups.append(result)

        # Check if type changed
        if result.old_type != result.new_type:
            stats.updated += 1
            if not dry_run:
                entity.entity_type = result.new_type
        else:
            stats.unchanged += 1

    # Log primes found
    logger.info("")
    logger.info(f"PRIMES IDENTIFIED ({stats.classified_as_prime}):")
    logger.info("-" * 60)
    for result in sorted(primes, key=lambda x: x.total_contract_value or 0, reverse=True):
        value_str = f"${result.total_contract_value:,.0f}" if result.total_contract_value else "$0"
        logger.info(f"  {result.entity_name[:45]:<45} | {value_str:>15} | {result.reason}")

    # Log some startup examples
    logger.info("")
    logger.info(f"STARTUPS ({stats.classified_as_startup}):")
    logger.info("-" * 60)
    sbir_startups = [s for s in startups if s.has_sbir]
    logger.info(f"  With SBIR awards: {len(sbir_startups)}")
    logger.info(f"  Without SBIR: {len(startups) - len(sbir_startups)}")

    if not dry_run:
        db.commit()
        logger.info("")
        logger.info("Changes committed to database.")
    else:
        logger.info("")
        logger.info("DRY RUN - no changes made.")

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total entities: {stats.total_entities}")
    logger.info(f"Classified as PRIME: {stats.classified_as_prime}")
    logger.info(f"Classified as STARTUP: {stats.classified_as_startup}")
    logger.info(f"Type changed: {stats.updated}")
    logger.info(f"Type unchanged: {stats.unchanged}")
    logger.info("=" * 60)

    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Classify entities into types (prime, startup, etc.)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be classified without making changes",
    )

    args = parser.parse_args()

    db = SessionLocal()

    try:
        run_classification(db, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
