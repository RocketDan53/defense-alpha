#!/usr/bin/env python3
"""
QA verification for sbir_validated_raise signal data.

Cross-references stored signal evidence against raw funding_events data
to verify SBIR counts, Reg D totals, timeline accuracy, and signal
computation correctness.

Usage:
    python scripts/qa_report_data.py
    python scripts/qa_report_data.py --top 10
    python scripts/qa_report_data.py --entity "SI2 TECHNOLOGIES"
"""

import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from processing.database import SessionLocal
from processing.models import (
    Entity, FundingEvent, FundingEventType, Signal, SignalStatus,
)

PHASE2_WINDOW_DAYS = 548  # ~18 months

SBIR_TYPES = [
    FundingEventType.SBIR_PHASE_1,
    FundingEventType.SBIR_PHASE_2,
    FundingEventType.SBIR_PHASE_3,
]

PHASE_LABELS = {
    FundingEventType.SBIR_PHASE_1: "SBIR Phase I",
    FundingEventType.SBIR_PHASE_2: "SBIR Phase II",
    FundingEventType.SBIR_PHASE_3: "SBIR Phase III",
    FundingEventType.REG_D_FILING: "Reg D",
    FundingEventType.VC_ROUND: "VC Round",
}


def fmt_money(val):
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:,.0f}"


def detect_regd_duplicates(regd_filings, window_days=30):
    """Flag Reg D filings with same amount within window_days as likely amendments."""
    dupes = set()
    sorted_filings = sorted(
        [f for f in regd_filings if f.event_date],
        key=lambda f: f.event_date,
    )
    for i, f1 in enumerate(sorted_filings):
        for j in range(i + 1, len(sorted_filings)):
            f2 = sorted_filings[j]
            gap = (f2.event_date - f1.event_date).days
            if gap > window_days:
                break
            amt1 = float(f1.amount or 0)
            amt2 = float(f2.amount or 0)
            if amt1 > 0 and amt1 == amt2:
                dupes.add(f2.id)
    return dupes


def _dedup_filings(filings):
    """Deduplicate filings with same (entity_id, event_date, amount)."""
    seen = set()
    deduped = []
    for f in filings:
        key = (str(f.entity_id), str(f.event_date), str(f.amount))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped


def recompute_signal(sbir_awards, regd_filings):
    """Recompute sbir_validated_raise from raw funding_events.

    Returns (should_fire, confidence, evidence) using the same logic
    as SignalDetector.detect_sbir_validated_raise but from raw data.
    Applies dedup to Reg D filings to match detector behavior.
    """
    sbir_with_dates = [a for a in sbir_awards if a.event_date]
    regd_deduped = _dedup_filings(regd_filings)
    regd_with_dates = [f for f in regd_deduped if f.event_date]

    if not sbir_with_dates or not regd_with_dates:
        return False, Decimal("0"), {}

    first_sbir_date = min(a.event_date for a in sbir_with_dates)
    first_regd_date = min(f.event_date for f in regd_with_dates)
    latest_regd_date = max(f.event_date for f in regd_with_dates)

    phase2_awards = [
        a for a in sbir_with_dates
        if a.event_type == FundingEventType.SBIR_PHASE_2
    ]

    # Condition A: first Reg D postdates first SBIR
    sbir_first_pathway = first_regd_date > first_sbir_date

    # Condition B: Reg D within 18 months after Phase II
    phase2_catalyst = False
    phase2_gap_months = None
    for p2 in phase2_awards:
        for rd in regd_with_dates:
            gap = (rd.event_date - p2.event_date).days
            if 0 < gap <= PHASE2_WINDOW_DAYS:
                phase2_catalyst = True
                gap_mo = round(gap / 30.44)
                if phase2_gap_months is None or gap_mo < phase2_gap_months:
                    phase2_gap_months = gap_mo
                break
        if phase2_catalyst:
            break

    if not sbir_first_pathway and not phase2_catalyst:
        return False, Decimal("0"), {"reason": "no qualifying pathway"}

    confidence = Decimal("0.70")
    if sbir_first_pathway:
        confidence += Decimal("0.10")
    if phase2_catalyst:
        confidence += Decimal("0.10")

    raise_post_sbir = sum(
        float(f.amount or 0)
        for f in regd_with_dates
        if f.event_date > first_sbir_date
    )
    if raise_post_sbir > 5_000_000:
        confidence += Decimal("0.05")

    confidence = min(Decimal("0.95"), confidence)

    if sbir_first_pathway:
        sequence = "sbir_first"
    elif first_regd_date < first_sbir_date:
        sequence = "mixed"
    else:
        sequence = "vc_first"

    return True, confidence, {
        "first_sbir_date": str(first_sbir_date),
        "first_regd_date": str(first_regd_date),
        "sbir_award_count": len(sbir_awards),
        "regd_filing_count": len(regd_deduped),
        "raise_amount_post_sbir": raise_post_sbir,
        "sequence": sequence,
        "sbir_first_pathway": sbir_first_pathway,
        "phase2_catalyst": phase2_catalyst,
        "phase2_to_raise_gap_months": phase2_gap_months,
    }


def verify_entity(db, entity, signal):
    """Run all verification checks for one entity. Returns dict of results."""
    eid = entity.id
    evidence = signal.evidence or {}
    results = {"name": entity.canonical_name, "checks": [], "pass_count": 0, "fail_count": 0}

    # ── 1. SBIR VERIFICATION ─────────────────────────────────────

    sbir_awards = db.query(FundingEvent).filter(
        FundingEvent.entity_id == eid,
        FundingEvent.event_type.in_(SBIR_TYPES),
    ).order_by(FundingEvent.event_date).all()

    actual_sbir_count = len(sbir_awards)
    actual_sbir_total = sum(float(a.amount or 0) for a in sbir_awards)
    evidence_sbir_count = evidence.get("sbir_award_count", 0)

    sbir_count_match = actual_sbir_count == evidence_sbir_count
    status = "PASS" if sbir_count_match else "FAIL"
    results["checks"].append({
        "section": "SBIR",
        "check": "SBIR count matches evidence",
        "status": status,
        "detail": f"DB: {actual_sbir_count}, Evidence: {evidence_sbir_count}",
    })
    if sbir_count_match:
        results["pass_count"] += 1
    else:
        results["fail_count"] += 1

    phase2_awards = [
        a for a in sbir_awards
        if a.event_type == FundingEventType.SBIR_PHASE_2
    ]

    results["sbir_summary"] = {
        "count": actual_sbir_count,
        "total": actual_sbir_total,
        "phase2_count": len(phase2_awards),
        "phase2_list": [
            {
                "title": (a.raw_data or {}).get("Award Title", "(no title)"),
                "date": str(a.event_date) if a.event_date else "N/A",
                "amount": float(a.amount or 0),
            }
            for a in phase2_awards
        ],
    }

    # ── 2. REG D VERIFICATION ────────────────────────────────────

    regd_filings = db.query(FundingEvent).filter(
        FundingEvent.entity_id == eid,
        FundingEvent.event_type == FundingEventType.REG_D_FILING,
    ).order_by(FundingEvent.event_date).all()

    raw_regd_count = len(regd_filings)
    actual_regd_total = sum(float(f.amount or 0) for f in regd_filings)
    evidence_regd_count = evidence.get("regd_filing_count", 0)

    # Duplicate detection (signal detector now deduplicates, so evidence
    # reflects deduped counts — compare against deduped count)
    dupe_ids = detect_regd_duplicates(regd_filings)
    deduped_regd_count = raw_regd_count - len(dupe_ids)

    regd_count_match = deduped_regd_count == evidence_regd_count
    status = "PASS" if regd_count_match else "FAIL"
    detail = f"DB raw: {raw_regd_count}, deduped: {deduped_regd_count}, evidence: {evidence_regd_count}"
    results["checks"].append({
        "section": "REG D",
        "check": "Reg D count matches evidence (deduped)",
        "status": status,
        "detail": detail,
    })
    if regd_count_match:
        results["pass_count"] += 1
    else:
        results["fail_count"] += 1
    deduped_total = sum(
        float(f.amount or 0) for f in regd_filings if f.id not in dupe_ids
    )

    results["checks"].append({
        "section": "REG D",
        "check": "Potential Reg D duplicates",
        "status": "WARN" if dupe_ids else "PASS",
        "detail": (
            f"{len(dupe_ids)} likely amended filing(s) detected"
            if dupe_ids
            else "No duplicates found"
        ),
    })
    if not dupe_ids:
        results["pass_count"] += 1

    # Post-SBIR raise calculation (compare against deduped amounts,
    # since signal detector now deduplicates before computing totals)
    first_sbir_date = min(
        (a.event_date for a in sbir_awards if a.event_date), default=None
    )
    if first_sbir_date:
        actual_post_sbir_deduped = sum(
            float(f.amount or 0)
            for f in regd_filings
            if f.event_date and f.event_date > first_sbir_date
            and f.id not in dupe_ids
        )
        evidence_post_sbir = evidence.get("raise_amount_post_sbir", 0)
        diff = abs(actual_post_sbir_deduped - evidence_post_sbir)
        match = diff < 1.0  # float rounding tolerance
        status = "PASS" if match else "FAIL"
        results["checks"].append({
            "section": "REG D",
            "check": "Post-SBIR raise amount matches evidence",
            "status": status,
            "detail": f"DB deduped: {fmt_money(actual_post_sbir_deduped)}, Evidence: {fmt_money(evidence_post_sbir)}",
        })
        if match:
            results["pass_count"] += 1
        else:
            results["fail_count"] += 1

    results["regd_summary"] = {
        "count": raw_regd_count,
        "total": actual_regd_total,
        "deduped_total": deduped_total,
        "duplicate_count": len(dupe_ids),
        "post_sbir_total": actual_post_sbir_deduped if first_sbir_date else 0,
        "post_sbir_deduped": actual_post_sbir_deduped if first_sbir_date else 0,
        "filings": [
            {
                "date": str(f.event_date) if f.event_date else "N/A",
                "amount": float(f.amount or 0),
                "is_dupe": f.id in dupe_ids,
            }
            for f in regd_filings
        ],
    }

    # ── 3. SIGNAL VERIFICATION ───────────────────────────────────

    should_fire, recomputed_conf, recomputed_ev = recompute_signal(
        sbir_awards, regd_filings,
    )

    # Did it fire correctly?
    status = "PASS" if should_fire else "FAIL"
    results["checks"].append({
        "section": "SIGNAL",
        "check": "Signal should fire (recomputed)",
        "status": status,
        "detail": "Recomputation confirms signal" if should_fire else "Signal should NOT have fired",
    })
    if should_fire:
        results["pass_count"] += 1
    else:
        results["fail_count"] += 1

    # Confidence match
    stored_conf = signal.confidence_score
    conf_match = stored_conf == recomputed_conf
    status = "PASS" if conf_match else "FAIL"
    results["checks"].append({
        "section": "SIGNAL",
        "check": "Confidence matches recomputation",
        "status": status,
        "detail": f"Stored: {stored_conf}, Recomputed: {recomputed_conf}",
    })
    if conf_match:
        results["pass_count"] += 1
    else:
        results["fail_count"] += 1

    # Sequence match
    stored_seq = evidence.get("sequence")
    recomputed_seq = recomputed_ev.get("sequence")
    seq_match = stored_seq == recomputed_seq
    status = "PASS" if seq_match else "FAIL"
    results["checks"].append({
        "section": "SIGNAL",
        "check": "Sequence classification matches",
        "status": status,
        "detail": f"Stored: {stored_seq}, Recomputed: {recomputed_seq}",
    })
    if seq_match:
        results["pass_count"] += 1
    else:
        results["fail_count"] += 1

    # Phase2 catalyst match
    stored_cat = evidence.get("phase2_catalyst")
    recomputed_cat = recomputed_ev.get("phase2_catalyst")
    cat_match = stored_cat == recomputed_cat
    status = "PASS" if cat_match else "FAIL"
    results["checks"].append({
        "section": "SIGNAL",
        "check": "Phase II catalyst flag matches",
        "status": status,
        "detail": f"Stored: {stored_cat}, Recomputed: {recomputed_cat}",
    })
    if cat_match:
        results["pass_count"] += 1
    else:
        results["fail_count"] += 1

    # ── 4. TIMELINE ──────────────────────────────────────────────

    timeline = []
    for a in sbir_awards:
        label = PHASE_LABELS.get(a.event_type, str(a.event_type))
        title = (a.raw_data or {}).get("Award Title", "")
        title_str = f" — {title}" if title else ""
        timeline.append({
            "date": a.event_date,
            "type": label,
            "amount": float(a.amount or 0),
            "detail": title_str,
        })
    for f in regd_filings:
        timeline.append({
            "date": f.event_date,
            "type": "Reg D" + (" (DUPE)" if f.id in dupe_ids else ""),
            "amount": float(f.amount or 0),
            "detail": "",
        })

    timeline.sort(key=lambda x: (x["date"] or date.min))
    results["timeline"] = timeline

    # Timeline narrative check: is the first event an SBIR?
    if timeline:
        first_event_is_sbir = timeline[0]["type"].startswith("SBIR")
        status = "PASS" if first_event_is_sbir else "INFO"
        results["checks"].append({
            "section": "TIMELINE",
            "check": "First event is SBIR (narrative check)",
            "status": status,
            "detail": f"First event: {timeline[0]['type']} on {timeline[0]['date']}",
        })
        if first_event_is_sbir:
            results["pass_count"] += 1

    return results


def print_report(all_results):
    """Print the full verification report."""
    total_pass = 0
    total_fail = 0
    total_warn = 0
    companies_clean = 0
    companies_with_issues = []

    for i, r in enumerate(all_results, 1):
        name = r["name"]
        p = r["pass_count"]
        f = r["fail_count"]
        total_pass += p
        total_fail += f

        print(f"\n{'=' * 74}")
        print(f"  #{i}  {name}")
        print(f"{'=' * 74}")

        # ── Checks table ──
        for c in r["checks"]:
            icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "INFO": "·"}.get(c["status"], "?")
            print(f"  [{icon} {c['status']:4s}] {c['section']:8s} | {c['check']}")
            if c["status"] in ("FAIL", "WARN") or (c["status"] == "PASS" and "matches" not in c["check"]):
                pass  # always show detail
            print(f"           {'':8s}   {c['detail']}")

        # ── SBIR summary ──
        ss = r["sbir_summary"]
        print(f"\n  SBIR: {ss['count']} awards, {fmt_money(ss['total'])} total, {ss['phase2_count']} Phase II")
        if ss["phase2_list"]:
            for p2 in ss["phase2_list"]:
                print(f"    Phase II: {p2['date']}  {fmt_money(p2['amount']):>8s}  {p2['title'][:60]}")

        # ── Reg D summary ──
        rs = r["regd_summary"]
        print(f"\n  Reg D: {rs['count']} filings, {fmt_money(rs['total'])} total")
        if rs["duplicate_count"]:
            print(f"    Duplicates: {rs['duplicate_count']} (deduped total: {fmt_money(rs['deduped_total'])})")
            print(f"    Post-SBIR deduped: {fmt_money(rs['post_sbir_deduped'])}")
        else:
            print(f"    Post-SBIR: {fmt_money(rs['post_sbir_total'])}")

        # ── Timeline ──
        print(f"\n  Timeline:")
        for ev in r["timeline"]:
            d = ev["date"] or "N/A"
            amt = fmt_money(ev["amount"]) if ev["amount"] else ""
            print(f"    [{d}]  {ev['type']:<16s}  {amt:>10s}{ev['detail'][:50]}")

        # ── Verdict ──
        if f == 0:
            warn_count = sum(1 for c in r["checks"] if c["status"] == "WARN")
            total_warn += warn_count
            if warn_count:
                print(f"\n  RESULT: PASS with {warn_count} warning(s)")
            else:
                print(f"\n  RESULT: CLEAN PASS ({p}/{p})")
            companies_clean += 1
        else:
            print(f"\n  RESULT: {f} FAILURE(s), {p} pass")
            companies_with_issues.append(name)

    # ── Summary ──
    print(f"\n{'=' * 74}")
    print(f"  QA SUMMARY")
    print(f"{'=' * 74}")
    print(f"  Companies verified:   {len(all_results)}")
    print(f"  Clean passes:         {companies_clean}")
    print(f"  With failures:        {len(companies_with_issues)}")
    print(f"  Total checks:         {total_pass + total_fail}")
    print(f"  Passed:               {total_pass}")
    print(f"  Failed:               {total_fail}")
    print(f"  Warnings:             {total_warn}")

    if companies_with_issues:
        print(f"\n  COMPANIES WITH FAILURES:")
        for name in companies_with_issues:
            print(f"    - {name}")

    # Duplicate summary
    dupe_companies = [
        (r["name"], r["regd_summary"]["duplicate_count"])
        for r in all_results if r["regd_summary"]["duplicate_count"] > 0
    ]
    if dupe_companies:
        print(f"\n  REG D DUPLICATE WARNINGS ({len(dupe_companies)} companies):")
        for name, dc in dupe_companies:
            r = next(x for x in all_results if x["name"] == name)
            rs = r["regd_summary"]
            print(f"    {name}: {dc} dupe(s), "
                  f"raw={fmt_money(rs['total'])}, "
                  f"deduped={fmt_money(rs['deduped_total'])}, "
                  f"diff={fmt_money(rs['total'] - rs['deduped_total'])}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="QA verification for sbir_validated_raise signal data"
    )
    parser.add_argument("--top", type=int, default=20, help="Number of top companies to verify")
    parser.add_argument("--entity", type=str, help="Verify a specific entity by name")
    args = parser.parse_args()

    db = SessionLocal()

    if args.entity:
        # Verify one entity
        signal = (
            db.query(Signal)
            .join(Entity, Entity.id == Signal.entity_id)
            .filter(
                Signal.signal_type == "sbir_validated_raise",
                Signal.status == SignalStatus.ACTIVE,
                Entity.canonical_name.ilike(f"%{args.entity}%"),
            )
            .first()
        )
        if not signal:
            print(f"No sbir_validated_raise signal found for: {args.entity}")
            sys.exit(1)
        entity = db.query(Entity).filter(Entity.id == signal.entity_id).first()
        results = [verify_entity(db, entity, signal)]
    else:
        # Top N by confidence then raise amount
        signals = (
            db.query(Signal)
            .filter(
                Signal.signal_type == "sbir_validated_raise",
                Signal.status == SignalStatus.ACTIVE,
            )
            .all()
        )
        # Sort by confidence desc, then raise_amount_post_sbir desc
        signals.sort(key=lambda s: (
            -float(s.confidence_score or 0),
            -(s.evidence or {}).get("raise_amount_post_sbir", 0),
        ))
        signals = signals[:args.top]

        results = []
        for sig in signals:
            entity = db.query(Entity).filter(Entity.id == sig.entity_id).first()
            if entity:
                results.append(verify_entity(db, entity, sig))

    print_report(results)
    db.close()


if __name__ == "__main__":
    main()
