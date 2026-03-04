#!/usr/bin/env python3
"""Redeploy all fund strategies with matched-pair benchmark methodology.

Drops existing 2026-Q1 cohorts and redeploys using the updated fund_manager.py
with matched-pair benchmark selection and bootstrap baselines.

Usage:
    # Preview what will happen (safe)
    python Fund/redeploy_fund.py --dry-run

    # Execute full redeployment
    python Fund/redeploy_fund.py

    # Redeploy a single strategy
    python Fund/redeploy_fund.py --strategy "Policy Tailwind"
"""

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import func
from processing.database import SessionLocal
from processing.models import (
    FundStrategy, FundCohort, FundPosition, FundMilestone,
    CohortType, StrategyStatus,
)

VINTAGE = "2026-Q1"

STRATEGIES = [
    "Next Wave",
    "Policy Tailwind",
    "Signal Momentum",
]


def drop_vintage(db, strategy_name: str, vintage: str, dry_run: bool):
    """Drop all cohorts and positions for a strategy+vintage."""
    strategy = db.query(FundStrategy).filter(
        FundStrategy.name == strategy_name
    ).first()

    if not strategy:
        print(f"  Strategy '{strategy_name}' not found — skipping.")
        return 0

    cohorts = db.query(FundCohort).filter(
        FundCohort.strategy_id == strategy.id,
        FundCohort.vintage_label == vintage,
    ).all()

    if not cohorts:
        print(f"  No {vintage} cohorts for '{strategy_name}'.")
        return 0

    total_positions = 0
    total_milestones = 0
    for cohort in cohorts:
        milestones = db.query(func.count(FundMilestone.id)).join(
            FundPosition, FundMilestone.position_id == FundPosition.id
        ).filter(FundPosition.cohort_id == cohort.id).scalar() or 0

        positions = db.query(func.count(FundPosition.id)).filter(
            FundPosition.cohort_id == cohort.id
        ).scalar() or 0

        total_milestones += milestones
        total_positions += positions

        print(f"  Cohort {cohort.id[:8]}... ({cohort.cohort_type.value}): "
              f"{positions} positions, {milestones} milestones")

    if not dry_run:
        for cohort in cohorts:
            # Delete milestones for positions in this cohort
            position_ids = [p.id for p in db.query(FundPosition.id).filter(
                FundPosition.cohort_id == cohort.id
            ).all()]
            if position_ids:
                db.query(FundMilestone).filter(
                    FundMilestone.position_id.in_(position_ids)
                ).delete(synchronize_session=False)

            # Delete positions
            db.query(FundPosition).filter(
                FundPosition.cohort_id == cohort.id
            ).delete(synchronize_session=False)

        # Delete cohorts
        cohort_ids = [c.id for c in cohorts]
        # Clear paired references first
        db.query(FundCohort).filter(
            FundCohort.id.in_(cohort_ids)
        ).update({FundCohort.paired_cohort_id: None}, synchronize_session=False)
        db.query(FundCohort).filter(
            FundCohort.id.in_(cohort_ids)
        ).delete(synchronize_session=False)

        db.commit()

    print(f"  {'Would drop' if dry_run else 'Dropped'}: "
          f"{len(cohorts)} cohorts, {total_positions} positions, {total_milestones} milestones")
    return total_positions


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Redeploy fund with matched-pair benchmarks")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--strategy", type=str, help="Single strategy to redeploy")
    parser.add_argument("--vintage", type=str, default=VINTAGE, help="Vintage label")
    args = parser.parse_args()

    strategies = [args.strategy] if args.strategy else STRATEGIES
    dry_run = args.dry_run

    print("=" * 70)
    print(f"FUND REDEPLOYMENT — {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Vintage: {args.vintage}")
    print(f"Strategies: {', '.join(strategies)}")
    print(f"Methodology: matched-pair benchmarks + bootstrap baselines")
    print("=" * 70)

    db = SessionLocal()
    try:
        # Phase 1: Drop existing cohorts
        print(f"\n--- Phase 1: Drop existing {args.vintage} cohorts ---\n")
        for name in strategies:
            drop_vintage(db, name, args.vintage, dry_run)

        if dry_run:
            print(f"\n--- DRY RUN complete. To execute: ---")
            print(f"\n  python Fund/redeploy_fund.py\n")
            print(f"--- Then redeploy each strategy: ---\n")
            for name in strategies:
                safe_name = name
                print(f"  python Fund/fund_manager.py deploy "
                      f"--strategy \"{safe_name}\" --vintage \"{args.vintage}\"")
            return

        # Phase 2: Redeploy via fund_manager
        print(f"\n--- Phase 2: Redeploy with matched-pair benchmarks ---\n")
        print("Run the following commands:\n")
        for name in strategies:
            print(f"  python Fund/fund_manager.py deploy "
                  f"--strategy \"{name}\" --vintage \"{args.vintage}\"")
        print(f"\nThen verify:")
        print(f"  python Fund/fund_manager.py performance --all\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()
