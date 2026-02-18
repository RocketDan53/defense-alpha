# The Phase II Signal

**SBIR Phase II Awards as Leading Indicators of Private Capital Formation in Defense Technology**

Aperture Signals Intelligence Report | February 2026

---

## 1. Analyst's Note

The defense technology sector is undergoing a structural shift in how early-stage companies capitalize. This report presents evidence for a specific, testable thesis: **SBIR Phase II awards are a leading indicator of private capital raises in defense-adjacent startups, with a median lag of 8 months and a cumulative $8.5 billion in post-SBIR private capital across the validated cohort.**

### The Finding

Of 264 defense startups that hold both SBIR awards and SEC Reg D filings, 164 (62%) meet a strict validation test: their SBIR activity demonstrably preceded or catalyzed their private fundraising. These 164 companies have collectively raised **$8.48 billion** in private capital following their SBIR milestones.

This is not a coincidence of timing. The data shows a consistent pattern:

- **82 companies** (50% of the cohort) followed the textbook pathway: SBIR first, Phase II as catalyst, then private raise. These companies account for **$3.6 billion** in post-SBIR capital.
- **49 companies** (30%) won SBIRs before raising privately but without a direct Phase II catalyst event — indicating the SBIR portfolio itself, rather than a single award, built the credibility that attracted capital.
- **33 companies** (20%) show a mixed sequence where early private capital and SBIR activity overlapped, but a Phase II award preceded a measurable acceleration in fundraising.

The 100 companies filtered out of the loose cohort failed the sequencing test: 75 raised venture capital before winning any SBIR, and 25 had ambiguous timelines. The strict filter removes 38% of the raw signal, leaving a higher-confidence subset.

### Key Statistics

| Metric | Value |
|--------|-------|
| Validated cohort size | 164 companies |
| Total post-SBIR private capital | $8.48B |
| Companies raising $100M+ | 16 ($5.94B, 70% of total capital) |
| Companies raising $25–100M | 36 ($1.73B) |
| Companies raising $5–25M | 56 ($694M) |
| Companies raising under $5M | 56 ($110M) |
| Median Phase II → raise gap | 8 months (N=82 with catalyst) |
| Mean SBIR awards per company | 6.9 (range: 1–128) |
| Mean Phase II awards per company | 3.2 |
| Signal confidence (0.95 tier) | 55 companies (33%) |
| Signal confidence (0.85+ tier) | 133 companies (81%) |
| Strict vs. loose filter rate | 164 / 264 = 62% retained |

The concentration is stark: **16 companies account for 70% of all post-SBIR capital raised.** The long tail of 56 companies raising under $5M suggests the SBIR-to-raise pipeline operates at all scales, but the outsized outcomes cluster in aerospace and RF hardware.

### What This Means

For investors, Phase II awards function as a government-validated technical milestone — a signal that the Department of Defense has independently assessed a technology's feasibility and committed follow-on funding. The 8-month median gap represents a window of asymmetric information: the Phase II award is public, but the market has not yet priced in the private capital formation it predicts.

For the 3,221 Phase II startups in our database that have not yet filed a Reg D, this analysis suggests a substantial pipeline of potential first-time raises. The next-wave section of this report identifies the 15 highest-tailwind candidates.

---

## 2. Cohort Analysis

### 2.1 Sector Distribution

Software companies dominate by count (64, or 39% of the cohort), but aerospace platforms dominate by capital raised ($4.25B, or 50% of total). RF hardware punches far above its weight: just 7 companies account for $1.22B, driven primarily by SI2 Technologies' $1.16B raise.

| Sector | Companies | Capital Raised | Avg Raise | % of Total Capital |
|--------|-----------|---------------|-----------|-------------------|
| AEROSPACE_PLATFORMS | 30 | $4,247.7M | $141.6M | 50.1% |
| RF_HARDWARE | 7 | $1,217.5M | $173.9M | 14.4% |
| SOFTWARE | 64 | $1,221.8M | $19.1M | 14.4% |
| COMPONENTS | 43 | $958.6M | $22.3M | 11.3% |
| OTHER | 15 | $624.4M | $41.6M | 7.4% |
| SYSTEMS_INTEGRATOR | 4 | $201.3M | $50.3M | 2.4% |

**Interpretation:** The bimodal distribution — many small software raises vs. few massive aerospace raises — reflects the capital intensity of the underlying businesses. Satellite launchers and RF antenna systems require physical infrastructure; software companies can reach commercialization with smaller rounds.

### 2.2 Sector x Sequence

The `sbir_first` pathway dominates across all sectors, but the proportion of `mixed` signals varies meaningfully:

| Sector | sbir_first | mixed | % Mixed |
|--------|-----------|-------|---------|
| AEROSPACE_PLATFORMS | 20 ($2,935M) | 10 ($1,313M) | 33% |
| COMPONENTS | 33 ($743M) | 10 ($215M) | 23% |
| SOFTWARE | 54 ($878M) | 10 ($344M) | 16% |
| RF_HARDWARE | 6 ($1,213M) | 1 ($5M) | 14% |
| OTHER | 13 ($545M) | 2 ($80M) | 13% |
| SYSTEMS_INTEGRATOR | 4 ($201M) | 0 | 0% |

Aerospace has the highest mixed-sequence rate (33%), suggesting that in capital-intensive sectors, companies often begin raising private capital before their SBIR portfolio matures — but a Phase II award still catalyzes larger follow-on rounds.

### 2.3 Policy Alignment

Companies are scored against 10 National Defense Strategy priority areas, weighted by FY26 budget growth rates. The top policy verticals in the cohort:

| Policy Priority | Companies | Capital | Avg Tailwind |
|----------------|-----------|---------|--------------|
| Space Resilience | 43 | $3,505.0M | 0.71+ |
| Autonomous Systems | 22 | $488.3M | 0.70+ |
| Contested Logistics | 21 | $1,473.8M | 0.70+ |
| Cyber Offense/Defense | 14 | $176.6M | 0.70+ |
| JADC2 | 13 | $292.8M | 0.70+ |
| Hypersonics | 8 | $232.7M | 0.70+ |
| Electronic Warfare | 2 | $1,346.8M | 0.70+ |
| Supply Chain Resilience | 5 | $175.8M | 0.70+ |
| Border/Homeland | 5 | $169.2M | 0.70+ |
| Nuclear Modernization | 1 | $139.5M | 0.70+ |

**Space resilience** accounts for 26% of the cohort and 41% of capital raised — consistent with the FY26 budget's emphasis on proliferated LEO constellations, responsive launch, and space domain awareness. The electronic warfare category has only 2 companies but $1.35B in capital, reflecting SI2 Technologies' outsized position.

30 companies (18%) have no policy alignment score, indicating either a highly niche technology or insufficient data to classify against NDS priorities.

### 2.4 Raise Timing

For the 115 companies with Phase II catalyst data, the gap between Phase II award and subsequent Reg D filing distributes as follows:

| Gap Window | Companies | Avg Raise | Pattern |
|------------|-----------|-----------|---------|
| 0–3 months | 32 (28%) | $80.7M | Phase II serves as both independent signal and closing catalyst — VCs tracking SBIR milestones time raises around award announcements |
| 4–6 months | 20 (17%) | $19.4M | Fast followers — Phase II triggers fundraising process |
| 7–12 months | 40 (35%) | $54.7M | Standard cycle — full fundraise initiated post-award |
| 13–18 months | 23 (20%) | $18.8M | Slow burn — likely Phase II-to-Phase III bridge before private raise |

The highest average raise ($80.7M) is in the 0–3 month bucket, where Phase II serves as both an independent signal and a closing catalyst — VCs tracking SBIR milestones time raises around award announcements, and the government validation tips late-stage investor decisions. The 7–12 month bucket is the largest by count (35%), representing the standard fundraise cycle: Phase II award → investor outreach → term sheet → close.

49 companies lack gap data because they either have no Phase II (only Phase I preceded their raise) or their Phase II did not directly catalyze the raise.

### 2.5 Geography

| State | Companies | Capital | Notable Cluster |
|-------|-----------|---------|-----------------|
| California | 41 (25%) | $3,009M | El Segundo (launch), Bay Area (software) |
| Texas | 13 (8%) | $315M | Austin, San Antonio |
| Colorado | 12 (7%) | $198M | Colorado Springs (space) |
| Virginia | 7 (4%) | $125M | Northern VA (DoD-adjacent) |
| Massachusetts | 4 (2%) | $1,210M | Billerica (SI2 Technologies) |
| Florida | 3 (2%) | $222M | Space Coast |
| Other | 84 (51%) | $3,401M | Distributed |

California's dominance (25% of companies, 35% of capital) reflects the state's combined aerospace heritage and venture capital density. Massachusetts' outsized capital figure ($1.21B from 4 companies) is almost entirely SI2 Technologies.

### 2.6 SBIR Depth

The cohort's SBIR engagement ranges from shallow (1 award) to deeply embedded (128 awards):

| SBIR Profile | Description |
|-------------|-------------|
| Avg awards per company | 6.9 |
| Avg Phase II per company | 3.2 |
| Range | 1 – 128 |
| Top 5 most prolific | Corvid Technologies (128), SI2 Technologies (55), ADA Technologies (49), Technology Holding (25), AOSense (24) |

Companies with 15+ SBIRs tend to be long-standing government technology contractors that have recently attracted private capital — they represent deep technical moats built over a decade of government-funded R&D.

---

## 3. The Next Wave: Deal Flow Pipeline

Of the 3,221 Phase II startups in our database that have never filed a Reg D, the following 15 have the highest policy tailwind scores and recent Phase II activity (2023–2024). These are the companies that exhibit the pattern most associated with subsequent private capital formation based on the validated cohort.

All raise amounts below are listed as **$0** — these companies have no Reg D filings. That is the point: they match the pre-raise profile of the validated cohort.

---

### 3.1 Portal Space Systems

**Aerospace Platforms | Bothell, WA | Tailwind: 0.90 | 7 SBIRs, 4 Phase II**

Policy priority: Space Resilience. Portal is developing advanced propulsion for dynamic space operations, with recent Phase II awards for solar concentrator technology and a proprietary "Flare" propulsion system. Four Phase IIs across multiple programs suggests broadening DoD confidence in the platform. The space resilience tailwind (0.90) is the highest in the next-wave cohort.

*Recent Phase II:* Solar Concentrator Development and Validation Testing for Advanced Dynamic Space Operations (Sep 2024); Flare Propulsion Qualification Testing for Enhanced Dynamic Space Operations (Aug 2024)

### 3.2 Experimental Design & Analysis Solutions

**Software | Spring Hill, TN | Tailwind: 0.90 | 7 SBIRs, 3 Phase II**

Policy priority: Hypersonics. EDAS builds advanced test platform software to accelerate hypersonic testing — directly supporting one of the DoD's top modernization priorities. Three Phase IIs and a Tennessee headquarters position it outside the typical VC corridors, which may explain the absence of private capital to date.

*Recent Phase II:* Advanced Test Platform Software to Accelerate Hypersonic Testing (Aug 2024)

### 3.3 Katalyst Space Technologies

**Components | Flagstaff, AZ | Tailwind: 0.90 | 7 SBIRs, 3 Phase II**

Policy priority: Space Resilience. Building interoperable cislunar observation networks and lightweight modular perception enhancements. Three Phase IIs suggest progression from concept to prototype. The cislunar focus aligns with growing DoD interest in monitoring activity beyond GEO.

*Recent Phase II:* Interoperable Cislunar Observation Network (ICON) Phase II (Feb 2024)

### 3.4 Assured Space Access Technologies

**RF Hardware | Chandler, AZ | Tailwind: 0.90 | 4 SBIRs, 1 Phase II**

Policy priority: Space Resilience. Developing space domain awareness systems under the "FreeSpace" product line. Single Phase II but four total SBIRs indicate active program engagement. RF hardware companies in the validated cohort show the highest average raise ($173.9M per company).

*Recent Phase II:* FreeSpace Space Domain Awareness (Feb 2024)

### 3.5 Busek Co.

**Components | Natick, MA | Tailwind: 0.80 | 38 SBIRs, 17 Phase II**

Policy priority: Space Resilience. A deeply embedded SBIR veteran with 38 awards over a decade — one of the most prolific SBIR recipients in the defense startup ecosystem. Specializes in electric propulsion systems (ion thrusters) for small satellites. 17 Phase IIs represent extensive government validation. The absence of private capital despite this depth is notable and may represent a founder-preference for organic growth, or an acquisition opportunity.

Note: Deep SBIR portfolio with no private capital history may indicate a self-sustaining government revenue model rather than a pre-raise posture.

*Recent Phase II:* Thermal Improvement on 1 Newton ASCENT Thruster Valve Assembly (Feb 2024)

### 3.6 EBase

**Software | Sterling, VA | Tailwind: 0.80 | 8 SBIRs, 4 Phase II**

Policy priority: Space Resilience. Building adversarial space threat simulators and space battle management C2 course-of-action generators. Four Phase IIs in space defense software is a strong signal. Northern Virginia location provides DoD customer proximity.

*Recent Phase II:* Adversarial Space Threat Simulator for Space Defense and Counter-Space Operations (Aug 2024)

### 3.7 Magma Space

**Components | Washington, DC | Tailwind: 0.80 | 2 SBIRs, 1 Phase II**

Policy priority: Space Resilience. Developing magnetic bearing reaction wheels for low-jitter, long-life satellite operations. Early stage (2 SBIRs) but targeting a high-value component market for proliferated LEO constellations.

*Recent Phase II:* Magnetic bearing reaction wheels for low-jitter and long-life operations (Sep 2024)

### 3.8 Silotech Group

**Software | San Antonio, TX | Tailwind: 0.80 | 2 SBIRs, 1 Phase II**

Policy priority: Space Resilience. Building spaceport digital twins for operational optimization. San Antonio location near JBSA and Space Training and Readiness Command.

*Recent Phase II:* Orbital Evolution: Navigating the Future with Spaceport Digital Twins (Jul 2024)

### 3.9 TB2 Aerospace

**Components | Breckenridge, CO | Tailwind: 0.75 | 3 SBIRs, 1 Phase II**

Policy priority: Contested Logistics. Developing drone recharging operational payload systems for autonomous resupply — directly aligned with the contested logistics priority area. The drone logistics sector has attracted significant VC attention in the civilian market; a DoD-validated entrant could attract crossover interest.

*Recent Phase II:* Utilizing the Drone Recharging Operational Payload System to Automate Logistics (May 2024)

### 3.10 Multi-Domain Global Solutions

**Systems Integrator | Palm Harbor, FL | Tailwind: 0.75 | 1 SBIR, 1 Phase II**

Policy priority: Autonomous Systems. Building a completely autonomous perimeter surveillance system. Single Phase II but strong autonomous systems alignment.

*Recent Phase II:* Completely Autonomous Perimeter Surveillance System (CAPS) (Aug 2024)

### 3.11 Hybird Space Systems

**Components | Huntsville, AL | Tailwind: 0.74 | 2 SBIRs, 1 Phase II**

Policy priority: Space Resilience. Developing hybrid propulsion for low-cost, scalable tactical rocket motors. Huntsville location places it within the U.S. Army's Redstone Arsenal ecosystem.

*Recent Phase II:* Hybrid Propulsion for Low-Cost and Scalable Tactical Rocket Motors (Sep 2024)

### 3.12 Evolution Space

**Aerospace Platforms | Zion, IL | Tailwind: 0.72 | 2 SBIRs, 1 Phase II**

Policy priority: Hypersonics. Building affordable, rapid-response hypersonic boost and target solutions. Hypersonics remains a top-3 DoD modernization priority with limited commercial entrants.

*Recent Phase II:* Affordable, Rapid and Responsive Hypersonic Boost and Target Solutions (Aug 2024)

### 3.13 Scout Space

**Aerospace Platforms | Reston, VA | Tailwind: 0.71 | 8 SBIRs, 4 Phase II**

Policy priority: Space Resilience. Developing on-board perception and electro-optical space domain awareness sensors. Four Phase IIs and 8 total SBIRs place it in the upper tier of SBIR engagement for its size. The company adapts OWL EO/SDA sensors for operationally responsive deployment.

*Recent Phase II:* Leveraging On-board Perception Data Products for Tactically-Responsive Space Operations (Aug 2024)

### 3.14 Argo Space Corp

**Aerospace Platforms | El Segundo, CA | Tailwind: 0.71 | 2 SBIRs, 1 Phase II**

Policy priority: Space Resilience. Building the "Argonaut" — a refuelable space transport vehicle for contested logistics. The refuelable architecture addresses a key gap in current space logistics. El Segundo location within the space industrial base corridor.

*Recent Phase II:* The Argonaut: Refuellable Space Transport Vehicle for Contested Logistics (Dec 2023)

### 3.15 Hart Scientific Consulting International

**Components | Tucson, AZ | Tailwind: 0.71 | 17 SBIRs, 9 Phase II**

Policy priority: Space Resilience. Deep SBIR portfolio (17 awards, 9 Phase II) spanning wavefront correction, passive aircraft avoidance, and advanced imaging. Like Busek, the depth of government engagement without private capital raises the question of whether the company is self-sustaining on SBIR revenue alone.

*Recent Phase II:* Passive Aircraft Avoidance through EO/IR Imaging and Reconfigured Beacon Technology (Jul 2024)

---

## 4. Illustrative Case Studies

The following companies are drawn from the validated cohort to illustrate the three primary pathways from SBIR to private capital. They are not ranked — they are evidence for the thesis.

### Pathway A: Textbook SBIR-First

*The classic pattern: deep SBIR portfolio built over years, private capital follows government validation.*

**SI2 Technologies** (Billerica, MA) — RF Hardware
- **55 SBIRs, 29 Phase II** over a decade (2014–2024)
- First SBIR: Oct 2014. First Reg D: Dec 2020 — a **6-year** SBIR-only development period
- Post-SBIR capital: **$1.16B** across 7 Reg D filings (cumulative, dominated by a single $1.1B filing in Mar 2022). This filing likely represents PE/growth equity, not a typical venture round.
- Phase II titles span phased arrays, conformal antennas, radar-absorbing materials, hypersonic radomes, and electronic warfare — a broad RF technology platform
- Confidence: 0.95 | Gap: 3 months | Tailwind: 0.49 (electronic warfare)
- **Thesis link:** SI2 built an unassailable technical moat through 29 Phase II awards before attracting a transformative capital raise. The SBIR portfolio is the product development history.

**Corvid Technologies** (Mooresville, NC) — Aerospace Platforms
- **128 SBIRs, 47 Phase II** — the most prolific SBIR winner in the entire cohort
- First SBIR: Dec 2014. First Reg D: May 2021. Post-SBIR capital: **$105.3M** across 5 filings
- Phase II work includes cruise missile systems, hypersonic analysis, and damaged control surface assessment
- Confidence: 0.95 | Gap: 14 months | Tailwind: 0.36 (hypersonics)
- **Thesis link:** 128 SBIR awards is not a company dabbling in government R&D — it is a company whose technical agenda is defined by it. The 14-month gap after Phase II represents the standard fundraise cycle for a complex aerospace company.

**X-Bow Launch Systems** (Albuquerque, NM) — Aerospace Platforms
- **5 SBIRs, 3 Phase II** — lean but high-impact portfolio
- First SBIR: Jun 2018. First Reg D: Apr 2022. Post-SBIR capital: **$92.5M** across 4 filings
- Developing 3D-printed solid rocket motors and tactical launch capabilities
- Confidence: 0.95 | Gap: 3 months | Tailwind: 0.51 (space resilience)
- **Thesis link:** Fewer SBIRs, but each Phase II directly supported the core product (solid rocket motors). The 3-month gap suggests Phase II served as a closing catalyst for a raise already in motion.

### Pathway B: SBIR-to-Scale

*Companies that used a modest SBIR footprint as a launchpad, then raised substantially larger private rounds.*

**ABL Space Systems** (El Segundo, CA) — Aerospace Platforms
- **5 SBIRs, 2 Phase II**
- First SBIR: Dec 2019. First Reg D: Mar 2020 — only **3 months** between first SBIR and first raise
- Post-SBIR capital: **$480.3M** across 5 Reg D filings
- Phase II work on rapid tactical space launch and operational flexibility demonstrations
- Confidence: 0.95 | Gap: 3 months | Tailwind: 0.77 (space resilience — highest in the case study set)
- **Thesis link:** ABL's SBIR engagement was surgical — 5 awards that validated the core responsive launch thesis, followed by rapid private capital formation. The 0.77 tailwind score reflects perfect alignment with the DoD's highest-growth budget lines.

**Gecko Robotics** (Pittsburgh, PA) — Systems Integrator
- **4 SBIRs, 2 Phase II**
- First SBIR: Aug 2019. First Reg D: May 2025. Post-SBIR capital: **$121.5M** in a single filing
- Phase II work on robotic inspections for ICBM infrastructure and predictive analytics for Minuteman III/GBSD sustainment
- Confidence: 0.85 | No Phase II catalyst | Tailwind: 0.45 (contested logistics)
- **Thesis link:** Gecko is primarily a commercial robotics company that used SBIRs to enter the defense market. The 6-year gap between first SBIR and Reg D, and the single large round, suggest the SBIR portfolio was part of a broader commercial story — but the nuclear sustainment work likely contributed to the company's defense credibility.

### Pathway C: Mixed Signal

*Companies where private capital and SBIR activity overlapped, but a Phase II award preceded measurable fundraising acceleration.*

**Antares Nuclear** (Torrance, CA) — Nuclear/Space
- **3 SBIRs, 2 Phase II**
- First Reg D: Oct 2023 ($8.1M). First SBIR: Dec 2023 (Phase I). Phase IIs: Aug 2024
- Post-SBIR capital: **$78.6M** — comprising $27.5M (Sep 2024) + $51.0M (Sep 2025)
- Phase II work on deployable microreactors and nuclear space power
- Confidence: 0.85 | Gap: 1 month | Tailwind: 0.61 (space resilience)
- **Thesis link:** Antares' initial Reg D ($8.1M) predated any SBIR activity, but the two Phase II awards in Aug 2024 preceded a $78.6M capital surge. The 1-month gap between Phase II and the next raise is the tightest in the case study set — suggesting the awards directly catalyzed investor confidence in a nuclear technology company where government validation carries exceptional weight.

**Hidden Level** (Syracuse, NY) — Software
- **4 SBIRs, 2 Phase II**
- First Reg D: Jun 2021 ($15.9M). First SBIR: Nov 2022. Phase IIs: Apr–May 2024
- Post-SBIR capital: **$109.1M** across 4 Reg D filings (cumulative)
- Phase II work on scalable UAS detection services and airspace monitoring
- Confidence: 0.85 | Gap: 3 months | Tailwind: 0.52 (border/homeland)
- **Thesis link:** Hidden Level raised initial capital before any SBIR engagement, but Phase II awards in 2024 preceded a significant step-up in round sizes. The UAS detection market is policy-driven (border/homeland security), and SBIR validation provided credibility with defense-focused investors even though the company was already venture-backed.

---

## 5. Methodology

### 5.1 Signal Detection

The `sbir_validated_raise` signal applies the following logic to every entity in the database:

**Trigger conditions** (must satisfy at least one):
1. **SBIR-first pathway:** The entity's first SBIR award (any phase) predates its first Reg D filing
2. **Phase II catalyst:** A Reg D filing occurs within 18 months (548 days) after a Phase II award

**Confidence scoring:**
- Base: 0.70
- +0.10 if SBIR-first pathway is satisfied
- +0.10 if Phase II catalyst is satisfied
- +0.05 if post-SBIR raise exceeds $5M
- Cap: 0.95

**Reg D deduplication:** Filings with identical (entity_id, event_date, amount) tuples are treated as amended filings and deduplicated before analysis. This removed 25 duplicate groups totaling $1.67B in inflated capital across the full dataset.

**Post-SBIR raise calculation:** Sum of all Reg D filing amounts that occur after the entity's first SBIR award date. This is a cumulative total across all Reg D filings, not a single round. Companies with multiple filings (e.g., SI2 Technologies with 7 filings) will show a cumulative figure.

### 5.2 Policy Alignment

Each entity is scored against 10 National Defense Strategy priority areas using a combination of:
- SBIR award title text matching against priority-area keyword taxonomies
- Weighting by FY26 budget growth rates per priority area
- Composite tailwind score (0.0–1.0) representing alignment with budget growth vectors

### 5.3 Cohort Construction

The validated cohort is built by:
1. Starting with all entities that have both SBIR awards and Reg D filings (264)
2. Applying the strict `sbir_validated_raise` trigger conditions (164 pass)
3. Excluding merged entities (duplicate resolution)
4. Computing enrichment data (composite scores, policy alignment, activity summaries)

The next-wave pipeline is built by:
1. Selecting all STARTUP entities with Phase II awards
2. Excluding any entity with a Reg D filing
3. Filtering for policy tailwind > 0.3 and Phase II activity since January 2023
4. Ranking by tailwind score, then Phase II count

### 5.4 Raise Amounts

All raise amounts in this report are **cumulative Reg D totals**, not single funding rounds. A company listed as raising "$381.9M" may have achieved that total across 3, 5, or 10 separate SEC filings over several years. This is a deliberate choice: the thesis concerns the total private capital attracted after SBIR validation, not the size of any individual round.

Reg D filings report "total amount sold" which may include debt, equity, or convertible instruments. We do not distinguish between instrument types. Some filings report $0 or NULL amounts and are excluded from raise calculations but included in filing counts.

---

## 6. Data Provenance & Limitations

### 6.1 Data Sources

| Source | Coverage | Freshness |
|--------|----------|-----------|
| SBIR.gov | All Phase I, II, III awards across DoD agencies | Through Sep 2024 |
| SEC EDGAR | Reg D filings (Form D) for private placements | Through Oct 2025 |
| Entity resolution | Proprietary matching across SBIR and SEC datasets | 27,529 SBIR embeddings |

### 6.2 Known Limitations

**Reg D coverage gaps:** Not all private fundraises require a Form D filing. Companies raising exclusively from non-US investors, or those operating under certain exemptions, may not appear in SEC data. The true volume of post-SBIR private capital is likely higher than reported.

**Reg D amount accuracy:** Form D filings report "total amount sold" which may be amended over time. Our deduplication catches same-date/same-amount amendments, but sequential amendments with different amounts are treated as separate filings. SI2 Technologies' $1.1B single filing, for example, may represent a rolling close reported at the final amount.

**SBIR date formats:** Historical SBIR records use inconsistent date formats (MM/DD/YYYY vs. YYYY-MM-DD), which limits year-over-year trend analysis for awards before 2023. All gap calculations use parsed dates and are unaffected by format inconsistency.

**Survivorship bias:** This analysis only includes companies that have both SBIR awards and Reg D filings. Companies that won SBIRs but failed before raising capital, or that were acquired before filing a Reg D, are not represented. The true SBIR-to-raise conversion rate is lower than the cohort statistics suggest.

**Causal inference:** This report identifies correlation and temporal sequence, not causation. We cannot definitively prove that a Phase II award caused a private raise — only that it preceded one with statistical regularity. Confounding factors (founder networks, market timing, technology maturity) are not controlled for.

**Entity resolution:** Matching SBIR awardees to SEC filers requires fuzzy name matching and manual review. Despite deduplication and merge resolution, some entities may be incorrectly linked or missing.

**Single-SBIR companies:** 23 companies in the cohort have only 1 SBIR award. For these companies (e.g., Relativity Space with a single $50K Phase I), the causal link between SBIR and private raise is weakest. The signal is technically valid but the SBIR may be incidental rather than formative.

---

*Report generated by Aperture Signals intelligence platform. Data as of February 2026. All raise amounts are cumulative Reg D totals. Signal detection methodology available in processing/signal_detector.py. QA verification: 178/178 checks passed across top 20 cohort companies (scripts/qa_report_data.py).*
