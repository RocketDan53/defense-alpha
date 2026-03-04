#!/usr/bin/env python3
"""Aperture Signals — Notional Fund Manager.

VC-style notional fund system for validating signal-based thesis in real time
and measuring differential alpha against baseline cohorts.

Usage:
    # Strategy management
    python Fund/fund_manager.py strategy create --name "Next Wave" --config Fund/strategies/next_wave.json
    python Fund/fund_manager.py strategy list
    python Fund/fund_manager.py strategy show --name "Next Wave"
    python Fund/fund_manager.py strategy activate --name "Next Wave"

    # Cohort deployment
    python Fund/fund_manager.py deploy --strategy "Next Wave" --vintage "2026-Q1" --dry-run
    python Fund/fund_manager.py deploy --strategy "Next Wave" --vintage "2026-Q1"

    # Milestone tracking
    python Fund/fund_manager.py track --since 2026-01-01 --dry-run
    python Fund/fund_manager.py track --since 2026-01-01

    # Performance reporting
    python Fund/fund_manager.py performance --strategy "Next Wave"
    python Fund/fund_manager.py performance --all
"""

import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from processing.database import SessionLocal
from processing.models import (
    Base,
    Entity, EntityType, Signal, SignalStatus,
    FundingEvent, FundingEventType, Contract,
    EntitySnapshot,
    FundStrategy, FundCohort, FundPosition, FundMilestone,
    StrategyStatus, CohortType, PositionStatus, MilestoneType,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_strategy(db: Session, name: str) -> FundStrategy | None:
    return db.query(FundStrategy).filter(FundStrategy.name == name).first()


def _compute_lifecycle_stage(db: Session, entity_id: str) -> str:
    """Compute lifecycle stage for an entity (matches aperture_query logic)."""
    p1 = db.query(func.count(FundingEvent.id)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type == FundingEventType.SBIR_PHASE_1,
    ).scalar() or 0
    p2 = db.query(func.count(FundingEvent.id)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type == FundingEventType.SBIR_PHASE_2,
    ).scalar() or 0
    p3 = db.query(func.count(FundingEvent.id)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type == FundingEventType.SBIR_PHASE_3,
    ).scalar() or 0
    contract_count = db.query(func.count(Contract.id)).filter(
        Contract.entity_id == entity_id,
    ).scalar() or 0
    max_contract = db.query(func.max(Contract.contract_value)).filter(
        Contract.entity_id == entity_id,
    ).scalar() or 0
    regd_total = db.query(func.coalesce(func.sum(FundingEvent.amount), 0)).filter(
        FundingEvent.entity_id == entity_id,
        FundingEvent.event_type.in_([
            FundingEventType.REG_D_FILING,
            FundingEventType.PRIVATE_ROUND,
        ]),
    ).scalar() or 0

    if p3 > 0 or (contract_count > 0 and float(max_contract or 0) > 1_000_000):
        return "Production"
    elif contract_count > 1 and float(regd_total) > 0:
        return "Growth"
    elif p2 > 0 or (contract_count > 0 and float(max_contract or 0) <= 1_000_000):
        return "Prototype"
    else:
        return "Pre-revenue R&D"


def _capture_entry_state(db: Session, entity: Entity) -> dict:
    """Capture full entity state at time of cohort entry."""
    # Get latest snapshot
    snapshot = db.query(EntitySnapshot).filter(
        EntitySnapshot.entity_id == entity.id,
    ).order_by(EntitySnapshot.snapshot_date.desc()).first()

    # Get active signals
    signals = db.query(Signal).filter(
        Signal.entity_id == entity.id,
        Signal.status == SignalStatus.ACTIVE,
    ).all()

    signal_list = [
        {
            "signal_type": s.signal_type,
            "confidence": float(s.confidence_score or 0),
            "freshness_weight": float(s.freshness_weight or 1.0),
            "detected_date": str(s.detected_date) if s.detected_date else None,
        }
        for s in signals
    ]

    # SBIR counts
    sbir_count = db.query(func.count(FundingEvent.id)).filter(
        FundingEvent.entity_id == entity.id,
        FundingEvent.event_type.in_([
            FundingEventType.SBIR_PHASE_1,
            FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]),
    ).scalar() or 0

    # Contracts
    contract_agg = db.query(
        func.count(Contract.id),
        func.coalesce(func.sum(Contract.contract_value), 0),
    ).filter(Contract.entity_id == entity.id).one()

    # Reg D / Private rounds
    regd_agg = db.query(
        func.count(FundingEvent.id),
        func.coalesce(func.sum(FundingEvent.amount), 0),
    ).filter(
        FundingEvent.entity_id == entity.id,
        FundingEvent.event_type.in_([
            FundingEventType.REG_D_FILING,
            FundingEventType.PRIVATE_ROUND,
        ]),
    ).one()

    # Policy tailwind
    policy_tailwind = None
    if entity.policy_alignment and isinstance(entity.policy_alignment, dict):
        policy_tailwind = entity.policy_alignment.get("policy_tailwind_score")

    lifecycle = _compute_lifecycle_stage(db, entity.id)

    return {
        "entry_composite_score": Decimal(str(snapshot.composite_score)) if snapshot and snapshot.composite_score else None,
        "entry_freshness_adjusted_score": Decimal(str(snapshot.freshness_adjusted_score)) if snapshot and snapshot.freshness_adjusted_score else None,
        "entry_policy_tailwind": Decimal(str(policy_tailwind)) if policy_tailwind else None,
        "entry_lifecycle_stage": lifecycle,
        "entry_signals": signal_list,
        "entry_sbir_count": sbir_count,
        "entry_contract_count": contract_agg[0],
        "entry_contract_value": Decimal(str(float(contract_agg[1]))),
        "entry_regd_count": regd_agg[0],
        "entry_regd_value": Decimal(str(float(regd_agg[1]))),
        "snapshot_id": snapshot.id if snapshot else None,
    }


def _get_score_for_entity(db: Session, entity_id: str, entity: Entity | None = None) -> dict:
    """Get composite/freshness-adjusted scores from latest snapshot."""
    snapshot = db.query(EntitySnapshot).filter(
        EntitySnapshot.entity_id == entity_id,
    ).order_by(EntitySnapshot.snapshot_date.desc()).first()

    if not snapshot:
        return {"composite_score": 0.0, "freshness_adjusted_score": 0.0, "policy_tailwind_score": 0.0}

    # Get policy tailwind from snapshot (preferred) or entity
    pt = float(snapshot.policy_tailwind_score or 0)
    if pt == 0 and entity and entity.policy_alignment and isinstance(entity.policy_alignment, dict):
        pt = float(entity.policy_alignment.get("policy_tailwind_score", 0) or 0)

    return {
        "composite_score": float(snapshot.composite_score or 0),
        "freshness_adjusted_score": float(snapshot.freshness_adjusted_score or 0),
        "policy_tailwind_score": pt,
    }


# ── Eligible Universe Query ─────────────────────────────────────────────


def query_eligible_universe(db: Session, criteria: dict) -> list[Entity]:
    """Apply selection criteria to build the eligible entity universe."""
    eu = criteria.get("eligible_universe", {})
    filters_cfg = criteria.get("filters", {})

    query = db.query(Entity).filter(
        Entity.entity_type == EntityType.STARTUP,
        Entity.merged_into_id.is_(None),
    )

    # Exclude merged
    if eu.get("exclude_merged", True):
        query = query.filter(Entity.merged_into_id.is_(None))

    # Require classified
    if eu.get("require_classified", False):
        query = query.filter(Entity.core_business.isnot(None))

    # Core business filter
    if eu.get("core_business_filter"):
        query = query.filter(Entity.core_business.in_(eu["core_business_filter"]))

    entities = query.all()

    # Post-filter: SBIR phase requirements
    min_p2 = eu.get("min_sbir_phase2", 0)
    min_sbir_count = eu.get("min_sbir_count", 0)
    max_regd = eu.get("max_regd_filings")
    min_composite = eu.get("min_composite_score", 0.0)

    # Signal filters
    excluded_signals = set(filters_cfg.get("excluded_signals", []))
    required_signals = set(filters_cfg.get("required_signals", []))
    min_policy_tailwind = filters_cfg.get("min_policy_tailwind", 0.0)

    eligible = []
    for entity in entities:
        # Check SBIR phase II minimum
        if min_p2 > 0:
            p2_count = db.query(func.count(FundingEvent.id)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type == FundingEventType.SBIR_PHASE_2,
            ).scalar() or 0
            if p2_count < min_p2:
                continue

        # Check min SBIR count
        if min_sbir_count > 0:
            sbir_count = db.query(func.count(FundingEvent.id)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
            ).scalar() or 0
            if sbir_count < min_sbir_count:
                continue

        # Check max Reg D filings
        if max_regd is not None:
            regd_count = db.query(func.count(FundingEvent.id)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.REG_D_FILING,
                    FundingEventType.PRIVATE_ROUND,
                ]),
            ).scalar() or 0
            if regd_count > max_regd:
                continue

        # Check excluded signals
        if excluded_signals:
            entity_signals = set(
                s.signal_type for s in db.query(Signal).filter(
                    Signal.entity_id == entity.id,
                    Signal.status == SignalStatus.ACTIVE,
                ).all()
            )
            if entity_signals & excluded_signals:
                continue

        # Check required signals
        if required_signals:
            entity_signals = set(
                s.signal_type for s in db.query(Signal).filter(
                    Signal.entity_id == entity.id,
                    Signal.status == SignalStatus.ACTIVE,
                ).all()
            )
            if not required_signals.issubset(entity_signals):
                continue

        # Check composite score minimum
        scores = _get_score_for_entity(db, entity.id, entity=entity)
        if min_composite > 0 and scores["composite_score"] < min_composite:
            continue

        # Check policy tailwind minimum
        if min_policy_tailwind > 0 and scores["policy_tailwind_score"] < min_policy_tailwind:
            continue

        # Check policy area minimum scores (e.g., space_resilience >= 0.5)
        policy_area_mins = filters_cfg.get("policy_area_min_scores", {})
        if policy_area_mins and entity.policy_alignment and isinstance(entity.policy_alignment, dict):
            area_scores = entity.policy_alignment.get("scores", {})
            skip = False
            for area, min_score in policy_area_mins.items():
                if area_scores.get(area, 0) < min_score:
                    skip = True
                    break
            if skip:
                continue
        elif policy_area_mins:
            continue  # No policy data but area minimums required

        # Check exclude gone stale
        if eu.get("exclude_gone_stale", False):
            stale = db.query(Signal).filter(
                Signal.entity_id == entity.id,
                Signal.signal_type == "gone_stale",
                Signal.status == SignalStatus.ACTIVE,
            ).first()
            if stale:
                continue

        eligible.append(entity)

    return eligible


def rank_entities(db: Session, entities: list[Entity], criteria: dict) -> list[tuple[Entity, dict]]:
    """Rank entities by the configured sort order. Returns (entity, scores) tuples."""
    ranking = criteria.get("ranking", {})
    primary = ranking.get("primary_sort", "freshness_adjusted_score")
    secondary = ranking.get("secondary_sort", "composite_score")
    desc = ranking.get("descending", True)

    scored = []
    for entity in entities:
        scores = _get_score_for_entity(db, entity.id, entity=entity)
        scored.append((entity, scores))

    def sort_key(item):
        _, s = item
        p = s.get(primary, 0.0)
        sec = s.get(secondary, 0.0)
        return (p, sec)

    scored.sort(key=sort_key, reverse=desc)
    return scored


# ── Strategy Subcommands ─────────────────────────────────────────────────


def cmd_strategy_create(db: Session, args):
    """Create a new fund strategy from a JSON config file."""
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    config = json.loads(config_path.read_text())

    name = args.name or config.get("name")
    if not name:
        print("Strategy name required (--name or in config file)")
        sys.exit(1)

    # Check for duplicate
    existing = _get_strategy(db, name)
    if existing:
        print(f"Strategy '{name}' already exists (status: {existing.status.value})")
        sys.exit(1)

    criteria = config.get("selection_criteria", config)
    if "selection_criteria" not in config and "eligible_universe" in config:
        criteria = config

    strategy = FundStrategy(
        name=name,
        description=config.get("description", ""),
        status=StrategyStatus.DRAFT,
        selection_criteria=criteria,
        target_cohort_size=int(config.get("target_cohort_size", 20)),
        deployment_frequency=config.get("deployment_frequency", "quarterly"),
    )

    db.add(strategy)
    db.commit()

    # Show eligible universe count
    eligible = query_eligible_universe(db, criteria)

    print(f"\n{'='*60}")
    print(f"STRATEGY CREATED: {name}")
    print(f"{'='*60}")
    print(f"  Status:            {strategy.status.value}")
    print(f"  Cohort size:       {strategy.target_cohort_size}")
    print(f"  Frequency:         {strategy.deployment_frequency}")
    print(f"  Eligible universe: {len(eligible)} companies")
    if strategy.description:
        print(f"  Description:       {strategy.description[:80]}...")
    print(f"\n  Activate with: python Fund/fund_manager.py strategy activate --name \"{name}\"")


def cmd_strategy_list(db: Session, args):
    """List all fund strategies."""
    strategies = db.query(FundStrategy).order_by(FundStrategy.created_at).all()

    if not strategies:
        print("No strategies defined yet.")
        return

    print(f"\n{'='*70}")
    print(f"FUND STRATEGIES")
    print(f"{'='*70}")
    print(f"\n  {'Name':<25} {'Status':<10} {'Size':>5} {'Cohorts':>8} {'Created':<12}")
    print(f"  {'-'*25} {'-'*10} {'-'*5} {'-'*8} {'-'*12}")

    for s in strategies:
        cohort_count = db.query(func.count(FundCohort.id)).filter(
            FundCohort.strategy_id == s.id,
            FundCohort.cohort_type == CohortType.SIGNAL,
        ).scalar() or 0
        created = str(s.created_at)[:10] if s.created_at else "?"
        print(f"  {s.name:<25} {s.status.value:<10} {int(s.target_cohort_size):>5} "
              f"{cohort_count:>8} {created}")


def cmd_strategy_show(db: Session, args):
    """Show details for a specific strategy."""
    strategy = _get_strategy(db, args.name)
    if not strategy:
        print(f"Strategy '{args.name}' not found.")
        sys.exit(1)

    eligible = query_eligible_universe(db, strategy.selection_criteria)
    cohorts = db.query(FundCohort).filter(
        FundCohort.strategy_id == strategy.id,
        FundCohort.cohort_type == CohortType.SIGNAL,
    ).order_by(FundCohort.deployed_at).all()

    print(f"\n{'='*60}")
    print(f"STRATEGY: {strategy.name}")
    print(f"{'='*60}")
    print(f"  Status:            {strategy.status.value}")
    print(f"  Cohort size:       {int(strategy.target_cohort_size)}")
    print(f"  Frequency:         {strategy.deployment_frequency}")
    print(f"  Eligible universe: {len(eligible)} companies")
    if strategy.description:
        print(f"  Description:       {strategy.description}")

    print(f"\n  Selection Criteria:")
    print(f"  {json.dumps(strategy.selection_criteria, indent=4)}")

    if cohorts:
        print(f"\n  Deployed Cohorts:")
        for c in cohorts:
            pos_count = db.query(func.count(FundPosition.id)).filter(
                FundPosition.cohort_id == c.id,
            ).scalar() or 0
            print(f"    {c.vintage_label} — deployed {c.deployed_at}, {pos_count} positions")


def cmd_strategy_activate(db: Session, args):
    """Activate a strategy for deployment."""
    strategy = _get_strategy(db, args.name)
    if not strategy:
        print(f"Strategy '{args.name}' not found.")
        sys.exit(1)

    if strategy.status == StrategyStatus.ACTIVE:
        print(f"Strategy '{args.name}' is already active.")
        return

    strategy.status = StrategyStatus.ACTIVE
    db.commit()
    print(f"Strategy '{args.name}' activated.")


# ── Deploy Subcommand ────────────────────────────────────────────────────


def cmd_deploy(db: Session, args):
    """Deploy a cohort for a strategy."""
    strategy = _get_strategy(db, args.strategy)
    if not strategy:
        print(f"Strategy '{args.strategy}' not found.")
        sys.exit(1)

    if strategy.status != StrategyStatus.ACTIVE:
        print(f"Strategy '{args.strategy}' is not active (status: {strategy.status.value}). Activate first.")
        sys.exit(1)

    # Check for existing cohort with same vintage
    existing_cohort = db.query(FundCohort).filter(
        FundCohort.strategy_id == strategy.id,
        FundCohort.vintage_label == args.vintage,
        FundCohort.cohort_type == CohortType.SIGNAL,
    ).first()
    if existing_cohort:
        print(f"Cohort {args.vintage} already exists for strategy '{args.strategy}'.")
        sys.exit(1)

    cohort_size = int(strategy.target_cohort_size)
    criteria = strategy.selection_criteria

    # 1. Query eligible universe
    print(f"\nQuerying eligible universe for '{strategy.name}'...")
    eligible = query_eligible_universe(db, criteria)
    print(f"  Eligible companies: {len(eligible)}")

    if len(eligible) < cohort_size:
        print(f"  WARNING: Only {len(eligible)} eligible, need {cohort_size}")

    # 2. Rank
    print(f"  Ranking by {criteria.get('ranking', {}).get('primary_sort', 'freshness_adjusted_score')}...")
    ranked = rank_entities(db, eligible, criteria)

    # 3. Select top N for signal cohort
    signal_picks = ranked[:cohort_size]
    signal_ids = {e.id for e, _ in signal_picks}

    # 4. Select benchmark (random from remaining eligible, same size)
    remaining = [(e, s) for e, s in ranked if e.id not in signal_ids]
    seed = int(datetime.now().timestamp())
    rng = random.Random(seed)
    benchmark_size = min(cohort_size, len(remaining))
    benchmark_picks = rng.sample(remaining, benchmark_size) if remaining else []

    dry_run = args.dry_run
    label = "DRY RUN — " if dry_run else ""

    # Print signal cohort
    print(f"\n{'='*80}")
    print(f"{label}DEPLOYMENT: {strategy.name} — {args.vintage}")
    print(f"{'='*80}")
    print(f"\nSIGNAL COHORT ({len(signal_picks)} positions):\n")
    print(f"  {'#':>3} {'Company':<38} {'Adj':>7} {'Raw':>7} {'Policy':>7} {'Signals':>7}")
    print(f"  {'-'*3} {'-'*38} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")

    for i, (entity, scores) in enumerate(signal_picks, 1):
        sig_count = db.query(func.count(Signal.id)).filter(
            Signal.entity_id == entity.id,
            Signal.status == SignalStatus.ACTIVE,
        ).scalar() or 0
        print(f"  {i:>3} {entity.canonical_name[:38]:<38} "
              f"{scores['freshness_adjusted_score']:>7.2f} "
              f"{scores['composite_score']:>7.2f} "
              f"{scores['policy_tailwind_score']:>7.2f} "
              f"{sig_count:>7}")

    # Print benchmark cohort
    print(f"\nBENCHMARK COHORT ({len(benchmark_picks)} positions, random seed={seed}):\n")
    print(f"  {'#':>3} {'Company':<38} {'Adj':>7} {'Raw':>7} {'Policy':>7}")
    print(f"  {'-'*3} {'-'*38} {'-'*7} {'-'*7} {'-'*7}")

    for i, (entity, scores) in enumerate(benchmark_picks, 1):
        print(f"  {i:>3} {entity.canonical_name[:38]:<38} "
              f"{scores['freshness_adjusted_score']:>7.2f} "
              f"{scores['composite_score']:>7.2f} "
              f"{scores['policy_tailwind_score']:>7.2f}")

    if dry_run:
        print(f"\n  DRY RUN — no changes made. Remove --dry-run to deploy.")
        return

    # 5. Create signal cohort
    signal_cohort = FundCohort(
        strategy_id=strategy.id,
        cohort_type=CohortType.SIGNAL,
        vintage_label=args.vintage,
        deployed_at=date.today(),
        selection_metadata={
            "eligible_universe_size": len(eligible),
            "random_seed": seed,
        },
    )
    db.add(signal_cohort)
    db.flush()  # get ID

    # 6. Create benchmark cohort
    benchmark_cohort = FundCohort(
        strategy_id=strategy.id,
        cohort_type=CohortType.BENCHMARK,
        vintage_label=args.vintage,
        deployed_at=date.today(),
        paired_cohort_id=signal_cohort.id,
        selection_metadata={
            "eligible_universe_size": len(eligible),
            "random_seed": seed,
        },
    )
    db.add(benchmark_cohort)
    db.flush()

    # Link signal cohort back to benchmark
    signal_cohort.paired_cohort_id = benchmark_cohort.id

    # 7. Create positions for signal cohort
    for rank, (entity, scores) in enumerate(signal_picks, 1):
        state = _capture_entry_state(db, entity)
        signals_str = ", ".join(
            f"{s['signal_type']} ({s['confidence']:.1f})"
            for s in (state["entry_signals"] or [])[:3]
        )
        position = FundPosition(
            cohort_id=signal_cohort.id,
            entity_id=entity.id,
            selection_rank=rank,
            selection_reason=f"Rank #{rank} by {criteria.get('ranking', {}).get('primary_sort', 'score')}. Signals: {signals_str}",
            **state,
        )
        db.add(position)

    # 8. Create positions for benchmark cohort
    for rank, (entity, scores) in enumerate(benchmark_picks, 1):
        state = _capture_entry_state(db, entity)
        position = FundPosition(
            cohort_id=benchmark_cohort.id,
            entity_id=entity.id,
            selection_rank=rank,
            selection_reason=f"Random benchmark selection (seed={seed})",
            **state,
        )
        db.add(position)

    db.commit()
    print(f"\n  Deployed {len(signal_picks)} signal + {len(benchmark_picks)} benchmark positions.")
    print(f"  Signal cohort:    {signal_cohort.id}")
    print(f"  Benchmark cohort: {benchmark_cohort.id}")


# ── Track Subcommand ─────────────────────────────────────────────────────


def _milestone_exists(db: Session, source_key: str) -> bool:
    """Check if a milestone with this source key already exists."""
    return db.query(FundMilestone).filter(
        FundMilestone.source_key == source_key
    ).first() is not None


def _months_between(d1: date, d2: date) -> int:
    """Calculate months between two dates."""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def cmd_track(db: Session, args):
    """Run milestone detection across active positions."""
    since = date.fromisoformat(args.since) if args.since else date(2026, 1, 1)
    dry_run = args.dry_run

    # Get positions to track
    query = db.query(FundPosition).filter(
        FundPosition.status == PositionStatus.ACTIVE,
    )

    if args.strategy:
        strategy = _get_strategy(db, args.strategy)
        if not strategy:
            print(f"Strategy '{args.strategy}' not found.")
            sys.exit(1)
        cohort_ids = [c.id for c in db.query(FundCohort).filter(
            FundCohort.strategy_id == strategy.id,
        ).all()]
        query = query.filter(FundPosition.cohort_id.in_(cohort_ids))

    positions = query.all()

    if not positions:
        print("No active positions to track.")
        return

    label = "DRY RUN — " if dry_run else ""
    print(f"\n{label}MILESTONE TRACKING")
    print(f"  Active positions: {len(positions)}")
    print(f"  Looking since:    {since}")
    print()

    stats = defaultdict(int)
    new_milestones = []

    for pos in positions:
        entry_date = pos.entered_at.date() if isinstance(pos.entered_at, datetime) else pos.entered_at
        entity = db.query(Entity).filter(Entity.id == pos.entity_id).first()
        if not entity:
            continue

        # FUNDING_RAISE: new funding events after entry
        funding_events = db.query(FundingEvent).filter(
            FundingEvent.entity_id == pos.entity_id,
            FundingEvent.event_type.in_([
                FundingEventType.REG_D_FILING,
                FundingEventType.PRIVATE_ROUND,
            ]),
            FundingEvent.event_date >= since,
            FundingEvent.event_date >= entry_date,
        ).all()

        for fe in funding_events:
            sk = f"fund_milestone:{pos.id}:funding_raise:{fe.id}"
            if _milestone_exists(db, sk):
                stats["duplicates_skipped"] += 1
                continue
            m_date = fe.event_date or date.today()
            ms = FundMilestone(
                position_id=pos.id,
                entity_id=pos.entity_id,
                milestone_type=MilestoneType.FUNDING_RAISE,
                milestone_date=m_date,
                milestone_value=fe.amount,
                months_since_entry=_months_between(entry_date, m_date),
                details={
                    "round_stage": fe.round_stage,
                    "amount": float(fe.amount) if fe.amount else None,
                    "source": fe.source,
                },
                source_key=sk,
            )
            new_milestones.append(ms)
            stats["funding_raise"] += 1

        # NEW_CONTRACT: new contracts after entry
        contracts = db.query(Contract).filter(
            Contract.entity_id == pos.entity_id,
            Contract.award_date >= since,
            Contract.award_date >= entry_date,
        ).all()

        for c in contracts:
            sk = f"fund_milestone:{pos.id}:new_contract:{c.id}"
            if _milestone_exists(db, sk):
                stats["duplicates_skipped"] += 1
                continue
            m_date = c.award_date or date.today()
            ms = FundMilestone(
                position_id=pos.id,
                entity_id=pos.entity_id,
                milestone_type=MilestoneType.NEW_CONTRACT,
                milestone_date=m_date,
                milestone_value=c.contract_value,
                months_since_entry=_months_between(entry_date, m_date),
                details={
                    "contract_number": c.contract_number,
                    "contracting_agency": c.contracting_agency,
                    "value": float(c.contract_value) if c.contract_value else None,
                },
                source_key=sk,
            )
            new_milestones.append(ms)
            stats["new_contract"] += 1

        # SBIR_ADVANCE: Phase II or III after entry
        sbir_advances = db.query(FundingEvent).filter(
            FundingEvent.entity_id == pos.entity_id,
            FundingEvent.event_type.in_([
                FundingEventType.SBIR_PHASE_2,
                FundingEventType.SBIR_PHASE_3,
            ]),
            FundingEvent.event_date >= since,
            FundingEvent.event_date >= entry_date,
        ).all()

        for fe in sbir_advances:
            sk = f"fund_milestone:{pos.id}:sbir_advance:{fe.id}"
            if _milestone_exists(db, sk):
                stats["duplicates_skipped"] += 1
                continue
            m_date = fe.event_date or date.today()
            ms = FundMilestone(
                position_id=pos.id,
                entity_id=pos.entity_id,
                milestone_type=MilestoneType.SBIR_ADVANCE,
                milestone_date=m_date,
                milestone_value=fe.amount,
                months_since_entry=_months_between(entry_date, m_date),
                details={
                    "phase": fe.event_type.value,
                    "amount": float(fe.amount) if fe.amount else None,
                },
                source_key=sk,
            )
            new_milestones.append(ms)
            stats["sbir_advance"] += 1

        # COMPOSITE_SCORE_INCREASE: compare current vs entry
        current_scores = _get_score_for_entity(db, pos.entity_id)
        entry_adj = float(pos.entry_freshness_adjusted_score or 0)
        current_adj = current_scores["freshness_adjusted_score"]
        if current_adj > entry_adj and entry_adj > 0:
            sk = f"fund_milestone:{pos.id}:score_increase:{date.today().isoformat()}"
            if not _milestone_exists(db, sk):
                ms = FundMilestone(
                    position_id=pos.id,
                    entity_id=pos.entity_id,
                    milestone_type=MilestoneType.COMPOSITE_SCORE_INCREASE,
                    milestone_date=date.today(),
                    months_since_entry=_months_between(entry_date, date.today()),
                    details={
                        "entry_score": entry_adj,
                        "current_score": current_adj,
                        "delta": round(current_adj - entry_adj, 2),
                    },
                    source_key=sk,
                )
                new_milestones.append(ms)
                stats["score_increase"] += 1

        # LIFECYCLE_ADVANCE: compare current vs entry lifecycle
        current_lifecycle = _compute_lifecycle_stage(db, pos.entity_id)
        stage_order = ["Pre-revenue R&D", "Prototype", "Growth", "Production"]
        entry_idx = stage_order.index(pos.entry_lifecycle_stage) if pos.entry_lifecycle_stage in stage_order else 0
        current_idx = stage_order.index(current_lifecycle) if current_lifecycle in stage_order else 0
        if current_idx > entry_idx:
            sk = f"fund_milestone:{pos.id}:lifecycle_advance:{current_lifecycle}"
            if not _milestone_exists(db, sk):
                ms = FundMilestone(
                    position_id=pos.id,
                    entity_id=pos.entity_id,
                    milestone_type=MilestoneType.LIFECYCLE_ADVANCE,
                    milestone_date=date.today(),
                    months_since_entry=_months_between(entry_date, date.today()),
                    details={
                        "from_stage": pos.entry_lifecycle_stage,
                        "to_stage": current_lifecycle,
                    },
                    source_key=sk,
                )
                new_milestones.append(ms)
                stats["lifecycle_advance"] += 1

        # GONE_STALE: check for gone_stale signal fired after entry
        stale_signal = db.query(Signal).filter(
            Signal.entity_id == pos.entity_id,
            Signal.signal_type == "gone_stale",
            Signal.status == SignalStatus.ACTIVE,
            Signal.detected_date >= entry_date,
        ).first()
        if stale_signal:
            sk = f"fund_milestone:{pos.id}:gone_stale:{stale_signal.id}"
            if not _milestone_exists(db, sk):
                m_date = stale_signal.detected_date or date.today()
                ms = FundMilestone(
                    position_id=pos.id,
                    entity_id=pos.entity_id,
                    milestone_type=MilestoneType.GONE_STALE,
                    milestone_date=m_date,
                    months_since_entry=_months_between(entry_date, m_date),
                    details={"signal_id": stale_signal.id},
                    source_key=sk,
                )
                new_milestones.append(ms)
                stats["gone_stale"] += 1

        # NEW_AGENCY: contract from agency not present at entry
        entry_agencies = set()
        if pos.entry_signals:
            for sig in pos.entry_signals:
                ev = sig.get("evidence") or {}
                if isinstance(ev, dict) and "agency" in ev:
                    entry_agencies.add(ev["agency"])
        # Also get agencies from contracts at entry time
        entry_contracts = db.query(Contract.contracting_agency).filter(
            Contract.entity_id == pos.entity_id,
            Contract.award_date < entry_date,
        ).distinct().all()
        entry_agencies.update(a[0] for a in entry_contracts if a[0])

        new_agency_contracts = db.query(Contract).filter(
            Contract.entity_id == pos.entity_id,
            Contract.award_date >= since,
            Contract.award_date >= entry_date,
            Contract.contracting_agency.isnot(None),
        ).all()

        for c in new_agency_contracts:
            if c.contracting_agency and c.contracting_agency not in entry_agencies:
                sk = f"fund_milestone:{pos.id}:new_agency:{c.contracting_agency}"
                if not _milestone_exists(db, sk):
                    m_date = c.award_date or date.today()
                    ms = FundMilestone(
                        position_id=pos.id,
                        entity_id=pos.entity_id,
                        milestone_type=MilestoneType.NEW_AGENCY,
                        milestone_date=m_date,
                        months_since_entry=_months_between(entry_date, m_date),
                        details={
                            "agency": c.contracting_agency,
                            "contract_number": c.contract_number,
                        },
                        source_key=sk,
                    )
                    new_milestones.append(ms)
                    stats["new_agency"] += 1
                    entry_agencies.add(c.contracting_agency)  # Don't double-count

    # Print results
    print(f"  Milestones found: {len(new_milestones)}")
    if stats:
        for mtype, cnt in sorted(stats.items()):
            if mtype != "duplicates_skipped":
                print(f"    {mtype:<25} {cnt:>5}")
        if stats.get("duplicates_skipped"):
            print(f"    {'(duplicates skipped)':<25} {stats['duplicates_skipped']:>5}")

    if not dry_run and new_milestones:
        for ms in new_milestones:
            db.add(ms)
        db.commit()
        print(f"\n  Committed {len(new_milestones)} milestones to database.")
    elif dry_run and new_milestones:
        print(f"\n  DRY RUN — no changes made. Remove --dry-run to commit.")


# ── Performance Subcommand ───────────────────────────────────────────────


def _cohort_metrics(db: Session, cohort: FundCohort) -> dict:
    """Calculate metrics for a single cohort."""
    positions = db.query(FundPosition).filter(
        FundPosition.cohort_id == cohort.id,
    ).all()

    total = len(positions)
    active = sum(1 for p in positions if p.status == PositionStatus.ACTIVE)

    # Milestone hit rates by type
    hit_rates = {}
    values = {}
    for mt in MilestoneType:
        positions_with = set()
        total_value = Decimal("0")
        for p in positions:
            milestones = db.query(FundMilestone).filter(
                FundMilestone.position_id == p.id,
                FundMilestone.milestone_type == mt,
            ).all()
            if milestones:
                positions_with.add(p.id)
                for m in milestones:
                    if m.milestone_value:
                        total_value += m.milestone_value

        hit_rates[mt.value] = (len(positions_with) / total * 100) if total > 0 else 0.0
        values[mt.value] = float(total_value)

    # Average score change
    score_deltas = []
    for p in positions:
        entry = float(p.entry_freshness_adjusted_score or 0)
        current = _get_score_for_entity(db, p.entity_id)["freshness_adjusted_score"]
        if entry > 0:
            score_deltas.append(current - entry)

    avg_score_delta = sum(score_deltas) / len(score_deltas) if score_deltas else 0.0

    return {
        "total": total,
        "active": active,
        "hit_rates": hit_rates,
        "values": values,
        "avg_score_delta": avg_score_delta,
    }


def cmd_performance(db: Session, args):
    """Show performance metrics for strategies."""
    if args.all:
        strategies = db.query(FundStrategy).filter(
            FundStrategy.status.in_([StrategyStatus.ACTIVE, StrategyStatus.PAUSED]),
        ).all()
    elif args.strategy:
        strategy = _get_strategy(db, args.strategy)
        if not strategy:
            print(f"Strategy '{args.strategy}' not found.")
            sys.exit(1)
        strategies = [strategy]
    else:
        print("Specify --strategy NAME or --all")
        sys.exit(1)

    for strategy in strategies:
        # Get signal cohorts (and their paired benchmarks)
        signal_cohorts = db.query(FundCohort).filter(
            FundCohort.strategy_id == strategy.id,
            FundCohort.cohort_type == CohortType.SIGNAL,
        ).order_by(FundCohort.deployed_at).all()

        if args.vintage:
            signal_cohorts = [c for c in signal_cohorts if c.vintage_label == args.vintage]

        if not signal_cohorts:
            print(f"\nNo cohorts deployed for '{strategy.name}'.")
            continue

        total_signal = sum(
            db.query(func.count(FundPosition.id)).filter(
                FundPosition.cohort_id == c.id,
            ).scalar() or 0
            for c in signal_cohorts
        )
        total_benchmark = sum(
            db.query(func.count(FundPosition.id)).filter(
                FundPosition.cohort_id == c.paired_cohort_id,
            ).scalar() or 0
            for c in signal_cohorts if c.paired_cohort_id
        )

        print(f"\n{'='*70}")
        print(f"FUND PERFORMANCE: {strategy.name}")
        print(f"{'='*70}")
        print(f"\n  Strategy: {strategy.name} ({strategy.status.value})")
        print(f"  Deployed cohorts: {len(signal_cohorts)}")
        print(f"  Total positions: {total_signal + total_benchmark} "
              f"({total_signal} signal + {total_benchmark} benchmark)")

        for cohort in signal_cohorts:
            days_ago = (date.today() - cohort.deployed_at).days

            print(f"\n--- {cohort.vintage_label} Vintage "
                  f"(deployed {cohort.deployed_at}, {days_ago} days ago) ---")

            signal_metrics = _cohort_metrics(db, cohort)

            benchmark_cohort = db.query(FundCohort).filter(
                FundCohort.id == cohort.paired_cohort_id,
            ).first() if cohort.paired_cohort_id else None

            benchmark_metrics = _cohort_metrics(db, benchmark_cohort) if benchmark_cohort else None

            # Header
            if benchmark_metrics:
                print(f"\n  {'':28} {'SIGNAL':>9} {'BENCHMARK':>11} {'DELTA':>9}")
                print(f"  Positions:                 {signal_metrics['total']:>9} "
                      f"{benchmark_metrics['total']:>11}")
                print(f"  Active:                    {signal_metrics['active']:>9} "
                      f"{benchmark_metrics['active']:>11}")
            else:
                print(f"\n  {'':28} {'SIGNAL':>9}")
                print(f"  Positions:                 {signal_metrics['total']:>9}")
                print(f"  Active:                    {signal_metrics['active']:>9}")

            # Hit rates
            print(f"\n  MILESTONE HIT RATES:")
            notable_types = [
                "funding_raise", "new_contract", "sbir_advance",
                "composite_score_increase", "lifecycle_advance",
                "new_agency", "gone_stale",
            ]
            for mt in notable_types:
                sig_rate = signal_metrics["hit_rates"].get(mt, 0.0)
                if benchmark_metrics:
                    bench_rate = benchmark_metrics["hit_rates"].get(mt, 0.0)
                    delta = sig_rate - bench_rate
                    notable = " ***" if abs(delta) > 10 else ""
                    print(f"    {mt.replace('_', ' ').title():<24} {sig_rate:>6.1f}% "
                          f"{bench_rate:>9.1f}% {delta:>+8.1f}%{notable}")
                else:
                    print(f"    {mt.replace('_', ' ').title():<24} {sig_rate:>6.1f}%")

            # Values
            sig_funding = signal_metrics["values"].get("funding_raise", 0)
            sig_contracts = signal_metrics["values"].get("new_contract", 0)
            if sig_funding > 0 or sig_contracts > 0:
                print(f"\n  MILESTONE VALUES:")
                if benchmark_metrics:
                    bench_funding = benchmark_metrics["values"].get("funding_raise", 0)
                    bench_contracts = benchmark_metrics["values"].get("new_contract", 0)
                    print(f"    Funding raised:       ${sig_funding/1e6:>8.1f}M "
                          f"${bench_funding/1e6:>9.1f}M  {(sig_funding-bench_funding)/1e6:>+9.1f}M")
                    print(f"    Contracts won:        ${sig_contracts/1e6:>8.1f}M "
                          f"${bench_contracts/1e6:>9.1f}M  {(sig_contracts-bench_contracts)/1e6:>+9.1f}M")
                else:
                    print(f"    Funding raised:       ${sig_funding/1e6:>8.1f}M")
                    print(f"    Contracts won:        ${sig_contracts/1e6:>8.1f}M")

            # Score trajectory
            print(f"\n  Avg score change:          {signal_metrics['avg_score_delta']:>+.2f}", end="")
            if benchmark_metrics:
                print(f"       {benchmark_metrics['avg_score_delta']:>+.2f}"
                      f"     {signal_metrics['avg_score_delta'] - benchmark_metrics['avg_score_delta']:>+.2f}")
            else:
                print()

        if benchmark_metrics:
            print(f"\n  *** = statistically notable (>10% differential)")
        print(f"{'='*70}")


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Aperture Signals — Notional Fund Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Strategy subcommands
    strat_parser = subparsers.add_parser("strategy", help="Strategy management")
    strat_sub = strat_parser.add_subparsers(dest="strategy_action")

    create_p = strat_sub.add_parser("create", help="Create a new strategy")
    create_p.add_argument("--name", type=str, help="Strategy name")
    create_p.add_argument("--config", type=str, required=True, help="JSON config file path")

    list_p = strat_sub.add_parser("list", help="List all strategies")

    show_p = strat_sub.add_parser("show", help="Show strategy details")
    show_p.add_argument("--name", type=str, required=True, help="Strategy name")

    activate_p = strat_sub.add_parser("activate", help="Activate a strategy")
    activate_p.add_argument("--name", type=str, required=True, help="Strategy name")

    # Deploy subcommand
    deploy_p = subparsers.add_parser("deploy", help="Deploy a cohort")
    deploy_p.add_argument("--strategy", type=str, required=True, help="Strategy name")
    deploy_p.add_argument("--vintage", type=str, required=True, help="Vintage label (e.g. 2026-Q1)")
    deploy_p.add_argument("--dry-run", action="store_true", help="Preview without deploying")

    # Track subcommand
    track_p = subparsers.add_parser("track", help="Run milestone detection")
    track_p.add_argument("--since", type=str, help="Track milestones since date (YYYY-MM-DD)")
    track_p.add_argument("--strategy", type=str, help="Limit to strategy")
    track_p.add_argument("--dry-run", action="store_true", help="Preview without committing")

    # Performance subcommand
    perf_p = subparsers.add_parser("performance", help="Show performance metrics")
    perf_p.add_argument("--strategy", type=str, help="Strategy name")
    perf_p.add_argument("--vintage", type=str, help="Specific vintage")
    perf_p.add_argument("--all", action="store_true", help="All active strategies")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    db = SessionLocal()
    try:
        if args.command == "strategy":
            if args.strategy_action == "create":
                cmd_strategy_create(db, args)
            elif args.strategy_action == "list":
                cmd_strategy_list(db, args)
            elif args.strategy_action == "show":
                cmd_strategy_show(db, args)
            elif args.strategy_action == "activate":
                cmd_strategy_activate(db, args)
            else:
                strat_parser.print_help()
        elif args.command == "deploy":
            cmd_deploy(db, args)
        elif args.command == "track":
            cmd_track(db, args)
        elif args.command == "performance":
            cmd_performance(db, args)
        else:
            parser.print_help()
    finally:
        db.close()


if __name__ == "__main__":
    main()
