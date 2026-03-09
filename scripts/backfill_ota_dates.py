#!/usr/bin/env python3
"""
Backfill NULL award_dates on OTA contracts from their raw_data JSON.

75% of OTA contracts (569/762) have NULL award_dates despite raw_data
containing valid dateSigned values. This script extracts the date from
the nested JSON and patches the award_date column.

Usage:
    python scripts/backfill_ota_dates.py            # Preview changes
    python scripts/backfill_ota_dates.py --commit    # Apply changes
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Contract, ProcurementType


def safe_get(data, *keys, default=None):
    """Safely navigate nested dict keys."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
        if current is None:
            return default
    return current


def parse_date(date_str):
    """Parse date string from SAM.gov raw_data."""
    if not date_str:
        return None
    cleaned = date_str.strip().replace("Z", "")
    try:
        return datetime.fromisoformat(cleaned).date()
    except (ValueError, TypeError):
        pass
    for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"]:
        try:
            return datetime.strptime(cleaned[:max(10, len(cleaned))], fmt).date()
        except ValueError:
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description="Backfill OTA award_dates from raw_data")
    parser.add_argument("--commit", action="store_true", help="Apply changes (default: preview only)")
    args = parser.parse_args()

    db = SessionLocal()

    # Find OTA contracts with NULL award_date but non-NULL raw_data
    null_dates = (
        db.query(Contract)
        .filter(
            Contract.procurement_type == ProcurementType.OTA.value,
            Contract.award_date.is_(None),
            Contract.raw_data.isnot(None),
        )
        .all()
    )

    print(f"OTA contracts with NULL award_date: {len(null_dates)}")

    fixed = 0
    no_date_in_raw = 0

    for contract in null_dates:
        raw = contract.raw_data
        if not isinstance(raw, dict):
            continue

        # Try nested path: awardDetails.dates.dateSigned
        date_str = safe_get(raw, "awardDetails", "dates", "dateSigned")

        if not date_str:
            # Fallback: try top-level dateSigned
            date_str = raw.get("dateSigned")

        parsed = parse_date(date_str)

        if parsed:
            if args.commit:
                contract.award_date = parsed
            fixed += 1
            if fixed <= 10:
                print(f"  {contract.contract_number}: {date_str} -> {parsed}")
        else:
            no_date_in_raw += 1

    print(f"\nResults:")
    print(f"  Fixable (date found in raw_data): {fixed}")
    print(f"  No date in raw_data: {no_date_in_raw}")
    print(f"  Remaining NULL: {len(null_dates) - fixed}")

    if args.commit:
        db.commit()
        print(f"\nCommitted {fixed} award_date updates.")
    else:
        print(f"\nDry run — use --commit to apply changes.")

    db.close()


if __name__ == "__main__":
    main()
