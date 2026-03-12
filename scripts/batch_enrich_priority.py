#!/usr/bin/env python3
"""
Batch enrichment for priority entities.

Reads priority_entities.txt, enriches each via two-phase Claude + web search,
auto-approves HIGH confidence findings, stages MEDIUM/LOW for manual review.

Features:
  - Checkpoint/resume: interrupted runs pick up where they left off
  - 10-second delay between entities to respect API rate limits
  - Skips entities enriched in the last 30 days
  - Detailed per-entity logging with confidence breakdowns
  - Summary report at end

Usage:
    python scripts/batch_enrich_priority.py --dry-run              # Preview what would run
    python scripts/batch_enrich_priority.py                        # Run with auto-approve high
    python scripts/batch_enrich_priority.py --no-auto-approve      # Stage everything for manual review
    python scripts/batch_enrich_priority.py --file custom_list.txt # Use custom entity file
    python scripts/batch_enrich_priority.py --delay 15             # Custom delay between entities
    python scripts/batch_enrich_priority.py --reset                # Clear checkpoint and start fresh
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.enrich_entity import (
    _connect,
    gather_existing_data,
    ingest_finding,
    lookup_entity,
    search_and_extract,
    stage_findings,
)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_ENTITY_FILE = PROJECT_ROOT / "priority_entities.txt"
CHECKPOINT_FILE = PROJECT_ROOT / "data" / "batch_enrich_checkpoint.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Checkpoint management ────────────────────────────────────────────────

def load_checkpoint() -> dict:
    """Load checkpoint file. Returns {completed: [names], started_at: iso}."""
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"completed": [], "started_at": None}


def save_checkpoint(checkpoint: dict):
    """Persist checkpoint to disk."""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint, indent=2))


def clear_checkpoint():
    """Remove checkpoint file."""
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint cleared.")


# ── Recency check ────────────────────────────────────────────────────────

def was_recently_enriched(conn, entity_id: str, days: int = 30) -> bool:
    """True if entity has enrichment_findings created within `days`."""
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    row = conn.execute(
        "SELECT MAX(created_at) as last_enriched FROM enrichment_findings WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()
    if row and row["last_enriched"]:
        return row["last_enriched"] >= cutoff
    return False


# ── Auto-approve high confidence ─────────────────────────────────────────

def auto_approve_high(conn, staged_ids: list[str]) -> dict:
    """Auto-approve HIGH confidence findings, return counts."""
    counts = {"approved": 0, "staged_for_review": 0}
    for finding_id in staged_ids:
        f = conn.execute(
            "SELECT * FROM enrichment_findings WHERE id = ?",
            (finding_id,),
        ).fetchone()
        if f and f["confidence"] == "high":
            record_id = ingest_finding(conn, f)
            conn.execute(
                """UPDATE enrichment_findings
                   SET status='ingested', reviewed_at=datetime('now'),
                       reviewed_by='auto', ingested_record_id=?
                   WHERE id=?""",
                (record_id, finding_id),
            )
            counts["approved"] += 1
        else:
            counts["staged_for_review"] += 1
    conn.commit()
    return counts


# ── Per-entity enrichment ────────────────────────────────────────────────

def enrich_one(conn, entity_name: str, do_auto_approve: bool = True) -> dict:
    """
    Enrich a single entity. Returns result dict with:
      entity, status, findings, high, medium, low, approved, staged, errors, by_type
    """
    result = {
        "entity": entity_name,
        "status": "not_found",
        "findings": 0,
        "high": 0, "medium": 0, "low": 0,
        "approved": 0, "staged": 0,
        "errors": [],
        "by_type": {},
    }

    entity = lookup_entity(conn, entity_name)
    if not entity:
        logger.warning("  Entity '%s' not found in database.", entity_name)
        return result

    canonical = entity["canonical_name"]
    entity_id = entity["id"]
    result["entity"] = canonical

    # Recency check
    if was_recently_enriched(conn, entity_id):
        result["status"] = "skipped_recent"
        logger.info("  Skipped (enriched within 30 days)")
        return result

    existing = gather_existing_data(conn, entity_id)
    logger.info("  DB state: %d SBIRs, %d contracts (%s), %d Reg D (%s)",
                existing["sbir_count"], existing["contract_count"],
                existing["contract_total"], existing["regd_count"],
                existing["regd_total"])

    try:
        findings = search_and_extract(canonical, existing)
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))
        logger.error("  Search failed: %s", e)
        return result

    if not findings:
        result["status"] = "no_findings"
        logger.info("  No new findings from web search.")
        return result

    # Count by type and confidence
    for category in ["contracts", "funding_rounds", "ota_awards", "partnerships"]:
        items = findings.get(category, [])
        if items:
            result["by_type"][category] = len(items)
            for item in items:
                conf = item.get("confidence", "low")
                result[conf] = result.get(conf, 0) + 1

    staged_ids = stage_findings(conn, entity_id, findings)
    result["findings"] = len(staged_ids)

    if do_auto_approve and staged_ids:
        counts = auto_approve_high(conn, staged_ids)
        result["approved"] = counts["approved"]
        result["staged"] = counts["staged_for_review"]
    else:
        result["staged"] = len(staged_ids)

    result["status"] = "success"
    return result


# ── Dry run ──────────────────────────────────────────────────────────────

def dry_run(conn, entity_names: list[str]):
    """Show what would be processed without making API calls."""
    checkpoint = load_checkpoint()
    completed = set(checkpoint["completed"])

    print(f"\n{'='*70}")
    print(f"  BATCH ENRICHMENT DRY RUN")
    print(f"  {len(entity_names)} entities in file")
    print(f"  {len(completed)} already completed (checkpoint)")
    print(f"{'='*70}\n")

    will_process = []
    will_skip_checkpoint = []
    will_skip_recent = []
    will_skip_not_found = []

    for name in entity_names:
        if name in completed:
            will_skip_checkpoint.append(name)
            continue

        entity = lookup_entity(conn, name)
        if not entity:
            will_skip_not_found.append(name)
            continue

        if was_recently_enriched(conn, entity["id"]):
            will_skip_recent.append(name)
            continue

        # Get existing data summary for display
        existing = gather_existing_data(conn, entity["id"])
        will_process.append((name, existing))

    print(f"  WILL PROCESS: {len(will_process)} entities")
    for i, (name, ex) in enumerate(will_process, 1):
        print(f"    {i:2d}. {name:<45s}  SBIRs={ex['sbir_count']:>3d}  contracts={ex['contract_count']:>3d} ({ex['contract_total']})  RegD={ex['regd_count']:>2d} ({ex['regd_total']})")

    if will_skip_checkpoint:
        print(f"\n  SKIP (checkpoint): {len(will_skip_checkpoint)}")
        for n in will_skip_checkpoint:
            print(f"    - {n}")

    if will_skip_recent:
        print(f"\n  SKIP (enriched <30 days): {len(will_skip_recent)}")
        for n in will_skip_recent:
            print(f"    - {n}")

    if will_skip_not_found:
        print(f"\n  SKIP (not found in DB): {len(will_skip_not_found)}")
        for n in will_skip_not_found:
            print(f"    - {n}")

    est_minutes = len(will_process) * 0.75  # ~45s per entity (search + structure + delay)
    print(f"\n  Estimated time: ~{est_minutes:.0f} minutes ({len(will_process)} entities x ~45s each)")
    print(f"  Estimated API cost: ~${len(will_process) * 0.08:.2f} ({len(will_process)} x ~$0.08/entity)")
    print()


# ── Main batch loop ──────────────────────────────────────────────────────

def run_batch(
    entity_names: list[str],
    do_auto_approve: bool = True,
    delay: int = 10,
):
    """Process all entities with checkpoint/resume and rate limiting."""
    conn = _connect()
    checkpoint = load_checkpoint()

    if not checkpoint["started_at"]:
        checkpoint["started_at"] = datetime.now(tz=timezone.utc).isoformat()

    completed = set(checkpoint["completed"])
    results = []
    total = len(entity_names)
    start_time = time.time()

    print(f"\n{'='*70}")
    print(f"  BATCH ENRICHMENT")
    print(f"  {total} entities | auto-approve={'ON' if do_auto_approve else 'OFF'} | delay={delay}s")
    if completed:
        print(f"  Resuming: {len(completed)} already completed")
    print(f"{'='*70}\n")

    processed = 0
    for i, name in enumerate(entity_names, 1):
        if name in completed:
            logger.info("[%d/%d] %s — skipped (checkpoint)", i, total, name)
            continue

        logger.info("[%d/%d] %s", i, total, name)
        result = enrich_one(conn, name, do_auto_approve=do_auto_approve)
        results.append(result)

        # Log result
        if result["status"] == "success":
            logger.info("  => %d findings: %d approved, %d staged for review",
                        result["findings"], result["approved"], result["staged"])
            if result["by_type"]:
                logger.info("  => Types: %s", result["by_type"])
        elif result["status"] == "error":
            logger.error("  => Error: %s", result["errors"])

        # Update checkpoint
        checkpoint["completed"].append(name)
        save_checkpoint(checkpoint)
        processed += 1

        # Rate limit delay (skip after last entity)
        remaining = sum(1 for n in entity_names[i:] if n not in completed)
        if remaining > 0 and result["status"] not in ("skipped_recent", "not_found"):
            logger.info("  Waiting %ds before next entity...", delay)
            time.sleep(delay)

    conn.close()
    elapsed = time.time() - start_time

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  BATCH ENRICHMENT COMPLETE")
    print(f"{'='*70}")

    statuses = {}
    total_findings = 0
    total_approved = 0
    total_staged = 0
    total_errors = 0
    type_totals = {}

    for r in results:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        total_findings += r["findings"]
        total_approved += r["approved"]
        total_staged += r["staged"]
        if r["errors"]:
            total_errors += len(r["errors"])
        for t, c in r.get("by_type", {}).items():
            type_totals[t] = type_totals.get(t, 0) + c

    print(f"\n  Entities processed:   {processed}")
    print(f"  Time elapsed:         {elapsed/60:.1f} minutes")
    print(f"  Status breakdown:     {statuses}")
    print(f"\n  Total findings:       {total_findings}")
    print(f"  Auto-approved (HIGH): {total_approved}")
    print(f"  Staged for review:    {total_staged}")
    print(f"  Errors:               {total_errors}")

    if type_totals:
        print(f"\n  Findings by type:")
        for t, c in sorted(type_totals.items(), key=lambda x: -x[1]):
            print(f"    {t:<20s} {c}")

    if total_staged > 0:
        print(f"\n  Run 'python scripts/enrich_entity.py --review' to review {total_staged} staged findings.")

    print()
    return results


# ── CLI ──────────────────────────────────────────────────────────────────

def load_entity_names(filepath: str) -> list[str]:
    """Read entity names from file, skip comments and blanks."""
    names = []
    for line in Path(filepath).read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


def main():
    parser = argparse.ArgumentParser(
        description="Batch enrichment for priority entities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--file", type=str, default=str(DEFAULT_ENTITY_FILE),
                        help="Entity list file (default: priority_entities.txt)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without making API calls")
    parser.add_argument("--no-auto-approve", action="store_true",
                        help="Stage all findings for manual review (don't auto-approve HIGH)")
    parser.add_argument("--delay", type=int, default=10,
                        help="Seconds between entities (default: 10)")
    parser.add_argument("--reset", action="store_true",
                        help="Clear checkpoint and start fresh")

    args = parser.parse_args()

    if args.reset:
        clear_checkpoint()
        if not args.dry_run:
            print("Checkpoint cleared. Run again without --reset to start.")
            return

    entity_names = load_entity_names(args.file)
    if not entity_names:
        print(f"No entities found in {args.file}")
        sys.exit(1)

    if args.dry_run:
        conn = _connect()
        dry_run(conn, entity_names)
        conn.close()
    else:
        run_batch(
            entity_names,
            do_auto_approve=not args.no_auto_approve,
            delay=args.delay,
        )


if __name__ == "__main__":
    main()
