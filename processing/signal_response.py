"""
Signal-Response Benchmark Framework

Generalized framework for measuring how government policy signals produce
measurable private market responses. Evolved from the Space Force PoC
(scripts/policy_signal_poc.py) into a reusable, parameterized engine.

Core idea: define a policy signal event, a treatment cohort (companies
aligned to the signal), a control group, baseline/response periods, and
measure differential market activity across SBIR, Reg D, and contracts.

Usage:
    from processing.signal_response import SignalResponseBenchmark, BenchmarkConfig

    config = BenchmarkConfig(
        signal_name="US Space Force Establishment",
        signal_date="2019-12-20",
        cohort_score="space_resilience",
        cohort_threshold=0.5,
        control_threshold=0.3,
        baseline_start="2017-01-01",
        baseline_end="2019-12-31",
        response_start="2020-01-01",
        response_end="2022-12-31",
    )

    benchmark = SignalResponseBenchmark(db_path)
    results = benchmark.run(config)
    benchmark.print_report(results)
"""

import json
import sqlite3
import statistics
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Optional


@dataclass
class BenchmarkConfig:
    """Configuration for a signal-response benchmark."""

    # Signal identification
    signal_name: str
    signal_date: str  # YYYY-MM-DD

    # Cohort definition — which policy_alignment score to use
    cohort_score: str  # Key in policy_alignment.scores (e.g., "space_resilience")
    cohort_threshold: float = 0.5  # Entities with score >= this are treatment
    control_threshold: float = 0.3  # Entities with score < this are control

    # Optional: filter cohort by multiple scores (OR logic)
    # e.g., ["autonomous_systems", "electronic_warfare", "jadc2"]
    cohort_scores_any: list[str] = field(default_factory=list)

    # Optional: additional SQL filter for cohort (e.g., SBIR title keyword)
    cohort_sbir_keywords: list[str] = field(default_factory=list)

    # Time periods
    baseline_start: str = ""  # YYYY-MM-DD
    baseline_end: str = ""
    response_start: str = ""
    response_end: str = ""

    # Control group settings
    control_entity_type: str = "STARTUP"  # Entity type for control group

    # Analysis settings
    bootstrap_iterations: int = 1000
    response_threshold_multiplier: float = 1.5  # Detect first response at N * baseline avg

    def __post_init__(self):
        # Default: use single score if cohort_scores_any not specified
        if not self.cohort_scores_any:
            self.cohort_scores_any = [self.cohort_score]


@dataclass
class PeriodMetrics:
    """Metrics for a single period (baseline or response)."""
    sbir_p1_count: int = 0
    sbir_p2_count: int = 0
    sbir_total_value: float = 0
    regd_count: int = 0
    regd_capital: float = 0
    contract_count: int = 0
    contract_value: float = 0
    unique_entities: int = 0


@dataclass
class QuarterMetrics:
    """Metrics for a single quarter."""
    quarter: str = ""
    sbir_p1_count: int = 0
    sbir_p2_count: int = 0
    sbir_total_value: float = 0
    regd_count: int = 0
    regd_capital: float = 0
    contract_count: int = 0
    contract_value: float = 0
    unique_entities: int = 0


@dataclass
class TimingResult:
    """Timing analysis for a single metric."""
    metric_name: str
    first_response_quarter: Optional[str] = None
    quarters_lag: Optional[int] = None
    peak_quarter: Optional[str] = None
    peak_value: float = 0
    baseline_avg: float = 0


@dataclass
class BootstrapCI:
    """Bootstrap confidence interval for a differential."""
    metric_name: str
    observed_differential: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    p_value_approx: Optional[float] = None  # Fraction of bootstrap samples <= 0


@dataclass
class BenchmarkResults:
    """Complete results from a signal-response benchmark run."""
    config: BenchmarkConfig
    cohort_size: int = 0
    control_size: int = 0

    # Period metrics
    cohort_baseline: PeriodMetrics = field(default_factory=PeriodMetrics)
    cohort_response: PeriodMetrics = field(default_factory=PeriodMetrics)
    control_baseline: PeriodMetrics = field(default_factory=PeriodMetrics)
    control_response: PeriodMetrics = field(default_factory=PeriodMetrics)

    # Time series
    cohort_quarterly: list[QuarterMetrics] = field(default_factory=list)
    control_quarterly: list[QuarterMetrics] = field(default_factory=list)

    # Timing analysis
    timing: list[TimingResult] = field(default_factory=list)

    # Bootstrap confidence intervals
    confidence_intervals: list[BootstrapCI] = field(default_factory=list)

    # Data coverage warnings
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize results to dict for JSON export."""
        return asdict(self)

    def to_json(self, path: Path):
        """Write results to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


def _generate_quarters(start_year: int, end_year: int) -> list[tuple[str, str, str]]:
    """Generate (label, start_date, end_date) tuples for quarters in range."""
    quarters = []
    for year in range(start_year, end_year + 1):
        for q in range(1, 5):
            q_start_month = (q - 1) * 3 + 1
            q_end_month = q * 3
            if q_end_month in (3, 12):
                q_end_day = 31
            elif q_end_month in (6, 9):
                q_end_day = 30
            else:
                q_end_day = 28
            q_start = f"{year}-{q_start_month:02d}-01"
            q_end = f"{year}-{q_end_month:02d}-{q_end_day:02d}"
            quarters.append((f"{year}-Q{q}", q_start, q_end))
    return quarters


def _placeholders(ids: list[str]) -> str:
    """Generate SQL placeholders."""
    return ",".join("?" * len(ids))


class SignalResponseBenchmark:
    """
    Runs a signal-response benchmark: measures whether a policy signal
    produced a differential market response in a treatment cohort vs control.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _get_cohort_ids(self, conn: sqlite3.Connection, config: BenchmarkConfig) -> list[str]:
        """Get entity IDs for the treatment cohort."""
        all_ids = set()

        for score_name in config.cohort_scores_any:
            cursor = conn.execute("""
                SELECT id
                FROM entities
                WHERE json_extract(policy_alignment, '$.scores.' || ?) >= ?
                  AND merged_into_id IS NULL
                  AND policy_alignment IS NOT NULL
            """, (score_name, config.cohort_threshold))
            for row in cursor.fetchall():
                all_ids.add(row[0])

        # Optional: filter by SBIR keywords (requires matching via sbir_embeddings)
        if config.cohort_sbir_keywords and all_ids:
            keyword_ids = set()
            ph = _placeholders(list(all_ids))
            for kw in config.cohort_sbir_keywords:
                cursor = conn.execute(f"""
                    SELECT DISTINCT se.entity_id
                    FROM sbir_embeddings se
                    WHERE se.entity_id IN ({ph})
                      AND LOWER(se.award_title) LIKE ?
                """, list(all_ids) + [f"%{kw.lower()}%"])
                for row in cursor.fetchall():
                    keyword_ids.add(row[0])
            all_ids = keyword_ids

        return list(all_ids)

    def _get_control_ids(self, conn: sqlite3.Connection, config: BenchmarkConfig) -> list[str]:
        """Get control group: entities with all cohort scores below threshold."""
        # Build condition: ALL cohort scores < control_threshold
        conditions = []
        for score_name in config.cohort_scores_any:
            conditions.append(
                f"(json_extract(policy_alignment, '$.scores.{score_name}') IS NULL "
                f"OR json_extract(policy_alignment, '$.scores.{score_name}') < ?)"
            )

        where_clause = " AND ".join(conditions)
        params = [config.control_threshold] * len(config.cohort_scores_any)

        cursor = conn.execute(f"""
            SELECT id
            FROM entities
            WHERE {where_clause}
              AND merged_into_id IS NULL
              AND policy_alignment IS NOT NULL
              AND entity_type = ?
        """, params + [config.control_entity_type])

        return [row[0] for row in cursor.fetchall()]

    def _compute_metrics(
        self, conn: sqlite3.Connection, entity_ids: list[str],
        date_start: str, date_end: str,
    ) -> PeriodMetrics:
        """Compute all metrics for a cohort in a date range."""
        if not entity_ids:
            return PeriodMetrics()

        ph = _placeholders(entity_ids)
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

        # Unique active entities
        fe_entities = conn.execute(f"""
            SELECT DISTINCT entity_id FROM funding_events
            WHERE entity_id IN ({ph}) AND event_date >= ? AND event_date <= ?
        """, base_params).fetchall()

        c_entities = conn.execute(f"""
            SELECT DISTINCT entity_id FROM contracts
            WHERE entity_id IN ({ph}) AND award_date >= ? AND award_date <= ?
        """, base_params).fetchall()

        active = set(r[0] for r in fe_entities) | set(r[0] for r in c_entities)

        return PeriodMetrics(
            sbir_p1_count=sbir_p1_count,
            sbir_p2_count=sbir_p2_count,
            sbir_total_value=float(sbir_p1_value + sbir_p2_value),
            regd_count=regd_count,
            regd_capital=float(regd_capital),
            contract_count=contract_count,
            contract_value=float(contract_value),
            unique_entities=len(active),
        )

    def _compute_quarterly(
        self, conn: sqlite3.Connection, entity_ids: list[str],
        quarters: list[tuple[str, str, str]],
    ) -> list[QuarterMetrics]:
        """Compute per-quarter metrics."""
        results = []
        for q_label, q_start, q_end in quarters:
            m = self._compute_metrics(conn, entity_ids, q_start, q_end)
            results.append(QuarterMetrics(
                quarter=q_label,
                sbir_p1_count=m.sbir_p1_count,
                sbir_p2_count=m.sbir_p2_count,
                sbir_total_value=m.sbir_total_value,
                regd_count=m.regd_count,
                regd_capital=m.regd_capital,
                contract_count=m.contract_count,
                contract_value=m.contract_value,
                unique_entities=m.unique_entities,
            ))
        return results

    def _analyze_timing(
        self, quarterly: list[QuarterMetrics], signal_quarter_idx: int,
        threshold_multiplier: float,
    ) -> list[TimingResult]:
        """Analyze response timing for each metric."""
        timing_metrics = [
            ("Reg D Filings", "regd_count"),
            ("Reg D Capital", "regd_capital"),
            ("SBIR Phase I", "sbir_p1_count"),
            ("SBIR Phase II", "sbir_p2_count"),
            ("Contracts", "contract_count"),
            ("Contract Value", "contract_value"),
        ]

        results = []
        for label, key in timing_metrics:
            # Average baseline quarterly value
            baseline_vals = [getattr(quarterly[i], key) for i in range(signal_quarter_idx)]
            avg_baseline = statistics.mean(baseline_vals) if baseline_vals else 0

            first_response_q = None
            peak_q = None
            peak_val = 0

            for i in range(signal_quarter_idx + 1, len(quarterly)):
                val = getattr(quarterly[i], key)
                if val > peak_val:
                    peak_val = val
                    peak_q = quarterly[i].quarter
                if first_response_q is None:
                    if avg_baseline > 0 and val > avg_baseline * threshold_multiplier:
                        first_response_q = i
                    elif avg_baseline == 0 and val > 0:
                        first_response_q = i

            result = TimingResult(
                metric_name=label,
                baseline_avg=avg_baseline,
                peak_quarter=peak_q,
                peak_value=peak_val,
            )

            if first_response_q is not None:
                result.first_response_quarter = quarterly[first_response_q].quarter
                result.quarters_lag = first_response_q - signal_quarter_idx

            results.append(result)

        return results

    def _bootstrap_confidence_intervals(
        self, conn: sqlite3.Connection,
        cohort_ids: list[str], control_ids: list[str],
        config: BenchmarkConfig, n_iterations: int,
    ) -> list[BootstrapCI]:
        """
        Bootstrap confidence intervals on the cohort-vs-control differential.

        Resamples entity IDs within each group to estimate variance of the
        percentage-change differential.
        """
        import random

        metric_keys = [
            ("SBIR Phase I", "sbir_p1_count"),
            ("SBIR Phase II", "sbir_p2_count"),
            ("Reg D Filings", "regd_count"),
            ("Reg D Capital", "regd_capital"),
            ("Contracts", "contract_count"),
            ("Contract Value", "contract_value"),
        ]

        # Compute observed differentials
        observed = {}
        cb = self._compute_metrics(conn, cohort_ids, config.baseline_start, config.baseline_end)
        cr = self._compute_metrics(conn, cohort_ids, config.response_start, config.response_end)
        ctb = self._compute_metrics(conn, control_ids, config.baseline_start, config.baseline_end)
        ctr = self._compute_metrics(conn, control_ids, config.response_start, config.response_end)

        for label, key in metric_keys:
            cohort_b = getattr(cb, key)
            cohort_r = getattr(cr, key)
            ctrl_b = getattr(ctb, key)
            ctrl_r = getattr(ctr, key)

            cohort_delta = ((cohort_r - cohort_b) / cohort_b * 100) if cohort_b > 0 else None
            ctrl_delta = ((ctrl_r - ctrl_b) / ctrl_b * 100) if ctrl_b > 0 else None

            if cohort_delta is not None and ctrl_delta is not None:
                observed[key] = cohort_delta - ctrl_delta
            else:
                observed[key] = None

        # Bootstrap: resample entities and recompute differentials
        bootstrap_diffs = {key: [] for _, key in metric_keys}

        for _ in range(n_iterations):
            # Resample with replacement
            boot_cohort = random.choices(cohort_ids, k=len(cohort_ids))
            boot_control = random.choices(control_ids, k=len(control_ids))

            bcb = self._compute_metrics(conn, boot_cohort, config.baseline_start, config.baseline_end)
            bcr = self._compute_metrics(conn, boot_cohort, config.response_start, config.response_end)
            bctb = self._compute_metrics(conn, boot_control, config.baseline_start, config.baseline_end)
            bctr = self._compute_metrics(conn, boot_control, config.response_start, config.response_end)

            for _, key in metric_keys:
                c_b = getattr(bcb, key)
                c_r = getattr(bcr, key)
                ct_b = getattr(bctb, key)
                ct_r = getattr(bctr, key)

                c_delta = ((c_r - c_b) / c_b * 100) if c_b > 0 else None
                ct_delta = ((ct_r - ct_b) / ct_b * 100) if ct_b > 0 else None

                if c_delta is not None and ct_delta is not None:
                    bootstrap_diffs[key].append(c_delta - ct_delta)

        # Compute CIs
        results = []
        for label, key in metric_keys:
            diffs = sorted(bootstrap_diffs[key])
            ci = BootstrapCI(
                metric_name=label,
                observed_differential=observed[key],
            )

            if len(diffs) >= 20:
                ci.ci_lower = diffs[int(len(diffs) * 0.025)]
                ci.ci_upper = diffs[int(len(diffs) * 0.975)]
                # Approximate p-value: fraction of bootstrap diffs <= 0
                ci.p_value_approx = sum(1 for d in diffs if d <= 0) / len(diffs)

            results.append(ci)

        return results

    def run(self, config: BenchmarkConfig) -> BenchmarkResults:
        """Run a complete signal-response benchmark."""
        conn = sqlite3.connect(str(self.db_path))
        results = BenchmarkResults(config=config)

        try:
            # Build cohorts
            cohort_ids = self._get_cohort_ids(conn, config)
            control_ids = self._get_control_ids(conn, config)
            results.cohort_size = len(cohort_ids)
            results.control_size = len(control_ids)

            if not cohort_ids:
                results.warnings.append("EMPTY COHORT: No entities matched the cohort criteria")
                return results

            if not control_ids:
                results.warnings.append("EMPTY CONTROL: No entities matched the control criteria")

            # Compute period metrics
            results.cohort_baseline = self._compute_metrics(
                conn, cohort_ids, config.baseline_start, config.baseline_end)
            results.cohort_response = self._compute_metrics(
                conn, cohort_ids, config.response_start, config.response_end)
            results.control_baseline = self._compute_metrics(
                conn, control_ids, config.baseline_start, config.baseline_end)
            results.control_response = self._compute_metrics(
                conn, control_ids, config.response_start, config.response_end)

            # Data coverage warnings
            for key, label in [
                ("sbir_p1_count", "SBIR Phase I"), ("sbir_p2_count", "SBIR Phase II"),
                ("regd_count", "Reg D Filings"), ("contract_count", "Contracts"),
            ]:
                val = getattr(results.cohort_baseline, key)
                if val < 10:
                    results.warnings.append(
                        f"LOW DATA: {label} (cohort baseline) has only {val} observations"
                    )
                cval = getattr(results.control_baseline, key)
                if cval < 10:
                    results.warnings.append(
                        f"LOW DATA: {label} (control baseline) has only {cval} observations"
                    )

            # Quarterly time series
            baseline_year = int(config.baseline_start[:4])
            response_year = int(config.response_end[:4])
            quarters = _generate_quarters(baseline_year, response_year)

            results.cohort_quarterly = self._compute_quarterly(conn, cohort_ids, quarters)
            results.control_quarterly = self._compute_quarterly(conn, control_ids, quarters)

            # Timing analysis
            signal_date = config.signal_date
            signal_year = int(signal_date[:4])
            signal_month = int(signal_date[5:7])
            signal_q = (signal_month - 1) // 3 + 1
            signal_q_label = f"{signal_year}-Q{signal_q}"

            signal_q_idx = None
            for i, qm in enumerate(results.cohort_quarterly):
                if qm.quarter == signal_q_label:
                    signal_q_idx = i
                    break

            if signal_q_idx is not None:
                results.timing = self._analyze_timing(
                    results.cohort_quarterly, signal_q_idx,
                    config.response_threshold_multiplier,
                )

            # Bootstrap confidence intervals
            if config.bootstrap_iterations > 0 and cohort_ids and control_ids:
                results.confidence_intervals = self._bootstrap_confidence_intervals(
                    conn, cohort_ids, control_ids, config, config.bootstrap_iterations,
                )

        finally:
            conn.close()

        return results


# ============================================================================
# Reporting
# ============================================================================

def pct_change(baseline: float, response: float) -> Optional[float]:
    """Calculate percentage change."""
    if baseline == 0:
        return None
    return (response - baseline) / baseline * 100


def fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    return f"{val:+.1f}%"


def fmt_dollars(val: float) -> str:
    return f"${val / 1_000_000:.1f}M"


def fmt_int(val: int | float) -> str:
    return f"{int(val):,}"


def print_report(results: BenchmarkResults):
    """Print a formatted benchmark report to stdout."""
    config = results.config

    print("=" * 78)
    print("SIGNAL-RESPONSE BENCHMARK")
    print("=" * 78)
    print()
    print(f"Signal: {config.signal_name} ({config.signal_date})")
    print(f"Cohort scores: {', '.join(config.cohort_scores_any)} >= {config.cohort_threshold}")
    if config.cohort_sbir_keywords:
        print(f"SBIR keywords: {', '.join(config.cohort_sbir_keywords)}")
    print(f"Baseline: {config.baseline_start} to {config.baseline_end}")
    print(f"Response: {config.response_start} to {config.response_end}")
    print()
    print(f"Treatment cohort: {results.cohort_size:,} entities")
    print(f"Control group:    {results.control_size:,} entities ({config.control_entity_type})")
    print()

    # Warnings
    if results.warnings:
        print("DATA COVERAGE WARNINGS:")
        for w in results.warnings:
            print(f"  {w}")
        print()

    # Delta table
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
        sb = getattr(results.cohort_baseline, key)
        sr = getattr(results.cohort_response, key)
        cb = getattr(results.control_baseline, key)
        cr = getattr(results.control_response, key)

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

    # Confidence intervals
    if results.confidence_intervals:
        print("-" * 78)
        print("BOOTSTRAP CONFIDENCE INTERVALS (95%)")
        print("-" * 78)
        print()
        ci_header = f"{'METRIC':<25} {'DIFFERENTIAL':>14} {'95% CI':>22} {'p-value':>10}"
        print(ci_header)
        print("-" * len(ci_header))

        for ci in results.confidence_intervals:
            diff_str = fmt_pct(ci.observed_differential)
            if ci.ci_lower is not None and ci.ci_upper is not None:
                ci_str = f"[{ci.ci_lower:+.1f}%, {ci.ci_upper:+.1f}%]"
            else:
                ci_str = "N/A"
            p_str = f"{ci.p_value_approx:.3f}" if ci.p_value_approx is not None else "N/A"
            print(f"{ci.metric_name:<25} {diff_str:>14} {ci_str:>22} {p_str:>10}")

        print()

    # Quarterly time series
    if results.cohort_quarterly:
        print("-" * 78)
        print("QUARTERLY TIME SERIES — Treatment Cohort")
        print("-" * 78)
        print()

        q_header = f"{'QUARTER':<10} {'SBIR_P1':>8} {'SBIR_P2':>8} {'REGD_CT':>8} {'REGD_$M':>10} {'CONTR_CT':>9} {'CONTR_$M':>11}"
        print(q_header)
        print("-" * len(q_header))
        for q in results.cohort_quarterly:
            print(
                f"{q.quarter:<10} {q.sbir_p1_count:>8,} {q.sbir_p2_count:>8,} "
                f"{q.regd_count:>8,} {fmt_dollars(q.regd_capital):>10} "
                f"{q.contract_count:>9,} {fmt_dollars(q.contract_value):>11}"
            )

        print()
        print("Control Group:")
        print(q_header)
        print("-" * len(q_header))
        for q in results.control_quarterly:
            print(
                f"{q.quarter:<10} {q.sbir_p1_count:>8,} {q.sbir_p2_count:>8,} "
                f"{q.regd_count:>8,} {fmt_dollars(q.regd_capital):>10} "
                f"{q.contract_count:>9,} {fmt_dollars(q.contract_value):>11}"
            )

        print()

    # Timing analysis
    if results.timing:
        print("-" * 78)
        print("TIMING / LAG ANALYSIS")
        print("-" * 78)
        print()

        for t in results.timing:
            if t.first_response_quarter:
                print(
                    f"  {t.metric_name + ':':<25} First response Q+{t.quarters_lag} "
                    f"({t.first_response_quarter}), Peak: {t.peak_quarter} "
                    f"(val: {t.peak_value:,.0f})"
                )
            else:
                peak_info = f", Peak: {t.peak_quarter} (val: {t.peak_value:,.0f})" if t.peak_quarter else ""
                print(
                    f"  {t.metric_name + ':':<25} No clear response detected "
                    f"(avg baseline: {t.baseline_avg:,.0f}){peak_info}"
                )

        print()

    # Interpretation
    print("=" * 78)
    print("INTERPRETATION")
    print("=" * 78)
    print()

    parts = _generate_interpretation(results)
    for p in parts:
        print(f"  {p}")
    if not parts:
        print("  Insufficient data for automated interpretation.")

    print()
    print("=" * 78)


def _generate_interpretation(results: BenchmarkResults) -> list[str]:
    """Auto-generate interpretation text from results."""
    parts = []
    config = results.config

    # Reg D capital differential
    regd_cap_cohort_d = pct_change(
        results.cohort_baseline.regd_capital, results.cohort_response.regd_capital)
    regd_cap_ctrl_d = pct_change(
        results.control_baseline.regd_capital, results.control_response.regd_capital)

    if regd_cap_cohort_d is not None and regd_cap_ctrl_d is not None:
        cap_diff = regd_cap_cohort_d - regd_cap_ctrl_d
        if cap_diff > 100:
            parts.append(
                f"Reg D capital shows a strong cohort-specific response "
                f"({fmt_pct(cap_diff)} differential vs control), suggesting "
                f"private investors disproportionately funded aligned companies "
                f"after {config.signal_name}."
            )
        elif cap_diff > 0:
            parts.append(
                f"Reg D capital shows modest cohort outperformance "
                f"({fmt_pct(cap_diff)} differential)."
            )
        else:
            parts.append(
                f"Reg D capital growth was not cohort-specific — general "
                f"defense VC activity explains both groups."
            )

    # SBIR differential
    sbir_cohort_d = pct_change(
        results.cohort_baseline.sbir_p1_count, results.cohort_response.sbir_p1_count)
    sbir_ctrl_d = pct_change(
        results.control_baseline.sbir_p1_count, results.control_response.sbir_p1_count)

    if sbir_cohort_d is not None and sbir_ctrl_d is not None:
        sbir_diff = sbir_cohort_d - sbir_ctrl_d
        if sbir_diff > 20:
            parts.append(
                f"SBIR Phase I awards show disproportionate cohort growth "
                f"({fmt_pct(sbir_diff)} differential)."
            )
        elif abs(sbir_diff) <= 20:
            parts.append(
                f"SBIR Phase I growth was comparable across cohort and control, "
                f"consistent with SBIR being budget-driven rather than policy-signal-driven."
            )
        else:
            parts.append(
                f"SBIR Phase I grew faster in the control group "
                f"({fmt_pct(sbir_diff)} differential)."
            )

    # Contract differential
    contract_cohort_d = pct_change(
        results.cohort_baseline.contract_count, results.cohort_response.contract_count)
    contract_ctrl_d = pct_change(
        results.control_baseline.contract_count, results.control_response.contract_count)

    if contract_cohort_d is not None and contract_ctrl_d is not None:
        contract_diff = contract_cohort_d - contract_ctrl_d
        if contract_diff > 20:
            parts.append(
                f"Contract activity shows cohort-specific acceleration "
                f"({fmt_pct(contract_diff)} differential), suggesting "
                f"production follow-through from the policy signal."
            )

    # Timing summary
    regd_timing = next((t for t in results.timing if t.metric_name == "Reg D Filings"), None)
    contract_timing = next((t for t in results.timing if t.metric_name == "Contracts"), None)

    if regd_timing and regd_timing.quarters_lag is not None:
        parts.append(
            f"Timing: Reg D response detected at Q+{regd_timing.quarters_lag} "
            f"({regd_timing.first_response_quarter})"
            + (f", contracts at Q+{contract_timing.quarters_lag} "
               f"({contract_timing.first_response_quarter})"
               if contract_timing and contract_timing.quarters_lag is not None else "")
            + "."
        )

    # CI summary
    regd_ci = next((ci for ci in results.confidence_intervals
                     if ci.metric_name == "Reg D Capital"), None)
    if regd_ci and regd_ci.p_value_approx is not None:
        if regd_ci.p_value_approx < 0.05:
            parts.append(
                f"The Reg D capital differential is statistically significant "
                f"(p={regd_ci.p_value_approx:.3f}, 95% CI [{regd_ci.ci_lower:+.1f}%, "
                f"{regd_ci.ci_upper:+.1f}%])."
            )
        elif regd_ci.p_value_approx < 0.10:
            parts.append(
                f"The Reg D capital differential is marginally significant "
                f"(p={regd_ci.p_value_approx:.3f})."
            )
        else:
            parts.append(
                f"The Reg D capital differential is not statistically significant "
                f"(p={regd_ci.p_value_approx:.3f}). More data may be needed."
            )

    return parts


# ============================================================================
# Predefined Benchmark Configurations
# ============================================================================

BENCHMARKS = {
    "space_force": BenchmarkConfig(
        signal_name="US Space Force Establishment",
        signal_date="2019-12-20",
        cohort_score="space_resilience",
        cohort_threshold=0.5,
        control_threshold=0.3,
        baseline_start="2017-01-01",
        baseline_end="2019-12-31",
        response_start="2020-01-01",
        response_end="2022-12-31",
    ),

    "nds_2018": BenchmarkConfig(
        signal_name="2018 National Defense Strategy — Great Power Competition",
        signal_date="2018-01-19",
        cohort_score="autonomous_systems",  # Primary score
        cohort_scores_any=["autonomous_systems", "electronic_warfare", "jadc2"],
        cohort_threshold=0.5,
        control_threshold=0.3,
        baseline_start="2016-01-01",
        baseline_end="2018-01-31",
        response_start="2018-02-01",
        response_end="2021-12-31",
    ),

    "ukraine_drones_2022": BenchmarkConfig(
        signal_name="Post-Ukraine Drone/Autonomous Systems Surge",
        signal_date="2022-02-24",
        cohort_score="autonomous_systems",
        cohort_scores_any=["autonomous_systems"],
        cohort_threshold=0.5,
        control_threshold=0.3,
        cohort_sbir_keywords=["drone", "uav", "uas", "unmanned", "counter-uas", "suas"],
        baseline_start="2020-01-01",
        baseline_end="2022-02-28",
        response_start="2022-03-01",
        response_end="2024-12-31",
    ),
}
