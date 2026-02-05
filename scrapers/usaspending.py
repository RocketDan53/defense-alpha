#!/usr/bin/env python3
"""
USA Spending API Scraper

Pulls Department of Defense contracts from the USA Spending API.
https://api.usaspending.gov/api/v2/search/spending_by_award/

Usage:
    python -m scrapers.usaspending --start-date 2024-01-01 --end-date 2024-01-31 --limit 100
    python -m scrapers.usaspending --agency "Air Force" --limit 50
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Contract, Entity, EntityType


# Configure logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "usaspending.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# DoD Agency codes and names
DOD_AGENCIES = {
    "Department of the Air Force": "097",
    "Air Force": "097",
    "Department of the Army": "021",
    "Army": "021",
    "Department of the Navy": "017",
    "Navy": "017",
    "Defense Advanced Research Projects Agency": "097",
    "DARPA": "097",
    "Missile Defense Agency": "097",
    "MDA": "097",
    "Department of the Space Force": "097",
    "Space Force": "097",
    "Defense Innovation Unit": "097",
    "DIU": "097",
}

# Toptier agency codes for filtering
DOD_TOPTIER_CODES = ["097", "021", "017"]  # DoD, Army, Navy


@dataclass
class ScraperStats:
    """Statistics from a scraping run."""
    contracts_fetched: int = 0
    contracts_inserted: int = 0
    contracts_updated: int = 0
    contracts_skipped: int = 0
    entities_created: int = 0
    entities_existing: int = 0
    errors: int = 0
    api_requests: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def log_summary(self):
        """Log summary statistics."""
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        logger.info("=" * 60)
        logger.info("SCRAPING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Duration: {duration:.1f} seconds")
        logger.info(f"API requests: {self.api_requests}")
        logger.info(f"Contracts fetched: {self.contracts_fetched}")
        logger.info(f"  - Inserted: {self.contracts_inserted}")
        logger.info(f"  - Updated: {self.contracts_updated}")
        logger.info(f"  - Skipped: {self.contracts_skipped}")
        logger.info(f"Entities: {self.entities_created} new, {self.entities_existing} existing")
        logger.info(f"Errors: {self.errors}")
        logger.info("=" * 60)


class USASpendingScraper:
    """
    Scraper for USA Spending API DoD contracts.
    """

    BASE_URL = "https://api.usaspending.gov/api/v2"
    SEARCH_ENDPOINT = "/search/spending_by_award/"

    # Rate limiting: max 10 requests/second
    MIN_REQUEST_INTERVAL = 0.1  # 100ms between requests

    def __init__(
        self,
        db: Session,
        min_contract_value: float = 100000,
        batch_size: int = 100,
    ):
        """
        Initialize the scraper.

        Args:
            db: Database session
            min_contract_value: Minimum contract value to include
            batch_size: Number of records per database commit
        """
        self.db = db
        self.min_contract_value = min_contract_value
        self.batch_size = batch_size
        self.stats = ScraperStats()
        self.last_request_time = 0

        # Setup session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self.last_request_time = time.time()

    def _make_request(self, payload: dict) -> Optional[dict]:
        """
        Make API request with rate limiting and error handling.

        Args:
            payload: Request payload

        Returns:
            Response JSON or None on failure
        """
        self._rate_limit()
        self.stats.api_requests += 1

        url = f"{self.BASE_URL}{self.SEARCH_ENDPOINT}"

        try:
            response = self.session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            self.stats.errors += 1
            return None

    def _build_filters(
        self,
        start_date: date,
        end_date: date,
        agency: Optional[str] = None,
    ) -> dict:
        """
        Build API filters for DoD contracts.

        Args:
            start_date: Start of date range
            end_date: End of date range
            agency: Optional specific agency filter

        Returns:
            Filters dict for API request
        """
        filters = {
            "time_period": [
                {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                }
            ],
            "award_type_codes": ["A", "B", "C", "D"],  # Contract types
            "award_amounts": [
                {
                    "lower_bound": self.min_contract_value,
                }
            ],
        }

        # Filter by agency
        if agency:
            # Map agency name to search term
            agency_upper = agency.upper()
            if agency_upper in ["AIR FORCE", "DEPARTMENT OF THE AIR FORCE"]:
                filters["agencies"] = [
                    {"type": "awarding", "tier": "subtier", "name": "Department of the Air Force"}
                ]
            elif agency_upper in ["ARMY", "DEPARTMENT OF THE ARMY"]:
                filters["agencies"] = [
                    {"type": "awarding", "tier": "subtier", "name": "Department of the Army"}
                ]
            elif agency_upper in ["NAVY", "DEPARTMENT OF THE NAVY"]:
                filters["agencies"] = [
                    {"type": "awarding", "tier": "subtier", "name": "Department of the Navy"}
                ]
            elif agency_upper == "DARPA":
                filters["agencies"] = [
                    {"type": "awarding", "tier": "subtier", "name": "Defense Advanced Research Projects Agency"}
                ]
            else:
                # Try exact match
                filters["agencies"] = [
                    {"type": "awarding", "tier": "subtier", "name": agency}
                ]
        else:
            # All DoD agencies
            filters["agencies"] = [
                {"type": "awarding", "tier": "toptier", "name": "Department of Defense"}
            ]

        return filters

    def _get_or_create_entity(self, company_name: str) -> Entity:
        """
        Get existing entity or create new one.

        Args:
            company_name: Company name from contract

        Returns:
            Entity record
        """
        if not company_name:
            company_name = "Unknown Contractor"

        # Clean up name
        company_name = company_name.strip()

        # Check for existing entity (simple name match for now)
        # Entity resolution will clean this up later
        entity = self.db.query(Entity).filter(
            Entity.canonical_name == company_name,
            Entity.merged_into_id.is_(None),
        ).first()

        if entity:
            self.stats.entities_existing += 1
            return entity

        # Create new entity
        entity = Entity(
            canonical_name=company_name,
            name_variants=[],
            entity_type=EntityType.STARTUP,  # Default, will refine later
        )
        self.db.add(entity)
        self.db.flush()  # Get the ID without committing
        self.stats.entities_created += 1

        return entity

    def _process_award(self, award: dict, seen_contracts: set) -> Optional[Contract]:
        """
        Process a single award record.

        Args:
            award: Award data from API
            seen_contracts: Set of contract numbers already processed in this batch

        Returns:
            Contract record or None if skipped/error
        """
        try:
            # Extract contract number
            contract_number = award.get("Award ID") or award.get("generated_internal_id")
            if not contract_number:
                logger.warning("Skipping award with no contract number")
                self.stats.contracts_skipped += 1
                return None

            # Skip if we've already seen this contract in this batch
            if contract_number in seen_contracts:
                self.stats.contracts_skipped += 1
                return None
            seen_contracts.add(contract_number)

            # Check for existing contract in database
            existing = self.db.query(Contract).filter(
                Contract.contract_number == contract_number
            ).first()

            if existing:
                # Update existing contract
                self._update_contract(existing, award)
                self.stats.contracts_updated += 1
                return existing

            # Get or create entity for recipient
            recipient_name = award.get("Recipient Name", "Unknown")
            entity = self._get_or_create_entity(recipient_name)

            # Parse dates
            award_date = self._parse_date(award.get("Start Date"))
            pop_start = self._parse_date(award.get("Start Date"))
            pop_end = self._parse_date(award.get("End Date"))

            # Parse amount
            amount = award.get("Award Amount")
            if amount is not None:
                try:
                    amount = Decimal(str(amount))
                except:
                    amount = None

            # Create contract
            contract = Contract(
                entity_id=entity.id,
                contract_number=contract_number,
                contracting_agency=award.get("Awarding Sub Agency") or award.get("Awarding Agency", ""),
                contract_value=amount,
                award_date=award_date,
                period_of_performance_start=pop_start,
                period_of_performance_end=pop_end,
                naics_code=award.get("NAICS Code"),
                psc_code=award.get("Product or Service Code"),
                place_of_performance=self._format_place_of_performance(award),
                contract_type=award.get("Award Type"),
                raw_data=award,
            )

            self.db.add(contract)
            self.stats.contracts_inserted += 1

            return contract

        except Exception as e:
            logger.error(f"Error processing award {contract_number}: {e}")
            self.stats.errors += 1
            # Rollback the current transaction to clear the error state
            self.db.rollback()
            return None

    def _update_contract(self, contract: Contract, award: dict):
        """Update existing contract with new data."""
        amount = award.get("Award Amount")
        if amount is not None:
            try:
                contract.contract_value = Decimal(str(amount))
            except:
                pass

        contract.raw_data = award
        pop_end = self._parse_date(award.get("End Date"))
        if pop_end:
            contract.period_of_performance_end = pop_end

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse date string from API."""
        if not date_str:
            return None

        try:
            # Try common formats
            for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"]:
                try:
                    return datetime.strptime(date_str[:10], fmt[:8] if len(date_str) < 11 else fmt).date()
                except ValueError:
                    continue
            return None
        except:
            return None

    def _format_place_of_performance(self, award: dict) -> str:
        """Format place of performance from award data."""
        parts = []
        if award.get("Place of Performance City"):
            parts.append(award["Place of Performance City"])
        if award.get("Place of Performance State"):
            parts.append(award["Place of Performance State"])
        return ", ".join(parts) if parts else ""

    def scrape(
        self,
        start_date: date,
        end_date: date,
        agency: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> ScraperStats:
        """
        Main scraping function.

        Args:
            start_date: Start of date range
            end_date: End of date range
            agency: Optional specific agency filter
            limit: Optional max contracts to fetch

        Returns:
            ScraperStats with results
        """
        self.stats = ScraperStats()
        self.stats.start_time = datetime.now()

        logger.info("=" * 60)
        logger.info("USA SPENDING SCRAPER - STARTING")
        logger.info("=" * 60)
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Agency filter: {agency or 'All DoD'}")
        logger.info(f"Min contract value: ${self.min_contract_value:,.0f}")
        logger.info(f"Limit: {limit or 'None'}")
        logger.info("=" * 60)

        filters = self._build_filters(start_date, end_date, agency)
        page = 1
        page_size = 100
        total_fetched = 0
        pending_commits = 0
        seen_contracts = set()  # Track contracts seen in this run

        while True:
            # Check limit
            if limit and total_fetched >= limit:
                logger.info(f"Reached limit of {limit} contracts")
                break

            # Build request payload
            payload = {
                "filters": filters,
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Award Amount",
                    "Awarding Agency",
                    "Awarding Sub Agency",
                    "Start Date",
                    "End Date",
                    "Award Type",
                    "NAICS Code",
                    "Product or Service Code",
                    "Place of Performance City",
                    "Place of Performance State",
                    "Place of Performance Country",
                    "generated_internal_id",
                    "Recipient DUNS",
                    "Recipient UEI",
                ],
                "page": page,
                "limit": page_size,
                "sort": "Award Amount",
                "order": "desc",
            }

            logger.info(f"Fetching page {page}...")
            response = self._make_request(payload)

            if not response:
                logger.error(f"Failed to fetch page {page}, stopping")
                break

            results = response.get("results", [])
            if not results:
                logger.info("No more results")
                break

            # Process each award
            for award in results:
                if limit and total_fetched >= limit:
                    break

                contract = self._process_award(award, seen_contracts)
                if contract:
                    total_fetched += 1
                    pending_commits += 1

                    # Progress logging
                    if total_fetched % 50 == 0:
                        logger.info(f"Progress: {total_fetched} contracts processed")

                # Batch commit
                if pending_commits >= self.batch_size:
                    try:
                        self.db.commit()
                        pending_commits = 0
                        logger.debug(f"Committed batch at {total_fetched} contracts")
                    except Exception as e:
                        logger.error(f"Batch commit failed: {e}")
                        self.db.rollback()
                        self.stats.errors += 1

            self.stats.contracts_fetched = total_fetched

            # Check if we've fetched all available
            if len(results) < page_size:
                logger.info("Fetched all available results")
                break

            page += 1

        # Final commit
        try:
            self.db.commit()
        except Exception as e:
            logger.error(f"Final commit failed: {e}")
            self.db.rollback()
            self.stats.errors += 1

        self.stats.end_time = datetime.now()
        self.stats.log_summary()

        return self.stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scrape DoD contracts from USA Spending API"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=(date.today().replace(year=date.today().year - 5)).isoformat(),
        help="Start date (YYYY-MM-DD), default: 5 years ago",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=date.today().isoformat(),
        help="End date (YYYY-MM-DD), default: today",
    )
    parser.add_argument(
        "--agency",
        type=str,
        help="Filter by specific agency (e.g., 'Air Force', 'Army', 'Navy', 'DARPA')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of contracts to fetch (for testing)",
    )
    parser.add_argument(
        "--min-value",
        type=float,
        default=100000,
        help="Minimum contract value (default: $100,000)",
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    # Create database session
    db = SessionLocal()

    try:
        scraper = USASpendingScraper(
            db=db,
            min_contract_value=args.min_value,
        )

        stats = scraper.scrape(
            start_date=start_date,
            end_date=end_date,
            agency=args.agency,
            limit=args.limit,
        )

        # Exit with error code if there were errors
        if stats.errors > 0:
            sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
