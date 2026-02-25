#!/usr/bin/env python3
"""
Policy Alignment Scorer - Maps companies to National Defense Strategy priorities.

Analyzes SBIR award portfolios to determine how well a company's work aligns
with current DoD/IC strategic priorities and budget growth areas.

Priority Areas (based on NDS 2022, budget trends, doctrine):
- china_pacing: Great power competition capabilities
- jadc2: Joint All-Domain Command and Control
- space_resilience: Space access, protection, communications
- cyber_offense_defense: Offensive/defensive cyber capabilities
- autonomous_systems: Unmanned platforms, AI-enabled systems
- hypersonics: Hypersonic weapons and defense
- supply_chain_resilience: Domestic manufacturing, microelectronics
- border_homeland: Surveillance, detection, interdiction
- nuclear_modernization: Nuclear triad modernization
- electronic_warfare: EW attack and protection

Usage:
    # Review prompt template (dry run)
    python -m processing.policy_alignment --test --dry-run

    # Score specific companies
    python -m processing.policy_alignment --names "SHIELD AI" "ANDURIL"

    # Score all classified entities (sequential, ~4/min)
    python -m processing.policy_alignment --all

    # Score all with async concurrency (~40/min with 10 concurrent)
    python -m processing.policy_alignment --all --async

    # Adjust concurrency level (default 10)
    python -m processing.policy_alignment --all --async --concurrency 15
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from anthropic import Anthropic, AsyncAnthropic
from sqlalchemy.orm import Session

from config.settings import settings
from processing.database import SessionLocal
from processing.models import (
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


# =============================================================================
# PRIORITY AREA TAXONOMY
# =============================================================================
# Loaded from config/policy_priorities.yaml
# Weights calibrated from FY2026 President's Budget Request (Feb 2026)

import yaml

def load_policy_config() -> dict:
    """Load policy priorities from YAML config."""
    config_path = Path(__file__).parent.parent / "config" / "policy_priorities.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


# Load config at module level
_CONFIG = load_policy_config()


class PolicyPriority(Enum):
    """National Defense Strategy priority areas."""

    SPACE_RESILIENCE = "space_resilience"
    NUCLEAR_MODERNIZATION = "nuclear_modernization"
    AUTONOMOUS_SYSTEMS = "autonomous_systems"
    SUPPLY_CHAIN_RESILIENCE = "supply_chain_resilience"
    CONTESTED_LOGISTICS = "contested_logistics"
    ELECTRONIC_WARFARE = "electronic_warfare"
    JADC2 = "jadc2"
    BORDER_HOMELAND = "border_homeland"
    CYBER_OFFENSE_DEFENSE = "cyber_offense_defense"
    HYPERSONICS = "hypersonics"


# Budget growth weights from YAML config
# Values calibrated from actual FY25→FY26 budget data
BUDGET_GROWTH_WEIGHTS = {
    PolicyPriority(name): data["weight"]
    for name, data in _CONFIG["priorities"].items()
}


# Priority area descriptions for the LLM prompt (loaded from YAML)
PRIORITY_DESCRIPTIONS = {
    PolicyPriority(name): data["description"].strip()
    for name, data in _CONFIG["priorities"].items()
}


# Geographic/strategic modifiers (boolean tags, not weighted)
MODIFIERS = _CONFIG.get("modifiers", {})


# =============================================================================
# PROMPT TEMPLATE
# =============================================================================

ALIGNMENT_PROMPT = """You are a defense policy analyst assessing how well a company's technology portfolio aligns with current U.S. National Defense Strategy priorities and budget growth areas.

COMPANY: {company_name}
CORE BUSINESS: {core_business}
LOCATION: {location}

SBIR/STTR AWARDS ({award_count} total, showing up to 15):
{sbir_list}

PRIORITY AREAS TO ASSESS (weighted by FY2026 budget growth):

{priority_descriptions}

TASK: For each priority area, score how directly this company's demonstrated capabilities (based on their SBIR awards) support that priority.

SCORING GUIDANCE:
- 0.0: No relevance to this priority
- 0.1-0.3: Tangential or indirect support (general-purpose tech that could apply)
- 0.4-0.6: Moderate alignment (some awards clearly relevant)
- 0.7-0.8: Strong alignment (multiple awards directly address this priority)
- 0.9-1.0: Core focus (company's primary work IS this priority area)

Be conservative - only score high if the SBIR titles clearly demonstrate direct relevance.

Examples:
- A company building general software tools should score low on most areas.
- A company building hypersonic thermal protection should score high on hypersonics, low elsewhere.
- A company building UAS/drone platforms or autonomous flight systems should score high on autonomous_systems (0.7-0.9), even if individual SBIR titles mention materials, sensors, or communications — the platform IS the autonomous system.
- A company building counter-UAS or counter-drone intercept technology should score moderate-to-high on autonomous_systems (0.5-0.7) and may also score on electronic_warfare if using RF/EW approaches.
- A company building satellite components should score high on space_resilience, not autonomous_systems, even if the satellite operates autonomously.

ALSO ASSESS these boolean modifiers:
- pacific_relevance: Does this company's work explicitly address Indo-Pacific operations, China threat scenarios, A2/AD, long-range Pacific strike, or Taiwan contingencies?

Respond with JSON only:
{{
  "scores": {{
    "space_resilience": <0.0-1.0>,
    "nuclear_modernization": <0.0-1.0>,
    "autonomous_systems": <0.0-1.0>,
    "supply_chain_resilience": <0.0-1.0>,
    "contested_logistics": <0.0-1.0>,
    "electronic_warfare": <0.0-1.0>,
    "jadc2": <0.0-1.0>,
    "border_homeland": <0.0-1.0>,
    "cyber_offense_defense": <0.0-1.0>,
    "hypersonics": <0.0-1.0>
  }},
  "modifiers": {{
    "pacific_relevance": <true/false>
  }},
  "top_priorities": ["<top 1-3 priority areas with score >= 0.5>"],
  "reasoning": "<1-2 sentences on what makes this company strategically relevant>"
}}"""


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class AlignmentResult:
    """Result of policy alignment scoring."""
    entity_id: str
    entity_name: str
    scores: dict[str, float]
    modifiers: dict[str, bool]  # Boolean tags like pacific_relevance
    top_priorities: list[str]
    reasoning: str
    policy_tailwind: float  # Weighted composite score
    sbir_count: int
    raw_response: Optional[str] = None


@dataclass
class ScorerStats:
    """Statistics from scoring run."""
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    high_alignment: int = 0  # At least one score >= 0.7
    by_priority: dict = field(default_factory=dict)

    def __post_init__(self):
        # Initialize counters for each priority
        for p in PolicyPriority:
            self.by_priority[p.value] = {"high": 0, "medium": 0, "low": 0}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

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
    for i, award in enumerate(awards[:15], 1):  # Show up to 15
        amount_str = f"${award['amount']:,.0f}" if award['amount'] else "N/A"
        lines.append(
            f"{i}. [{award['phase']}] {award['title']}\n"
            f"   Agency: {award['agency']} | Amount: {amount_str}"
        )
    if len(awards) > 15:
        lines.append(f"\n... and {len(awards) - 15} more awards")
    return "\n".join(lines)


def format_priority_descriptions() -> str:
    """Format all priority descriptions for the prompt."""
    lines = []
    for i, (priority, desc) in enumerate(PRIORITY_DESCRIPTIONS.items(), 1):
        lines.append(f"{i}. {priority.value.upper()}: {desc}")
    return "\n\n".join(lines)


def calculate_policy_tailwind(scores: dict[str, float]) -> float:
    """
    Calculate composite policy tailwind score.

    Weights each alignment score by the budget growth rate for that area.
    Only includes priorities where alignment score > 0.2 (meaningful relevance).

    Higher score = company is aligned with faster-growing budget areas.
    Returns weighted average, not normalized to 0-1.
    """
    weighted_sum = 0.0
    weight_sum = 0.0

    for priority in PolicyPriority:
        score = scores.get(priority.value, 0.0)
        if score > 0.2:  # Only count meaningful alignment
            weight = BUDGET_GROWTH_WEIGHTS.get(priority, 1.0)
            weighted_sum += score * weight
            weight_sum += weight

    # Weighted average of (score * budget_weight) for relevant priorities
    if weight_sum > 0:
        return round(weighted_sum / weight_sum, 3)
    return 0.0


def filter_valid_scores(scores: dict[str, float]) -> dict[str, float]:
    """Filter scores to only include valid priority names."""
    valid_priorities = {p.value for p in PolicyPriority}
    return {k: v for k, v in scores.items() if k in valid_priorities}


# =============================================================================
# CORE SCORING FUNCTION
# =============================================================================

def score_entity_alignment(
    client: Anthropic,
    db: Session,
    entity: Entity,
    model: str = "claude-sonnet-4-20250514",
) -> Optional[AlignmentResult]:
    """
    Score a single entity's policy alignment using Claude.

    Args:
        client: Anthropic client
        db: Database session
        entity: Entity to score
        model: Claude model to use

    Returns:
        AlignmentResult or None if scoring failed
    """
    # Get SBIR awards
    awards = get_sbir_awards(db, entity.id)
    if not awards:
        logger.warning(f"No SBIR awards found for {entity.canonical_name}")
        return None

    # Build prompt
    sbir_list = format_sbir_list(awards)
    priority_descriptions = format_priority_descriptions()

    core_business_str = entity.core_business.value if entity.core_business else "unknown"

    prompt = ALIGNMENT_PROMPT.format(
        company_name=entity.canonical_name,
        core_business=core_business_str,
        location=entity.headquarters_location or "Unknown",
        award_count=len(awards),
        sbir_list=sbir_list,
        priority_descriptions=priority_descriptions,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()

        # Parse JSON response
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)
        scores = result.get("scores", {})
        modifiers = result.get("modifiers", {})

        # Calculate composite score
        policy_tailwind = calculate_policy_tailwind(scores)

        return AlignmentResult(
            entity_id=entity.id,
            entity_name=entity.canonical_name,
            scores=scores,
            modifiers=modifiers,
            top_priorities=result.get("top_priorities", []),
            reasoning=result.get("reasoning", ""),
            policy_tailwind=policy_tailwind,
            sbir_count=len(awards),
            raw_response=raw_text,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON for {entity.canonical_name}: {e}")
        logger.error(f"Raw response: {raw_text[:500]}")
        return None
    except Exception as e:
        logger.error(f"Scoring failed for {entity.canonical_name}: {e}")
        return None


async def score_entity_alignment_async(
    client: AsyncAnthropic,
    entity_data: dict,
    model: str = "claude-sonnet-4-20250514",
) -> Optional[AlignmentResult]:
    """
    Async version: Score a single entity's policy alignment using Claude.

    Args:
        client: AsyncAnthropic client
        entity_data: Pre-fetched entity data dict with awards
        model: Claude model to use

    Returns:
        AlignmentResult or None if scoring failed
    """
    awards = entity_data["awards"]
    entity_id = entity_data["id"]
    entity_name = entity_data["name"]

    if not awards:
        logger.warning(f"No SBIR awards found for {entity_name}")
        return None

    # Build prompt
    sbir_list = format_sbir_list(awards)
    priority_descriptions = format_priority_descriptions()

    prompt = ALIGNMENT_PROMPT.format(
        company_name=entity_name,
        core_business=entity_data.get("core_business", "unknown"),
        location=entity_data.get("location", "Unknown"),
        award_count=len(awards),
        sbir_list=sbir_list,
        priority_descriptions=priority_descriptions,
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()

        # Parse JSON response
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)
        scores = result.get("scores", {})
        modifiers = result.get("modifiers", {})

        # Calculate composite score
        policy_tailwind = calculate_policy_tailwind(scores)

        return AlignmentResult(
            entity_id=entity_id,
            entity_name=entity_name,
            scores=scores,
            modifiers=modifiers,
            top_priorities=result.get("top_priorities", []),
            reasoning=result.get("reasoning", ""),
            policy_tailwind=policy_tailwind,
            sbir_count=len(awards),
            raw_response=raw_text,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON for {entity_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Scoring failed for {entity_name}: {e}")
        return None


def save_alignment(db: Session, result: AlignmentResult, dry_run: bool = False):
    """Save alignment result to database."""
    from datetime import date as date_type

    entity = db.query(Entity).filter(Entity.id == result.entity_id).first()
    if not entity:
        logger.error(f"Entity not found: {result.entity_id}")
        return

    # Store in policy_alignment JSON field (filter to valid priorities only)
    valid_scores = filter_valid_scores(result.scores)
    valid_priorities = {p.value for p in PolicyPriority}
    valid_top = [p for p in result.top_priorities if p in valid_priorities]

    entity.policy_alignment = {
        "scores": valid_scores,
        "pacific_relevance": result.modifiers.get("pacific_relevance", False),
        "top_priorities": valid_top,
        "policy_tailwind_score": result.policy_tailwind,
        "reasoning": result.reasoning,
        "scored_date": date_type.today().isoformat(),
    }

    if not dry_run:
        db.commit()


# =============================================================================
# MAIN RUNNER
# =============================================================================

def run_alignment_scoring(
    db: Session,
    client: Anthropic,
    entity_names: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
) -> ScorerStats:
    """
    Run policy alignment scoring on entities.

    Args:
        db: Database session
        client: Anthropic client
        entity_names: Specific entity names to score (None = all classified)
        limit: Max entities to process
        dry_run: If True, don't save to database
        model: Claude model to use

    Returns:
        ScorerStats with results
    """
    stats = ScorerStats()

    # Get entities to score
    if entity_names:
        entities = (
            db.query(Entity)
            .filter(
                Entity.canonical_name.in_(entity_names),
                Entity.merged_into_id.is_(None),
            )
            .all()
        )
    else:
        # Get classified entities with SBIR awards
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
        entities = (
            db.query(Entity)
            .filter(
                Entity.id.in_(entity_ids_with_sbir),
                Entity.merged_into_id.is_(None),
                Entity.entity_type == EntityType.STARTUP,
                Entity.core_business.isnot(None),
                Entity.core_business != CoreBusiness.UNCLASSIFIED,
            )
            .all()
        )

    if limit:
        entities = entities[:limit]

    logger.info("=" * 70)
    logger.info("POLICY ALIGNMENT SCORER")
    logger.info("=" * 70)
    logger.info(f"Entities to process: {len(entities)}")
    logger.info(f"Model: {model}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 70)

    for i, entity in enumerate(entities, 1):
        logger.info(f"\n[{i}/{len(entities)}] {entity.canonical_name}")

        result = score_entity_alignment(client, db, entity, model=model)
        stats.total_processed += 1

        if result:
            stats.successful += 1

            # Track high-alignment entities
            if any(s >= 0.7 for s in result.scores.values()):
                stats.high_alignment += 1

            # Track by priority (only count known priorities)
            valid_priorities = {p.value for p in PolicyPriority}
            for priority, score in result.scores.items():
                if priority not in valid_priorities:
                    continue  # Skip unexpected priorities from LLM
                if score >= 0.7:
                    stats.by_priority[priority]["high"] += 1
                elif score >= 0.4:
                    stats.by_priority[priority]["medium"] += 1
                else:
                    stats.by_priority[priority]["low"] += 1

            pacific_tag = " [PACIFIC]" if result.modifiers.get("pacific_relevance") else ""
            logger.info(f"  Policy tailwind: {result.policy_tailwind:.3f}{pacific_tag}")
            logger.info(f"  Top priorities: {', '.join(result.top_priorities) or 'none'}")
            logger.info(f"  {result.reasoning[:80]}...")

            save_alignment(db, result, dry_run=dry_run)
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
    logger.info(f"High alignment (>= 0.7 in any area): {stats.high_alignment}")
    logger.info("")
    logger.info("Entities with high alignment by priority:")
    for priority, counts in sorted(
        stats.by_priority.items(),
        key=lambda x: -x[1]["high"]
    ):
        logger.info(f"  {priority:25}: {counts['high']} high, {counts['medium']} medium")

    if dry_run:
        logger.info("\nDRY RUN - no changes saved to database.")

    return stats


# =============================================================================
# ASYNC CONCURRENT RUNNER
# =============================================================================

def prefetch_entity_data(db: Session, entities: list[Entity]) -> list[dict]:
    """
    Pre-fetch all entity data including SBIR awards for async processing.
    This avoids database access during async operations.
    """
    entity_data_list = []
    for entity in entities:
        awards = get_sbir_awards(db, entity.id)
        entity_data_list.append({
            "id": entity.id,
            "name": entity.canonical_name,
            "core_business": entity.core_business.value if entity.core_business else "unknown",
            "location": entity.headquarters_location or "Unknown",
            "awards": awards,
        })
    return entity_data_list


async def process_entity_with_semaphore(
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic,
    entity_data: dict,
    index: int,
    total: int,
    model: str,
) -> tuple[int, Optional[AlignmentResult]]:
    """Process a single entity with semaphore for rate limiting."""
    async with semaphore:
        logger.info(f"[{index}/{total}] {entity_data['name']}")
        result = await score_entity_alignment_async(client, entity_data, model=model)
        return index, result


async def run_alignment_scoring_async(
    db: Session,
    client: AsyncAnthropic,
    entity_names: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
    concurrency: int = 10,
    skip_scored: bool = False,
) -> ScorerStats:
    """
    Async version: Run policy alignment scoring with concurrent API calls.

    Args:
        db: Database session
        client: AsyncAnthropic client
        entity_names: Specific entity names to score (None = all classified)
        limit: Max entities to process
        dry_run: If True, don't save to database
        model: Claude model to use
        concurrency: Number of concurrent API calls (default 10)
        skip_scored: If True, skip entities that already have policy_alignment

    Returns:
        ScorerStats with results
    """
    stats = ScorerStats()

    # Get entities to score (same logic as sync version)
    if entity_names:
        query = (
            db.query(Entity)
            .filter(
                Entity.canonical_name.in_(entity_names),
                Entity.merged_into_id.is_(None),
            )
        )
        if skip_scored:
            query = query.filter(Entity.policy_alignment.is_(None))
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
                Entity.core_business.isnot(None),
                Entity.core_business != CoreBusiness.UNCLASSIFIED,
            )
        )
        if skip_scored:
            query = query.filter(Entity.policy_alignment.is_(None))
        entities = query.all()

    if limit:
        entities = entities[:limit]

    logger.info("=" * 70)
    logger.info("POLICY ALIGNMENT SCORER (ASYNC)")
    logger.info("=" * 70)
    logger.info(f"Entities to process: {len(entities)}")
    logger.info(f"Model: {model}")
    logger.info(f"Concurrency: {concurrency}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 70)

    # Pre-fetch all entity data (including SBIR awards) synchronously
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
    for index, result in results:
        stats.total_processed += 1
        entity_data = entity_data_list[index - 1]

        if result:
            stats.successful += 1

            # Track high-alignment entities
            # Guard against malformed LLM responses where scores may be dicts
            if any(isinstance(s, (int, float)) and s >= 0.7 for s in result.scores.values()):
                stats.high_alignment += 1

            # Track by priority (only count known priorities)
            valid_priorities = {p.value for p in PolicyPriority}
            for priority, score in result.scores.items():
                if priority not in valid_priorities:
                    continue
                if not isinstance(score, (int, float)):
                    continue
                if score >= 0.7:
                    stats.by_priority[priority]["high"] += 1
                elif score >= 0.4:
                    stats.by_priority[priority]["medium"] += 1
                else:
                    stats.by_priority[priority]["low"] += 1

            pacific_tag = " [PACIFIC]" if result.modifiers.get("pacific_relevance") else ""
            logger.info(f"  -> {entity_data['name']}: {result.policy_tailwind:.3f}{pacific_tag}")

            save_alignment(db, result, dry_run=dry_run)
        else:
            stats.failed += 1
            logger.error(f"  -> {entity_data['name']}: FAILED")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total processed: {stats.total_processed}")
    logger.info(f"Successful: {stats.successful}")
    logger.info(f"Failed: {stats.failed}")
    logger.info(f"High alignment (>= 0.7 in any area): {stats.high_alignment}")
    logger.info("")
    logger.info("Entities with high alignment by priority:")
    for priority, counts in sorted(
        stats.by_priority.items(),
        key=lambda x: -x[1]["high"]
    ):
        logger.info(f"  {priority:25}: {counts['high']} high, {counts['medium']} medium")

    if dry_run:
        logger.info("\nDRY RUN - no changes saved to database.")

    return stats


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Score company alignment with NDS priority areas"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test on specific companies",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Score all classified entities with SBIR awards",
    )
    parser.add_argument(
        "--names",
        type=str,
        nargs="+",
        help="Specific company names to score",
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
        help="Claude model to use",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the prompt template and exit",
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
        "--skip-scored",
        action="store_true",
        help="Skip entities that already have policy_alignment scores",
    )

    args = parser.parse_args()

    # Show prompt template
    if args.show_prompt:
        print("=" * 70)
        print("POLICY ALIGNMENT PROMPT TEMPLATE")
        print("=" * 70)
        print(ALIGNMENT_PROMPT.format(
            company_name="[COMPANY_NAME]",
            core_business="[CORE_BUSINESS]",
            location="[LOCATION]",
            award_count="[N]",
            sbir_list="[SBIR AWARDS LISTED HERE]",
            priority_descriptions=format_priority_descriptions(),
        ))
        print("\n" + "=" * 70)
        print("BUDGET GROWTH WEIGHTS (for policy_tailwind calculation)")
        print("=" * 70)
        for p, w in sorted(BUDGET_GROWTH_WEIGHTS.items(), key=lambda x: -x[1]):
            print(f"  {p.value:25}: {w:.2f}x")
        return

    # Check for API key
    api_key = settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    db = SessionLocal()

    try:
        # Test companies for --test mode
        test_companies = [
            "HAVENLOCK INC",                      # Door locks - should score low overall
            "TETRATE.IO, INC.",                   # Service mesh software - cyber only
            "MATRIXSPACE, INC",                   # RF hardware - EW, JADC2, space
            "PHASE SENSITIVE INNOVATIONS INC",   # RF components - EW
            "TERASPATIAL INC",                   # mmWave - JADC2, space
            "THRUST AI LLC",                      # AI software - autonomous
            "ZENITH AEROSPACE INC",              # UAS - autonomous, contested logistics
            "FOURTH STATE COMMUNICATIONS, LLC",  # BLOS comms - JADC2, contested logistics
            "SOLSTAR SPACE COMPANY",             # Space comms - space_resilience
            "XL SCIENTIFIC LLC",                  # RF/antenna - EW, JADC2
        ]

        if args.use_async:
            # Async concurrent mode
            async_client = AsyncAnthropic(api_key=api_key)

            async def run_async():
                if args.test:
                    return await run_alignment_scoring_async(
                        db, async_client,
                        entity_names=test_companies,
                        dry_run=args.dry_run,
                        model=args.model,
                        concurrency=args.concurrency,
                        skip_scored=args.skip_scored,
                    )
                elif args.names:
                    return await run_alignment_scoring_async(
                        db, async_client,
                        entity_names=args.names,
                        dry_run=args.dry_run,
                        model=args.model,
                        concurrency=args.concurrency,
                        skip_scored=args.skip_scored,
                    )
                elif args.all:
                    return await run_alignment_scoring_async(
                        db, async_client,
                        limit=args.limit,
                        dry_run=args.dry_run,
                        model=args.model,
                        concurrency=args.concurrency,
                        skip_scored=args.skip_scored,
                    )
                else:
                    parser.print_help()
                    return None

            asyncio.run(run_async())
        else:
            # Sync sequential mode (original behavior)
            client = Anthropic(api_key=api_key)

            if args.test:
                run_alignment_scoring(
                    db, client,
                    entity_names=test_companies,
                    dry_run=args.dry_run,
                    model=args.model,
                )
            elif args.names:
                run_alignment_scoring(
                    db, client,
                    entity_names=args.names,
                    dry_run=args.dry_run,
                    model=args.model,
                )
            elif args.all:
                run_alignment_scoring(
                    db, client,
                    limit=args.limit,
                    dry_run=args.dry_run,
                    model=args.model,
                )
            else:
                parser.print_help()

    finally:
        db.close()


if __name__ == "__main__":
    main()
