# Defense Alpha: Project Context

**Last Updated:** February 10, 2026
**Purpose:** Spin up a new Claude instance with full context on the Defense Alpha project

---

## What Is Defense Alpha

A Python-based defense intelligence platform that aggregates government and private market data to identify investment signals in defense technology companies. Built to surface emerging companies with real traction for defense investors, sales consultants, and BD teams.

**Core value proposition:** Systematic signal detection + policy alignment scoring + freshness-weighted composite ranking to identify which SBIR-stage companies are most likely to win production contracts.

---

## Current Data State (Feb 10, 2026)

### Entity Counts by Type
| Type | Count | Description |
|------|-------|-------------|
| STARTUP | 8,770 | Emerging defense tech companies (core tracking population) |
| PRIME | 864 | Large defense contractors |
| NON_DEFENSE | 558 | Commercial companies with no defense footprint (SEC EDGAR only) |
| RESEARCH | 22 | Universities, FFRDCs, APLs |
| INVESTOR | 0 | (Not yet populated) |
| AGENCY | 0 | (Not yet populated) |
| **Total (unmerged)** | **10,214** | After entity resolution (834 merges from 11,048) |

### Entity Counts by Core Business (5,488 classified)
| Classification | Count | Examples |
|----------------|-------|----------|
| components | 2,159 | Sensors, materials, subsystems, manufacturing equipment |
| software | 1,912 | AI/ML, cybersecurity, C2 software, platforms |
| other | 608 | Doesn't fit categories (medical, water purification, etc.) |
| rf_hardware | 310 | Radios, antennas, radar, EW systems |
| aerospace_platforms | 270 | Drones, satellites, spacecraft, eVTOL aircraft |
| services | 174 | Consulting, support, training, R&D services |
| systems_integrator | 55 | Solution integrators |
| (not yet classified) | ~3,282 | Remaining startups awaiting classification |

### Data Volumes
| Table | Records | Value | Notes |
|-------|---------|-------|-------|
| Contracts | 13,340 | $1.16T | USASpending data |
| Funding Events | 29,523 | - | SBIR + Reg D + VC combined |
| Signals | 14,426 | - | 15 signal types (active only) |
| Outcome Events | 114 | - | 23 new_contract + 91 funding_raise |
| SBIR Embeddings | 27,529 | - | 100% coverage, all-MiniLM-L6-v2 |
| Policy Alignments | ~1,010 | - | Async scoring in progress (~4,478 total expected) |
| Entity Merges | 834 | - | High-confidence auto-merges |
| Review Queue | 201,328 | - | Pairs flagged for manual review |

---

## Systems Status

### 1. Business Classifier ✅ COMPLETE
**File:** `processing/business_classifier.py`

Classifies entities into core business categories based on SBIR award analysis:
- Uses Claude API (Sonnet) to analyze up to 10 most recent award titles
- Outputs: classification, confidence score (0-1), reasoning
- **5,488 entities classified** (full batch completed Feb 10)
- Supports async mode: `--async --concurrency 10` (~10x faster)
- `--skip-classified` flag to avoid re-processing

**Usage:**
```bash
python -m processing.business_classifier --all --async --concurrency 10 --skip-classified
python -m processing.business_classifier --names "SHIELD AI" "ANDURIL"
python -m processing.business_classifier --test --dry-run
```

### 2. Policy Alignment Scorer ✅ COMPLETE
**File:** `processing/policy_alignment.py`

Scores entities against FY2026 National Defense Strategy priorities:
- 10 priority areas with budget-derived weights (loaded from `config/policy_priorities.yaml`)
- Async concurrency support (`--async --concurrency 10`, ~40 entities/min)
- `--skip-scored` flag to resume interrupted runs
- Pacific/Indo-Pacific relevance flagging (boolean tag, not weighted)
- ~1,010 entities scored, async batch in progress for remaining

**Priority Areas (with FY26 budget weights):**
| Priority | Weight | FY26 Growth |
|----------|--------|-------------|
| space_resilience | 0.235 | +38% |
| nuclear_modernization | 0.170 | +17% |
| autonomous_systems | 0.130 | +10% |
| supply_chain_resilience | 0.110 | +7% |
| contested_logistics | 0.100 | +10% |
| electronic_warfare | 0.085 | +10% |
| jadc2 | 0.075 | +10% |
| border_homeland | 0.050 | +10% |
| cyber_offense_defense | 0.030 | +10% |
| hypersonics | 0.015 | -43% |

**Usage:**
```bash
python -m processing.policy_alignment --all --async --concurrency 10 --skip-scored
python -m processing.policy_alignment --names "SHIELD AI" "ANDURIL"
```

### 3. Signal Detection ✅ COMPLETE (15 signal types)
**Files:** `processing/signal_detector.py`, `scripts/detect_signals.py`

| Signal Type | Count | Weight | Decay Profile | Description |
|-------------|-------|--------|---------------|-------------|
| high_priority_technology | 4,422 | +1.0 | NO_DECAY | Works on priority tech areas |
| sbir_phase_2_transition | 2,871 | +1.5 | SLOW_DECAY | Phase I to II advancement |
| sbir_graduation_speed | 2,413 | +1.5 | SLOW_DECAY | Fast SBIR phase progression |
| customer_concentration | 1,183 | -1.5 | NO_DECAY | >80% revenue from one agency |
| multi_agency_interest | 758 | +1.5 | NO_DECAY | Contracts from 3+ agencies |
| **gone_stale** | **351** | **-1.5** | **NO_DECAY** | **No activity in 24+ months** |
| first_dod_contract | 422 | +1.0 | FAST_DECAY | New entrant to defense |
| sbir_stalled | 417 | -2.0 | NO_DECAY | 2+ Phase I, zero Phase II |
| sbir_to_contract_transition | 323 | +3.0 | SLOW_DECAY | SBIR to procurement pipeline |
| funding_velocity | 319 | +1.5 | FAST_DECAY | 2+ Reg D filings in 18 months |
| time_to_contract | 299 | +2.0 | SLOW_DECAY | Quick SBIR to procurement |
| rapid_contract_growth | 290 | +2.5 | FAST_DECAY | Contract value growth rate |
| sbir_to_vc_raise | 264 | +2.0 | SLOW_DECAY | VC validates gov't R&D |
| outsized_award | 94 | +2.0 | SLOW_DECAY | Unusually large contract |

### 4. Composite Scoring with Freshness Decay ✅ COMPLETE
**File:** `scripts/calculate_composite_scores.py`

Aggregates signals into a single score per entity with **signal-type-specific freshness decay:**

**Three decay profiles:**
| Profile | Signals | Curve |
|---------|---------|-------|
| FAST_DECAY | funding_velocity, rapid_growth, first_dod_contract | 0-6mo: 1.0, 6-12mo: 0.7, 12-24mo: 0.4, 24+: 0.2 |
| SLOW_DECAY | sbir_phase_2, sbir_to_contract, sbir_to_vc, graduation_speed, time_to_contract, outsized_award | 0-12mo: 1.0, 12-24mo: 0.85, 24-36mo: 0.65, 36+: 0.4 |
| NO_DECAY | customer_concentration, multi_agency, high_priority_tech, sbir_stalled, gone_stale | Always 1.0 |

Computes both `composite_score` (raw) and `freshness_adjusted_score` (decayed). Average freshness discount: **37.8%** across all signals.

**Usage:**
```bash
python scripts/calculate_composite_scores.py --top 20          # Top 20 by adjusted score
python scripts/calculate_composite_scores.py --all --persist   # Full breakdown, save freshness_weight to DB
python scripts/calculate_composite_scores.py --negative        # Show entities with risk signals
```

### 5. Outcome Tracking ✅ PARTIAL (2 of 8 detectors)
**File:** `scripts/track_outcomes.py`

Tracks what happens to entities after signals are detected:
- Links outcomes back to related signals via `related_signal_ids`
- Calculates `months_since_signal` for prediction accuracy measurement
- Deduplicates via `source_key`
- Only tracks STARTUP entities with defense footprint (skips non_defense)

**Outcome Types:**
| Type | Status | Count | Description |
|------|--------|-------|-------------|
| new_contract | ✅ Working | 23 | Won DoD/federal contract |
| funding_raise | ✅ Working | 91 | New Reg D / VC round ($2.66B total, 80.2% true predictions) |
| sbir_advance | Stub | 0 | Phase progression (I->II->III) |
| acquisition | Stub | 0 | Acquired by another entity |
| new_agency | Stub | 0 | Contract with new DoD branch |
| recompete_loss | Stub | 0 | Lost contract renewal |
| company_inactive | Stub | 0 | No activity 12+ months |
| sbir_stall | Stub | 0 | Phase I with no advancement 24+ months |

**Funding raise validation stats:**
- 80.2% true predictions (funding happened after signal fired)
- Median lead time: 35 months
- Top signal predictors: sbir_to_vc_raise (75), high_priority_tech (58), sbir_phase_2_transition (47)
- Filter: skips entities with 0 SBIRs AND 0 contracts (prevents SEC EDGAR noise)

**Usage:**
```bash
python scripts/track_outcomes.py --since 2025-01-01
python scripts/track_outcomes.py --since 2025-01-01 --detector funding_raise --dry-run
```

### 6. Pipeline Orchestrator ✅ COMPLETE
**File:** `scripts/run_pipeline.py`

Single-command runner for the full processing chain:

```bash
python scripts/run_pipeline.py --full-refresh              # Scrape + process (10 steps)
python scripts/run_pipeline.py --process-only              # Reprocess only (7 steps)
python scripts/run_pipeline.py --process-only --dry-run    # Show steps without executing
python scripts/run_pipeline.py --full-refresh --no-prompt  # Unattended (auto-continue on failure)
```

**Full-refresh steps:** USASpending scraper -> SBIR scraper -> SEC EDGAR scraper -> Entity resolution -> Reclassification check -> Business classifier (async) -> Policy alignment (async) -> Embedding generation -> Signal detection -> Outcome tracking

Logs saved to `data/pipeline_runs/<timestamp>.log`

### 7. Semantic Search ✅ COMPLETE
**File:** `scripts/find_similar.py`

Semantic similarity search over SBIR award titles using sentence-transformers:
- Model: all-MiniLM-L6-v2 (384-dim, runs locally on CPU)
- 27,529 SBIR titles embedded (100% coverage)
- Search by company name or free-text technology query

**Usage:**
```bash
python scripts/find_similar.py --company "HawkEye 360" --top 20
python scripts/find_similar.py --query "autonomous underwater vehicle"
python scripts/find_similar.py --embed  # Regenerate embeddings
```

### 8. Entity Types ✅ COMPLETE
**Files:** `processing/models.py` (EntityType enum)

| Type | Count | Description |
|------|-------|-------------|
| STARTUP | 8,770 | Core tracking population |
| PRIME | 864 | Large defense contractors |
| NON_DEFENSE | 558 | No defense footprint (0 SBIRs, 0 contracts) |
| RESEARCH | 22 | Universities, FFRDCs, APLs |

**Reclassification history:**
- 474 entities reclassified STARTUP -> PRIME (>$50M contracts, excluding AeroVironment, BlueHalo, SpaceX)
- 8 entities reclassified STARTUP -> RESEARCH (universities/labs)
- 558 entities reclassified STARTUP -> NON_DEFENSE (SEC EDGAR only, zero defense footprint)

### 9. Report Generation ✅ COMPLETE
**Files:** `scripts/generate_prospect_report.py`, `scripts/generate_pdf_report.py`

Generates branded PDF/Markdown reports for specific verticals:
- RF & Communications Report v2 (55 companies)
- Execution-weighted combined scoring
- Top 10 detailed profiles with policy analysis

---

## Key Decisions Made and Why

### 1. Combined Score Formula (Execution-Weighted)
```
combined = 0.55 x norm_composite + 0.30 x policy_tailwind + 0.15 x contract_tier
```

**Rationale:** Original formula over-weighted policy alignment, causing companies with no contracts to rank above proven performers.
- 55% signal strength (freshness-adjusted composite)
- 30% policy tailwind (NDS priority alignment)
- 15% execution bonus (tiered by contract value: 0 contracts=0.0, <$1M=0.5, >=$1M=1.0)

### 2. Signal-Type-Specific Freshness Decay
**Decision:** Three-tier decay instead of one-size-fits-all:
- FAST_DECAY for momentum signals (funding velocity, growth, first contract)
- SLOW_DECAY for milestone signals (SBIR transitions, outsized awards)
- NO_DECAY for structural signals (tech focus, agency concentration, stalled)

**Rationale:** A company's SBIR Phase II transition is meaningful for years (milestone), but their funding velocity score from 2 years ago is stale (momentum). Structural signals like multi-agency interest remain true until contradicted. Average freshness discount: 37.8%.

### 3. Gone Stale Signal (24-month threshold)
**Decision:** New negative signal fires when ALL of an entity's signals are >24 months old AND no new contracts/funding in that period.

**Rationale:** 18 months was too aggressive for defense timelines (SBIR Phase II takes 12-18 months alone). 24 months captures genuinely inactive companies while allowing for normal procurement lag.

### 4. Non-Defense Entity Classification
**Decision:** Created `NON_DEFENSE` entity type for 558 entities with zero SBIRs, zero contracts, only SEC EDGAR Reg D filings.

**Rationale:** SEC EDGAR scraper captured commercial companies (Genesys Cloud, BitMine, Compass real estate). These polluted analysis — Genesys alone inflated funding raise outcomes by $3B. NON_DEFENSE excludes them from classifier, scorer, and signal pipelines.

### 5. Funding Raise Defense Footprint Filter
**Decision:** `detect_funding_raises()` skips entities with 0 SBIRs AND 0 contracts.

**Rationale:** Without this filter, 50% of funding raise outcomes were non-defense noise. With filter: 181->91 outcomes, value $7.4B->$2.66B, true prediction rate 62.4%->80.2%.

### 6. China Pacing: Tag Not Weight
**Decision:** `china_pacing` is a boolean tag (`pacific_relevance: true`), not a weighted scoring factor.

**Rationale:** Not a budget line item. Companies get tagged when relevant to Indo-Pacific posture.

### 7. Policy Weights from Budget Data
**Decision:** Weights from FY25->FY26 President's Budget Request growth rates.

**Rationale:** Budget growth is the best available signal for where DoD is putting money. Space resilience gets highest weight (0.235) because +38% growth. Hypersonics lowest (0.015) because -43% cuts.

### 8. Async Concurrency for API Calls
**Decision:** Both business classifier and policy alignment support `--async --concurrency N` with `asyncio.Semaphore`.

**Rationale:** Sequential: ~4 entities/min. Async with 10 concurrency: ~40 entities/min. 10x improvement.

---

## Architecture

```
defense-alpha/
├── scrapers/
│   ├── usaspending.py          # DoD contracts from USASpending API
│   ├── sbir.py                 # SBIR/STTR awards (bulk CSV + API)
│   └── sec_edgar.py            # SEC Form D private funding (Reg D filings)
├── processing/
│   ├── models.py               # SQLAlchemy models (Entity, Contract, Signal, OutcomeEvent, etc.)
│   ├── database.py             # DB connection and session management
│   ├── entity_resolver.py      # Deduplication with fuzzy matching
│   ├── entity_resolution/      # Advanced resolution (resolver.py, matchers.py)
│   ├── business_classifier.py  # LLM-based core business classification (sync + async)
│   ├── policy_alignment.py     # NDS priority scoring (sync + async)
│   ├── signal_detector.py      # All signal detection logic (15 types)
│   └── technology_tagger.py    # Keyword-based tech categorization
├── scripts/
│   ├── run_pipeline.py         # Full pipeline orchestrator (--full-refresh / --process-only)
│   ├── detect_signals.py       # Signal detection CLI
│   ├── calculate_composite_scores.py  # Composite scoring with freshness decay
│   ├── run_entity_resolution.py
│   ├── find_similar.py         # Semantic search over SBIR embeddings
│   ├── track_outcomes.py       # Outcome tracking for signal validation
│   ├── tag_sbir_entities.py
│   ├── tech_clusters.py        # K-means clustering of SBIR abstracts
│   ├── generate_prospect_report.py  # Markdown report generator
│   └── generate_pdf_report.py       # PDF report generator
├── reports/
│   ├── rf_comms_v2.md          # Latest RF report (55 companies)
│   └── rf_comms_v2.pdf
├── config/
│   ├── policy_priorities.yaml  # NDS priority definitions and weights
│   └── settings.py             # App configuration
├── data/
│   ├── defense_alpha.db        # SQLite database (~210MB)
│   ├── review_queue.csv        # Entity resolution review queue (201K pairs)
│   └── pipeline_runs/          # Pipeline execution logs
├── docs/
│   └── PROJECT_CONTEXT.md      # This file
├── PROJECT_CONTEXT.md          # Root copy for easy access
└── requirements.txt
```

---

## Database Schema (Key Tables)

### entities
```sql
id, canonical_name, entity_type (startup/prime/research/non_defense/investor/agency)
cage_code, duns_number, ein, uei
headquarters_location, founded_date, technology_tags (JSON)
website_url
core_business (rf_hardware/software/systems_integrator/aerospace_platforms/components/services/other/unclassified)
core_business_confidence, core_business_reasoning
policy_alignment (JSON: scores, top_priorities, policy_tailwind_score, pacific_relevance, reasoning, scored_date)
merged_into_id
```

### contracts
```sql
id, entity_id (FK), contract_number, contract_value, award_date
contracting_agency, naics_code, psc_code
period_of_performance_start/end, place_of_performance, raw_data (JSON)
```

### funding_events
```sql
id, entity_id (FK), event_type (sbir_phase_1/2/3, reg_d_filing, vc_round, etc.)
amount, event_date, investors_awarders (JSON), round_stage, raw_data (JSON)
```

### signals
```sql
id, entity_id (FK), signal_type, confidence_score (0-1)
detected_date, evidence (JSON), status (active/expired/validated/false_positive)
freshness_weight (0-1, decay factor applied during scoring)
```

### outcome_events
```sql
id, entity_id (FK)
outcome_type (new_contract/funding_raise/sbir_advance/acquisition/new_agency/recompete_loss/company_inactive/sbir_stall)
outcome_date, outcome_value
details (JSON), source, source_key (unique, for dedup)
related_signal_ids (JSON), months_since_signal
```

### sbir_embeddings
```sql
id, funding_event_id (FK), entity_id (FK)
award_title, embedding (BLOB, 384-dim float32)
```

---

## How to Start a Session

```
I'm working on defense-alpha at ~/projects/defense-alpha

cd ~/projects/defense-alpha && source venv/bin/activate

Defense intelligence platform with:
- 10,214 entities (8,770 startups, 864 primes, 558 non-defense, 22 research)
- 13,340 contracts ($1.16T), 29,523 funding events
- 14,426 active signals (15 types, freshness-weighted)
- 5,488 entities classified by core business
- 114 outcome events (23 contracts, 91 funding raises — 80.2% true predictions)
- 27,529 SBIR embeddings (100% coverage)
- Pipeline orchestrator: scripts/run_pipeline.py

Current priorities: see Next Tasks section below.

Show me current DB stats to confirm state, then let's continue.
```

---

## Next Session Priorities

### 1. Verify Policy Alignment Scorer Completed
- Background task was at 90% (4,031/4,478) when this session ended
- Check: `SELECT COUNT(*) FROM entities WHERE policy_alignment IS NOT NULL AND merged_into_id IS NULL`
- If incomplete, re-run: `python -m processing.policy_alignment --all --skip-scored --async --concurrency 10`
- Expected final count: ~4,478+ entities scored (all classified startups with SBIRs)

### 2. RAG Integration
- Add retrieval-augmented generation for entity research
- Use SBIR embeddings (27,529 titles, all-MiniLM-L6-v2) as retrieval layer
- Enable queries like: "What companies are working on contested logistics in space?"
- Could extend `find_similar.py` or build a new `scripts/rag_query.py`
- Consider: Should RAG use SBIR abstracts (richer) or just titles (already embedded)?

### 3. Data Validation Layer
- Build automated data quality checks that run before/after pipeline
- Validate: no orphaned contracts, no duplicate source_keys, entity type distribution sanity
- Check for entity merges that broke signal/outcome links
- Detect anomalies: entities with $1B+ contracts but entity_type=STARTUP
- Could be a new step in `run_pipeline.py` or standalone `scripts/validate_data.py`

### 4. Policy Headwind Signal
- New negative signal: entity works primarily in areas with declining budget
- Inverse of `high_priority_technology` — flags companies in shrinking areas (e.g., hypersonics -43%)
- Use policy_alignment scores: if top priorities are all low-weight/declining, fire signal
- Weight: -1.0 to -1.5, NO_DECAY profile
- Add to `signal_detector.py` alongside existing negative signals

### 5. Remaining Outcome Detectors (6 stubs)
Priority order:
1. **sbir_advance** — Phase progression I->II->III. Compare funding_events before/after signal.
2. **new_agency** — Contract with new DoD branch. Check contracting_agency vs historical.
3. **company_inactive** — No new contracts/funding/SBIRs in 12+ months.
4. **sbir_stall** — Phase I with no Phase II after 24+ months (mirrors sbir_stalled signal).
5. **acquisition** — Check for merged_into_id changes or acquisition funding events.
6. **recompete_loss** — Hardest: requires tracking contract end dates and renewal patterns.

### Medium Priority
6. **Classify remaining ~3,282 entities** — Run business classifier on unclassified startups
7. **Refresh data pulls** — USASpending (30 days), SBIR (current year), SEC EDGAR (90 days)
8. **Generate updated reports** — New RF report, potentially software/aerospace verticals
9. **Review entity resolution queue** — 201,328 pairs in `data/review_queue.csv`

---

## Key Files to Reference

| Purpose | File |
|---------|------|
| Pipeline orchestrator | `scripts/run_pipeline.py` |
| Signal detection | `processing/signal_detector.py` |
| Composite scoring | `scripts/calculate_composite_scores.py` |
| Business classification | `processing/business_classifier.py` |
| Policy alignment | `processing/policy_alignment.py` |
| Outcome tracking | `scripts/track_outcomes.py` |
| Entity resolution | `processing/entity_resolver.py` |
| Semantic search | `scripts/find_similar.py` |
| Report generation | `scripts/generate_prospect_report.py` |
| Policy config | `config/policy_priorities.yaml` |
| DB models | `processing/models.py` |

---

## Strategic Context

**Moat is in data infrastructure** (pipelines, connectors, entity resolution) — not the LLM layer. Classification is plumbing. **Outcome tracking is defensible** — backtest which signals predict success; this is the unique dataset. **Workflow integration creates stickiness** — alerts, watchlists, embedded in user's daily process.

**Key validation:** Funding raise detector shows 80.2% true prediction rate with 35-month median lead time. Signals fire well before capital raises happen.

Don (first client) feedback: "All new SBIR companies to me!" He suggested targeting VCs + Primes as customers ("matchmaker" positioning).

---

*This document should give any Claude instance enough context to continue work on Defense Alpha.*
