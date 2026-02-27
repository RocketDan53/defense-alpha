"""
Scraper Framework — Base class for all data scrapers.

Provides HTTP session management, rate limiting, and audit logging via ScraperRun.

Usage:
    class MyScraper(BaseScraper):
        source_name = "my_source"

        def scrape(self) -> ScraperResult:
            data = self.get("https://api.example.com/data")
            return ScraperResult(records_fetched=len(data), ...)
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class ScraperResult:
    """Result of a scraper run."""
    records_fetched: int = 0
    records_new: int = 0
    records_updated: int = 0
    entities_created: int = 0
    entities_matched: int = 0
    error_message: Optional[str] = None
    checkpoint: Optional[dict] = None


class BaseScraper(ABC):
    """
    Abstract base class for all scrapers.

    Provides:
    - HTTP session with retry logic
    - Rate limiting (requests per second)
    - ScraperRun audit trail (start/finish logging)
    """

    source_name: str = "unknown"
    requests_per_second: float = 2.0

    def __init__(self, db=None):
        self.db = db
        self._session = self._build_session()
        self._last_request_time = 0.0
        self._run_id: Optional[str] = None

    def _build_session(self) -> requests.Session:
        """Build HTTP session with retry logic."""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": "ApertureSignals/1.0 (research)",
        })
        return session

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        if self.requests_per_second <= 0:
            return
        min_interval = 1.0 / self.requests_per_second
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET request."""
        self._rate_limit()
        return self._session.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited POST request."""
        self._rate_limit()
        return self._session.post(url, **kwargs)

    def start_run(self, config: dict | None = None) -> str:
        """Record the start of a scraper run. Returns run_id."""
        if not self.db:
            return ""

        from processing.models import ScraperRun
        run = ScraperRun(
            source_name=self.source_name,
            status="running",
            config=config,
        )
        self.db.add(run)
        self.db.commit()
        self._run_id = run.id
        logger.info(f"Scraper run started: {self.source_name} ({run.id})")
        return run.id

    def finish_run(self, result: ScraperResult):
        """Record the completion of a scraper run."""
        if not self.db or not self._run_id:
            return

        from processing.models import ScraperRun
        run = self.db.query(ScraperRun).filter(ScraperRun.id == self._run_id).first()
        if not run:
            return

        run.completed_at = datetime.utcnow()
        run.status = "failed" if result.error_message else "success"
        run.records_fetched = result.records_fetched
        run.records_new = result.records_new
        run.records_updated = result.records_updated
        run.entities_created = result.entities_created
        run.entities_matched = result.entities_matched
        run.error_message = result.error_message
        run.checkpoint = result.checkpoint
        self.db.commit()

        logger.info(
            f"Scraper run complete: {self.source_name} — "
            f"{result.records_fetched} fetched, {result.records_new} new, "
            f"{result.entities_created} entities created"
        )

    @abstractmethod
    def scrape(self) -> ScraperResult:
        """Execute the scrape. Subclasses must implement this."""
        ...
