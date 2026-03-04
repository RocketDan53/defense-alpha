#!/usr/bin/env python3
"""Batch Enrichment Runner — enrich multiple entities with throttling and checkpoints.

Wraps enrich_entity.py to process batches with:
  - Throttling (default 10s between entities)
  - Checkpoint/resume on interruption
  - Error tracking with auto-abort on consecutive failures
  - Summary report

Usage:
    python scripts/batch_enrich.py --top 200
    python scripts/batch_enrich.py --file data/enrichment_priority.txt
    python scripts/batch_enrich.py --report sbir_lapse --top-per-sector 25
    python scripts/batch_enrich.py --resume
    python scripts/batch_enrich.py --top 50 --dry-run
    python scripts/batch_enrich.py --top 50 --delay 5
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

DB_PATH = PROJECT_DIR / "data" / "defense_alpha.db"
CHECKPOINT_FILE = PROJECT_DIR / "data" / "enrichment_checkpoint.json"

DELAY_BETWEEN_ENTITIES = 10  # seconds
MAX_CONCURRENT = 1  # Sequential only
MAX_ERRORS_BEFORE_ABORT = 5  # Consecutive failures
COST_PER_ENTITY = 0.75  # Estimated USD

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _load_checkpoint() -> dict | None:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return None


def _save_checkpoint(data: dict):
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2))


def _clear_checkpoint():
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


def get_entities_from_queue(top: int, report_filter: str | None = None) -> list[str]:
    """Get entity names from the priority queue."""
    from enrichment_queue import build_priority_queue, _connect as eq_connect

    conn = eq_connect()
    try:
        queue = build_priority_queue(conn, report_filter=report_filter)
        return [e["canonical_name"] for e in queue[:top]]
    finally:
        conn.close()


def get_entities_from_file(filepath: str) -> list[str]:
    """Read entity names from a file (one per line)."""
    lines = Path(filepath).read_text().strip().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def get_entities_for_report(report_type: str, top_per_sector: int) -> list[str]:
    """Get top N entities per sector for a specific report type."""
    if report_type != "sbir_lapse":
        logger.error("Unknown report type: %s", report_type)
        return []

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT e.canonical_name, e.core_business,
                      COALESCE(SUM(fe.amount), 0) as sbir_total
               FROM entities e
               JOIN signals s ON e.id = s.entity_id
               LEFT JOIN funding_events fe ON e.id = fe.entity_id
                    AND fe.event_type LIKE 'SBIR_%'
               WHERE s.signal_type = 'sbir_lapse_risk' AND s.status = 'ACTIVE'
                 AND e.merged_into_id IS NULL
               GROUP BY e.id, e.canonical_name, e.core_business
               ORDER BY e.core_business, sbir_total DESC""",
        ).fetchall()

        # Group by sector, take top N per sector
        sector_counts = {}
        entities = []
        for row in rows:
            sector = row["core_business"] or "OTHER"
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if sector_counts[sector] <= top_per_sector:
                entities.append(row["canonical_name"])

        return entities
    finally:
        conn.close()


def run_batch(
    entity_names: list[str],
    delay: int = DELAY_BETWEEN_ENTITIES,
    dry_run: bool = False,
    resume_from: int = 0,
    batch_id: str | None = None,
) -> dict:
    """
    Run enrichment on a list of entities.

    Returns summary dict with counts and per-entity results.
    """
    from enrich_entity import enrich_single_entity

    if not batch_id:
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    total = len(entity_names)
    est_cost = total * COST_PER_ENTITY
    est_time_min = (total * delay) / 60

    print(f"\nBATCH ENRICHMENT — {batch_id}")
    print(f"  Entities:       {total}")
    print(f"  Delay:          {delay}s between entities")
    print(f"  Est. cost:      ~${est_cost:.0f}")
    print(f"  Est. time:      ~{est_time_min:.0f} min")

    if resume_from > 0:
        print(f"  Resuming from:  entity #{resume_from + 1}")

    if dry_run:
        print(f"\n  DRY RUN — entities that would be enriched:\n")
        for i, name in enumerate(entity_names, 1):
            print(f"    {i:>3}. {name}")
        print(f"\n  Use without --dry-run to execute.")
        return {"batch_id": batch_id, "total": total, "dry_run": True}

    print()

    results = []
    consecutive_errors = 0
    start_time = time.time()

    for i in range(resume_from, total):
        name = entity_names[i]
        print(f"  [{i+1}/{total}] {name} ...", end=" ", flush=True)

        try:
            result = enrich_single_entity(name, auto_approve=True)
            results.append(result)

            status = result["status"]
            findings = result["findings"]
            approved = result["approved"]

            if status == "success":
                print(f"OK — {findings} findings, {approved} approved")
                consecutive_errors = 0
            elif status == "not_found":
                print("SKIP (not found)")
                consecutive_errors = 0
            elif status == "no_findings":
                print("OK — no new findings")
                consecutive_errors = 0
            elif status == "error":
                print(f"ERROR — {result['errors'][0] if result['errors'] else '?'}")
                consecutive_errors += 1
            else:
                print(f"{status}")
                consecutive_errors = 0

        except KeyboardInterrupt:
            print("\n\n  Interrupted! Saving checkpoint...")
            _save_checkpoint({
                "batch_id": batch_id,
                "total": total,
                "completed": i,
                "last_entity": name,
                "entity_names": entity_names,
                "results": results,
            })
            print(f"  Checkpoint saved. Resume with: python scripts/batch_enrich.py --resume")
            break

        except Exception as e:
            print(f"CRASH — {e}")
            results.append({
                "entity": name, "status": "error",
                "findings": 0, "approved": 0,
                "errors": [str(e)],
            })
            consecutive_errors += 1

        # Check consecutive error limit
        if consecutive_errors >= MAX_ERRORS_BEFORE_ABORT:
            print(f"\n  ABORT: {MAX_ERRORS_BEFORE_ABORT} consecutive errors. "
                  f"Likely rate limited. Saving checkpoint...")
            _save_checkpoint({
                "batch_id": batch_id,
                "total": total,
                "completed": i + 1,
                "last_entity": name,
                "entity_names": entity_names,
                "results": results,
            })
            print(f"  Resume later with: python scripts/batch_enrich.py --resume")
            break

        # Save periodic checkpoint every 10 entities
        if (i + 1) % 10 == 0:
            _save_checkpoint({
                "batch_id": batch_id,
                "total": total,
                "completed": i + 1,
                "last_entity": name,
                "entity_names": entity_names,
                "results": results,
            })

        # Throttle (skip delay after last entity)
        if i < total - 1:
            time.sleep(delay)
    else:
        # Completed all entities — clear checkpoint
        _clear_checkpoint()

    elapsed = time.time() - start_time

    # Print summary
    summary = _build_summary(results, elapsed, batch_id)
    _print_summary(summary)

    return summary


def _build_summary(results: list[dict], elapsed: float, batch_id: str) -> dict:
    """Build summary dict from results."""
    successful = [r for r in results if r["status"] == "success"]
    errors = [r for r in results if r["status"] == "error"]
    no_findings = [r for r in results if r["status"] == "no_findings"]
    not_found = [r for r in results if r["status"] == "not_found"]

    total_findings = sum(r.get("findings", 0) for r in results)
    total_approved = sum(r.get("approved", 0) for r in results)
    total_rejected = sum(r.get("rejected", 0) for r in results)

    # Aggregate by finding type
    type_counts = {}
    for r in results:
        for ftype, count in r.get("by_type", {}).items():
            type_counts[ftype] = type_counts.get(ftype, 0) + count

    # Top entities by findings
    top_entities = sorted(
        [r for r in results if r.get("findings", 0) > 0],
        key=lambda x: x["findings"],
        reverse=True,
    )[:10]

    return {
        "batch_id": batch_id,
        "processed": len(results),
        "successful": len(successful),
        "no_findings": len(no_findings),
        "not_found": len(not_found),
        "errors": len(errors),
        "findings": total_findings,
        "approved": total_approved,
        "rejected": total_rejected,
        "by_type": type_counts,
        "top_entities": top_entities,
        "elapsed_seconds": elapsed,
        "est_cost": len(successful) * COST_PER_ENTITY,
    }


def _print_summary(summary: dict):
    """Print batch enrichment summary."""
    elapsed = summary.get("elapsed_seconds", 0)
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print(f"\n{'='*60}")
    print(f"BATCH ENRICHMENT COMPLETE")
    print(f"{'='*60}")
    print(f"  Entities processed:  {summary['processed']}")
    print(f"  Successful:          {summary['successful']}")
    print(f"  No new findings:     {summary['no_findings']}")
    print(f"  Not found:           {summary['not_found']}")
    print(f"  Errors:              {summary['errors']}")
    print(f"  Findings discovered: {summary['findings']}")
    print(f"  Findings approved:   {summary['approved']} (auto)")
    print(f"  Findings rejected:   {summary['rejected']} (low confidence)")
    print(f"  API cost (est):      ~${summary['est_cost']:.0f}")
    print(f"  Time elapsed:        {minutes}m {seconds}s")

    if summary.get("by_type"):
        print(f"\n  Top findings by type:")
        for ftype, count in sorted(summary["by_type"].items(), key=lambda x: -x[1]):
            print(f"    {ftype:<20} {count:>5}")

    if summary.get("top_entities"):
        print(f"\n  Entities with most new data:")
        for r in summary["top_entities"][:5]:
            by_type = r.get("by_type", {})
            type_detail = ", ".join(f"{c} {t}" for t, c in by_type.items())
            print(f"    {r['entity'][:40]:<40} {r['findings']} findings ({type_detail})")


def enrich_for_report(report_type: str, top_per_sector: int = 25) -> dict:
    """
    Entry point for report generators.
    Enriches top companies per sector for a specific report.
    Returns summary dict.
    """
    entities = get_entities_for_report(report_type, top_per_sector)
    if not entities:
        return {"processed": 0, "findings": 0}
    return run_batch(entities, delay=DELAY_BETWEEN_ENTITIES)


def main():
    parser = argparse.ArgumentParser(
        description="Batch Enrichment Runner — enrich multiple entities",
    )
    parser.add_argument("--top", type=int,
                        help="Enrich top N from priority queue")
    parser.add_argument("--file", type=str,
                        help="File with entity names (one per line)")
    parser.add_argument("--report", type=str, choices=["sbir_lapse"],
                        help="Enrich for a specific report type")
    parser.add_argument("--top-per-sector", type=int, default=25,
                        help="Top N per sector for --report mode (default: 25)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume interrupted batch from checkpoint")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be enriched without calling API")
    parser.add_argument("--delay", type=int, default=DELAY_BETWEEN_ENTITIES,
                        help=f"Seconds between entities (default: {DELAY_BETWEEN_ENTITIES})")

    args = parser.parse_args()

    if args.resume:
        checkpoint = _load_checkpoint()
        if not checkpoint:
            print("No checkpoint found. Start a new batch instead.")
            sys.exit(1)
        print(f"Resuming batch {checkpoint['batch_id']} "
              f"({checkpoint['completed']}/{checkpoint['total']} completed)")
        run_batch(
            checkpoint["entity_names"],
            delay=args.delay,
            resume_from=checkpoint["completed"],
            batch_id=checkpoint["batch_id"],
        )
        return

    if args.report:
        entities = get_entities_for_report(args.report, args.top_per_sector)
    elif args.file:
        entities = get_entities_from_file(args.file)
    elif args.top:
        entities = get_entities_from_queue(args.top, report_filter=None)
    else:
        parser.print_help()
        sys.exit(1)

    if not entities:
        print("No entities to enrich.")
        sys.exit(0)

    run_batch(entities, delay=args.delay, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
