#!/usr/bin/env python3
"""Enrichment Priority Queue — score entities by enrichment urgency.

Pure local computation (no API calls). Scores every STARTUP entity on how
urgently it needs web enrichment, based on report visibility and data gaps.

Usage:
    python scripts/enrichment_queue.py --top 50
    python scripts/enrichment_queue.py --report sbir_lapse --top 25
    python scripts/enrichment_queue.py --top 200 --export data/enrichment_priority.txt
    python scripts/enrichment_queue.py --recently-enriched
    python scripts/enrichment_queue.py --status
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "data" / "defense_alpha.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _get_composite_score(conn, entity_id: str) -> float | None:
    """Get most recent composite score from entity_snapshots."""
    row = conn.execute(
        "SELECT composite_score FROM entity_snapshots "
        "WHERE entity_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (entity_id,),
    ).fetchone()
    return float(row["composite_score"]) if row and row["composite_score"] else None


def compute_enrichment_priority(conn, entity_id: str) -> dict:
    """Score how urgently this entity needs enrichment. Higher = more urgent."""
    score = 0.0
    reasons = []

    # 1. SBIR lapse exposure (will appear in lapse report)
    has_lapse_risk = conn.execute(
        "SELECT confidence_score FROM signals "
        "WHERE entity_id = ? AND signal_type = 'sbir_lapse_risk' AND status = 'ACTIVE'",
        (entity_id,),
    ).fetchone()
    if has_lapse_risk:
        score += 3.0
        reasons.append("sbir_lapse")

    # 2. High composite score (likely to appear in deal briefs, sector reports)
    composite = _get_composite_score(conn, entity_id)
    if composite and composite > 5.0:
        score += 2.0
        reasons.append("high_composite")
    elif composite and composite > 3.0:
        score += 1.0
        reasons.append("medium_composite")

    # 3. KOP alignment (will appear in KOP sector maps)
    has_kop = conn.execute(
        "SELECT 1 FROM signals "
        "WHERE entity_id = ? AND signal_type = 'kop_alignment' AND status = 'ACTIVE'",
        (entity_id,),
    ).fetchone()
    if has_kop:
        score += 1.5
        reasons.append("kop_aligned")

    # 4. Data staleness — entities with ONLY SBIR data and nothing else
    has_contracts = conn.execute(
        "SELECT 1 FROM contracts WHERE entity_id = ? LIMIT 1",
        (entity_id,),
    ).fetchone()
    has_regd = conn.execute(
        "SELECT 1 FROM funding_events "
        "WHERE entity_id = ? AND event_type IN ('REG_D_FILING', 'PRIVATE_ROUND') LIMIT 1",
        (entity_id,),
    ).fetchone()

    if not has_contracts and not has_regd:
        score += 2.0
        reasons.append("no_non_sbir_data")
    elif not has_contracts or not has_regd:
        score += 1.0
        reasons.append("partial_data")

    # 5. SBIR dollar amount (bigger pipelines = more visible in reports)
    sbir_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM funding_events "
        "WHERE entity_id = ? AND event_type LIKE 'SBIR_%'",
        (entity_id,),
    ).fetchone()[0]
    if sbir_total >= 10_000_000:
        score += 2.0
        reasons.append("large_sbir_pipeline")
    elif sbir_total >= 1_000_000:
        score += 1.0
        reasons.append("medium_sbir_pipeline")

    # 6. Already enriched recently — deprioritize
    last_enriched = conn.execute(
        "SELECT MAX(created_at) FROM enrichment_findings WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()[0]
    enriched_date_str = None
    if last_enriched:
        try:
            enriched_date = datetime.fromisoformat(last_enriched.replace("Z", "+00:00"))
            now = datetime.now(enriched_date.tzinfo) if enriched_date.tzinfo else datetime.now()
            days_ago = (now - enriched_date).days
            enriched_date_str = enriched_date.strftime("%Y-%m-%d")
            if days_ago < 90:
                score -= 10.0  # Effectively skip
                reasons.append(f"enriched_{days_ago}d_ago")
            elif days_ago < 180:
                score -= 3.0
                reasons.append(f"enriched_{days_ago}d_ago")
        except (ValueError, TypeError):
            pass

    return {
        "entity_id": entity_id,
        "priority_score": round(score, 1),
        "reasons": reasons,
        "last_enriched": enriched_date_str,
    }


def build_priority_queue(conn, report_filter: str | None = None) -> list[dict]:
    """Score all STARTUP entities and return sorted by priority descending."""
    if report_filter == "sbir_lapse":
        # Only score entities with sbir_lapse_risk signal
        rows = conn.execute(
            "SELECT DISTINCT e.id, e.canonical_name "
            "FROM entities e "
            "JOIN signals s ON e.id = s.entity_id "
            "WHERE e.entity_type = 'STARTUP' AND e.merged_into_id IS NULL "
            "AND s.signal_type = 'sbir_lapse_risk' AND s.status = 'ACTIVE'",
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, canonical_name FROM entities "
            "WHERE entity_type = 'STARTUP' AND merged_into_id IS NULL",
        ).fetchall()

    queue = []
    for row in rows:
        result = compute_enrichment_priority(conn, row["id"])
        result["canonical_name"] = row["canonical_name"]
        queue.append(result)

    queue.sort(key=lambda x: x["priority_score"], reverse=True)
    return queue


def show_recently_enriched(conn):
    """Show entities that were recently enriched."""
    rows = conn.execute(
        """SELECT e.canonical_name, ef.finding_type, ef.confidence, ef.status,
                  ef.created_at
           FROM enrichment_findings ef
           JOIN entities e ON ef.entity_id = e.id
           ORDER BY ef.created_at DESC LIMIT 30""",
    ).fetchall()

    if not rows:
        print("No enrichment findings in database.")
        return

    print("\nRECENTLY ENRICHED FINDINGS (last 30)\n")
    print(f"  {'Entity':<35} {'Type':<15} {'Conf':<8} {'Status':<10} {'Date':<12}")
    print(f"  {'-'*35} {'-'*15} {'-'*8} {'-'*10} {'-'*12}")
    for r in rows:
        dt = r["created_at"][:10] if r["created_at"] else "?"
        print(f"  {r['canonical_name'][:35]:<35} {r['finding_type']:<15} "
              f"{r['confidence'] or '?':<8} {r['status']:<10} {dt}")


def show_status(conn):
    """Show enrichment status dashboard."""
    total_startups = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE entity_type='STARTUP' AND merged_into_id IS NULL"
    ).fetchone()[0]

    now = datetime.now()
    d90 = (now - timedelta(days=90)).isoformat()
    d180 = (now - timedelta(days=180)).isoformat()

    # Entities with enrichment findings, grouped by recency
    enriched_entities = conn.execute(
        "SELECT entity_id, MAX(created_at) as last_enriched "
        "FROM enrichment_findings GROUP BY entity_id"
    ).fetchall()

    never = total_startups - len(enriched_entities)
    recent_90 = 0
    recent_180 = 0
    older = 0
    for row in enriched_entities:
        le = row["last_enriched"] or ""
        if le >= d90:
            recent_90 += 1
        elif le >= d180:
            recent_180 += 1
        else:
            older += 1

    # Finding stats
    total_findings = conn.execute("SELECT COUNT(*) FROM enrichment_findings").fetchone()[0]
    approved = conn.execute(
        "SELECT COUNT(*) FROM enrichment_findings WHERE status IN ('approved', 'ingested')"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM enrichment_findings WHERE status = 'pending'"
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM enrichment_findings WHERE status = 'rejected'"
    ).fetchone()[0]

    # By type
    by_type = conn.execute(
        "SELECT finding_type, COUNT(*) as cnt FROM enrichment_findings GROUP BY finding_type ORDER BY cnt DESC"
    ).fetchall()

    print("\nENRICHMENT STATUS\n")
    print(f"  Total startups:           {total_startups:,}")
    print(f"  Never enriched:           {never:,} ({never/total_startups*100:.1f}%)")
    print(f"  Enriched < 90 days:       {recent_90:>5,} ({recent_90/total_startups*100:.1f}%)")
    print(f"  Enriched 90-180 days:     {recent_180:>5,} ({recent_180/total_startups*100:.1f}%)")
    print(f"  Enriched > 180 days:      {older:>5,} ({older/total_startups*100:.1f}%)")

    print(f"\n  Enrichment findings:")
    print(f"    Total:                  {total_findings:>5,}")
    print(f"    Approved/ingested:      {approved:>5,}")
    print(f"    Pending review:         {pending:>5,}")
    print(f"    Rejected:               {rejected:>5,}")

    if by_type:
        print(f"\n  By finding type:")
        for row in by_type:
            print(f"    {row['finding_type']:<20} {row['cnt']:>5,}")


def main():
    parser = argparse.ArgumentParser(
        description="Enrichment Priority Queue — score entities by enrichment urgency",
    )
    parser.add_argument("--top", type=int, default=50,
                        help="Show top N entities (default: 50)")
    parser.add_argument("--report", type=str, choices=["sbir_lapse"],
                        help="Filter to entities relevant to a specific report")
    parser.add_argument("--export", type=str,
                        help="Export entity names to file (one per line)")
    parser.add_argument("--recently-enriched", action="store_true",
                        help="Show recently enriched entities")
    parser.add_argument("--status", action="store_true",
                        help="Show enrichment status dashboard")

    args = parser.parse_args()

    conn = _connect()
    try:
        if args.status:
            show_status(conn)
            return

        if args.recently_enriched:
            show_recently_enriched(conn)
            return

        queue = build_priority_queue(conn, report_filter=args.report)
        top = queue[: args.top]

        filter_label = f" ({args.report})" if args.report else ""
        print(f"\nENRICHMENT PRIORITY QUEUE{filter_label} — Top {len(top)}\n")
        print(f"  {'#':>3} | {'Entity':<35} | {'Score':>5} | {'Reasons':<35} | Last Enriched")
        print(f"  {'-'*3}-+-{'-'*35}-+-{'-'*5}-+-{'-'*35}-+-{'-'*14}")

        for i, entry in enumerate(top, 1):
            reasons_str = ", ".join(entry["reasons"])
            enriched_str = entry["last_enriched"] or "Never"
            print(f"  {i:>3} | {entry['canonical_name'][:35]:<35} | "
                  f"{entry['priority_score']:>5.1f} | {reasons_str[:35]:<35} | {enriched_str}")

        # Summary
        positive = [e for e in queue if e["priority_score"] > 0]
        print(f"\n  Total entities scored: {len(queue)}")
        print(f"  With positive score:  {len(positive)}")

        if args.export:
            export_path = Path(args.export)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            with open(export_path, "w") as f:
                for entry in top:
                    f.write(entry["canonical_name"] + "\n")
            print(f"\n  Exported {len(top)} entity names to {export_path}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
