#!/usr/bin/env python3
"""
SEC EDGAR Form D Scraper

Scrapes Regulation D (Form D) filings from SEC EDGAR to capture
private fundraising by defense technology companies.

Uses DERA (Division of Economic and Risk Analysis) quarterly bulk data sets
rather than scraping individual filings. Each quarter's zip contains
pre-parsed TSV files with all Form D fields.

Two-pass entity matching:
  Pass 1: Match issuer names against existing entities (high confidence)
  Pass 2: Pull defense-relevant filings by SIC code / industry group + keywords
          and create new entities for unmatched defense companies

Usage:
    # Full historical backfill (DERA data available from 2008 Q1)
    python scrapers/sec_edgar.py --start-date 2008-01-01

    # Backfill pre-2019 for signal-response benchmarks
    python scrapers/sec_edgar.py --start-date 2012-01-01 --end-date 2019-12-31

    # Single quarter test
    python scrapers/sec_edgar.py --start-date 2024-07-01 --end-date 2024-09-30 --limit 50

    # Only match existing entities (skip Pass 2)
    python scrapers/sec_edgar.py --start-date 2024-01-01 --match-only
"""

import argparse
import csv
import io
import json
import logging
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import requests
from rapidfuzz import fuzz, process
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
        logging.FileHandler(LOG_DIR / "sec_edgar.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# DERA bulk data URL pattern
DERA_BASE_URL = "https://www.sec.gov/files/structureddata/data/form-d-data-sets"

# SEC requires a declared User-Agent
USER_AGENT = "DefenseAlpha/1.0 research@defensealpha.com"

# Defense-relevant SIC code ranges
DEFENSE_SIC_RANGES = [
    (3720, 3729),  # Aircraft & parts
    (3760, 3769),  # Guided missiles, space vehicles
    (3812, 3812),  # Search/navigation equipment
    (7370, 7379),  # Software & data processing
]

# Defense keywords for name-based matching (Pass 2 fallback)
DEFENSE_KEYWORDS = [
    "defense", "defence", "aerospace", "military", "tactical", "unmanned",
    "drone", "satellite", "radar", "missile", "hypersonic", "cyber",
    "intelligence", "surveillance", "reconnaissance", "autonomous",
    "quantum", "space", "avionics", "propulsion", "munitions", "armament",
    "directed energy", "laser weapon", "c4isr", "electronic warfare",
    "sonar", "stealth", "counter-uas", "anti-drone",
]

# Industry groups from Form D that could contain defense companies
DEFENSE_INDUSTRY_GROUPS = {"Technology", "Manufacturing"}

# Corporate suffixes to strip for name normalization
CORPORATE_SUFFIXES = [
    r"\s+Incorporated$", r"\s+Corporation$", r"\s+Limited$", r"\s+Company$",
    r"\s+Inc\.?$", r"\s+Corp\.?$", r"\s+LLC\.?$", r"\s+L\.L\.C\.?$",
    r"\s+Ltd\.?$", r"\s+LLP\.?$", r"\s+L\.L\.P\.?$", r"\s+LP\.?$",
    r"\s+L\.P\.?$", r"\s+Co\.?$", r"\s+PC\.?$", r"\s+P\.C\.?$",
    r"\s+PLLC\.?$",
    r",\s*Inc\.?$", r",\s*LLC\.?$", r",\s*Corp\.?$", r",\s*$",
]


@dataclass
class ScraperStats:
    """Statistics from a scraping run."""
    filings_fetched: int = 0
    filings_inserted: int = 0
    filings_updated: int = 0
    filings_skipped: int = 0
    entities_matched: int = 0
    entities_created: int = 0
    errors: int = 0
    quarters_downloaded: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def log_summary(self):
        duration = 0
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("SEC EDGAR FORM D SCRAPER - RESULTS")
        logger.info("=" * 60)
        logger.info(f"Duration: {duration:.1f}s")
        logger.info(f"Quarters downloaded: {self.quarters_downloaded}")
        logger.info(f"Filings fetched: {self.filings_fetched}")
        logger.info(f"Filings inserted: {self.filings_inserted}")
        logger.info(f"Filings updated: {self.filings_updated}")
        logger.info(f"Filings skipped: {self.filings_skipped}")
        logger.info(f"Entities matched (Pass 1): {self.entities_matched}")
        logger.info(f"Entities created (Pass 2): {self.entities_created}")
        logger.info(f"Errors: {self.errors}")
        logger.info("=" * 60)


def _normalize_name(name: str) -> str:
    """Normalize company name for comparison."""
    if not name:
        return ""
    normalized = name.strip()
    for _ in range(3):
        prev = normalized
        for pattern in CORPORATE_SUFFIXES:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
        normalized = normalized.strip()
        if normalized == prev:
            break
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.lower()


def _parse_amount(value: str) -> Optional[Decimal]:
    """Parse amount from DERA TSV, handling 'Indefinite' and empty values."""
    if not value or value.strip().lower() in ("", "indefinite"):
        return None
    try:
        cleaned = value.replace("$", "").replace(",", "").strip()
        if not cleaned:
            return None
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _parse_date_str(date_str: str) -> Optional[date]:
    """Parse date from DERA TSV (multiple formats)."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str[:10], fmt[:10]).date()
        except ValueError:
            continue
    return None


def _estimate_round_stage(amount: Optional[Decimal]) -> Optional[str]:
    """Estimate funding round stage from Reg D amount."""
    if amount is None or amount <= 0:
        return None
    amt = float(amount)
    if amt < 2_000_000:
        return "seed"
    elif amt < 15_000_000:
        return "series_a"
    elif amt < 50_000_000:
        return "series_b"
    elif amt < 150_000_000:
        return "series_c"
    else:
        return "growth"


def _sic_is_defense_relevant(sic_code: str) -> bool:
    """Check if a SIC code falls within defense-relevant ranges."""
    if not sic_code or not sic_code.strip():
        return False
    try:
        code = int(sic_code.strip())
    except ValueError:
        return False
    return any(lo <= code <= hi for lo, hi in DEFENSE_SIC_RANGES)


def _name_has_defense_keyword(name: str) -> bool:
    """Check if issuer name contains defense-relevant keywords."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in DEFENSE_KEYWORDS)


class SECEdgarScraper:
    """Scrapes SEC EDGAR Form D filings via DERA bulk data."""

    MIN_REQUEST_INTERVAL = 0.5  # Conservative for SEC

    def __init__(self, db: Session, batch_size: int = 100):
        self.db = db
        self.batch_size = batch_size
        self.stats = ScraperStats()
        self.last_request_time = 0.0

        # HTTP session with retry
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)

        # Build entity name index for matching
        self._entity_index: dict[str, Entity] = {}
        self._entity_names: list[tuple[str, str]] = []
        self._build_entity_index()

    def _build_entity_index(self):
        """Load all entities into memory for fast name matching."""
        entities = self.db.query(Entity).filter(
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            norm = _normalize_name(entity.canonical_name)
            if norm:
                self._entity_index[norm] = entity
                self._entity_names.append((norm, entity.id))

            # Also index name variants
            for variant in (entity.name_variants or []):
                vnorm = _normalize_name(variant)
                if vnorm and vnorm not in self._entity_index:
                    self._entity_index[vnorm] = entity
                    self._entity_names.append((vnorm, entity.id))

        logger.info(f"Entity index built: {len(self._entity_index)} normalized names from {len(entities)} entities")

    def _rate_limit(self):
        """Enforce rate limiting for SEC requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self.last_request_time = time.time()

    def _get_quarters(self, start_date: date, end_date: date) -> list[tuple[int, int]]:
        """Return list of (year, quarter) tuples covering the date range."""
        quarters = []
        year = start_date.year
        quarter = (start_date.month - 1) // 3 + 1

        while True:
            q_end_month = quarter * 3
            q_end_date = date(year, q_end_month, 1)
            if q_end_date > end_date and date(year, (quarter - 1) * 3 + 1, 1) > end_date:
                break
            quarters.append((year, quarter))
            quarter += 1
            if quarter > 4:
                quarter = 1
                year += 1
            if year > end_date.year + 1:
                break

        return quarters

    def _download_quarter(self, year: int, quarter: int) -> list[dict]:
        """
        Download and parse a DERA quarterly Form D data set.

        Returns list of merged filing dicts (ISSUERS + OFFERING + FORMDSUBMISSION).
        """
        url = f"{DERA_BASE_URL}/{year}q{quarter}_d.zip"
        logger.info(f"Downloading {url}...")

        self._rate_limit()

        try:
            resp = self.session.get(url, timeout=60)
        except requests.RequestException as e:
            logger.error(f"Failed to download {url}: {e}")
            self.stats.errors += 1
            return []

        if resp.status_code == 404:
            logger.warning(f"Quarter {year}Q{quarter} not available (404)")
            return []

        if resp.status_code != 200:
            logger.error(f"Unexpected status {resp.status_code} for {url}")
            self.stats.errors += 1
            return []

        self.stats.quarters_downloaded += 1

        # Parse zip
        try:
            z = zipfile.ZipFile(io.BytesIO(resp.content))
        except zipfile.BadZipFile:
            logger.error(f"Bad zip file for {year}Q{quarter}")
            self.stats.errors += 1
            return []

        # Find the TSV files (they're in a subdirectory like 2024Q3_d/)
        file_map = {}
        for name in z.namelist():
            basename = name.split("/")[-1].upper()
            if basename in ("ISSUERS.TSV", "OFFERING.TSV", "FORMDSUBMISSION.TSV", "RELATEDPERSONS.TSV"):
                file_map[basename] = name

        required = {"ISSUERS.TSV", "OFFERING.TSV", "FORMDSUBMISSION.TSV"}
        if not required.issubset(file_map.keys()):
            logger.error(f"Missing TSV files in {year}Q{quarter} zip. Found: {list(file_map.keys())}")
            self.stats.errors += 1
            return []

        # Parse each TSV into dicts keyed by accession number
        def parse_tsv(filename: str) -> dict[str, dict]:
            with z.open(file_map[filename]) as f:
                content = f.read().decode("utf-8", errors="replace")
                reader = csv.DictReader(io.StringIO(content), delimiter="\t")
                result = {}
                for row in reader:
                    acc = row.get("ACCESSIONNUMBER", "").strip()
                    if acc:
                        result[acc] = row
                return result

        def parse_tsv_multi(filename: str) -> dict[str, list[dict]]:
            """Parse TSV where multiple rows can share an accession number."""
            with z.open(file_map[filename]) as f:
                content = f.read().decode("utf-8", errors="replace")
                reader = csv.DictReader(io.StringIO(content), delimiter="\t")
                result: dict[str, list[dict]] = {}
                for row in reader:
                    acc = row.get("ACCESSIONNUMBER", "").strip()
                    if acc:
                        result.setdefault(acc, []).append(row)
                return result

        issuers = parse_tsv("ISSUERS.TSV")
        offerings = parse_tsv("OFFERING.TSV")
        submissions = parse_tsv("FORMDSUBMISSION.TSV")

        # RELATEDPERSONS has multiple rows per filing (directors, officers, promoters)
        related_persons: dict[str, list[dict]] = {}
        if "RELATEDPERSONS.TSV" in file_map:
            related_persons = parse_tsv_multi("RELATEDPERSONS.TSV")

        # Merge on accession number
        filings = []
        for acc, offering in offerings.items():
            merged = {"ACCESSIONNUMBER": acc}
            merged.update({f"O_{k}": v for k, v in offering.items() if k != "ACCESSIONNUMBER"})

            issuer = issuers.get(acc, {})
            merged.update({f"I_{k}": v for k, v in issuer.items() if k != "ACCESSIONNUMBER"})

            submission = submissions.get(acc, {})
            merged.update({f"S_{k}": v for k, v in submission.items() if k != "ACCESSIONNUMBER"})

            # Attach related persons (directors, officers, promoters)
            persons = related_persons.get(acc, [])
            if persons:
                merged["_related_persons"] = [
                    {
                        "first_name": p.get("RELATEDPERSONFIRSTNAME", "").strip(),
                        "last_name": p.get("RELATEDPERSONLASTNAME", "").strip(),
                        "relationships": p.get("RELATEDPERSONRELATIONSHIPS", "").strip(),
                    }
                    for p in persons
                ]

            filings.append(merged)

        logger.info(f"  {year}Q{quarter}: {len(filings)} filings parsed")
        if related_persons:
            total_persons = sum(len(v) for v in related_persons.values())
            logger.info(f"  {year}Q{quarter}: {total_persons} related persons parsed")
        return filings

    def _match_existing_entity(
        self, issuer_name: str, state: Optional[str] = None
    ) -> Optional[Entity]:
        """
        Pass 1: Match issuer name against existing entities.

        Returns matched Entity or None.
        """
        norm = _normalize_name(issuer_name)
        if not norm:
            return None

        # Exact match
        if norm in self._entity_index:
            return self._entity_index[norm]

        # Fuzzy match using rapidfuzz
        if not self._entity_names:
            return None

        names_only = [n for n, _ in self._entity_names]
        result = process.extractOne(
            norm, names_only, scorer=fuzz.token_sort_ratio, score_cutoff=85,
        )

        if not result:
            return None

        matched_name, score, idx = result
        entity = self._entity_index.get(matched_name)
        if not entity:
            return None

        # State confirmation boosts confidence for borderline matches
        if score < 92 and state:
            entity_loc = (entity.headquarters_location or "").upper()
            if state.upper() not in entity_loc:
                return None  # Below 92 without state confirmation: reject

        return entity

    def _is_defense_relevant(self, filing: dict) -> bool:
        """
        Pass 2: Check if an unmatched filing is defense-relevant.

        Uses SIC codes when available, falls back to industry group + keywords.
        """
        # Check SIC code (from FORMDSUBMISSION)
        sic_code = filing.get("S_SIC_CODE", "").strip()
        if _sic_is_defense_relevant(sic_code):
            return True

        # Check industry group + name keywords
        industry = filing.get("O_INDUSTRYGROUPTYPE", "").strip()
        issuer_name = filing.get("I_ENTITYNAME", "")

        if industry in DEFENSE_INDUSTRY_GROUPS and _name_has_defense_keyword(issuer_name):
            return True

        # Strong keyword match regardless of industry group
        if _name_has_defense_keyword(issuer_name):
            # Require a minimum offering size to filter noise
            amount = _parse_amount(filing.get("O_TOTALAMOUNTSOLD", ""))
            if amount and amount >= 500_000:
                return True

        return False

    def _process_filing(
        self, filing: dict, seen_accessions: set, match_only: bool = False,
    ) -> Optional[FundingEvent]:
        """Process a single Form D filing."""
        accession = filing.get("ACCESSIONNUMBER", "").strip()
        if not accession:
            return None

        source_key = f"sec_edgar:{accession}"

        # Dedup: skip if already seen in this batch
        if accession in seen_accessions:
            self.stats.filings_skipped += 1
            return None
        seen_accessions.add(accession)

        # Filter out pooled investment funds (vast majority, not relevant)
        industry = filing.get("O_INDUSTRYGROUPTYPE", "").strip()
        if industry == "Pooled Investment Fund":
            self.stats.filings_skipped += 1
            return None

        issuer_name = filing.get("I_ENTITYNAME", "").strip()
        if not issuer_name:
            self.stats.filings_skipped += 1
            return None

        self.stats.filings_fetched += 1

        # Check for amendment — update existing record
        is_amendment = filing.get("O_ISAMENDMENT", "").strip().lower() == "true"
        prev_accession = filing.get("O_PREVIOUSACCESSIONNUMBER", "").strip()

        if is_amendment and prev_accession:
            existing = self.db.query(FundingEvent).filter(
                FundingEvent.source == f"sec_edgar:{prev_accession}",
            ).first()
            if existing:
                # Update the existing record with amended data
                amount = _parse_amount(filing.get("O_TOTALAMOUNTSOLD", ""))
                if amount is not None:
                    existing.amount = amount
                    existing.round_stage = _estimate_round_stage(amount)
                existing.raw_data = filing
                self.stats.filings_updated += 1
                return existing

        # Dedup: check DB for this exact accession
        existing = self.db.query(FundingEvent).filter(
            FundingEvent.source == source_key,
        ).first()
        if existing:
            self.stats.filings_skipped += 1
            return None

        # --- Entity matching ---
        state = filing.get("I_STATEORCOUNTRY", "").strip()
        entity = self._match_existing_entity(issuer_name, state)

        if entity:
            self.stats.entities_matched += 1
        elif not match_only and self._is_defense_relevant(filing):
            # Pass 2: create new entity for defense-relevant company
            location_parts = []
            city = filing.get("I_CITY", "").strip()
            state_desc = filing.get("I_STATEORCOUNTRYDESCRIPTION", "").strip()
            if city:
                location_parts.append(city)
            if state_desc:
                location_parts.append(state_desc)
            location = ", ".join(location_parts) if location_parts else None

            entity = Entity(
                canonical_name=issuer_name,
                name_variants=[],
                entity_type=EntityType.STARTUP,
                headquarters_location=location,
                technology_tags=[],
            )
            self.db.add(entity)
            self.db.flush()
            self.stats.entities_created += 1
        else:
            # No match, not defense-relevant — skip
            self.stats.filings_skipped += 1
            return None

        # Parse financial data
        amount = _parse_amount(filing.get("O_TOTALAMOUNTSOLD", ""))
        sale_date = _parse_date_str(filing.get("O_SALE_DATE", ""))
        filing_date = _parse_date_str(filing.get("S_FILING_DATE", ""))
        event_date = sale_date or filing_date
        investor_count = filing.get("O_TOTALNUMBERALREADYINVESTED", "").strip()

        # Build raw_data with source flag for Pass 2 entities
        raw_data = dict(filing)
        if not self._match_existing_entity(issuer_name, state):
            raw_data["_source"] = "sec_edgar"
            raw_data["_match_type"] = "defense_relevant_new"
        else:
            raw_data["_match_type"] = "existing_entity"

        funding_event = FundingEvent(
            entity_id=entity.id,
            event_type=FundingEventType.REG_D_FILING,
            amount=amount,
            event_date=event_date,
            source=source_key,
            round_stage=_estimate_round_stage(amount),
            investors_awarders=[],
            raw_data=raw_data,
        )
        self.db.add(funding_event)
        self.stats.filings_inserted += 1

        return funding_event

    def scrape(
        self,
        start_date: date,
        end_date: date,
        limit: Optional[int] = None,
        match_only: bool = False,
    ) -> ScraperStats:
        """
        Scrape Form D filings from DERA bulk data.

        Args:
            start_date: Start of date range
            end_date: End of date range
            limit: Max filings to process (for testing)
            match_only: If True, only match existing entities (skip Pass 2)
        """
        self.stats = ScraperStats(start_time=datetime.now())

        quarters = self._get_quarters(start_date, end_date)
        logger.info(f"Scraping Form D filings: {start_date} to {end_date}")
        logger.info(f"Quarters to process: {len(quarters)}")
        if match_only:
            logger.info("Match-only mode: skipping Pass 2 (no new entities)")

        seen_accessions: set[str] = set()
        pending_commits = 0
        total_processed = 0

        for year, quarter in quarters:
            filings = self._download_quarter(year, quarter)

            for filing in filings:
                if limit and total_processed >= limit:
                    break

                try:
                    result = self._process_filing(filing, seen_accessions, match_only)
                    if result:
                        pending_commits += 1
                    total_processed += 1

                    if pending_commits >= self.batch_size:
                        self.db.commit()
                        pending_commits = 0
                        logger.info(
                            f"  Progress: {self.stats.filings_inserted} inserted, "
                            f"{self.stats.entities_matched} matched, "
                            f"{self.stats.entities_created} new entities"
                        )

                except Exception as e:
                    logger.error(f"Error processing filing {filing.get('ACCESSIONNUMBER', '?')}: {e}")
                    self.db.rollback()
                    self.stats.errors += 1
                    pending_commits = 0

            if limit and total_processed >= limit:
                logger.info(f"Limit of {limit} reached, stopping")
                break

        # Final commit
        if pending_commits > 0:
            self.db.commit()

        self.stats.end_time = datetime.now()
        self.stats.log_summary()
        return self.stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scrape SEC EDGAR Form D filings for defense-relevant private fundraising"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2008-01-01",
        help="Start date YYYY-MM-DD (default: 2008-01-01, DERA data available from 2008 Q1)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=date.today().isoformat(),
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max filings to process (for testing)",
    )
    parser.add_argument(
        "--match-only",
        action="store_true",
        help="Only match existing entities, don't create new ones (skip Pass 2)",
    )

    args = parser.parse_args()

    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    if start_date > end_date:
        logger.error("Start date must be before end date")
        sys.exit(1)

    db = SessionLocal()

    try:
        scraper = SECEdgarScraper(db=db)
        stats = scraper.scrape(
            start_date=start_date,
            end_date=end_date,
            limit=args.limit,
            match_only=args.match_only,
        )

        if stats.errors > 0:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
