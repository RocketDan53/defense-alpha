#!/usr/bin/env bash
# =============================================================================
# Aperture Signals — Full Rescore Pipeline
# =============================================================================
# Machine: Apple M5, 24GB RAM
# Database: defense_alpha.db (~243MB, SQLite)
# Estimated runtime: ~3-4 hours total (mostly API wait time)
#
# PHASE 1: Local-only processing (no API, no network) — ~15 min
# PHASE 2: New signal detector implementation — ~5 min
# PHASE 3: API-dependent classification + policy scoring — ~2.5 hours
# PHASE 4: Local rescore with enriched data — ~10 min
# PHASE 5: Validation — ~5 min
#
# Usage:
#   chmod +x scripts/full_rescore.sh
#   cd ~/projects/defense-alpha && source venv/bin/activate
#   ./scripts/full_rescore.sh [--skip-api] [--skip-classify] [--phase N]
#
# Options:
#   --skip-api       Run local phases only (1, 2, 4, 5), skip classification/policy
#   --skip-classify  Skip classification, only run policy alignment on already-classified
#   --phase N        Start from phase N (for resuming after interruption)
#   --enrich         Run batch enrichment (Phase 2.5) on top 200 priority entities
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Parse arguments
SKIP_API=false
SKIP_CLASSIFY=false
START_PHASE=1
ENRICH=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-api) SKIP_API=true; shift ;;
        --skip-classify) SKIP_CLASSIFY=true; shift ;;
        --phase) START_PHASE=$2; shift 2 ;;
        --enrich) ENRICH=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Logging
LOG_DIR="data/pipeline_runs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/full_rescore_${TIMESTAMP}.log"

log() {
    local msg="[$(date '+%H:%M:%S')] $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

run_step() {
    local step_name="$1"
    shift
    log "  START: $step_name"
    local start_time=$(date +%s)
    if "$@" >> "$LOG_FILE" 2>&1; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log "  DONE:  $step_name (${duration}s)"
    else
        local exit_code=$?
        log "  FAILED: $step_name (exit code $exit_code)"
        log "  Check $LOG_FILE for details"
        echo ""
        echo "Step failed: $step_name"
        echo "Continue anyway? (y/n)"
        read -r response
        if [[ "$response" != "y" ]]; then
            exit 1
        fi
    fi
}

# Pre-flight checks
log "============================================"
log "Aperture Signals — Full Rescore Pipeline"
log "============================================"
log "Machine: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'Unknown')"
log "RAM: $(sysctl -n hw.memsize 2>/dev/null | awk '{print $0/1073741824 " GB"}' || echo 'Unknown')"
log "Python: $(python3 --version)"
log "Database: $(ls -lh data/defense_alpha.db | awk '{print $5}')"
log "Log file: $LOG_FILE"
log ""

# Verify database exists
if [[ ! -f "data/defense_alpha.db" ]]; then
    log "ERROR: data/defense_alpha.db not found"
    exit 1
fi

# Verify venv is active
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    log "WARNING: No virtual environment detected. Activating..."
    source venv/bin/activate
fi

# Backup database before rescore
log "Backing up database..."
cp data/defense_alpha.db "data/defense_alpha_backup_${TIMESTAMP}.db"
log "Backup: data/defense_alpha_backup_${TIMESTAMP}.db"
log ""

# =============================================================================
# PHASE 1: Local-only processing (no API needed)
# =============================================================================
# Everything here runs on CPU with no network calls.
# M5 + 24GB RAM handles all of this comfortably.
# Embedding model (MiniLM-L6-v2) is ~80MB in memory.
# =============================================================================

if [[ $START_PHASE -le 1 ]]; then
    log "============================================"
    log "PHASE 1: Local Processing (no API needed)"
    log "============================================"
    log ""

    # Step 1.1: Database integrity check
    log "Step 1.1: Database integrity check"
    run_step "SQLite integrity check" python3 -c "
import sqlite3
conn = sqlite3.connect('data/defense_alpha.db')
result = conn.execute('PRAGMA integrity_check').fetchone()
print(f'Integrity: {result[0]}')
assert result[0] == 'ok', f'Database integrity check failed: {result[0]}'

# Entity counts
for etype in ['STARTUP', 'PRIME', 'NON_DEFENSE', 'RESEARCH']:
    count = conn.execute('SELECT COUNT(*) FROM entities WHERE entity_type = ?', (etype,)).fetchone()[0]
    print(f'  {etype}: {count}')

# Table counts
for table in ['contracts', 'funding_events', 'signals', 'outcome_events', 'sbir_embeddings', 'relationships']:
    count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'  {table}: {count}')

conn.close()
print('Database OK')
"
    log ""

    # Step 1.2: Regenerate SBIR embeddings (local model, CPU)
    # MiniLM-L6-v2 is ~80MB RAM, 27K titles takes ~2-3 min on M5
    log "Step 1.2: Regenerate SBIR embeddings"
    run_step "SBIR embeddings" python3 scripts/find_similar.py --embed
    log ""

    # Step 1.3: Run signal detection (all 15 existing types)
    # Pure SQL + Python logic, no API calls
    log "Step 1.3: Signal detection (15 existing types)"
    run_step "Signal detection" python3 scripts/detect_signals.py --all
    log ""

    # Step 1.4: Calculate composite scores with freshness decay
    log "Step 1.4: Composite scoring"
    run_step "Composite scores" python3 scripts/calculate_composite_scores.py --all --persist
    log ""

    # Step 1.5: Run outcome tracking
    log "Step 1.5: Outcome tracking"
    run_step "Outcome tracking" python3 scripts/track_outcomes.py --since 2024-01-01
    log ""

    # Step 1.6: Rebuild knowledge graph
    log "Step 1.6: Knowledge graph materialization"
    run_step "Knowledge graph" python3 scripts/build_graph.py --materialize
    log ""

    # Step 1.7: Database stats after Phase 1
    log "Step 1.7: Post-Phase-1 stats"
    run_step "Stats check" python3 -c "
import sqlite3
conn = sqlite3.connect('data/defense_alpha.db')
conn.row_factory = sqlite3.Row

signals = conn.execute('SELECT COUNT(*) as cnt FROM signals WHERE status = \"ACTIVE\"').fetchone()['cnt']
print(f'Active signals: {signals}')

# Signal type breakdown
rows = conn.execute('''
    SELECT signal_type, COUNT(*) as cnt 
    FROM signals WHERE status = \"ACTIVE\" 
    GROUP BY signal_type ORDER BY cnt DESC
''').fetchall()
for r in rows:
    print(f'  {r[\"signal_type\"]}: {r[\"cnt\"]}')

outcomes = conn.execute('SELECT COUNT(*) FROM outcome_events').fetchone()[0]
print(f'Outcome events: {outcomes}')

rels = conn.execute('SELECT COUNT(*) FROM relationships').fetchone()[0]
print(f'Relationships: {rels}')

conn.close()
"
    log ""
    log "Phase 1 complete. All local processing done."
    log ""
fi

# =============================================================================
# PHASE 2: Add new signal detectors (kop_alignment, sbir_lapse_risk, commercial_pathway_fit)
# =============================================================================
# These 3 new signals from the MEIA spec run locally — no API needed.
# They need to be added to processing/signal_detector.py first.
# If Claude Code hasn't landed these yet, this phase patches them in.
# =============================================================================

if [[ $START_PHASE -le 2 ]]; then
    log "============================================"
    log "PHASE 2: New Signal Detectors"
    log "============================================"
    log ""

    # Check if new signal types already exist in signal_detector.py
    if grep -q "kop_alignment" processing/signal_detector.py 2>/dev/null; then
        log "New signal detectors already in signal_detector.py"
    else
        log "WARNING: New signal detectors (kop_alignment, sbir_lapse_risk, commercial_pathway_fit)"
        log "  not found in processing/signal_detector.py."
        log "  These need to be implemented from docs/MEIA_SIGNAL_SPEC.md before running."
        log "  Skipping Phase 2 — implement detectors and re-run with --phase 2"
        log ""
        # Don't exit — continue to Phase 3 so API work isn't blocked
    fi

    # If detectors exist, run them
    if grep -q "kop_alignment" processing/signal_detector.py 2>/dev/null; then
        log "Step 2.1: KOP alignment detection"
        run_step "KOP alignment signals" python3 scripts/detect_signals.py --types kop_alignment
        log ""

        log "Step 2.2: SBIR lapse risk detection"
        run_step "SBIR lapse risk signals" python3 scripts/detect_signals.py --types sbir_lapse_risk
        log ""

        log "Step 2.3: Commercial pathway fit detection"
        run_step "Commercial pathway signals" python3 scripts/detect_signals.py --types commercial_pathway_fit
        log ""

        # Rescore composites with new signals included
        log "Step 2.4: Rescore composites with new signals"
        run_step "Composite rescore" python3 scripts/calculate_composite_scores.py --all --persist
        log ""
    fi

    log "Phase 2 complete."
    log ""
fi

# =============================================================================
# PHASE 2.5: Batch Enrichment (optional, requires API)
# =============================================================================

if [[ "$ENRICH" == true ]] && [[ $START_PHASE -le 3 ]]; then
    log "============================================"
    log "PHASE 2.5: Batch Enrichment"
    log "============================================"
    log ""

    run_step "Enrichment queue" python3 scripts/enrichment_queue.py --top 200 --export data/enrichment_priority.txt
    run_step "Batch enrichment" python3 scripts/batch_enrich.py --file data/enrichment_priority.txt --delay 10

    log ""
    log "Phase 2.5 complete."
    log ""
fi

# =============================================================================
# PHASE 3: API-dependent processing (requires ANTHROPIC_API_KEY + network)
# =============================================================================
# Business classifier: ~5,623 entities × ~$0.01/entity = ~$56
# Policy alignment:    ~5,623 entities × ~$0.01/entity = ~$56
# Total API cost:      ~$110
# Wall clock:          ~2.5 hours at concurrency 10 (~40 entities/min)
#
# M5 + 24GB RAM handles the async concurrency easily. The bottleneck is
# API round-trip latency, not local compute. Concurrency 10 is the sweet
# spot — higher risks rate limiting, lower wastes time.
# =============================================================================

if [[ $START_PHASE -le 3 ]]; then
    log "============================================"
    log "PHASE 3: API-Dependent Processing"
    log "============================================"
    log ""

    if [[ "$SKIP_API" == true ]]; then
        log "Skipping Phase 3 (--skip-api flag set)"
        log ""
    else
        # Verify API key exists
        if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
            # Try loading from .env
            if [[ -f ".env" ]]; then
                export $(grep -v '^#' .env | grep ANTHROPIC_API_KEY | xargs)
            fi
        fi

        if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
            log "ERROR: ANTHROPIC_API_KEY not set. Set in .env or environment."
            log "Skipping Phase 3. Re-run with API key configured."
            log ""
        else
            log "API key found. Estimated cost: ~\$110 for full classify + score."
            log "Estimated time: ~2.5 hours at concurrency 10."
            log ""

            if [[ "$SKIP_CLASSIFY" == false ]]; then
                # Step 3.1: Business classification (async, concurrency 10)
                # ~5,623 unclassified entities, ~40/min = ~140 min
                log "Step 3.1: Business classification (5,623 unclassified entities)"
                log "  This will take ~90-140 minutes. Progress logged to $LOG_FILE"
                run_step "Business classifier" python3 -m processing.business_classifier \
                    --all --async --concurrency 10 --skip-classified
                log ""
            else
                log "Skipping classification (--skip-classify flag set)"
                log ""
            fi

            # Step 3.2: Policy alignment scoring (async, concurrency 10)
            # Runs on all classified entities that haven't been scored
            log "Step 3.2: Policy alignment scoring"
            log "  Scoring all classified entities that haven't been scored yet."
            run_step "Policy alignment" python3 -m processing.policy_alignment \
                --all --async --concurrency 10 --skip-scored
            log ""

            log "Phase 3 complete. API processing done."
            log ""
        fi
    fi
fi

# =============================================================================
# PHASE 4: Local rescore with enriched data
# =============================================================================
# Now that classification + policy data is complete for the full universe,
# re-run signals and scoring to pick up entities that were previously
# unclassified (and therefore missed by signal detectors that filter on
# core_business or policy_alignment).
# =============================================================================

if [[ $START_PHASE -le 4 ]]; then
    log "============================================"
    log "PHASE 4: Rescore with Enriched Data"
    log "============================================"
    log ""

    # Step 4.1: Re-run signal detection (now covers newly classified entities)
    log "Step 4.1: Re-run signal detection (full universe)"
    run_step "Signal detection (rescore)" python3 scripts/detect_signals.py --all
    log ""

    # Step 4.2: Run new signal detectors again (if implemented)
    if grep -q "kop_alignment" processing/signal_detector.py 2>/dev/null; then
        log "Step 4.2: Re-run new signal detectors"
        run_step "KOP alignment (rescore)" python3 scripts/detect_signals.py --types kop_alignment
        run_step "SBIR lapse risk (rescore)" python3 scripts/detect_signals.py --types sbir_lapse_risk
        run_step "Commercial pathway (rescore)" python3 scripts/detect_signals.py --types commercial_pathway_fit
        log ""
    fi

    # Step 4.3: Recalculate composite scores
    log "Step 4.3: Final composite scoring"
    run_step "Final composite scores" python3 scripts/calculate_composite_scores.py --all --persist
    log ""

    # Step 4.4: Re-run outcome tracking (may find new outcomes from newly classified entities)
    log "Step 4.4: Outcome tracking (rescore)"
    run_step "Outcome tracking (rescore)" python3 scripts/track_outcomes.py --since 2024-01-01
    log ""

    # Step 4.5: Rebuild knowledge graph with full data
    log "Step 4.5: Knowledge graph rebuild"
    run_step "Knowledge graph (rebuild)" python3 scripts/build_graph.py --materialize
    log ""

    log "Phase 4 complete."
    log ""
fi

# =============================================================================
# PHASE 5: Validation
# =============================================================================

if [[ $START_PHASE -le 5 ]]; then
    log "============================================"
    log "PHASE 5: Validation"
    log "============================================"
    log ""

    run_step "Final validation" python3 -c "
import sqlite3, json
conn = sqlite3.connect('data/defense_alpha.db')
conn.row_factory = sqlite3.Row

print('=' * 60)
print('APERTURE SIGNALS — RESCORE VALIDATION REPORT')
print('=' * 60)
print()

# Entity classification coverage
total = conn.execute('SELECT COUNT(*) FROM entities WHERE entity_type = \"STARTUP\"').fetchone()[0]
classified = conn.execute('''
    SELECT COUNT(*) FROM entities 
    WHERE entity_type = \"STARTUP\" AND core_business IS NOT NULL 
    AND core_business != \"unclassified\"
''').fetchone()[0]
scored = conn.execute('''
    SELECT COUNT(*) FROM entities 
    WHERE entity_type = \"STARTUP\" AND policy_alignment IS NOT NULL
''').fetchone()[0]
print(f'ENTITY COVERAGE:')
print(f'  Startups total:     {total:,}')
print(f'  Classified:         {classified:,} ({classified/total*100:.1f}%)')
print(f'  Policy scored:      {scored:,} ({scored/total*100:.1f}%)')
print(f'  Unclassified:       {total - classified:,} ({(total-classified)/total*100:.1f}%)')
print()

# Signal counts
active = conn.execute('SELECT COUNT(*) FROM signals WHERE status = \"ACTIVE\"').fetchone()[0]
print(f'SIGNALS:')
print(f'  Total active:       {active:,}')
rows = conn.execute('''
    SELECT signal_type, COUNT(*) as cnt 
    FROM signals WHERE status = \"ACTIVE\" 
    GROUP BY signal_type ORDER BY cnt DESC
''').fetchall()
for r in rows:
    print(f'    {r[\"signal_type\"]:35s} {r[\"cnt\"]:>6,}')
print()

# New signal types check
for stype in ['kop_alignment', 'sbir_lapse_risk', 'commercial_pathway_fit']:
    cnt = conn.execute(
        'SELECT COUNT(*) FROM signals WHERE signal_type = ? AND status = \"ACTIVE\"', 
        (stype,)
    ).fetchone()[0]
    status = f'{cnt:,} detected' if cnt > 0 else 'NOT DETECTED (detector may not be implemented yet)'
    print(f'  NEW: {stype:35s} {status}')
print()

# Composite score distribution
top20 = conn.execute('''
    SELECT e.canonical_name, 
           json_extract(e.policy_alignment, \"$.policy_tailwind_score\") as tailwind
    FROM entities e
    JOIN (
        SELECT entity_id, SUM(
            CASE WHEN signal_type IN ('sbir_to_contract_transition','jar_funding') THEN 3.0 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type IN ('sbir_validated_raise','rapid_contract_growth','kop_alignment','meia_experimentation') THEN 2.5 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type IN ('sbir_to_vc_raise','outsized_award','time_to_contract','pae_portfolio_member') THEN 2.0 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type IN ('sbir_phase_2_transition','sbir_graduation_speed','multi_agency_interest','funding_velocity','commercial_pathway_fit') THEN 1.5 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type IN ('high_priority_technology','first_dod_contract') THEN 1.0 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type = 'customer_concentration' THEN -1.5 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type = 'sbir_lapse_risk' THEN -1.5 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type = 'sbir_stalled' THEN -2.0 * COALESCE(freshness_weight, 1.0)
                 WHEN signal_type = 'gone_stale' THEN -1.5 * COALESCE(freshness_weight, 1.0)
                 ELSE 0.0
            END
        ) as composite
        FROM signals WHERE status = 'ACTIVE'
        GROUP BY entity_id
    ) s ON e.id = s.entity_id
    WHERE e.entity_type = 'STARTUP'
    ORDER BY s.composite DESC
    LIMIT 20
''').fetchall()

print(f'TOP 20 BY COMPOSITE SCORE:')
for i, r in enumerate(top20, 1):
    tailwind = r['tailwind'] or 'N/A'
    if tailwind != 'N/A':
        tailwind = f'{float(tailwind):.3f}'
    print(f'  {i:2d}. {r[\"canonical_name\"]:40s} tailwind={tailwind}')
print()

# Outcome tracking
outcomes = conn.execute('''
    SELECT outcome_type, COUNT(*) as cnt, 
           ROUND(SUM(outcome_value)/1e6, 1) as value_m
    FROM outcome_events GROUP BY outcome_type
''').fetchall()
print(f'OUTCOMES:')
for o in outcomes:
    val = f'\${o[\"value_m\"]}M' if o['value_m'] else 'N/A'
    print(f'  {o[\"outcome_type\"]:25s} {o[\"cnt\"]:>5,} ({val})')
print()

# Knowledge graph
rels = conn.execute('''
    SELECT relationship_type, COUNT(*) as cnt 
    FROM relationships GROUP BY relationship_type ORDER BY cnt DESC
''').fetchall()
print(f'KNOWLEDGE GRAPH:')
for r in rels:
    print(f'  {r[\"relationship_type\"]:35s} {r[\"cnt\"]:>6,}')
print()

# Data freshness
latest_signal = conn.execute('SELECT MAX(detected_date) FROM signals').fetchone()[0]
latest_contract = conn.execute('SELECT MAX(award_date) FROM contracts').fetchone()[0]
latest_funding = conn.execute('SELECT MAX(event_date) FROM funding_events').fetchone()[0]
print(f'DATA FRESHNESS:')
print(f'  Latest signal:      {latest_signal}')
print(f'  Latest contract:    {latest_contract}')
print(f'  Latest funding:     {latest_funding}')
print()

# SBIR lapse impact assessment
sbir_dependent = conn.execute('''
    SELECT COUNT(*) FROM entities e
    WHERE e.entity_type = 'STARTUP'
    AND (SELECT COUNT(*) FROM funding_events f 
         WHERE f.entity_id = e.id AND f.event_type LIKE 'SBIR_%') > 0
    AND (SELECT COUNT(*) FROM funding_events f 
         WHERE f.entity_id = e.id AND f.event_type IN ('REG_D_FILING', 'PRIVATE_ROUND')) = 0
    AND (SELECT COUNT(*) FROM contracts c WHERE c.entity_id = e.id) = 0
''').fetchone()[0]
print(f'SBIR LAPSE EXPOSURE:')
print(f'  SBIR-only entities (no contracts, no private capital): {sbir_dependent:,}')
print(f'  These are most exposed to SBIR/STTR authorization lapse.')
print()

print('=' * 60)
print('Rescore complete. Review log: data/pipeline_runs/')
print('=' * 60)

conn.close()
"

    log ""
    log "============================================"
    log "PIPELINE COMPLETE"
    log "============================================"
    log "Log: $LOG_FILE"
    log "Backup: data/defense_alpha_backup_${TIMESTAMP}.db"
    log ""
    log "Next steps:"
    log "  1. Review validation report above"
    log "  2. If new signal detectors weren't implemented, do that and re-run --phase 2"
    log "  3. Generate a test brief: python scripts/aperture_query.py --type deal --entity 'Scout Space' --no-claude --no-verify"
    log "  4. If everything looks good, delete backup: rm data/defense_alpha_backup_${TIMESTAMP}.db"
    log ""
fi
