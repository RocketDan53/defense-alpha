# Aperture Signals — Client Readiness Scorecard

**Generated:** 2026-03-11
**Audit Status:** PASS (0 failures, 5 warnings)

---

## Signal Stack

25 active signal types across 6,339 scored entities.

| Signal Type | Count | Weight | Decay |
|-------------|------:|--------|-------|
| high_priority_technology | 4,384 | +1.0 | No decay |
| sbir_phase_2_transition | 2,843 | +1.5 | Slow |
| sbir_graduation_speed | 2,391 | +1.5 | Slow |
| sbir_lapse_risk | 2,378 | -1.5 | Fast |
| sbir_to_vc_raise | 897 | +2.0 | Slow |
| customer_concentration | 803 | -1.5 | No decay |
| multi_agency_interest | 476 | +1.5 | No decay |
| funding_velocity | 420 | +1.5 | Fast |
| sbir_stalled | 412 | -2.0 | No decay |
| first_dod_contract | 411 | +1.0 | Fast |
| kop_alignment | 401 | +2.5 | No decay |
| gone_stale | 337 | -1.5 | No decay |
| sbir_breadth | 334 | +1.5 | No decay |
| policy_headwind | 296 | -1.5 | No decay |
| sbir_to_contract_transition | 285 | +3.0 | Slow |
| sbir_validated_raise | 275 | +2.5 | Slow |
| time_to_contract | 270 | +2.0 | Slow |
| contract_acceleration | 238 | +2.0 | Fast |
| rapid_contract_growth | 218 | +2.5 | Fast |
| commercial_pathway_fit | 82 | +1.5 | No decay |
| sole_source_award | 53 | +2.0 | Slow |
| outsized_award | 13 | +2.0 | Slow |
| multi_vehicle_presence | 11 | +1.5 | No decay |
| ota_bridge_award | 3 | +2.5 | Slow |
| contract_value_step_change | 3 | +2.0 | Fast |

**Positive types:** 20 | **Negative types:** 5

---

## Data Completeness

| Metric | Count |
|--------|------:|
| Total STARTUP entities | 9,657 |
| Complete data (contracts + funding + signals + policy) | 395 |
| At least one data gap | 9,262 |
| Entities with active signals | 6,339 |
| Entities with policy alignment scores | 8,798 |

---

## OTA Coverage

| Source | Entities |
|--------|------:|
| OTA contracts (FPDS scraper) | 66 |
| OTA awards (web enrichment) | 43 ingested findings |
| OTA bridge awards (signal) | 3 |

---

## Batch Enrichment Results

50 priority entities enriched (March 2026 batch).

| Finding Type | Ingested |
|-------------|------:|
| Partnerships | 113 |
| Contracts | 112 |
| Funding rounds | 69 |
| OTA awards | 43 |
| Public company flags | 3 |
| **Total** | **337** |

---

## Outcome Tracking

| Metric | Value |
|--------|-------|
| Total tracked outcomes | 1,976 |
| New contracts | 1,794 |
| Funding raises | 182 |
| Prediction rate (outcomes with preceding signal) | 100% |
| Average signal lead time | 41.5 months |

---

## Top 20 Data Coverage

17/20 entities have full data coverage. 3 have enrichment gaps.

| # | Entity | Score | Contracts | Value | Funding | Signals | Policy | Enriched | Gaps |
|--:|--------|------:|----------:|------:|--------:|--------:|-------:|---------:|------|
| 1 | Vannevar Labs | 27.90 | 5+12 OTA | $295.6M | 7 | 22 | 0.647 | 2026-03-12 | |
| 2 | X-Bow Launch Systems | 20.09 | 9+5 OTA | $450.5M | 10 | 16 | 0.547 | 2026-02-26 | |
| 3 | Seaflight Technologies | 15.94 | 0+13 OTA | $38.3M | 10 | 14 | 0.496 | never | No enrichment |
| 4 | Starfish Space | 13.01 | 7+0 | $190.0M | 15 | 11 | 0.712 | 2026-03-11 | |
| 5 | Lunar Outpost | 12.91 | 2+0 | $12.4M | 14 | 11 | 0.669 | 2026-03-11 | |
| 6 | Picogrid | 12.62 | 2+0 | $11.1M | 19 | 10 | 0.504 | 2026-03-11 | |
| 7 | DittoLive | 11.89 | 3+0 | $34.8M | 10 | 9 | 0.418 | 2026-03-12 | |
| 8 | Corvid Technologies | 11.68 | 10+0 | $1,010.1M | 133 | 12 | 0.484 | 2026-03-11 | |
| 9 | SI2 Technologies | 11.48 | 4+0 | $31.4M | 66 | 11 | 0.489 | 2026-03-12 | |
| 10 | Darkhive | 11.47 | 4+1 OTA | $107.3M | 13 | 12 | 0.508 | 2026-02-27 | |
| 11 | Windborne Systems | 11.32 | 1+0 | $6.0M | 7 | 9 | 0.439 | 2026-03-11 | |
| 12 | Defense Unicorns | 10.99 | 3+0 | $26.8M | 9 | 11 | 0.320 | 2026-03-11 | |
| 13 | Firehawk Aerospace | 10.97 | 4+0 | $15.5M | 6 | 10 | 0.497 | 2026-03-12 | |
| 14 | Benchmark Space Systems | 10.87 | 3+0 | $10.7M | 16 | 9 | 0.576 | 2026-03-12 | |
| 15 | Shipcom Federal Solutions | 10.55 | 7+1 OTA | $111.4M | 6 | 10 | 0.423 | 2026-03-12 | |
| 16 | Urban Sky Theory | 10.06 | 2+0 | $106.2M | 17 | 11 | 0.492 | 2026-03-11 | |
| 17 | Compound Eye | 10.05 | 1+0 | $9.2M | 7 | 7 | 0.425 | never | No enrichment |
| 18 | MZA Associates | 9.90 | 4+0 | $5.1M | 52 | 10 | 0.536 | 2026-03-11 | |
| 19 | Xona Space Systems | 9.72 | 3+0 | $26.2M | 8 | 8 | 0.526 | 2026-03-12 | |
| 20 | ADA Technologies | 9.70 | 1+0 | $7.6M | 58 | 11 | 0.395 | never | No enrichment |

---

## Score Movement (vs. Prior Run)

| Metric | Value |
|--------|------:|
| Entities with score changes | 4,920 / 6,339 |
| Average delta | -0.83 |
| Positive movers | 1,125 (avg +1.25) |
| Negative movers | 3,795 (avg -1.44) |
| Newly scored entities | 19 |

Primary drivers: +contract_acceleration (+2.0, 238 entities), +sbir_breadth (+1.5, 334 entities), -policy_headwind (-1.5, 296 entities), continued freshness decay on older signals.

---

## Audit Warnings (non-blocking)

- 21 STARTUPs with >$50M contracts — potential PRIME misclassification (known, validated as correct)
- 9 funding events >$5B — Facebook and MetLife Reg D filings (legitimate, non-defense entities)
- 47 NON_DEFENSE/PRIME entities fully scored — comparables queries filter by entity_type=STARTUP
- 1 contract >$50B — verify data accuracy
