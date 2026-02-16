#!/usr/bin/env python3
"""
Policy Signal-Response Proof of Concept — Space Force Establishment

Tests whether the US Space Force establishment (Dec 2019) produced measurable
private market responses in SBIR awards, Reg D filings, and contract activity
for space-aligned entities vs. a non-space defense control group.

Usage:
    cd ~/projects/defense-alpha && source venv/bin/activate
    python scripts/policy_signal_poc.py
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "defense_alpha.db"

# === Section 1: Configuration ===

SIGNAL_NAME = "US Space Force Establishment"
SIGNAL_DATE = "2019-12-20"

BASELINE_START = "2017-01-01"
BASELINE_END = "2019-12-31"
RESPONSE_START = "2020-01-01"
RESPONSE_END = "2022-12-31"

SPACE_THRESHOLD = 0.5
CONTROL_THRESHOLD = 0.3

# Quarters for time series
QUARTERS = []
for year in range(2017, 2023):
    for q in range(1, 5):
        q_start_month = (q - 1) * 3 + 1
        q_end_month = q * 3
        # Last day of quarter
        if q_end_month in (3, 12):
            q_end_day = 31
        elif q_end_month in (6, 9):
            q_end_day = 30
        else:
            q_end_day = 28
        q_start = f"{year}-{q_start_month:02d}-01"
        q_end = f"{year}-{q_end_month:02d}-{q_end_day:02d}"
        QUARTERS.append((f"{year}-Q{q}", q_start, q_end))


def get_cohort_ids(conn, threshold_op, threshold_val):
    """Get entity IDs matching space_resilience threshold."""
    cursor = conn.execute("""
        SELECT id
        FROM entities
        WHERE json_extract(policy_alignment, '$.scores.space_resilience') """ + threshold_op + """ ?
          AND merged_into_id IS NULL
          AND policy_alignment IS NOT NULL
    """, (threshold_val,))
    return [row[0] for row in cursor.fetchall()]


def get_control_ids(conn):
    """Get control group: STARTUP entities with space_resilience < 0.3."""
    cursor = conn.execute("""
        SELECT id
        FROM entities
        WHERE json_extract(policy_alignment, '$.scores.space_resilience') < ?
          AND merged_into_id IS NULL
          AND policy_alignment IS NOT NULL
          AND entity_type = 'STARTUP'
    """, (CONTROL_THRESHOLD,))
    return [row[0] for row in cursor.fetchall()]


def placeholders(ids):
    """Generate SQL placeholders for a list of IDs."""
    return ",".join("?" * len(ids))


def compute_metrics(conn, entity_ids, date_start, date_end):
    """Compute all metrics for a cohort in a date range."""
    if not entity_ids:
        return {
            "sbir_p1_count": 0, "sbir_p2_count": 0, "sbir_total_value": 0,
            "regd_count": 0, "regd_capital": 0,
            "contract_count": 0, "contract_value": 0,
            "unique_entities": 0,
        }

    ph = placeholders(entity_ids)
    base_params = entity_ids + [date_start, date_end]

    # SBIR Phase I
    row = conn.execute(f"""
        SELECT COUNT(*), COALESCE(SUM(amount), 0)
        FROM funding_events
        WHERE entity_id IN ({ph})
          AND event_type = 'SBIR_PHASE_1'
          AND event_date >= ? AND event_date <= ?
    """, base_params).fetchone()
    sbir_p1_count, sbir_p1_value = row

    # SBIR Phase II
    row = conn.execute(f"""
        SELECT COUNT(*), COALESCE(SUM(amount), 0)
        FROM funding_events
        WHERE entity_id IN ({ph})
          AND event_type = 'SBIR_PHASE_2'
          AND event_date >= ? AND event_date <= ?
    """, base_params).fetchone()
    sbir_p2_count, sbir_p2_value = row

    # Reg D
    row = conn.execute(f"""
        SELECT COUNT(*), COALESCE(SUM(amount), 0)
        FROM funding_events
        WHERE entity_id IN ({ph})
          AND event_type = 'REG_D_FILING'
          AND event_date >= ? AND event_date <= ?
    """, base_params).fetchone()
    regd_count, regd_capital = row

    # Contracts
    row = conn.execute(f"""
        SELECT COUNT(*), COALESCE(SUM(contract_value), 0)
        FROM contracts
        WHERE entity_id IN ({ph})
          AND award_date >= ? AND award_date <= ?
    """, base_params).fetchone()
    contract_count, contract_value = row

    # Unique active entities (any funding event or contract in period)
    fe_entities = conn.execute(f"""
        SELECT DISTINCT entity_id
        FROM funding_events
        WHERE entity_id IN ({ph})
          AND event_date >= ? AND event_date <= ?
    """, base_params).fetchall()

    c_entities = conn.execute(f"""
        SELECT DISTINCT entity_id
        FROM contracts
        WHERE entity_id IN ({ph})
          AND award_date >= ? AND award_date <= ?
    """, base_params).fetchall()

    active = set(r[0] for r in fe_entities) | set(r[0] for r in c_entities)

    return {
        "sbir_p1_count": sbir_p1_count,
        "sbir_p2_count": sbir_p2_count,
        "sbir_total_value": sbir_p1_value + sbir_p2_value,
        "regd_count": regd_count,
        "regd_capital": regd_capital,
        "contract_count": contract_count,
        "contract_value": contract_value,
        "unique_entities": len(active),
    }


def compute_quarterly(conn, entity_ids, quarters):
    """Compute per-quarter metrics for time series analysis."""
    results = []
    for q_label, q_start, q_end in quarters:
        m = compute_metrics(conn, entity_ids, q_start, q_end)
        m["quarter"] = q_label
        results.append(m)
    return results


def pct_change(baseline, response):
    """Calculate percentage change, handling zero baseline."""
    if baseline == 0:
        return None  # Cannot compute
    return (response - baseline) / baseline * 100


def fmt_pct(val):
    """Format percentage for display."""
    if val is None:
        return "N/A"
    return f"{val:+.1f}%"


def fmt_dollars(val):
    """Format dollar value in millions."""
    return f"${val / 1_000_000:.1f}M"


def fmt_int(val):
    """Format integer with commas."""
    return f"{val:,}"


def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))

    try:
        # === Section 2: Cohort Summary ===
        print("=" * 70)
        print("POLICY SIGNAL-RESPONSE PROOF OF CONCEPT")
        print("=" * 70)
        print()

        space_ids = get_cohort_ids(conn, ">=", SPACE_THRESHOLD)
        control_ids = get_control_ids(conn)

        print(f"Signal: {SIGNAL_NAME} ({SIGNAL_DATE})")
        print(f"Baseline period: {BASELINE_START} to {BASELINE_END} (36 months)")
        print(f"Response period: {RESPONSE_START} to {RESPONSE_END} (36 months)")
        print()
        print(f"Space cohort: {len(space_ids):,} entities (space_resilience >= {SPACE_THRESHOLD})")
        print(f"Control group: {len(control_ids):,} entities (STARTUP, space_resilience < {CONTROL_THRESHOLD})")
        print()

        # Top 10 space entities by score
        top10 = conn.execute("""
            SELECT canonical_name,
                   json_extract(policy_alignment, '$.scores.space_resilience') as score,
                   entity_type
            FROM entities
            WHERE json_extract(policy_alignment, '$.scores.space_resilience') >= ?
              AND merged_into_id IS NULL
              AND policy_alignment IS NOT NULL
            ORDER BY score DESC, canonical_name
            LIMIT 10
        """, (SPACE_THRESHOLD,)).fetchall()

        print("Top 10 space-aligned entities (sanity check):")
        print(f"  {'Name':<40} {'Score':>6}  {'Type':<10}")
        print(f"  {'-'*40} {'-'*6}  {'-'*10}")
        for name, score, etype in top10:
            print(f"  {name:<40} {score:>6.2f}  {etype:<10}")
        print()

        # === Section 3: Baseline vs Response Metrics ===
        print("-" * 70)
        print("COMPUTING METRICS...")
        print("-" * 70)
        print()

        space_baseline = compute_metrics(conn, space_ids, BASELINE_START, BASELINE_END)
        space_response = compute_metrics(conn, space_ids, RESPONSE_START, RESPONSE_END)
        control_baseline = compute_metrics(conn, control_ids, BASELINE_START, BASELINE_END)
        control_response = compute_metrics(conn, control_ids, RESPONSE_START, RESPONSE_END)

        # === Data coverage warnings ===
        warnings = []
        metric_labels_for_warning = {
            "sbir_p1_count": "SBIR Phase I (space baseline)",
            "sbir_p2_count": "SBIR Phase II (space baseline)",
            "regd_count": "Reg D Filings (space baseline)",
            "contract_count": "Contracts (space baseline)",
        }
        for key, label in metric_labels_for_warning.items():
            if space_baseline[key] < 10:
                warnings.append(f"  WARNING: {label} has only {space_baseline[key]} observations — interpret with caution")

        ctrl_labels = {
            "sbir_p1_count": "SBIR Phase I (control baseline)",
            "sbir_p2_count": "SBIR Phase II (control baseline)",
            "regd_count": "Reg D Filings (control baseline)",
            "contract_count": "Contracts (control baseline)",
        }
        for key, label in ctrl_labels.items():
            if control_baseline[key] < 10:
                warnings.append(f"  WARNING: {label} has only {control_baseline[key]} observations — interpret with caution")

        if warnings:
            print("DATA COVERAGE WARNINGS:")
            for w in warnings:
                print(w)
            print()

        # === Section 4: Delta Calculation ===
        metrics = [
            ("SBIR Phase I (count)", "sbir_p1_count", "count"),
            ("SBIR Phase II (count)", "sbir_p2_count", "count"),
            ("SBIR Total Value ($M)", "sbir_total_value", "dollars"),
            ("Reg D Filings (count)", "regd_count", "count"),
            ("Reg D Capital ($M)", "regd_capital", "dollars"),
            ("Contracts (count)", "contract_count", "count"),
            ("Contract Value ($M)", "contract_value", "dollars"),
            ("Unique Active Entities", "unique_entities", "count"),
        ]

        header = f"{'METRIC':<25} {'BASELINE':>12} {'RESPONSE':>12} {'DELTA':>10} {'CTRL_DELTA':>12} {'DIFFERENTIAL':>14}"
        print(header)
        print("-" * len(header))

        for label, key, fmt_type in metrics:
            sb = space_baseline[key]
            sr = space_response[key]
            cb = control_baseline[key]
            cr = control_response[key]

            space_delta = pct_change(sb, sr)
            ctrl_delta = pct_change(cb, cr)

            if space_delta is not None and ctrl_delta is not None:
                diff = space_delta - ctrl_delta
            else:
                diff = None

            if fmt_type == "dollars":
                sb_str = fmt_dollars(sb)
                sr_str = fmt_dollars(sr)
            else:
                sb_str = fmt_int(sb)
                sr_str = fmt_int(sr)

            print(f"{label:<25} {sb_str:>12} {sr_str:>12} {fmt_pct(space_delta):>10} {fmt_pct(ctrl_delta):>12} {fmt_pct(diff):>14}")

        print()

        # === Section 5: Quarterly Time Series ===
        print("-" * 70)
        print("QUARTERLY TIME SERIES")
        print("-" * 70)
        print()

        space_quarterly = compute_quarterly(conn, space_ids, QUARTERS)

        q_header = f"{'QUARTER':<10} {'SBIR_P1':>8} {'SBIR_P2':>8} {'REGD_CT':>8} {'REGD_$M':>10} {'CONTR_CT':>9} {'CONTR_$M':>11}"
        print("Space Cohort:")
        print(q_header)
        print("-" * len(q_header))
        for q in space_quarterly:
            print(f"{q['quarter']:<10} {q['sbir_p1_count']:>8,} {q['sbir_p2_count']:>8,} {q['regd_count']:>8,} {fmt_dollars(q['regd_capital']):>10} {q['contract_count']:>9,} {fmt_dollars(q['contract_value']):>11}")

        print()

        control_quarterly = compute_quarterly(conn, control_ids, QUARTERS)

        print("Control Group:")
        print(q_header)
        print("-" * len(q_header))
        for q in control_quarterly:
            print(f"{q['quarter']:<10} {q['sbir_p1_count']:>8,} {q['sbir_p2_count']:>8,} {q['regd_count']:>8,} {fmt_dollars(q['regd_capital']):>10} {q['contract_count']:>9,} {fmt_dollars(q['contract_value']):>11}")

        print()

        # === Lag Analysis ===
        print("-" * 70)
        print("TIMING / LAG ANALYSIS")
        print("-" * 70)
        print()

        # Signal quarter index: 2019-Q4 is index 11 (0-based)
        signal_q_idx = 11  # 2019-Q4

        timing_metrics = [
            ("Reg D Filings", "regd_count"),
            ("Reg D Capital", "regd_capital"),
            ("SBIR Phase I", "sbir_p1_count"),
            ("SBIR Phase II", "sbir_p2_count"),
            ("Contracts", "contract_count"),
            ("Contract Value", "contract_value"),
        ]

        # Calculate average baseline quarterly value for each metric
        for label, key in timing_metrics:
            baseline_vals = [space_quarterly[i][key] for i in range(signal_q_idx)]  # Q1 2017 through Q3 2019
            if baseline_vals:
                avg_baseline = sum(baseline_vals) / len(baseline_vals)
            else:
                avg_baseline = 0

            # Find first quarter after signal with value > 1.5x baseline average
            first_response_q = None
            peak_q = None
            peak_val = 0

            for i in range(signal_q_idx + 1, len(space_quarterly)):
                val = space_quarterly[i][key]
                if val > peak_val:
                    peak_val = val
                    peak_q = space_quarterly[i]["quarter"]
                if first_response_q is None and avg_baseline > 0 and val > avg_baseline * 1.5:
                    first_response_q = i
                elif first_response_q is None and avg_baseline == 0 and val > 0:
                    first_response_q = i

            if first_response_q is not None:
                quarters_lag = first_response_q - signal_q_idx
                print(f"  {label + ':':<25} First response Q+{quarters_lag} ({space_quarterly[first_response_q]['quarter']}), "
                      f"Peak: {peak_q} (val: {peak_val:,.0f})")
            else:
                peak_info = f", Peak: {peak_q} (val: {peak_val:,.0f})" if peak_q else ""
                print(f"  {label + ':':<25} No clear response detected (avg baseline: {avg_baseline:,.0f}){peak_info}")

        print()

        # === Section 6: Output Summary ===
        print("=" * 70)
        print("POLICY SIGNAL-RESPONSE PAIR — SUMMARY")
        print("=" * 70)
        print()
        print(f"Signal: {SIGNAL_NAME} ({SIGNAL_DATE})")
        print(f"Cohort: {len(space_ids):,} space-aligned entities (space_resilience >= {SPACE_THRESHOLD})")
        print(f"Control: {len(control_ids):,} non-space defense entities (space_resilience < {CONTROL_THRESHOLD})")
        print()

        # Reprint the delta table in summary
        print(header)
        print("-" * len(header))
        for label, key, fmt_type in metrics:
            sb = space_baseline[key]
            sr = space_response[key]
            cb = control_baseline[key]
            cr = control_response[key]
            space_delta = pct_change(sb, sr)
            ctrl_delta = pct_change(cb, cr)
            diff = (space_delta - ctrl_delta) if (space_delta is not None and ctrl_delta is not None) else None
            if fmt_type == "dollars":
                sb_str = fmt_dollars(sb)
                sr_str = fmt_dollars(sr)
            else:
                sb_str = fmt_int(sb)
                sr_str = fmt_int(sr)
            print(f"{label:<25} {sb_str:>12} {sr_str:>12} {fmt_pct(space_delta):>10} {fmt_pct(ctrl_delta):>12} {fmt_pct(diff):>14}")

        print()

        # Auto-generated interpretation
        print("INTERPRETATION:")
        parts = []

        # Reg D capital differential (strongest signal in our data)
        regd_cap_space_d = pct_change(space_baseline["regd_capital"], space_response["regd_capital"])
        regd_cap_ctrl_d = pct_change(control_baseline["regd_capital"], control_response["regd_capital"])
        if regd_cap_space_d is not None and regd_cap_ctrl_d is not None:
            cap_diff = regd_cap_space_d - regd_cap_ctrl_d
            if cap_diff > 100:
                parts.append(f"Reg D capital raised shows a strong space-specific response ({fmt_pct(cap_diff)} differential vs control), "
                             f"suggesting private investors disproportionately funded space companies post-signal.")
            elif cap_diff > 0:
                parts.append(f"Reg D capital shows modest space-specific outperformance ({fmt_pct(cap_diff)} differential).")
            else:
                parts.append("Reg D capital growth was not space-specific — general defense VC boom explains both cohorts.")

        # Reg D filing count
        regd_space_d = pct_change(space_baseline["regd_count"], space_response["regd_count"])
        regd_ctrl_d = pct_change(control_baseline["regd_count"], control_response["regd_count"])
        if regd_space_d is not None and regd_ctrl_d is not None:
            regd_diff = regd_space_d - regd_ctrl_d
            if regd_diff < 0:
                parts.append(f"Reg D filing count grew faster in the control group ({fmt_pct(regd_diff)} differential), "
                             "but space deals were larger on average — quality over quantity.")

        # SBIR
        sbir_space_d = pct_change(space_baseline["sbir_p1_count"], space_response["sbir_p1_count"])
        sbir_ctrl_d = pct_change(control_baseline["sbir_p1_count"], control_response["sbir_p1_count"])
        if sbir_space_d is not None and sbir_ctrl_d is not None:
            sbir_diff = sbir_space_d - sbir_ctrl_d
            if sbir_diff > 20:
                parts.append(f"SBIR Phase I awards show disproportionate space-sector growth ({fmt_pct(sbir_diff)} differential).")
            elif abs(sbir_diff) <= 20:
                parts.append("SBIR Phase I growth was comparable across space and non-space defense sectors, "
                             "consistent with SBIR being budget-driven rather than policy-signal-driven.")
            else:
                parts.append(f"SBIR Phase I grew faster in non-space defense ({fmt_pct(sbir_diff)} differential).")

        for p in parts:
            print(f"  {p}")

        if not parts:
            print("  Insufficient data for automated interpretation.")

        print()
        print("=" * 70)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
