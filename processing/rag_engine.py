"""
RAG (Retrieval-Augmented Generation) engine for Aperture Signals.

Combines semantic search over SBIR embeddings with entity intelligence
enrichment and Claude-powered reasoning to answer natural language
questions about the defense industrial base.

Usage:
    from processing.rag_engine import RAGEngine
    from processing.database import SessionLocal

    db = SessionLocal()
    engine = RAGEngine(db)
    # Raw retrieval + enrichment (no Claude call):
    results = engine.retrieve("counter-drone RF systems")
    enriched = engine.enrich(results)
    context = engine.build_context(enriched)

    # Full pipeline with Claude reasoning:
    from anthropic import Anthropic
    engine = RAGEngine(db, client=Anthropic())
    response = engine.query("companies building jam-resistant tactical radios")
"""

import json
import logging
import re
import struct
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from processing.models import (
    Entity,
    EntityType,
    CoreBusiness,
    Contract,
    Signal,
    SignalStatus,
    FundingEvent,
    FundingEventType,
    SbirEmbedding,
)
from processing.signal_detector import (
    SIGNAL_SBIR_PHASE_2,
    SIGNAL_SBIR_PHASE_3,
    SIGNAL_FIRST_DOD_CONTRACT,
    SIGNAL_RAPID_GROWTH,
    SIGNAL_HIGH_PRIORITY_TECH,
    SIGNAL_MULTI_AGENCY,
    SIGNAL_OUTSIZED_AWARD,
    SIGNAL_SBIR_TO_CONTRACT,
    SIGNAL_SBIR_TO_VC,
    SIGNAL_SBIR_GRADUATION_SPEED,
    SIGNAL_TIME_TO_CONTRACT,
    SIGNAL_FUNDING_VELOCITY,
    SIGNAL_SBIR_STALLED,
    SIGNAL_CUSTOMER_CONCENTRATION,
    SIGNAL_GONE_STALE,
    SIGNAL_SBIR_VALIDATED_RAISE,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
DEFAULT_SIMILARITY_THRESHOLD = 0.25
DEFAULT_TOKEN_BUDGET = 12_000
CHARS_PER_TOKEN = 4  # conservative estimate for English + numbers
MAX_TITLES_PER_ENTITY = 5
MIN_ENTITIES_WARNING = 3

# Signal weights (mirrored from generate_prospect_report.py / calculate_composite_scores.py)
POSITIVE_WEIGHTS = {
    SIGNAL_SBIR_TO_CONTRACT: 3.0,
    SIGNAL_RAPID_GROWTH: 2.5,
    SIGNAL_SBIR_TO_VC: 2.0,
    SIGNAL_OUTSIZED_AWARD: 2.0,
    SIGNAL_SBIR_PHASE_3: 2.0,
    SIGNAL_TIME_TO_CONTRACT: 2.0,
    SIGNAL_SBIR_PHASE_2: 1.5,
    SIGNAL_MULTI_AGENCY: 1.5,
    SIGNAL_SBIR_GRADUATION_SPEED: 1.5,
    SIGNAL_FUNDING_VELOCITY: 1.5,
    SIGNAL_HIGH_PRIORITY_TECH: 1.0,
    SIGNAL_FIRST_DOD_CONTRACT: 1.0,
    SIGNAL_SBIR_VALIDATED_RAISE: 2.5,
}

NEGATIVE_WEIGHTS = {
    SIGNAL_SBIR_STALLED: -2.0,
    SIGNAL_CUSTOMER_CONCENTRATION: -1.5,
    SIGNAL_GONE_STALE: -1.5,
}

ALL_WEIGHTS = {**POSITIVE_WEIGHTS, **NEGATIVE_WEIGHTS}

SIGNAL_DISPLAY_NAMES = {
    SIGNAL_SBIR_TO_CONTRACT: "SBIR->Contract",
    SIGNAL_RAPID_GROWTH: "Rapid Growth",
    SIGNAL_SBIR_TO_VC: "SBIR + VC Raise",
    SIGNAL_OUTSIZED_AWARD: "Outsized Award",
    SIGNAL_SBIR_PHASE_2: "SBIR Phase II",
    SIGNAL_SBIR_PHASE_3: "SBIR Phase III",
    SIGNAL_MULTI_AGENCY: "Multi-Agency",
    SIGNAL_HIGH_PRIORITY_TECH: "High-Priority Tech",
    SIGNAL_FIRST_DOD_CONTRACT: "First DoD Contract",
    SIGNAL_SBIR_GRADUATION_SPEED: "Fast SBIR Graduation",
    SIGNAL_TIME_TO_CONTRACT: "Fast Time-to-Contract",
    SIGNAL_FUNDING_VELOCITY: "Funding Velocity",
    SIGNAL_SBIR_STALLED: "SBIR Stalled",
    SIGNAL_CUSTOMER_CONCENTRATION: "Customer Concentration",
    SIGNAL_GONE_STALE: "Gone Stale",
    SIGNAL_SBIR_VALIDATED_RAISE: "SBIR Validated Raise",
}

SBIR_PHASE_TYPES = [
    FundingEventType.SBIR_PHASE_1,
    FundingEventType.SBIR_PHASE_2,
    FundingEventType.SBIR_PHASE_3,
]


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    """Single entity result from semantic retrieval."""
    entity_id: str
    similarity: float
    matching_titles: list  # list of (similarity, title) tuples


@dataclass
class EnrichedEntity:
    """Fully enriched entity with all intelligence data."""
    entity_id: str
    similarity: float
    name: str
    location: str
    entity_type: str
    core_business: str
    core_business_confidence: float
    policy_alignment: Optional[dict]
    composite_score: float
    positive_score: float
    negative_score: float
    positive_signals: list
    negative_signals: list
    activity: dict
    matching_titles: list
    contracts_summary: dict
    funding_summary: dict


@dataclass
class RAGResponse:
    """Structured response from the full RAG pipeline."""
    question: str
    relevant_companies: list
    watchlist: list
    gaps: list
    summary: str
    entities_retrieved: int
    entities_enriched: int
    context_tokens_estimate: int
    elapsed_seconds: float
    raw_context: Optional[str] = None
    _enriched: Optional[list] = field(default=None, repr=False)

    def to_report_input(self) -> list:
        """Return ranked entity IDs for generate_prospect_report.py.

        Output format matches what generate_prospect_report.py expects:
        a list of dicts with entity_id, name, similarity, composite_score,
        and stage — ordered by the RAG ranking (Claude's ranking if
        available, otherwise by similarity).

        Usage:
            response = engine.query("counter-drone RF systems")
            report_input = response.to_report_input()
            # [{"rank": 1, "entity_id": "abc-123", "name": "...", ...}, ...]
        """
        # If Claude ranked them, use that order
        if self.relevant_companies:
            ranked_names = [
                c.get("name", "").upper() for c in self.relevant_companies
            ]
            # Build lookup from enriched data
            enriched_by_name = {}
            if self._enriched:
                for e in self._enriched:
                    enriched_by_name[e.name.upper()] = e

            output = []
            rank = 1
            for name_upper in ranked_names:
                e = enriched_by_name.get(name_upper)
                if e:
                    output.append({
                        "rank": rank,
                        "entity_id": e.entity_id,
                        "name": e.name,
                        "similarity": round(e.similarity, 4),
                        "composite_score": e.composite_score,
                        "stage": e.activity["stage"],
                    })
                    rank += 1
            if output:
                return output

        # Fallback: use enriched entities in similarity order
        if not self._enriched:
            return []

        return [
            {
                "rank": i,
                "entity_id": e.entity_id,
                "name": e.name,
                "similarity": round(e.similarity, 4),
                "composite_score": e.composite_score,
                "stage": e.activity["stage"],
            }
            for i, e in enumerate(
                sorted(self._enriched, key=lambda x: -x.similarity), 1
            )
        ]


# ── Helper functions ─────────────────────────────────────────────────────

def _deserialize_embedding(data: bytes) -> np.ndarray:
    """Unpack bytes to float32 array (same format as find_similar.py)."""
    n = len(data) // 4  # 4 bytes per float32
    return np.array(struct.unpack(f"{n}f", data), dtype=np.float32)


def _clean_title(title: str) -> str:
    """Strip leading junk characters from SBIR titles."""
    title = re.sub(r'^[?\s\x00-\x1f\ufffd]+', '', title)
    return title.strip()


def _format_currency(val: float) -> str:
    """Format dollar amounts for display."""
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:.0f}"


def _compute_composite(db: Session, entity_id: str) -> dict:
    """Compute composite score and signal list for one entity.

    Adapted from generate_prospect_report.py:compute_composite.
    """
    signals = db.query(Signal).filter(
        Signal.entity_id == entity_id,
        Signal.status == SignalStatus.ACTIVE,
    ).all()

    positive_score = 0.0
    negative_score = 0.0
    positive_signals = []
    negative_signals = []

    for sig in signals:
        weight = ALL_WEIGHTS.get(sig.signal_type, 0.0)
        confidence = float(sig.confidence_score or 0)
        freshness = float(sig.freshness_weight or 1.0)
        weighted = weight * confidence * freshness
        display = SIGNAL_DISPLAY_NAMES.get(sig.signal_type, sig.signal_type)

        entry = {
            "name": display,
            "type": sig.signal_type,
            "score": round(weighted, 2),
            "confidence": confidence,
            "freshness": freshness,
        }

        if weight > 0:
            positive_score += weighted
            positive_signals.append(entry)
        elif weight < 0:
            negative_score += weighted
            negative_signals.append(entry)

    positive_signals.sort(key=lambda x: -x["score"])
    negative_signals.sort(key=lambda x: x["score"])

    return {
        "composite": round(positive_score + negative_score, 2),
        "positive": round(positive_score, 2),
        "negative": round(negative_score, 2),
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
    }


def _collect_funding_data(db: Session, entity_id: str) -> tuple:
    """Single query for all funding_events; returns (activity_dict, funding_summary).

    Replaces the former _get_entity_activity (funding half) and
    _collect_funding_summary — one DB round-trip instead of eight.
    """
    events = db.query(FundingEvent).filter(
        FundingEvent.entity_id == entity_id,
    ).all()

    sbir_total = 0.0
    sbir_count = 0
    latest_sbir = None
    regd_total = 0.0
    vc_rounds = 0
    vc_total = 0.0
    latest_regd = None

    sbir_set = {t.value for t in SBIR_PHASE_TYPES}
    vc_set = {FundingEventType.REG_D_FILING.value, FundingEventType.VC_ROUND.value}

    for ev in events:
        ev_type = ev.event_type.value if ev.event_type else None
        amount = float(ev.amount or 0)

        if ev_type in sbir_set:
            sbir_count += 1
            sbir_total += amount
            if ev.event_date and (latest_sbir is None or ev.event_date > latest_sbir):
                latest_sbir = ev.event_date

        if ev_type in vc_set:
            vc_rounds += 1
            vc_total += amount
            if ev_type == FundingEventType.REG_D_FILING.value:
                regd_total += amount
                if ev.event_date and (latest_regd is None or ev.event_date > latest_regd):
                    latest_regd = ev.event_date

    funding_summary = {
        "sbir_count": sbir_count,
        "sbir_total": sbir_total,
        "vc_rounds": vc_rounds,
        "vc_total": vc_total,
    }

    funding_activity = {
        "latest_sbir": latest_sbir,
        "latest_regd": latest_regd,
        "total_sbir": sbir_total,
        "total_regd": regd_total,
        "sbir_count": sbir_count,
    }

    return funding_activity, funding_summary


def _collect_contract_data(db: Session, entity_id: str) -> tuple:
    """Single query for all contracts; returns (activity_dict, contracts_summary).

    Replaces the former _get_entity_activity (contract half) and
    _collect_contract_summary — one DB round-trip instead of four.
    """
    contracts = db.query(Contract).filter(
        Contract.entity_id == entity_id,
    ).all()

    if not contracts:
        empty_activity = {
            "latest_contract": None,
            "total_contract": 0.0,
            "contract_count": 0,
        }
        empty_summary = {"count": 0, "total_value": 0.0, "agencies": []}
        return empty_activity, empty_summary

    total_value = 0.0
    latest_contract = None
    agencies = set()

    for c in contracts:
        total_value += float(c.contract_value or 0)
        if c.award_date and (latest_contract is None or c.award_date > latest_contract):
            latest_contract = c.award_date
        if c.contracting_agency:
            agencies.add(c.contracting_agency)

    contract_activity = {
        "latest_contract": latest_contract,
        "total_contract": total_value,
        "contract_count": len(contracts),
    }

    contracts_summary = {
        "count": len(contracts),
        "total_value": total_value,
        "agencies": sorted(agencies),
    }

    return contract_activity, contracts_summary


def _build_activity(funding_activity: dict, contract_activity: dict) -> dict:
    """Merge funding + contract activity into a single activity dict with stage."""
    dates = [
        d for d in [
            funding_activity["latest_sbir"],
            contract_activity["latest_contract"],
            funding_activity["latest_regd"],
        ] if d
    ]
    latest_activity = max(dates) if dates else None

    total_value = (
        funding_activity["total_sbir"]
        + contract_activity["total_contract"]
        + funding_activity["total_regd"]
    )

    if total_value > 100_000_000:
        stage = "Growth / Scale-up"
    elif total_value > 20_000_000:
        stage = "Series B+"
    elif total_value > 5_000_000:
        stage = "Series A"
    elif total_value > 1_000_000:
        stage = "Seed / Early"
    else:
        stage = "Pre-seed / SBIR"

    return {
        "latest_sbir": funding_activity["latest_sbir"],
        "latest_contract": contract_activity["latest_contract"],
        "latest_regd": funding_activity["latest_regd"],
        "latest_activity": latest_activity,
        "total_sbir": funding_activity["total_sbir"],
        "total_contract": contract_activity["total_contract"],
        "total_regd": funding_activity["total_regd"],
        "total_value": total_value,
        "sbir_count": funding_activity["sbir_count"],
        "contract_count": contract_activity["contract_count"],
        "stage": stage,
    }


# ── RAG Engine ───────────────────────────────────────────────────────────

class RAGEngine:
    """Retrieval-Augmented Generation engine for defense intelligence queries.

    Loads SBIR embeddings into memory on init for fast semantic search.
    Enriches retrieved entities with signals, contracts, funding, and
    policy alignment data. Optionally sends enriched context to Claude
    for structured analysis.
    """

    def __init__(self, db: Session, client=None):
        """Initialize the RAG engine.

        Args:
            db: SQLAlchemy session for database queries.
            client: anthropic.Anthropic instance. Optional — only needed
                    for the reason() and query() methods. Pass None for
                    retrieval + enrichment only (--raw mode).
        """
        self.db = db
        self.client = client

        # Load sentence-transformer model
        logger.info("Loading sentence-transformer model: %s", MODEL_NAME)
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(MODEL_NAME)

        # Load ALL embeddings into memory (27,529 × 384 ≈ 40MB)
        logger.info("Loading embeddings into memory...")
        t0 = time.time()
        self._embeddings, self._meta = self._load_embeddings()

        if self._embeddings is None:
            raise RuntimeError(
                "No embeddings found in database. "
                "Run `python scripts/find_similar.py --embed` first."
            )

        n_entities = len(set(m["entity_id"] for m in self._meta))
        logger.info(
            "Loaded %d embeddings (%d entities) in %.1fs",
            len(self._meta), n_entities, time.time() - t0,
        )

    def _load_embeddings(self):
        """Load all SBIR embeddings from DB, L2-normalize for cosine sim."""
        rows = self.db.query(SbirEmbedding).all()
        if not rows:
            return None, None

        embeddings = np.zeros((len(rows), EMBEDDING_DIM), dtype=np.float32)
        meta = []

        for i, row in enumerate(rows):
            embeddings[i] = _deserialize_embedding(row.embedding)
            meta.append({
                "entity_id": row.entity_id,
                "funding_event_id": row.funding_event_id,
                "award_title": row.award_title,
            })

        # L2 normalize for cosine similarity via dot product
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        embeddings = embeddings / norms

        return embeddings, meta

    # ── Step 1: Retrieval ────────────────────────────────────────────

    def retrieve(self, question: str, top_k: int = 50) -> list:
        """Embed the query and retrieve top_k entities by cosine similarity.

        Groups SBIR awards by entity, keeps the highest similarity per
        entity, drops results below the similarity threshold, and caps
        titles at MAX_TITLES_PER_ENTITY per entity.

        Returns:
            List of RetrievalResult, sorted by similarity descending.
        """
        # Encode query with same MiniLM model
        query_vec = self._model.encode([question])[0]
        query_vec = query_vec / np.linalg.norm(query_vec)

        # Cosine similarity via dot product (embeddings already L2-normalized)
        similarities = self._embeddings @ query_vec

        # Group by entity_id: keep max similarity + collect all titles
        entity_scores = {}
        entity_titles = defaultdict(list)

        for i, meta in enumerate(self._meta):
            eid = meta["entity_id"]
            sim = float(similarities[i])
            title = meta["award_title"]

            entity_titles[eid].append((sim, title))
            if eid not in entity_scores or sim > entity_scores[eid]:
                entity_scores[eid] = sim

        # Filter by similarity threshold
        filtered = {
            eid: score for eid, score in entity_scores.items()
            if score >= DEFAULT_SIMILARITY_THRESHOLD
        }

        if not filtered:
            logger.warning(
                "No entities above similarity threshold %.2f for: %s",
                DEFAULT_SIMILARITY_THRESHOLD, question,
            )
            return []

        # Rank and take top_k
        ranked = sorted(filtered.items(), key=lambda x: -x[1])[:top_k]

        results = []
        for eid, score in ranked:
            # Sort titles by similarity descending, cap at 5
            titles = sorted(entity_titles[eid], key=lambda x: -x[0])
            titles = [
                (s, _clean_title(t))
                for s, t in titles[:MAX_TITLES_PER_ENTITY]
                if _clean_title(t)
            ]
            results.append(RetrievalResult(
                entity_id=eid,
                similarity=score,
                matching_titles=titles,
            ))

        logger.info(
            "Retrieved %d entities (from %d above threshold) for: %s",
            len(results), len(filtered), question[:60],
        )

        if len(results) < MIN_ENTITIES_WARNING:
            logger.warning(
                "Only %d entities retrieved — limited database coverage "
                "for this query.", len(results),
            )

        return results

    # ── Step 2: Enrichment ───────────────────────────────────────────

    def enrich(self, results: list) -> list:
        """Enrich retrieval results with full entity intelligence data.

        For each entity, pulls: classification, policy alignment, active
        signals, composite score, contracts summary, funding summary,
        and activity timeline.

        Skips merged entities.

        Returns:
            List of EnrichedEntity, same order as input.
        """
        enriched = []

        for r in results:
            entity = self.db.query(Entity).filter(
                Entity.id == r.entity_id,
            ).first()

            if not entity or entity.merged_into_id:
                continue

            # Composite score from active signals
            scoring = _compute_composite(self.db, r.entity_id)

            # Funding data (1 query for all funding_events)
            funding_activity, funding_summary = _collect_funding_data(
                self.db, r.entity_id,
            )

            # Contract data (1 query for all contracts)
            contract_activity, contracts_summary = _collect_contract_data(
                self.db, r.entity_id,
            )

            # Merge into activity dict with stage
            activity = _build_activity(funding_activity, contract_activity)

            # Policy alignment (JSON field on entity)
            policy = entity.policy_alignment

            enriched.append(EnrichedEntity(
                entity_id=r.entity_id,
                similarity=r.similarity,
                name=entity.canonical_name,
                location=entity.headquarters_location or "",
                entity_type=(
                    entity.entity_type.value if entity.entity_type else "unknown"
                ),
                core_business=(
                    entity.core_business.value
                    if entity.core_business else "unclassified"
                ),
                core_business_confidence=float(
                    entity.core_business_confidence or 0
                ),
                policy_alignment=policy,
                composite_score=scoring["composite"],
                positive_score=scoring["positive"],
                negative_score=scoring["negative"],
                positive_signals=scoring["positive_signals"],
                negative_signals=scoring["negative_signals"],
                activity=activity,
                matching_titles=r.matching_titles,
                contracts_summary=contracts_summary,
                funding_summary=funding_summary,
            ))

        logger.info("Enriched %d entities", len(enriched))
        return enriched

    # ── Step 3: Context building ─────────────────────────────────────

    def build_context(self, enriched: list,
                      max_tokens: int = DEFAULT_TOKEN_BUDGET) -> str:
        """Format enriched entities into a text context for Claude.

        Entities are included in similarity-descending order. Stops adding
        entities when the next section would exceed the token budget.
        Warns if fewer than MIN_ENTITIES_WARNING entities fit.

        Returns:
            Formatted context string.
        """
        entities = sorted(enriched, key=lambda e: -e.similarity)

        sections = []
        total_chars = 0
        max_chars = max_tokens * CHARS_PER_TOKEN

        for entity in entities:
            section = self._format_entity_section(entity)
            section_chars = len(section)

            if total_chars + section_chars > max_chars and sections:
                # Would exceed budget and we already have some — stop
                logger.info(
                    "Token budget reached after %d entities (est. %d tokens)",
                    len(sections), total_chars // CHARS_PER_TOKEN,
                )
                break

            sections.append(section)
            total_chars += section_chars

        if len(sections) < MIN_ENTITIES_WARNING:
            warnings.warn(
                f"Only {len(sections)} entities fit within {max_tokens}-token "
                f"budget. Database may have limited coverage for this query.",
                stacklevel=2,
            )

        header = (
            f"=== DEFENSE INTELLIGENCE CONTEXT ===\n"
            f"Entities: {len(sections)}\n"
            f"Estimated tokens: {total_chars // CHARS_PER_TOKEN}\n"
            f"---\n"
        )

        return header + "\n\n".join(sections)

    def _format_entity_section(self, entity: EnrichedEntity) -> str:
        """Format a single enriched entity as a text section."""
        lines = []

        # Header
        loc = f" ({entity.location})" if entity.location else ""
        lines.append(f"### {entity.name}{loc}")
        lines.append(
            f"Similarity: {entity.similarity:.3f} | "
            f"Composite: {entity.composite_score:.2f} | "
            f"Type: {entity.entity_type} | "
            f"Business: {entity.core_business} "
            f"(conf: {entity.core_business_confidence:.2f})"
        )

        # SBIR titles (already capped at 5)
        if entity.matching_titles:
            lines.append("SBIR Awards:")
            for sim, title in entity.matching_titles:
                lines.append(f"  - [{sim:.3f}] {title}")

        # Signals
        if entity.positive_signals:
            sig_strs = [
                f"{s['name']}({s['score']:+.1f})"
                for s in entity.positive_signals[:5]
            ]
            lines.append(f"Positive Signals: {', '.join(sig_strs)}")

        if entity.negative_signals:
            sig_strs = [
                f"{s['name']}({s['score']:+.1f})"
                for s in entity.negative_signals
            ]
            lines.append(f"Risk Signals: {', '.join(sig_strs)}")

        # Financial summary
        fs = entity.funding_summary
        cs = entity.contracts_summary
        fin_parts = []
        if fs["sbir_count"]:
            fin_parts.append(
                f"{fs['sbir_count']} SBIRs ({_format_currency(fs['sbir_total'])})"
            )
        if cs["count"]:
            fin_parts.append(
                f"{cs['count']} contracts ({_format_currency(cs['total_value'])})"
            )
        if fs["vc_rounds"]:
            fin_parts.append(
                f"{fs['vc_rounds']} VC/Reg D rounds "
                f"({_format_currency(fs['vc_total'])})"
            )
        if fin_parts:
            lines.append(f"Financial: {' | '.join(fin_parts)}")

        lines.append(f"Stage: {entity.activity['stage']}")

        # Policy alignment
        if entity.policy_alignment:
            pa = entity.policy_alignment
            top = pa.get("top_priorities", [])
            tailwind = pa.get("policy_tailwind_score", 0)
            pacific = pa.get("pacific_relevance", False)
            if top:
                pac_tag = " [PACIFIC]" if pacific else ""
                lines.append(
                    f"Policy Alignment: {', '.join(top[:4])} "
                    f"(tailwind: {tailwind:.3f}){pac_tag}"
                )

        # Contracting agencies
        if cs["agencies"]:
            lines.append(
                f"Contracting Agencies: {', '.join(cs['agencies'][:5])}"
            )

        # Latest activity
        if entity.activity["latest_activity"]:
            lines.append(
                f"Latest Activity: {entity.activity['latest_activity']}"
            )

        return "\n".join(lines)

    # ── Step 4: Claude reasoning ─────────────────────────────────────

    def reason(self, question: str, context: str) -> dict:
        """Send enriched context to Claude for structured analysis.

        Requires an Anthropic client to be set on the engine.

        Returns:
            Dict with relevant_companies, watchlist, gaps, summary.
        """
        if self.client is None:
            raise RuntimeError(
                "No Anthropic client provided. Cannot call Claude. "
                "Pass an Anthropic client to RAGEngine or use --raw mode."
            )

        n_entities = context.count("### ")

        system_prompt = (
            "You are a defense intelligence analyst working with a "
            "proprietary database of defense technology companies. You have "
            "deep knowledge of DoD procurement, SBIR programs, and the "
            "defense industrial base.\n\n"
            "Analyze the provided intelligence data to answer questions "
            "about companies in the defense sector. Be specific, cite "
            "evidence from the data (SBIR awards, signals, contract values), "
            "and distinguish between high-confidence and speculative "
            "assessments."
        )

        user_prompt = (
            f"QUESTION: {question}\n\n"
            f"INTELLIGENCE DATA ({n_entities} companies retrieved by "
            f"semantic similarity):\n\n{context}\n\n"
            "INSTRUCTIONS:\n"
            "1. Filter out companies that aren't truly relevant to the "
            "query — semantic search finds keyword matches that may not "
            "be business-model matches.\n"
            "2. Rank remaining companies by fit to the query.\n"
            "3. For each relevant company, explain WHY they're relevant "
            "in 1-2 sentences, citing specific SBIR awards or signals.\n"
            "4. Flag any companies worth WATCHING but not a direct match "
            "(adjacent technology, early stage, or notable risk signals).\n"
            "5. Note any GAPS — areas the query covers that have few or "
            "no companies in the database.\n\n"
            "Respond as JSON:\n"
            "{\n"
            '  "relevant_companies": [\n'
            '    {"name": "...", "rank": 1, '
            '"relevance_reason": "...", '
            '"key_evidence": ["..."], '
            '"risk_factors": ["..."]}\n'
            "  ],\n"
            '  "watchlist": [\n'
            '    {"name": "...", "reason": "...", '
            '"watch_for": "..."}\n'
            "  ],\n"
            '  "gaps": ["..."],\n'
            '  "summary": "2-3 sentence synthesis"\n'
            "}"
        )

        logger.info("Sending %d-token context to Claude...", len(context) // CHARS_PER_TOKEN)

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text.strip()

        # Parse JSON — handle markdown code fences
        json_text = raw_text
        if json_text.startswith("```"):
            json_text = json_text.split("```")[1]
            if json_text.startswith("json"):
                json_text = json_text[4:]
            json_text = json_text.strip()

        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            logger.error("Failed to parse Claude response as JSON")
            logger.debug("Raw response: %s", raw_text[:500])
            return {
                "relevant_companies": [],
                "watchlist": [],
                "gaps": ["Failed to parse Claude response"],
                "summary": raw_text[:500],
            }

    # ── Full pipeline ────────────────────────────────────────────────

    def query(self, question: str, top_k: int = 50,
              filters: dict = None, max_results: int = 15) -> RAGResponse:
        """Run the full RAG pipeline: retrieve → enrich → filter → reason.

        Args:
            question: Natural language query.
            top_k: Number of entities to retrieve from semantic search.
            filters: Optional dict with keys like 'core_business',
                     'min_composite', 'entity_type'.
            max_results: Maximum entities in the final context.

        Returns:
            RAGResponse with structured analysis and metadata.
        """
        t0 = time.time()

        # Step 1: Retrieve
        retrieval_results = self.retrieve(question, top_k=top_k)

        if not retrieval_results:
            return RAGResponse(
                question=question,
                relevant_companies=[],
                watchlist=[],
                gaps=["No entities matched the query above the "
                      f"similarity threshold ({DEFAULT_SIMILARITY_THRESHOLD})."],
                summary="No matching entities found in the database.",
                entities_retrieved=0,
                entities_enriched=0,
                context_tokens_estimate=0,
                elapsed_seconds=time.time() - t0,
                _enriched=[],
            )

        # Step 2: Enrich
        enriched = self.enrich(retrieval_results)

        # Step 3: Apply filters
        if filters:
            enriched = self._apply_filters(enriched, filters)

        # Cap at max_results
        enriched = enriched[:max_results]

        # Step 4: Build context
        context = self.build_context(enriched)
        context_tokens = len(context) // CHARS_PER_TOKEN

        # Step 5: Reason
        result = self.reason(question, context)

        return RAGResponse(
            question=question,
            relevant_companies=result.get("relevant_companies", []),
            watchlist=result.get("watchlist", []),
            gaps=result.get("gaps", []),
            summary=result.get("summary", ""),
            entities_retrieved=len(retrieval_results),
            entities_enriched=len(enriched),
            context_tokens_estimate=context_tokens,
            elapsed_seconds=time.time() - t0,
            raw_context=context,
            _enriched=enriched,
        )

    def _apply_filters(self, enriched: list, filters: dict) -> list:
        """Apply optional filters to enriched entities."""
        result = enriched

        if filters.get("core_business"):
            val = filters["core_business"]
            result = [e for e in result if e.core_business == val]

        if filters.get("min_composite") and filters["min_composite"] > 0:
            threshold = filters["min_composite"]
            result = [e for e in result if e.composite_score >= threshold]

        if filters.get("entity_type"):
            val = filters["entity_type"]
            result = [e for e in result if e.entity_type == val]

        if len(result) < len(enriched):
            logger.info(
                "Filters reduced entities from %d to %d",
                len(enriched), len(result),
            )

        return result
