# Aperture Signals: Project Context

**Last Updated:** March 5, 2026
**Purpose:** Spin up a new Claude instance with full context on the Aperture Signals project

---

## What Is Aperture Signals

A Python-based defense intelligence platform that aggregates government and private market data to identify investment signals in defense technology companies. Built to surface emerging companies with real traction for defense investors, sales consultants, and BD teams.

**Core value proposition:** Systematic signal detection + policy alignment scoring + freshness-weighted composite ranking to identify which SBIR-stage companies are most likely to win production contracts. Web enrichment pipeline closes data gaps (OTA contracts, full funding round sizes) that make reports credible to insiders.

**Business model:** Intelligence company, not SaaS platform. Reports are the product, the engine is the back office. Revenue model: curated reports ($250-500 per brief for sales consultants, $2-5K for investors), quarterly intelligence briefs ($10-20K/yr). Defensibility comes from outcome tracking time series (time-locked), human intelligence from client feedback, and analyst reputation. First client (Don) has received 3 free deliverables; pricing conversation pending on next request.

---

## Current Data State (Mar 5, 2026)

### Entity Counts by Type
| Type | Count | Description |
|------|-------|-------------|
| STARTUP | 9,655 | Emerging defense tech companies (core tracking population) |
| PRIME | 876 | Large defense contractors |
| NON_DEFENSE | 1,441 | No defense footprint or merged duplicates |
| RESEARCH | 22 | Universities, FFRDCs, APLs |
| **Total (unmerged)** | **~11,994** | After entity resolution (834 merges from 11,048+) |

### Classification Pipeline Status ✅ COMPLETE
| Stage | Count | Description |
|-------|-------|-------------|
| Classified + policy scored | 8,798 | Business classification + policy alignment complete (SBIR-based + contract-based) |
| Classified (no policy score) | 40 | Classified but not yet scored |
| Unclassified (Reg D only) | 857 | Only Reg D filings, no SBIR/contract data for classification |
| Non-defense (excluded) | 1,441 | No defense footprint or resolved merges |

### Data Volumes
| Table | Records | Value | Notes |
|-------|---------|-------|-------|
| Contracts | 13,904 | $1.16T+ | USASpending + 752 OTA contracts from SAM.gov |
| Funding Events | 32,659+ | - | SBIR + Reg D + VC combined (88 duplicates removed Mar 5) |
| Signals | 17,297 | - | 15+ signal types (active only), tiered freshness decay, refreshed Mar 5 |
| Outcome Events | 114 | - | 23 new_contract + 91 funding_raise |
| SBIR Embeddings | 27,529 | - | 100% coverage, all-MiniLM-L6-v2 |
| Policy Alignments | 8,798 | - | All classified startups scored (SBIR-based + contract-based) |
| Relationships | 39,712 | - | Knowledge graph (rebuilt Feb 24) |
| Entity Merges | 834 | - | High-confidence auto-merges |
| Review Queue | 201,328 | - | Pairs flagged for manual review |
| Fund Positions | 120 | - | All 3 strategies deployed Q1 2026 (60 signal + 60 benchmark, 58 unique companies) |
| Composite Scores | 7,137 | - | Entities with freshness-adjusted composite scores |

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
- SAM.gov OTA scraper (`scrapers/sam_gov_ota.py`) — 752 OTA contracts ingested, SAM.gov rate-limiting paused further scraping
- Comparables engine — validated on Scout Space (43 comps, 5x raise multiplier finding); now includes Jaccard technology tag similarity (weight 2.0)
- Deal intelligence brief generator (`scripts/aperture_query.py`) — single-command 9-section deal brief with comparables, signals, policy alignment, lifecycle narrative, web verification, and Claude analyst assessment
- Web verification layer (`scripts/aperture_query.py:build_verification_notes()`) — Claude + web_search tool cross-references Aperture data against public sources, outputs CONFIRMED/GAP/NOTE findings; now passes contract/funding details for proper dedup (Feb 27)
- Web enrichment pipeline (`scripts/enrich_entity.py`) — two-phase Claude + web_search: search phase finds data, structure phase extracts JSON; stages findings in `enrichment_findings` table for review/approval before ingesting into contracts/funding_events; tags all ingested records with `source = "web_enrichment"` for provenance
- Branded PDF generator (`scripts/generate_darkhive_pdf.py`) — Aperture Signals branded PDFs with compact layout, PROPRIETARY & CONFIDENTIAL marking, left-aligned tables; reusable template for all client-facing briefs
- Analyst note PDF generator (`scripts/generate_analyst_note.py`) — one-page branded PDF for client-facing competitive positioning notes
- SEC EDGAR Form D competitor research — EDGAR API integration for capitalization tiering of competitors by Reg D filing amounts
- Key Contacts & Investor Syndicate section — new standard brief section with company leadership, investor syndicate with named individuals, and network analysis notes (Feb 27)
- Notional fund system (`Fund/fund_manager.py`) — VC-style portfolio construct for thesis validation; strategy definition, cohort deployment with matched-pair benchmarks + bootstrap baselines, milestone tracking, performance reporting; 3 strategies deployed Q1 2026 (Next Wave, Policy Tailwind, Signal Momentum); 120 positions (60 signal + 60 matched benchmark), 58 unique companies (Mar 3)
- Fund redeployment tool (`Fund/redeploy_fund.py`) — drops existing cohorts for a vintage and provides redeployment instructions; supports `--dry-run`
- Fund overview PDF generator (`Fund/generate_fund_overview.py`) — branded one-sheeter with strategy summaries, portfolio tables, entry-state differentials, benchmark methodology, and disclaimer; uses reportlab
- Contract-based business classifier (`processing/business_classifier.py --contracts-only`) — extends classification to entities with contracts but no SBIR awards using NAICS/PSC codes; 3,329 entities classified Mar 5
- Contract-based policy alignment scoring (`processing/policy_alignment.py`) — scores entities using contract data (agencies, NAICS, PSC) when no SBIR data available; 3,329 entities scored Mar 5
- Data quality audit (`scripts/audit_data_quality.py`) — comprehensive infrastructure audit covering entity integrity, funding accuracy, signal correctness, policy alignment consistency; 5 sections, returns exit code 0/1 (Mar 5)
- Employment target identifier (`scripts/employment_targets.py`) — scores startups for employment fit based on composite signals, signal diversity, policy tailwind, momentum recency, KOP alignment, and domain preference multiplier; outputs top 20 profiles + signal heatmap + sector concentration + dark horse list (Mar 5)

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
2. **Phase II Signal** — 164 companies, $8.48B thesis, shipped (`reports/phase2_signal_report.pdf`). Ready to send to Konstantine (teaser first, let him pull the report). QA: 178/178 checks passed, zero discrepancies.
3. **Scout Space Comparables** — 43 comparable companies, contract traction = 5x raise multiplier (`reports/comparables_scout_space.md`). Raise expectation: $7-12M base, $15-25M upside with contract traction.
4. **Scout Space Deal Brief** — Full 8-section intelligence brief with comparables (76 comps), signal profile (Tier 2, 4.88), policy alignment (space resilience 0.90), lifecycle narrative, and Claude analyst assessment (`reports/brief_scout_space.md`)
5. **Starfish Space Deal Brief** — Deal brief generated via aperture_query.py (`reports/brief_starfish_space.md`)
6. **Firestorm Labs Deal Brief** — Full 9-section deal brief with web verification, technology-tag-aware comparables (`reports/brief_firestorm_labs_v3.md`)
7. **Firestorm Labs Analyst Note** — One-page PDF competitive positioning note for Drone Dominance program (`reports/firestorm_drone_dominance.pdf`). Includes SEC EDGAR capitalization tiering of 24 UAS competitors.
8. **Investor Leads for Don** — Anti-jam GPS/PNT investor syndicate analysis extracted from SEC EDGAR Form D director data
9. **X-Bow Launch Systems Deal Brief (enriched)** — First brief generated after web enrichment pipeline. Before: "No contracts found," $92.5M raised. After: 14 contracts ($450.5M including 6 OTAs), "Scaling" lifecycle. Validated enrichment pipeline closes credibility gaps.
10. **Darkhive Inc. Deal Brief** — Client-facing brief with Key Contacts & Investor Syndicate section (Goodson/Turner/Moroniti/Tisdale + 6 investor entities with named individuals), Client Opportunity section (antenna/RF integration for YellowJacket variants), branded PDF delivered to Don (`reports/darkhive_brief.pdf`). Third free deliverable before pricing conversation.

---

## Systems Status

### 1. Business Classifier ✅ COMPLETE
**File:** `processing/business_classifier.py`

Classifies entities into core business categories based on SBIR award or contract analysis:
- Uses Claude API (Sonnet) to analyze up to 10 most recent SBIR award titles (default) or contract data (--contracts-only)
- Outputs: classification, confidence score (0-1), reasoning
- **8,838 entities classified** (5,488 SBIR-based Feb 10 + 3,329 contract-based Mar 5 + 21 re-classified)
- Supports async mode: `--async --concurrency 10` (~10x faster)
- `--skip-classified` flag to avoid re-processing
- `--contracts-only` flag classifies entities with contracts but no SBIRs using NAICS/PSC codes and agency data
- Contract-based classifications tagged with `[contract-based classification]` prefix in `core_business_reasoning`

**Usage:**
```bash
python -m processing.business_classifier --all --async --concurrency 10 --skip-classified
python -m processing.business_classifier --contracts-only --async --concurrency 10 --skip-classified
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
- **8,798 entities scored** (5,488 SBIR-based + 3,329 contract-based Mar 5; 120 AEROSPACE_PLATFORMS re-scored Feb 24)
- Now scores entities using contract data (agencies, NAICS, PSC codes) as fallback when no SBIR data available
- Contract-based scoring uses `CONTRACT_ALIGNMENT_PROMPT` and tags reasoning with `[contract-based scoring]` prefix
- Entity selection no longer requires SBIR data — includes all classified startups
- Structured examples in prompt for UAS/drone, counter-UAS, satellite, and general software companies with score range guidance
- `autonomous_systems` description expanded to include UAS/UAV/drones, counter-UAS, Group 1-5 platforms, attritable systems

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
| customer_concentration | 1,200 | -1.5 | NO_DECAY | >80% revenue from one agency |
| sbir_to_vc_raise | 905 | +2.0 | SLOW_DECAY | VC validates gov't R&D (loose) |
| multi_agency_interest | 777 | +1.5 | NO_DECAY | Contracts from 3+ agencies |
| funding_velocity | 672 | +1.5 | FAST_DECAY | 2+ Reg D filings in 18 months |
| first_dod_contract | 422 | +1.0 | FAST_DECAY | New entrant to defense |
| sbir_stalled | 417 | -2.0 | NO_DECAY | 2+ Phase I, zero Phase II |
| gone_stale | 353 | -1.5 | NO_DECAY | No activity in 24+ months |
| sbir_to_contract_transition | 325 | +3.0 | SLOW_DECAY | SBIR to procurement pipeline |
| time_to_contract | 300 | +2.0 | SLOW_DECAY | Quick SBIR to procurement |
| rapid_contract_growth | 293 | +2.5 | FAST_DECAY | Contract value growth rate |
| sbir_validated_raise | 281 | +2.5 | SLOW_DECAY | Strict temporal: SBIR precedes/catalyzes raise |
| outsized_award | 102 | +2.0 | SLOW_DECAY | Unusually large contract |

**Total active signals: 17,297** (refreshed Mar 5, 2026 — expanded to cover newly classified entities; 1,473 stale signals on PRIME/NON_DEFENSE expired during data quality audit)

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
| STARTUP | 9,655 | Core tracking population |
| PRIME | 876 | Large defense contractors |
| NON_DEFENSE | 1,441 | No defense footprint or merged duplicates |
| RESEARCH | 22 | Universities, FFRDCs, APLs |

**Reclassification history:**
- 474 entities reclassified STARTUP -> PRIME (>$50M contracts, excluding AeroVironment, BlueHalo, SpaceX)
- 7 additional entities reclassified STARTUP -> PRIME (>$100M contracts, Mar 5): SpaceX ($1.46B), AeroVironment ($703M), BlueHalo ($200M), ATI ($523M), NSTXL ($369M), MTEC ($165M), Sheltered Wings ($286M)
- 8 entities reclassified STARTUP -> RESEARCH (universities/labs)
- 553 entities reclassified STARTUP -> NON_DEFENSE (SEC EDGAR only, zero defense footprint)
- 883 merged duplicates (merged_into_id IS NOT NULL) reclassified to NON_DEFENSE (Mar 5)
- 8 consortium entities flagged with `[CONSORTIUM - second-level resolution needed]` tag in core_business_reasoning (Mar 5)

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

### 12. SAM.gov OTA Scraper ✅ PARTIAL (752 contracts ingested)
**File:** `scrapers/sam_gov_ota.py`

Scrapes Other Transaction Authority contracts from SAM.gov Contract Awards API:
- Queries three OT types: ORDER, AGREEMENT, IDV
- Entity resolution via `EntityResolver` for vendor matching
- `procurement_type` column on Contract model (`standard` vs `ota`)
- `ProcurementType` enum in `processing/models.py`
- Rate limit: 5-second delay for free tier API key (`MIN_REQUEST_INTERVAL = 5.0`)
- **752 OTA contracts ingested** (Feb 24 run, stopped by SAM.gov rate limiting at page 7)
- Has checkpoint/resume logic for interrupted runs
- SAM_GOV_API_KEY stored in `.env` at project root
- Post-scrape analytics: FY breakdown, top vendors, contracting offices
- USASpending confirmed blind to OTAs (no type code exists)
- FPDS Atom Feed decommissioned Feb 24, 2026 — SAM.gov is the only durable path

**OTA data context:**
- OTAs grew from $950M (FY2015) to $18B+ (FY2024) — 18% of DoD R&D spending
- Top issuers: ACC-NJ, DARPA, DIU, AFWERX, Army Apps Lab
- 57% of OTA dollars flow through consortia intermediaries (SOSSEC, ATI, NCMS) — need second-level resolution to find actual performers
- GAO found $40B+ in OTAs not reported to USASpending
- This is Aperture's biggest data gap — Anduril, Shield AI, Skydio entered through OTAs and are invisible in current data

**Usage:**
```bash
python -m scrapers.sam_gov_ota --start-date 2023-10-01           # FY2024+
python -m scrapers.sam_gov_ota --start-date 2015-10-01           # Full history
python -m scrapers.sam_gov_ota --ot-type "OTHER TRANSACTION ORDER" --limit 100
python -m scrapers.sam_gov_ota --dry-run                         # Count only
```

### 13. Comparables Engine ✅ VALIDATED
**File:** `scripts/aperture_query.py` (integrated into deal brief pipeline)

Deal intelligence via SBIR embedding similarity + agency overlap + policy alignment + technology tag overlap:
- Scout Space test case: 43 comparable companies identified
- Key finding: contract traction = 5x raise multiplier (19% of comps had production contracts, raised 5x median)
- Raise expectation: $7-12M base, $15-25M upside with contract traction
- End-to-end validation: signals → benchmarks → comparables → recommendation
- **Jaccard technology tag similarity** (weight 2.0) added Feb 24 — ensures domain peers rank above cross-domain matches (e.g., cybersecurity companies no longer appear as comps for UAS companies)

### 14. Deal Intelligence Brief Generator ✅ COMPLETE
**File:** `scripts/aperture_query.py`

Single-command 9-section deal intelligence brief connecting all data sources:
- **Sections:** Company Profile, Government Traction, Private Capital Activity, Signal Profile, Policy Alignment, Lifecycle Position, Comparables Analysis, Data Coverage & Verification Notes, Analyst Assessment
- **Client-facing variant:** Removes Signal Profile, Policy Alignment, Top 15 comparables, CONFIRMED/GAP data points; adds Key Contacts & Investor Syndicate section and Client Opportunity section tailored to recipient's capabilities
- Direct sqlite3 queries (not SQLAlchemy ORM) for performance and simplicity
- Fuzzy entity lookup via `rapidfuzz` (token_sort_ratio, cutoff=75)
- Comparables engine: primary search by policy alignment (top priority >= 0.5), secondary by core_business; filters: SBIR count 0.5x-2x target, Phase II >= 1, Reg D total >= $50K; sorted by profile similarity with **Jaccard technology tag overlap** (weight 2.0); top 15 in table + top 5 detailed profiles
- Lifecycle narrative: 3-4 sentence paragraph with dated milestone progression; **graceful NULL date handling** (falls back to count-based narrative when contract dates unavailable)
- **Web verification** (`build_verification_notes()`): Claude + `web_search_20250305` server-side tool cross-references Aperture data against public sources. Now passes top 10 contract details (value, agency, date, procurement type) and all funding events for proper dedup — prevents flagging already-ingested enrichment data as GAPs. Outputs CONFIRMED/GAP/NOTE findings. Disabled with `--no-verify`.
- Claude analyst assessment (Sonnet) with current date in system prompt and temporal framing instruction. Includes disclaimer referencing verification notes for identified data gaps.
- Signal composite scoring with freshness-weighted tiers (same weights as RAG engine)
- Policy tailwind score: weighted average of scores > 0.2 (matches `processing/policy_alignment.py`)
- **NULL contract date sorting:** `ORDER BY CASE WHEN award_date IS NULL THEN 1 ELSE 0 END, award_date` in both Government Traction and Lifecycle queries — dated contracts first, undated at bottom
- **Private Capital query:** Excludes superseded funding events (WHERE id NOT IN subquery on parent_event_id), includes both REG_D_FILING and PRIVATE_ROUND event types, displays source provenance (SEC EDGAR vs Web Enrichment)
- Validated on Scout Space, Starfish Space, Firestorm Labs, X-Bow (enriched), Darkhive (client-facing)

**Usage:**
```bash
python scripts/aperture_query.py --type deal --entity "Scout Space" --output reports/brief_scout_space.md
python scripts/aperture_query.py --type deal --entity "Starfish Space" --no-claude  # Skip API call
python scripts/aperture_query.py --type deal --entity "Shield AI" --pdf             # Also generate PDF
python scripts/aperture_query.py --type deal --entity "Firestorm Labs" --no-verify  # Skip web verification
```

### 15. Web Enrichment Pipeline ✅ COMPLETE
**File:** `scripts/enrich_entity.py`

Closes data gaps by searching the web for contracts, funding rounds, OTAs, and partnerships that aren't captured by structured scrapers (USASpending, SBIR.gov, SEC EDGAR):

**Architecture — two-phase approach:**
1. **Search phase:** Claude + `web_search_20250305` tool finds contracts, funding rounds, acquisitions, partnerships, OTA agreements. Prompt includes current DB counts and details so Claude can identify what's missing.
2. **Structure phase:** Separate Claude API call (no tools) extracts structured JSON from search results. Separation matters because web search responses are messy (tool_use blocks, citations). Asking for clean JSON in the same call that uses tools is unreliable.

**Data flow:**
```
enrich_entity.py
  ├── gather_existing_data(conn, entity_id) → current DB counts/details
  ├── search_and_extract(client, name, existing) → structured JSON findings
  ├── stage_findings(conn, entity_id, findings) → enrichment_findings table (status='pending')
  ├── review_pending(conn) → interactive CLI approve/reject
  └── ingest_approved(conn, finding_id) → writes to contracts/funding_events
```

**Ingestion logic:**
- Contracts: INSERT with `source = "web_enrichment:{url}"`
- Funding rounds (new): INSERT as `event_type = 'PRIVATE_ROUND'`
- Funding rounds (update existing): Links via `parent_event_id` to original EDGAR filing, preserving provenance while displaying corrected amount
- OTA awards: INSERT into contracts with `procurement_type = 'ota'`
- Partnerships: INSERT into relationships table

**Deduplication:**
- Contracts: match on similar value (within 10%) + same agency + date within 90 days
- Funding: match on same round_stage + date within 6 months; if new amount > existing, flag as update (not duplicate)

**Validation:** X-Bow brief went from "No contracts found" + $92.5M raised → 14 contracts ($450.5M) + lifecycle "Scaling." Enrichment ingested the $191M production contract, Navy rocket motor contracts, NSWC Indian Head contract, and Spencer Composites acquisition data.

**Usage:**
```bash
python scripts/enrich_entity.py --entity "X-BOW LAUNCH SYSTEMS INC"
python scripts/enrich_entity.py --entity "DARKHIVE INC" --auto-approve  # High-confidence auto-ingest
python scripts/enrich_entity.py --batch --file priority_entities.txt
python scripts/enrich_entity.py --review  # Review pending enrichments
```

### 16. Notional Fund System ✅ COMPLETE
**Files:** `Fund/fund_manager.py`, `Fund/create_fund_tables.py`, `Fund/redeploy_fund.py`, `Fund/generate_fund_overview.py`, `Fund/strategies/*.json`

VC-style portfolio construct that tests Aperture's signal-based thesis in real time. Deploys signal-selected cohorts against matched-pair benchmarks and tracks milestone hit rates to measure differential alpha.

**Design principles:**
- Buy-and-hold positions (no exits except terminal events) — matches defense VC reality
- Milestone-based performance measurement (not IRR/TVPI) — measurable in quarters, not decades
- Matched-pair benchmarks from same eligible universe — each signal company paired with nearest neighbor on observable characteristics, isolating the test variable
- Bootstrap baselines (100 random draws) computed at deploy time for confidence intervals
- Entry state frozen at selection time — every position captures the full signal profile that justified inclusion

**Components:**
- `fund_strategies` — Thesis definitions with structured JSON selection criteria (eligible universe filters, ranking, signal requirements)
- `fund_cohorts` — Vintage deployments; each signal cohort gets a paired random benchmark cohort
- `fund_positions` — Per-company positions with frozen entry state (composite score, signals, SBIRs, contracts, policy tailwind, lifecycle stage)
- `fund_milestones` — Observable events after entry (funding raises, contracts, SBIR advances, lifecycle progression, score changes) with `months_since_entry` and dedup via `source_key`

**Strategies defined:**
| Strategy | Thesis | Eligible Universe |
|----------|--------|-------------------|
| Next Wave | Phase II graduates with no private capital yet (core 80%/35mo prediction) | ~2,638 companies |
| Policy Tailwind | Highest alignment to top-growth budget areas (space +38%, autonomous +10%) | ~3,044 companies |
| Signal Momentum | Strongest recent signal activity regardless of funding history | ~2,386 companies |

**Q1 2026 deployment (all 3 strategies):**
- **Next Wave:** 20 signal (adj 3.58–5.09) vs 20 matched benchmark (avg 2.89); match vars: sbir_count, contract_count, contract_value_log, core_business, policy_tailwind_score
- **Policy Tailwind:** 20 signal (policy 0.90 across board) vs 20 matched benchmark (avg policy 0.54); match vars: sbir_count, contract_count, contract_value_log, core_business, freshness_adjusted_score
- **Signal Momentum:** 20 signal (adj 4.62–7.25, Defense Unicorns #1) vs 20 matched benchmark (avg 3.02); match vars: sbir_count, contract_count, contract_value_log, core_business, policy_tailwind_score
- 120 total positions (60 signal + 60 benchmark), 58 unique companies (2 appear in multiple strategies)

**Milestone types tracked:**
- FUNDING_RAISE — New Reg D / VC round after entry
- NEW_CONTRACT — DoD/federal contract after entry
- SBIR_ADVANCE — Phase progression after entry
- LIFECYCLE_ADVANCE — Stage progression (e.g., prototype → production)
- COMPOSITE_SCORE_INCREASE — Score improvement since entry
- NEW_AGENCY — Contract with new DoD branch
- ACQUISITION — Company acquired (terminal)
- GONE_STALE — No activity 24+ months (negative milestone)

**Performance metric:** Milestone hit rate differential (signal cohort rate minus benchmark rate). A 25% vs 10% funding raise hit rate at 12 months = concrete, defensible claim for client conversations.

**Usage:**
```bash
# Strategy management
python Fund/fund_manager.py strategy create --name "Next Wave" --config Fund/strategies/next_wave.json
python Fund/fund_manager.py strategy activate --name "Next Wave"
python Fund/fund_manager.py strategy list
python Fund/fund_manager.py strategy show --name "Next Wave"

# Cohort deployment (matched-pair + bootstrap)
python Fund/fund_manager.py deploy --strategy "Next Wave" --vintage "2026-Q1" --dry-run
python Fund/fund_manager.py deploy --strategy "Next Wave" --vintage "2026-Q1"

# Redeployment (drop + redeploy all strategies for a vintage)
python Fund/redeploy_fund.py --dry-run
python Fund/redeploy_fund.py

# Milestone tracking
python Fund/fund_manager.py track --since 2026-01-01 --dry-run
python Fund/fund_manager.py track --since 2026-01-01

# Performance reporting
python Fund/fund_manager.py performance --strategy "Next Wave"
python Fund/fund_manager.py performance --all

# Fund overview one-sheeter PDF
python Fund/generate_fund_overview.py --vintage 2026-Q1 --output reports/fund_overview_2026_q1.pdf
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

### 9. Technology Tag Overlap in Comparables (Jaccard Similarity)
**Decision:** Added Jaccard similarity on `technology_tags` (weight 2.0) to comparables scoring in `aperture_query.py`.

**Rationale:** Firestorm Labs (UAS/drones, tags: `autonomy`, `materials`) was matching cybersecurity companies (Illumio, Nozomi Networks) because similarity scoring ignored technology domain entirely. Jaccard weight of 2.0 (matching SBIR count weight) ensures domain peers rank above cross-domain matches. Max total similarity goes from 7.0 to 9.0. Companies with no tags get 0.0 (no penalty, just no bonus).

### 10. UAS/Drone Policy Alignment Prompt Fix
**Decision:** Expanded `autonomous_systems` description in `config/policy_priorities.yaml` and added structured examples with score ranges to `processing/policy_alignment.py`.

**Rationale:** Firestorm Labs scored 0.20 on autonomous_systems despite building military UAS platforms. The policy prompt lacked UAS-specific terminology (drones, UAV, Group 1-5, counter-UAS), so Claude under-scored. After fix: Firestorm Labs scores 0.90. 120 AEROSPACE_PLATFORMS entities re-scored; 17 UAS/drone companies corrected.

### 11. Reg D Deduplication
**Decision:** Filings with identical (entity_id, event_date, amount) treated as amended filings and collapsed to one.

**Rationale:** Found 25 duplicate groups totaling $1.67B in inflated capital. Biggest offender: Genesys Cloud ($1.5B duplicated). Applied consistently across all three detector locations (sbir_to_vc_raise, sbir_validated_raise, detect_funding_raises).

### 12. Funding Round Double-Counting Fix (parent_event_id)
**Decision:** Added `parent_event_id` column to `funding_events` table. When web enrichment finds a larger round size than the EDGAR filing (e.g., $105M Series B vs $21M Form D), the enriched record links to the original via `parent_event_id` instead of creating a duplicate. Private Capital query excludes superseded rows: `WHERE id NOT IN (SELECT parent_event_id FROM funding_events WHERE parent_event_id IS NOT NULL)`.

**Rationale:** EDGAR Form D captures the amount offered in the filing, which is often just a tranche (not the full round). Press releases report full round sizes. Without linking, both appear in the brief, inflating totals. X-Bow showed $92.5M (EDGAR) when actual was ~$157M, but naively adding both would double-count.

### 13. Two-Phase Web Enrichment (Search → Structure)
**Decision:** Enrichment uses two separate Claude API calls: Phase 1 with `web_search` tool for research, Phase 2 without tools for JSON extraction.

**Rationale:** Asking Claude to search the web AND return structured JSON in the same call produces unreliable JSON — response contains tool_use blocks, partial text, and citations mixed with data. Separating search from structuring produces clean, parseable JSON consistently.

### 14. Verification Prompt Dedup Enhancement
**Decision:** `build_verification_notes()` now passes top 10 contract details (value, agency, date, procurement type) and all funding events to Claude, not just counts.

**Rationale:** After enrichment ingests data, verification was still flagging it as GAPs because the prompt only said "14 contracts" without details. Claude couldn't match "$191M production contract" against just a count. With details, Claude properly marks matching data as CONFIRMED.

### 15. NULL Contract Date Handling
**Decision:** Contract queries use `ORDER BY CASE WHEN award_date IS NULL THEN 1 ELSE 0 END, award_date`. Lifecycle narrative filters `dated_contracts = [c for c in contracts if c["award_date"] is not None]` and falls back to count-based narrative when no dates available.

**Rationale:** Web-enriched contracts often have NULL dates (press releases mention value/agency but not exact award date). Before fix, lifecycle narrative said "first production contract ($191.3M) in N/A" — clearly broken. Now it says "secured 14 contracts totaling $450.5M, including a $191.3M standard award."

### 16. Client-Facing Brief Variant
**Decision:** For sales consultant recipients (Don), briefs remove Signal Profile, Policy Alignment, Top 15 comparables table, and CONFIRMED/GAP data points. Add Key Contacts & Investor Syndicate section and Client Opportunity section tailored to recipient's capabilities.

**Rationale:** Don needs actionable sales intelligence, not Aperture's internal scoring methodology. Contacts section transforms the brief from a research report into a sales tool — Don can reference specific investor relationships and integration needs in his outreach. Client Opportunity section maps the target company's product roadmap to Don's specific capabilities (antenna/RF engineering).

### 17. Notional Fund as Forward-Looking Validation
**Decision:** Build a VC-style notional portfolio system to test Aperture's thesis in real time, rather than relying solely on backward-looking signal validation.

**Rationale:** The 80% prediction rate and 35-month lead time are historical backtests. A notional fund creates dated, documented picks measured against random baselines — the difference between "our backtest looks good" and "here's what we called in real time." The fund also becomes the most compelling sales artifact for client conversations: it demonstrates Aperture trusts its own signals enough to bet on them. Designed with VC constraints (buy-and-hold, no exits) and VC-relevant metrics (milestone hit rates, not IRR) because that matches how the client base actually deploys capital.

### 18. Contract-Based Classification and Scoring (Mar 5)
**Decision:** Extended `business_classifier.py` and `policy_alignment.py` to classify/score entities using contract data (NAICS codes, PSC codes, agencies) when no SBIR awards exist.

**Rationale:** 5,021 unclassified entities had zero SBIR awards, making the SBIR-only classifier useless for them. Analysis showed 3,331 had contracts (classifiable via NAICS/PSC), 857 had only Reg D filings (not classifiable), 833 were merged duplicates (safe to ignore). Contract-based classification uses a separate prompt with PSC code ranges (1000-1999 weapons, 5800-5999 comms, 7000-7999 IT) and NAICS codes for domain inference. Results: 3,329/3,329 classified and scored successfully. Dry-run validated (SpaceX → AEROSPACE_PLATFORMS 0.95). Classifications tagged with `[contract-based classification]` and scores tagged with `[contract-based scoring]` for provenance.

### 19. Data Quality Audit Script (Mar 5)
**Decision:** Created `scripts/audit_data_quality.py` as a persistent, rerunnable infrastructure audit.

**Rationale:** After extending classification to the full universe, needed systematic verification. 5 sections: Entity Integrity (merged duplicates, consortium flags, PRIME misclassification), Funding Accuracy (duplicate events, superseded rows), Signal Correctness (wrong entity types, gone_stale consistency, temporal sequencing), Policy Alignment Consistency, Brief Generation Reliability. Found and fixed 6 failures: 1,473 stale signals on PRIME/NON_DEFENSE, 88 duplicate funding events, 883 un-cleaned merged entities, 26 negative contract values (deobligations). Final state: 0 failures, 5 acceptable warnings. Key check details: consortium detection uses `LIKE '%[CONSORTIUM -%'` (matches the tag, not bare word); NON_DEFENSE contract check excludes merged entities (`AND e.merged_into_id IS NULL`).

### 20. Matched-Pair Benchmarks over Random Benchmarks
**Decision:** Replaced random benchmark selection with matched-pair nearest-neighbor. For each signal company, the benchmark is the closest match on observable characteristics (SBIR count, contract count, contract value, core business, policy tailwind/signal score) from the same eligible universe, excluding the test variable. Bootstrap baselines (100 random draws) computed at deploy time for confidence intervals.

**Rationale:** Random benchmarks don't control for observable differences — a signal company with 30 SBIRs and $50M in contracts compared to a random company with 2 SBIRs proves nothing about signal quality. Matched-pair isolates the specific dimension being tested (signal strength, policy alignment, or momentum) by holding everything else constant. If the signal cohort still outperforms its matched pair on milestones, the alpha comes from the signal, not from the company's size or maturity. Bootstrap baselines confirm the matched cohort is representative of the broader eligible universe.

---

## Architecture

```
defense-alpha/
├── scrapers/
│   ├── usaspending.py          # DoD contracts from USASpending API
│   ├── sbir.py                 # SBIR/STTR awards (bulk CSV + API)
│   ├── sec_edgar.py            # SEC Form D private funding (Reg D filings)
│   └── sam_gov_ota.py          # OTA contracts from SAM.gov Contract Awards API
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
│   ├── aperture_query.py            # Deal intelligence brief generator (9-section, single command)
│   ├── enrich_entity.py             # Web enrichment pipeline (two-phase Claude + web_search)
│   ├── generate_prospect_report.py  # Markdown report generator
│   ├── generate_pdf_report.py       # PDF report generator (prospect reports)
│   ├── generate_phase2_pdf.py       # PDF report generator (Phase II Signal)
│   ├── generate_analyst_note.py     # One-page analyst note PDF (branded)
│   ├── generate_darkhive_pdf.py     # Branded client-facing PDF (reusable template)
│   ├── audit_data_quality.py        # Infrastructure quality audit (5 sections, exit code 0/1)
│   ├── employment_targets.py        # Employment target identifier (top 20 + heatmap + dark horses)
│   └── policy_signal_poc.py         # Policy signal-response PoC (Space Force, original)
├── Fund/
│   ├── fund_manager.py         # Notional fund CLI (strategy/deploy/track/performance)
│   ├── create_fund_tables.py   # Fund table creation
│   ├── redeploy_fund.py        # Drop + redeploy cohorts for a vintage
│   ├── generate_fund_overview.py  # Branded one-sheeter PDF (reportlab)
│   └── strategies/
│       ├── next_wave.json      # Phase II graduates, no private capital
│       ├── policy_tailwind.json # Highest policy alignment
│       └── signal_momentum.json # Strongest recent signals
├── results/
│   ├── benchmark_space_force.json       # Signal-response benchmark results
│   ├── benchmark_nds_2018.json
│   └── benchmark_ukraine_drones_2022.json
├── reports/
│   ├── rf_comms_v2.md          # RF report (55 companies)
│   ├── rf_comms_v2.pdf
│   ├── phase2_signal_report.md # Phase II Signal thesis report (164 companies)
│   ├── phase2_signal_report.pdf
│   ├── comparables_scout_space.md  # Scout Space comparables (43 companies)
│   ├── brief_scout_space.md       # Scout Space deal intelligence brief (8 sections)
│   ├── brief_starfish_space.md    # Starfish Space deal intelligence brief
│   ├── brief_firestorm_labs_v3.md # Firestorm Labs deal brief (9-section, web-verified)
│   ├── brief_xbow_enriched.md    # X-Bow deal brief (post-enrichment, 14 contracts/$450M)
│   ├── brief_darkhive.md         # Darkhive client-facing brief (contacts + client opportunity)
│   ├── darkhive_brief.pdf        # Darkhive branded PDF for Don
│   ├── firestorm_drone_dominance.pdf  # Firestorm analyst note (one-page PDF)
│   ├── fund_overview_2026_q1.pdf       # Fund one-sheeter (3 strategies, 58 companies)
│   ├── graph_space_resilience.html     # Interactive ecosystem visualizations
│   ├── graph_autonomous_systems.html
│   ├── graph_anduril.html
│   └── employment_targets.md        # Employment target report (top 20 startups for Marine pilot/JTAC)
├── config/
│   ├── policy_priorities.yaml  # NDS priority definitions and weights
│   └── settings.py             # App configuration
├── data/
│   ├── defense_alpha.db        # SQLite database (~243MB, restored)
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
period_of_performance_start/end, place_of_performance, contract_type, raw_data (JSON)
procurement_type (standard/ota, indexed)
```

### funding_events
```sql
id, entity_id (FK), event_type (sbir_phase_1/2/3, reg_d_filing, vc_round, PRIVATE_ROUND, etc.)
amount, event_date, investors_awarders (JSON), round_stage, raw_data (JSON)
parent_event_id (FK self-ref, nullable) -- links enriched round to original EDGAR filing it supersedes
source -- "sec_edgar", "web_enrichment:{url}", etc.
```

### enrichment_findings
```sql
id, entity_id (FK)
finding_type (contract/funding_round/partnership/ota_award)
finding_data (JSON), source_url, confidence (high/medium/low)
status (pending/approved/rejected/ingested)
reviewed_at, reviewed_by (auto/manual)
ingested_at, ingested_record_id
created_at
-- Index: (entity_id, status)
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

### fund_strategies
```sql
id, name (unique), description, status (draft/active/paused/retired)
selection_criteria (JSON: eligible_universe, ranking, filters)
target_cohort_size, deployment_frequency (quarterly/monthly/manual)
```

### fund_cohorts
```sql
id, strategy_id (FK), cohort_type (signal/benchmark)
vintage_label (e.g. "2026-Q1"), deployed_at
paired_cohort_id (FK self-ref) -- benchmark points to its signal cohort
selection_metadata (JSON: eligible_universe_size, random_seed, score_distribution)
```

### fund_positions
```sql
id, cohort_id (FK), entity_id (FK)
status (active/terminal_acquired/terminal_inactive/terminal_merged)
-- Frozen entry state:
entry_composite_score, entry_freshness_adjusted_score, entry_policy_tailwind
entry_lifecycle_stage, entry_signals (JSON), entry_sbir_count
entry_contract_count, entry_contract_value, entry_regd_count, entry_regd_value
snapshot_id (FK to entity_snapshots), selection_rank, selection_reason
-- Unique: (cohort_id, entity_id)
```

### fund_milestones
```sql
id, position_id (FK), entity_id (FK)
milestone_type (funding_raise/new_contract/sbir_advance/lifecycle_advance/
                composite_score_increase/new_agency/acquisition/gone_stale)
milestone_date, milestone_value, months_since_entry
details (JSON), source_key (unique, for dedup)
```

---

## How to Start a Session

```
I'm working on Aperture Signals at ~/projects/defense-alpha

cd ~/projects/defense-alpha && source venv/bin/activate

Defense intelligence platform with:
- ~11,994 entities (9,655 startups, 876 primes, 1,441 non_defense, 22 research)
- 8,838 classified + 8,798 policy scored (SBIR-based + contract-based)
- 857 unclassifiable (Reg D only, no SBIR/contract data)
- 13,904 contracts ($1.16T+), 32,659+ funding events
- 17,297 signals (15+ types, tiered freshness decay)
- 114 outcome events (23 contracts, 91 funding raises — 80% prediction rate, 35mo lead)
- 27,529 SBIR embeddings (full coverage)
- Key finding: SBIR Phase II predicts private raises — 164 companies, $8.48B, 8-month median gap
- Next wave pipeline: 3,221 Phase II startups with no Reg D
- Knowledge graph: 39,712 relationships materialized (agency, contract, policy edges)
- Signal-response benchmarks: 3 calibrated pairs (Space Force, NDS 2018, Ukraine Drones)
- Web enrichment pipeline: `python scripts/enrich_entity.py --entity "Company Name"` (two-phase Claude + web search → staged findings → approve → ingest)
- Notional fund: 3 strategies deployed Q1 2026 with matched-pair benchmarks (120 positions, 58 unique companies)
- Fund CLI: `python Fund/fund_manager.py performance --all`
- Fund overview PDF: `python Fund/generate_fund_overview.py --vintage 2026-Q1`
- Deal brief generator: `python scripts/aperture_query.py --type deal --entity "Company Name"`
- Data quality audit: `python scripts/audit_data_quality.py` (0 failures, 5 warnings as of Mar 5)
- Employment targets: `python scripts/employment_targets.py` (top 20 startups for employment fit)
- Reports delivered: Scout Space, Starfish Space, Firestorm Labs, X-Bow (enriched), Darkhive (client-facing + branded PDF), Phase II Signal, RF/Comms v2, investor leads
- Remaining data gaps: OTA scraper paused at 752 (SAM.gov rate limit), EDGAR captures tranches not full rounds (enrichment compensates per-entity), consortium resolution needed

Current priorities: see Next Priority section below.

Show me current DB stats to confirm state, then let's continue.
```

---

## Knowledge Graph
- 39,712 relationships (16,656 FUNDED_BY_AGENCY, 5,919 CONTRACTED_BY_AGENCY, 17,137 ALIGNED_TO_POLICY)
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
- SBIR is budget-driven, not policy-signal-responsive
- Limitation: Pre-2019 Reg D baseline too thin (7 filings). SEC EDGAR scraper now supports backfill to 2008.
- CLI: `scripts/run_benchmarks.py` (`--benchmark space_force`, `--bootstrap 1000`, `--output results/`)
- Results stored as JSON in `results/benchmark_*.json`
- Original PoC preserved: `scripts/policy_signal_poc.py`

## Investor Data
- `scripts/extract_investors.py` parses RELATEDPERSONS from SEC EDGAR DERA data
- SEC EDGAR scraper updated to download `RELATEDPERSONS.TSV` (directors, officers, promoters)
- Enables investor pattern analysis (who invests in which signal profiles)
- Related persons stored in `raw_data._related_persons` on Reg D funding_events

## Product Vision (Crystallized)

**Model: "Noetica for defense capital formation"**
- Noetica: unstructured deal docs → structured term intelligence → benchmarks → acquired by Thomson Reuters
- Aperture: public gov/capital data → structured signals → benchmarks → defense investment intelligence

Aperture Signals → knowledge graph of defense capital formation
- Take government/DoD signals (policy, budget, SBIR, OTA, solicitations)
- Map to private market responses (VC raises, company formation, contract wins)
- Build historical benchmarks from signal-response pairs
- Apply benchmarks to current signals for quantitative predictions
- Defensible: time-locked dataset, cross-domain linkage nobody else has

**Seven product surfaces validated:**
1. Thesis reports (Phase II Signal)
2. Deal intelligence briefs — single-command 9-section brief via `aperture_query.py` (Scout Space, Starfish Space, Firestorm Labs, X-Bow enriched)
3. Client-facing briefs — stripped-down variant with Key Contacts, Investor Syndicate, Client Opportunity sections, branded PDF delivery (Darkhive for Don)
4. Analyst notes — one-page competitive positioning PDFs with EDGAR-sourced capitalization data (Firestorm Labs)
5. Comparables/deal intelligence (Scout Space standalone, now integrated into briefs with Jaccard tag similarity)
6. Sector intelligence (RF/Comms v2)
7. Notional fund system — VC-style portfolio construct with signal-selected cohorts vs matched-pair benchmarks + bootstrap baselines; measures milestone hit rate differential as forward-looking thesis validation; 3 strategies deployed Q1 2026 (120 positions, 58 unique companies); branded one-sheeter PDF (`reports/fund_overview_2026_q1.pdf`)
8. Employment target identifier — personal use tool for identifying high-signal small defense startups for employment; configurable scoring formula with domain preference multiplier for specific MOS/background relevance; top 20 profiles, signal heatmap, sector concentration, dark horse list (`scripts/employment_targets.py`)

**Elevator Pitch:**
"Aperture maps government defense spending to private capital markets. We track every SBIR award, defense contract, and SEC filing, link them to the same companies, and detect signals that predict where private money is going to flow. Think of it as the intelligence layer between the Pentagon's budget and the investors deploying capital around it."

One-liner: "Aperture tells defense investors where the government's money is going before the market figures it out."

---

## Next Priority

### ~~1. Restore defense_alpha.db from backup/old machine~~ ✅ DONE
- DB restored (~243MB) — all entities, contracts, funding events, signals, embeddings, relationships intact

### ~~2. Recreate .env with all API keys~~ ✅ DONE
- ANTHROPIC_API_KEY ✅ configured
- SAM_GOV_API_KEY ✅ configured

### 3. Resume SAM.gov OTA scraper (752 contracts ingested, rate-limited)
- 752 OTA contracts ingested before SAM.gov throttled (Feb 24)
- Has checkpoint/resume logic — retry from different network or wait for rate limit reset
- `python -m scrapers.sam_gov_ota --start-date 2023-10-01`
- Then backfill: `python -m scrapers.sam_gov_ota --start-date 2015-10-01 --end-date 2023-09-30`
- **This remains Aperture's biggest structured data gap.** OTAs grew from $950M (FY2015) to $18B+ (FY2024). Anduril, Shield AI, Skydio entered defense through OTAs and are underrepresented in current data. GAO found $40B+ in OTAs not reported to USASpending.
- 57% of OTA dollars flow through consortia (SOSSEC, ATI, NCMS) — need second-level resolution for actual performers
- Web enrichment pipeline partially compensates (ingests OTAs found via web search with `procurement_type = 'ota'`), but systematic scraping is needed for coverage

### ~~4. Classify remaining 5,623 entities (~51% of universe)~~ ✅ DONE (Mar 5)
- Extended classifier with `--contracts-only` mode for 3,329 entities with contracts but no SBIRs
- Extended policy alignment to score using contract data as fallback when no SBIRs
- 857 Reg D-only entities remain unclassifiable (no SBIR or contract data)
- 883 merged duplicates reclassified to NON_DEFENSE
- Final: 8,838 classified, 8,798 policy scored

### 5. Entity resolution on OTA data — quantify blind spot
- How many OTA vendors are already in the entity universe?
- How many are new (invisible in current data)?

### ~~6. Backfill SEC EDGAR Reg D to 2012 for stronger baselines~~ ✅ DONE
- `python scrapers/sec_edgar.py --start-date 2012-01-01 --end-date 2019-12-31`
- Added ~3,000 historical funding events strengthening baseline benchmarks
- Pre-2019 Reg D baseline expanded from 7 filings to statistically useful sample

### ~~7. Run comparables on 2-3 more companies to confirm methodology generalizes~~ ✅ DONE
- Scout Space, Starfish Space, and Firestorm Labs briefs generated via `aperture_query.py`
- Comparables engine integrated into deal brief pipeline with Jaccard tag similarity

### 8. Package Phase II Signal report + Scout Space comparables as sample deliverables

### 9. Build feedback capture mechanism for report recipients

### ~~10. Data validation layer~~ ✅ DONE (Mar 5)
- `scripts/audit_data_quality.py` — comprehensive 5-section audit (entity integrity, funding accuracy, signal correctness, policy alignment consistency, brief generation reliability)
- Returns exit code 0 (PASS) or 1 (FAIL) for CI integration
- Current state: 0 failures, 5 acceptable warnings
- `python scripts/audit_data_quality.py`

### 11. Connect RAG → report generator (single command query → PDF)
- Goal: `python scripts/rag_query.py "counter-drone RF" --pdf reports/counter_drone.pdf`
- **Partial:** `aperture_query.py` achieves single-command → markdown → optional PDF for deal briefs. RAG→sector report pipeline still needed.

### ~~12. Build notional fund system for thesis validation~~ ✅ DONE (Mar 3)
- VC-style portfolio construct: strategy definition → cohort deployment (matched-pair benchmarks + bootstrap baselines) → milestone tracking → performance reporting
- 3 strategies deployed Q1 2026: Next Wave, Policy Tailwind, Signal Momentum (120 positions, 58 unique companies)
- Upgraded from random benchmarks to matched-pair nearest-neighbor (isolates test variable by matching on SBIR count, contract count, contract value, core business, policy/signal scores)
- Fund overview one-sheeter PDF generated (`reports/fund_overview_2026_q1.pdf`)
- Next: run first milestone scan, generate performance report at 90 days (June 2026)

### Medium Priority

#### Remaining Data Gaps (Credibility Blockers)
- **Private market funding accuracy:** SEC EDGAR Form D captures filing amounts (often just tranches), not full round sizes. Web enrichment partially closes this on a per-entity basis, but systematic coverage requires either: (a) paid data source integration (Crunchbase/PitchBook API), or (b) batch web enrichment across priority entities before each report delivery. Current state: enrichment validated on X-Bow ($92.5M EDGAR → ~$157M actual), needs to be run on every entity before external delivery.
- **OTA contract completeness:** 752 OTA contracts ingested from SAM.gov (paused by rate limiting). Estimated 10,000+ OTA awards exist across DIU, AFWERX, NavalX, SOCOM, Army Apps Lab, DARPA. Web enrichment fills gaps per-entity but can't replace systematic scraping for universe-wide coverage. The companies that matter most (Anduril, Shield AI, Skydio) entered defense through OTAs.
- **Consortium resolution:** 57% of OTA dollars flow through intermediaries (NSTXL, SOSSEC, ATI, NCMS). SAM.gov awards list the consortium as vendor, not the performing company. Need second-level resolution to attribute awards to actual performers.
- **Acquisition/partnership data:** No structured source. Web enrichment captures these opportunistically but no systematic coverage. Matters for lifecycle classification (X-Bow's Spencer Composites acquisition indicates production stage).

#### Other Medium Priority
- **Policy headwind signal** — Negative signal for companies in declining budget areas (e.g., hypersonics -43%)
- **Remaining outcome detectors** — sbir_advance, new_agency, company_inactive (3 stubs)
- **~~Fix Reg D filing count edge case~~** ✅ Fixed via `parent_event_id` schema change — NULL-date filings and double-counting resolved
- **Refresh data pulls** — USASpending (30 days), SBIR (current year), SEC EDGAR (90 days)
- **Generate updated RF report** — Refresh with latest signal/policy data
- **Review entity resolution queue** — 201,328 pairs in `data/review_queue.csv`
- **Generate Defense Software Report** — Filter for `core_business = 'software'` (1,912 entities)
- **Remaining outcome stubs** — sbir_stall, acquisition, recompete_loss

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
- SAM.gov OTA scraper rate limit: 5-second delay for free tier; SAM.gov throttled after concurrent scraper runs (Feb 24)
- OTA contracts stored with `procurement_type='ota'` vs `'standard'` for FAR contracts
- 57% of OTA dollars flow through consortia — need second-level resolution for actual performers
- SBIR raw_data JSON keys use title case with spaces: `"Award Title"`, `"Agency"` (access via `json_extract(raw_data, '$."Award Title"')`)
- Policy alignment JSON has nested `"scores"` key: `{"scores": {"space_resilience": 0.9, ...}, "top_priorities": [...], "policy_tailwind_score": 0.712}`
- Policy tailwind formula: `sum(score * budget_weight) / sum(budget_weight)` only for priorities where `score > 0.2`
- `aperture_query.py` uses direct sqlite3 (not SQLAlchemy) — requires UPPERCASE enum values in SQL and `json_extract` with quoted keys

### Web Verification Layer
- `build_verification_notes()` in `aperture_query.py` uses Claude Sonnet + `web_search_20250305` server-side tool
- Tool definition: `{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}`
- Now passes top 10 contract details (value, agency, date, procurement type) and all funding events for proper dedup against enriched data
- Extracts text blocks from response (skips tool_use/tool_result blocks)
- Outputs CONFIRMED/GAP/NOTE findings
- Disabled with `--no-verify` flag
- First use on Firestorm Labs caught: $47M Series A, $100M Air Force IDIQ, HP partnership — all missing from Aperture data

### Web Enrichment Pipeline
- `scripts/enrich_entity.py` uses two-phase Claude approach (search → structure) for reliable JSON extraction
- Findings staged in `enrichment_findings` table with confidence levels (high/medium/low)
- Ingested records tagged with `source = "web_enrichment:{url}"` for provenance tracking
- `parent_event_id` on `funding_events` links enriched round amounts to original EDGAR filings — prevents double-counting while preserving audit trail
- Private Capital query uses: `WHERE id NOT IN (SELECT parent_event_id FROM funding_events WHERE parent_event_id IS NOT NULL)` to exclude superseded rows
- Dedup checks run during staging: contract value within 10% + same agency + date within 90 days; funding same round_stage + date within 6 months
- Auto-approve mode available for high-confidence findings (>90% approval rate threshold)
- Batch mode supports `priority_entities.txt` file for systematic enrichment before report delivery

### Data Quality Fixes Applied (Mar 5, 2026)
- **Stale signals on wrong entity types:** Expired 1,473 active signals on PRIME and NON_DEFENSE entities (signals should only be active on STARTUPs)
- **Duplicate funding events:** Removed 88 duplicate funding events across 77 groups (same entity_id, event_date, amount, event_type)
- **Merged entity cleanup:** Reclassified 883 merged duplicates (merged_into_id IS NOT NULL) from STARTUP to NON_DEFENSE
- **Negative contract values:** Zeroed 26 negative contract values (deobligations — government clawbacks, not real contract awards)
- **PRIME reclassification:** 7 entities with >$100M contracts reclassified STARTUP → PRIME (SpaceX, AeroVironment, BlueHalo, ATI, NSTXL, MTEC, Sheltered Wings)
- **Consortium flagging:** 8 consortium entities tagged with `[CONSORTIUM - second-level resolution needed]` in core_business_reasoning
- **Consortium check fix:** Audit check 1c uses `LIKE '%[CONSORTIUM -%'` to match the tag, not the bare word "CONSORTIUM" (which appeared in LLM reasoning for legitimate companies like PROFESSIONAL SOFTWARE CONSORTIUM INC)
- **NON_DEFENSE contract check:** Audit check 1d2 excludes merged entities (`AND e.merged_into_id IS NULL`) to avoid circular issues with entities that have orphaned contracts from pre-merge state

### Bug Fixes Applied (Feb 27, 2026)
- **NULL contract dates:** `ORDER BY CASE WHEN award_date IS NULL THEN 1 ELSE 0 END, award_date` in Government Traction + Lifecycle queries
- **Lifecycle narrative crash:** Filters to `dated_contracts` before selecting earliest; falls back to count-based narrative
- **Funding double-counting:** `parent_event_id` schema change (migration 351c28b78ecd) + `build_private_capital()` excludes superseded rows
- **Verification dedup:** Prompt now includes contract/funding details, not just counts
- **Darkhive series_b mislabel:** Fixed to series_a for $21M Aug 2024 round
- **DARKHIVE INC. all-caps:** Normalized to Darkhive Inc. throughout brief

### New Machine Setup (Feb 19, 2026)
- Code synced via git, venv recreated at `~/projects/defense-alpha/venv`
- Python: `/opt/homebrew/bin/python3` (Python 3.14)
- ✅ `defense_alpha.db` restored (~243MB)
- ✅ `.env` configured with `SAM_GOV_API_KEY` + `ANTHROPIC_API_KEY`
- Domain: aperturesignals.com (live)
- Database filename remains `defense_alpha.db` (intentional, not rebranded)

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
| Deal intelligence briefs | `scripts/aperture_query.py` |
| Web enrichment pipeline | `scripts/enrich_entity.py` |
| Branded PDF generator | `scripts/generate_darkhive_pdf.py` |
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
| OTA scraper | `scrapers/sam_gov_ota.py` |
| Analyst note PDF | `scripts/generate_analyst_note.py` |
| Policy config | `config/policy_priorities.yaml` |
| DB models | `processing/models.py` |
| Fund manager CLI | `Fund/fund_manager.py` |
| Fund redeployment | `Fund/redeploy_fund.py` |
| Fund overview PDF | `Fund/generate_fund_overview.py` |
| Fund table creation | `Fund/create_fund_tables.py` |
| Fund strategy configs | `Fund/strategies/*.json` |
| Data quality audit | `scripts/audit_data_quality.py` |
| Employment target identifier | `scripts/employment_targets.py` |

---

## Strategic Context

**Business model:** Intelligence company, not SaaS platform. Reports are the product, engine is the back office. Defensibility: outcome tracking time series (time-locked), human intelligence from client feedback, analyst reputation. Revenue model: curated reports ($2-5K), quarterly intelligence briefs ($10-20K/yr).

**Architecture philosophy:**
- Local models: MiniLM-L6-v2 for embeddings/similarity (free, fast)
- API LLM: Claude for classification, scoring, RAG reasoning (~$55 for full universe)
- Future: predictive model on outcome tracking data (6-12 months)
- RAG connects embeddings (finding) to Claude (reasoning) — `aperture_query.py` achieves single-command deal briefs; RAG→sector report pipeline still TBD
- PDF generation: reportlab for fund overview one-sheeter (`Fund/generate_fund_overview.py`)

**Key validation:** Funding raise detector shows 80% true prediction rate with 35-month median lead time. SBIR phase transitions predict private capital raises ~3 years ahead — this is the core defensible insight. Phase II Signal report ($8.48B across 164 companies) is the proof point.

Don (first client) feedback: "All new SBIR companies to me!" on RF report. Validated investor leads report had companies new to him. Third deliverable (Darkhive brief) delivered; Don asked "how can you make money making connections?" — confirmed demand but Danny clarified lane: intelligence reports are the product, not introductions (active duty constraint). Pricing conversation triggers on next request.

**Rebrand:** Defense Alpha → Aperture Signals across 17 files. Domain: aperturesignals.com (live). Database filename remains `defense_alpha.db` (intentional).

---

*This document should give any Claude instance enough context to continue work on Aperture Signals.*
