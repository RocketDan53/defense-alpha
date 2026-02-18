#!/usr/bin/env python3
"""
Aperture Signals Pipeline Orchestrator

Single-command runner for the full processing chain.

Modes:
    --full-refresh    Scrape new data + process everything
    --process-only    Skip scrapers, reprocess existing data

Usage:
    python scripts/run_pipeline.py --full-refresh
    python scripts/run_pipeline.py --process-only
    python scripts/run_pipeline.py --full-refresh --dry-run
    python scripts/run_pipeline.py --process-only --no-prompt
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "pipeline_runs"

# ANSI colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def fmt_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"


def build_steps(mode: str, concurrency: int) -> list[dict]:
    """
    Build the ordered list of pipeline steps.

    Each step is a dict with:
        name:        Short identifier
        description: What this step does
        command:     Shell command to run
        mode:        'full' = full-refresh only, 'both' = always
    """
    today = datetime.now().strftime("%Y-%m-%d")
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    ninety_days_ago = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    current_year = datetime.now().year

    steps = [
        # --- FULL-REFRESH ONLY: scrapers (sequential, SQLite can't handle concurrent writes) ---
        {
            "name": "usaspending_scraper",
            "description": "Scrape USASpending contracts (last 30 days)",
            "command": f"python -m scrapers.usaspending --start-date {thirty_days_ago} --end-date {today}",
            "mode": "full",
        },
        {
            "name": "sbir_scraper",
            "description": "Scrape SBIR/STTR awards",
            "command": f"python -m scrapers.sbir --start-year {current_year}",
            "mode": "full",
        },
        {
            "name": "sec_edgar_scraper",
            "description": "Scrape SEC EDGAR filings (last 90 days)",
            "command": f"python scrapers/sec_edgar.py --start-date {ninety_days_ago} --end-date {today}",
            "mode": "full",
        },
        # --- BOTH MODES: processing pipeline ---
        {
            "name": "entity_resolution",
            "description": "Deduplicate and merge entities",
            "command": "python scripts/run_entity_resolution.py",
            "mode": "both",
        },
        {
            "name": "reclassification_check",
            "description": "Flag startups with >$50M contracts for PRIME review",
            "command": (
                'python -c "'
                "import sys; sys.path.insert(0, '.'); "
                "from processing.database import SessionLocal; "
                "from processing.models import Entity, EntityType; "
                "from sqlalchemy import func; "
                "from processing.models import Contract; "
                "db = SessionLocal(); "
                "results = db.query(Entity.canonical_name, func.sum(Contract.contract_value), func.count(Contract.id))"
                ".join(Contract, Contract.entity_id == Entity.id)"
                ".filter(Entity.entity_type == EntityType.STARTUP, Entity.merged_into_id.is_(None))"
                ".group_by(Entity.id)"
                ".having(func.sum(Contract.contract_value) > 50_000_000)"
                ".order_by(func.sum(Contract.contract_value).desc())"
                ".all(); "
                "print(f'Entities flagged for PRIME review: {len(results)}'); "
                "[print(f'  {name:<45} ${val:>15,.0f}  ({cnt} contracts)') for name, val, cnt in results[:25]]; "
                "print(f'  ... and {len(results)-25} more') if len(results) > 25 else None; "
                "print('ACTION REQUIRED: Review these entities and reclassify manually.') if results else print('No reclassification candidates found.'); "
                "db.close()"
                '"'
            ),
            "mode": "both",
        },
        {
            "name": "business_classifier",
            "description": f"Classify unclassified SBIR entities (async, concurrency {concurrency})",
            "command": f"python -m processing.business_classifier --all --skip-classified --async --concurrency {concurrency}",
            "mode": "both",
        },
        {
            "name": "policy_alignment",
            "description": f"Score unscored entities for policy alignment (async, concurrency {concurrency})",
            "command": f"python -m processing.policy_alignment --all --skip-scored --async --concurrency {concurrency}",
            "mode": "both",
        },
        {
            "name": "embedding_generation",
            "description": "Generate embeddings for new SBIR award titles",
            "command": "python scripts/find_similar.py --embed",
            "mode": "both",
        },
        {
            "name": "signal_detection",
            "description": "Run all signal detection algorithms",
            "command": "python scripts/detect_signals.py",
            "mode": "both",
        },
        {
            "name": "outcome_tracking",
            "description": "Track outcomes (last 30 days)",
            "command": f"python scripts/track_outcomes.py --since {thirty_days_ago}",
            "mode": "both",
        },
    ]

    return steps


def print_header(text: str, log_file=None):
    """Print a formatted header."""
    line = "=" * 70
    msg = f"\n{line}\n  {text}\n{line}"
    print(f"{BOLD}{CYAN}{msg}{RESET}")
    if log_file:
        log_file.write(msg + "\n")


def print_step_header(index: int, total: int, step: dict, log_file=None):
    """Print step start header."""
    msg = f"\n[{index}/{total}] {step['name']}: {step['description']}"
    print(f"{BOLD}{msg}{RESET}")
    print(f"  Command: {step['command']}")
    if log_file:
        log_file.write(f"\n{'─' * 70}\n")
        log_file.write(msg + "\n")
        log_file.write(f"  Command: {step['command']}\n")


def run_pipeline(args):
    """Execute the pipeline."""
    mode = "full" if args.full_refresh else "process"
    steps = build_steps(mode, args.concurrency)

    # Filter steps by mode
    if mode == "process":
        steps = [s for s in steps if s["mode"] == "both"]

    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Create log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"{timestamp}.log"

    # Track results for summary
    results = []
    pipeline_start = time.time()

    print_header(
        f"APERTURE SIGNALS PIPELINE — {mode.upper().replace('_', ' ')} MODE"
        + (" (DRY RUN)" if args.dry_run else "")
    )
    print(f"  Started:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Steps:    {len(steps)}")
    print(f"  Log file: {log_path}")
    if not args.dry_run:
        print(f"  Prompt:   {'disabled (auto-continue on failure)' if args.no_prompt else 'enabled'}")

    with open(log_path, "w") as log_file:
        log_file.write(f"Aperture Signals Pipeline Run\n")
        log_file.write(f"Mode: {mode}\n")
        log_file.write(f"Started: {datetime.now().isoformat()}\n")
        log_file.write(f"Dry run: {args.dry_run}\n\n")

        # --- DRY RUN: just show steps ---
        if args.dry_run:
            print(f"\n{YELLOW}DRY RUN — showing steps that would execute:{RESET}\n")
            for i, step in enumerate(steps, 1):
                tag = "[SCRAPER]" if step["mode"] == "full" else "[PROCESS]"
                print(f"  {i:>2}. {tag:10} {step['name']:<25} {step['description']}")
                print(f"      $ {step['command']}\n")
            log_file.write("DRY RUN — no steps executed.\n")
            print(f"{GREEN}Dry run complete. {len(steps)} steps would execute.{RESET}")
            return 0

        # --- LIVE RUN ---
        abort = False
        for i, step in enumerate(steps, 1):
            if abort:
                results.append({
                    "name": step["name"],
                    "status": "skipped",
                    "duration": 0,
                    "output_tail": "",
                })
                continue

            print_step_header(i, len(steps), step, log_file)

            step_start = time.time()
            log_file.write(f"  Started: {datetime.now().strftime('%H:%M:%S')}\n")
            log_file.flush()

            try:
                proc = subprocess.run(
                    step["command"],
                    shell=True,
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                )
                duration = time.time() - step_start
                exit_code = proc.returncode

                # Write stdout/stderr to log
                if proc.stdout:
                    log_file.write(proc.stdout)
                if proc.stderr:
                    log_file.write(proc.stderr)
                log_file.write(f"\n  Exit code: {exit_code}\n")
                log_file.write(f"  Duration: {fmt_duration(duration)}\n")
                log_file.flush()

                # Extract last meaningful lines for summary
                output_lines = (proc.stdout or "").strip().split("\n")
                output_tail = "\n".join(output_lines[-3:]) if output_lines else ""

                if exit_code == 0:
                    print(f"  {GREEN}OK{RESET} ({fmt_duration(duration)})")
                    # Show last few lines of output for context
                    for line in output_lines[-3:]:
                        if line.strip():
                            print(f"  {line.strip()[:100]}")
                    results.append({
                        "name": step["name"],
                        "status": "success",
                        "duration": duration,
                        "output_tail": output_tail,
                    })
                else:
                    print(f"  {RED}FAILED{RESET} (exit code {exit_code}, {fmt_duration(duration)})")
                    # Show error output
                    err_lines = (proc.stderr or proc.stdout or "").strip().split("\n")
                    for line in err_lines[-5:]:
                        if line.strip():
                            print(f"  {RED}{line.strip()[:120]}{RESET}")

                    results.append({
                        "name": step["name"],
                        "status": "failed",
                        "duration": duration,
                        "output_tail": "\n".join(err_lines[-3:]),
                    })

                    # Ask whether to continue
                    if not args.no_prompt:
                        try:
                            answer = input(f"\n  Step failed. Continue to next step? [Y/n] ").strip().lower()
                            if answer in ("n", "no"):
                                print(f"  {YELLOW}Pipeline aborted by user.{RESET}")
                                log_file.write("  Pipeline aborted by user.\n")
                                abort = True
                        except (EOFError, KeyboardInterrupt):
                            print(f"\n  {YELLOW}Pipeline aborted.{RESET}")
                            abort = True
                    else:
                        print(f"  {YELLOW}--no-prompt: continuing to next step{RESET}")

            except KeyboardInterrupt:
                duration = time.time() - step_start
                print(f"\n  {YELLOW}Interrupted{RESET} ({fmt_duration(duration)})")
                results.append({
                    "name": step["name"],
                    "status": "interrupted",
                    "duration": duration,
                    "output_tail": "",
                })
                log_file.write(f"\n  Interrupted by user after {fmt_duration(duration)}\n")
                abort = True

        # --- SUMMARY ---
        pipeline_duration = time.time() - pipeline_start

        print_header("PIPELINE SUMMARY")

        # Summary table
        header = f"  {'Step':<25} {'Status':<12} {'Duration':>10}"
        separator = "  " + "─" * 50
        print(header)
        print(separator)
        log_file.write(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}\n")
        log_file.write(header + "\n")
        log_file.write(separator + "\n")

        success_count = 0
        failed_count = 0
        skipped_count = 0

        for r in results:
            status = r["status"]
            dur = fmt_duration(r["duration"]) if r["duration"] else "—"

            if status == "success":
                color = GREEN
                success_count += 1
            elif status == "failed":
                color = RED
                failed_count += 1
            elif status == "skipped":
                color = YELLOW
                skipped_count += 1
            else:
                color = YELLOW
                failed_count += 1

            line = f"  {r['name']:<25} {status:<12} {dur:>10}"
            print(f"{color}{line}{RESET}")
            log_file.write(line + "\n")

        print(separator)
        total_line = (
            f"  Total: {fmt_duration(pipeline_duration):>10}  |  "
            f"{GREEN}{success_count} passed{RESET}  "
            f"{RED}{failed_count} failed{RESET}  "
            f"{YELLOW}{skipped_count} skipped{RESET}"
        )
        print(total_line)
        log_file.write(
            f"\n  Total: {fmt_duration(pipeline_duration)}  |  "
            f"{success_count} passed  {failed_count} failed  {skipped_count} skipped\n"
        )

        log_file.write(f"\nCompleted: {datetime.now().isoformat()}\n")
        print(f"\n  Log saved to: {log_path}")

    return 1 if failed_count > 0 else 0


def main():
    parser = argparse.ArgumentParser(
        description="Aperture Signals Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_pipeline.py --full-refresh
  python scripts/run_pipeline.py --process-only
  python scripts/run_pipeline.py --process-only --dry-run
  python scripts/run_pipeline.py --full-refresh --no-prompt
  python scripts/run_pipeline.py --process-only --concurrency 5
        """,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--full-refresh",
        action="store_true",
        help="Full pipeline: scrape new data + process everything",
    )
    mode_group.add_argument(
        "--process-only",
        action="store_true",
        help="Process-only: skip scrapers, reprocess existing data",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without executing",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Auto-continue on failure (for unattended runs)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Concurrency for async steps (default: 10)",
    )

    args = parser.parse_args()
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()
