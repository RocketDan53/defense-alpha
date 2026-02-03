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


class FundingEventType(PyEnum):
    VC_ROUND = "vc_round"
    SBIR_PHASE_1 = "sbir_phase_1"
    SBIR_PHASE_2 = "sbir_phase_2"
    SBIR_PHASE_3 = "sbir_phase_3"
    CONTRACT = "contract"
    ACQUISITION = "acquisition"


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
    founded_date: Mapped[Optional[date]] = mapped_column(Date)
    technology_tags: Mapped[Optional[dict]] = mapped_column(JSON, default=list)

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

    __table_args__ = (
        Index("ix_entities_cage_duns", "cage_code", "duns_number"),
    )

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
