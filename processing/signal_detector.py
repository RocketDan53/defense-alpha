"""
Signal Detection Engine for Defense Alpha Intelligence Platform.

Detects actionable intelligence signals from entity activity patterns:
- SBIR phase transitions (Phase I -> II -> III)
- First DoD contract for startups
- Rapid contract growth
- High-priority technology focus
- Multi-agency interest
- Outsized awards relative to company history
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from processing.models import (
    Entity, EntityType, Contract, FundingEvent, FundingEventType,
    Signal, SignalStatus
)


# Signal type constants
SIGNAL_SBIR_PHASE_2 = "sbir_phase_2_transition"
SIGNAL_SBIR_PHASE_3 = "sbir_phase_3_transition"
SIGNAL_FIRST_DOD_CONTRACT = "first_dod_contract"
SIGNAL_RAPID_GROWTH = "rapid_contract_growth"
SIGNAL_HIGH_PRIORITY_TECH = "high_priority_technology"
SIGNAL_MULTI_AGENCY = "multi_agency_interest"
SIGNAL_OUTSIZED_AWARD = "outsized_award"

# High-priority technology areas for defense
HIGH_PRIORITY_TECH = {
    "ai_ml", "autonomy", "quantum", "hypersonics", "cyber",
    "space", "directed_energy", "c4isr", "ew"
}

# Confidence score thresholds
HIGH_CONFIDENCE = Decimal("0.90")
MEDIUM_CONFIDENCE = Decimal("0.75")
LOW_CONFIDENCE = Decimal("0.60")


class SignalDetector:
    """Detects intelligence signals from entity data."""

    def __init__(self, db: Session):
        self.db = db
        self.signals_created = 0
        self.signals_updated = 0

    def detect_all_signals(self, lookback_days: int = 365) -> dict:
        """
        Run all signal detection algorithms.

        Args:
            lookback_days: How far back to look for new activity

        Returns:
            Summary of signals detected
        """
        cutoff_date = date.today() - timedelta(days=lookback_days)

        results = {
            "sbir_transitions": self.detect_sbir_transitions(cutoff_date),
            "first_contracts": self.detect_first_dod_contracts(cutoff_date),
            "rapid_growth": self.detect_rapid_growth(cutoff_date),
            "high_priority_tech": self.detect_high_priority_tech(),
            "multi_agency": self.detect_multi_agency_interest(cutoff_date),
            "outsized_awards": self.detect_outsized_awards(cutoff_date),
        }

        self.db.commit()

        return {
            "signals_created": self.signals_created,
            "signals_updated": self.signals_updated,
            "details": results
        }

    def _create_or_update_signal(
        self,
        entity_id: str,
        signal_type: str,
        confidence: Decimal,
        detected_date: date,
        evidence: dict
    ) -> Signal:
        """Create a new signal or update existing one."""
        # Check for existing active signal of same type
        existing = self.db.query(Signal).filter(
            Signal.entity_id == entity_id,
            Signal.signal_type == signal_type,
            Signal.status == SignalStatus.ACTIVE
        ).first()

        if existing:
            # Update evidence if new info
            if existing.evidence != evidence:
                existing.evidence = evidence
                existing.confidence_score = confidence
                self.signals_updated += 1
            return existing

        # Create new signal
        signal = Signal(
            entity_id=entity_id,
            signal_type=signal_type,
            confidence_score=confidence,
            detected_date=detected_date,
            evidence=evidence,
            status=SignalStatus.ACTIVE
        )
        self.db.add(signal)
        self.signals_created += 1
        return signal

    def detect_sbir_transitions(self, cutoff_date: date) -> dict:
        """
        Detect SBIR phase transitions (I->II, II->III).
        These indicate technology maturation and commercialization potential.
        """
        phase_2_count = 0
        phase_3_count = 0

        # Get all startups with SBIR awards
        sbir_entities = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None)
        ).all()

        for entity in sbir_entities:
            awards = self.db.query(FundingEvent).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3
                ])
            ).order_by(FundingEvent.event_date).all()

            has_phase_1 = any(a.event_type == FundingEventType.SBIR_PHASE_1 for a in awards)
            has_phase_2 = any(a.event_type == FundingEventType.SBIR_PHASE_2 for a in awards)
            has_phase_3 = any(a.event_type == FundingEventType.SBIR_PHASE_3 for a in awards)

            # Check for Phase II transition
            phase_2_awards = [a for a in awards if a.event_type == FundingEventType.SBIR_PHASE_2]
            recent_phase_2 = [a for a in phase_2_awards if a.event_date and a.event_date >= cutoff_date]

            if has_phase_1 and recent_phase_2:
                latest = max(recent_phase_2, key=lambda x: x.event_date or date.min)
                total_phase_2_value = sum(float(a.amount or 0) for a in phase_2_awards)

                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_SBIR_PHASE_2,
                    confidence=HIGH_CONFIDENCE,
                    detected_date=latest.event_date,
                    evidence={
                        "phase_1_count": len([a for a in awards if a.event_type == FundingEventType.SBIR_PHASE_1]),
                        "phase_2_count": len(phase_2_awards),
                        "total_phase_2_value": total_phase_2_value,
                        "latest_award_date": str(latest.event_date),
                        "entity_name": entity.canonical_name
                    }
                )
                phase_2_count += 1

            # Check for Phase III transition (high value - indicates production)
            phase_3_awards = [a for a in awards if a.event_type == FundingEventType.SBIR_PHASE_3]
            recent_phase_3 = [a for a in phase_3_awards if a.event_date and a.event_date >= cutoff_date]

            if has_phase_2 and recent_phase_3:
                latest = max(recent_phase_3, key=lambda x: x.event_date or date.min)
                total_phase_3_value = sum(float(a.amount or 0) for a in phase_3_awards)

                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_SBIR_PHASE_3,
                    confidence=HIGH_CONFIDENCE,
                    detected_date=latest.event_date,
                    evidence={
                        "phase_2_count": len(phase_2_awards),
                        "phase_3_count": len(phase_3_awards),
                        "total_phase_3_value": total_phase_3_value,
                        "latest_award_date": str(latest.event_date),
                        "entity_name": entity.canonical_name
                    }
                )
                phase_3_count += 1

        return {"phase_2_transitions": phase_2_count, "phase_3_transitions": phase_3_count}

    def detect_first_dod_contracts(self, cutoff_date: date) -> dict:
        """
        Detect startups receiving their first DoD contract.
        Indicates new entrant to defense market.
        """
        count = 0
        min_value = 100000  # $100K minimum to be significant

        # Get startups with recent contracts
        startups = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None)
        ).all()

        for entity in startups:
            contracts = self.db.query(Contract).filter(
                Contract.entity_id == entity.id,
                Contract.contract_value >= min_value
            ).order_by(Contract.award_date).all()

            if not contracts:
                continue

            # Check if first contract is recent
            first_contract = contracts[0]
            if first_contract.award_date and first_contract.award_date >= cutoff_date:
                # Verify they don't have older SBIR awards (which would make this not "first")
                older_sbir = self.db.query(FundingEvent).filter(
                    FundingEvent.entity_id == entity.id,
                    FundingEvent.event_type.in_([
                        FundingEventType.SBIR_PHASE_1,
                        FundingEventType.SBIR_PHASE_2,
                        FundingEventType.SBIR_PHASE_3
                    ]),
                    FundingEvent.event_date < cutoff_date
                ).first()

                if not older_sbir:
                    self._create_or_update_signal(
                        entity_id=entity.id,
                        signal_type=SIGNAL_FIRST_DOD_CONTRACT,
                        confidence=MEDIUM_CONFIDENCE,
                        detected_date=first_contract.award_date,
                        evidence={
                            "contract_number": first_contract.contract_number,
                            "contract_value": float(first_contract.contract_value or 0),
                            "contracting_agency": first_contract.contracting_agency,
                            "award_date": str(first_contract.award_date),
                            "entity_name": entity.canonical_name
                        }
                    )
                    count += 1

        return {"first_dod_contracts": count}

    def detect_rapid_growth(self, cutoff_date: date) -> dict:
        """
        Detect entities with rapid contract value growth.
        Compares recent period to historical baseline.
        """
        count = 0
        growth_threshold = 2.0  # 2x growth is significant

        # Get all active entities with contracts
        entities = self.db.query(Entity).filter(
            Entity.merged_into_id.is_(None)
        ).all()

        for entity in entities:
            # Get historical contracts (before cutoff)
            historical = self.db.query(func.sum(Contract.contract_value)).filter(
                Contract.entity_id == entity.id,
                Contract.award_date < cutoff_date
            ).scalar() or Decimal(0)

            # Get recent contracts (after cutoff)
            recent = self.db.query(func.sum(Contract.contract_value)).filter(
                Contract.entity_id == entity.id,
                Contract.award_date >= cutoff_date
            ).scalar() or Decimal(0)

            # Need both historical and recent to compare
            if historical > 100000 and recent > 100000:
                # Normalize by time period
                days_historical = (cutoff_date - date(2020, 1, 1)).days
                days_recent = (date.today() - cutoff_date).days

                if days_historical > 0 and days_recent > 0:
                    historical_rate = float(historical) / days_historical
                    recent_rate = float(recent) / days_recent

                    if historical_rate > 0:
                        growth_rate = recent_rate / historical_rate

                        if growth_rate >= growth_threshold:
                            confidence = min(Decimal("0.95"), Decimal(str(0.5 + (growth_rate - 2) * 0.1)))

                            self._create_or_update_signal(
                                entity_id=entity.id,
                                signal_type=SIGNAL_RAPID_GROWTH,
                                confidence=confidence,
                                detected_date=date.today(),
                                evidence={
                                    "historical_total": float(historical),
                                    "recent_total": float(recent),
                                    "growth_rate": round(growth_rate, 2),
                                    "historical_daily_rate": round(historical_rate, 2),
                                    "recent_daily_rate": round(recent_rate, 2),
                                    "entity_name": entity.canonical_name
                                }
                            )
                            count += 1

        return {"rapid_growth_signals": count}

    def detect_high_priority_tech(self) -> dict:
        """
        Detect entities focused on high-priority defense technology areas.
        Based on technology tags.
        """
        count = 0

        entities = self.db.query(Entity).filter(
            Entity.merged_into_id.is_(None),
            Entity.technology_tags.isnot(None)
        ).all()

        for entity in entities:
            tags = entity.technology_tags or []
            priority_tags = [t for t in tags if t in HIGH_PRIORITY_TECH]

            if priority_tags:
                # More priority tags = higher confidence
                confidence = min(
                    HIGH_CONFIDENCE,
                    Decimal(str(0.6 + len(priority_tags) * 0.1))
                )

                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_HIGH_PRIORITY_TECH,
                    confidence=confidence,
                    detected_date=date.today(),
                    evidence={
                        "priority_technologies": priority_tags,
                        "all_technologies": tags,
                        "priority_count": len(priority_tags),
                        "entity_name": entity.canonical_name
                    }
                )
                count += 1

        return {"high_priority_tech_signals": count}

    def detect_multi_agency_interest(self, cutoff_date: date) -> dict:
        """
        Detect startups receiving contracts from multiple DoD agencies.
        Indicates broad relevance across defense.
        """
        count = 0
        min_agencies = 2

        startups = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None)
        ).all()

        for entity in startups:
            # Get distinct agencies for recent contracts
            agencies = self.db.query(Contract.contracting_agency).filter(
                Contract.entity_id == entity.id,
                Contract.award_date >= cutoff_date,
                Contract.contracting_agency.isnot(None)
            ).distinct().all()

            agency_list = [a[0] for a in agencies if a[0]]

            # Normalize agency names (extract main agency)
            normalized = set()
            for agency in agency_list:
                agency_upper = agency.upper()
                if "ARMY" in agency_upper:
                    normalized.add("Army")
                elif "NAVY" in agency_upper or "NAVAL" in agency_upper:
                    normalized.add("Navy")
                elif "AIR FORCE" in agency_upper:
                    normalized.add("Air Force")
                elif "SPACE FORCE" in agency_upper:
                    normalized.add("Space Force")
                elif "DARPA" in agency_upper:
                    normalized.add("DARPA")
                elif "DLA" in agency_upper:
                    normalized.add("DLA")
                elif "DISA" in agency_upper:
                    normalized.add("DISA")
                elif "MDA" in agency_upper or "MISSILE DEFENSE" in agency_upper:
                    normalized.add("MDA")
                else:
                    normalized.add(agency[:50])  # Keep original truncated

            if len(normalized) >= min_agencies:
                confidence = min(
                    HIGH_CONFIDENCE,
                    Decimal(str(0.6 + (len(normalized) - 2) * 0.1))
                )

                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_MULTI_AGENCY,
                    confidence=confidence,
                    detected_date=date.today(),
                    evidence={
                        "agencies": list(normalized),
                        "agency_count": len(normalized),
                        "entity_name": entity.canonical_name
                    }
                )
                count += 1

        return {"multi_agency_signals": count}

    def detect_outsized_awards(self, cutoff_date: date) -> dict:
        """
        Detect awards that are unusually large relative to entity's history.
        May indicate breakout success or strategic importance.
        """
        count = 0
        size_multiplier = 3.0  # Award must be 3x their average

        startups = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None)
        ).all()

        for entity in startups:
            # Get all contracts
            all_contracts = self.db.query(Contract).filter(
                Contract.entity_id == entity.id,
                Contract.contract_value.isnot(None),
                Contract.contract_value > 0
            ).all()

            if len(all_contracts) < 2:
                continue

            # Calculate average
            total = sum(float(c.contract_value) for c in all_contracts)
            avg = total / len(all_contracts)

            if avg < 50000:  # Skip if average is too small
                continue

            # Check for outsized recent awards
            for contract in all_contracts:
                if (contract.award_date and
                    contract.award_date >= cutoff_date and
                    float(contract.contract_value) >= avg * size_multiplier):

                    ratio = float(contract.contract_value) / avg
                    confidence = min(HIGH_CONFIDENCE, Decimal(str(0.6 + (ratio - 3) * 0.05)))

                    self._create_or_update_signal(
                        entity_id=entity.id,
                        signal_type=SIGNAL_OUTSIZED_AWARD,
                        confidence=confidence,
                        detected_date=contract.award_date,
                        evidence={
                            "contract_number": contract.contract_number,
                            "contract_value": float(contract.contract_value),
                            "average_contract_value": round(avg, 2),
                            "size_ratio": round(ratio, 2),
                            "contracting_agency": contract.contracting_agency,
                            "entity_name": entity.canonical_name
                        }
                    )
                    count += 1
                    break  # One signal per entity

        return {"outsized_award_signals": count}


def get_signal_summary(db: Session) -> dict:
    """Get summary of all active signals in database."""
    total = db.query(func.count(Signal.id)).filter(
        Signal.status == SignalStatus.ACTIVE
    ).scalar() or 0

    by_type = db.query(
        Signal.signal_type,
        func.count(Signal.id)
    ).filter(
        Signal.status == SignalStatus.ACTIVE
    ).group_by(Signal.signal_type).all()

    return {
        "total_active_signals": total,
        "by_type": {t: c for t, c in by_type}
    }


def get_top_signals(db: Session, limit: int = 20) -> list[dict]:
    """Get top signals by confidence score."""
    signals = db.query(Signal).filter(
        Signal.status == SignalStatus.ACTIVE
    ).order_by(Signal.confidence_score.desc()).limit(limit).all()

    results = []
    for s in signals:
        entity = db.query(Entity).filter(Entity.id == s.entity_id).first()
        results.append({
            "entity_name": entity.canonical_name if entity else "Unknown",
            "signal_type": s.signal_type,
            "confidence": float(s.confidence_score) if s.confidence_score else 0,
            "detected_date": str(s.detected_date) if s.detected_date else None,
            "evidence": s.evidence
        })

    return results
