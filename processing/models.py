"""
Defense Alpha Intelligence Engine - Database Models

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
    INVESTOR = "investor"
    AGENCY = "agency"


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


class SignalStatus(PyEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    VALIDATED = "validated"
    FALSE_POSITIVE = "false_positive"


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
