#!/usr/bin/env python3
"""Create fund system tables in the database.

Uses Base.metadata.create_all() scoped to fund tables only.
Safe to run multiple times — only creates tables that don't exist.

Usage:
    python Fund/create_fund_tables.py
"""

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import create_engine, inspect
from config.settings import settings
from processing.models import (
    Base, FundStrategy, FundCohort, FundPosition, FundMilestone,
)

FUND_TABLES = [
    FundStrategy.__tablename__,
    FundCohort.__tablename__,
    FundPosition.__tablename__,
    FundMilestone.__tablename__,
]


def main():
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    existing = inspector.get_table_names()

    new_tables = [t for t in FUND_TABLES if t not in existing]

    if not new_tables:
        print("All fund tables already exist:")
        for t in FUND_TABLES:
            print(f"  {t}")
        return

    print("Creating fund tables...")
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables[t]
            for t in FUND_TABLES
            if t not in existing
        ],
    )

    # Verify
    inspector = inspect(engine)
    for t in FUND_TABLES:
        if t in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns(t)]
            print(f"  {t}: {len(cols)} columns")
        else:
            print(f"  {t}: FAILED TO CREATE")

    print("Done.")


if __name__ == "__main__":
    main()
