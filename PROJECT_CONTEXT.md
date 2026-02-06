# Defense Alpha: Project Context for New Claude Session

**Last Updated:** February 5, 2026
**Purpose:** Spin up a new Claude instance with full context on the Defense Alpha project

---

## What Is Defense Alpha

A Python-based defense intelligence platform that aggregates government and private market data to identify investment signals in defense technology companies. Built to surface emerging companies with real traction for defense investors, sales consultants, and BD teams.

---

## Current Data State

| Source | Records | Value | Status |
|--------|---------|-------|--------|
| DoD Contracts (USASpending) | 5,147 | $805B | ✅ Working (partial backfill) |
| SBIR/STTR Awards | ~1,653 | ~$27M | ✅ Working |
| SEC Form D (VC Funding) | 1,979 | $109B | ✅ Working |
| **Entities** | 4,517 | - | 147 primes, rest startups |
| **Funding Events** | 3,632 | - | SBIR + Reg D combined |
| **Signals** | 1,944 | - | Across 13 types |

---

## Signal Detection Engine

**13 signal types, 1,944 total signals:**

| Signal | Count | Direction | Description |
|--------|-------|-----------|-------------|
| high_priority_technology | 457 | + | AI, quantum, hypersonics, space, cyber, autonomy, directed energy |
| customer_concentration | 383 | − | >80% revenue from single agency (risk) |
| multi_agency_interest | 255 | + | Contracts from 2+ DoD branches |
| sbir_to_vc_raise | 236 | + | SBIR company raised private capital |
| sbir_phase_2_transition | 228 | + | Advanced from Phase I → II |
| sbir_graduation_speed | 159 | + | Faster than median Phase I→II time |
| funding_velocity | 130 | + | 2+ funding rounds in 18 months |
| sbir_stalled | 57 | − | 2+ Phase I, zero Phase II (red flag) |
| outsized_award | 26 | + | Contract significantly above company average |
| sbir_to_contract_transition | 6 | + | SBIR → real procurement |
| time_to_contract | 4 | + | Speed of SBIR → contract graduation |
| rapid_contract_growth | 2 | + | YoY contract acceleration |
| first_dod_contract | 1 | + | New market entrant |

**Composite Scoring:** Risk-adjusted ranking combining all signals with weights. Score range: -2.75 to 6.05.

---

## Key Capabilities Built

| Capability | Command | Status |
|------------|---------|--------|
| Pull DoD contracts | `python scrapers/usaspending.py --start-date 2024-01-01` | ✅ |
| Pull SBIR awards | `python scrapers/sbir.py` | ✅ |
| Pull VC funding | `python scrapers/sec_edgar.py --start-date 2024-01-01` | ✅ |
| Deduplicate entities | `python scripts/run_entity_resolution.py` | ✅ |
| Detect signals | `python scripts/detect_signals.py --top 30` | ✅ |
| Rank companies | `python scripts/calculate_composite_scores.py --top 50` | ✅ |
| Semantic search | `python scripts/find_similar.py --company "Anduril"` | ✅ |
| Technology clusters | `python scripts/tech_clusters.py --n-clusters 20` | ✅ |
| Generate prospect reports | `python scripts/generate_prospect_report.py --query "..." --output report.pdf` | ✅ |

---

## Architecture

```
defense-alpha/
├── scrapers/
│   ├── usaspending.py      # DoD contracts from USASpending API
│   ├── sbir.py             # SBIR/STTR awards
│   └── sec_edgar.py        # SEC Form D private funding
├── processing/
│   ├── models.py           # SQLAlchemy models (Entity, Contract, FundingEvent, Signal, etc.)
│   ├── database.py         # DB connection and session management
│   ├── entity_resolver.py  # Deduplication with fuzzy matching
│   ├── entity_classifier.py # Prime vs startup classification
│   ├── signal_detector.py  # All signal detection logic
│   ├── technology_tagger.py # Keyword-based tech categorization
│   └── business_classifier.py # NEW: LLM-based core business classification (needs testing)
├── scripts/
│   ├── detect_signals.py
│   ├── calculate_composite_scores.py
│   ├── run_entity_resolution.py
│   ├── find_similar.py     # Semantic search over SBIR embeddings
│   ├── tech_clusters.py    # K-means clustering of SBIR abstracts
│   └── generate_prospect_report.py # PDF/MD report generator
├── reports/
│   └── rf_comms_prospects.pdf # Sample client deliverable
├── data/
│   └── defense_alpha.db    # SQLite database
├── docs/
│   ├── DATA_COLLECTION_PLAN.md
│   ├── DATA_COLLECTION_CHECKLIST.md
│   ├── CLAUDE_CODE_PROMPTS.md
│   └── CLAUDE_CODE_PRIMER.md
└── requirements.txt
```

---

## Database Schema (Key Tables)

**entities:**
- id (UUID), canonical_name, entity_type (prime/startup/investor/agency)
- cage_code, duns_number, ein, uei
- headquarters_location, founded_date, technology_tags (JSON)
- website_url, core_business (NEW - enum), core_business_confidence, core_business_reasoning
- merged_into_id (for deduplication)

**contracts:**
- id, entity_id (FK), contract_number, contract_value, award_date
- contracting_agency (sub-agency level), naics_code, psc_code
- period_of_performance_start/end, place_of_performance, raw_data (JSON)

**funding_events:**
- id, entity_id (FK), event_type (sbir_phase_1/2/3, reg_d_filing, vc_round, etc.)
- amount, event_date, investors_awarders (JSON), raw_data (JSON)

**signals:**
- id, entity_id (FK), signal_type, confidence_score (0-1)
- detected_date, evidence (JSON), status (active/expired/validated/false_positive)

**sbir_embeddings:**
- funding_event_id (FK), entity_id (FK), award_title, embedding (BLOB - 384-dim vector)

---

## Recent Work: Client MVP

**Delivered:** RF & Communications Emerging Company Report for Don (defense sales consultant)
- 10 verified RF hardware companies
- Analyst's Note with market synthesis
- PDF with branding, methodology, company profiles

**Key learnings from that process:**
1. Semantic search matches keywords but not business models ("mesh" in software ≠ "mesh" in radios)
2. Had to manually curate - removed Havenlock (door locks), Tetrate (software), NextGen Aeronautics (structures)
3. Need systematic business classification to avoid false positives in future reports

---

## Current Task: Business Classifier

**Problem:** Semantic search finds topical relevance but not business model fit. Companies get flagged because their SBIR title mentions "RF" even if they're a software company that just processes RF signals.

**Solution in progress:** Add `core_business` classification to entities:
- rf_hardware, software, systems_integrator, aerospace_platforms, components, services, other, unclassified

**Files created:**
- `processing/business_classifier.py` - LLM-based classifier (calls Anthropic API)
- Schema updated with core_business, core_business_confidence, core_business_reasoning fields

**Blocker:** API credits issue. Need to either:
1. Add Anthropic API credits
2. Have Claude Code classify directly (it can read DB and update)
3. Classify manually based on SBIR data

**Test companies for validation:**
1. PHASE SENSITIVE INNOVATIONS INC → should be rf_hardware
2. THRUST AI LLC → should be software
3. ZENITH AEROSPACE INC → should be aerospace_platforms
4. XL SCIENTIFIC LLC → should be rf_hardware
5. HAVENLOCK INC → should be other (door locks)
6. TETRATE.IO, INC. → should be software
7. MATRIXSPACE, INC → should be rf_hardware
8. SOLSTAR SPACE COMPANY → should be rf_hardware
9. FOURTH STATE COMMUNICATIONS, LLC → should be rf_hardware
10. TERASPATIAL INC → should be rf_hardware

---

## Parking Lot (Future Work)

**Data depth (needs disk upgrade):**
- [ ] Full USASpending backfill (50-100K contracts vs current 5K)
- [ ] Full SBIR historical pull (2015-present)
- [ ] SAM.gov CAGE code enrichment

**Defensibility improvements:**
- [ ] Outcome tracking (which flagged companies actually won contracts/raised?)
- [ ] Harder data sources (FPDS, congressional markup, program office org charts)
- [ ] Workflow stickiness (weekly email alerts, watchlists)
- [ ] Network effects (multi-user tagging, consensus signals)

**Product surface:**
- [ ] Dashboard / web UI
- [ ] Automated weekly reports
- [ ] API for integrations

---

## How to Start a Session

```
I'm working on defense-alpha at ~/projects/defense-alpha

cd ~/projects/defense-alpha && source venv/bin/activate

Defense intelligence platform with:
- 5,147 contracts, 4,517 entities, 1,944 signals across 13 types
- Semantic search over SBIR embeddings
- Composite scoring with risk adjustment
- PDF report generation

Database: SQLite at data/defense_alpha.db

Current task: Implementing business classifier to fix false positives in prospect reports.
The classifier script exists at processing/business_classifier.py but needs API credits.
Alternative: classify directly using Claude Code's built-in reasoning.

Show me current DB stats to confirm state, then let's continue.
```

---

## Key Files to Reference

If you need to understand specific implementations:
- **Entity resolution logic:** `processing/entity_resolver.py`
- **Signal detection:** `processing/signal_detector.py`
- **Report generation:** `scripts/generate_prospect_report.py`
- **Semantic search:** `scripts/find_similar.py`
- **Business classifier:** `processing/business_classifier.py`

---

## Strategic Context

From recent analysis on defensibility:
- **Moat is in data infrastructure** (pipelines, connectors, entity resolution) - not the LLM layer
- **Classification is plumbing** - useful but not defensible
- **Outcome tracking would be defensible** - backtest which signals predict success
- **Workflow integration creates stickiness** - alerts, watchlists, embedded in user's daily process

Don (first client) feedback: "All new SBIR companies to me!" - validation that filtering works. He suggested targeting VCs + Primes as customers ("matchmaker" positioning).

---

*This document should give any Claude instance enough context to continue work on Defense Alpha.*
