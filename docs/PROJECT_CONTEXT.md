# Defense Alpha: Project Context

**Last Updated:** February 16, 2026
**Purpose:** Spin up a new Claude instance with full context on the Defense Alpha project

---

## What Is Defense Alpha

A Python-based defense intelligence platform that aggregates government and private market data to identify investment signals in defense technology companies. Built to surface emerging companies with real traction for defense investors, sales consultants, and BD teams.

**Core value proposition:** Systematic signal detection + policy alignment scoring + freshness-weighted composite ranking to identify which SBIR-stage companies are most likely to win production contracts.

**Business model:** Intelligence company, not SaaS platform. Reports are the product, the engine is the back office. Revenue model: curated reports ($2-5K), quarterly intelligence briefs ($10-20K/yr). Defensibility comes from outcome tracking time series (time-locked), human intelligence from client feedback, and analyst reputation.

---

## Current Data State (Feb 16, 2026)

### Entity Counts by Type
| Type | Count | Description |
|------|-------|-------------|
| STARTUP | 9,328 | Emerging defense tech companies (core tracking population) |
| PRIME | 864 | Large defense contractors |
| NON_DEFENSE | 553 | No defense footprint (0 SBIRs, 0 contracts, SEC EDGAR only) |
| RESEARCH | 22 | Universities, FFRDCs, APLs |
| **Total (unmerged)** | **10,214** | After entity resolution (834 merges from 11,048) |

### Classification Pipeline Status
| Stage | Count | Description |
|-------|-------|-------------|
| Fully classified + policy scored | 5,481 | Business classification + policy alignment complete |
| Unclassified | 3,289 | Need business classifier run before policy scoring |
| Non-defense (excluded) | 553 | No defense footprint (0 SBIRs, 0 contracts, SEC EDGAR only) |

### Data Volumes
| Table | Records | Value | Notes |
|-------|---------|-------|-------|
| Contracts | 13,340 | $1.16T | USASpending data |
| Funding Events | 29,523 | - | SBIR + Reg D + VC combined |
| Signals | 14,502 | - | 15 signal types (active only), tiered freshness decay |
| Outcome Events | 114 | - | 23 new_contract + 91 funding_raise |
| SBIR Embeddings | 27,529 | - | 100% coverage, all-MiniLM-L6-v2 |
| Policy Alignments | 5,481 | - | All eligible entities scored (requires SBIR + classified business) |
| Entity Merges | 834 | - | High-confidence auto-merges |
| Review Queue | 201,328 | - | Pairs flagged for manual review |

---

## Infrastructure Complete

- Pipeline orchestrator (`scripts/run_pipeline.py`)
- Async business classifier + policy alignment scorer
- Tiered signal decay (fast/slow/none by signal type)
- Gone stale detection (24mo threshold)
- Funding raise detector (91 outcomes, 80% prediction rate, 35mo lead)
- New contract detector (23 outcomes)
- `sbir_validated_raise` signal (strict temporal sequencing, 164 companies, $8.48B)
- RAG engine (`processing/rag_engine.py`) — semantic retrieval → enrichment → Claude reasoning
- CLI: `python scripts/rag_query.py "<question>"`
- QA verification script (`scripts/qa_report_data.py`)
- Report generation pipeline (`scripts/generate_prospect_report.py`, `scripts/generate_pdf_report.py`, `scripts/generate_phase2_pdf.py`)

---

## Key Findings

- **SBIR Phase II predicts private capital raises:** 164 validated companies, $8.48B post-SBIR capital, 8-month median gap
- 82 companies followed textbook SBIR-first pathway ($3.6B)
- 80% funding raise prediction rate with 35-month lead time
- Government SBIR activity predicts private raises ~3 years ahead
- Signal co-occurrence: `funding_velocity` + `sbir_to_vc_raise` = "smart money in motion" (100 entities)
- Next wave pipeline: 3,221 Phase II startups with no Reg D filing
- Raise tier concentration: 16 companies account for 70% of all post-SBIR capital ($5.94B)
- Space resilience dominates: 43 companies, $3.5B, 41% of cohort capital

---

## Reports Delivered

1. **RF/Comms v2** — 56 companies, delivered to Don
2. **Phase II Signal** — 164 companies, $8.48B thesis, ready for Konstantine (`reports/phase2_signal_report.pdf`)

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
- **5,481 entities scored** (all startups with SBIR events + classified core business)

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

### 3. Signal Detection ✅ COMPLETE (15 signal types, tiered freshness decay)
**Files:** `processing/signal_detector.py`, `scripts/detect_signals.py`

| Signal Type | Count | Weight | Decay Profile | Description |
|-------------|-------|--------|---------------|-------------|
| high_priority_technology | 4,422 | +1.0 | NO_DECAY | Works on priority tech areas |
| sbir_phase_2_transition | 2,871 | +1.5 | SLOW_DECAY | Phase I to II advancement |
| sbir_graduation_speed | 2,413 | +1.5 | SLOW_DECAY | Fast SBIR phase progression |
| customer_concentration | 1,183 | -1.5 | NO_DECAY | >80% revenue from one agency |
| multi_agency_interest | 758 | +1.5 | NO_DECAY | Contracts from 3+ agencies |
| first_dod_contract | 422 | +1.0 | FAST_DECAY | New entrant to defense |
| sbir_stalled | 417 | -2.0 | NO_DECAY | 2+ Phase I, zero Phase II |
| gone_stale | 351 | -1.5 | NO_DECAY | No activity in 24+ months |
| sbir_to_contract_transition | 323 | +3.0 | SLOW_DECAY | SBIR to procurement pipeline |
| funding_velocity | 319 | +1.5 | FAST_DECAY | 2+ Reg D filings in 18 months |
| time_to_contract | 299 | +2.0 | SLOW_DECAY | Quick SBIR to procurement |
| rapid_contract_growth | 290 | +2.5 | FAST_DECAY | Contract value growth rate |
| sbir_to_vc_raise | 264 | +2.0 | SLOW_DECAY | VC validates gov't R&D (loose) |
| sbir_validated_raise | 164 | +2.5 | SLOW_DECAY | Strict temporal: SBIR precedes/catalyzes raise |
| outsized_award | 94 | +2.0 | SLOW_DECAY | Unusually large contract |

### 4. Composite Scoring with Freshness Decay ✅ COMPLETE
**File:** `scripts/calculate_composite_scores.py`

Aggregates signals into a single score per entity with **signal-type-specific freshness decay:**

**Three decay profiles:**
| Profile | Signals | Curve |
|---------|---------|-------|
| FAST_DECAY | funding_velocity, rapid_growth, first_dod_contract | 0-6mo: 1.0, 6-12mo: 0.7, 12-24mo: 0.4, 24+: 0.2 |
| SLOW_DECAY | sbir_phase_2, sbir_to_contract, sbir_to_vc, sbir_validated_raise, graduation_speed, time_to_contract, outsized_award | 0-12mo: 1.0, 12-24mo: 0.85, 24-36mo: 0.65, 36+: 0.4 |
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
| funding_raise | ✅ Working | 91 | New Reg D / VC round ($2.66B total, 80% true predictions) |
| sbir_advance | Stub | 0 | Phase progression (I->II->III) |
| acquisition | Stub | 0 | Acquired by another entity |
| new_agency | Stub | 0 | Contract with new DoD branch |
| recompete_loss | Stub | 0 | Lost contract renewal |
| company_inactive | Stub | 0 | No activity 12+ months |
| sbir_stall | Stub | 0 | Phase I with no advancement 24+ months |

**Key finding:** SBIR phase transitions predict private capital raises ~3 years ahead (35-month median lead time).

**Funding raise validation stats:**
- 80% true predictions (funding happened after signal fired)
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
| STARTUP | 9,328 | Core tracking population |
| PRIME | 864 | Large defense contractors |
| NON_DEFENSE | 553 | No defense footprint (0 SBIRs, 0 contracts) |
| RESEARCH | 22 | Universities, FFRDCs, APLs |

**Reclassification history:**
- 474 entities reclassified STARTUP -> PRIME (>$50M contracts, excluding AeroVironment, BlueHalo, SpaceX)
- 8 entities reclassified STARTUP -> RESEARCH (universities/labs)
- 553 entities reclassified STARTUP -> NON_DEFENSE (SEC EDGAR only, zero defense footprint)

### 9. Report Generation ✅ COMPLETE
**Files:** `scripts/generate_prospect_report.py`, `scripts/generate_pdf_report.py`, `scripts/generate_phase2_pdf.py`

Generates branded PDF/Markdown reports:
- RF & Communications Report v2 (55 companies)
- Phase II Signal report (164 companies, $8.48B thesis)
- Execution-weighted combined scoring
- Top 10 detailed profiles with policy analysis

### 10. RAG Engine ✅ COMPLETE
**Files:** `processing/rag_engine.py`, `scripts/rag_query.py`

Retrieval-augmented generation connecting semantic search to Claude reasoning:
- Semantic retrieval over 27,529 SBIR embeddings (all-MiniLM-L6-v2, loaded into memory on init ~40MB)
- Entity enrichment: signals, policy alignment, contracts, funding, composite scores (2 DB queries per entity)
- Claude reasoning with structured JSON output (relevant_companies, watchlist, gaps, summary)
- Filters: `core_business`, `min_composite`, `entity_type`
- Token budget management (12K default, drops lowest-similarity entities first)
- Similarity threshold: 0.25 minimum, warns if <3 entities remain
- `to_report_input()` bridges RAG results to PDF report generator
- End-to-end latency: ~19s including Claude reasoning

**Usage:**
```bash
python scripts/rag_query.py "companies building counter-drone RF systems" --raw   # Verify context
python scripts/rag_query.py "jam-resistant tactical radios for Pacific ops"        # Full pipeline
python scripts/rag_query.py "mesh networking" --filter-business software --min-score 2.0
python scripts/rag_query.py "autonomous underwater vehicles" --report              # JSON for reports
```

### 11. QA Verification ✅ COMPLETE
**File:** `scripts/qa_report_data.py`

Cross-references stored signal evidence against raw funding_events data:
- 4 verification sections per entity: SBIR, Reg D, Signal recomputation, Timeline
- Reg D deduplication detection (same amount within 30 days)
- Independent signal recomputation from raw data
- 178/178 checks passed across top 20 cohort companies

**Usage:**
```bash
python scripts/qa_report_data.py                    # Top 20 by raise amount
python scripts/qa_report_data.py --top 10
python scripts/qa_report_data.py --entity "SI2 TECHNOLOGIES"
```

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
**Decision:** Created `NON_DEFENSE` entity type for 553 entities with zero SBIRs, zero contracts, only SEC EDGAR Reg D filings.

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

### 9. Reg D Deduplication
**Decision:** Filings with identical (entity_id, event_date, amount) treated as amended filings and collapsed to one.

**Rationale:** Found 25 duplicate groups totaling $1.67B in inflated capital. Biggest offender: Genesys Cloud ($1.5B duplicated). Applied consistently across all three detector locations (sbir_to_vc_raise, sbir_validated_raise, detect_funding_raises).

---

## Architecture

```
defense-alpha/
├── scrapers/
│   ├── usaspending.py          # DoD contracts from USASpending API
│   ├── sbir.py                 # SBIR/STTR awards (bulk CSV + API)
│   └── sec_edgar.py            # SEC Form D private funding (Reg D filings)
├── processing/
│   ├── models.py               # SQLAlchemy models (Entity, Contract, Signal, Relationship, etc.)
│   ├── database.py             # DB connection and session management
│   ├── entity_resolver.py      # Deduplication with fuzzy matching
│   ├── entity_resolution/      # Advanced resolution (resolver.py, matchers.py)
│   ├── business_classifier.py  # LLM-based core business classification (sync + async)
│   ├── policy_alignment.py     # NDS priority scoring (sync + async)
│   ├── signal_detector.py      # All signal detection logic (15 types)
│   ├── signal_response.py      # Signal-response benchmark framework (parameterized, bootstrap CIs)
│   ├── knowledge_graph.py      # Graph materialization + path queries
│   ├── rag_engine.py           # RAG: retrieval → enrichment → Claude reasoning
│   └── technology_tagger.py    # Keyword-based tech categorization
├── scripts/
│   ├── run_pipeline.py         # Full pipeline orchestrator (--full-refresh / --process-only)
│   ├── detect_signals.py       # Signal detection CLI
│   ├── calculate_composite_scores.py  # Composite scoring with freshness decay
│   ├── run_entity_resolution.py
│   ├── find_similar.py         # Semantic search over SBIR embeddings
│   ├── track_outcomes.py       # Outcome tracking for signal validation
│   ├── rag_query.py            # RAG CLI (--raw, --report, full pipeline)
│   ├── qa_report_data.py       # QA verification for signal data
│   ├── tag_sbir_entities.py
│   ├── tech_clusters.py        # K-means clustering of SBIR abstracts (--save to JSON)
│   ├── run_benchmarks.py       # Signal-response benchmark runner (3 predefined configs)
│   ├── build_graph.py          # Knowledge graph materialization + queries
│   ├── visualize_graph.py      # NetworkX/Pyvis interactive graph visualization
│   ├── extract_investors.py    # Investor extraction from Reg D related persons
│   ├── materialize_agencies.py # Agency relationship profiles (dollar volumes, counts)
│   ├── generate_prospect_report.py  # Markdown report generator
│   ├── generate_pdf_report.py       # PDF report generator (prospect reports)
│   ├── generate_phase2_pdf.py       # PDF report generator (Phase II Signal)
│   └── policy_signal_poc.py         # Policy signal-response PoC (Space Force, original)
├── results/
│   ├── benchmark_space_force.json       # Signal-response benchmark results
│   ├── benchmark_nds_2018.json
│   └── benchmark_ukraine_drones_2022.json
├── reports/
│   ├── rf_comms_v2.md          # RF report (55 companies)
│   ├── rf_comms_v2.pdf
│   ├── phase2_signal_report.md # Phase II Signal thesis report (164 companies)
│   ├── phase2_signal_report.pdf
│   ├── graph_space_resilience.html     # Interactive ecosystem visualizations
│   ├── graph_autonomous_systems.html
│   └── graph_anduril.html
├── config/
│   ├── policy_priorities.yaml  # NDS priority definitions and weights
│   └── settings.py             # App configuration
├── data/
│   ├── defense_alpha.db        # SQLite database (~210MB)
│   ├── review_queue.csv        # Entity resolution review queue (201K pairs)
│   └── pipeline_runs/          # Pipeline execution logs
├── docs/
│   └── project_context.md      # This file
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

### relationships
```sql
id, source_entity_id (FK), relationship_type (funded_by_agency/contracted_by_agency/invested_in_by/similar_technology/competes_with/aligned_to_policy)
target_entity_id (FK, nullable), target_name (for non-entity targets like agencies/policy areas)
weight (edge strength/dollar value), properties (JSON)
first_observed, last_observed
```

---

## How to Start a Session

```
I'm working on defense-alpha at ~/projects/defense-alpha

cd ~/projects/defense-alpha && source venv/bin/activate

Defense intelligence platform with:
- 10,214 entities (9,328 startups, 864 primes, 553 non_defense, 22 research)
- 5,481 fully classified + policy scored
- 3,289 unclassified (need business classifier)
- 13,340 contracts ($1.16T), 29,523 funding events
- 14,502 signals (15 types, tiered freshness decay)
- 114 outcome events (23 contracts, 91 funding raises — 80% prediction rate, 35mo lead)
- 27,529 SBIR embeddings (full coverage)
- Key finding: SBIR Phase II predicts private raises — 164 companies, $8.48B, 8-month median gap
- Next wave pipeline: 3,221 Phase II startups with no Reg D
- Knowledge graph: 39,604 relationships materialized (agency, contract, policy edges)
- Signal-response benchmarks: 3 calibrated pairs (Space Force, NDS 2018, Ukraine Drones)
- Interactive visualizations: reports/graph_space_resilience.html, etc.

Current priorities: see Next Priority section below.

Show me current DB stats to confirm state, then let's continue.
```

---

## Knowledge Graph
- 39,604 relationships (16,656 FUNDED_BY_AGENCY, 5,811 CONTRACTED_BY_AGENCY, 17,137 ALIGNED_TO_POLICY)
- Relationship model in `processing/models.py` (`Relationship`, `RelationshipType`)
- Materialization: `scripts/build_graph.py` (`--materialize`, `--stats`, `--path`, `--ecosystem`)
- Visualization: `scripts/visualize_graph.py` (Pyvis interactive HTML)
- Supports path queries between entities (`--path "Anduril" --policy space_resilience`)
- Ecosystem graphs show companies, agencies, and policy connections in one view
- Graph engine: `processing/knowledge_graph.py`

## Signal-Response Benchmarks
- Framework: `processing/signal_response.py` (parameterized configs, bootstrap CIs, auto-interpretation)
- 3 calibrated pairs:

| Signal | Reg D Capital Differential | Reg D Timing | Contract Differential | Contract Timing |
|--------|---------------------------|-------------|----------------------|-----------------|
| **Space Force (Dec 2019)** | +871% vs control | Q+1 | -54.9% | Q+3 |
| **NDS 2018 (Jan 2018)** | -41,169% (general VC boom) | Q+2 | +829.8% | Q+1 |
| **Ukraine Drones (Feb 2022)** | +51.3% | Q+1 | +23.0% | Q+2 |

- Key pattern: Reg D responds Q+1 to Q+2, contracts respond Q+1 to Q+3
- Limitation: Pre-2019 Reg D baseline too thin (7 filings). SEC EDGAR scraper now supports backfill to 2008.
- CLI: `scripts/run_benchmarks.py` (`--benchmark space_force`, `--bootstrap 1000`, `--output results/`)
- Results stored as JSON in `results/benchmark_*.json`
- Original PoC preserved: `scripts/policy_signal_poc.py`

## Investor Data
- `scripts/extract_investors.py` parses RELATEDPERSONS from SEC EDGAR DERA data
- SEC EDGAR scraper updated to download `RELATEDPERSONS.TSV` (directors, officers, promoters)
- Enables investor pattern analysis (who invests in which signal profiles)
- Related persons stored in `raw_data._related_persons` on Reg D funding_events

## Product Vision (Validated)
Defense Alpha → knowledge graph of defense capital formation
- Take government/DoD signals (policy, budget, SBIR, OTA, solicitations)
- Map to private market responses (VC raises, company formation, contract wins)
- Build historical benchmarks from signal-response pairs
- Apply benchmarks to current signals for quantitative predictions
- Defensible: time-locked dataset, cross-domain linkage nobody else has

---

## Next Priority

### 1. Backfill Reg D to 2012 for stronger baselines
- SEC EDGAR scraper now supports `--start-date 2008-01-01` (DERA data available from 2008 Q1)
- Run: `python scrapers/sec_edgar.py --start-date 2012-01-01 --end-date 2019-12-31`
- This unblocks statistically valid baselines for all signal-response benchmarks
- Current pre-2019 Reg D baseline: only 7 filings (too thin for confidence intervals)

### 2. Build comparables engine for deal intelligence queries
- Given a target company, find comparables via SBIR embedding similarity + agency overlap + policy alignment
- Extend knowledge graph with SIMILAR_TECHNOLOGY and COMPETES_WITH edges
- Cross-reference overlapping agencies, NAICS codes, and policy priorities
- Output: "Companies like X" with signal profiles, funding history, agency relationships

### 3. OTA data integration (USASpending filter expansion)
- Add Other Transaction Authority (OTA) awards as a funding event type
- OTAs are a key signal for non-traditional defense companies
- USASpending API supports OTA filtering

### 4. Test manual comparables analysis on Scout Space
- Use the knowledge graph + benchmarks to build a full investment memo
- End-to-end validation: signals → benchmarks → comparables → recommendation

### Next Session Priorities (carried over)

### 5. Data Validation Layer
- Build automated data quality checks that run before/after pipeline
- Validate: no orphaned contracts, no duplicate source_keys, entity type distribution sanity

### 6. Policy Headwind Signal
- New negative signal for companies in declining budget areas (e.g., hypersonics -43%)
- Add to `signal_detector.py` alongside existing negative signals

### 7. Remaining Outcome Detectors (3 priority stubs)
1. **sbir_advance** — Phase progression I->II->III
2. **new_agency** — Contract with new DoD branch
3. **company_inactive** — No activity in 12+ months

### 8. Classify Remaining 3,289 Entities
- `python -m processing.business_classifier --all --async --concurrency 10 --skip-classified`
- `python -m processing.policy_alignment --all --skip-scored --async --concurrency 10`

### 9. Connect RAG → Report Generator (single command: query → PDF)
- Goal: `python scripts/rag_query.py "counter-drone RF" --pdf reports/counter_drone.pdf`

### 10. Fix Reg D Filing Count Edge Case
- NULL-date Reg D filings cause off-by-one in evidence `regd_filing_count`

### Medium Priority
- **Refresh data pulls** — USASpending (30 days), SBIR (current year), SEC EDGAR (90 days)
- **Generate updated RF report** — Refresh with latest signal/policy data
- **Review entity resolution queue** — 201,328 pairs in `data/review_queue.csv`
- **Remaining outcome stubs** — sbir_stall, acquisition, recompete_loss (lower priority)
- **Generate Defense Software Report** — Filter for `core_business = 'software'` (1,912 entities)
- **Build Feedback Capture Mechanism** — Capture report recipient feedback, feed into signal weighting

---

## Technical Notes

- Run scrapers sequentially (SQLite can't handle concurrent writes)
- Business classifier now has `--async --concurrency --skip-classified` flags
- Signal weights: `sbir_to_contract` (3.0), `sbir_validated_raise` (2.5), `rapid_growth` (2.5), `sbir_to_vc` (2.0) are highest positive
- Tiered decay: FAST (momentum signals), SLOW (milestones), NONE (structural)
- Gone stale threshold: 24 months with no activity
- Reg D amounts are cumulative filing totals, not individual round sizes
- SI2 Technologies $1.1B single filing likely PE/growth equity, not typical VC
- 201K entity resolution review pairs — needs better blocking strategy at scale
- DB column names: `canonical_name` (not `name`), `headquarters_location` (not `location`), `confidence_score` (not `confidence`), `evidence` (not `raw_data`) on signals table
- Enum values are UPPERCASE in the database: `STARTUP`, `ACTIVE`, `SBIR_PHASE_2`, etc.
- SBIR dates are mixed format: MM/DD/YYYY (older) vs YYYY-MM-DD (2023+); use `json_extract(raw_data, '$.Proposal Award Date')` for award dates

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
| RAG engine | `processing/rag_engine.py` |
| RAG CLI | `scripts/rag_query.py` |
| Report generation (prospects) | `scripts/generate_prospect_report.py` |
| Report generation (PDF) | `scripts/generate_pdf_report.py` |
| Report generation (Phase II) | `scripts/generate_phase2_pdf.py` |
| QA verification | `scripts/qa_report_data.py` |
| Policy signal-response PoC | `scripts/policy_signal_poc.py` |
| Signal-response framework | `processing/signal_response.py` |
| Benchmark runner | `scripts/run_benchmarks.py` |
| Knowledge graph engine | `processing/knowledge_graph.py` |
| Graph builder/query CLI | `scripts/build_graph.py` |
| Graph visualization | `scripts/visualize_graph.py` |
| Investor extraction | `scripts/extract_investors.py` |
| Agency materialization | `scripts/materialize_agencies.py` |
| Technology clusters | `scripts/tech_clusters.py` |
| Policy config | `config/policy_priorities.yaml` |
| DB models | `processing/models.py` |

---

## Strategic Context

**Business model:** Intelligence company, not SaaS platform. Reports are the product, engine is the back office. Defensibility: outcome tracking time series (time-locked), human intelligence from client feedback, analyst reputation. Revenue model: curated reports ($2-5K), quarterly intelligence briefs ($10-20K/yr).

**Architecture philosophy:**
- Local models: MiniLM-L6-v2 for embeddings/similarity (free, fast)
- API LLM: Claude for classification, scoring, RAG reasoning (~$55 for full universe)
- Future: predictive model on outcome tracking data (6-12 months)
- RAG connects embeddings (finding) to Claude (reasoning) — not yet connected to report generator as single command

**Key validation:** Funding raise detector shows 80% true prediction rate with 35-month median lead time. SBIR phase transitions predict private capital raises ~3 years ahead — this is the core defensible insight. Phase II Signal report ($8.48B across 164 companies) is the proof point.

Don (first client) feedback: "All new SBIR companies to me!" He suggested targeting VCs + Primes as customers ("matchmaker" positioning).

---

*This document should give any Claude instance enough context to continue work on Defense Alpha.*
