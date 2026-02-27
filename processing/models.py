"""
Aperture Signals Intelligence Engine - Database Models

SQLAlchemy ORM models for the intelligence platform.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Enums
class EntityType(PyEnum):
    STARTUP = "startup"
    PRIME = "prime"
    RESEARCH = "research"  # Universities, FFRDCs, APLs, think tanks
    INVESTOR = "investor"
    AGENCY = "agency"
    NON_DEFENSE = "non_defense"  # Commercial companies with no defense footprint


class CoreBusiness(PyEnum):
    """What the company primarily builds or sells."""
    RF_HARDWARE = "rf_hardware"              # Builds radios, antennas, radar, EW systems
    SOFTWARE = "software"                     # Builds software products
    SYSTEMS_INTEGRATOR = "systems_integrator" # Integrates others' tech into solutions
    AEROSPACE_PLATFORMS = "aerospace_platforms"  # Builds aircraft, spacecraft, drones, satellites
    COMPONENTS = "components"                 # Builds parts/subsystems, not full systems
    SERVICES = "services"                     # Consulting, support, training, R&D services
    OTHER = "other"                           # Doesn't fit above categories
    UNCLASSIFIED = "unclassified"            # Not yet classified


class FundingEventType(PyEnum):
    VC_ROUND = "vc_round"
    SBIR_PHASE_1 = "sbir_phase_1"
    SBIR_PHASE_2 = "sbir_phase_2"
    SBIR_PHASE_3 = "sbir_phase_3"
    CONTRACT = "contract"
    ACQUISITION = "acquisition"
    REG_D_FILING = "reg_d_filing"
    PRIVATE_ROUND = "private_round"


class SignalStatus(PyEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    VALIDATED = "validated"
    FALSE_POSITIVE = "false_positive"


class OutcomeType(PyEnum):
    """Types of outcomes we track for signal validation."""
    NEW_CONTRACT = "new_contract"           # Won DoD/federal contract
    FUNDING_RAISE = "funding_raise"         # New Reg D filing or VC round
    SBIR_ADVANCE = "sbir_advance"           # Phase progression (I->II, II->III)
    ACQUISITION = "acquisition"             # Acquired by another entity
    NEW_AGENCY = "new_agency"               # Contract with new DoD branch
    RECOMPETE_LOSS = "recompete_loss"       # Lost contract recompete
    COMPANY_INACTIVE = "company_inactive"   # No activity 12+ months
    SBIR_STALL = "sbir_stall"               # Phase I but no advancement


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Entity(Base):
    """
    Core entity table - represents companies, agencies, and investors.
    Uses entity resolution to deduplicate across data sources.
    """

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name_variants: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType), nullable=False, index=True
    )

    # Identifiers
    cage_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    duns_number: Mapped[Optional[str]] = mapped_column(String(13), index=True)
    ein: Mapped[Optional[str]] = mapped_column(String(10))

    # Metadata
    headquarters_location: Mapped[Optional[str]] = mapped_column(Text)
    website_url: Mapped[Optional[str]] = mapped_column(Text)
    founded_date: Mapped[Optional[date]] = mapped_column(Date)
    technology_tags: Mapped[Optional[dict]] = mapped_column(JSON, default=list)

    # Business classification (what they build/sell)
    core_business: Mapped[Optional[CoreBusiness]] = mapped_column(
        Enum(CoreBusiness), nullable=True, index=True
    )
    core_business_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    core_business_reasoning: Mapped[Optional[str]] = mapped_column(Text)

    # Policy alignment (NDS priority area scores)
    policy_alignment: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Soft delete for merged entities
    merged_into_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=True, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    funding_events: Mapped[list["FundingEvent"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    contracts: Mapped[list["Contract"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    signals: Mapped[list["Signal"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    outcomes: Mapped[list["OutcomeEvent"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    merged_into: Mapped[Optional["Entity"]] = relationship(
        "Entity", remote_side="Entity.id", foreign_keys=[merged_into_id]
    )

    __table_args__ = (
        Index("ix_entities_cage_duns", "cage_code", "duns_number"),
    )

    @property
    def is_merged(self) -> bool:
        """Check if this entity has been merged into another."""
        return self.merged_into_id is not None

    def __repr__(self) -> str:
        return f"<Entity(id={self.id}, name={self.canonical_name}, type={self.entity_type.value})>"


class FundingEvent(Base):
    """
    Funding events including VC rounds, SBIR awards, and acquisitions.
    """

    __tablename__ = "funding_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )

    event_type: Mapped[FundingEventType] = mapped_column(
        Enum(FundingEventType), nullable=False, index=True
    )
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    event_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    source: Mapped[Optional[str]] = mapped_column(Text)
    investors_awarders: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    round_stage: Mapped[Optional[str]] = mapped_column(String(50))
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)
    parent_event_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("funding_events.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    entity: Mapped["Entity"] = relationship(back_populates="funding_events")

    __table_args__ = (
        Index("ix_funding_entity_date", "entity_id", "event_date"),
    )

    def __repr__(self) -> str:
        return f"<FundingEvent(id={self.id}, type={self.event_type.value}, amount={self.amount})>"


class Contract(Base):
    """
    DoD and federal contracts from USAspending, FPDS, and other sources.
    """

    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )

    contract_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    contracting_agency: Mapped[Optional[str]] = mapped_column(Text, index=True)
    contract_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    award_date: Mapped[Optional[date]] = mapped_column(Date, index=True)

    # Period of performance
    period_of_performance_start: Mapped[Optional[date]] = mapped_column(Date)
    period_of_performance_end: Mapped[Optional[date]] = mapped_column(Date)

    # Classification codes
    naics_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    psc_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)

    place_of_performance: Mapped[Optional[str]] = mapped_column(Text)
    contract_type: Mapped[Optional[str]] = mapped_column(String(50))
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)

    # Procurement type: "standard" (FAR) or "ota" (Other Transaction Authority)
    procurement_type: Mapped[Optional[str]] = mapped_column(
        String(20), default="standard", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    entity: Mapped["Entity"] = relationship(back_populates="contracts")

    __table_args__ = (
        Index("ix_contracts_entity_agency", "entity_id", "contracting_agency"),
        Index("ix_contracts_naics_psc", "naics_code", "psc_code"),
    )

    def __repr__(self) -> str:
        return f"<Contract(id={self.id}, number={self.contract_number}, value={self.contract_value})>"


class Signal(Base):
    """
    Intelligence signals detected through analysis.
    Examples: rapid funding growth, new DoD engagement, technology pivot, etc.
    """

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )

    signal_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    detected_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[SignalStatus] = mapped_column(
        Enum(SignalStatus), default=SignalStatus.ACTIVE, index=True
    )

    # Freshness decay weight (1.0 = recent, 0.25 = stale) applied during scoring
    freshness_weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2), default=Decimal("1.00")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    entity: Mapped["Entity"] = relationship(back_populates="signals")

    __table_args__ = (
        Index("ix_signals_entity_type", "entity_id", "signal_type"),
        Index("ix_signals_status_date", "status", "detected_date"),
    )

    def __repr__(self) -> str:
        return f"<Signal(id={self.id}, type={self.signal_type}, confidence={self.confidence_score})>"


class OutcomeEvent(Base):
    """
    Tracked outcomes for signal validation.

    Records what actually happened to entities after signals were detected,
    enabling measurement of signal predictive accuracy.
    """

    __tablename__ = "outcome_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )

    # What happened
    outcome_type: Mapped[OutcomeType] = mapped_column(
        Enum(OutcomeType), nullable=False, index=True
    )
    outcome_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    outcome_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    # Link back to what predicted it
    related_signal_ids: Mapped[Optional[dict]] = mapped_column(JSON, default=list)

    # For measuring prediction accuracy
    months_since_signal: Mapped[Optional[int]] = mapped_column(Numeric(4, 0))

    # Deduplication key (source:unique_id)
    source_key: Mapped[Optional[str]] = mapped_column(Text, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    entity: Mapped["Entity"] = relationship(back_populates="outcomes")

    __table_args__ = (
        Index("ix_outcomes_entity_type", "entity_id", "outcome_type"),
        Index("ix_outcomes_date_type", "outcome_date", "outcome_type"),
    )

    def __repr__(self) -> str:
        return f"<OutcomeEvent(id={self.id}, type={self.outcome_type.value}, value={self.outcome_value})>"


class ProcurementType(PyEnum):
    """How the contract was procured."""
    STANDARD = "standard"  # FAR-based procurement (traditional contracts)
    OTA = "ota"            # Other Transaction Authority (10 USC 4022)


class MergeReason(PyEnum):
    """Reason for entity merge."""
    IDENTIFIER_MATCH = "identifier_match"
    NAME_SIMILARITY = "name_similarity"
    NAME_AND_LOCATION = "name_and_location"
    NAME_AND_NAICS = "name_and_naics"
    MANUAL = "manual"


class EntityMerge(Base):
    """
    Audit trail for entity merges.
    Tracks all merge decisions for transparency and potential rollback.
    """

    __tablename__ = "entity_merges"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    source_entity_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    target_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    merge_reason: Mapped[MergeReason] = mapped_column(
        Enum(MergeReason), nullable=False
    )
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    target_name: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationship to target entity
    target_entity: Mapped["Entity"] = relationship("Entity")

    def __repr__(self) -> str:
        return f"<EntityMerge(source={self.source_name} -> target={self.target_name}, reason={self.merge_reason.value})>"


class SbirEmbedding(Base):
    """
    Sentence-transformer embeddings for SBIR award titles/abstracts.
    Enables semantic similarity search across defense technology projects.
    """

    __tablename__ = "sbir_embeddings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    funding_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("funding_events.id"), nullable=False, unique=True, index=True
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    award_title: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    funding_event: Mapped["FundingEvent"] = relationship("FundingEvent")
    entity: Mapped["Entity"] = relationship("Entity")

    def __repr__(self) -> str:
        return f"<SbirEmbedding(id={self.id}, title={self.award_title[:50]})>"


class RelationshipType(PyEnum):
    """Types of edges in the knowledge graph."""
    FUNDED_BY_AGENCY = "funded_by_agency"           # SBIR awarded by agency
    CONTRACTED_BY_AGENCY = "contracted_by_agency"   # Production contract from agency
    INVESTED_IN_BY = "invested_in_by"               # VC/investor → company
    SIMILAR_TECHNOLOGY = "similar_technology"        # Embedding cosine similarity
    COMPETES_WITH = "competes_with"                 # Same tech cluster
    ALIGNED_TO_POLICY = "aligned_to_policy"         # Policy alignment score


class Relationship(Base):
    """
    Explicit edges in the knowledge graph.

    Stores typed, directed relationships between entities (or between entities
    and external concepts like agencies or technology areas). This table makes
    the implicit relationships in funding_events and contracts first-class,
    enabling graph traversal and path queries.
    """

    __tablename__ = "relationships"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    source_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    relationship_type: Mapped[RelationshipType] = mapped_column(
        Enum(RelationshipType), nullable=False, index=True
    )
    target_entity_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=True, index=True
    )
    # For non-entity targets (agencies, tech areas, policy signals)
    target_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)

    # Edge properties
    weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))  # Strength/value
    properties: Mapped[Optional[dict]] = mapped_column(JSON)  # Flexible metadata
    first_observed: Mapped[Optional[date]] = mapped_column(Date)
    last_observed: Mapped[Optional[date]] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    source_entity: Mapped["Entity"] = relationship(
        "Entity", foreign_keys=[source_entity_id]
    )
    target_entity: Mapped[Optional["Entity"]] = relationship(
        "Entity", foreign_keys=[target_entity_id]
    )

    __table_args__ = (
        Index("ix_rel_source_type", "source_entity_id", "relationship_type"),
        Index("ix_rel_target_type", "target_entity_id", "relationship_type"),
        Index("ix_rel_type_target_name", "relationship_type", "target_name"),
    )

    def __repr__(self) -> str:
        target = self.target_entity_id or self.target_name
        return f"<Relationship({self.source_entity_id} --{self.relationship_type.value}--> {target})>"


# ====================================================================
# Defensibility Layer Models
# ====================================================================


class EntityCorrection(Base):
    """
    Audit log for entity resolution corrections.

    Every merge, reject-merge, and manual override is recorded here,
    building an immutable decision trail that compounds over time.
    """

    __tablename__ = "entity_corrections"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    correction_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # merge, reject_merge, split, reclassify
    entity_a_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    entity_b_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=True
    )
    source_name_a: Mapped[Optional[str]] = mapped_column(Text)
    source_name_b: Mapped[Optional[str]] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # accepted, rejected
    confidence_before: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    confidence_after: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(
        String(50), nullable=False, default="system"
    )  # system, manual, algorithm
    decided_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    correction_source: Mapped[Optional[str]] = mapped_column(
        String(100)
    )  # entity_resolver, manual_csv, api
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)

    # Relationships
    entity_a: Mapped["Entity"] = relationship(
        "Entity", foreign_keys=[entity_a_id]
    )
    entity_b: Mapped[Optional["Entity"]] = relationship(
        "Entity", foreign_keys=[entity_b_id]
    )

    def __repr__(self) -> str:
        return f"<EntityCorrection(type={self.correction_type}, a={self.source_name_a}, decision={self.decision})>"


class ReportDelivery(Base):
    """
    Tracks every report/brief delivered, capturing a point-in-time snapshot
    of what intelligence the recipient saw.
    """

    __tablename__ = "report_deliveries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    report_slug: Mapped[str] = mapped_column(Text, nullable=False)
    recipient: Mapped[Optional[str]] = mapped_column(String(100))
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    snapshot_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entity_snapshots.id"), nullable=True
    )

    # Feedback fields
    feedback_rating: Mapped[Optional[str]] = mapped_column(String(50))
    feedback_notes: Mapped[Optional[str]] = mapped_column(Text)
    feedback_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Outcome tracking
    outcome_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean)
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    entity: Mapped["Entity"] = relationship("Entity")

    __table_args__ = (
        Index("ix_deliveries_entity_date", "entity_id", "delivered_at"),
    )

    def __repr__(self) -> str:
        return f"<ReportDelivery(type={self.report_type}, slug={self.report_slug})>"


class SignalValidation(Base):
    """
    Records whether a detected signal was confirmed by a real-world outcome.

    Over time, this builds a hit-rate ledger that proves which signals
    are predictive and which are noise.
    """

    __tablename__ = "signal_validations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    signal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("signals.id"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    validation_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # confirmed, false_positive, pending
    validation_source: Mapped[Optional[str]] = mapped_column(String(100))
    expected_outcome: Mapped[Optional[str]] = mapped_column(Text)
    actual_outcome: Mapped[Optional[str]] = mapped_column(Text)
    lead_time_months: Mapped[Optional[int]] = mapped_column(Numeric(4, 0))
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    validated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    signal: Mapped["Signal"] = relationship("Signal")
    entity: Mapped["Entity"] = relationship("Entity")

    __table_args__ = (
        Index("ix_validations_signal_type", "signal_type", "validation_type"),
    )

    def __repr__(self) -> str:
        return f"<SignalValidation(signal={self.signal_id}, type={self.validation_type})>"


class EntitySnapshot(Base):
    """
    Point-in-time capture of an entity's composite state.

    Running daily/weekly builds a time series showing how each entity's
    score, signals, and funding evolve — enabling trajectory analysis.
    """

    __tablename__ = "entity_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    core_business: Mapped[Optional[str]] = mapped_column(String(50))
    composite_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    freshness_adjusted_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    policy_tailwind_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    sbir_count: Mapped[Optional[int]] = mapped_column(Numeric(6, 0))
    sbir_total_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    contract_count: Mapped[Optional[int]] = mapped_column(Numeric(6, 0))
    contract_total_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    regd_count: Mapped[Optional[int]] = mapped_column(Numeric(6, 0))
    regd_total_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    active_signals: Mapped[Optional[dict]] = mapped_column(JSON)
    lifecycle_stage: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    entity: Mapped["Entity"] = relationship("Entity")

    __table_args__ = (
        UniqueConstraint("entity_id", "snapshot_date", name="uq_entity_snapshot_date"),
        Index("ix_snapshots_entity_date", "entity_id", "snapshot_date"),
    )

    def __repr__(self) -> str:
        return f"<EntitySnapshot(entity={self.entity_id}, date={self.snapshot_date})>"


class ScraperRun(Base):
    """
    Audit log for scraper executions.

    Tracks every scrape: what ran, how many records were fetched/matched,
    and any errors — making the data pipeline observable and debuggable.
    """

    __tablename__ = "scraper_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    source_name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running"
    )  # running, success, failed, partial
    records_fetched: Mapped[Optional[int]] = mapped_column(Numeric(8, 0), default=0)
    records_new: Mapped[Optional[int]] = mapped_column(Numeric(8, 0), default=0)
    records_updated: Mapped[Optional[int]] = mapped_column(Numeric(8, 0), default=0)
    entities_created: Mapped[Optional[int]] = mapped_column(Numeric(8, 0), default=0)
    entities_matched: Mapped[Optional[int]] = mapped_column(Numeric(8, 0), default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    checkpoint: Mapped[Optional[dict]] = mapped_column(JSON)
    config: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_scraper_runs_source_started", "source_name", "started_at"),
    )

    def __repr__(self) -> str:
        return f"<ScraperRun(source={self.source_name}, status={self.status})>"


class EnrichmentFinding(Base):
    """
    Staging queue for web-enriched data.

    Findings from web search are staged here for review before ingestion
    into contracts, funding_events, or relationships tables.
    """

    __tablename__ = "enrichment_findings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    finding_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # contract, funding_round, partnership, ota_award
    finding_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[str]] = mapped_column(String(20))  # high, medium, low
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, approved, rejected, ingested
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(50))  # auto, manual
    ingested_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ingested_record_id: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    entity: Mapped["Entity"] = relationship("Entity")

    __table_args__ = (
        Index("ix_enrichment_entity_status", "entity_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<EnrichmentFinding(type={self.finding_type}, status={self.status})>"
