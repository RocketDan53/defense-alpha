# Defense Alpha: Project Context

**Last Updated:** February 6, 2026
**Purpose:** Spin up a new Claude instance with full context on the Defense Alpha project

---

## What Is Defense Alpha

A Python-based defense intelligence platform that aggregates government and private market data to identify investment signals in defense technology companies. Built to surface emerging companies with real traction for defense investors, sales consultants, and BD teams.

**Core value proposition:** Systematic signal detection + policy alignment scoring to identify which SBIR-stage companies are most likely to win production contracts.

---

## Current Data State (Feb 6, 2026)

### Entity Counts by Type
| Type | Count | Description |
|------|-------|-------------|
| STARTUP | 4,084 | Emerging defense tech companies |
| PRIME | 405 | Large defense contractors |
| RESEARCH | 14 | Universities, FFRDCs, APLs |
| INVESTOR | 0 | (Not yet populated) |
| AGENCY | 0 | (Not yet populated) |

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
| Signals (active) | 1,944 | - | 13 signal types |
| Outcome Events | 23 | - | NEW: Signal validation tracking |
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
- 10 priority areas with budget-derived weights
- Async concurrency support (10 concurrent API calls)
- Pacific/Indo-Pacific relevance flagging
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
python -m processing.policy_alignment --limit 100 --async --concurrency 10
python -m processing.policy_alignment --skip-scored  # Resume from where you left off
```

### 3. Outcome Tracking ✅ NEW (Partial)
**File:** `scripts/track_outcomes.py`
**Model:** `OutcomeEvent` in `processing/models.py`

Tracks what happens to entities after signals are detected:
- Links outcomes back to related signals
- Calculates `months_since_signal` for prediction accuracy
- Deduplicates via `source_key`

**Outcome Types:**
| Type | Status | Description |
|------|--------|-------------|
| new_contract | ✅ Working | Won DoD/federal contract |
| funding_raise | ⏸️ Stub | New Reg D / VC round |
| sbir_advance | ⏸️ Stub | Phase progression |
| acquisition | ⏸️ Stub | Acquired by another entity |
| new_agency | ⏸️ Stub | Contract with new DoD branch |
| recompete_loss | ⏸️ Stub | Lost contract renewal |
| company_inactive | ⏸️ Stub | No activity 12+ months |
| sbir_stall | ⏸️ Stub | Phase I with no advancement |

**Usage:**
```bash
python scripts/track_outcomes.py --since 2025-01-01 --dry-run
python scripts/track_outcomes.py --since 2025-01-01 --detector new_contract
```

### 4. Report Generation ✅ COMPLETE
**Files:** `scripts/generate_prospect_report.py`, `scripts/generate_pdf_report.py`

Generates branded PDF/Markdown reports for specific verticals:
- RF & Communications Report v2 (55 companies)
- Execution-weighted combined scoring
- Top 10 detailed profiles with policy analysis

**Latest Report:** `reports/rf_comms_v2.pdf` (Feb 6, 2026)

---

## Key Decisions Made

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
**Decision:** `china_pacing` removed from weighted policy scoring. Applied as a tag for Pacific-relevant companies instead.

**Rationale:** Not a budget line item - it's a strategic posture that manifests through other priorities. Companies get `pacific_relevance: true` flag when relevant.

### 3. Entity Type Reclassification
**Decision:** Split mislabeled "startups" into three categories:
- **PRIME (263 entities):** Large contractors (L3, Rockwell Collins, Accenture, IBM, etc.)
- **RESEARCH (14 entities):** Universities, FFRDCs, APLs (Johns Hopkins APL, RAND, etc.)
- **STARTUP (10 scaled):** Companies that grew large but started as startups (SpaceX, BlueHalo, etc.)

**Rationale:** Outcome tracking was measuring prime contractor activity, not startup success. Clean entity types enable accurate signal validation.

### 4. Async Concurrency for API Calls
**Decision:** Added `--async --concurrency 10` to policy alignment scorer.

**Rationale:** Sequential processing was ~4 entities/min (4+ hours for 1,000). Async with semaphore achieves ~40 entities/min. Built-in retry for 429/503 errors.

---

## Files Created/Modified (Feb 6, 2026)

### New Files
| File | Purpose |
|------|---------|
| `scripts/track_outcomes.py` | Outcome tracking script |
| `reports/rf_comms_v2.md` | Updated RF report (55 companies) |
| `reports/rf_comms_v2.pdf` | PDF version of RF report |

### Modified Files
| File | Changes |
|------|---------|
| `processing/models.py` | Added `OutcomeType` enum, `OutcomeEvent` model, `RESEARCH` entity type |
| `processing/policy_alignment.py` | Added async support, concurrency, skip-scored flag |

---

## Next Tasks (Priority Order)

### Immediate (This Week)
1. **Implement `funding_raise` detector** in `track_outcomes.py`
   - Integrate with SEC EDGAR scraper
   - Detect new Reg D filings for entities with signals
   - Link back to related signals

2. **Refresh data pulls**
   - USASpending: `python scrapers/usaspending.py --start-date 2025-01-01`
   - SBIR: `python scrapers/sbir.py`
   - SEC EDGAR: `python scrapers/sec_edgar.py --start-date 2025-01-01`

3. **Validate RF report classifications** (spot-check completed Feb 6):
   - PRONTO.AI → ✅ Correct (wireless mesh nodes)
   - Leolabs Federal → ✅ Correct (S-Band phased array radar)
   - PRASAD, SARITA → ✅ Correct (C-Band HPM RF Suite)
   - LUNAR RESOURCES → ❌ Reclassified to OTHER (lunar mining company)

### Medium Priority
4. **Classify remaining 3,431 entities**
   - Run business classifier in batches
   - Prioritize entities with active signals

5. **Reclassify Dynetics to PRIME**
   - Acquired by Leidos in 2020
   - Currently in "scaled startup" list

### Lower Priority
6. **Build async into policy_alignment.py** (already done, documented above)

7. **Research AGILE-BOT LLC**
   - $88.9M in contracts, unclear if startup or contractor
   - Need to determine correct entity_type

---

## Strategic Roadmap (4 Phases)

### Phase 1: Signal Validation (Current)
**Goal:** Prove signals predict outcomes
- ✅ Outcome tracking model built
- ✅ new_contract detector working
- ⏸️ Need more time/data to measure prediction accuracy
- ⏸️ funding_raise and sbir_advance detectors pending

### Phase 2: Data Depth (Next)
**Goal:** Comprehensive data coverage
- [ ] Full USASpending backfill (current: 5K, target: 50K+)
- [ ] Full SBIR historical pull (2015-present)
- [ ] SAM.gov CAGE code enrichment
- [ ] FPDS integration for contract modifications

### Phase 3: Product Surface
**Goal:** User-facing tools
- [ ] Weekly email alerts for tracked entities
- [ ] Watchlist functionality
- [ ] Web dashboard / API
- [ ] Automated report generation

### Phase 4: Network Effects
**Goal:** Multi-user value creation
- [ ] User tagging and annotations
- [ ] Consensus signals from multiple users
- [ ] Community-validated classifications

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
│   ├── business_classifier.py  # LLM-based core business classification
│   ├── policy_alignment.py # NDS priority scoring (async support)
│   ├── signal_detector.py  # All signal detection logic
│   └── technology_tagger.py # Keyword-based tech categorization
├── scripts/
│   ├── detect_signals.py
│   ├── calculate_composite_scores.py
│   ├── run_entity_resolution.py
│   ├── find_similar.py     # Semantic search over SBIR embeddings
│   ├── track_outcomes.py   # NEW: Outcome tracking for signal validation
│   ├── tech_clusters.py    # K-means clustering of SBIR abstracts
│   └── generate_prospect_report.py # PDF/MD report generator
├── reports/
│   ├── rf_comms_v2.md      # Latest RF report (55 companies)
│   └── rf_comms_v2.pdf
├── config/
│   └── policy_priorities.yaml  # NDS priority definitions and weights
├── data/
│   └── defense_alpha.db    # SQLite database
├── docs/
│   └── PROJECT_CONTEXT.md  # This file
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
policy_alignment (JSON: scores, top_priorities, tailwind_score, pacific_relevance, reasoning)
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

### outcome_events (NEW)
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
- 5,147 contracts ($805B), 3,632 funding events, 1,944 active signals
- 1,072 entities classified by core business
- 1,038 entities scored for policy alignment
- 23 outcome events tracked

Current priorities:
1. Implement funding_raise detector in track_outcomes.py
2. Refresh data pulls from USASpending/SBIR/SEC EDGAR
3. Classify remaining 3,431 entities

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

---

## Strategic Context

From recent analysis on defensibility:
- **Moat is in data infrastructure** (pipelines, connectors, entity resolution) - not the LLM layer
- **Classification is plumbing** - useful but not defensible
- **Outcome tracking is defensible** - backtest which signals predict success
- **Workflow integration creates stickiness** - alerts, watchlists, embedded in user's daily process

Don (first client) feedback: "All new SBIR companies to me!" - validation that filtering works. He suggested targeting VCs + Primes as customers ("matchmaker" positioning).

---

*This document should give any Claude instance enough context to continue work on Defense Alpha.*
