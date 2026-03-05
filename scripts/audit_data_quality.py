#!/usr/bin/env python3
"""
Aperture Signals — Data Quality Audit

Comprehensive infrastructure audit covering entity integrity, funding accuracy,
signal correctness, policy alignment consistency, and brief generation reliability.

Usage:
    python scripts/audit_data_quality.py
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "defense_alpha.db"


def run_audit():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    issues = []
    warnings = []

    print("=" * 60)
    print("APERTURE SIGNALS — INFRASTRUCTURE QUALITY AUDIT")
    print("=" * 60)

    # ─────────────────────────────────────────────
    # SECTION 1: ENTITY INTEGRITY
    # ─────────────────────────────────────────────
    print("\n[1] ENTITY INTEGRITY")

    # 1a. STARTUPs with large contracts that may be PRIMEs
    c.execute("""
        SELECT e.canonical_name, ROUND(SUM(con.contract_value)/1e6,1) as total_m, COUNT(con.id) as n
        FROM entities e
        JOIN contracts con ON e.id = con.entity_id
        WHERE e.entity_type = 'STARTUP'
        GROUP BY e.id
        HAVING SUM(con.contract_value) > 50000000
        ORDER BY total_m DESC
    """)
    rows = c.fetchall()
    if rows:
        warnings.append(f"1a. {len(rows)} STARTUPs with >$50M contracts — potential PRIME misclassification")
        print(f"  WARN 1a: {len(rows)} STARTUPs with >$50M contracts (may be misclassified PRIMEs):")
        for r in rows[:10]:
            print(f"    {r[0][:40]:<40} ${r[1]}M across {r[2]} contracts")
    else:
        print("  OK 1a: No STARTUP entities with >$50M contracts")

    # 1b. Merged duplicates still appearing as active
    c.execute("""
        SELECT COUNT(*) FROM entities
        WHERE merged_into_id IS NOT NULL
        AND entity_type != 'NON_DEFENSE'
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"1b. {v} merged entities still have active entity_type")
        print(f"  FAIL 1b: {v} entities have merged_into_id set but active entity_type")
    else:
        print("  OK 1b: All merged entities properly handled")

    # 1c. Consortium entities still in STARTUP pool (match the tag, not the word)
    c.execute("""
        SELECT COUNT(*) FROM entities
        WHERE entity_type = 'STARTUP'
        AND core_business_reasoning LIKE '%[CONSORTIUM -%'
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"1c. {v} consortium entities still classified as STARTUP")
        print(f"  FAIL 1c: {v} consortium entities still in STARTUP pool")
    else:
        print("  OK 1c: No consortium entities in STARTUP pool")

    # 1d. NON_DEFENSE entities with SBIR or contract data
    c.execute("""
        SELECT COUNT(DISTINCT e.id) FROM entities e
        JOIN funding_events fe ON e.id = fe.entity_id
        WHERE e.entity_type = 'NON_DEFENSE'
        AND fe.event_type LIKE 'SBIR%'
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"1d. {v} NON_DEFENSE entities have SBIR data — misclassified")
        print(f"  FAIL 1d: {v} NON_DEFENSE entities have SBIR events (misclassified)")
    else:
        print("  OK 1d: No NON_DEFENSE entities with SBIR data")

    c.execute("""
        SELECT COUNT(DISTINCT e.id) FROM entities e
        JOIN contracts con ON e.id = con.entity_id
        WHERE e.entity_type = 'NON_DEFENSE'
        AND e.merged_into_id IS NULL
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"1d2. {v} NON_DEFENSE entities have contract data — misclassified")
        print(f"  FAIL 1d2: {v} NON_DEFENSE entities have contracts (misclassified)")
    else:
        print("  OK 1d2: No NON_DEFENSE entities with contract data")

    # ─────────────────────────────────────────────
    # SECTION 2: FUNDING DATA ACCURACY
    # ─────────────────────────────────────────────
    print("\n[2] FUNDING DATA ACCURACY")

    # 2a. parent_event_id integrity
    c.execute("""
        SELECT COUNT(*) FROM funding_events
        WHERE parent_event_id IS NOT NULL
        AND parent_event_id NOT IN (SELECT id FROM funding_events)
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"2a. {v} funding events reference non-existent parent_event_id")
        print(f"  FAIL 2a: {v} orphaned parent_event_id references")
    else:
        print("  OK 2a: All parent_event_id references valid")

    # 2b. Superseded row count
    c.execute("SELECT COUNT(*) FROM funding_events WHERE parent_event_id IS NOT NULL")
    print(f"  INFO 2b: {c.fetchone()[0]} superseded funding rows (linked via parent_event_id)")

    # 2c. Duplicate funding events
    c.execute("""
        SELECT entity_id, amount, event_date, COUNT(*) as cnt,
               MIN(id) as keep_id
        FROM funding_events
        WHERE event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')
        AND amount IS NOT NULL
        AND parent_event_id IS NULL
        GROUP BY entity_id, amount, event_date
        HAVING COUNT(*) > 1
    """)
    dupes = c.fetchall()
    if dupes:
        issues.append(f"2c. {len(dupes)} duplicate funding event groups (same entity/amount/date)")
        print(f"  FAIL 2c: {len(dupes)} duplicate funding event groups:")
        for d in dupes[:5]:
            c.execute("SELECT canonical_name FROM entities WHERE id=?", (d[0],))
            name = c.fetchone()
            print(f"    {(name[0] if name else d[0])[:35]:<35} ${(d[1] or 0)/1e6:.1f}M on {d[2]} x{d[3]}")
    else:
        print("  OK 2c: No duplicate funding events")

    # 2d. Funding events with NULL amounts on non-SBIR records
    c.execute("""
        SELECT event_type, COUNT(*) FROM funding_events
        WHERE amount IS NULL
        AND event_type NOT LIKE 'SBIR%'
        GROUP BY event_type
    """)
    null_amounts = c.fetchall()
    if null_amounts:
        for row in null_amounts:
            warnings.append(f"2d. {row[1]} {row[0]} events have NULL amount")
            print(f"  WARN 2d: {row[1]} {row[0]} records with NULL amount")
    else:
        print("  OK 2d: No unexpected NULL amounts in funding events")

    # 2e. Implausibly large single funding events (>$5B)
    c.execute("""
        SELECT e.canonical_name, fe.amount/1e9, fe.event_type, fe.event_date
        FROM funding_events fe
        JOIN entities e ON fe.entity_id = e.id
        WHERE fe.amount > 5000000000
        AND fe.parent_event_id IS NULL
        ORDER BY fe.amount DESC
    """)
    large_rounds = c.fetchall()
    if large_rounds:
        warnings.append(f"2e. {len(large_rounds)} funding events >$5B — verify not data errors")
        print(f"  WARN 2e: {len(large_rounds)} funding events >$5B:")
        for r in large_rounds:
            print(f"    {r[0][:35]:<35} ${r[1]:.1f}B ({r[2]}, {r[3]})")
    else:
        print("  OK 2e: No implausibly large funding events")

    # ─────────────────────────────────────────────
    # SECTION 3: SIGNAL CORRECTNESS
    # ─────────────────────────────────────────────
    print("\n[3] SIGNAL CORRECTNESS")

    # 3a. Signals on NON_DEFENSE or PRIME entities
    c.execute("""
        SELECT e.entity_type, COUNT(*) as cnt
        FROM signals s
        JOIN entities e ON s.entity_id = e.id
        WHERE s.status = 'ACTIVE'
        AND e.entity_type IN ('NON_DEFENSE', 'PRIME')
        GROUP BY e.entity_type
    """)
    wrong_type_signals = c.fetchall()
    if wrong_type_signals:
        for row in wrong_type_signals:
            issues.append(f"3a. {row[1]} active signals on {row[0]} entities")
            print(f"  FAIL 3a: {row[1]} active signals on {row[0]} entities")
    else:
        print("  OK 3a: All active signals are on STARTUP entities")

    # 3b. gone_stale firing on entities with recent activity
    c.execute("""
        SELECT COUNT(*) FROM signals s
        JOIN entities e ON s.entity_id = e.id
        WHERE s.signal_type = 'gone_stale'
        AND s.status = 'ACTIVE'
        AND (
            e.id IN (SELECT entity_id FROM contracts WHERE award_date > date('now', '-24 months'))
            OR e.id IN (SELECT entity_id FROM funding_events WHERE event_date > date('now', '-24 months'))
        )
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"3b. {v} entities have gone_stale but recent activity in last 24mo")
        print(f"  FAIL 3b: {v} entities flagged gone_stale but have recent activity")
    else:
        print("  OK 3b: gone_stale signal firing correctly")

    # 3c. sbir_validated_raise temporal sequencing
    c.execute("""
        SELECT COUNT(*) FROM signals s
        WHERE s.signal_type = 'sbir_validated_raise'
        AND s.status = 'ACTIVE'
        AND json_extract(s.evidence, '$.sbir_date') > json_extract(s.evidence, '$.raise_date')
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"3c. {v} sbir_validated_raise with raise before SBIR")
        print(f"  FAIL 3c: {v} sbir_validated_raise with raise_date before sbir_date")
    else:
        print("  OK 3c: sbir_validated_raise temporal sequencing correct")

    # 3d. Signal score distribution sanity
    c.execute("""
        SELECT signal_type,
            ROUND(MIN(confidence_score),3),
            ROUND(MAX(confidence_score),3),
            ROUND(AVG(confidence_score),3),
            COUNT(*)
        FROM signals WHERE status='ACTIVE'
        GROUP BY signal_type
        ORDER BY COUNT(*) DESC
    """)
    print("  INFO 3d: Signal confidence distribution:")
    for r in c.fetchall():
        flag = " *** CHECK" if r[1] < 0 or r[2] > 1 else ""
        print(f"    {r[0]:<35} min:{r[1]} max:{r[2]} avg:{r[3]} n={r[4]}{flag}")

    # 3e. Signals referencing non-existent entities
    c.execute("""
        SELECT COUNT(*) FROM signals s
        LEFT JOIN entities e ON s.entity_id = e.id
        WHERE e.id IS NULL
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"3e. {v} signals reference non-existent entities")
        print(f"  FAIL 3e: {v} orphaned signals")
    else:
        print("  OK 3e: All signals reference valid entities")

    # ─────────────────────────────────────────────
    # SECTION 4: POLICY ALIGNMENT CONSISTENCY
    # ─────────────────────────────────────────────
    print("\n[4] POLICY ALIGNMENT CONSISTENCY")

    # 4a. Policy tailwind score range
    c.execute("""
        SELECT COUNT(*) FROM entities
        WHERE entity_type = 'STARTUP'
        AND policy_alignment IS NOT NULL
        AND (
            json_extract(policy_alignment, '$.policy_tailwind_score') > 1.0
            OR json_extract(policy_alignment, '$.policy_tailwind_score') < 0.0
        )
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"4a. {v} entities have policy_tailwind_score outside [0,1]")
        print(f"  FAIL 4a: {v} entities with out-of-range policy_tailwind_score")
    else:
        print("  OK 4a: All policy_tailwind_scores within [0,1]")

    # 4b. Entities with classification but no policy score
    c.execute("""
        SELECT COUNT(*) FROM entities
        WHERE entity_type = 'STARTUP'
        AND core_business IS NOT NULL
        AND core_business != 'unclassified'
        AND policy_alignment IS NULL
    """)
    v = c.fetchone()[0]
    if v:
        warnings.append(f"4b. {v} classified STARTUPs missing policy alignment score")
        print(f"  WARN 4b: {v} classified STARTUPs have no policy score")
    else:
        print("  OK 4b: All classified STARTUPs have policy scores")

    # 4c. Policy score distribution
    c.execute("""
        SELECT
            SUM(CASE WHEN json_extract(policy_alignment, '$.policy_tailwind_score') = 0 THEN 1 ELSE 0 END) as zero_score,
            SUM(CASE WHEN json_extract(policy_alignment, '$.policy_tailwind_score') > 0.8 THEN 1 ELSE 0 END) as high_score,
            SUM(CASE WHEN json_extract(policy_alignment, '$.policy_tailwind_score') BETWEEN 0.3 AND 0.7 THEN 1 ELSE 0 END) as mid_score,
            COUNT(*) as total
        FROM entities
        WHERE entity_type = 'STARTUP'
        AND policy_alignment IS NOT NULL
    """)
    r = c.fetchone()
    print(f"  INFO 4c: Score distribution — zero: {r[0]}, mid(0.3-0.7): {r[2]}, high(>0.8): {r[1]}, total: {r[3]}")
    if r[0] and r[3] and r[0] > r[3] * 0.3:
        warnings.append(f"4c. {r[0]} entities ({round(r[0]/r[3]*100)}%) scored exactly 0.0")
        print(f"  WARN 4c: High concentration of zero scores ({round(r[0]/r[3]*100)}%)")

    # ─────────────────────────────────────────────
    # SECTION 5: BRIEF GENERATION RELIABILITY
    # ─────────────────────────────────────────────
    print("\n[5] BRIEF GENERATION RELIABILITY")

    # 5a. PRIMEs or NON_DEFENSE fully scored (comparables filter check)
    c.execute("""
        SELECT entity_type, COUNT(*) FROM entities
        WHERE entity_type IN ('PRIME', 'NON_DEFENSE')
        AND core_business IS NOT NULL
        AND core_business != 'unclassified'
        AND policy_alignment IS NOT NULL
        GROUP BY entity_type
    """)
    rows = c.fetchall()
    for r in rows:
        warnings.append(f"5a. {r[1]} {r[0]} entities are fully scored — comparables must filter by entity_type")
        print(f"  WARN 5a: {r[1]} {r[0]} entities are fully scored (comparables query must filter by entity_type=STARTUP)")
    if not rows:
        print("  OK 5a: No non-STARTUP entities in comparables pool")

    # 5b. Contracts with negative values
    c.execute("SELECT COUNT(*) FROM contracts WHERE contract_value < 0")
    v = c.fetchone()[0]
    if v:
        issues.append(f"5b. {v} contracts with negative value")
        print(f"  FAIL 5b: {v} contracts with negative contract_value")
    else:
        print("  OK 5b: No negative contract values")

    c.execute("SELECT COUNT(*) FROM contracts WHERE contract_value > 50000000000")
    v = c.fetchone()[0]
    if v:
        warnings.append(f"5b2. {v} contracts >$50B — verify not data errors")
        print(f"  WARN 5b2: {v} contracts with value >$50B")
    else:
        print("  OK 5b2: No implausibly large contracts")

    # 5c. Contract-based signals without contract records
    c.execute("""
        SELECT COUNT(DISTINCT s.entity_id) FROM signals s
        JOIN entities e ON s.entity_id = e.id
        WHERE s.signal_type IN ('sbir_to_contract_transition', 'rapid_contract_growth')
        AND s.status = 'ACTIVE'
        AND e.id NOT IN (SELECT DISTINCT entity_id FROM contracts)
    """)
    v = c.fetchone()[0]
    if v:
        issues.append(f"5c. {v} entities have contract signals but no contract records")
        print(f"  FAIL 5c: {v} entities with contract signals but no contracts in DB")
    else:
        print("  OK 5c: Contract-based signals all have supporting contract records")

    # ─────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("AUDIT SUMMARY")
    print("=" * 60)
    print(f"\nFAILURES ({len(issues)}) — must fix before investor delivery:")
    if issues:
        for i in issues:
            print(f"  ✗ {i}")
    else:
        print("  None")

    print(f"\nWARNINGS ({len(warnings)}) — review before delivery:")
    if warnings:
        for w in warnings:
            print(f"  △ {w}")
    else:
        print("  None")

    result = "PASS" if not issues else "FAIL — address failures before delivery"
    print(f"\nOverall: {result}")

    conn.close()
    return len(issues) == 0


if __name__ == "__main__":
    passed = run_audit()
    sys.exit(0 if passed else 1)
