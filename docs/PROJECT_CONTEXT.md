# Defense Alpha: Project Context

**Last Updated:** February 9, 2026
**Purpose:** Spin up a new Claude instance with full context on the Defense Alpha project

---

## What Is Defense Alpha

A Python-based defense intelligence platform that aggregates government and private market data to identify investment signals in defense technology companies. Built to surface emerging companies with real traction for defense investors, sales consultants, and BD teams.

**Core value proposition:** Systematic signal detection + policy alignment scoring to identify which SBIR-stage companies are most likely to win production contracts.

---

## Current Data State (Feb 9, 2026)

### Entity Counts by Type
| Type | Count | Description |
|------|-------|-------------|
| STARTUP | 4,084 | Emerging defense tech companies |
| PRIME | 405 | Large defense contractors (reclassified from startup) |
| RESEARCH | 14 | Universities, FFRDCs, APLs (reclassified from startup) |
| INVESTOR | 0 | (Not yet populated) |
| AGENCY | 0 | (Not yet populated) |
| **Total (unmerged)** | **4,503** | |

### Entity Counts by Core Business (1,072 classified)
| Classification | Count | Examples |
|----------------|-------|----------|
| software | 448 | AI/ML, cybersecurity, C2 software |
| components | 334 | Sensors, materials, subsystems |
| aerospace_platforms | 93 | Drones, satellites, aircraft |
| other | 63 | Doesn't fit categories |
| rf_hardware | 55 | Radios, antennas, radar, EW |
| unclassified | 34 | Low-confidence classifications |
| services | 26 | Consulting, support, training |
| systems_integrator | 19 | Solution integrators |
| (null - not yet classified) | 3,431 | Awaiting classification |

### Other Data
| Table | Records | Value | Notes |
|-------|---------|-------|-------|
| Contracts | 5,147 | $804.7B | USASpending data |
| Funding Events | 3,632 | - | SBIR + Reg D combined |
| Signals | 1,944 | - | 13 signal types |
| Outcome Events | 23 | - | Signal validation tracking |
| Policy Alignments | 1,038 | - | Entities scored against NDS priorities |

---

## Systems Status

### 1. Business Classifier ✅ COMPLETE
**File:** `processing/business_classifier.py`

Classifies entities into core business categories based on SBIR award analysis:
- Uses Claude API to analyze award titles and abstracts
- Outputs: classification, confidence score (0-1), reasoning
- 1,072 entities classified, 3,431 remaining

**Usage:**
```bash
python -m processing.business_classifier --limit 100
python -m processing.business_classifier --entity "PHASE SENSITIVE INNOVATIONS"
```

### 2. Policy Alignment Scorer ✅ COMPLETE
**File:** `processing/policy_alignment.py`

Scores entities against FY2026 National Defense Strategy priorities:
- 10 priority areas with budget-derived weights (loaded from `config/policy_priorities.yaml`)
- Async concurrency support (`--async --concurrency 10`, ~40 entities/min)
- `--skip-scored` flag to resume interrupted runs
- Pacific/Indo-Pacific relevance flagging (boolean tag, not weighted)
- 1,038 entities scored

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
python -m processing.policy_alignment --all --async --concurrency 10
python -m processing.policy_alignment --skip-scored    # Resume from where you left off
python -m processing.policy_alignment --names "SHIELD AI" "ANDURIL"
python -m processing.policy_alignment --show-prompt    # Review prompt template
```

### 3. Outcome Tracking ✅ PARTIAL
**File:** `scripts/track_outcomes.py`
**Model:** `OutcomeEvent` in `processing/models.py`

Tracks what happens to entities after signals are detected:
- Links outcomes back to related signals via `related_signal_ids`
- Calculates `months_since_signal` for prediction accuracy measurement
- Deduplicates via `source_key`
- Only tracks STARTUP entities (skips primes/research)

**Outcome Types:**
| Type | Status | Description |
|------|--------|-------------|
| new_contract | ✅ Working | Won DoD/federal contract (23 tracked) |
| funding_raise | ⏸️ Stub | New Reg D / VC round |
| sbir_advance | ⏸️ Stub | Phase progression (I→II→III) |
| acquisition | ⏸️ Stub | Acquired by another entity |
| new_agency | ⏸️ Stub | Contract with new DoD branch |
| recompete_loss | ⏸️ Stub | Lost contract renewal |
| company_inactive | ⏸️ Stub | No activity 12+ months |
| sbir_stall | ⏸️ Stub | Phase I with no advancement 24+ months |

**Usage:**
```bash
python scripts/track_outcomes.py --since 2025-01-01 --dry-run
python scripts/track_outcomes.py --since 2025-01-01 --detector new_contract
```

### 4. Entity Types ✅ COMPLETE
**Files:** `processing/models.py` (EntityType enum)

Clean entity type taxonomy after reclassification:
- **STARTUP:** Emerging defense tech companies (core tracking population)
- **PRIME:** Large defense contractors (L3, Rockwell Collins, Accenture, IBM, etc.)
- **RESEARCH:** Universities, FFRDCs, APLs (Johns Hopkins APL, RAND, etc.)
- **INVESTOR / AGENCY:** Schema exists, not yet populated

### 5. Report Generation ✅ COMPLETE
**Files:** `scripts/generate_prospect_report.py`, `scripts/generate_pdf_report.py`

Generates branded PDF/Markdown reports for specific verticals:
- RF & Communications Report v2 (55 companies)
- Execution-weighted combined scoring
- Top 10 detailed profiles with policy analysis

**Latest Report:** `reports/rf_comms_v2.pdf` (Feb 6, 2026)

---

## Key Decisions Made and Why

### 1. Combined Score Formula (Execution-Weighted)
```
combined = 0.55 × norm_composite + 0.30 × policy_tailwind + 0.15 × contract_tier
```

**Rationale:** Original formula over-weighted policy alignment, causing companies like AscendArc (no contracts) to rank above proven performers. New formula:
- 55% signal strength (SBIR progression, multi-agency, etc.)
- 30% policy tailwind (NDS priority alignment)
- 15% execution bonus (tiered by contract value)

**Contract Tier:**
- 0 contracts: 0.0
- <$1M contracts: 0.5
- ≥$1M contracts: 1.0

### 2. China Pacing: Tag Not Weight
**Decision:** `china_pacing` removed from weighted policy scoring. Applied as a boolean tag for Pacific-relevant companies instead.

**Rationale:** Not a budget line item — it's a strategic posture that manifests through other priorities (space, autonomous systems, contested logistics). Companies get `pacific_relevance: true` flag in their policy_alignment JSON when relevant. Keeping it as a weight would double-count capabilities already captured by the 10 priority areas.

### 3. Entity Type Reclassification Approach
**Decision:** Split mislabeled "startups" into proper categories via SQL reclassification:
- **PRIME (263 reclassified → 405 total):** Large contractors (L3, Rockwell Collins, Accenture, IBM, etc.)
- **RESEARCH (14 entities):** Universities, FFRDCs, APLs (Johns Hopkins APL, RAND, etc.)
- **STARTUP (10 "scaled"):** Companies that grew large but started as startups (SpaceX, BlueHalo, etc.) — kept as startup because their growth trajectory IS the signal

**Rationale:** Outcome tracking was measuring prime contractor activity, not startup success. Clean entity types enable accurate signal validation. A prime winning another contract is not a useful "outcome" — a startup winning its first production contract is.

### 4. Async Concurrency for API Calls
**Decision:** Added `--async --concurrency 10` to policy alignment scorer with `asyncio.Semaphore`.

**Rationale:** Sequential processing was ~4 entities/min (4+ hours for 1,000). Async achieves ~40 entities/min. Pre-fetches all entity data synchronously, then runs concurrent Claude API calls. Built-in retry for 429/503 errors.

### 5. Policy Weights from Budget Data
**Decision:** Weights derived from actual FY25→FY26 President's Budget Request growth rates, not subjective importance.

**Rationale:** Budget growth is the best available signal for where DoD is actually putting money. Space resilience gets highest weight (0.235) because it saw +38% growth. Hypersonics gets lowest (0.015) because it saw -43% cuts. This makes the scoring predictive of where contracts will flow.

---

## Files Created/Modified

### Session: Feb 6, 2026
| File | Purpose |
|------|---------|
| `scripts/track_outcomes.py` | **NEW** — Outcome tracking script with new_contract detector |
| `reports/rf_comms_v2.md` | **NEW** — Updated RF report (55 companies) |
| `reports/rf_comms_v2.pdf` | **NEW** — PDF version of RF report |
| `processing/models.py` | **MODIFIED** — Added `OutcomeType` enum, `OutcomeEvent` model, `RESEARCH` entity type |
| `processing/policy_alignment.py` | **MODIFIED** — Added async support, concurrency, skip-scored flag |
| `config/policy_priorities.yaml` | **MODIFIED** — Externalized priority definitions and weights |
| `processing/business_classifier.py` | **NEW** — LLM-based core business classification |

### Session: Feb 9, 2026
| File | Purpose |
|------|---------|
| `docs/PROJECT_CONTEXT.md` | **UPDATED** — Comprehensive project context refresh |
| `PROJECT_CONTEXT.md` | **UPDATED** — Root copy for easy access |

---

## Next Tasks (Priority Order)

### Immediate
1. **Implement `funding_raise` detector** in `scripts/track_outcomes.py`
   - Wire up SEC EDGAR scraper (`scrapers/sec_edgar.py`) to detect new Reg D filings
   - Match filings to entities with active signals
   - Create `OutcomeEvent` with `outcome_type=FUNDING_RAISE`
   - Link back to related signals, calculate `months_since_signal`
   - Source key format: `reg_d:{filing_id}` for dedup

2. **Refresh data pulls** (data is getting stale)
   - USASpending: `python scrapers/usaspending.py --start-date 2025-01-01`
   - SBIR: `python scrapers/sbir.py`
   - SEC EDGAR: `python scrapers/sec_edgar.py --start-date 2025-01-01`
   - After refresh: re-run signal detection and outcome tracking

3. **Spot-check RF report misclassifications**
   - PRONTO.AI — verify rf_hardware classification (wireless mesh nodes)
   - Leolabs Federal — verify rf_hardware classification (S-Band phased array radar)
   - PRASAD, SARITA — verify rf_hardware classification (C-Band HPM RF Suite)
   - LUNAR RESOURCES — was reclassified to OTHER (lunar mining company, not RF)
   - Check for other false positives in the 55-company list

4. **Build async concurrency into `policy_alignment.py`** (already discussed, low priority)
   - Async mode already implemented and working
   - Consider adding retry logic with exponential backoff for production runs
   - Consider adding progress persistence for crash recovery on large batches

### Medium Priority
5. **Classify remaining 3,431 entities**
   - Run business classifier in batches: `python -m processing.business_classifier --limit 100`
   - Prioritize entities with active signals first

6. **Reclassify Dynetics to PRIME**
   - Acquired by Leidos in 2020, currently in "scaled startup" list

7. **Research AGILE-BOT LLC**
   - $88.9M in contracts, unclear if startup or contractor
   - Need to determine correct entity_type

---

## Strategic Roadmap (4 Phases)

### Phase 1: Signal Validation (Current — Q1 2026)
**Goal:** Prove signals predict outcomes
**Timeline:** Now through March 2026
- ✅ Outcome tracking model built (`OutcomeEvent` table, source_key dedup)
- ✅ `new_contract` detector working (23 outcomes tracked)
- ✅ Entity reclassification complete (clean startup population)
- ⏸️ `funding_raise` detector — next to implement
- ⏸️ `sbir_advance` detector — after funding_raise
- ⏸️ Need 3-6 months of data to measure prediction accuracy
- **Success metric:** Can show that entities with high composite scores win contracts at higher rates

### Phase 2: Data Depth (Q2 2026)
**Goal:** Comprehensive data coverage for better signal accuracy
**Timeline:** April–June 2026
- [ ] Full USASpending backfill (current: 5K contracts, target: 50K+)
- [ ] Full SBIR historical pull (2015-present)
- [ ] SAM.gov CAGE code enrichment (better entity matching)
- [ ] FPDS integration for contract modifications
- [ ] Classify all 3,431 remaining entities
- **Success metric:** >90% of SBIR companies have complete data profiles

### Phase 3: Product Surface (Q3 2026)
**Goal:** User-facing tools that create workflow stickiness
**Timeline:** July–September 2026
- [ ] Weekly email alerts for tracked entities
- [ ] Watchlist functionality (per-user entity tracking)
- [ ] Web dashboard / API
- [ ] Automated report generation (beyond manual RF report)
- **Success metric:** 5+ active users checking alerts weekly

### Phase 4: Network Effects (Q4 2026+)
**Goal:** Multi-user value creation
**Timeline:** October 2026+
- [ ] User tagging and annotations
- [ ] Consensus signals from multiple users
- [ ] Community-validated classifications
- **Success metric:** User contributions improve data quality measurably

---

## Architecture

```
defense-alpha/
├── scrapers/
│   ├── usaspending.py      # DoD contracts from USASpending API
│   ├── sbir.py             # SBIR/STTR awards
│   └── sec_edgar.py        # SEC Form D private funding
├── processing/
│   ├── models.py           # SQLAlchemy models (Entity, Contract, Signal, OutcomeEvent, etc.)
│   ├── database.py         # DB connection and session management
│   ├── entity_resolver.py  # Deduplication with fuzzy matching
│   ├── entity_resolution/  # Advanced resolution (resolver.py, matchers.py)
│   ├── business_classifier.py  # LLM-based core business classification
│   ├── policy_alignment.py # NDS priority scoring (sync + async)
│   ├── signal_detector.py  # All signal detection logic (13 types)
│   └── technology_tagger.py # Keyword-based tech categorization
├── scripts/
│   ├── detect_signals.py
│   ├── calculate_composite_scores.py
│   ├── run_entity_resolution.py
│   ├── tag_sbir_entities.py
│   ├── find_similar.py     # Semantic search over SBIR embeddings
│   ├── track_outcomes.py   # Outcome tracking for signal validation
│   ├── tech_clusters.py    # K-means clustering of SBIR abstracts
│   ├── generate_prospect_report.py  # Markdown report generator
│   └── generate_pdf_report.py       # PDF report generator
├── reports/
│   ├── rf_comms_v2.md      # Latest RF report (55 companies)
│   └── rf_comms_v2.pdf
├── config/
│   ├── policy_priorities.yaml  # NDS priority definitions and weights
│   └── settings.py             # App configuration
├── data/
│   └── defense_alpha.db    # SQLite database
├── docs/
│   └── PROJECT_CONTEXT.md  # This file
├── PROJECT_CONTEXT.md      # Root copy for easy access
└── requirements.txt
```

---

## Database Schema (Key Tables)

### entities
```sql
id, canonical_name, entity_type (startup/prime/research/investor/agency)
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
amount, event_date, investors_awarders (JSON), raw_data (JSON)
```

### signals
```sql
id, entity_id (FK), signal_type, confidence_score (0-1)
detected_date, evidence (JSON), status (active/expired/validated/false_positive)
```

### outcome_events
```sql
id, entity_id (FK)
outcome_type (new_contract/funding_raise/sbir_advance/acquisition/new_agency/recompete_loss/company_inactive/sbir_stall)
outcome_date, outcome_value
details (JSON), source, source_key (unique, for dedup)
related_signal_ids (JSON), months_since_signal
```

---

## How to Start a Session

```
I'm working on defense-alpha at ~/projects/defense-alpha

cd ~/projects/defense-alpha && source venv/bin/activate

Defense intelligence platform with:
- 4,503 entities (4,084 startups, 405 primes, 14 research)
- 5,147 contracts ($805B), 3,632 funding events, 1,944 signals (13 types)
- 1,072 entities classified by core business
- 1,038 entities scored for policy alignment
- 23 outcome events tracked (new_contract detector only)

Current priorities:
1. Implement funding_raise detector in track_outcomes.py
2. Refresh data pulls from USASpending/SBIR/SEC EDGAR
3. Spot-check RF report misclassifications
4. Classify remaining 3,431 entities

Show me current DB stats to confirm state, then let's continue.
```

---

## Key Files to Reference

| Purpose | File |
|---------|------|
| Entity resolution | `processing/entity_resolver.py` |
| Signal detection | `processing/signal_detector.py` |
| Business classification | `processing/business_classifier.py` |
| Policy alignment | `processing/policy_alignment.py` |
| Outcome tracking | `scripts/track_outcomes.py` |
| Report generation | `scripts/generate_prospect_report.py` |
| Semantic search | `scripts/find_similar.py` |
| Policy config | `config/policy_priorities.yaml` |
| DB models | `processing/models.py` |

---

## Strategic Context

From recent analysis on defensibility:
- **Moat is in data infrastructure** (pipelines, connectors, entity resolution) — not the LLM layer
- **Classification is plumbing** — useful but not defensible
- **Outcome tracking is defensible** — backtest which signals predict success; this is the unique dataset
- **Workflow integration creates stickiness** — alerts, watchlists, embedded in user's daily process

Don (first client) feedback: "All new SBIR companies to me!" — validation that filtering works. He suggested targeting VCs + Primes as customers ("matchmaker" positioning).

---

*This document should give any Claude instance enough context to continue work on Defense Alpha.*
