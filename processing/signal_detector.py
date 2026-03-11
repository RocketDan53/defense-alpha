"""
Signal Detection Engine for Aperture Signals Intelligence Platform.

Detects actionable intelligence signals from entity activity patterns:
- SBIR phase transitions (Phase I -> II -> III)
- First DoD contract for startups
- Rapid contract growth
- High-priority technology focus
- Multi-agency interest
- Outsized awards relative to company history
"""

import json
import logging
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import Session

from processing.models import (
    Entity, EntityType, Contract, FundingEvent, FundingEventType,
    Signal, SignalStatus, Relationship, RelationshipType,
    EnrichmentFinding, SbirEmbedding,
)

logger = logging.getLogger(__name__)


# Signal type constants
SIGNAL_SBIR_PHASE_2 = "sbir_phase_2_transition"
SIGNAL_SBIR_PHASE_3 = "sbir_phase_3_transition"
SIGNAL_FIRST_DOD_CONTRACT = "first_dod_contract"
SIGNAL_RAPID_GROWTH = "rapid_contract_growth"
SIGNAL_HIGH_PRIORITY_TECH = "high_priority_technology"
SIGNAL_MULTI_AGENCY = "multi_agency_interest"
SIGNAL_OUTSIZED_AWARD = "outsized_award"
SIGNAL_SBIR_TO_CONTRACT = "sbir_to_contract_transition"
SIGNAL_SBIR_TO_VC = "sbir_to_vc_raise"
SIGNAL_SBIR_VALIDATED_RAISE = "sbir_validated_raise"

# Timing-based signals
SIGNAL_SBIR_GRADUATION_SPEED = "sbir_graduation_speed"
SIGNAL_TIME_TO_CONTRACT = "time_to_contract"
SIGNAL_FUNDING_VELOCITY = "funding_velocity"

# Negative signals (risk indicators)
SIGNAL_SBIR_STALLED = "sbir_stalled"
SIGNAL_CUSTOMER_CONCENTRATION = "customer_concentration"
SIGNAL_GONE_STALE = "gone_stale"

# MEIA/KOP/JAR signal types (acquisition reform)
SIGNAL_KOP_ALIGNMENT = "kop_alignment"
SIGNAL_MEIA_EXPERIMENTATION = "meia_experimentation"
SIGNAL_JAR_FUNDING = "jar_funding"
SIGNAL_PAE_PORTFOLIO = "pae_portfolio_member"
SIGNAL_COMMERCIAL_PATHWAY = "commercial_pathway_fit"
SIGNAL_SBIR_LAPSE_RISK = "sbir_lapse_risk"

# Contract vehicle progression signals
SIGNAL_SOLE_SOURCE_AWARD = "sole_source_award"
SIGNAL_OTA_BRIDGE_AWARD = "ota_bridge_award"
SIGNAL_MULTI_VEHICLE_PRESENCE = "multi_vehicle_presence"
SIGNAL_CONTRACT_VALUE_STEP_CHANGE = "contract_value_step_change"

# SBIR reauthorization signals (March 2026)
SIGNAL_STRATEGIC_BREAKTHROUGH_AWARD = "strategic_breakthrough_award"

# High-priority technology areas for defense
HIGH_PRIORITY_TECH = {
    "ai_ml", "autonomy", "quantum", "hypersonics", "cyber",
    "space", "directed_energy", "c4isr", "ew"
}

# Confidence score thresholds
HIGH_CONFIDENCE = Decimal("0.90")
MEDIUM_CONFIDENCE = Decimal("0.75")
LOW_CONFIDENCE = Decimal("0.60")

# Stop words for SBIR title keyword extraction
STOP_WORDS = {'the', 'a', 'an', 'and', 'or', 'for', 'of', 'to', 'in', 'on', 'with', 'by',
              'from', 'at', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has',
              'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
              'shall', 'can', 'need', 'dare', 'ought', 'used', 'this', 'that', 'these', 'those',
              'phase', 'ii', 'iii', 'i', 'sbir', 'sttr', 'development', 'system', 'systems',
              'technology', 'advanced', 'based', 'using', 'new', 'novel', 'improved'}

# Abbreviation and synonym mappings for defense/tech domain
# Each key maps to a set of related terms for bidirectional expansion
TERM_GROUPS = [
    {"uas", "uav", "unmanned aerial", "drone", "rpas", "remotely piloted"},
    {"counter-uas", "c-uas", "counter-drone", "anti-drone", "drone defense", "cuas"},
    {"ew", "electronic warfare", "electronic countermeasures", "ecm", "electronic attack"},
    {"directed energy", "directed_energy", "laser weapon", "high-energy laser", "hel", "dew"},
    {"satcom", "satellite communications", "satellite comms"},
    {"pnt", "positioning navigation timing", "alternative pnt", "gps-denied navigation"},
    {"isr", "intelligence surveillance reconnaissance"},
    {"jadc2", "joint all-domain", "joint all domain command"},
    {"sda", "space domain awareness", "space situational awareness", "ssa"},
    {"c2", "command control", "command and control", "battle management"},
    {"ai", "artificial intelligence", "machine learning", "ml", "ai_ml"},
    {"sigint", "signals intelligence"},
    {"lidar", "light detection ranging", "laser radar"},
    {"mesh networking", "mesh network", "tactical network", "mobile ad-hoc"},
    {"anti-jam", "jam-resistant", "anti-jamming", "jam resistant"},
    {"autonomous navigation", "autonomous nav", "gps-denied", "gps denied"},
    {"swarm", "swarm defeat", "counter-swarm", "massed attack"},
    {"undersea warfare", "undersea", "submarine", "asw", "anti-submarine"},
    {"mine warfare", "mine countermeasures", "mcm", "demining"},
    {"target recognition", "target identification", "automatic target", "atr"},
    {"kill chain", "kill-chain", "sensor-to-shooter", "sensor to shooter"},
    {"additive manufacturing", "3d printing", "3-d printing", "am manufacturing"},
    {"microelectronics", "microchip", "semiconductor", "trusted foundry"},
    {"munitions", "munitions production", "ammunition", "ordnance"},
    {"hypersonic", "hypersonics", "hypersonic weapon", "scramjet"},
    {"cyber", "cybersecurity", "cyber security", "cyber warfare"},
    {"quantum", "quantum computing", "quantum sensing", "quantum communications"},
    {"counter-space", "counterspace", "space protection", "satellite protection"},
    {"autonomous resupply", "autonomous logistics", "unmanned logistics", "unmanned resupply"},
    {"fire coordination", "fire control", "fires coordination", "coordinated fires"},
]

# Build bidirectional lookup: any term → all terms in its group
ABBREV_MAP = {}
for group in TERM_GROUPS:
    for term in group:
        ABBREV_MAP[term] = group - {term}


def _expand_with_abbreviations(terms: set) -> set:
    """Expand a set of terms with synonym/abbreviation mappings."""
    expanded = set(terms)
    for term in terms:
        if term in ABBREV_MAP:
            for synonym in ABBREV_MAP[term]:
                expanded.add(synonym)
                # Also add individual words from multi-word synonyms
                expanded.update(synonym.split())
    return expanded


def _extract_tech_keywords(title: str) -> set:
    """Extract meaningful tech keywords from an SBIR award title."""
    words = re.findall(r'[a-z][a-z-]+', title.lower())
    keywords = {w for w in words if w not in STOP_WORDS and len(w) > 2}
    # Also extract uppercase abbreviations (UAS, EW, ISR, etc.) from original title
    abbrevs = re.findall(r'\b[A-Z][A-Z0-9-]{1,8}\b', title)
    keywords.update(a.lower() for a in abbrevs)
    # Extract meaningful bigrams for multi-word concept matching
    # e.g., "Counter Unmanned Aerial System" → "counter unmanned", "unmanned aerial"
    filtered = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    for i in range(len(filtered) - 1):
        keywords.add(f"{filtered[i]} {filtered[i+1]}")
    return keywords


def _normalize_tag(tag: str) -> set:
    """Normalize a technology tag into searchable terms.

    'directed_energy' → {'directed_energy', 'directed energy', 'directed', 'energy'}
    """
    tag_lower = tag.lower().strip()
    terms = {tag_lower}
    # Split underscored tags into space-separated form and individual words
    if '_' in tag_lower:
        spaced = tag_lower.replace('_', ' ')
        terms.add(spaced)
        terms.update(spaced.split())
    # Split hyphenated tags into individual words too
    if '-' in tag_lower:
        terms.update(tag_lower.replace('-', ' ').split())
    return terms


def _match_indicators(entity_profile: set, indicators: list) -> list:
    """Match KOP indicators against entity tech profile.

    Supports multi-word indicators via:
    1. Substring containment on joined profile text
    2. All meaningful words of indicator present individually (split on spaces AND hyphens)
    3. Abbreviation expansion (both directions)
    """
    # Expand entity profile with abbreviation mappings
    expanded_profile = _expand_with_abbreviations(entity_profile)
    profile_text = ' '.join(expanded_profile)

    matches = []
    for indicator in indicators:
        indicator_lower = indicator.lower()

        # Expand indicator with abbreviations/synonyms too
        indicator_expanded = {indicator_lower}
        if indicator_lower in ABBREV_MAP:
            indicator_expanded.update(ABBREV_MAP[indicator_lower])

        matched = False
        for ind_form in indicator_expanded:
            # Check substring containment
            if ind_form in profile_text:
                matched = True
                break
            # Check if all meaningful words appear individually
            # Split on both spaces and hyphens for compound terms like "counter-UAS"
            ind_words = {w for w in re.split(r'[\s-]+', ind_form) if len(w) > 1}
            if ind_words and ind_words.issubset(expanded_profile):
                matched = True
                break

        if matched:
            matches.append(indicator)
    return matches


def _dedup_regd_filings(filings):
    """Remove duplicate Reg D filings (same entity, same date, same amount).

    SEC EDGAR often contains amended filings that duplicate the original.
    When two filings share entity_id + event_date + amount, keep one.
    Returns deduplicated list.
    """
    seen = set()
    deduped = []
    for f in filings:
        key = (str(f.entity_id), str(f.event_date), str(f.amount))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped


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
            "sbir_to_contract": self.detect_sbir_to_contract(),
            "sbir_to_vc": self.detect_sbir_to_vc_raise(),
            "sbir_validated_raise": self.detect_sbir_validated_raise(),
            "sbir_stalled": self.detect_sbir_stalled(),
            "customer_concentration": self.detect_customer_concentration(),
            "sbir_graduation_speed": self.detect_sbir_graduation_speed(),
            "time_to_contract": self.detect_time_to_contract(),
            "funding_velocity": self.detect_funding_velocity(),
            "gone_stale": self.detect_gone_stale(),
            # MEIA/KOP/JAR detectors
            "kop_alignment": self.detect_kop_alignment(),
            "commercial_pathway": self.detect_commercial_pathway(),
            "sbir_lapse_risk": self.detect_sbir_lapse_risk(),
            "meia_experimentation": self.detect_meia_experimentation(),
            "jar_funding": self.detect_jar_funding(),
            "pae_portfolio": self.detect_pae_portfolio(),
            # Contract vehicle progression
            "sole_source_award": self.detect_sole_source_award(),
            "ota_bridge_award": self.detect_ota_bridge_award(),
            "multi_vehicle_presence": self.detect_multi_vehicle_presence(),
            "contract_value_step_change": self.detect_contract_value_step_change(),
            # SBIR reauthorization (stub — Q4 FY2026)
            "strategic_breakthrough_award": self.detect_strategic_breakthrough_awards(),
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
            # No recency filter: a Phase I→II transition signals company capability
            # regardless of when it occurred. detected_date captures timing for consumers.
            phase_2_awards = [a for a in awards if a.event_type == FundingEventType.SBIR_PHASE_2]

            if has_phase_1 and phase_2_awards:
                latest = max(phase_2_awards, key=lambda x: x.event_date or date.min)
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
            # No recency filter: same rationale as Phase II above.
            phase_3_awards = [a for a in awards if a.event_type == FundingEventType.SBIR_PHASE_3]

            if has_phase_2 and phase_3_awards:
                latest = max(phase_3_awards, key=lambda x: x.event_date or date.min)
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
            # Get distinct agencies across all contracts (no recency filter —
            # multi-agency interest is a structural signal about the company)
            agencies = self.db.query(Contract.contracting_agency).filter(
                Contract.entity_id == entity.id,
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

            # Check for outsized awards (no recency filter — an outsized award
            # signals breakout success regardless of when it occurred)
            for contract in all_contracts:
                if float(contract.contract_value) >= avg * size_multiplier:

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

    def detect_sbir_to_contract(self) -> dict:
        """
        Detect entities that transitioned from SBIR R&D to real procurement contracts.
        Indicates successful commercialization of SBIR-funded technology.
        """
        count = 0

        # Get startups with SBIR awards
        sbir_entity_ids = (
            self.db.query(FundingEvent.entity_id)
            .filter(
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ])
            )
            .distinct()
        )

        entities = self.db.query(Entity).filter(
            Entity.id.in_(sbir_entity_ids.scalar_subquery()),
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            contracts = self.db.query(Contract).filter(
                Contract.entity_id == entity.id,
                Contract.contract_value.isnot(None),
                Contract.contract_value > 0,
            ).order_by(Contract.award_date).all()

            if not contracts:
                continue

            # Get earliest SBIR award date for this entity
            earliest_sbir = self.db.query(func.min(FundingEvent.event_date)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
            ).scalar()

            # Contracts that came after SBIR activity
            if earliest_sbir:
                post_sbir = [c for c in contracts if c.award_date and c.award_date > earliest_sbir]
            else:
                # No dates on SBIR awards — count all contracts
                post_sbir = contracts

            if not post_sbir:
                continue

            total_contract_value = sum(float(c.contract_value) for c in post_sbir)
            latest_contract = max(post_sbir, key=lambda c: c.award_date or date.min)

            # Higher confidence if contract value is substantial relative to SBIR
            total_sbir_value = self.db.query(func.sum(FundingEvent.amount)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
            ).scalar() or Decimal(0)

            ratio = float(total_contract_value) / max(float(total_sbir_value), 1)
            confidence = min(HIGH_CONFIDENCE, Decimal(str(0.6 + min(ratio, 3) * 0.1)))

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_SBIR_TO_CONTRACT,
                confidence=confidence,
                detected_date=latest_contract.award_date or date.today(),
                evidence={
                    "sbir_award_count": self.db.query(FundingEvent).filter(
                        FundingEvent.entity_id == entity.id,
                        FundingEvent.event_type.in_([
                            FundingEventType.SBIR_PHASE_1,
                            FundingEventType.SBIR_PHASE_2,
                            FundingEventType.SBIR_PHASE_3,
                        ]),
                    ).count(),
                    "total_sbir_value": float(total_sbir_value),
                    "post_sbir_contract_count": len(post_sbir),
                    "total_contract_value": total_contract_value,
                    "contract_to_sbir_ratio": round(ratio, 2),
                    "earliest_sbir_date": str(earliest_sbir),
                    "latest_contract_date": str(latest_contract.award_date),
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"sbir_to_contract_signals": count}

    def detect_sbir_to_vc_raise(self) -> dict:
        """
        Detect entities with both SBIR awards and Reg D (private capital) filings.
        Signals that smart money is validating government-funded R&D.
        Higher confidence when the VC raise came after SBIR awards.
        """
        count = 0

        # Find entities that have both SBIR awards and Reg D filings
        sbir_entities = (
            self.db.query(FundingEvent.entity_id)
            .filter(
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ])
            )
            .distinct()
        )

        regd_entities = (
            self.db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type == FundingEventType.REG_D_FILING)
            .distinct()
        )

        entities = self.db.query(Entity).filter(
            Entity.id.in_(sbir_entities.scalar_subquery()),
            Entity.id.in_(regd_entities.scalar_subquery()),
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            # Get SBIR summary
            sbir_awards = self.db.query(FundingEvent).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
            ).all()

            earliest_sbir = min(
                (a.event_date for a in sbir_awards if a.event_date),
                default=None,
            )
            total_sbir = sum(float(a.amount or 0) for a in sbir_awards)

            # Get Reg D summary (deduplicated)
            regd_filings_raw = self.db.query(FundingEvent).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type == FundingEventType.REG_D_FILING,
            ).all()
            regd_filings = _dedup_regd_filings(regd_filings_raw)

            total_regd = sum(float(f.amount or 0) for f in regd_filings)
            latest_regd = max(
                (f.event_date for f in regd_filings if f.event_date),
                default=None,
            )

            # Confidence scoring
            # Base: 0.70 for having both SBIR and Reg D
            # Bonus: +0.10 if VC raise came after SBIR (temporal validation)
            # Bonus: +0.05 if multiple Reg D filings (sustained investor interest)
            # Bonus: +0.05 if Reg D total > $10M (significant capital)
            confidence = Decimal("0.70")

            vc_after_sbir = False
            if earliest_sbir and latest_regd and latest_regd > earliest_sbir:
                confidence += Decimal("0.10")
                vc_after_sbir = True

            if len(regd_filings) >= 2:
                confidence += Decimal("0.05")

            if total_regd >= 10_000_000:
                confidence += Decimal("0.05")

            confidence = min(HIGH_CONFIDENCE, confidence)

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_SBIR_TO_VC,
                confidence=confidence,
                detected_date=latest_regd or date.today(),
                evidence={
                    "sbir_award_count": len(sbir_awards),
                    "total_sbir_value": total_sbir,
                    "earliest_sbir_date": str(earliest_sbir),
                    "regd_filing_count": len(regd_filings),
                    "total_regd_value": total_regd,
                    "latest_regd_date": str(latest_regd),
                    "vc_after_sbir": vc_after_sbir,
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"sbir_to_vc_signals": count}

    def detect_sbir_validated_raise(self) -> dict:
        """
        Strict version of sbir_to_vc_raise: detects entities where SBIR
        traction preceded and plausibly influenced private capital raises.

        Requires EITHER:
          A) The entity's first Reg D filing postdates its first SBIR award
             (entire VC history follows SBIR entry), OR
          B) A Reg D filing occurred within 18 months after an SBIR Phase II
             (Phase II milestone was the catalyst).

        Confidence scoring (additive, capped at 0.95):
          Base  0.70  — any Reg D postdates any SBIR
          +0.10       — first Reg D postdates first SBIR (pure pathway)
          +0.10       — Reg D within 18 months of Phase II (catalyst)
          +0.05       — post-SBIR raise amount > $5M (meaningful capital)
        """
        count = 0
        phase2_window_days = 548  # ~18 months

        sbir_types = [
            FundingEventType.SBIR_PHASE_1,
            FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]

        # Find entities that have both SBIR awards and Reg D filings
        sbir_entity_ids = (
            self.db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type.in_(sbir_types))
            .distinct()
        )
        regd_entity_ids = (
            self.db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type == FundingEventType.REG_D_FILING)
            .distinct()
        )

        entities = self.db.query(Entity).filter(
            Entity.id.in_(sbir_entity_ids.scalar_subquery()),
            Entity.id.in_(regd_entity_ids.scalar_subquery()),
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            # Fetch all SBIR awards with dates
            sbir_awards = self.db.query(FundingEvent).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_(sbir_types),
            ).all()

            sbir_with_dates = [a for a in sbir_awards if a.event_date]
            if not sbir_with_dates:
                continue

            first_sbir_date = min(a.event_date for a in sbir_with_dates)

            # Phase II awards specifically (for catalyst check)
            phase2_awards = [
                a for a in sbir_with_dates
                if a.event_type == FundingEventType.SBIR_PHASE_2
            ]

            # Fetch all Reg D filings with dates (deduplicated)
            regd_filings_raw = self.db.query(FundingEvent).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type == FundingEventType.REG_D_FILING,
            ).all()
            regd_filings = _dedup_regd_filings(regd_filings_raw)

            regd_with_dates = [f for f in regd_filings if f.event_date]
            if not regd_with_dates:
                continue

            first_regd_date = min(f.event_date for f in regd_with_dates)
            latest_regd_date = max(f.event_date for f in regd_with_dates)

            # ── Check trigger conditions ──────────────────────────

            # Condition A: first Reg D postdates first SBIR
            sbir_first_pathway = first_regd_date > first_sbir_date

            # Condition B: any Reg D within 18 months after a Phase II
            phase2_catalyst = False
            phase2_gap_months = None
            for p2 in phase2_awards:
                for rd in regd_with_dates:
                    gap = (rd.event_date - p2.event_date).days
                    if 0 < gap <= phase2_window_days:
                        phase2_catalyst = True
                        gap_mo = round(gap / 30.44)
                        if phase2_gap_months is None or gap_mo < phase2_gap_months:
                            phase2_gap_months = gap_mo
                        break
                if phase2_catalyst:
                    break

            # Must satisfy at least one condition
            if not sbir_first_pathway and not phase2_catalyst:
                continue

            # ── Confidence scoring ────────────────────────────────

            confidence = Decimal("0.70")

            if sbir_first_pathway:
                confidence += Decimal("0.10")

            if phase2_catalyst:
                confidence += Decimal("0.10")

            # Post-SBIR raise amount
            raise_amount_post_sbir = sum(
                float(f.amount or 0)
                for f in regd_with_dates
                if f.event_date > first_sbir_date
            )
            if raise_amount_post_sbir > 5_000_000:
                confidence += Decimal("0.05")

            confidence = min(Decimal("0.95"), confidence)

            # ── Classify the sequence ─────────────────────────────

            if sbir_first_pathway:
                sequence = "sbir_first"
            elif first_regd_date < first_sbir_date:
                sequence = "mixed"
            else:
                sequence = "vc_first"

            # ── Store signal ──────────────────────────────────────

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_SBIR_VALIDATED_RAISE,
                confidence=confidence,
                detected_date=latest_regd_date or date.today(),
                evidence={
                    "entity_name": entity.canonical_name,
                    "first_sbir_date": str(first_sbir_date),
                    "first_regd_date": str(first_regd_date),
                    "sbir_award_count": len(sbir_awards),
                    "regd_filing_count": len(regd_filings),
                    "raise_amount_post_sbir": raise_amount_post_sbir,
                    "sequence": sequence,
                    "sbir_first_pathway": sbir_first_pathway,
                    "phase2_catalyst": phase2_catalyst,
                    "phase2_to_raise_gap_months": phase2_gap_months,
                },
            )
            count += 1

        return {"sbir_validated_raise_signals": count}

    def detect_sbir_stalled(self) -> dict:
        """
        Detect entities with 2+ Phase I SBIR awards but zero Phase II.
        Indicates company is stuck in early R&D and failing to advance.
        This is a NEGATIVE signal (risk indicator).
        """
        count = 0

        # Get startups with SBIR Phase I awards
        phase1_entity_ids = (
            self.db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type == FundingEventType.SBIR_PHASE_1)
            .group_by(FundingEvent.entity_id)
            .having(func.count(FundingEvent.id) >= 2)
        )

        entities = self.db.query(Entity).filter(
            Entity.id.in_(phase1_entity_ids.scalar_subquery()),
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            # Check for any Phase II or Phase III awards
            advanced_count = self.db.query(func.count(FundingEvent.id)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
            ).scalar() or 0

            if advanced_count > 0:
                continue

            # Get Phase I details
            phase1_awards = self.db.query(FundingEvent).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type == FundingEventType.SBIR_PHASE_1,
            ).all()

            total_phase1_value = sum(float(a.amount or 0) for a in phase1_awards)
            earliest = min((a.event_date for a in phase1_awards if a.event_date), default=None)
            latest = max((a.event_date for a in phase1_awards if a.event_date), default=None)

            # Higher confidence with more Phase I awards (more evidence of stalling)
            confidence = min(HIGH_CONFIDENCE, Decimal(str(0.60 + len(phase1_awards) * 0.05)))

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_SBIR_STALLED,
                confidence=confidence,
                detected_date=latest or date.today(),
                evidence={
                    "phase_1_count": len(phase1_awards),
                    "phase_2_count": 0,
                    "total_phase_1_value": total_phase1_value,
                    "earliest_phase_1": str(earliest),
                    "latest_phase_1": str(latest),
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"sbir_stalled_signals": count}

    def detect_customer_concentration(self) -> dict:
        """
        Detect entities where >80% of contract value comes from a single agency.
        Indicates revenue concentration risk.
        This is a NEGATIVE signal (risk indicator).
        """
        count = 0
        concentration_threshold = 0.80

        entities = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            # Get contracts with valid agency and value
            contracts = self.db.query(Contract).filter(
                Contract.entity_id == entity.id,
                Contract.contract_value.isnot(None),
                Contract.contract_value > 0,
                Contract.contracting_agency.isnot(None),
            ).all()

            if len(contracts) < 2:
                continue

            # Aggregate value by agency
            agency_totals = {}
            total_value = Decimal(0)
            for c in contracts:
                agency = c.contracting_agency
                agency_totals[agency] = agency_totals.get(agency, Decimal(0)) + c.contract_value
                total_value += c.contract_value

            if total_value == 0:
                continue

            # Find dominant agency
            top_agency = max(agency_totals, key=agency_totals.get)
            top_value = agency_totals[top_agency]
            concentration = float(top_value) / float(total_value)

            if concentration >= concentration_threshold:
                # Higher concentration = higher confidence in the risk signal
                confidence = min(HIGH_CONFIDENCE, Decimal(str(0.60 + (concentration - 0.80) * 1.5)))

                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_CUSTOMER_CONCENTRATION,
                    confidence=confidence,
                    detected_date=date.today(),
                    evidence={
                        "dominant_agency": top_agency,
                        "concentration_pct": round(concentration * 100, 1),
                        "dominant_agency_value": float(top_value),
                        "total_contract_value": float(total_value),
                        "total_contracts": len(contracts),
                        "unique_agencies": len(agency_totals),
                        "entity_name": entity.canonical_name,
                    },
                )
                count += 1

        return {"customer_concentration_signals": count}

    def detect_sbir_graduation_speed(self) -> dict:
        """
        Measure days from first Phase I to first Phase II award.
        Signal fires for all companies that graduated; confidence is higher
        for faster graduations (below median).
        """
        count = 0

        # First pass: collect all graduation durations to compute median
        durations = []  # (entity, days, first_p1_date, first_p2_date)

        phase2_entity_ids = (
            self.db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type == FundingEventType.SBIR_PHASE_2)
            .distinct()
        )

        entities = self.db.query(Entity).filter(
            Entity.id.in_(phase2_entity_ids.scalar_subquery()),
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            first_p1 = self.db.query(func.min(FundingEvent.event_date)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type == FundingEventType.SBIR_PHASE_1,
                FundingEvent.event_date.isnot(None),
            ).scalar()

            first_p2 = self.db.query(func.min(FundingEvent.event_date)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type == FundingEventType.SBIR_PHASE_2,
                FundingEvent.event_date.isnot(None),
            ).scalar()

            if first_p1 and first_p2 and first_p2 > first_p1:
                days = (first_p2 - first_p1).days
                durations.append((entity, days, first_p1, first_p2))

        if not durations:
            return {"sbir_graduation_speed_signals": 0}

        # Compute median
        sorted_days = sorted(d[1] for d in durations)
        mid = len(sorted_days) // 2
        if len(sorted_days) % 2 == 0:
            median_days = (sorted_days[mid - 1] + sorted_days[mid]) / 2
        else:
            median_days = sorted_days[mid]

        # Second pass: create signals
        for entity, days, first_p1, first_p2 in durations:
            # Faster = higher confidence
            if days <= median_days:
                # Below median: scale 0.75–0.90 based on how fast
                speed_ratio = days / max(median_days, 1)
                confidence = min(HIGH_CONFIDENCE, Decimal(str(0.90 - speed_ratio * 0.15)))
            else:
                # Above median: still a signal but lower confidence
                slowness = min(days / max(median_days, 1), 3.0)
                confidence = max(LOW_CONFIDENCE, Decimal(str(0.75 - (slowness - 1) * 0.10)))

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_SBIR_GRADUATION_SPEED,
                confidence=confidence,
                detected_date=first_p2,
                evidence={
                    "days_to_graduate": days,
                    "first_phase_1_date": str(first_p1),
                    "first_phase_2_date": str(first_p2),
                    "median_days": round(median_days),
                    "faster_than_median": days <= median_days,
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {
            "sbir_graduation_speed_signals": count,
            "median_graduation_days": round(median_days),
        }

    def detect_time_to_contract(self) -> dict:
        """
        Measure days from first SBIR award to first real procurement contract.
        Faster transitions indicate strong commercialization capability.
        """
        count = 0

        durations = []  # (entity, days, first_sbir_date, first_contract_date)

        # Entities with both SBIR awards and contracts
        sbir_entity_ids = (
            self.db.query(FundingEvent.entity_id)
            .filter(
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ])
            )
            .distinct()
        )

        contract_entity_ids = (
            self.db.query(Contract.entity_id)
            .filter(Contract.contract_value > 0)
            .distinct()
        )

        entities = self.db.query(Entity).filter(
            Entity.id.in_(sbir_entity_ids.scalar_subquery()),
            Entity.id.in_(contract_entity_ids.scalar_subquery()),
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            first_sbir = self.db.query(func.min(FundingEvent.event_date)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
                FundingEvent.event_date.isnot(None),
            ).scalar()

            first_contract = self.db.query(func.min(Contract.award_date)).filter(
                Contract.entity_id == entity.id,
                Contract.contract_value > 0,
                Contract.award_date.isnot(None),
            ).scalar()

            if first_sbir and first_contract and first_contract > first_sbir:
                days = (first_contract - first_sbir).days
                durations.append((entity, days, first_sbir, first_contract))

        if not durations:
            return {"time_to_contract_signals": 0}

        sorted_days = sorted(d[1] for d in durations)
        mid = len(sorted_days) // 2
        if len(sorted_days) % 2 == 0:
            median_days = (sorted_days[mid - 1] + sorted_days[mid]) / 2
        else:
            median_days = sorted_days[mid]

        for entity, days, first_sbir, first_contract in durations:
            if days <= median_days:
                speed_ratio = days / max(median_days, 1)
                confidence = min(HIGH_CONFIDENCE, Decimal(str(0.90 - speed_ratio * 0.15)))
            else:
                slowness = min(days / max(median_days, 1), 3.0)
                confidence = max(LOW_CONFIDENCE, Decimal(str(0.75 - (slowness - 1) * 0.10)))

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_TIME_TO_CONTRACT,
                confidence=confidence,
                detected_date=first_contract,
                evidence={
                    "days_to_contract": days,
                    "first_sbir_date": str(first_sbir),
                    "first_contract_date": str(first_contract),
                    "median_days": round(median_days),
                    "faster_than_median": days <= median_days,
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {
            "time_to_contract_signals": count,
            "median_time_to_contract_days": round(median_days),
        }

    def detect_funding_velocity(self) -> dict:
        """
        Detect companies with high private capital fundraising velocity.
        2+ Reg D filings within 18 months = high velocity signal.
        """
        count = 0
        velocity_window_days = 548  # ~18 months

        regd_entity_ids = (
            self.db.query(FundingEvent.entity_id)
            .filter(FundingEvent.event_type == FundingEventType.REG_D_FILING)
            .group_by(FundingEvent.entity_id)
            .having(func.count(FundingEvent.id) >= 2)
        )

        entities = self.db.query(Entity).filter(
            Entity.id.in_(regd_entity_ids.scalar_subquery()),
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            filings = self.db.query(FundingEvent).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type == FundingEventType.REG_D_FILING,
                FundingEvent.event_date.isnot(None),
            ).order_by(FundingEvent.event_date).all()

            if len(filings) < 2:
                continue

            # Find the tightest window with 2+ filings
            best_window_filings = []
            for i in range(len(filings)):
                window = [filings[i]]
                for j in range(i + 1, len(filings)):
                    span = (filings[j].event_date - filings[i].event_date).days
                    if span <= velocity_window_days:
                        window.append(filings[j])
                if len(window) >= 2 and len(window) > len(best_window_filings):
                    best_window_filings = window

            if len(best_window_filings) < 2:
                continue

            window_start = best_window_filings[0].event_date
            window_end = best_window_filings[-1].event_date
            window_days = (window_end - window_start).days
            total_raised = sum(float(f.amount or 0) for f in best_window_filings)

            # Confidence: more filings in window + larger amounts = higher
            confidence = Decimal("0.70")
            if len(best_window_filings) >= 3:
                confidence += Decimal("0.10")
            if total_raised >= 10_000_000:
                confidence += Decimal("0.05")
            if total_raised >= 50_000_000:
                confidence += Decimal("0.05")
            confidence = min(HIGH_CONFIDENCE, confidence)

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_FUNDING_VELOCITY,
                confidence=confidence,
                detected_date=window_end,
                evidence={
                    "filings_in_window": len(best_window_filings),
                    "window_days": window_days,
                    "window_start": str(window_start),
                    "window_end": str(window_end),
                    "total_raised_in_window": total_raised,
                    "total_regd_filings": len(filings),
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"funding_velocity_signals": count}

    def detect_gone_stale(self) -> dict:
        """
        Detect entities whose most recent signal is >24 months old AND have
        no new contracts or funding events in that period.

        This is a NEGATIVE signal (risk indicator) — the company was once
        interesting but has gone quiet. Uses 24-month threshold to account
        for slow defense procurement timelines.
        """
        count = 0
        stale_cutoff = date.today() - timedelta(days=730)  # 24 months

        # Get entities with active signals where ALL signals are old
        entity_ids_with_signals = (
            self.db.query(Signal.entity_id)
            .filter(Signal.status == SignalStatus.ACTIVE)
            .group_by(Signal.entity_id)
            .having(func.max(Signal.detected_date) < stale_cutoff)
            .all()
        )

        for (entity_id,) in entity_ids_with_signals:
            entity = self.db.query(Entity).filter(
                Entity.id == entity_id,
                Entity.merged_into_id.is_(None),
            ).first()
            if not entity:
                continue

            # Check for recent contracts (award_date within 18 months)
            recent_contracts = (
                self.db.query(func.count(Contract.id))
                .filter(
                    Contract.entity_id == entity_id,
                    Contract.award_date >= stale_cutoff,
                )
                .scalar() or 0
            )
            if recent_contracts > 0:
                continue

            # Check for recent funding events (any type, within 18 months)
            recent_funding = (
                self.db.query(func.count(FundingEvent.id))
                .filter(
                    FundingEvent.entity_id == entity_id,
                    FundingEvent.event_date >= stale_cutoff,
                )
                .scalar() or 0
            )
            if recent_funding > 0:
                continue

            # Entity is stale — get details
            most_recent_signal = (
                self.db.query(Signal)
                .filter(
                    Signal.entity_id == entity_id,
                    Signal.status == SignalStatus.ACTIVE,
                )
                .order_by(Signal.detected_date.desc())
                .first()
            )

            if not most_recent_signal:
                continue

            months_since = (date.today() - most_recent_signal.detected_date).days // 30

            # Active signal count for this entity
            active_count = (
                self.db.query(func.count(Signal.id))
                .filter(
                    Signal.entity_id == entity_id,
                    Signal.status == SignalStatus.ACTIVE,
                )
                .scalar()
            )

            # Higher confidence the longer they've been quiet
            confidence = min(HIGH_CONFIDENCE, Decimal(str(0.60 + months_since * 0.01)))

            self._create_or_update_signal(
                entity_id=entity_id,
                signal_type=SIGNAL_GONE_STALE,
                confidence=confidence,
                detected_date=date.today(),
                evidence={
                    "months_since_last_signal": months_since,
                    "most_recent_signal_type": most_recent_signal.signal_type,
                    "most_recent_signal_date": str(most_recent_signal.detected_date),
                    "active_signal_count": active_count,
                    "recent_contracts": 0,
                    "recent_funding_events": 0,
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"gone_stale_signals": count}

    # ------------------------------------------------------------------
    # MEIA / KOP / JAR detectors
    # ------------------------------------------------------------------

    def _load_kops(self) -> list[dict]:
        """Load Key Operational Problems from policy_priorities.yaml."""
        config_path = Path(__file__).parent.parent / "config" / "policy_priorities.yaml"
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            af = config.get("acquisition_framework", {})
            kops = af.get("key_operational_problems", {})
            return kops.get("problems", [])
        except Exception as e:
            logger.warning(f"Could not load KOPs from config: {e}")
            return []

    def detect_kop_alignment(self) -> dict:
        """
        Detect entity alignment to Key Operational Problems.

        Uses technology_tags + SBIR titles to match against KOP technology_indicators.
        Confidence scales with KOP rank (rank 1 = 1.0, rank 7 = 0.4).
        """
        kops = self._load_kops()
        if not kops:
            return {"kop_alignment_signals": 0, "note": "No KOPs loaded"}

        count = 0
        entities = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            # Build entity tech profile from tags (normalized)
            tech_profile = set()
            if entity.technology_tags:
                try:
                    tags = json.loads(entity.technology_tags) if isinstance(entity.technology_tags, str) else entity.technology_tags
                    for t in tags:
                        tech_profile.update(_normalize_tag(t))
                except (json.JSONDecodeError, TypeError):
                    pass

            # Add keywords from SBIR titles via sbir_embeddings table
            sbir_titles = self.db.query(SbirEmbedding.award_title).filter(
                SbirEmbedding.entity_id == entity.id,
            ).all()

            for (title,) in sbir_titles:
                if title:
                    tech_profile.update(_extract_tech_keywords(title))

            if not tech_profile:
                continue

            # Score against each KOP using multi-word indicator matching
            best_kop = None
            best_score = 0.0
            best_matches = []

            for kop in kops:
                indicators = kop.get("technology_indicators", [])
                if not indicators:
                    continue
                matches = _match_indicators(tech_profile, indicators)
                if not matches:
                    continue
                score = len(matches) / len(indicators)

                # Rank multiplier: rank 1 = 1.0, rank 7 = 0.4
                rank = kop.get("estimated_rank", 7)
                rank_multiplier = 1.0 - (rank - 1) * 0.05  # rank 1=1.0, rank 7=0.7
                adjusted_score = score * max(rank_multiplier, 0.1)

                if adjusted_score > best_score:
                    best_score = adjusted_score
                    best_kop = kop
                    best_matches = matches

            if best_score >= 0.25 and best_kop:
                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_KOP_ALIGNMENT,
                    confidence=Decimal(str(min(best_score, 1.0))),
                    detected_date=date.today(),
                    evidence={
                        "kop_id": best_kop.get("id"),
                        "kop_name": best_kop.get("name"),
                        "kop_rank": best_kop.get("estimated_rank"),
                        "kop_status": "estimated",
                        "matching_indicators": sorted(best_matches),
                        "alignment_score": round(best_score, 3),
                        "tech_profile_size": len(tech_profile),
                        "source": "technology_tags + sbir_titles",
                    },
                )
                count += 1

        return {"kop_alignment_signals": count}

    def detect_meia_experimentation(self) -> dict:
        """
        Detect company participation in MEIA experimentation campaigns.

        Phase 1: Detected via enrichment_findings tagged as MEIA/experimentation.
        Phase 2: Detected via structured MEIA disclosure data when available.
        """
        count = 0

        # Check enrichment_findings for MEIA-related evidence
        meia_findings = (
            self.db.query(EnrichmentFinding)
            .filter(
                EnrichmentFinding.status == "ingested",
                or_(
                    EnrichmentFinding.finding_type == "meia_participation",
                    EnrichmentFinding.finding_data.contains("MEIA"),
                    EnrichmentFinding.finding_data.contains("experimentation campaign"),
                    EnrichmentFinding.finding_data.contains("mission engineering"),
                ),
            )
            .all()
        )

        seen_entities = set()
        for finding in meia_findings:
            if finding.entity_id in seen_entities:
                continue
            seen_entities.add(finding.entity_id)

            confidence_map = {"high": Decimal("0.90"), "medium": Decimal("0.70"), "low": Decimal("0.50")}
            confidence = confidence_map.get(finding.confidence, Decimal("0.60"))

            try:
                data = json.loads(finding.finding_data) if isinstance(finding.finding_data, str) else (finding.finding_data or {})
            except (json.JSONDecodeError, TypeError):
                data = {}

            self._create_or_update_signal(
                entity_id=finding.entity_id,
                signal_type=SIGNAL_MEIA_EXPERIMENTATION,
                confidence=confidence,
                detected_date=date.today(),
                evidence={
                    "source": "web_enrichment",
                    "source_url": finding.source_url,
                    "campaign_name": data.get("campaign_name"),
                    "kop_alignment": data.get("kop_id"),
                    "date": data.get("date"),
                    "details": data.get("description", ""),
                },
            )
            count += 1

        return {"meia_experimentation_signals": count}

    def detect_jar_funding(self) -> dict:
        """
        Detect JAR (Joint Acceleration Reserve) funding.

        Checks contracts table for JAR-tagged awards, then falls back to
        enrichment findings.
        """
        count = 0

        # Check contracts for JAR awards
        jar_contracts = (
            self.db.query(Contract.entity_id, Contract.contract_value, Contract.award_date, Contract.contracting_agency)
            .filter(
                or_(
                    Contract.procurement_type == "jar",
                    Contract.contract_type.ilike("%joint acceleration%"),
                ),
            )
            .all()
        )

        seen_entities = set()
        for entity_id, value, award_date, agency in jar_contracts:
            if entity_id in seen_entities:
                continue
            seen_entities.add(entity_id)

            self._create_or_update_signal(
                entity_id=entity_id,
                signal_type=SIGNAL_JAR_FUNDING,
                confidence=Decimal("0.95"),
                detected_date=award_date or date.today(),
                evidence={
                    "source": "contracts_db",
                    "value": str(value) if value else None,
                    "date": str(award_date) if award_date else None,
                    "agency": agency,
                },
            )
            count += 1

        # Fallback: enrichment findings
        jar_findings = (
            self.db.query(EnrichmentFinding)
            .filter(
                EnrichmentFinding.status == "ingested",
                or_(
                    EnrichmentFinding.finding_type == "jar_funding",
                    EnrichmentFinding.finding_data.contains("Joint Acceleration Reserve"),
                    EnrichmentFinding.finding_data.contains("JAR fund"),
                ),
            )
            .all()
        )

        for finding in jar_findings:
            if finding.entity_id in seen_entities:
                continue
            seen_entities.add(finding.entity_id)

            confidence_map = {"high": Decimal("0.90"), "medium": Decimal("0.70"), "low": Decimal("0.50")}
            confidence = confidence_map.get(finding.confidence, Decimal("0.60"))

            try:
                data = json.loads(finding.finding_data) if isinstance(finding.finding_data, str) else (finding.finding_data or {})
            except (json.JSONDecodeError, TypeError):
                data = {}

            self._create_or_update_signal(
                entity_id=finding.entity_id,
                signal_type=SIGNAL_JAR_FUNDING,
                confidence=confidence,
                detected_date=date.today(),
                evidence={
                    "source": "web_enrichment",
                    "source_url": finding.source_url,
                    "value": data.get("value"),
                    "date": data.get("date"),
                    "details": data.get("description", ""),
                },
            )
            count += 1

        return {"jar_funding_signals": count}

    def detect_pae_portfolio(self) -> dict:
        """
        Detect inclusion in a Portfolio Acquisition Executive's portfolio.

        Checks relationships table for IN_PAE_PORTFOLIO edges.
        """
        count = 0

        try:
            pae_rels = (
                self.db.query(Relationship)
                .filter(Relationship.relationship_type == RelationshipType.IN_PAE_PORTFOLIO)
                .all()
            )
        except Exception:
            # RelationshipType may not have IN_PAE_PORTFOLIO yet
            return {"pae_portfolio_signals": 0, "note": "IN_PAE_PORTFOLIO relationship type not available"}

        seen_entities = set()
        for rel in pae_rels:
            if rel.source_entity_id in seen_entities:
                continue
            seen_entities.add(rel.source_entity_id)

            props = rel.properties or {}

            self._create_or_update_signal(
                entity_id=rel.source_entity_id,
                signal_type=SIGNAL_PAE_PORTFOLIO,
                confidence=Decimal("0.85"),
                detected_date=date.today(),
                evidence={
                    "pae_name": rel.target_name,
                    "portfolio_area": props.get("portfolio_area"),
                    "source": props.get("source", "web_enrichment"),
                },
            )
            count += 1

        return {"pae_portfolio_signals": count}

    def detect_commercial_pathway(self) -> dict:
        """
        Detect companies positioned for the "presumption of commerciality"
        pathway under FY26 NDAA.

        Scores based on: commercial keywords in business description,
        dual traction (SBIR + private capital), multi-source funding
        (contracts + private capital), and dual-use technology tags.
        """
        count = 0
        commercial_keywords = [
            "commercial", "cots", "dual-use", "civilian",
            "enterprise", "saas", "commercial off-the-shelf",
            "dual use", "commercial product",
        ]
        dual_use_tag_keywords = ["commercial", "dual-use", "enterprise", "saas", "cloud"]

        entities = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            # Skip entities without business reasoning
            if not entity.core_business_reasoning:
                continue

            indicators = []
            score = 0.0

            # Check business description for commercial keywords (+0.2 each, cap 0.4)
            business_desc = entity.core_business_reasoning.lower()
            keyword_score = 0.0
            for kw in commercial_keywords:
                if kw in business_desc:
                    indicators.append(f"Business description mentions '{kw}'")
                    keyword_score += 0.2
                    if keyword_score >= 0.4:
                        break
            score += min(keyword_score, 0.4)

            # Check for both SBIR AND private capital (dual traction: +0.3)
            sbir_count = self.db.query(func.count(FundingEvent.id)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
            ).scalar() or 0

            regd_count = self.db.query(func.count(FundingEvent.id)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.REG_D_FILING,
                    FundingEventType.PRIVATE_ROUND,
                ]),
            ).scalar() or 0

            if sbir_count > 0 and regd_count > 0:
                indicators.append(f"Dual traction: {sbir_count} SBIRs + {regd_count} private rounds")
                score += 0.3

            # Check for contracts AND private capital (multi-source: +0.2)
            contract_count = self.db.query(func.count(Contract.id)).filter(
                Contract.entity_id == entity.id,
            ).scalar() or 0

            if contract_count > 0 and regd_count > 0:
                indicators.append("Has both contracts and private capital")
                score += 0.2

            # Check technology_tags for dual-use indicators (+0.1 each, cap 0.2)
            tag_score = 0.0
            if entity.technology_tags:
                try:
                    tags = json.loads(entity.technology_tags) if isinstance(entity.technology_tags, str) else entity.technology_tags
                    if tags:
                        for tag in tags:
                            tag_lower = tag.lower()
                            for dukw in dual_use_tag_keywords:
                                if dukw in tag_lower:
                                    tag_score += 0.1
                                    break
                            if tag_score >= 0.2:
                                break
                except (json.JSONDecodeError, TypeError):
                    pass
            score += min(tag_score, 0.2)

            if score >= 0.4 and indicators:
                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_COMMERCIAL_PATHWAY,
                    confidence=Decimal(str(min(score, 1.0))),
                    detected_date=date.today(),
                    evidence={
                        "commercial_score": round(score, 2),
                        "indicators": indicators,
                        "sbir_count": sbir_count,
                        "regd_count": regd_count,
                        "contract_count": contract_count,
                        "note": "FY26 NDAA presumption of commerciality benefits this company",
                    },
                )
                count += 1

        return {"commercial_pathway_signals": count}

    def detect_sbir_lapse_risk(self) -> dict:
        """
        SBIR lapse risk: program lapsed Oct 1 2025, reauthorized March 4 2026 (~5 months).
        Companies mid-Phase II during lapse face pipeline disruption even post-restart.
        Agencies need time to process backlog before new awards flow.
        Signal remains relevant through Q3 2026 for affected companies.

        Fires for companies where SBIR is >70% of total government funding
        AND they have no significant private capital (< $1M Reg D).
        """
        count = 0

        # Subquery for superseded funding events (same pattern as aperture_query.py)
        superseded_ids = self.db.query(FundingEvent.parent_event_id).filter(
            FundingEvent.parent_event_id.isnot(None)
        )

        entities = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        for entity in entities:
            # SBIR total and count (exclude superseded)
            sbir_agg = self.db.query(
                func.coalesce(func.sum(FundingEvent.amount), 0),
                func.count(FundingEvent.id),
            ).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.SBIR_PHASE_1,
                    FundingEventType.SBIR_PHASE_2,
                    FundingEventType.SBIR_PHASE_3,
                ]),
                ~FundingEvent.id.in_(superseded_ids),
            ).one()
            sbir_total = sbir_agg[0] or 0
            sbir_count = sbir_agg[1] or 0

            # Skip companies without real SBIR pipelines:
            # require >= $500K total (roughly a Phase II) AND >= 2 awards
            if sbir_total == 0 or float(sbir_total) < 500_000 or sbir_count < 2:
                continue

            # Skip public companies — they have market-cap-level funding
            is_public = self.db.execute(
                text("""SELECT 1 FROM enrichment_findings
                        WHERE entity_id = :eid AND finding_type = 'public_company'
                        AND status IN ('approved', 'ingested')"""),
                {"eid": entity.id},
            ).fetchone()
            if is_public:
                continue

            # Contract total
            contract_total = self.db.query(func.coalesce(func.sum(Contract.contract_value), 0)).filter(
                Contract.entity_id == entity.id,
            ).scalar() or 0

            # Private capital total (Reg D + Private Round, exclude superseded)
            regd_total = self.db.query(func.coalesce(func.sum(FundingEvent.amount), 0)).filter(
                FundingEvent.entity_id == entity.id,
                FundingEvent.event_type.in_([
                    FundingEventType.REG_D_FILING,
                    FundingEventType.PRIVATE_ROUND,
                ]),
                ~FundingEvent.id.in_(superseded_ids),
            ).scalar() or 0

            total_gov = float(sbir_total) + float(contract_total)
            if total_gov == 0:
                continue

            sbir_pct = float(sbir_total) / total_gov

            # Only flag if SBIR-dependent AND capital-thin
            if sbir_pct > 0.70 and float(regd_total) < 1_000_000:
                # Determine risk level based on dependency percentage
                if sbir_pct >= 0.90:
                    risk_level = "high"
                elif sbir_pct >= 0.80:
                    risk_level = "medium"
                else:
                    risk_level = "low"

                self._create_or_update_signal(
                    entity_id=entity.id,
                    signal_type=SIGNAL_SBIR_LAPSE_RISK,
                    confidence=Decimal(str(round(sbir_pct, 2))),
                    detected_date=date.today(),
                    evidence={
                        "sbir_total": float(sbir_total),
                        "contract_total": float(contract_total),
                        "regd_total": float(regd_total),
                        "sbir_dependency_pct": round(sbir_pct * 100, 1),
                        "total_gov_funding": float(total_gov),
                        "risk_level": risk_level,
                        "lapse_period_months": 5,
                        "reauthorization_date": "2026-03-04",
                        "reauthorization_act": "Small Business Innovation and Economic Security Act",
                        "pipeline_status": "disrupted_recovering",
                    },
                )
                count += 1

        return {"sbir_lapse_risk_signals": count}

    # ------------------------------------------------------------------
    # Contract vehicle progression signals
    # ------------------------------------------------------------------

    def detect_sole_source_award(self) -> dict:
        """
        Detect startups with sole-source (non-competed) contract awards.

        Sole-source indicates the government considers this company the only
        viable provider — strong defensibility signal that often precedes
        follow-on production contracts.

        Data availability: Only OTA contracts (SAM.gov) have competition data.
        Standard contracts (USASpending) lack extent_competed field.
        Detects via nested JSON: coreData.competitionInformation.extentCompeted.code = 'C'
        OR coreData.competitionInformation.solicitationProcedures.code = 'SSS'
        """
        count = 0

        startups = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        startup_ids = {e.id for e in startups}
        startup_map = {e.id: e for e in startups}

        # Query OTA contracts with raw_data (only source with competition info)
        ota_contracts = self.db.query(Contract).filter(
            Contract.entity_id.in_(startup_ids),
            Contract.procurement_type == "ota",
            Contract.raw_data.isnot(None),
        ).all()

        for contract in ota_contracts:
            raw = contract.raw_data
            if not isinstance(raw, dict):
                try:
                    raw = json.loads(raw) if isinstance(raw, str) else {}
                except (json.JSONDecodeError, TypeError):
                    continue

            comp_info = raw.get("coreData", {}).get("competitionInformation", {})
            extent_code = comp_info.get("extentCompeted", {}).get("code", "")
            sol_code = comp_info.get("solicitationProcedures", {}).get("code", "")
            extent_name = comp_info.get("extentCompeted", {}).get("name", "")
            sol_name = comp_info.get("solicitationProcedures", {}).get("name", "")

            is_sole_source = extent_code == "C" or sol_code == "SSS"
            if not is_sole_source:
                continue

            entity = startup_map.get(contract.entity_id)
            if not entity:
                continue

            self._create_or_update_signal(
                entity_id=entity.id,
                signal_type=SIGNAL_SOLE_SOURCE_AWARD,
                confidence=Decimal("0.85"),
                detected_date=contract.award_date or date.today(),
                evidence={
                    "contracting_agency": contract.contracting_agency,
                    "contract_value": float(contract.contract_value or 0),
                    "award_date": str(contract.award_date) if contract.award_date else None,
                    "contract_number": contract.contract_number,
                    "extent_competed": extent_name or extent_code,
                    "solicitation_procedures": sol_name or sol_code,
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"sole_source_award_signals": count}

    def detect_ota_bridge_award(self) -> dict:
        """
        Detect startups that bridged from OTA prototype to standard (FAR) production contract.

        The OTA-to-production transition is the canonical defense startup maturation
        path. Companies that complete this bridge are acquisition targets and capital
        events.

        Fires when entity has OTA contract AND a later standard contract.
        Agency matching at department level (OTA uses office names, standard uses
        department names — both share sub-tier identifiers).
        """
        count = 0

        startups = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        startup_ids = {e.id for e in startups}
        startup_map = {e.id: e for e in startups}

        # Get all contracts for startups, grouped by entity
        all_contracts = self.db.query(Contract).filter(
            Contract.entity_id.in_(startup_ids),
        ).order_by(Contract.award_date).all()

        from collections import defaultdict
        entity_contracts = defaultdict(list)
        for c in all_contracts:
            entity_contracts[c.entity_id].append(c)

        for entity_id, contracts in entity_contracts.items():
            ota_contracts = [c for c in contracts if c.procurement_type == "ota"]
            std_contracts = [c for c in contracts if c.procurement_type == "standard"]

            if not ota_contracts or not std_contracts:
                continue

            # Find earliest OTA and any standard contract that follows it
            earliest_ota = None
            for c in ota_contracts:
                if c.award_date and (earliest_ota is None or c.award_date < earliest_ota.award_date):
                    earliest_ota = c

            if earliest_ota is None or earliest_ota.award_date is None:
                # Try with undated OTAs — if entity has both types, still meaningful
                # but we can't confirm temporal ordering, so skip
                continue

            # Find first standard contract after the OTA
            followon = None
            for c in std_contracts:
                if c.award_date and c.award_date > earliest_ota.award_date:
                    if followon is None or c.award_date < followon.award_date:
                        followon = c

            if followon is None:
                continue

            gap_days = (followon.award_date - earliest_ota.award_date).days
            gap_months = round(gap_days / 30.44, 1)

            entity = startup_map.get(entity_id)
            if not entity:
                continue

            self._create_or_update_signal(
                entity_id=entity_id,
                signal_type=SIGNAL_OTA_BRIDGE_AWARD,
                confidence=Decimal("0.90"),
                detected_date=followon.award_date,
                evidence={
                    "ota_agency": earliest_ota.contracting_agency,
                    "ota_value": float(earliest_ota.contract_value or 0),
                    "ota_date": str(earliest_ota.award_date),
                    "followon_agency": followon.contracting_agency,
                    "followon_value": float(followon.contract_value or 0),
                    "followon_date": str(followon.award_date),
                    "gap_months": gap_months,
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"ota_bridge_award_signals": count}

    def detect_multi_vehicle_presence(self) -> dict:
        """
        Detect startups with contracts across 3+ distinct vehicle types.

        Multi-vehicle presence means government is finding this company through
        multiple acquisition pathways simultaneously — indicates broad demand.

        Vehicle types classified from available data:
        - 'ota': procurement_type = 'ota'
        - 'sbir': has SBIR funding events
        - 'baa_rd': R&D PSC codes (A-series = R&D/BAA-type)
        - 'standard_production': standard contracts with non-R&D PSC codes
        """
        count = 0

        startups = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        startup_ids = {e.id for e in startups}
        startup_map = {e.id: e for e in startups}

        # Pre-fetch all contracts for startups
        all_contracts = self.db.query(Contract).filter(
            Contract.entity_id.in_(startup_ids),
        ).all()

        from collections import defaultdict
        entity_contracts = defaultdict(list)
        for c in all_contracts:
            entity_contracts[c.entity_id].append(c)

        # Pre-fetch SBIR status per entity
        sbir_entities = set()
        sbir_results = self.db.query(FundingEvent.entity_id).filter(
            FundingEvent.entity_id.in_(startup_ids),
            FundingEvent.event_type.in_([
                FundingEventType.SBIR_PHASE_1,
                FundingEventType.SBIR_PHASE_2,
                FundingEventType.SBIR_PHASE_3,
            ]),
        ).distinct().all()
        sbir_entities = {r[0] for r in sbir_results}

        for entity_id, contracts in entity_contracts.items():
            vehicle_types = set()
            total_value = Decimal(0)

            # Check OTA
            if any(c.procurement_type == "ota" for c in contracts):
                vehicle_types.add("ota")

            # Check SBIR
            if entity_id in sbir_entities:
                vehicle_types.add("sbir")

            # Check R&D (BAA-type): PSC codes starting with 'A'
            if any(c.psc_code and c.psc_code.startswith("A") for c in contracts):
                vehicle_types.add("baa_rd")

            # Check standard production (non-R&D standard contracts)
            std_non_rd = [
                c for c in contracts
                if c.procurement_type == "standard"
                and not (c.psc_code and c.psc_code.startswith("A"))
            ]
            if std_non_rd:
                vehicle_types.add("standard_production")

            for c in contracts:
                total_value += c.contract_value or Decimal(0)

            if len(vehicle_types) < 3:
                continue

            entity = startup_map.get(entity_id)
            if not entity:
                continue

            self._create_or_update_signal(
                entity_id=entity_id,
                signal_type=SIGNAL_MULTI_VEHICLE_PRESENCE,
                confidence=Decimal("0.80"),
                detected_date=date.today(),
                evidence={
                    "vehicle_types": sorted(vehicle_types),
                    "vehicle_count": len(vehicle_types),
                    "total_contract_value": float(total_value),
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"multi_vehicle_presence_signals": count}

    def detect_contract_value_step_change(self) -> dict:
        """
        Detect startups whose most recent contract is 5x+ their median prior contract.

        A step-change in contract size (e.g., $2M -> $15M) indicates the government
        has moved from R&D to production commitment. Often precedes private capital raise.

        Requires minimum 3 prior contracts to avoid noise. Uses contracts with
        non-null, positive values.
        """
        count = 0
        min_prior = 3
        step_threshold = 5.0

        startups = self.db.query(Entity).filter(
            Entity.entity_type == EntityType.STARTUP,
            Entity.merged_into_id.is_(None),
        ).all()

        startup_ids = {e.id for e in startups}
        startup_map = {e.id: e for e in startups}

        # Pre-fetch contracts with positive values, ordered by date
        all_contracts = self.db.query(Contract).filter(
            Contract.entity_id.in_(startup_ids),
            Contract.contract_value > 0,
        ).order_by(Contract.award_date).all()

        from collections import defaultdict
        entity_contracts = defaultdict(list)
        for c in all_contracts:
            entity_contracts[c.entity_id].append(c)

        for entity_id, contracts in entity_contracts.items():
            if len(contracts) < min_prior + 1:
                continue

            # Latest contract is the last one (ordered by date)
            # Handle NULL dates: sort with NULLs last
            dated = [c for c in contracts if c.award_date is not None]
            if len(dated) < min_prior + 1:
                continue

            dated.sort(key=lambda c: c.award_date)
            latest = dated[-1]
            prior = dated[:-1]

            # Calculate median of prior contracts
            prior_values = sorted([float(c.contract_value) for c in prior])
            n = len(prior_values)
            if n % 2 == 0:
                median_prior = (prior_values[n // 2 - 1] + prior_values[n // 2]) / 2
            else:
                median_prior = prior_values[n // 2]

            if median_prior <= 0:
                continue

            latest_value = float(latest.contract_value)
            step_ratio = latest_value / median_prior

            if step_ratio < step_threshold:
                continue

            entity = startup_map.get(entity_id)
            if not entity:
                continue

            self._create_or_update_signal(
                entity_id=entity_id,
                signal_type=SIGNAL_CONTRACT_VALUE_STEP_CHANGE,
                confidence=Decimal("0.75"),
                detected_date=latest.award_date or date.today(),
                evidence={
                    "latest_contract_value": latest_value,
                    "median_prior_value": round(median_prior, 2),
                    "step_ratio": round(step_ratio, 2),
                    "latest_agency": latest.contracting_agency,
                    "latest_date": str(latest.award_date) if latest.award_date else None,
                    "prior_contract_count": len(prior),
                    "entity_name": entity.canonical_name,
                },
            )
            count += 1

        return {"contract_value_step_change_signals": count}

    def detect_strategic_breakthrough_awards(self, entity_ids=None):
        """
        Detects Strategic Breakthrough Award recipients.

        New program created by Small Business Innovation and Economic Security Act
        (March 2026). Requires 100% matching funds, 48-month performance period.
        Companies receiving this award are explicitly venture-capital-ready by design.

        STATUS: STUB — first DoD solicitations expected Q4 FY2026 (July-Sept 2026).
        Will fire when awards begin appearing in SBIR.gov / USASpending data.

        Detection logic (when live):
        - SBIR.gov award with program = 'Strategic Breakthrough' or equivalent tag
        - USASpending contract with SBIR topic referencing Strategic Breakthrough
        - Confidence: 0.95 (highest in platform — matching capital already committed)
        """
        logger.info("strategic_breakthrough_award: STUB — no awards expected until Q4 FY2026")
        return {"strategic_breakthrough_award_signals": 0}


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
