#!/usr/bin/env python3
"""
Test script to verify database schema and basic operations.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect

from config.logging import logger
from processing.database import SessionLocal, engine
from processing.models import (
    Base,
    Contract,
    Entity,
    EntityType,
    FundingEvent,
    FundingEventType,
    Signal,
    SignalStatus,
)


def test_schema():
    """Verify all tables exist with correct columns."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    expected_tables = ["entities", "funding_events", "contracts", "signals", "alembic_version"]

    print("\n=== DATABASE SCHEMA VERIFICATION ===\n")
    print(f"Database: {engine.url}")
    print(f"\nTables found: {len(tables)}")

    for table in expected_tables:
        if table in tables:
            print(f"  ✓ {table}")
            columns = inspector.get_columns(table)
            for col in columns:
                print(f"      - {col['name']}: {col['type']}")
        else:
            print(f"  ✗ {table} (MISSING)")

    return all(t in tables for t in expected_tables)


def test_crud_operations():
    """Test basic CRUD operations."""
    print("\n=== CRUD OPERATIONS TEST ===\n")

    db = SessionLocal()
    try:
        # Create test entity
        test_entity = Entity(
            canonical_name="Anduril Industries",
            name_variants=["Anduril", "Anduril Industries Inc", "Anduril Industries, Inc."],
            entity_type=EntityType.STARTUP,
            cage_code="8GNK6",
            headquarters_location="Costa Mesa, CA",
            founded_date=date(2017, 1, 1),
            technology_tags=["autonomous systems", "computer vision", "defense AI"],
        )
        db.add(test_entity)
        db.commit()
        db.refresh(test_entity)
        print(f"✓ Created entity: {test_entity}")

        # Create funding event
        funding = FundingEvent(
            entity_id=test_entity.id,
            event_type=FundingEventType.VC_ROUND,
            amount=Decimal("1500000000.00"),
            event_date=date(2022, 12, 1),
            source="Crunchbase",
            investors_awarders=["Andreessen Horowitz", "8VC", "Founders Fund"],
            round_stage="Series E",
        )
        db.add(funding)
        db.commit()
        print(f"✓ Created funding event: {funding}")

        # Create contract
        contract = Contract(
            entity_id=test_entity.id,
            contract_number="W911QY-23-C-0001",
            contracting_agency="US Army",
            contract_value=Decimal("250000000.00"),
            award_date=date(2023, 3, 15),
            naics_code="334511",
            psc_code="1550",
            place_of_performance="Costa Mesa, CA",
            contract_type="IDIQ",
        )
        db.add(contract)
        db.commit()
        print(f"✓ Created contract: {contract}")

        # Create signal
        signal = Signal(
            entity_id=test_entity.id,
            signal_type="rapid_growth",
            confidence_score=Decimal("0.92"),
            detected_date=date.today(),
            evidence={
                "funding_velocity": "3 rounds in 18 months",
                "contract_growth": "150% YoY",
            },
            status=SignalStatus.ACTIVE,
        )
        db.add(signal)
        db.commit()
        print(f"✓ Created signal: {signal}")

        # Query back
        entity = db.query(Entity).filter(Entity.canonical_name == "Anduril Industries").first()
        print(f"\n✓ Retrieved entity with {len(entity.funding_events)} funding events, {len(entity.contracts)} contracts, {len(entity.signals)} signals")

        # Cleanup test data
        db.delete(entity)
        db.commit()
        print("✓ Cleaned up test data")

        return True

    except Exception as e:
        logger.error(f"CRUD test failed: {e}")
        db.rollback()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    schema_ok = test_schema()
    crud_ok = test_crud_operations()

    print("\n=== TEST RESULTS ===")
    print(f"Schema verification: {'PASSED' if schema_ok else 'FAILED'}")
    print(f"CRUD operations: {'PASSED' if crud_ok else 'FAILED'}")

    sys.exit(0 if (schema_ok and crud_ok) else 1)
