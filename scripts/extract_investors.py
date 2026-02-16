#!/usr/bin/env python3
"""
Extract investor names from Reg D filing raw_data.

DERA Form D data has a RELATEDPERSONS table with directors, executive officers,
and promoters. For VC-backed companies, these often include fund names and
managing partners. This script parses those out to build investor → company edges.

Usage:
    python scripts/extract_investors.py                  # Extract and display
    python scripts/extract_investors.py --save           # Save to JSON
    python scripts/extract_investors.py --top 20         # Show top 20 investors
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from processing.database import SessionLocal
from processing.models import Entity, FundingEvent, FundingEventType

PROJECT_ROOT = Path(__file__).parent.parent


# Patterns that indicate a person (not a fund)
PERSON_PATTERNS = [
    r"^[A-Z][a-z]+ [A-Z][a-z]+$",  # "John Smith"
    r"^[A-Z]\. [A-Z][a-z]+$",       # "J. Smith"
]

# Patterns that indicate a fund/firm (what we want)
FUND_INDICATORS = [
    "capital", "ventures", "partners", "fund", "investments", "management",
    "holdings", "group", "advisors", "advisory", "equity", "asset",
    "securities", "financial", "associates", "llc", "l.p.", "lp",
]

# Noise to filter out
SKIP_NAMES = {
    "", "none", "n/a", "na", "not applicable", "self", "various",
    "undisclosed", "anonymous",
}


def extract_investors_from_regd(db) -> dict:
    """
    Extract investor information from Reg D funding events.

    The raw_data from DERA contains fields like:
    - I_ENTITYNAME: issuer name (the company)
    - Related persons fields (directors/executive officers/promoters)

    For Form D, the "related persons" are often the investors or their
    representatives. We look for patterns that indicate institutional investors.
    """
    # Query all Reg D filings with raw_data
    filings = db.query(FundingEvent).filter(
        FundingEvent.event_type == FundingEventType.REG_D_FILING,
        FundingEvent.raw_data.isnot(None),
    ).all()

    print(f"Processing {len(filings)} Reg D filings...")

    # investor_name -> list of {entity_id, entity_name, amount, date}
    investor_map = defaultdict(list)
    # entity_id -> list of investor names
    entity_investors = defaultdict(list)

    for fe in filings:
        raw = fe.raw_data or {}
        entity_id = fe.entity_id

        # Get company name
        entity = db.query(Entity).filter(Entity.id == entity_id).first()
        entity_name = entity.canonical_name if entity else "Unknown"

        # Extract from related persons (_related_persons stored by scraper)
        persons = _extract_related_persons(raw)

        # Also check investors_awarders field (sometimes populated by scraper)
        existing_investors = fe.investors_awarders or []
        if isinstance(existing_investors, list):
            for inv in existing_investors:
                if isinstance(inv, str) and inv.strip():
                    persons.append({
                        "name": inv.strip(),
                        "role": "investor",
                        "is_fund": True,
                    })

        for person in persons:
            name = person["name"]
            if not name or name.lower() in SKIP_NAMES:
                continue

            # Determine if this is a fund/firm vs individual person
            is_fund = person.get("is_fund", _is_likely_fund(name))

            if is_fund:
                normalized = _normalize_investor_name(name)
                if normalized:
                    investment = {
                        "entity_id": entity_id,
                        "entity_name": entity_name,
                        "amount": float(fe.amount) if fe.amount else None,
                        "date": str(fe.event_date) if fe.event_date else None,
                        "role": person.get("role", "unknown"),
                    }
                    investor_map[normalized].append(investment)
                    entity_investors[entity_id].append(normalized)

    return {
        "investor_map": dict(investor_map),
        "entity_investors": dict(entity_investors),
    }


def _extract_related_persons(raw_data: dict) -> list[dict]:
    """Extract related persons from DERA raw_data fields."""
    persons = []

    # Primary source: _related_persons array (from RELATEDPERSONS.TSV)
    related = raw_data.get("_related_persons", [])
    if isinstance(related, list):
        for rp in related:
            first = rp.get("first_name", "").strip()
            last = rp.get("last_name", "").strip()
            roles = rp.get("relationships", "").strip().lower()

            if not last:
                continue

            full_name = f"{first} {last}".strip() if first else last

            # Promoters are often investment funds
            is_promoter = "promoter" in roles
            persons.append({
                "name": full_name,
                "role": roles,
                "is_fund": is_promoter or _is_likely_fund(full_name),
            })

    # Fallback: individual numbered fields (older format)
    for i in range(1, 20):
        last = raw_data.get(f"O_RELATEDPERSON{i}LASTNAME", "").strip()
        first = raw_data.get(f"O_RELATEDPERSON{i}FIRSTNAME", "").strip()
        roles = raw_data.get(f"O_RELATEDPERSON{i}RELATIONSHIPS", "").strip()

        if last:
            full_name = f"{first} {last}".strip() if first else last
            is_promoter = "promoter" in roles.lower()
            persons.append({
                "name": full_name,
                "role": roles.lower(),
                "is_fund": is_promoter or _is_likely_fund(full_name),
            })

    return persons


def _is_likely_fund(name: str) -> bool:
    """Check if a name looks like an investment fund vs a person."""
    name_lower = name.lower()
    # Check fund indicators
    for indicator in FUND_INDICATORS:
        if indicator in name_lower:
            return True
    # Check if it has corporate suffixes
    if re.search(r'\b(inc|llc|lp|corp|ltd)\b', name_lower, re.IGNORECASE):
        return True
    # Names with 3+ words are more likely to be firms
    if len(name.split()) >= 3:
        return True
    return False


def _normalize_investor_name(name: str) -> str:
    """Normalize investor/fund name for deduplication."""
    if not name:
        return ""
    # Strip common suffixes
    normalized = name.strip()
    normalized = re.sub(r',?\s*(LLC|L\.L\.C\.|LP|L\.P\.|Inc\.?|Corp\.?)$', '', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def print_investor_summary(data: dict, top_n: int = 30):
    """Print summary of extracted investors."""
    investor_map = data["investor_map"]
    entity_investors = data["entity_investors"]

    print(f"\n{'='*90}")
    print(f"  INVESTOR EXTRACTION RESULTS")
    print(f"{'='*90}")
    print(f"\n  Unique investors/funds found: {len(investor_map):,}")
    print(f"  Companies with investor data: {len(entity_investors):,}")
    total_investments = sum(len(v) for v in investor_map.values())
    print(f"  Total investor→company edges: {total_investments:,}")

    # Top investors by number of portfolio companies
    sorted_investors = sorted(
        investor_map.items(),
        key=lambda x: len(set(inv["entity_id"] for inv in x[1])),
        reverse=True,
    )

    print(f"\n--- Top {top_n} Investors by Portfolio Size ---")
    print(f"  {'Investor':<50} {'Companies':>10} {'Total Capital':>15}")
    print(f"  {'-'*50} {'-'*10} {'-'*15}")

    for name, investments in sorted_investors[:top_n]:
        unique_companies = len(set(inv["entity_id"] for inv in investments))
        total_capital = sum(inv["amount"] or 0 for inv in investments)
        cap_str = f"${total_capital/1_000_000:.1f}M" if total_capital > 0 else "N/A"
        print(f"  {name:<50} {unique_companies:>10} {cap_str:>15}")

    # Companies with the most investor connections
    sorted_entities = sorted(
        entity_investors.items(),
        key=lambda x: len(set(x[1])),
        reverse=True,
    )

    print(f"\n--- Top 15 Companies by Investor Connections ---")
    for entity_id, investors in sorted_entities[:15]:
        unique_investors = sorted(set(investors))
        # Look up entity name from investor_map
        entity_name = "Unknown"
        for inv_name, investments in investor_map.items():
            for inv in investments:
                if inv["entity_id"] == entity_id:
                    entity_name = inv["entity_name"]
                    break
            if entity_name != "Unknown":
                break
        print(f"  {entity_name:<45} {len(unique_investors)} investors")
        for inv in unique_investors[:5]:
            print(f"    - {inv}")


def save_investor_data(data: dict, output_path: Path):
    """Save investor data to JSON."""
    # Convert for JSON serialization
    export = {
        "metadata": {
            "unique_investors": len(data["investor_map"]),
            "companies_with_investors": len(data["entity_investors"]),
            "total_edges": sum(len(v) for v in data["investor_map"].values()),
        },
        "investors": {},
        "entity_investors": data["entity_investors"],
    }

    for name, investments in data["investor_map"].items():
        export["investors"][name] = {
            "portfolio_count": len(set(inv["entity_id"] for inv in investments)),
            "total_capital": sum(inv["amount"] or 0 for inv in investments),
            "investments": investments,
        }

    with open(output_path, "w") as f:
        json.dump(export, f, indent=2)

    print(f"\nInvestor data saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Extract investors from Reg D filings")
    parser.add_argument("--save", action="store_true", help="Save to JSON")
    parser.add_argument("--output", type=str, default=None, help="Output path")
    parser.add_argument("--top", type=int, default=30, help="Show top N investors")

    args = parser.parse_args()

    db = SessionLocal()
    data = extract_investors_from_regd(db)
    print_investor_summary(data, args.top)

    if args.save:
        output_path = Path(args.output) if args.output else PROJECT_ROOT / "data" / "investor_edges.json"
        save_investor_data(data, output_path)

    db.close()


if __name__ == "__main__":
    main()
