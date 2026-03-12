# Aperture Signals: Business Strategy

**Author:** Danny | **Date:** March 2026 | **Status:** Pre-revenue, productizing

---

## What Aperture Is

Aperture Signals is a defense intelligence platform that maps government spending to private capital markets. It tracks every SBIR award, defense contract, and SEC filing, links them to the same companies through entity resolution, and detects signals that predict where private money is going to flow.

**One-liner:** Aperture tells defense investors where the government's money is going before the market figures it out.

**Core thesis (validated):** SBIR Phase II awards predict private capital raises with a ~35-month lead time. 164 validated companies, $8.48B in post-SBIR capital formation, 80% prediction accuracy. This isn't a backtest claim — it's derived from cross-referencing SBIR.gov awards against SEC EDGAR Form D filings across the full universe.

---

## The Problem

Defense capital markets are informationally broken. The data exists — SBIR awards, USASpending contracts, SEC filings, OTA awards, policy documents — but it's fragmented across dozens of government databases with no entity resolution, no temporal linking, and no signal layer. The result:

- **Investors** can't systematically identify which SBIR-stage companies are gaining real traction versus burning through government R&D grants with no commercial path
- **Defense founders** don't know how they compare to peers on government traction, funding timing, or policy alignment
- **BD consultants** lack the data to match capabilities to opportunities or identify warm introductions through investor networks
- **VCs writing $5-50M checks** are making decisions based on founder pitches and gut feel, not on whether the government's money is actually flowing toward the problem the company claims to solve

Every defense VC fund has an analyst spending 20 hours on diligence that Aperture answers in minutes. Every BD consultant is manually tracking SBIR awards in spreadsheets. Every defense founder is guessing at comparables and raise timing. The information asymmetry is the product opportunity.

---

## What's Built

**Data infrastructure (the moat):**
- ~9,655 startups, 876 primes tracked with entity resolution across all sources
- 13,904 contracts ($1.16T+), 32,659+ funding events, 17,297 active signals
- 15+ signal types with tiered freshness decay (fast/slow/none by category)
- Policy alignment scoring against 10 NDS budget priorities with FY26 growth weights
- MEIA/KOP/JAR acquisition reform framework integrated (6 new signal types)
- Knowledge graph: 39,712 relationships (agency, investor, policy edges)
- SBIR semantic search: 27,529 embeddings for technology similarity
- Web enrichment pipeline that closes data gaps per-entity via Claude + web search
- Notional fund: 3 strategies, 120 positions, matched-pair benchmarks for thesis validation

**Product surfaces (validated through delivery):**
- 9-section deal intelligence briefs (single command → branded PDF)
- Client-facing brief variant (strips methodology, adds contacts and opportunity sections)
- Sector intelligence reports (RF/Comms: 56 companies delivered)
- Thesis reports (Phase II Signal: 164 companies, $8.48B)
- Analyst notes (one-page competitive positioning PDFs)
- Comparables engine (technology-tag-aware peer benchmarking)
- Investor syndicate analysis (SEC EDGAR Form D director extraction)
- Employment target identifier (signal-weighted startup scoring)

**Reports delivered:** 10 total across deal briefs, sector reports, thesis reports, analyst notes, and investor syndicate analysis. One active client relationship (Don, defense sales consultant). Three deliverables provided free to establish value; pricing conversation pending.

---

## Go-to-Market Strategy

### Phase 1: Boutique Intelligence (Months 0-6)

**Goal:** First revenue. Validate that people will pay for what Aperture produces.

**Immediate actions:**
- Price next deliverable for Don at $500-1,000 per deal brief. Frame as: "Delivered three free to build the product, now taking paying clients." If he pushes back, learn what format/depth/frequency he'd pay for.
- Package 2-3 sample deliverables for outreach: Phase II Signal report + one enriched deal brief (Firestorm Labs or X-Bow showing full data depth). Branded PDFs, ready to hand over without explanation.
- Run 5-10 outreach conversations with defense-focused VCs and family offices over 30 days. Not selling the platform — selling a specific deliverable: "Which SBIR-stage companies are most likely to raise in the next 12 months, and who's already investing in adjacent thesis areas." Hook: the Phase II Signal thesis.
- Send Phase II Signal teaser to Konstantine. Let him pull the full report rather than pushing it.

**Target customers:**
- Defense BD consultants like Don ($250-500/brief, $2-5K for investor syndicate reports)
- Small/mid defense VCs doing their own sourcing ($2-5K per deal brief, $10-20K/year for quarterly sector intelligence)
- Defense startup founders preparing for fundraise ($1-2K for competitive positioning + comparables)

**Revenue target:** $25-50K in first 6 months from 5-10 paying clients. This isn't about the money — it's about proving the model and learning what the market actually wants.

**What NOT to build:** No web app. No dashboard. No API. No authentication. The product is a branded PDF in someone's inbox, generated from a command line. Every hour on invisible infrastructure is an hour not on revenue conversations.

### Phase 2: Subscription Intelligence (Months 6-18)

**Goal:** Recurring revenue. Shift from one-off reports to ongoing relationships.

**Products:**
- **Quarterly sector briefs** ($10-20K/year per subscriber): Themed intelligence reports covering a sector (autonomous systems, space resilience, EW, etc.) with updated rankings, new entrants, policy shifts, and raise predictions. 20-30 pages, branded, exclusive.
- **Monthly signal alerts** ($5-10K/year): Automated email digest of significant signal changes — new Phase II transitions, funding raises, contract wins, policy alignment shifts — filtered to the subscriber's areas of interest. This is where pipeline automation pays off.
- **On-demand deal briefs** ($500-2,500 each): Ad hoc deep dives when a subscriber is evaluating a specific company. Turnaround: 24-48 hours. Enriched, web-verified, branded.

**Revenue target:** $100-200K/year from 10-20 subscribers. This is the "real business" threshold — enough to sustain full-time operations, fund data source improvements, and build track record.

**Infrastructure investments (now justified by revenue):**
- Batch enrichment pipeline for pre-delivery quality (run across priority entities before each quarterly report)
- Resume SAM.gov OTA scraper (biggest data gap, now worth the effort)
- Automated signal alert generation and email delivery
- Client portal for report access (simple, not a platform — think shared Google Drive with branded folder structure, or a basic Notion workspace)

### Phase 3: Strategic Positioning (Months 12-24)

**Goal:** Build the asset and reputation that enables the next move — whether that's scaling Aperture, launching a fund, or joining one.

This is where the paths diverge. The first 12 months of revenue and client relationships create optionality. Three possible directions:

---

## Path A: Scale Aperture as a Standalone Business

**What it looks like:** Continue growing the subscriber base. Hire 1-2 analysts. Productize further (possibly a lightweight SaaS layer for recurring subscribers). Target $500K-1M ARR.

**Analogues:** Govini (raised $120M+, sells to government buyers), Janes (defense intelligence, acquired for $350M+), Preqin (alternative assets data, acquired for $3.5B). These are different scales, but the model is the same: proprietary data + analysis + recurring subscriptions.

**Pros:** You own the whole thing. Aperture's data compounds daily — every day the snapshots run, you have trajectory data nobody else has. The moat deepens with time.

**Cons:** Intelligence businesses are labor-intensive. Scaling beyond $500K means hiring, and hiring means managing people instead of building product. The defense market is small enough that 50-100 subscribers might be the ceiling for a niche intelligence product.

**When to choose this:** If by month 12 you have 15+ paying subscribers and demand is growing faster than you can serve it alone.

## Path B: Launch a Defense VC Fund Using Aperture as Infrastructure

**What it looks like:** Raise a small fund ($10-25M) with Aperture as the proprietary sourcing and diligence engine. You're the GP with a quantitative edge — every investment thesis backed by signal data, comparables, and policy alignment scoring that no other fund has.

**The pitch to LPs:** "We built the intelligence layer between the Pentagon's budget and private capital markets. Our signals predict funding raises 35 months ahead with 80% accuracy. We don't just source deals — we know which companies the government is about to validate before the market does."

**The notional fund is already building the track record.** Three strategies deployed Q1 2026 with matched-pair benchmarks. If the signal cohort outperforms the benchmark cohort on milestones at the 12-month scan (June 2026), that's a concrete, dated, defensible claim. Not a backtest — a real-time demonstration.

**Pros:** Highest upside. Aligns the data asset with capital deployment. Carried interest + management fees + Aperture intelligence revenue = multiple income streams. Defense VC is a growing space with room for differentiated entrants.

**Cons:** Raising a fund is a 12-18 month process. You need a track record (the notional fund helps but isn't a substitute for real returns). LP fundraising is a full-time job that competes with everything else. Regulatory and compliance overhead is real.

**When to choose this:** If by month 12-18 you have (a) Aperture generating $100K+ revenue proving the intelligence model works, (b) the notional fund showing measurable signal alpha, and (c) LP relationships developed through the intelligence business.

## Path C: Join a Defense VC Fund as a Partner with Proprietary Deal Flow

**What it looks like:** Approach defense-focused funds (Shield Capital, Razor's Edge, Heroic Ventures, Sapient Capital, Marque Ventures) not as an associate applicant but as a partner bringing proprietary sourcing infrastructure they can't build internally.

**The play:**
1. Months 0-6: Build Aperture's client base. Some of those clients will be at VC funds. Deliver intelligence they can't get elsewhere.
2. Months 6-12: The intelligence relationship naturally evolves into deal flow sharing. You're surfacing companies they should look at. They start relying on your signal data for diligence.
3. Months 12-18: The conversation shifts from "we buy your reports" to "what would it look like if you were on our team?" You negotiate from a position where you're bringing a functioning intelligence platform, an existing client book, and operational credibility as a Marine pilot/JTAC.

**What you bring that no other candidate does:**
- Proprietary deal sourcing engine (Aperture) — systematically identifies investment targets before they're on anyone else's radar
- Operational credibility for diligence — you can evaluate whether a "sensor-to-shooter" pitch maps to real warfighter workflows because you've closed kill chains as a JTAC
- Existing client relationships in defense — your intelligence subscribers become the fund's deal flow network
- Quantitative thesis validation — the notional fund with matched-pair benchmarks is more rigorous than anything most emerging managers bring to LP conversations

**Target funds:**
- **Shield Capital** — defense-focused, DC-based, would value the systematic sourcing approach
- **Razor's Edge** — veteran-founded, defense technology thesis, natural cultural fit
- **Heroic Ventures** — national security focus, smaller team where Aperture would be transformational
- **a16z American Dynamism** — larger platform, but the defense practice is growing and differentiated sourcing matters
- **Lux Capital** — deep tech thesis includes defense, Josh Wolfe has been vocal about defense tech opportunity

**Pros:** Immediate compensation (salary + carry). Access to LP capital without raising your own fund. Learn fund operations with someone else's infrastructure and compliance. Aperture can continue as a side vehicle or be absorbed into the fund's operations.

**Cons:** You give up control. The fund may want Aperture's data exclusively. Your equity upside is carry in their fund, not ownership of your own business. If the cultural fit is wrong, you're an employee with a fancy title.

**When to choose this:** If by month 12 you've built strong relationships with 2-3 fund GPs through intelligence delivery, and one of them makes an offer that's compelling enough to trade independence for.

---

## The Recommended Sequence

Don't choose a path now. Execute Phase 1 and Phase 2 while keeping all three options open. The work is the same regardless:

**Months 0-6:** Get to first revenue. Price Don's next brief. Run 5-10 outreach conversations. Learn what the market wants. Ship the `aperture_query.py` upgrade (MEIA integration, PDF generation, client-facing mode). Deliver 5-10 paid reports.

**Months 6-12:** Build to $100K+ ARR. Launch quarterly sector briefs. Develop relationships with 2-3 defense VC GPs through intelligence delivery (they're clients first, potential partners second). Run the first notional fund milestone scan (June 2026). Resume OTA scraper to close the biggest data gap.

**Month 12 decision point:** You'll have revenue data, client feedback, notional fund results, and VC relationships. The right path will be obvious by then because you'll have the information you need to decide. Today you don't.

**The one thing that matters right now:** Send an invoice. Everything else is infrastructure for a business that hasn't proven anyone will pay for it yet.

---

## Competitive Landscape

**Who else does this:** Nobody, exactly. The closest comparisons are:

| Competitor | What They Do | Why Aperture Is Different |
|---|---|---|
| Govini | SaaS platform for government acquisition officials | Sells TO government; Aperture sells ABOUT government to private market |
| Janes | Defense intelligence (capabilities, threat assessments) | Focused on military capabilities and ORBAT, not capital markets |
| PitchBook / Crunchbase | Startup funding data | No defense signal layer, no SBIR integration, no policy alignment |
| GovWin (Deltek) | Government contract opportunity tracking | Forward-looking contract opportunities, not backward-looking signal detection |
| Defense Investor Network | Deal flow matchmaking for defense investors | Marketplace model, no proprietary analytics or signal detection |
| Bloomberg Government | Policy and budget tracking for government market | Policy-focused, no entity-level signal detection or capital market prediction |

**Aperture's moat:** The combination of fragmented data sources unified through entity resolution, proprietary signal definitions, and temporal trajectory data that compounds daily. The SBIR-to-capital prediction (80% accuracy, 35-month lead) is the proof that the assembled dataset produces insights nobody else has. The MEIA/KOP framework adds a forward-looking layer that maps the new acquisition system before structured data even exists. No one can replicate this by prompting an LLM because the data infrastructure underneath doesn't exist anywhere else in assembled form.

---

## Founder Positioning

**Danny's credibility stack:**
- Marine Corps helicopter pilot/instructor — understands aviation systems, cockpit integration, human-machine teaming
- JTAC at 1st ANGLICO — the human node in the kill chain; has coordinated joint/coalition fires, operated in degraded comms, managed sensor-to-shooter workflows under fire
- Built Aperture from raw government data to functioning intelligence platform — demonstrates technical capability, data engineering skill, and domain synthesis
- Operational experience maps directly to the highest-growth defense tech areas: JADC2, autonomous systems, contested comms, sensor fusion

This combination — operator credibility + data engineering + defense market intelligence — is extremely rare. Most defense VCs have either the finance background or the military background, rarely both, and almost never paired with a proprietary data asset. That's the differentiation, whether deploying it as a business, a fund, or a partnership.

---

## Key Metrics to Track

| Metric | Phase 1 Target | Phase 2 Target | Why It Matters |
|---|---|---|---|
| Paid reports delivered | 5-10 | 30-50 | Revenue validation |
| Recurring subscribers | 0 | 10-20 | Business model validation |
| Revenue | $25-50K | $100-200K | Sustainability threshold |
| Notional fund signal alpha | Deployed | Measured (June 2026) | Thesis validation |
| VC GP relationships | 2-3 conversations | 2-3 active clients | Path C optionality |
| Data coverage (OTA contracts) | 752 | 5,000+ | Credibility with sophisticated buyers |
| Prediction accuracy (maintained) | 80% | 80%+ | Core defensibility claim |

---

*The best time to send an invoice was three deliverables ago. The second best time is the next one.*
