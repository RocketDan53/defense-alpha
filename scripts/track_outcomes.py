#!/usr/bin/env python3
"""
Track outcomes for entities with active signals.

Detects new events (contracts, funding, SBIR advancement) and creates
OutcomeEvent records linked back to the signals that predicted them.
This enables measuring signal predictive accuracy over time.

Usage:
    python scripts/track_outcomes.py --since 2026-01-01
    python scripts/track_outcomes.py --since 2026-01-01 --dry-run
    python scripts/track_outcomes.py --since 2026-01-01 --detector new_contract
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from processing.database import SessionLocal
from processing.models import (
    Contract,
    Entity,
    EntityType,
    FundingEvent,
    FundingEventType,
    OutcomeEvent,
    OutcomeType,
    Signal,
    SignalStatus,
)


@dataclass
class OutcomeStats:
    """Statistics for outcome tracking run."""

    entities_checked: int = 0
    new_contracts: int = 0
    funding_raises: int = 0
    sbir_advances: int = 0
    acquisitions: int = 0
    new_agencies: int = 0
    recompete_losses: int = 0
    inactive_companies: int = 0
    sbir_stalls: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None

    @property
    def total_outcomes(self) -> int:
        return (
            self.new_contracts
            + self.funding_raises
            + self.sbir_advances
            + self.acquisitions
            + self.new_agencies
            + self.recompete_losses
            + self.inactive_companies
            + self.sbir_stalls
        )


def get_entities_with_signals(db: Session, since: date) -> list[Entity]:
    """
    Get all entities that have active signals.

    Returns entities that had signals active at any point since the given date,
    so we can track outcomes for predictions made in that window.
    """
    # Get entity IDs with active signals
    entity_ids = (
        db.query(Signal.entity_id)
        .filter(Signal.status == SignalStatus.ACTIVE)
        .distinct()
        .all()
    )
    entity_ids = [eid[0] for eid in entity_ids]

    if not entity_ids:
        return []

    # Get the full entities
    entities = (
        db.query(Entity)
        .filter(Entity.id.in_(entity_ids))
        .filter(Entity.merged_into_id.is_(None))
        .filter(Entity.entity_type == EntityType.STARTUP)
        .all()
    )

    return entities


def get_active_signals_for_entity(db: Session, entity_id: str) -> list[Signal]:
    """Get all active signals for an entity."""
    return (
        db.query(Signal)
        .filter(Signal.entity_id == entity_id)
        .filter(Signal.status == SignalStatus.ACTIVE)
        .all()
    )


def calculate_months_since_signal(
    outcome_date: date, signals: list[Signal]
) -> Optional[int]:
    """Calculate months between earliest signal and outcome."""
    if not signals:
        return None

    earliest = min(
        s.detected_date for s in signals if s.detected_date is not None
    )
    if earliest is None:
        return None

    delta = outcome_date - earliest
    return max(0, delta.days // 30)


def outcome_exists(db: Session, source_key: str) -> bool:
    """Check if an outcome with this source key already exists."""
    return (
        db.query(OutcomeEvent).filter(OutcomeEvent.source_key == source_key).first()
        is not None
    )


# =============================================================================
# DETECTOR: new_contract
# =============================================================================


def detect_new_contracts(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect new contracts awarded since the given date.

    Compares current contracts against what existed when signals were detected.
    A contract is "new" if:
    - award_date >= since date
    - Not already recorded as an OutcomeEvent
    """
    outcomes = []

    # Get contracts awarded since the cutoff date
    new_contracts = (
        db.query(Contract)
        .filter(Contract.entity_id == entity.id)
        .filter(Contract.award_date >= since)
        .all()
    )

    if not new_contracts:
        return outcomes

    # Get active signals for linking
    signals = get_active_signals_for_entity(db, entity.id)
    signal_ids = [s.id for s in signals]

    for contract in new_contracts:
        source_key = f"contract:{contract.contract_number}"

        # Skip if already tracked
        if outcome_exists(db, source_key):
            continue

        months = calculate_months_since_signal(contract.award_date, signals)

        outcome = OutcomeEvent(
            entity_id=entity.id,
            outcome_type=OutcomeType.NEW_CONTRACT,
            outcome_date=contract.award_date,
            outcome_value=contract.contract_value,
            details={
                "contract_number": contract.contract_number,
                "contracting_agency": contract.contracting_agency,
                "naics_code": contract.naics_code,
                "psc_code": contract.psc_code,
                "contract_type": contract.contract_type,
            },
            source="usaspending",
            related_signal_ids=signal_ids,
            months_since_signal=months,
            source_key=source_key,
        )

        if not dry_run:
            db.add(outcome)

        outcomes.append(outcome)

    return outcomes


# =============================================================================
# DETECTOR: funding_raise
# =============================================================================


def detect_funding_raises(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect funding events (Reg D filings, VC rounds) that occurred AFTER
    a signal was detected for this entity.

    Logic: For entities with active signals, find any funding_events with
    event_type in ('reg_d_filing', 'vc_round') where event_date is after
    the entity's earliest signal detected_date. This detects cases where
    we flagged a company and they subsequently raised private capital.
    """
    outcomes = []

    # Get active signals and find the earliest detection date
    signals = get_active_signals_for_entity(db, entity.id)
    if not signals:
        return outcomes

    signal_dates = [s.detected_date for s in signals if s.detected_date is not None]
    if not signal_dates:
        return outcomes

    earliest_signal_date = min(signal_dates)
    signal_ids = [s.id for s in signals]

    # Skip entities with no defense footprint (0 SBIRs AND 0 contracts)
    sbir_count = (
        db.query(func.count(FundingEvent.id))
        .filter(
            FundingEvent.entity_id == entity.id,
            FundingEvent.event_type.in_([
                FundingEventType.SBIR_PHASE_1,
                FundingEventType.SBIR_PHASE_2,
                FundingEventType.SBIR_PHASE_3,
            ]),
        )
        .scalar()
    )
    contract_count = (
        db.query(func.count(Contract.id))
        .filter(Contract.entity_id == entity.id)
        .scalar()
    )
    if sbir_count == 0 and contract_count == 0:
        return outcomes

    # Find funding events after earliest signal date
    funding_events_raw = (
        db.query(FundingEvent)
        .filter(
            FundingEvent.entity_id == entity.id,
            FundingEvent.event_type.in_([
                FundingEventType.REG_D_FILING,
                FundingEventType.VC_ROUND,
            ]),
            FundingEvent.event_date >= earliest_signal_date,
            FundingEvent.event_date >= since,
        )
        .all()
    )

    if not funding_events_raw:
        return outcomes

    # Deduplicate: SEC EDGAR amended filings create rows with
    # identical (entity_id, event_date, amount). Keep one per group.
    seen_keys = set()
    funding_events = []
    for fe in funding_events_raw:
        dedup_key = (str(fe.entity_id), str(fe.event_date), str(fe.amount))
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        funding_events.append(fe)

    for fe in funding_events:
        source_key = f"funding_{fe.id}"

        # Deduplication: skip if already tracked
        if outcome_exists(db, source_key):
            continue

        months = calculate_months_since_signal(fe.event_date, signals)

        # Build details from funding event fields
        details = {
            "event_type": fe.event_type.value,
            "round_stage": fe.round_stage,
            "investors_awarders": fe.investors_awarders,
            "source": fe.source,
        }
        # Include any raw_data fields that might be useful
        if fe.raw_data:
            for key in ("form_type", "filing_date", "cik", "accession_number"):
                if key in fe.raw_data:
                    details[key] = fe.raw_data[key]

        source = fe.source or ("sec_edgar" if fe.event_type == FundingEventType.REG_D_FILING else "crunchbase")

        outcome = OutcomeEvent(
            entity_id=entity.id,
            outcome_type=OutcomeType.FUNDING_RAISE,
            outcome_date=fe.event_date,
            outcome_value=fe.amount,
            details=details,
            source=source,
            related_signal_ids=signal_ids,
            months_since_signal=months,
            source_key=source_key,
        )

        if not dry_run:
            db.add(outcome)

        outcomes.append(outcome)

    return outcomes


# =============================================================================
# DETECTOR: sbir_advance (STUB)
# =============================================================================


def detect_sbir_advances(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect SBIR phase progressions since the given date.

    TODO: Implement phase advancement detection.
    Will look for:
    - Entity that had Phase I now has Phase II (or II -> III)
    - Based on FundingEvent records with SBIR types
    """
    # STUB: Not yet implemented
    return []


# =============================================================================
# DETECTOR: acquisition (STUB)
# =============================================================================


def detect_acquisitions(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect if entity was acquired.

    TODO: Implement acquisition detection.
    Will look for:
    - FundingEvent with event_type = ACQUISITION
    - Or entity merged_into_id is set
    """
    # STUB: Not yet implemented
    return []


# =============================================================================
# DETECTOR: new_agency (STUB)
# =============================================================================


def detect_new_agencies(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect contracts with new DoD agencies (agency diversification).

    TODO: Implement new agency detection.
    Will look for:
    - New contracts where contracting_agency is different from all prior agencies
    """
    # STUB: Not yet implemented
    return []


# =============================================================================
# DETECTOR: recompete_loss (STUB)
# =============================================================================


def detect_recompete_losses(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect lost contract recompetes.

    TODO: Implement recompete loss detection.
    Will require tracking contract end dates and checking if renewed.
    """
    # STUB: Not yet implemented
    return []


# =============================================================================
# DETECTOR: company_inactive (STUB)
# =============================================================================


def detect_inactive_companies(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect companies with no activity for 12+ months.

    TODO: Implement inactivity detection.
    Will check if entity has no new contracts, funding, or SBIRs in 12 months.
    """
    # STUB: Not yet implemented
    return []


# =============================================================================
# DETECTOR: sbir_stall (STUB)
# =============================================================================


def detect_sbir_stalls(
    db: Session, entity: Entity, since: date, dry_run: bool = False
) -> list[OutcomeEvent]:
    """
    Detect SBIR stalls (Phase I with no advancement after 24+ months).

    TODO: Implement SBIR stall detection.
    Will check entities with Phase I but no Phase II after sufficient time.
    """
    # STUB: Not yet implemented
    return []


# =============================================================================
# MAIN ORCHESTRATION
# =============================================================================

DETECTORS = {
    "new_contract": detect_new_contracts,
    "funding_raise": detect_funding_raises,
    "sbir_advance": detect_sbir_advances,
    "acquisition": detect_acquisitions,
    "new_agency": detect_new_agencies,
    "recompete_loss": detect_recompete_losses,
    "company_inactive": detect_inactive_companies,
    "sbir_stall": detect_sbir_stalls,
}


def run_outcome_tracking(
    db: Session,
    since: date,
    dry_run: bool = False,
    detectors: Optional[list[str]] = None,
) -> OutcomeStats:
    """
    Run outcome tracking for all entities with active signals.

    Args:
        db: Database session
        since: Only detect outcomes on or after this date
        dry_run: If True, don't commit changes
        detectors: List of detector names to run (None = all)

    Returns:
        OutcomeStats with counts of detected outcomes
    """
    stats = OutcomeStats()

    # Determine which detectors to run
    if detectors is None:
        active_detectors = DETECTORS
    else:
        active_detectors = {k: v for k, v in DETECTORS.items() if k in detectors}

    print("=" * 70)
    print("OUTCOME TRACKER")
    print("=" * 70)
    print(f"Since: {since}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Detectors: {', '.join(active_detectors.keys())}")
    print("=" * 70)

    # Get entities to check
    entities = get_entities_with_signals(db, since)
    stats.entities_checked = len(entities)
    print(f"\nEntities with active signals: {len(entities)}")

    if not entities:
        print("No entities to check.")
        stats.end_time = datetime.now()
        return stats

    # Run detectors for each entity
    for i, entity in enumerate(entities, 1):
        print(f"\n[{i}/{len(entities)}] {entity.canonical_name}")

        for detector_name, detector_fn in active_detectors.items():
            try:
                outcomes = detector_fn(db, entity, since, dry_run)

                for outcome in outcomes:
                    # Update stats
                    if outcome.outcome_type == OutcomeType.NEW_CONTRACT:
                        stats.new_contracts += 1
                        value_str = (
                            f"${outcome.outcome_value:,.0f}"
                            if outcome.outcome_value
                            else "N/A"
                        )
                        print(f"  + NEW_CONTRACT: {value_str}")
                    elif outcome.outcome_type == OutcomeType.FUNDING_RAISE:
                        stats.funding_raises += 1
                        value_str = (
                            f"${outcome.outcome_value:,.0f}"
                            if outcome.outcome_value
                            else "N/A"
                        )
                        months_str = (
                            f" ({outcome.months_since_signal}mo after signal)"
                            if outcome.months_since_signal
                            else ""
                        )
                        print(f"  + FUNDING_RAISE: {value_str}{months_str}")
                    elif outcome.outcome_type == OutcomeType.SBIR_ADVANCE:
                        stats.sbir_advances += 1
                        print(f"  + SBIR_ADVANCE")
                    elif outcome.outcome_type == OutcomeType.ACQUISITION:
                        stats.acquisitions += 1
                        print(f"  + ACQUISITION")
                    elif outcome.outcome_type == OutcomeType.NEW_AGENCY:
                        stats.new_agencies += 1
                        print(f"  + NEW_AGENCY")
                    elif outcome.outcome_type == OutcomeType.RECOMPETE_LOSS:
                        stats.recompete_losses += 1
                        print(f"  - RECOMPETE_LOSS")
                    elif outcome.outcome_type == OutcomeType.COMPANY_INACTIVE:
                        stats.inactive_companies += 1
                        print(f"  - COMPANY_INACTIVE")
                    elif outcome.outcome_type == OutcomeType.SBIR_STALL:
                        stats.sbir_stalls += 1
                        print(f"  - SBIR_STALL")

            except Exception as e:
                stats.errors += 1
                print(f"  ERROR in {detector_name}: {e}")

    # Commit if not dry run
    if not dry_run:
        db.commit()
        print("\nChanges committed to database.")
    else:
        print("\nDRY RUN - no changes made.")

    stats.end_time = datetime.now()
    return stats


def print_summary(stats: OutcomeStats):
    """Print summary of outcome tracking run."""
    duration = (stats.end_time - stats.start_time).total_seconds()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Entities checked:     {stats.entities_checked}")
    print(f"Total outcomes:       {stats.total_outcomes}")
    print(f"  - New contracts:    {stats.new_contracts}")
    print(f"  - Funding raises:   {stats.funding_raises}")
    print(f"  - SBIR advances:    {stats.sbir_advances}")
    print(f"  - Acquisitions:     {stats.acquisitions}")
    print(f"  - New agencies:     {stats.new_agencies}")
    print(f"  - Recompete losses: {stats.recompete_losses}")
    print(f"  - Inactive:         {stats.inactive_companies}")
    print(f"  - SBIR stalls:      {stats.sbir_stalls}")
    print(f"Duplicates skipped:   {stats.duplicates_skipped}")
    print(f"Errors:               {stats.errors}")
    print(f"Duration:             {duration:.1f}s")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Track outcomes for entities with active signals"
    )
    parser.add_argument(
        "--since",
        type=str,
        required=True,
        help="Track outcomes since this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't commit changes to database",
    )
    parser.add_argument(
        "--detector",
        type=str,
        choices=list(DETECTORS.keys()),
        help="Run only this detector (default: all)",
    )
    args = parser.parse_args()

    # Parse since date
    try:
        since = datetime.strptime(args.since, "%Y-%m-%d").date()
    except ValueError:
        print(f"ERROR: Invalid date format: {args.since}")
        print("Expected format: YYYY-MM-DD")
        sys.exit(1)

    # Determine detectors to run
    detectors = [args.detector] if args.detector else None

    # Run tracking
    db = SessionLocal()
    try:
        stats = run_outcome_tracking(
            db=db,
            since=since,
            dry_run=args.dry_run,
            detectors=detectors,
        )
        print_summary(stats)
    finally:
        db.close()


if __name__ == "__main__":
    main()
