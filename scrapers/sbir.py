#!/usr/bin/env python3
"""
SBIR.gov Scraper

Pulls SBIR/STTR awards from SBIR.gov.

Supports two modes:
1. Bulk CSV download (recommended): Downloads full dataset from data.www.sbir.gov
2. API mode: Uses the SBIR.gov API (rate-limited)

Usage:
    # Bulk download mode (recommended)
    python -m scrapers.sbir --start-year 2024 --end-year 2024 --limit 100

    # API mode (slower, rate-limited)
    python -m scrapers.sbir --api --start-year 2024 --end-year 2024 --limit 100

    # Filter by agency
    python -m scrapers.sbir --agency "Air Force" --phase 2 --limit 50
"""

import argparse
import csv
import io
import logging
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Optional

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Entity, EntityType, FundingEvent, FundingEventType


# Configure logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "sbir.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# Bulk download URLs
BULK_DOWNLOAD_URL = "https://data.www.sbir.gov/awarddatapublic/award_data.csv"
BULK_DOWNLOAD_NO_ABSTRACT_URL = "https://data.www.sbir.gov/mod_awarddatapublic_no_abstract/award_data_no_abstract.csv"

# DoD branches as they appear in the data
DOD_BRANCHES = [
    "Air Force",
    "Army",
    "Navy",
    "DARPA",
    "MDA",
    "SOCOM",
    "DLA",
    "DTRA",
    "NGA",
    "OSD",
    "Space Force",
    "CBD",
    "DISA",
    "DHP",
    "DCAA",
    "USSOCOM",
    "Missile Defense Agency",
    "Defense Advanced Research Projects Agency",
    "Defense Logistics Agency",
    "Defense Threat Reduction Agency",
    "National Geospatial-Intelligence Agency",
    "Office of the Secretary of Defense",
    "Chemical and Biological Defense Program",
    "Defense Information Systems Agency",
    "Defense Health Program",
    "AFRL",
    "AFMC",
    "AFOSR",
    "SPAWAR",
    "NAVAIR",
    "NAVSEA",
    "ONR",
    "NSWC",
]

# Technology keywords for tagging
TECHNOLOGY_KEYWORDS = {
    "ai_ml": [
        "artificial intelligence", "machine learning", "deep learning", "neural network",
        "computer vision", "natural language processing", "nlp", "reinforcement learning",
        "predictive analytics", "cognitive", "autonomous decision",
    ],
    "autonomy": [
        "autonomous", "unmanned", "uav", "ugv", "usv", "uuv", "drone", "robotics",
        "robot", "self-driving", "automated", "swarm",
    ],
    "cyber": [
        "cyber", "cybersecurity", "encryption", "cryptograph", "malware", "intrusion",
        "network security", "zero trust", "penetration", "vulnerability",
    ],
    "space": [
        "satellite", "spacecraft", "orbital", "space-based", "launch vehicle",
        "propulsion", "cislunar", "leo", "geo", "small sat", "cubesat",
    ],
    "quantum": [
        "quantum", "qubit", "quantum computing", "quantum sensing", "quantum communication",
        "quantum cryptography", "post-quantum",
    ],
    "hypersonics": [
        "hypersonic", "scramjet", "mach 5", "high-speed", "thermal protection",
        "hypersonic glide", "boost-glide",
    ],
    "biotech": [
        "biotech", "biotechnology", "synthetic biology", "gene", "crispr", "biologic",
        "pharmaceutical", "vaccine", "therapeutic", "biomaterial", "biodefense",
    ],
    "sensors": [
        "sensor", "radar", "lidar", "sonar", "electro-optical", "infrared", "rf",
        "imaging", "detection", "surveillance", "reconnaissance", "isr",
    ],
    "communications": [
        "5g", "6g", "communications", "datalink", "mesh network", "satcom",
        "software defined radio", "sdr", "tactical network", "resilient comms",
    ],
    "directed_energy": [
        "directed energy", "laser", "high-energy laser", "hel", "microwave",
        "high-powered microwave", "hpm", "particle beam",
    ],
    "materials": [
        "metamaterial", "composite", "advanced material", "lightweight", "armor",
        "ceramic", "carbon fiber", "additive manufacturing", "3d printing",
    ],
    "electronics": [
        "semiconductor", "microelectronics", "photonics", "fpga", "asic", "rf",
        "power electronics", "gan", "sic", "silicon carbide",
    ],
    "c4isr": [
        "c4isr", "command and control", "c2", "battle management", "situational awareness",
        "targeting", "mission planning", "decision support",
    ],
    "ew": [
        "electronic warfare", "ew", "jamming", "spoofing", "spectrum", "sigint",
        "elint", "comint", "spectrum management",
    ],
}


@dataclass
class ScraperStats:
    """Statistics from a scraping run."""
    awards_fetched: int = 0
    awards_inserted: int = 0
    awards_updated: int = 0
    awards_skipped: int = 0
    entities_created: int = 0
    entities_existing: int = 0
    entities_updated: int = 0
    errors: int = 0
    api_requests: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    technology_tags_added: int = 0

    def log_summary(self):
        """Log summary statistics."""
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        logger.info("=" * 60)
        logger.info("SCRAPING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Duration: {duration:.1f} seconds")
        logger.info(f"API/Download requests: {self.api_requests}")
        logger.info(f"Awards fetched: {self.awards_fetched}")
        logger.info(f"  - Inserted: {self.awards_inserted}")
        logger.info(f"  - Updated: {self.awards_updated}")
        logger.info(f"  - Skipped: {self.awards_skipped}")
        logger.info(f"Entities: {self.entities_created} new, {self.entities_existing} existing, {self.entities_updated} updated")
        logger.info(f"Technology tags added: {self.technology_tags_added}")
        logger.info(f"Errors: {self.errors}")
        logger.info("=" * 60)


class SBIRScraper:
    """
    Scraper for SBIR.gov awards.

    Supports two modes:
    - Bulk download: Downloads full CSV dataset (recommended)
    - API: Uses the SBIR.gov API (rate-limited)
    """

    BASE_URL = "https://api.www.sbir.gov/public/api"
    AWARDS_ENDPOINT = "/awards"

    # Rate limiting: be very conservative with government sites
    MIN_REQUEST_INTERVAL = 2.0  # 2 seconds between requests for API mode

    def __init__(
        self,
        db: Session,
        batch_size: int = 100,
        use_api: bool = False,
        include_abstracts: bool = True,
    ):
        """
        Initialize the scraper.

        Args:
            db: Database session
            batch_size: Number of records per database commit
            use_api: If True, use API instead of bulk download
            include_abstracts: If True, download version with abstracts (290MB vs 65MB)
        """
        self.db = db
        self.batch_size = batch_size
        self.use_api = use_api
        self.include_abstracts = include_abstracts
        self.stats = ScraperStats()
        self.last_request_time = 0

        # Setup session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=3,
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

    def _download_bulk_csv(self) -> Optional[Iterator[dict]]:
        """
        Download and stream the bulk CSV file.

        Returns:
            Iterator of award dicts or None on failure
        """
        url = BULK_DOWNLOAD_URL if self.include_abstracts else BULK_DOWNLOAD_NO_ABSTRACT_URL

        logger.info(f"Downloading bulk CSV from {url}...")
        logger.info("(This may take a few minutes for the 290MB file)")
        self.stats.api_requests += 1

        try:
            response = self.session.get(
                url,
                headers={
                    "User-Agent": "DefenseAlphaIntelligence/1.0 (Research)",
                },
                timeout=600,  # 10 minute timeout for large file
                stream=True,
            )
            response.raise_for_status()

            # Get content length if available
            content_length = response.headers.get('Content-Length')
            if content_length:
                logger.info(f"Download size: {int(content_length) / 1024 / 1024:.1f} MB")

            # Stream and parse CSV - decode bytes to string
            def line_generator():
                for line in response.iter_lines():
                    if line:
                        yield line.decode('utf-8', errors='replace')

            lines = line_generator()

            # Read header
            header_line = next(lines, None)
            if not header_line:
                logger.error("Empty CSV file")
                return None

            # Parse header to get field names
            header_reader = csv.reader(io.StringIO(header_line))
            fieldnames = next(header_reader)

            logger.info(f"CSV columns: {len(fieldnames)}")

            # Create generator for remaining lines
            def row_generator():
                for line in lines:
                    if line:
                        try:
                            row_reader = csv.reader(io.StringIO(line))
                            values = next(row_reader, None)
                            if values and len(values) == len(fieldnames):
                                yield dict(zip(fieldnames, values))
                        except Exception as e:
                            # Skip malformed rows
                            continue

            return row_generator()

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download bulk CSV: {e}")
            self.stats.errors += 1
            return None

    def _make_api_request(self, params: dict) -> Optional[list]:
        """
        Make API request with rate limiting and error handling.

        Args:
            params: Query parameters

        Returns:
            Response JSON list or None on failure
        """
        self._rate_limit()
        self.stats.api_requests += 1

        url = f"{self.BASE_URL}{self.AWARDS_ENDPOINT}"

        try:
            response = self.session.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "DefenseAlphaIntelligence/1.0 (Research)",
                },
                timeout=60,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            self.stats.errors += 1
            return None

    def _extract_technology_tags(self, award: dict) -> list[str]:
        """
        Extract technology tags from award keywords and abstract.

        Args:
            award: Award data

        Returns:
            List of technology tag strings
        """
        tags = set()

        # Combine text sources for analysis (handle both CSV and API field names)
        text_sources = [
            award.get("Abstract", "") or award.get("abstract", ""),
            award.get("Award Title", "") or award.get("award_title", ""),
            award.get("Research Keywords", "") or award.get("research_keywords", ""),
        ]
        combined_text = " ".join(str(s) for s in text_sources if s).lower()

        # Check for each technology category
        for tag_name, keywords in TECHNOLOGY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in combined_text:
                    tags.add(tag_name)
                    break

        return sorted(list(tags))

    def _parse_phase(self, phase_str: Optional[str]) -> Optional[FundingEventType]:
        """
        Parse phase string to FundingEventType.

        Args:
            phase_str: Phase string (e.g., "Phase I", "Phase II", "1", "2")

        Returns:
            FundingEventType or None
        """
        if not phase_str:
            return None

        phase_str = str(phase_str).lower().strip()

        if "1" in phase_str or "i" == phase_str or phase_str.endswith(" i"):
            return FundingEventType.SBIR_PHASE_1
        elif "2" in phase_str or "ii" in phase_str:
            return FundingEventType.SBIR_PHASE_2
        elif "3" in phase_str or "iii" in phase_str:
            return FundingEventType.SBIR_PHASE_3

        return FundingEventType.SBIR_PHASE_1  # Default to Phase 1

    def _get_or_create_entity(
        self,
        company_name: str,
        location: Optional[str] = None,
        duns_number: Optional[str] = None,
        uei: Optional[str] = None,
    ) -> Entity:
        """
        Get existing entity or create new one.

        Args:
            company_name: Company name from award
            location: City, State location
            duns_number: DUNS number if available
            uei: UEI identifier if available

        Returns:
            Entity record
        """
        if not company_name:
            company_name = "Unknown Contractor"

        # Clean up name
        company_name = company_name.strip()

        # Try to find by DUNS first (most reliable)
        entity = None
        if duns_number:
            duns_clean = duns_number.strip()
            if duns_clean:
                entity = self.db.query(Entity).filter(
                    Entity.duns_number == duns_clean,
                    Entity.merged_into_id.is_(None),
                ).first()

        # Try by name if no DUNS match
        if not entity:
            entity = self.db.query(Entity).filter(
                Entity.canonical_name == company_name,
                Entity.merged_into_id.is_(None),
            ).first()

        if entity:
            self.stats.entities_existing += 1

            # Update entity with additional info if we have it
            updated = False
            if duns_number and not entity.duns_number:
                entity.duns_number = duns_number.strip()
                updated = True
            if location and not entity.headquarters_location:
                entity.headquarters_location = location
                updated = True

            if updated:
                self.stats.entities_updated += 1

            return entity

        # Create new entity
        entity = Entity(
            canonical_name=company_name,
            name_variants=[],
            entity_type=EntityType.STARTUP,  # Default for SBIR companies
            duns_number=duns_number.strip() if duns_number else None,
            headquarters_location=location,
            technology_tags=[],
        )
        self.db.add(entity)
        self.db.flush()  # Get the ID without committing
        self.stats.entities_created += 1

        return entity

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse date string from data."""
        if not date_str:
            return None

        date_str = str(date_str).strip()
        if not date_str:
            return None

        try:
            # Try common formats
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%d-%b-%Y", "%Y"]:
                try:
                    return datetime.strptime(date_str[:min(len(date_str), 10)], fmt[:min(len(fmt), 10)]).date()
                except ValueError:
                    continue

            # Try just year
            if len(date_str) == 4 and date_str.isdigit():
                return date(int(date_str), 1, 1)

            return None
        except Exception:
            return None

    def _parse_year(self, year_str: Optional[str]) -> Optional[int]:
        """Parse year from string."""
        if not year_str:
            return None
        try:
            year_str = str(year_str).strip()
            if year_str.isdigit() and len(year_str) == 4:
                return int(year_str)
            return None
        except Exception:
            return None

    def _parse_amount(self, amount) -> Optional[Decimal]:
        """Parse award amount to Decimal."""
        if amount is None:
            return None

        try:
            # Handle string amounts with currency symbols
            if isinstance(amount, str):
                amount = amount.replace("$", "").replace(",", "").strip()
                if not amount:
                    return None
            return Decimal(str(amount))
        except (InvalidOperation, ValueError):
            return None

    def _format_location(self, award: dict) -> Optional[str]:
        """Format location from award data."""
        parts = []
        # Handle both CSV and API field names
        city = award.get("City", "") or award.get("city", "")
        state = award.get("State", "") or award.get("state", "")
        if city:
            parts.append(city)
        if state:
            parts.append(state)
        return ", ".join(parts) if parts else None

    def _get_award_identifier(self, award: dict) -> Optional[str]:
        """
        Get unique identifier for an award.

        Priority:
        1. Contract/grant number
        2. Agency tracking number
        3. Combination of company + year + title (fallback)
        """
        # Try contract number first (CSV: Contract, API: contract)
        contract_num = (
            award.get("Contract", "") or
            award.get("contract", "") or
            award.get("Contract Number", "") or
            award.get("contract_number", "")
        )
        if contract_num and str(contract_num).strip():
            return str(contract_num).strip()

        # Try agency tracking number
        agency_tracking = (
            award.get("Agency Tracking Number", "") or
            award.get("agency_tracking_number", "")
        )
        if agency_tracking and str(agency_tracking).strip():
            return str(agency_tracking).strip()

        # Fallback: create composite key
        company = award.get("Company", "") or award.get("company", "")
        year = award.get("Award Year", "") or award.get("award_year", "")
        title = (award.get("Award Title", "") or award.get("award_title", ""))[:50] if (award.get("Award Title") or award.get("award_title")) else ""

        if company and year:
            return f"{company}_{year}_{title}".strip()

        return None

    def _is_dod_award(self, award: dict) -> bool:
        """Check if award is from a DoD agency."""
        # Handle both CSV and API field names
        agency = (award.get("Agency", "") or award.get("agency", "")).upper()
        branch = award.get("Branch", "") or award.get("branch", "")

        # Check agency
        if agency == "DOD":
            return True

        # Check branch against known DoD branches
        if branch:
            branch_upper = branch.upper()
            for dod_branch in DOD_BRANCHES:
                if dod_branch.upper() in branch_upper or branch_upper in dod_branch.upper():
                    return True

        return False

    def _filter_by_branch(self, award: dict, agency_filter: Optional[str]) -> bool:
        """Check if award matches the agency/branch filter."""
        if not agency_filter:
            return True

        branch = award.get("Branch", "") or award.get("branch", "")
        if not branch:
            return False

        # Normalize for comparison
        agency_filter_upper = agency_filter.upper()
        branch_upper = branch.upper()

        # Direct match
        if agency_filter_upper in branch_upper:
            return True

        # Handle abbreviations
        abbreviation_map = {
            "DARPA": ["DARPA", "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY"],
            "MDA": ["MDA", "MISSILE DEFENSE AGENCY"],
            "SOCOM": ["SOCOM", "USSOCOM", "SPECIAL OPERATIONS"],
            "AIR FORCE": ["AIR FORCE", "USAF", "AF", "AFRL", "AFMC", "AFOSR"],
            "ARMY": ["ARMY"],
            "NAVY": ["NAVY", "USN", "NAVAIR", "NAVSEA", "ONR", "NSWC", "SPAWAR"],
            "SPACE FORCE": ["SPACE FORCE", "USSF"],
        }

        if agency_filter_upper in abbreviation_map:
            for variant in abbreviation_map[agency_filter_upper]:
                if variant in branch_upper:
                    return True

        return False

    def _filter_by_year(self, award: dict, start_year: int, end_year: int) -> bool:
        """Check if award is within the year range."""
        year_str = award.get("Award Year", "") or award.get("award_year", "")
        year = self._parse_year(year_str)
        if year is None:
            return False
        return start_year <= year <= end_year

    def _process_award(
        self,
        award: dict,
        seen_awards: set,
        start_year: int,
        end_year: int,
        agency_filter: Optional[str],
        phase_filter: Optional[int]
    ) -> Optional[FundingEvent]:
        """
        Process a single award record.

        Args:
            award: Award data
            seen_awards: Set of award identifiers already processed
            start_year: Start year filter
            end_year: End year filter
            agency_filter: Optional agency/branch filter
            phase_filter: Optional phase filter (1, 2, or 3)

        Returns:
            FundingEvent record or None if skipped/error
        """
        try:
            # Check year range
            if not self._filter_by_year(award, start_year, end_year):
                self.stats.awards_skipped += 1
                return None

            # Check if DoD award
            if not self._is_dod_award(award):
                self.stats.awards_skipped += 1
                return None

            # Check agency/branch filter
            if agency_filter and not self._filter_by_branch(award, agency_filter):
                self.stats.awards_skipped += 1
                return None

            # Parse phase
            phase_str = award.get("Phase", "") or award.get("phase", "")
            phase_type = self._parse_phase(phase_str)

            # Check phase filter
            if phase_filter:
                phase_map = {
                    1: FundingEventType.SBIR_PHASE_1,
                    2: FundingEventType.SBIR_PHASE_2,
                    3: FundingEventType.SBIR_PHASE_3,
                }
                if phase_type != phase_map.get(phase_filter):
                    self.stats.awards_skipped += 1
                    return None

            # Get unique identifier
            award_id = self._get_award_identifier(award)
            if not award_id:
                logger.warning("Skipping award with no identifier")
                self.stats.awards_skipped += 1
                return None

            # Skip if we've already seen this award in this batch
            if award_id in seen_awards:
                self.stats.awards_skipped += 1
                return None
            seen_awards.add(award_id)

            # Check for existing award in database
            existing = self.db.query(FundingEvent).filter(
                FundingEvent.source == f"sbir:{award_id}"
            ).first()

            if existing:
                # Update existing award
                self._update_funding_event(existing, award)
                self.stats.awards_updated += 1
                return existing

            # Get or create entity for company
            company_name = award.get("Company", "") or award.get("company", "") or "Unknown"
            location = self._format_location(award)
            duns = award.get("DUNS", "") or award.get("duns", "")
            uei = award.get("UEI", "") or award.get("uei", "")

            entity = self._get_or_create_entity(company_name, location, duns, uei)

            # Extract and update technology tags
            new_tags = self._extract_technology_tags(award)
            if new_tags:
                existing_tags = entity.technology_tags or []
                combined_tags = list(set(existing_tags + new_tags))
                if combined_tags != existing_tags:
                    entity.technology_tags = combined_tags
                    self.stats.technology_tags_added += len(set(new_tags) - set(existing_tags))

            # Parse dates
            award_date_str = (
                award.get("Proposal Award Date", "") or
                award.get("proposal_award_date", "") or
                award.get("Award Year", "") or
                award.get("award_year", "")
            )
            award_date = self._parse_date(award_date_str)

            # Parse amount
            amount_str = award.get("Award Amount", "") or award.get("award_amount", "")
            amount = self._parse_amount(amount_str)

            # Build investors/awarders info
            awarders = []
            agency = award.get("Agency", "") or award.get("agency", "")
            branch = award.get("Branch", "") or award.get("branch", "")
            if agency:
                awarders.append(agency)
            if branch:
                awarders.append(branch)

            # Create funding event
            funding_event = FundingEvent(
                entity_id=entity.id,
                event_type=phase_type or FundingEventType.SBIR_PHASE_1,
                amount=amount,
                event_date=award_date,
                source=f"sbir:{award_id}",
                investors_awarders=awarders,
                round_stage=phase_str,
                raw_data=award,
            )

            self.db.add(funding_event)
            self.stats.awards_inserted += 1

            return funding_event

        except Exception as e:
            logger.error(f"Error processing award: {e}")
            self.stats.errors += 1
            self.db.rollback()
            return None

    def _update_funding_event(self, event: FundingEvent, award: dict):
        """Update existing funding event with new data."""
        amount_str = award.get("Award Amount", "") or award.get("award_amount", "")
        amount = self._parse_amount(amount_str)
        if amount is not None:
            event.amount = amount

        event.raw_data = award

    def scrape(
        self,
        start_year: int,
        end_year: int,
        agency: Optional[str] = None,
        phase: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> ScraperStats:
        """
        Main scraping function.

        Args:
            start_year: Start year (e.g., 2015)
            end_year: End year (e.g., 2024)
            agency: Optional specific agency filter (e.g., 'Air Force', 'DARPA')
            phase: Optional phase filter (1, 2, or 3)
            limit: Optional max awards to fetch

        Returns:
            ScraperStats with results
        """
        self.stats = ScraperStats()
        self.stats.start_time = datetime.now()

        mode = "API" if self.use_api else "Bulk CSV Download"
        logger.info("=" * 60)
        logger.info(f"SBIR.GOV SCRAPER - STARTING ({mode})")
        logger.info("=" * 60)
        logger.info(f"Year range: {start_year} to {end_year}")
        logger.info(f"Agency filter: {agency or 'All DoD'}")
        logger.info(f"Phase filter: {phase or 'All phases'}")
        logger.info(f"Limit: {limit or 'None'}")
        logger.info("=" * 60)

        if self.use_api:
            self._scrape_api(start_year, end_year, agency, phase, limit)
        else:
            self._scrape_bulk(start_year, end_year, agency, phase, limit)

        self.stats.end_time = datetime.now()
        self.stats.log_summary()

        return self.stats

    def _scrape_bulk(
        self,
        start_year: int,
        end_year: int,
        agency: Optional[str],
        phase: Optional[int],
        limit: Optional[int],
    ):
        """Scrape using bulk CSV download."""
        # Download CSV
        rows = self._download_bulk_csv()
        if rows is None:
            logger.error("Failed to download bulk CSV")
            return

        total_fetched = 0
        pending_commits = 0
        seen_awards = set()
        rows_processed = 0

        for row in rows:
            rows_processed += 1

            if limit and total_fetched >= limit:
                break

            event = self._process_award(row, seen_awards, start_year, end_year, agency, phase)
            if event:
                total_fetched += 1
                pending_commits += 1

            # Progress logging
            if rows_processed % 10000 == 0:
                logger.info(f"Progress: {rows_processed} rows processed, {total_fetched} DoD awards found")

            # Batch commit
            if pending_commits >= self.batch_size:
                try:
                    self.db.commit()
                    pending_commits = 0
                except Exception as e:
                    logger.error(f"Batch commit failed: {e}")
                    self.db.rollback()
                    self.stats.errors += 1

        self.stats.awards_fetched = total_fetched

        # Final commit
        try:
            self.db.commit()
        except Exception as e:
            logger.error(f"Final commit failed: {e}")
            self.db.rollback()
            self.stats.errors += 1

        logger.info(f"Processed {rows_processed} total rows from CSV")

    def _scrape_api(
        self,
        start_year: int,
        end_year: int,
        agency: Optional[str],
        phase: Optional[int],
        limit: Optional[int],
    ):
        """Scrape using the API (rate-limited)."""
        total_fetched = 0
        pending_commits = 0
        seen_awards = set()

        # Iterate through each year
        for year in range(start_year, end_year + 1):
            if limit and total_fetched >= limit:
                break

            logger.info(f"Fetching year {year}...")

            offset = 0
            rows_per_request = 100

            while True:
                if limit and total_fetched >= limit:
                    break

                # Build request parameters
                params = {
                    "agency": "DOD",
                    "year": year,
                    "rows": rows_per_request,
                    "start": offset,
                }

                logger.info(f"  Fetching offset {offset}...")
                results = self._make_api_request(params)

                if results is None:
                    logger.error(f"Failed to fetch year {year} offset {offset}")
                    break

                if not results:
                    logger.info(f"  No more results for year {year}")
                    break

                # Process each award
                for award in results:
                    if limit and total_fetched >= limit:
                        break

                    event = self._process_award(award, seen_awards, start_year, end_year, agency, phase)
                    if event:
                        total_fetched += 1
                        pending_commits += 1

                        if total_fetched % 50 == 0:
                            logger.info(f"  Progress: {total_fetched} awards processed")

                    # Batch commit
                    if pending_commits >= self.batch_size:
                        try:
                            self.db.commit()
                            pending_commits = 0
                        except Exception as e:
                            logger.error(f"Batch commit failed: {e}")
                            self.db.rollback()
                            self.stats.errors += 1

                self.stats.awards_fetched = total_fetched

                if len(results) < rows_per_request:
                    logger.info(f"  Completed year {year}")
                    break

                offset += rows_per_request

        # Final commit
        try:
            self.db.commit()
        except Exception as e:
            logger.error(f"Final commit failed: {e}")
            self.db.rollback()
            self.stats.errors += 1


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scrape SBIR/STTR awards from SBIR.gov"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2015,
        help="Start year (default: 2015)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=date.today().year,
        help="End year (default: current year)",
    )
    parser.add_argument(
        "--agency",
        type=str,
        help="Filter by DoD branch (e.g., 'Air Force', 'Army', 'Navy', 'DARPA', 'MDA', 'SOCOM')",
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3],
        help="Filter by phase (1, 2, or 3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of awards to fetch (for testing)",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Use API instead of bulk download (slower, may be rate-limited)",
    )
    parser.add_argument(
        "--no-abstracts",
        action="store_true",
        help="Download smaller CSV without abstracts (65MB vs 290MB)",
    )

    args = parser.parse_args()

    # Validate years
    if args.start_year > args.end_year:
        logger.error("Start year must be <= end year")
        sys.exit(1)

    if args.start_year < 2000:
        logger.error("Start year must be >= 2000")
        sys.exit(1)

    # Create database session
    db = SessionLocal()

    try:
        scraper = SBIRScraper(
            db=db,
            use_api=args.api,
            include_abstracts=not args.no_abstracts,
        )

        stats = scraper.scrape(
            start_year=args.start_year,
            end_year=args.end_year,
            agency=args.agency,
            phase=args.phase,
            limit=args.limit,
        )

        # Exit with error code if there were errors
        if stats.errors > 0:
            sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
