#!/usr/bin/env python3
"""
SAM.gov OTA (Other Transaction Authority) Scraper

Pulls OTA contracts from the SAM.gov Contract Awards API.
https://api.sam.gov/contract-awards/v1/search

OTAs (10 USC 4022) are how DoD moves money to startups outside the FAR.
~$18B/yr, 5,000+ actions/yr, growing 712% since FY2015. Not captured by
USASpending's award type taxonomy — this scraper fills that blind spot.

Three OT types are queried:
  - OTHER TRANSACTION ORDER
  - OTHER TRANSACTION AGREEMENT
  - OTHER TRANSACTION IDV

Usage:
    python -m scrapers.sam_gov_ota
    python -m scrapers.sam_gov_ota --start-date 2020-10-01 --limit 500
    python -m scrapers.sam_gov_ota --ot-type "OTHER TRANSACTION ORDER"
    python -m scrapers.sam_gov_ota --dry-run
"""

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from processing.database import SessionLocal
from processing.models import Contract, Entity, EntityType, ProcurementType
from processing.entity_resolution.resolver import EntityResolver


# Configure logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "sam_gov_ota.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# OT award type names as used by SAM.gov / FPDS
OT_TYPES = [
    "OTHER TRANSACTION ORDER",
    "OTHER TRANSACTION AGREEMENT",
    "OTHER TRANSACTION IDV",
]

# Default start: FY2016 (Oct 1, 2015)
DEFAULT_START_DATE = date(2015, 10, 1)


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
    records_by_ot_type: dict = field(default_factory=lambda: defaultdict(int))

    def log_summary(self):
        """Log summary statistics."""
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        logger.info("=" * 60)
        logger.info("SAM.GOV OTA SCRAPING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Duration: {duration:.1f} seconds")
        logger.info(f"API requests: {self.api_requests}")
        logger.info(f"Contracts fetched: {self.contracts_fetched}")
        logger.info(f"  - Inserted: {self.contracts_inserted}")
        logger.info(f"  - Updated: {self.contracts_updated}")
        logger.info(f"  - Skipped: {self.contracts_skipped}")
        logger.info(f"Entities: {self.entities_created} new, {self.entities_existing} existing")
        logger.info(f"Errors: {self.errors}")
        if self.records_by_ot_type:
            logger.info("Records by OT type:")
            for ot_type, count in sorted(self.records_by_ot_type.items()):
                logger.info(f"  - {ot_type}: {count}")
        logger.info("=" * 60)


class SamGovOTAScraper:
    """
    Scraper for SAM.gov Contract Awards API — OTA contracts only.

    Queries three OT award types and maps results to the Contract model
    with procurement_type='ota'. Uses the EntityResolver for vendor matching.
    """

    BASE_URL = "https://api.sam.gov/contract-awards/v1/search"

    # SAM.gov rate limits are tight — 1 request/second baseline
    MIN_REQUEST_INTERVAL = 1.0

    def __init__(
        self,
        db: Session,
        batch_size: int = 100,
    ):
        self.db = db
        self.batch_size = batch_size
        self.stats = ScraperStats()
        self.last_request_time = 0.0
        self.resolver = EntityResolver(db)

        # API key
        self.api_key = settings.SAM_GOV_API_KEY
        if not self.api_key:
            raise ValueError(
                "SAM_GOV_API_KEY not set. Add it to .env or environment variables."
            )

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

    def _make_request(self, params: dict) -> Optional[dict]:
        """
        Make GET request to SAM.gov API with rate limiting and error handling.

        Args:
            params: Query parameters (api_key added automatically)

        Returns:
            Response JSON or None on failure
        """
        self._rate_limit()
        self.stats.api_requests += 1

        params["api_key"] = self.api_key

        try:
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=60,
            )

            if response.status_code == 429:
                logger.warning("Rate limited by SAM.gov. Waiting 60 seconds...")
                time.sleep(60)
                # Retry once after waiting
                response = self.session.get(
                    self.BASE_URL,
                    params=params,
                    timeout=60,
                )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"SAM.gov API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text[:500]}")
            self.stats.errors += 1
            return None

    def _build_params(
        self,
        ot_type: str,
        start_date: date,
        end_date: date,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """
        Build query parameters for SAM.gov API.

        SAM.gov date format: [MM/DD/YYYY,MM/DD/YYYY]
        """
        date_range = f"[{start_date.strftime('%m/%d/%Y')},{end_date.strftime('%m/%d/%Y')}]"

        return {
            "awardOrIDVTypeName": ot_type,
            "contractingDepartmentCode": "9700",  # Department of Defense
            "lastModifiedDate": date_range,
            "limit": limit,
            "offset": offset,
        }

    def _safe_get(self, data: dict, *keys, default=None):
        """
        Safely navigate nested dict keys.

        Example: _safe_get(record, "awardDetails", "dollars", "actionObligation")
        """
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and isinstance(key, int) and key < len(current):
                current = current[key]
            else:
                return default
            if current is None:
                return default
        return current

    def _extract_vendor_info(self, record: dict) -> dict:
        """Extract vendor name, CAGE, UEI from a SAM.gov record."""
        awardee_data = self._safe_get(record, "awardDetails", "awardeeData") or {}
        awardee_header = awardee_data.get("awardeeHeader") or {}
        uei_info = awardee_data.get("awardeeUEIInformation") or {}

        return {
            "name": (
                awardee_header.get("awardeeName")
                or self._safe_get(record, "recipientName")
                or "Unknown Contractor"
            ).strip(),
            "cage_code": uei_info.get("cageCode"),
            "uei": uei_info.get("uniqueEntityId"),
        }

    def _extract_contract_fields(self, record: dict) -> dict:
        """
        Extract and map SAM.gov record fields to Contract columns.

        Defensive .get() chains throughout — structure may vary from docs.
        """
        # Contract ID
        piid = self._safe_get(record, "contractId", "piid") or ""

        # Dollars
        dollars = self._safe_get(record, "awardDetails", "dollars") or {}
        action_obligation = dollars.get("actionObligation")
        base_and_options = dollars.get("baseAndAllOptionsValue")

        # Dates
        dates = self._safe_get(record, "awardDetails", "dates") or {}
        date_signed = dates.get("dateSigned")

        # Organization
        fed_org = self._safe_get(record, "coreData", "federalOrganization") or {}
        contracting_info = fed_org.get("contractingInformation") or {}
        contracting_office = contracting_info.get("contractingOffice") or {}
        office_name = contracting_office.get("name") or ""

        # Also try department/agency name as fallback
        if not office_name:
            office_name = (
                self._safe_get(record, "coreData", "federalOrganization", "agency", "name")
                or ""
            )

        # Classification codes
        psi = self._safe_get(record, "coreData", "productOrServiceInformation") or {}
        naics_list = psi.get("principalNaics") or []
        naics_code = naics_list[0].get("code") if naics_list else None
        psc_info = psi.get("productOrService") or {}
        psc_code = psc_info.get("code")

        # Place of performance
        pop = self._safe_get(record, "coreData", "principalPlaceOfPerformance") or {}
        state_info = pop.get("state") or {}
        city_info = pop.get("city") or {}
        pop_parts = []
        if city_info.get("name"):
            pop_parts.append(city_info["name"])
        if state_info.get("code"):
            pop_parts.append(state_info["code"])
        place_of_performance = ", ".join(pop_parts) if pop_parts else ""

        # Award type
        award_type_info = self._safe_get(record, "coreData", "awardOrIDVType") or {}
        contract_type = award_type_info.get("name") or ""

        return {
            "piid": piid,
            "action_obligation": action_obligation,
            "base_and_options": base_and_options,
            "date_signed": date_signed,
            "contracting_office": office_name,
            "naics_code": naics_code,
            "psc_code": psc_code,
            "place_of_performance": place_of_performance,
            "contract_type": contract_type,
        }

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse date string from SAM.gov API (various formats)."""
        if not date_str:
            return None
        for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(date_str[:max(10, len(date_str))], fmt).date()
            except ValueError:
                continue
        logger.warning(f"Could not parse date: {date_str}")
        return None

    def _parse_amount(self, value) -> Optional[Decimal]:
        """Parse a dollar amount to Decimal."""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    def _get_or_create_entity(self, vendor_info: dict) -> tuple[Entity, bool]:
        """
        Resolve vendor to an entity using the EntityResolver.

        Three-tier matching: CAGE code -> fuzzy name -> create new.

        Args:
            vendor_info: dict with 'name', 'cage_code', 'uei'

        Returns:
            Tuple of (entity, created)
        """
        name = vendor_info["name"]
        cage_code = vendor_info.get("cage_code")

        entity, created = self.resolver.resolve_or_create(
            name=name,
            entity_type=EntityType.STARTUP,  # Default for OTA vendors
            cage_code=cage_code,
        )

        if created:
            self.stats.entities_created += 1
            logger.info(
                f"NEW ENTITY (OTA): {name} | CAGE={cage_code} | UEI={vendor_info.get('uei')}"
            )
        else:
            self.stats.entities_existing += 1

        return entity, created

    def _process_record(self, record: dict, seen_contracts: set) -> Optional[Contract]:
        """
        Process a single SAM.gov award record.

        Args:
            record: Raw JSON record from API
            seen_contracts: Set of PIIDs already processed in this run

        Returns:
            Contract record or None if skipped/error
        """
        try:
            fields = self._extract_contract_fields(record)
            piid = fields["piid"]

            if not piid:
                logger.warning("Skipping record with no PIID")
                self.stats.contracts_skipped += 1
                return None

            # Use PIID as contract_number for dedup/grouping
            contract_number = piid

            # Skip if we've already seen this contract in this batch
            if contract_number in seen_contracts:
                self.stats.contracts_skipped += 1
                return None
            seen_contracts.add(contract_number)

            # Check for existing contract
            existing = self.db.query(Contract).filter(
                Contract.contract_number == contract_number
            ).first()

            if existing:
                # Update: latest obligated amount and raw_data
                new_value = self._parse_amount(fields["action_obligation"])
                if new_value is not None:
                    existing.contract_value = new_value
                existing.raw_data = record
                existing.procurement_type = ProcurementType.OTA.value
                self.stats.contracts_updated += 1
                return existing

            # Resolve vendor entity
            vendor_info = self._extract_vendor_info(record)
            entity, _ = self._get_or_create_entity(vendor_info)

            # Build contract
            contract = Contract(
                entity_id=entity.id,
                contract_number=contract_number,
                contracting_agency=fields["contracting_office"],
                contract_value=self._parse_amount(fields["action_obligation"]),
                award_date=self._parse_date(fields["date_signed"]),
                naics_code=fields["naics_code"],
                psc_code=fields["psc_code"],
                place_of_performance=fields["place_of_performance"],
                contract_type=fields["contract_type"],
                raw_data=record,
                procurement_type=ProcurementType.OTA.value,
            )

            self.db.add(contract)
            self.stats.contracts_inserted += 1

            # Track by OT type
            ot_type = fields["contract_type"]
            if ot_type:
                self.stats.records_by_ot_type[ot_type] += 1

            return contract

        except Exception as e:
            piid_str = self._safe_get(record, "contractId", "piid") or "unknown"
            logger.error(f"Error processing record {piid_str}: {e}", exc_info=True)
            self.stats.errors += 1
            self.db.rollback()
            return None

    def _scrape_ot_type(
        self,
        ot_type: str,
        start_date: date,
        end_date: date,
        limit: Optional[int] = None,
        dry_run: bool = False,
    ) -> int:
        """
        Scrape all records for a single OT type.

        Args:
            ot_type: e.g. "OTHER TRANSACTION ORDER"
            start_date: Range start
            end_date: Range end
            limit: Max records to fetch (None=all)
            dry_run: If True, only count records, don't store

        Returns:
            Number of records fetched for this OT type
        """
        logger.info(f"--- Scraping: {ot_type} ---")

        offset = 0
        page_size = 100
        type_fetched = 0
        pending_commits = 0
        seen_contracts = set()

        while True:
            if limit and type_fetched >= limit:
                logger.info(f"Reached limit of {limit} for {ot_type}")
                break

            params = self._build_params(
                ot_type=ot_type,
                start_date=start_date,
                end_date=end_date,
                limit=page_size,
                offset=offset,
            )

            logger.info(f"Fetching {ot_type} page {offset} (offset={offset})...")
            response = self._make_request(params)

            if not response:
                logger.error(f"Failed to fetch page {offset} for {ot_type}, stopping this type")
                break

            # Log response structure on first page for debugging
            if offset == 0:
                total_records = response.get("totalRecords", "unknown")
                logger.info(f"Total records available for {ot_type}: {total_records}")
                # Log top-level keys for structure validation
                logger.debug(f"Response keys: {list(response.keys())}")

            records = response.get("contractData") or response.get("results") or []
            if not records:
                # Try alternate key names
                for key in response.keys():
                    if isinstance(response[key], list) and len(response[key]) > 0:
                        records = response[key]
                        logger.info(f"Found records under key '{key}'")
                        break

            if not records:
                logger.info(f"No more results for {ot_type}")
                break

            # Log first record structure on first page
            if offset == 0 and records:
                first_record = records[0]
                logger.info(f"First record top-level keys: {list(first_record.keys()) if isinstance(first_record, dict) else type(first_record)}")
                # Log sample vendor extraction
                sample_vendor = self._extract_vendor_info(first_record) if isinstance(first_record, dict) else {}
                logger.info(f"Sample vendor extraction: {sample_vendor}")
                sample_fields = self._extract_contract_fields(first_record) if isinstance(first_record, dict) else {}
                logger.info(f"Sample field extraction: piid={sample_fields.get('piid')}, "
                           f"office={sample_fields.get('contracting_office')}, "
                           f"value={sample_fields.get('action_obligation')}")

            if dry_run:
                type_fetched += len(records)
                total_records = response.get("totalRecords", 0)
                logger.info(f"[DRY RUN] Page {offset}: {len(records)} records (total available: {total_records})")
            else:
                for record in records:
                    if limit and type_fetched >= limit:
                        break

                    if not isinstance(record, dict):
                        logger.warning(f"Unexpected record type: {type(record)}")
                        continue

                    contract = self._process_record(record, seen_contracts)
                    if contract:
                        type_fetched += 1
                        pending_commits += 1

                        if type_fetched % 50 == 0:
                            logger.info(f"Progress ({ot_type}): {type_fetched} contracts processed")

                    # Batch commit
                    if pending_commits >= self.batch_size:
                        try:
                            self.db.commit()
                            pending_commits = 0
                            logger.debug(f"Committed batch at {type_fetched} contracts")
                        except Exception as e:
                            logger.error(f"Batch commit failed: {e}")
                            self.db.rollback()
                            self.stats.errors += 1

            self.stats.contracts_fetched = (
                self.stats.contracts_inserted
                + self.stats.contracts_updated
                + self.stats.contracts_skipped
            )

            # Pagination: stop if fewer than page_size records returned
            if len(records) < page_size:
                logger.info(f"Fetched all available results for {ot_type}")
                break

            # Check total records limit
            total_records = int(response.get("totalRecords", 0) or 0)
            if total_records and (offset + 1) * page_size >= total_records:
                logger.info(f"Reached end of results for {ot_type} ({total_records} total)")
                break

            offset += 1

        # Final commit for this OT type
        if not dry_run and pending_commits > 0:
            try:
                self.db.commit()
            except Exception as e:
                logger.error(f"Final commit failed for {ot_type}: {e}")
                self.db.rollback()
                self.stats.errors += 1

        logger.info(f"Completed {ot_type}: {type_fetched} records")
        return type_fetched

    def scrape(
        self,
        start_date: date = DEFAULT_START_DATE,
        end_date: Optional[date] = None,
        ot_types: Optional[list[str]] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
    ) -> ScraperStats:
        """
        Main scraping function. Queries each OT type and unions results.

        Args:
            start_date: Start of date range (default: FY2016 start)
            end_date: End of date range (default: today)
            ot_types: OT types to query (default: all three)
            limit: Max records per OT type (None=all)
            dry_run: If True, count records only — don't store

        Returns:
            ScraperStats with results
        """
        if end_date is None:
            end_date = date.today()
        if ot_types is None:
            ot_types = OT_TYPES

        self.stats = ScraperStats()
        self.stats.start_time = datetime.now()

        logger.info("=" * 60)
        logger.info("SAM.GOV OTA SCRAPER - STARTING")
        logger.info("=" * 60)
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"OT types: {ot_types}")
        logger.info(f"Limit per type: {limit or 'None'}")
        logger.info(f"Dry run: {dry_run}")
        logger.info("=" * 60)

        total = 0
        for ot_type in ot_types:
            count = self._scrape_ot_type(
                ot_type=ot_type,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                dry_run=dry_run,
            )
            total += count

        self.stats.contracts_fetched = total
        self.stats.end_time = datetime.now()
        self.stats.log_summary()

        return self.stats


def print_analytics(db: Session):
    """
    Post-scrape analytics: print summary of OTA records in the database.
    Runs automatically after scraping.
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("OTA ANALYTICS")
    logger.info("=" * 60)

    # 1. Total OTA records
    total_ota = db.query(Contract).filter(
        Contract.procurement_type == ProcurementType.OTA.value
    ).count()
    logger.info(f"Total OTA records in database: {total_ota}")

    if total_ota == 0:
        logger.info("No OTA records to analyze.")
        return

    # 2. Records by fiscal year (FY = Oct-Sep, derive from award_date)
    logger.info("")
    logger.info("Records by fiscal year:")
    ota_contracts = db.query(Contract).filter(
        Contract.procurement_type == ProcurementType.OTA.value,
        Contract.award_date.isnot(None),
    ).all()

    fy_counts = defaultdict(int)
    fy_dollars = defaultdict(Decimal)
    for c in ota_contracts:
        # Fiscal year: if month >= 10, it's the next FY
        if c.award_date.month >= 10:
            fy = c.award_date.year + 1
        else:
            fy = c.award_date.year
        fy_counts[fy] += 1
        if c.contract_value:
            fy_dollars[fy] += c.contract_value

    for fy in sorted(fy_counts.keys()):
        dollars = fy_dollars.get(fy, Decimal(0))
        logger.info(f"  FY{fy}: {fy_counts[fy]:,} records, ${dollars:,.0f} obligated")

    # 3. Top 20 vendors by total obligated amount
    logger.info("")
    logger.info("Top 20 vendors by total obligated amount:")
    vendor_query = (
        db.query(
            Entity.canonical_name,
            sa_func.count(Contract.id).label("contract_count"),
            sa_func.sum(Contract.contract_value).label("total_value"),
        )
        .join(Entity, Contract.entity_id == Entity.id)
        .filter(Contract.procurement_type == ProcurementType.OTA.value)
        .group_by(Entity.canonical_name)
        .order_by(sa_func.sum(Contract.contract_value).desc())
        .limit(20)
        .all()
    )
    for i, (name, count, total) in enumerate(vendor_query, 1):
        total_str = f"${total:,.0f}" if total else "$0"
        logger.info(f"  {i:2d}. {name[:50]:<50s} {count:>4d} contracts  {total_str:>15s}")

    # 4. Entity resolution stats (already in ScraperStats, but also show DB state)
    total_entities_with_ota = (
        db.query(Entity)
        .join(Contract, Contract.entity_id == Entity.id)
        .filter(Contract.procurement_type == ProcurementType.OTA.value)
        .distinct()
        .count()
    )
    logger.info("")
    logger.info(f"Unique entities with OTA contracts: {total_entities_with_ota}")

    # 5. Top contracting offices
    logger.info("")
    logger.info("Top contracting offices:")
    office_query = (
        db.query(
            Contract.contracting_agency,
            sa_func.count(Contract.id).label("count"),
            sa_func.sum(Contract.contract_value).label("total"),
        )
        .filter(
            Contract.procurement_type == ProcurementType.OTA.value,
            Contract.contracting_agency.isnot(None),
            Contract.contracting_agency != "",
        )
        .group_by(Contract.contracting_agency)
        .order_by(sa_func.count(Contract.id).desc())
        .limit(20)
        .all()
    )
    for i, (office, count, total) in enumerate(office_query, 1):
        total_str = f"${total:,.0f}" if total else "$0"
        logger.info(f"  {i:2d}. {(office or 'Unknown')[:50]:<50s} {count:>4d} contracts  {total_str:>15s}")

    logger.info("=" * 60)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scrape OTA contracts from SAM.gov Contract Awards API"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=DEFAULT_START_DATE.isoformat(),
        help="Start date (YYYY-MM-DD), default: 2015-10-01 (FY2016)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=date.today().isoformat(),
        help="End date (YYYY-MM-DD), default: today",
    )
    parser.add_argument(
        "--ot-type",
        type=str,
        help="Filter to a single OT type (e.g., 'OTHER TRANSACTION ORDER')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of contracts to fetch per OT type (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count records only, don't store in database",
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    # Determine OT types to query
    ot_types = [args.ot_type] if args.ot_type else OT_TYPES

    # Create database session
    db = SessionLocal()

    try:
        scraper = SamGovOTAScraper(db=db)

        stats = scraper.scrape(
            start_date=start_date,
            end_date=end_date,
            ot_types=ot_types,
            limit=args.limit,
            dry_run=args.dry_run,
        )

        # Post-scrape analytics
        if not args.dry_run:
            print_analytics(db)

        # Exit with error code if there were errors
        if stats.errors > 0:
            sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
