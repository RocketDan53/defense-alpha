#!/usr/bin/env python3
"""
Backfill Deliveries — Register existing reports as deliveries.

Parses entity names from report filenames, looks up entity_id,
and creates report_deliveries rows with file mtime as delivered_at.

Usage:
    python scripts/backfill_deliveries.py
    python scripts/backfill_deliveries.py --dry-run
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

# Map known report files to their entity names and types
KNOWN_REPORTS = [
    {
        "file": "rf_comms_v2.md",
        "entity_hint": None,
        "report_type": "sector_report",
        "slug": "rf_comms_v2",
    },
    {
        "file": "phase2_signal_report.md",
        "entity_hint": None,
        "report_type": "signal_report",
        "slug": "phase2_signal_report",
    },
    {
        "file": "Finished Reports/brief_scout_space.md",
        "entity_hint": "Scout Space",
        "report_type": "deal_brief",
        "slug": "brief_scout_space",
    },
    {
        "file": "Finished Reports/brief_starfish_space.md",
        "entity_hint": "Starfish Space",
        "report_type": "deal_brief",
        "slug": "brief_starfish_space",
    },
    {
        "file": "Finished Reports/brief_firestorm_labs_final.md",
        "entity_hint": "Firestorm",
        "report_type": "deal_brief",
        "slug": "brief_firestorm_labs",
    },
    {
        "file": "investor_leads_antijam_gps.md",
        "entity_hint": None,
        "report_type": "investor_list",
        "slug": "investor_leads_antijam_gps",
    },
    {
        "file": "investor_targets_antijam_gps.md",
        "entity_hint": None,
        "report_type": "investor_list",
        "slug": "investor_targets_antijam_gps",
    },
]


def _db_path() -> str:
    url = settings.DATABASE_URL
    return url.replace("sqlite:///", "")


def lookup_entity_id(conn: sqlite3.Connection, name: str) -> str | None:
    """Find entity_id by name (case-insensitive, partial match)."""
    row = conn.execute(
        "SELECT id FROM entities WHERE canonical_name LIKE ? AND merged_into_id IS NULL LIMIT 1",
        (f"%{name}%",),
    ).fetchone()
    return row[0] if row else None


def main():
    parser = argparse.ArgumentParser(description="Backfill report deliveries")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be inserted")
    args = parser.parse_args()

    conn = sqlite3.connect(_db_path())
    inserted = 0

    for report in KNOWN_REPORTS:
        filepath = REPORTS_DIR / report["file"]
        if not filepath.exists():
            print(f"  SKIP (not found): {report['file']}")
            continue

        # Get file modification time as delivered_at
        mtime = os.path.getmtime(filepath)
        delivered_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Look up entity_id if we have a hint
        entity_id = None
        if report["entity_hint"]:
            entity_id = lookup_entity_id(conn, report["entity_hint"])
            if not entity_id:
                print(f"  SKIP (entity not found): {report['entity_hint']} for {report['file']}")
                continue

        # Check for existing delivery
        existing = conn.execute(
            "SELECT id FROM report_deliveries WHERE report_slug = ?",
            (report["slug"],),
        ).fetchone()
        if existing:
            print(f"  SKIP (already exists): {report['slug']}")
            continue

        if args.dry_run:
            print(f"  WOULD INSERT: {report['slug']} (entity={entity_id}, delivered={delivered_at})")
        else:
            # For sector/signal reports without a specific entity, use a placeholder
            if not entity_id:
                # Use first active entity as placeholder (these are portfolio-wide reports)
                row = conn.execute(
                    "SELECT id FROM entities WHERE merged_into_id IS NULL LIMIT 1"
                ).fetchone()
                entity_id = row[0] if row else None

            if entity_id:
                conn.execute(
                    "INSERT INTO report_deliveries (id, entity_id, report_type, report_slug, delivered_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), entity_id, report["report_type"], report["slug"], delivered_at),
                )
                inserted += 1
                print(f"  INSERTED: {report['slug']} (delivered {delivered_at})")

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\nBackfill complete: {inserted} deliveries inserted")


if __name__ == "__main__":
    main()
