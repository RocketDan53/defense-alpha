#!/usr/bin/env python3
"""
Business Classifier - LLM-based classification of company core business.

Uses Claude to analyze SBIR award titles and determine what a company
primarily BUILDS or SELLS (not what technology they work WITH).

Categories:
- rf_hardware: Builds radios, antennas, radar, EW systems
- software: Builds software products
- systems_integrator: Integrates others' tech into solutions
- aerospace_platforms: Builds aircraft, spacecraft, drones, satellites
- components: Builds parts/subsystems, not full systems
- services: Consulting, support, training, R&D services
- other: Doesn't fit above categories

Usage:
    # Test on specific companies
    python -m processing.business_classifier --test

    # Classify all entities with SBIR awards
    python -m processing.business_classifier --all

    # Dry run (don't save to DB)
    python -m processing.business_classifier --all --dry-run

    # Async with concurrency (10x faster)
    python -m processing.business_classifier --all --async --concurrency 10

    # Skip already-classified entities
    python -m processing.business_classifier --all --async --concurrency 10 --skip-classified
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from anthropic import Anthropic, AsyncAnthropic
from sqlalchemy.orm import Session

from config.settings import settings
from processing.database import SessionLocal
from processing.models import (
    Contract,
    CoreBusiness,
    Entity,
    EntityType,
    FundingEvent,
    FundingEventType,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# Classification prompt
CLASSIFICATION_PROMPT = """You are an analyst classifying defense/aerospace companies based on their government R&D contracts (SBIR awards).

Your task: Based on the SBIR award titles below, determine what this company primarily BUILDS or SELLS as their core product.

IMPORTANT DISTINCTION:
- Focus on what they BUILD/MANUFACTURE/SELL, not what technology they USE or INTEGRATE
- A company that builds door locks but uses mesh radios = "other" or "components", NOT "rf_hardware"
- A company that builds software that processes radar data = "software", NOT "rf_hardware"
- A company that builds actual radar hardware = "rf_hardware"

CATEGORIES (choose exactly one):
- rf_hardware: Company builds RF/radio/antenna/radar/EW hardware as their primary product
- software: Company builds software products (apps, platforms, algorithms, AI/ML systems)
- systems_integrator: Company integrates others' hardware/software into complete solutions
- aerospace_platforms: Company builds complete aircraft, spacecraft, drones, satellites, or vehicles
- components: Company builds parts, subsystems, materials, or manufacturing equipment
- services: Company provides consulting, training, testing, or R&D services (not products)
- other: Doesn't clearly fit any category above

COMPANY: {company_name}
LOCATION: {location}

SBIR AWARDS ({award_count} total):
{sbir_list}

Respond with JSON only:
{{
  "classification": "<one of: rf_hardware, software, systems_integrator, aerospace_platforms, components, services, other>",
  "confidence": <0.0-1.0>,
  "reasoning": "<1-2 sentences explaining what they build and why this category>"
}}"""


CONTRACT_CLASSIFICATION_PROMPT = """You are an analyst classifying defense/aerospace companies based on their government contract data.

This company has NO SBIR awards, so you are classifying based on federal contracts only.

Your task: Based on the contract data below (agencies, NAICS codes, PSC codes, values, procurement types), determine what this company primarily BUILDS or SELLS.

IMPORTANT DISTINCTION:
- Focus on what they BUILD/MANUFACTURE/SELL, not what technology they USE or INTEGRATE
- PSC code guidance:
  - 1000-1999: Weapons/ammunition → likely aerospace_platforms or components
  - 5800-5999: Communication/detection equipment → likely rf_hardware
  - 7000-7999: IT/ADP equipment → likely software
  - AC-AZ, B, C codes: R&D services → check agency for domain
  - D codes: IT and telecom services → likely software or services
  - H codes: Quality control/testing → likely services or components
- NAICS guidance:
  - 334: Computer/electronic manufacturing → rf_hardware or components
  - 336: Transportation equipment → aerospace_platforms
  - 541: Professional/scientific/technical → services or software
  - 332: Fabricated metal → components

CATEGORIES (choose exactly one):
- rf_hardware: Company builds RF/radio/antenna/radar/EW hardware as their primary product
- software: Company builds software products (apps, platforms, algorithms, AI/ML systems)
- systems_integrator: Company integrates others' hardware/software into complete solutions
- aerospace_platforms: Company builds complete aircraft, spacecraft, drones, satellites, or vehicles
- components: Company builds parts, subsystems, materials, or manufacturing equipment
- services: Company provides consulting, training, testing, or R&D services (not products)
- other: Doesn't clearly fit any category above

COMPANY: {company_name}
LOCATION: {location}

CONTRACTS ({contract_count} total, ${total_value:,.0f} total value):
{contract_list}

Respond with JSON only:
{{
  "classification": "<one of: rf_hardware, software, systems_integrator, aerospace_platforms, components, services, other>",
  "confidence": <0.0-1.0>,
  "reasoning": "<1-2 sentences explaining what they build and why this category>"
}}"""


@dataclass
class ClassificationResult:
    """Result of business classification."""
    entity_id: str
    entity_name: str
    classification: CoreBusiness
    confidence: float
    reasoning: str
    sbir_count: int
    raw_response: Optional[str] = None


@dataclass
class ClassifierStats:
    """Statistics from classification run."""
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    low_confidence: int = 0  # < 0.7 confidence
    by_category: dict = None

    def __post_init__(self):
        if self.by_category is None:
            self.by_category = {}


def get_sbir_awards(db: Session, entity_id: str) -> list[dict]:
    """Get all SBIR awards for an entity."""
    sbir_types = [
        FundingEventType.SBIR_PHASE_1,
        FundingEventType.SBIR_PHASE_2,
        FundingEventType.SBIR_PHASE_3,
    ]
    events = (
        db.query(FundingEvent)
        .filter(
            FundingEvent.entity_id == entity_id,
            FundingEvent.event_type.in_(sbir_types),
        )
        .order_by(FundingEvent.event_date.desc())
        .all()
    )

    awards = []
    for ev in events:
        rd = ev.raw_data or {}
        awards.append({
            "title": rd.get("Award Title", "(no title)"),
            "phase": rd.get("Phase", ev.event_type.value),
            "amount": float(ev.amount) if ev.amount else 0,
            "date": str(ev.event_date) if ev.event_date else "",
            "agency": rd.get("Branch", rd.get("Agency", "")),
        })
    return awards


def format_sbir_list(awards: list[dict]) -> str:
    """Format SBIR awards for the prompt."""
    lines = []
    for i, award in enumerate(awards[:10], 1):  # Limit to 10 most recent
        amount_str = f"${award['amount']:,.0f}" if award['amount'] else "N/A"
        lines.append(
            f"{i}. [{award['phase']}] {award['title']}\n"
            f"   Agency: {award['agency']} | Amount: {amount_str} | Date: {award['date']}"
        )
    if len(awards) > 10:
        lines.append(f"\n... and {len(awards) - 10} more awards")
    return "\n".join(lines)


def get_contracts(db: Session, entity_id: str) -> list[dict]:
    """Get all contracts for an entity."""
    contracts = (
        db.query(Contract)
        .filter(Contract.entity_id == entity_id)
        .order_by(Contract.award_date.desc())
        .all()
    )

    result = []
    for c in contracts:
        result.append({
            "agency": c.contracting_agency or "Unknown",
            "naics_code": c.naics_code or "N/A",
            "psc_code": c.psc_code or "N/A",
            "value": float(c.contract_value) if c.contract_value else 0,
            "date": str(c.award_date) if c.award_date else "N/A",
            "procurement_type": c.procurement_type or "standard",
        })
    return result


def format_contract_list(contracts: list[dict]) -> str:
    """Format contracts for the prompt."""
    lines = []
    for i, c in enumerate(contracts[:10], 1):  # Limit to 10 most recent
        value_str = f"${c['value']:,.0f}" if c['value'] else "N/A"
        lines.append(
            f"{i}. Agency: {c['agency']}\n"
            f"   NAICS: {c['naics_code']} | PSC: {c['psc_code']} | "
            f"Value: {value_str} | Type: {c['procurement_type']} | Date: {c['date']}"
        )
    if len(contracts) > 10:
        lines.append(f"\n... and {len(contracts) - 10} more contracts")
    return "\n".join(lines)


def classify_entity(
    client: Anthropic,
    db: Session,
    entity: Entity,
    model: str = "claude-sonnet-4-20250514",
) -> Optional[ClassificationResult]:
    """
    Classify a single entity using Claude.

    Args:
        client: Anthropic client
        db: Database session
        entity: Entity to classify
        model: Claude model to use

    Returns:
        ClassificationResult or None if classification failed
    """
    # Get SBIR awards
    awards = get_sbir_awards(db, entity.id)
    if not awards:
        logger.warning(f"No SBIR awards found for {entity.canonical_name}")
        return None

    # Build prompt
    sbir_list = format_sbir_list(awards)
    prompt = CLASSIFICATION_PROMPT.format(
        company_name=entity.canonical_name,
        location=entity.headquarters_location or "Unknown",
        award_count=len(awards),
        sbir_list=sbir_list,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()

        # Parse JSON response
        # Handle potential markdown code blocks
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)

        # Map string to enum
        classification_str = result.get("classification", "other").lower()
        try:
            classification = CoreBusiness(classification_str)
        except ValueError:
            logger.warning(f"Unknown classification '{classification_str}', defaulting to OTHER")
            classification = CoreBusiness.OTHER

        return ClassificationResult(
            entity_id=entity.id,
            entity_name=entity.canonical_name,
            classification=classification,
            confidence=float(result.get("confidence", 0.5)),
            reasoning=result.get("reasoning", ""),
            sbir_count=len(awards),
            raw_response=raw_text,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON for {entity.canonical_name}: {e}")
        logger.error(f"Raw response: {raw_text[:500]}")
        return None
    except Exception as e:
        logger.error(f"Classification failed for {entity.canonical_name}: {e}")
        return None


def save_classification(db: Session, result: ClassificationResult, dry_run: bool = False):
    """Save classification result to database."""
    entity = db.query(Entity).filter(Entity.id == result.entity_id).first()
    if not entity:
        logger.error(f"Entity not found: {result.entity_id}")
        return

    entity.core_business = result.classification
    entity.core_business_confidence = Decimal(str(round(result.confidence, 2)))
    entity.core_business_reasoning = result.reasoning

    if not dry_run:
        db.commit()


def prefetch_entity_data(db: Session, entities: list[Entity]) -> list[dict]:
    """Pre-fetch all entity data including SBIR awards for async processing."""
    data_list = []
    for entity in entities:
        awards = get_sbir_awards(db, entity.id)
        data_list.append({
            "id": entity.id,
            "name": entity.canonical_name,
            "location": entity.headquarters_location or "Unknown",
            "awards": awards,
        })
    return data_list


def prefetch_contract_data(db: Session, entities: list[Entity]) -> list[dict]:
    """Pre-fetch all entity data including contracts for async processing."""
    data_list = []
    for entity in entities:
        contracts = get_contracts(db, entity.id)
        data_list.append({
            "id": entity.id,
            "name": entity.canonical_name,
            "location": entity.headquarters_location or "Unknown",
            "contracts": contracts,
            "source": "contracts",
        })
    return data_list


async def classify_entity_from_contracts_async(
    client: AsyncAnthropic,
    entity_data: dict,
    model: str = "claude-sonnet-4-20250514",
) -> Optional[ClassificationResult]:
    """
    Async: Classify a single entity using contract data instead of SBIR awards.
    """
    contracts = entity_data["contracts"]
    entity_id = entity_data["id"]
    entity_name = entity_data["name"]

    if not contracts:
        logger.warning(f"No contracts found for {entity_name}")
        return None

    total_value = sum(c["value"] for c in contracts)
    contract_list = format_contract_list(contracts)
    prompt = CONTRACT_CLASSIFICATION_PROMPT.format(
        company_name=entity_name,
        location=entity_data["location"],
        contract_count=len(contracts),
        total_value=total_value,
        contract_list=contract_list,
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()

        # Parse JSON response - handle potential markdown code blocks
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)

        classification_str = result.get("classification", "other").lower()
        try:
            classification = CoreBusiness(classification_str)
        except ValueError:
            logger.warning(f"Unknown classification '{classification_str}', defaulting to OTHER")
            classification = CoreBusiness.OTHER

        reasoning = result.get("reasoning", "")
        reasoning = f"[contract-based classification] {reasoning}"

        return ClassificationResult(
            entity_id=entity_id,
            entity_name=entity_name,
            classification=classification,
            confidence=float(result.get("confidence", 0.5)),
            reasoning=reasoning,
            sbir_count=0,
            raw_response=raw_text,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON for {entity_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Classification failed for {entity_name}: {e}")
        return None


async def process_contract_entity_with_semaphore(
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic,
    entity_data: dict,
    index: int,
    total: int,
    model: str,
) -> tuple[int, Optional[ClassificationResult]]:
    """Process a single contract-based entity with semaphore for rate limiting."""
    async with semaphore:
        logger.info(f"[{index}/{total}] {entity_data['name']} ({len(entity_data['contracts'])} contracts)")
        result = await classify_entity_from_contracts_async(client, entity_data, model=model)
        return index, result


async def run_contract_classification_async(
    db: Session,
    client: AsyncAnthropic,
    limit: Optional[int] = None,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
    concurrency: int = 10,
    skip_classified: bool = False,
) -> ClassifierStats:
    """
    Async: Run classification on entities with contracts but no SBIR awards.
    """
    stats = ClassifierStats()

    # Get entities with contracts but no SBIR awards
    sbir_types = [
        FundingEventType.SBIR_PHASE_1,
        FundingEventType.SBIR_PHASE_2,
        FundingEventType.SBIR_PHASE_3,
    ]
    entity_ids_with_sbir = (
        db.query(FundingEvent.entity_id)
        .filter(FundingEvent.event_type.in_(sbir_types))
        .distinct()
        .subquery()
    )
    entity_ids_with_contracts = (
        db.query(Contract.entity_id)
        .distinct()
        .subquery()
    )
    query = (
        db.query(Entity)
        .filter(
            Entity.id.in_(entity_ids_with_contracts),
            ~Entity.id.in_(entity_ids_with_sbir),
            Entity.merged_into_id.is_(None),
            Entity.entity_type == EntityType.STARTUP,
        )
    )
    if skip_classified:
        query = query.filter(
            (Entity.core_business.is_(None)) | (Entity.core_business == CoreBusiness.UNCLASSIFIED)
        )
    entities = query.all()

    if limit:
        entities = entities[:limit]

    logger.info("=" * 70)
    logger.info("BUSINESS CLASSIFIER — CONTRACT-BASED (ASYNC)")
    logger.info("=" * 70)
    logger.info(f"Entities to process: {len(entities)}")
    logger.info(f"Model: {model}")
    logger.info(f"Concurrency: {concurrency}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 70)

    # Pre-fetch all entity data synchronously
    logger.info("Pre-fetching contract data...")
    entity_data_list = prefetch_contract_data(db, entities)
    logger.info(f"Pre-fetched {len(entity_data_list)} entities\n")

    # Create semaphore for rate limiting
    semaphore = asyncio.Semaphore(concurrency)

    # Create all tasks
    tasks = [
        process_contract_entity_with_semaphore(
            semaphore, client, entity_data, i, len(entity_data_list), model
        )
        for i, entity_data in enumerate(entity_data_list, 1)
    ]

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)

    # Process results and save to database
    low_confidence_results = []

    for index, result in results:
        stats.total_processed += 1

        if result:
            stats.successful += 1
            stats.by_category[result.classification.value] = (
                stats.by_category.get(result.classification.value, 0) + 1
            )

            conf_indicator = "LOW" if result.confidence < 0.7 else "OK "
            if result.confidence < 0.7:
                stats.low_confidence += 1
                low_confidence_results.append(result)

            logger.info(
                f"  -> {result.entity_name}: {result.classification.value:20} "
                f"(conf: {result.confidence:.2f} {conf_indicator})"
            )

            save_classification(db, result, dry_run=dry_run)
        else:
            stats.failed += 1
            entity_data = entity_data_list[index - 1]
            logger.error(f"  -> {entity_data['name']}: FAILED")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total processed: {stats.total_processed}")
    logger.info(f"Successful: {stats.successful}")
    logger.info(f"Failed: {stats.failed}")
    logger.info(f"Low confidence (<0.7): {stats.low_confidence}")
    logger.info("")
    logger.info("By category:")
    for cat, count in sorted(stats.by_category.items(), key=lambda x: -x[1]):
        logger.info(f"  {cat:20}: {count}")

    if low_confidence_results:
        logger.info("\n" + "-" * 70)
        logger.info("LOW CONFIDENCE CLASSIFICATIONS (manual review recommended):")
        logger.info("-" * 70)
        for r in low_confidence_results:
            logger.info(f"  {r.entity_name}")
            logger.info(f"    -> {r.classification.value} (conf: {r.confidence:.2f})")
            logger.info(f"    -> {r.reasoning}")

    if dry_run:
        logger.info("\nDRY RUN - no changes saved to database.")
    else:
        logger.info("\nClassifications saved to database.")

    return stats


async def classify_entity_async(
    client: AsyncAnthropic,
    entity_data: dict,
    model: str = "claude-sonnet-4-20250514",
) -> Optional[ClassificationResult]:
    """
    Async version: Classify a single entity using Claude.

    Args:
        client: AsyncAnthropic client
        entity_data: Pre-fetched entity data dict
        model: Claude model to use

    Returns:
        ClassificationResult or None if classification failed
    """
    awards = entity_data["awards"]
    entity_id = entity_data["id"]
    entity_name = entity_data["name"]

    if not awards:
        logger.warning(f"No SBIR awards found for {entity_name}")
        return None

    # Build prompt
    sbir_list = format_sbir_list(awards)
    prompt = CLASSIFICATION_PROMPT.format(
        company_name=entity_name,
        location=entity_data["location"],
        award_count=len(awards),
        sbir_list=sbir_list,
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()

        # Parse JSON response - handle potential markdown code blocks
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)

        # Map string to enum
        classification_str = result.get("classification", "other").lower()
        try:
            classification = CoreBusiness(classification_str)
        except ValueError:
            logger.warning(f"Unknown classification '{classification_str}', defaulting to OTHER")
            classification = CoreBusiness.OTHER

        return ClassificationResult(
            entity_id=entity_id,
            entity_name=entity_name,
            classification=classification,
            confidence=float(result.get("confidence", 0.5)),
            reasoning=result.get("reasoning", ""),
            sbir_count=len(awards),
            raw_response=raw_text,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON for {entity_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Classification failed for {entity_name}: {e}")
        return None


async def process_entity_with_semaphore(
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic,
    entity_data: dict,
    index: int,
    total: int,
    model: str,
) -> tuple[int, Optional[ClassificationResult]]:
    """Process a single entity with semaphore for rate limiting."""
    async with semaphore:
        logger.info(f"[{index}/{total}] {entity_data['name']}")
        result = await classify_entity_async(client, entity_data, model=model)
        return index, result


async def run_classification_async(
    db: Session,
    client: AsyncAnthropic,
    entity_names: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
    concurrency: int = 10,
    skip_classified: bool = False,
) -> ClassifierStats:
    """
    Async version: Run classification with concurrent API calls.

    Args:
        db: Database session
        client: AsyncAnthropic client
        entity_names: Specific entity names to classify (None = all with SBIR)
        limit: Max entities to process
        dry_run: If True, don't save to database
        model: Claude model to use
        concurrency: Number of concurrent API calls
        skip_classified: If True, skip entities that already have core_business set

    Returns:
        ClassifierStats with results
    """
    stats = ClassifierStats()

    # Get entities to classify
    if entity_names:
        query = (
            db.query(Entity)
            .filter(
                Entity.canonical_name.in_(entity_names),
                Entity.merged_into_id.is_(None),
            )
        )
        if skip_classified:
            query = query.filter(
                (Entity.core_business.is_(None)) | (Entity.core_business == CoreBusiness.UNCLASSIFIED)
            )
        entities = query.all()
    else:
        sbir_types = [
            FundingEventType.SBIR_PHASE_1,
            FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]
        entity_ids_with_sbir = (
            db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type.in_(sbir_types))
            .distinct()
            .subquery()
        )
        query = (
            db.query(Entity)
            .filter(
                Entity.id.in_(entity_ids_with_sbir),
                Entity.merged_into_id.is_(None),
                Entity.entity_type == EntityType.STARTUP,
            )
        )
        if skip_classified:
            query = query.filter(
                (Entity.core_business.is_(None)) | (Entity.core_business == CoreBusiness.UNCLASSIFIED)
            )
        entities = query.all()

    if limit:
        entities = entities[:limit]

    logger.info("=" * 70)
    logger.info("BUSINESS CLASSIFIER (ASYNC)")
    logger.info("=" * 70)
    logger.info(f"Entities to process: {len(entities)}")
    logger.info(f"Model: {model}")
    logger.info(f"Concurrency: {concurrency}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 70)

    # Pre-fetch all entity data synchronously
    logger.info("Pre-fetching entity data...")
    entity_data_list = prefetch_entity_data(db, entities)
    logger.info(f"Pre-fetched {len(entity_data_list)} entities\n")

    # Create semaphore for rate limiting
    semaphore = asyncio.Semaphore(concurrency)

    # Create all tasks
    tasks = [
        process_entity_with_semaphore(
            semaphore, client, entity_data, i, len(entity_data_list), model
        )
        for i, entity_data in enumerate(entity_data_list, 1)
    ]

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)

    # Process results and save to database
    low_confidence_results = []

    for index, result in results:
        stats.total_processed += 1

        if result:
            stats.successful += 1
            stats.by_category[result.classification.value] = (
                stats.by_category.get(result.classification.value, 0) + 1
            )

            conf_indicator = "LOW" if result.confidence < 0.7 else "OK "
            if result.confidence < 0.7:
                stats.low_confidence += 1
                low_confidence_results.append(result)

            logger.info(
                f"  -> {result.entity_name}: {result.classification.value:20} "
                f"(conf: {result.confidence:.2f} {conf_indicator})"
            )

            save_classification(db, result, dry_run=dry_run)
        else:
            stats.failed += 1
            entity_data = entity_data_list[index - 1]
            logger.error(f"  -> {entity_data['name']}: FAILED")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total processed: {stats.total_processed}")
    logger.info(f"Successful: {stats.successful}")
    logger.info(f"Failed: {stats.failed}")
    logger.info(f"Low confidence (<0.7): {stats.low_confidence}")
    logger.info("")
    logger.info("By category:")
    for cat, count in sorted(stats.by_category.items(), key=lambda x: -x[1]):
        logger.info(f"  {cat:20}: {count}")

    if low_confidence_results:
        logger.info("\n" + "-" * 70)
        logger.info("LOW CONFIDENCE CLASSIFICATIONS (manual review recommended):")
        logger.info("-" * 70)
        for r in low_confidence_results:
            logger.info(f"  {r.entity_name}")
            logger.info(f"    -> {r.classification.value} (conf: {r.confidence:.2f})")
            logger.info(f"    -> {r.reasoning}")

    if dry_run:
        logger.info("\nDRY RUN - no changes saved to database.")
    else:
        logger.info("\nClassifications saved to database.")

    return stats


def run_classification(
    db: Session,
    client: Anthropic,
    entity_names: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
    skip_classified: bool = False,
) -> ClassifierStats:
    """
    Run classification on entities.

    Args:
        db: Database session
        client: Anthropic client
        entity_names: Specific entity names to classify (None = all with SBIR)
        limit: Max entities to process
        dry_run: If True, don't save to database
        model: Claude model to use
        skip_classified: If True, skip entities that already have core_business set

    Returns:
        ClassifierStats with results
    """
    stats = ClassifierStats()

    # Get entities to classify
    if entity_names:
        query = (
            db.query(Entity)
            .filter(
                Entity.canonical_name.in_(entity_names),
                Entity.merged_into_id.is_(None),
            )
        )
        if skip_classified:
            query = query.filter(
                (Entity.core_business.is_(None)) | (Entity.core_business == CoreBusiness.UNCLASSIFIED)
            )
        entities = query.all()
    else:
        # Get entities with SBIR awards
        sbir_types = [
            FundingEventType.SBIR_PHASE_1,
            FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]
        entity_ids_with_sbir = (
            db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type.in_(sbir_types))
            .distinct()
            .subquery()
        )
        query = (
            db.query(Entity)
            .filter(
                Entity.id.in_(entity_ids_with_sbir),
                Entity.merged_into_id.is_(None),
                Entity.entity_type == EntityType.STARTUP,
            )
        )
        if skip_classified:
            query = query.filter(
                (Entity.core_business.is_(None)) | (Entity.core_business == CoreBusiness.UNCLASSIFIED)
            )
        entities = query.all()

    if limit:
        entities = entities[:limit]

    logger.info("=" * 70)
    logger.info("BUSINESS CLASSIFIER")
    logger.info("=" * 70)
    logger.info(f"Entities to process: {len(entities)}")
    logger.info(f"Model: {model}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 70)

    low_confidence_results = []

    for i, entity in enumerate(entities, 1):
        logger.info(f"\n[{i}/{len(entities)}] {entity.canonical_name}")

        result = classify_entity(client, db, entity, model=model)
        stats.total_processed += 1

        if result:
            stats.successful += 1
            stats.by_category[result.classification.value] = (
                stats.by_category.get(result.classification.value, 0) + 1
            )

            conf_indicator = "LOW" if result.confidence < 0.7 else "OK "
            if result.confidence < 0.7:
                stats.low_confidence += 1
                low_confidence_results.append(result)

            logger.info(
                f"  -> {result.classification.value:20} "
                f"(conf: {result.confidence:.2f} {conf_indicator})"
            )
            logger.info(f"     {result.reasoning[:80]}...")

            save_classification(db, result, dry_run=dry_run)
        else:
            stats.failed += 1
            logger.error(f"  -> FAILED")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total processed: {stats.total_processed}")
    logger.info(f"Successful: {stats.successful}")
    logger.info(f"Failed: {stats.failed}")
    logger.info(f"Low confidence (<0.7): {stats.low_confidence}")
    logger.info("")
    logger.info("By category:")
    for cat, count in sorted(stats.by_category.items(), key=lambda x: -x[1]):
        logger.info(f"  {cat:20}: {count}")

    if low_confidence_results:
        logger.info("\n" + "-" * 70)
        logger.info("LOW CONFIDENCE CLASSIFICATIONS (manual review recommended):")
        logger.info("-" * 70)
        for r in low_confidence_results:
            logger.info(f"  {r.entity_name}")
            logger.info(f"    -> {r.classification.value} (conf: {r.confidence:.2f})")
            logger.info(f"    -> {r.reasoning}")

    if dry_run:
        logger.info("\nDRY RUN - no changes saved to database.")
    else:
        logger.info("\nClassifications saved to database.")

    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Classify company core business using LLM analysis of SBIR awards"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test on specific companies (Havenlock, Tetrate, MatrixSpace, etc.)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Classify all entities with SBIR awards",
    )
    parser.add_argument(
        "--names",
        type=str,
        nargs="+",
        help="Specific company names to classify",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of entities to process",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save results to database",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-20250514",
        help="Claude model to use (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--async",
        dest="use_async",
        action="store_true",
        help="Use async concurrent processing (faster)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent API calls for async mode (default: 10)",
    )
    parser.add_argument(
        "--skip-classified",
        action="store_true",
        help="Skip entities that already have core_business classifications",
    )
    parser.add_argument(
        "--contracts-only",
        action="store_true",
        help="Classify entities with contracts but no SBIR awards (contract-based classification)",
    )

    args = parser.parse_args()

    # Check for API key
    api_key = settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set in environment or .env file")
        sys.exit(1)

    db = SessionLocal()

    try:
        test_companies = [
            "HAVENLOCK INC",
            "TETRATE.IO, INC.",
            "MATRIXSPACE, INC",
            "PHASE SENSITIVE INNOVATIONS INC",
            "TERASPATIAL INC",
            "THRUST AI LLC",
            "ZENITH AEROSPACE INC",
            "FOURTH STATE COMMUNICATIONS, LLC",
            "SOLSTAR SPACE COMPANY",
            "XL SCIENTIFIC LLC",
        ]

        if args.use_async:
            # Async concurrent mode
            async_client = AsyncAnthropic(api_key=api_key)

            async def run_async():
                if args.contracts_only:
                    return await run_contract_classification_async(
                        db, async_client,
                        limit=args.limit,
                        dry_run=args.dry_run,
                        model=args.model,
                        concurrency=args.concurrency,
                        skip_classified=args.skip_classified,
                    )
                elif args.test:
                    return await run_classification_async(
                        db, async_client,
                        entity_names=test_companies,
                        dry_run=args.dry_run,
                        model=args.model,
                        concurrency=args.concurrency,
                        skip_classified=args.skip_classified,
                    )
                elif args.names:
                    return await run_classification_async(
                        db, async_client,
                        entity_names=args.names,
                        dry_run=args.dry_run,
                        model=args.model,
                        concurrency=args.concurrency,
                        skip_classified=args.skip_classified,
                    )
                elif args.all:
                    return await run_classification_async(
                        db, async_client,
                        limit=args.limit,
                        dry_run=args.dry_run,
                        model=args.model,
                        concurrency=args.concurrency,
                        skip_classified=args.skip_classified,
                    )
                else:
                    parser.print_help()
                    return None

            asyncio.run(run_async())
        else:
            # Sync sequential mode
            client = Anthropic(api_key=api_key)

            if args.contracts_only:
                logger.error("--contracts-only requires --async mode")
                sys.exit(1)
            elif args.test:
                run_classification(
                    db, client,
                    entity_names=test_companies,
                    dry_run=args.dry_run,
                    model=args.model,
                    skip_classified=args.skip_classified,
                )
            elif args.names:
                run_classification(
                    db, client,
                    entity_names=args.names,
                    dry_run=args.dry_run,
                    model=args.model,
                    skip_classified=args.skip_classified,
                )
            elif args.all:
                run_classification(
                    db, client,
                    limit=args.limit,
                    dry_run=args.dry_run,
                    model=args.model,
                    skip_classified=args.skip_classified,
                )
            else:
                parser.print_help()

    finally:
        db.close()


if __name__ == "__main__":
    main()
