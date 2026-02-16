#!/usr/bin/env python3
"""
Materialize company → agency relationship data.

Aggregates contract and SBIR funding data to create per-company agency profiles
with dollar volumes, counts, and temporal coverage. Enables queries like:
  - "Which 5 companies have the deepest Air Force relationship?"
  - "Did Space Force establishment shift which agencies space companies work with?"

Usage:
    python scripts/materialize_agencies.py                  # Display summary
    python scripts/materialize_agencies.py --save           # Save to JSON
    python scripts/materialize_agencies.py --entity "Anduril"  # Show single entity
    python scripts/materialize_agencies.py --agency "Air Force" # Show agency portfolio
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func, text

from processing.database import SessionLocal
from processing.models import Contract, Entity, FundingEvent, FundingEventType

PROJECT_ROOT = Path(__file__).parent.parent

# Agency name normalization map
AGENCY_NORMALIZE = {
    "dept of the air force": "Air Force",
    "department of the air force": "Air Force",
    "air force": "Air Force",
    "dept of the army": "Army",
    "department of the army": "Army",
    "army": "Army",
    "dept of the navy": "Navy",
    "department of the navy": "Navy",
    "navy": "Navy",
    "defense advanced research projects agency": "DARPA",
    "darpa": "DARPA",
    "missile defense agency": "MDA",
    "mda": "MDA",
    "defense logistics agency": "DLA",
    "dla": "DLA",
    "defense threat reduction agency": "DTRA",
    "dtra": "DTRA",
    "national geospatial-intelligence agency": "NGA",
    "nga": "NGA",
    "national security agency": "NSA",
    "nsa": "NSA",
    "special operations command": "SOCOM",
    "us special operations command": "SOCOM",
    "socom": "SOCOM",
    "space force": "Space Force",
    "united states space force": "Space Force",
    "office of the secretary of defense": "OSD",
    "osd": "OSD",
    "defense information systems agency": "DISA",
    "disa": "DISA",
    "defense intelligence agency": "DIA",
    "dia": "DIA",
    "department of homeland security": "DHS",
    "dhs": "DHS",
    "customs and border protection": "CBP",
    "cbp": "CBP",
    "national aeronautics and space administration": "NASA",
    "nasa": "NASA",
    "department of energy": "DOE",
    "doe": "DOE",
}


def normalize_agency(name: str) -> str:
    """Normalize agency name to standard abbreviation."""
    if not name:
        return "Unknown"
    lower = name.strip().lower()
    # Try direct match
    if lower in AGENCY_NORMALIZE:
        return AGENCY_NORMALIZE[lower]
    # Try substring match
    for pattern, normalized in AGENCY_NORMALIZE.items():
        if pattern in lower:
            return normalized
    # Return cleaned-up original
    return name.strip().title()


def materialize_agency_relationships(db) -> dict:
    """
    Build company → agency relationship profiles from contracts and SBIR awards.

    Returns:
        {
            entity_id: {
                "entity_name": str,
                "entity_type": str,
                "agencies": {
                    "Air Force": {
                        "contract_count": int,
                        "contract_value": float,
                        "sbir_count": int,
                        "sbir_value": float,
                        "total_value": float,
                        "first_date": str,
                        "last_date": str,
                    },
                    ...
                },
                "primary_agency": str,
                "agency_count": int,
            }
        }
    """
    entity_profiles = {}

    # 1. Get contract-based agency relationships
    print("Loading contract → agency relationships...")
    contract_rows = db.execute(text("""
        SELECT
            c.entity_id,
            e.canonical_name,
            e.entity_type,
            c.contracting_agency,
            COUNT(*) as contract_count,
            COALESCE(SUM(c.contract_value), 0) as total_value,
            MIN(c.award_date) as first_date,
            MAX(c.award_date) as last_date
        FROM contracts c
        JOIN entities e ON c.entity_id = e.id
        WHERE e.merged_into_id IS NULL
          AND c.contracting_agency IS NOT NULL
        GROUP BY c.entity_id, c.contracting_agency
    """)).fetchall()

    for row in contract_rows:
        entity_id, entity_name, entity_type, agency, count, value, first_dt, last_dt = row
        agency_norm = normalize_agency(agency)

        if entity_id not in entity_profiles:
            entity_profiles[entity_id] = {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "agencies": {},
            }

        if agency_norm not in entity_profiles[entity_id]["agencies"]:
            entity_profiles[entity_id]["agencies"][agency_norm] = {
                "contract_count": 0, "contract_value": 0,
                "sbir_count": 0, "sbir_value": 0,
                "total_value": 0,
                "first_date": None, "last_date": None,
            }

        profile = entity_profiles[entity_id]["agencies"][agency_norm]
        profile["contract_count"] = count
        profile["contract_value"] = float(value)
        profile["total_value"] += float(value)
        profile["first_date"] = str(first_dt) if first_dt else None
        profile["last_date"] = str(last_dt) if last_dt else None

    print(f"  {len(contract_rows)} contract → agency relationships loaded")

    # 2. Get SBIR-based agency relationships
    print("Loading SBIR → agency relationships...")
    sbir_rows = db.execute(text("""
        SELECT
            fe.entity_id,
            e.canonical_name,
            e.entity_type,
            fe.investors_awarders,
            COUNT(*) as sbir_count,
            COALESCE(SUM(fe.amount), 0) as total_value,
            MIN(fe.event_date) as first_date,
            MAX(fe.event_date) as last_date
        FROM funding_events fe
        JOIN entities e ON fe.entity_id = e.id
        WHERE e.merged_into_id IS NULL
          AND fe.event_type IN ('SBIR_PHASE_1', 'SBIR_PHASE_2', 'SBIR_PHASE_3')
          AND fe.investors_awarders IS NOT NULL
        GROUP BY fe.entity_id, fe.investors_awarders
    """)).fetchall()

    for row in sbir_rows:
        entity_id, entity_name, entity_type, awarders_json, count, value, first_dt, last_dt = row

        # Parse awarders (stored as JSON array)
        try:
            awarders = json.loads(awarders_json) if isinstance(awarders_json, str) else awarders_json or []
        except (json.JSONDecodeError, TypeError):
            awarders = []

        if not awarders:
            continue

        if entity_id not in entity_profiles:
            entity_profiles[entity_id] = {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "agencies": {},
            }

        for awarder in awarders:
            if not isinstance(awarder, str):
                continue
            agency_norm = normalize_agency(awarder)

            if agency_norm not in entity_profiles[entity_id]["agencies"]:
                entity_profiles[entity_id]["agencies"][agency_norm] = {
                    "contract_count": 0, "contract_value": 0,
                    "sbir_count": 0, "sbir_value": 0,
                    "total_value": 0,
                    "first_date": None, "last_date": None,
                }

            profile = entity_profiles[entity_id]["agencies"][agency_norm]
            profile["sbir_count"] += count
            profile["sbir_value"] += float(value)
            profile["total_value"] += float(value)
            if first_dt and (not profile["first_date"] or str(first_dt) < profile["first_date"]):
                profile["first_date"] = str(first_dt)
            if last_dt and (not profile["last_date"] or str(last_dt) > profile["last_date"]):
                profile["last_date"] = str(last_dt)

    print(f"  {len(sbir_rows)} SBIR → agency relationships loaded")

    # 3. Compute derived fields
    for eid, profile in entity_profiles.items():
        agencies = profile["agencies"]
        if agencies:
            primary = max(agencies.items(), key=lambda x: x[1]["total_value"])
            profile["primary_agency"] = primary[0]
            profile["agency_count"] = len(agencies)
        else:
            profile["primary_agency"] = None
            profile["agency_count"] = 0

    print(f"\n  Total entities with agency relationships: {len(entity_profiles):,}")
    return entity_profiles


def print_agency_summary(profiles: dict):
    """Print agency-level summary statistics."""
    # Aggregate by agency
    agency_stats = defaultdict(lambda: {
        "company_count": 0, "contract_count": 0, "contract_value": 0,
        "sbir_count": 0, "sbir_value": 0, "total_value": 0,
    })

    for eid, profile in profiles.items():
        for agency, data in profile["agencies"].items():
            stats = agency_stats[agency]
            stats["company_count"] += 1
            stats["contract_count"] += data["contract_count"]
            stats["contract_value"] += data["contract_value"]
            stats["sbir_count"] += data["sbir_count"]
            stats["sbir_value"] += data["sbir_value"]
            stats["total_value"] += data["total_value"]

    sorted_agencies = sorted(agency_stats.items(), key=lambda x: -x[1]["total_value"])

    print(f"\n{'='*100}")
    print("  AGENCY RELATIONSHIP SUMMARY")
    print(f"{'='*100}")
    print(f"\n{'Agency':<20} {'Companies':>10} {'Contracts':>10} {'Contract $':>14} {'SBIRs':>8} {'SBIR $':>12} {'Total $':>14}")
    print("-" * 100)

    for agency, stats in sorted_agencies[:25]:
        print(
            f"{agency:<20} {stats['company_count']:>10,} {stats['contract_count']:>10,} "
            f"${stats['contract_value']/1e6:>12.1f}M {stats['sbir_count']:>8,} "
            f"${stats['sbir_value']/1e6:>10.1f}M ${stats['total_value']/1e6:>12.1f}M"
        )


def print_entity_profile(profiles: dict, search_name: str):
    """Print detailed agency profile for a specific entity."""
    # Find entity by name substring
    matches = []
    for eid, profile in profiles.items():
        if search_name.lower() in profile["entity_name"].lower():
            matches.append((eid, profile))

    if not matches:
        print(f"No entities found matching '{search_name}'")
        return

    for eid, profile in matches[:5]:
        print(f"\n{'='*70}")
        print(f"  {profile['entity_name']} ({profile['entity_type']})")
        print(f"{'='*70}")
        print(f"  Primary agency: {profile['primary_agency']}")
        print(f"  Agency count: {profile['agency_count']}")

        sorted_agencies = sorted(
            profile["agencies"].items(), key=lambda x: -x[1]["total_value"]
        )

        print(f"\n  {'Agency':<20} {'Contracts':>10} {'Contract $':>12} {'SBIRs':>8} {'SBIR $':>10} {'First':>12} {'Last':>12}")
        print(f"  {'-'*20} {'-'*10} {'-'*12} {'-'*8} {'-'*10} {'-'*12} {'-'*12}")

        for agency, data in sorted_agencies:
            print(
                f"  {agency:<20} {data['contract_count']:>10} "
                f"${data['contract_value']/1e6:>10.1f}M {data['sbir_count']:>8} "
                f"${data['sbir_value']/1e6:>8.1f}M {data['first_date'] or 'N/A':>12} "
                f"{data['last_date'] or 'N/A':>12}"
            )


def print_agency_portfolio(profiles: dict, agency_name: str, top_n: int = 20):
    """Print top companies for a specific agency."""
    # Find companies with this agency
    companies = []
    for eid, profile in profiles.items():
        for agency, data in profile["agencies"].items():
            if agency_name.lower() in agency.lower():
                companies.append({
                    "entity_id": eid,
                    "entity_name": profile["entity_name"],
                    "entity_type": profile["entity_type"],
                    "agency": agency,
                    **data,
                })

    if not companies:
        print(f"No companies found for agency '{agency_name}'")
        return

    companies.sort(key=lambda x: -x["total_value"])

    print(f"\n{'='*90}")
    print(f"  TOP {top_n} COMPANIES — {companies[0]['agency']}")
    print(f"{'='*90}")
    print(f"\n  Total companies: {len(companies):,}")
    print(f"\n  {'Company':<40} {'Type':<10} {'Contracts':>10} {'SBIRs':>8} {'Total $':>14}")
    print(f"  {'-'*40} {'-'*10} {'-'*10} {'-'*8} {'-'*14}")

    for c in companies[:top_n]:
        print(
            f"  {c['entity_name'][:40]:<40} {c['entity_type']:<10} "
            f"{c['contract_count']:>10} {c['sbir_count']:>8} "
            f"${c['total_value']/1e6:>12.1f}M"
        )


def save_agency_data(profiles: dict, output_path: Path):
    """Save agency relationship data to JSON."""
    with open(output_path, "w") as f:
        json.dump(profiles, f, indent=2, default=str)
    print(f"\nAgency data saved to {output_path}")
    print(f"  {len(profiles):,} entity profiles")


def main():
    parser = argparse.ArgumentParser(description="Materialize agency relationships")
    parser.add_argument("--save", action="store_true", help="Save to JSON")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--entity", type=str, help="Show profile for a specific entity")
    parser.add_argument("--agency", type=str, help="Show portfolio for a specific agency")
    parser.add_argument("--top", type=int, default=20, help="Number of results to show")

    args = parser.parse_args()

    db = SessionLocal()
    profiles = materialize_agency_relationships(db)

    if args.entity:
        print_entity_profile(profiles, args.entity)
    elif args.agency:
        print_agency_portfolio(profiles, args.agency, args.top)
    else:
        print_agency_summary(profiles)

    if args.save:
        output_path = Path(args.output) if args.output else PROJECT_ROOT / "data" / "agency_relationships.json"
        save_agency_data(profiles, output_path)

    db.close()


if __name__ == "__main__":
    main()
