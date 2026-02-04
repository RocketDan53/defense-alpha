"""
Entity Resolution Module

Hybrid entity resolution combining:
- Identifier-based matching (CAGE, DUNS, EIN) - definitive
- Fuzzy name matching with location/NAICS confirmation
- Manual review queue for ambiguous cases

Decision tree:
a) If shared identifier (CAGE/DUNS/EIN) → MERGE (confidence: 1.0)
b) If name similarity >90 AND same state → MERGE (confidence: 0.95)
c) If name similarity >90 AND same NAICS code → MERGE (confidence: 0.90)
d) If name similarity 70-90 → FLAG FOR REVIEW
e) If name similarity <70 → KEEP SEPARATE
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from config.logging import logger
from config.settings import settings
from processing.models import Entity, EntityType, EntityMerge, MergeReason


@dataclass
class ResolutionStats:
    """Statistics from a resolution run."""
    total_entities_start: int = 0
    total_entities_end: int = 0
    high_confidence_merges: int = 0
    medium_confidence_merges: int = 0
    flagged_for_review: int = 0
    identifier_matches: int = 0
    name_location_matches: int = 0
    name_naics_matches: int = 0


@dataclass
class PotentialMatch:
    """A potential duplicate match between two entities."""
    entity_a: Entity
    entity_b: Entity
    similarity_score: float
    match_reason: str
    shared_identifiers: list[str] = field(default_factory=list)
    shared_location: bool = False
    shared_naics: bool = False

    @property
    def confidence(self) -> float:
        """Calculate confidence score based on match signals."""
        if self.shared_identifiers:
            return 1.0
        if self.similarity_score >= 90:
            if self.shared_location:
                return 0.95
            if self.shared_naics:
                return 0.90
            return 0.85
        return self.similarity_score / 100.0


class EntityResolver:
    """
    Hybrid entity resolver for deduplication.

    Usage:
        resolver = EntityResolver(db)
        stats = resolver.resolve_all_entities()
        resolver.export_review_queue()
    """

    # Common corporate suffixes to normalize (order matters - longer patterns first)
    CORPORATE_SUFFIXES = [
        # Full words first
        r"\s+Incorporated$",
        r"\s+Corporation$",
        r"\s+Limited$",
        r"\s+Company$",
        # Then abbreviations
        r"\s+Inc\.?$",
        r"\s+Corp\.?$",
        r"\s+LLC\.?$",
        r"\s+L\.L\.C\.?$",
        r"\s+Ltd\.?$",
        r"\s+LLP\.?$",
        r"\s+L\.L\.P\.?$",
        r"\s+LP\.?$",
        r"\s+L\.P\.?$",
        r"\s+Co\.?$",
        r"\s+PC\.?$",
        r"\s+P\.C\.?$",
        r"\s+PLLC\.?$",
        # Handle comma before suffix
        r",\s*Inc\.?$",
        r",\s*LLC\.?$",
        r",\s*Corp\.?$",
        r",\s*$",  # Trailing commas
    ]

    # State abbreviations for location matching
    US_STATES = {
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'
    }

    # Generic industry words that shouldn't drive matches on their own
    # If BOTH normalized names reduce to just these words, don't flag as match
    GENERIC_WORDS = {
        'aerospace', 'technologies', 'technology', 'systems', 'solutions',
        'services', 'defense', 'dynamics', 'industries', 'engineering',
        'international', 'corporation', 'advanced', 'global', 'group',
        'associates', 'consulting', 'research', 'analytics', 'scientific',
        'innovations', 'enterprises', 'partners', 'holdings', 'management',
    }

    def __init__(self, db: Session):
        self.db = db
        self.review_queue: list[PotentialMatch] = []
        self.stats = ResolutionStats()

    def normalize_name(self, name: str, verbose: bool = False) -> str:
        """
        Normalize company name for comparison.

        - Remove common suffixes (Inc, LLC, Corp, Corporation, etc.)
        - Remove punctuation and extra whitespace
        - Lowercase everything
        - Handle "The XYZ Company" → "xyz"
        """
        if not name:
            return ""

        original = name
        normalized = name.strip()

        # Remove corporate suffixes (case insensitive) - apply multiple times
        # to handle cases like "XYZ Corp." or "XYZ Corporation"
        for _ in range(3):  # Multiple passes for nested suffixes
            prev = normalized
            for pattern in self.CORPORATE_SUFFIXES:
                normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
            normalized = normalized.strip()
            if normalized == prev:
                break

        # Remove punctuation and normalize whitespace
        normalized = re.sub(r"[^\w\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Lowercase
        normalized = normalized.lower()

        # Handle "The XYZ" -> "xyz" (remove leading "the")
        if normalized.startswith("the "):
            normalized = normalized[4:]

        if verbose and original.lower() != normalized:
            logger.debug(f"  Normalized: '{original}' → '{normalized}'")

        return normalized

    def is_only_generic_words(self, normalized_name: str) -> bool:
        """
        Check if a normalized name consists only of generic industry words.

        Used to filter out false positive matches like "aerospace" vs "aerospace technologies"
        which would match highly but are clearly different companies.
        """
        if not normalized_name:
            return True

        words = set(normalized_name.lower().split())
        # If all words are generic, return True
        return words.issubset(self.GENERIC_WORDS)

    def calculate_similarity(self, name1: str, name2: str) -> float:
        """
        Calculate fuzzy similarity score between two names.

        Uses combined scoring:
        - Token sort ratio (40%): handles word reordering
        - Token set ratio (40%): handles partial matches
        - Standard ratio (20%): exact similarity

        Returns score 0-100.
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        if not norm1 or not norm2:
            return 0.0

        token_sort = fuzz.token_sort_ratio(norm1, norm2)
        token_set = fuzz.token_set_ratio(norm1, norm2)
        ratio = fuzz.ratio(norm1, norm2)

        return (token_sort * 0.4) + (token_set * 0.4) + (ratio * 0.2)

    def check_identifier_match(self, e1: Entity, e2: Entity) -> list[str]:
        """
        Check if two entities share any identifier.

        Returns list of matching identifier types.
        """
        matches = []

        if e1.cage_code and e2.cage_code and e1.cage_code == e2.cage_code:
            matches.append("cage_code")
        if e1.duns_number and e2.duns_number and e1.duns_number == e2.duns_number:
            matches.append("duns_number")
        if e1.ein and e2.ein and e1.ein == e2.ein:
            matches.append("ein")

        return matches

    def extract_state(self, location: Optional[str]) -> Optional[str]:
        """Extract state abbreviation from location string."""
        if not location:
            return None

        # Look for state abbreviation
        parts = location.upper().replace(",", " ").split()
        for part in parts:
            if part in self.US_STATES:
                return part

        return None

    def check_location_match(self, e1: Entity, e2: Entity) -> bool:
        """Check if two entities are in the same state."""
        state1 = self.extract_state(e1.headquarters_location)
        state2 = self.extract_state(e2.headquarters_location)

        if state1 and state2:
            return state1 == state2
        return False

    def get_entity_naics_codes(self, entity: Entity) -> set[str]:
        """Get all NAICS codes associated with an entity's contracts."""
        codes = set()
        for contract in entity.contracts:
            if contract.naics_code:
                codes.add(contract.naics_code)
        return codes

    def check_naics_match(self, e1: Entity, e2: Entity) -> bool:
        """Check if two entities share any NAICS codes."""
        codes1 = self.get_entity_naics_codes(e1)
        codes2 = self.get_entity_naics_codes(e2)

        if codes1 and codes2:
            return bool(codes1 & codes2)
        return False

    def find_potential_duplicates(
        self,
        entity: Entity,
        threshold: float = 70.0,
    ) -> list[PotentialMatch]:
        """
        Find potential duplicate matches for a single entity.

        Args:
            entity: Entity to find duplicates for
            threshold: Minimum similarity score (0-100)

        Returns:
            List of potential matches above threshold
        """
        matches = []

        # Get all active (non-merged) entities except the current one
        candidates = self.db.query(Entity).filter(
            Entity.id != entity.id,
            Entity.merged_into_id.is_(None)
        ).all()

        for candidate in candidates:
            # Check identifier match first (definitive)
            shared_ids = self.check_identifier_match(entity, candidate)
            if shared_ids:
                matches.append(PotentialMatch(
                    entity_a=entity,
                    entity_b=candidate,
                    similarity_score=100.0,
                    match_reason=f"identifier_match: {', '.join(shared_ids)}",
                    shared_identifiers=shared_ids,
                ))
                continue

            # Calculate name similarity
            # Check against canonical name and all variants
            best_score = self.calculate_similarity(
                entity.canonical_name,
                candidate.canonical_name
            )

            # Also check entity's name against candidate's variants
            for variant in (candidate.name_variants or []):
                score = self.calculate_similarity(entity.canonical_name, variant)
                best_score = max(best_score, score)

            # And candidate's name against entity's variants
            for variant in (entity.name_variants or []):
                score = self.calculate_similarity(variant, candidate.canonical_name)
                best_score = max(best_score, score)

            if best_score >= threshold:
                # Skip if both names are only generic industry words
                norm1 = self.normalize_name(entity.canonical_name)
                norm2 = self.normalize_name(candidate.canonical_name)

                if self.is_only_generic_words(norm1) and self.is_only_generic_words(norm2):
                    # Both names are just generic words - skip this match
                    continue

                shared_location = self.check_location_match(entity, candidate)
                shared_naics = self.check_naics_match(entity, candidate)

                reason_parts = [f"name_similarity: {best_score:.1f}"]
                if shared_location:
                    reason_parts.append("same_state")
                if shared_naics:
                    reason_parts.append("same_naics")

                matches.append(PotentialMatch(
                    entity_a=entity,
                    entity_b=candidate,
                    similarity_score=best_score,
                    match_reason=", ".join(reason_parts),
                    shared_location=shared_location,
                    shared_naics=shared_naics,
                ))

        return matches

    def determine_canonical_entity(self, e1: Entity, e2: Entity) -> tuple[Entity, Entity]:
        """
        Determine which entity should be the canonical (kept) one.

        Prefers entity with:
        1. More identifiers (CAGE, DUNS, EIN)
        2. More relationships (contracts, funding, signals)
        3. More complete data
        """
        def score_completeness(e: Entity) -> int:
            score = 0
            if e.cage_code:
                score += 10
            if e.duns_number:
                score += 10
            if e.ein:
                score += 10
            if e.headquarters_location:
                score += 5
            if e.founded_date:
                score += 5
            if e.technology_tags:
                score += len(e.technology_tags)

            # Relationship counts
            score += len(e.contracts) * 3
            score += len(e.funding_events) * 3
            score += len(e.signals) * 2

            return score

        score1 = score_completeness(e1)
        score2 = score_completeness(e2)

        if score1 >= score2:
            return e1, e2  # e1 is canonical, e2 is merged
        return e2, e1  # e2 is canonical, e1 is merged

    def merge_entities(
        self,
        source: Entity,
        target: Entity,
        confidence_score: float,
        merge_reason: MergeReason,
        details: Optional[dict] = None,
    ) -> Entity:
        """
        Merge source entity into target entity.

        - Keeps target as canonical
        - Adds source name to target's name_variants
        - Preserves all non-null identifiers
        - Updates all relationships to point to target
        - Soft deletes source (sets merged_into_id)
        - Creates audit record

        Args:
            source: Entity to merge (will be soft deleted)
            target: Entity to keep (canonical)
            confidence_score: Confidence of the merge decision
            merge_reason: Reason for the merge
            details: Additional details for audit

        Returns:
            Updated target entity
        """
        logger.info(
            f"Merging '{source.canonical_name}' into '{target.canonical_name}' "
            f"(confidence: {confidence_score:.2f}, reason: {merge_reason.value})"
        )

        try:
            # Add source name and variants to target's variants
            variants = set(target.name_variants or [])
            variants.add(source.canonical_name)
            variants.update(source.name_variants or [])
            # Remove the canonical name from variants
            variants.discard(target.canonical_name)
            target.name_variants = list(variants)

            # Fill missing identifiers from source
            if not target.cage_code and source.cage_code:
                target.cage_code = source.cage_code
            if not target.duns_number and source.duns_number:
                target.duns_number = source.duns_number
            if not target.ein and source.ein:
                target.ein = source.ein

            # Fill missing metadata
            if not target.headquarters_location and source.headquarters_location:
                target.headquarters_location = source.headquarters_location
            if not target.founded_date and source.founded_date:
                target.founded_date = source.founded_date

            # Merge technology tags
            target_tags = set(target.technology_tags or [])
            source_tags = set(source.technology_tags or [])
            target.technology_tags = list(target_tags | source_tags)

            # Transfer relationships
            for funding in source.funding_events:
                funding.entity_id = target.id
            for contract in source.contracts:
                contract.entity_id = target.id
            for signal in source.signals:
                signal.entity_id = target.id

            # Soft delete source (don't actually delete, just mark as merged)
            source.merged_into_id = target.id

            # Create audit record
            merge_record = EntityMerge(
                source_entity_id=source.id,
                target_entity_id=target.id,
                merge_reason=merge_reason,
                confidence_score=Decimal(str(confidence_score)),
                source_name=source.canonical_name,
                target_name=target.canonical_name,
                details=details or {},
            )
            self.db.add(merge_record)

            self.db.commit()

            logger.info(
                f"Merge complete. Target now has {len(target.name_variants)} name variants"
            )
            return target

        except Exception as e:
            logger.error(f"Merge failed, rolling back: {e}")
            self.db.rollback()
            raise

    def resolve_all_entities(self, dry_run: bool = False, verbose: bool = False) -> ResolutionStats:
        """
        Run full entity resolution pass.

        Decision tree:
        a) If shared identifier (CAGE/DUNS/EIN) → MERGE (confidence: 1.0)
        b) If normalized names are IDENTICAL → MERGE (confidence: 0.98)
        c) If name similarity >90 AND same state → MERGE (confidence: 0.95)
        d) If name similarity >90 AND same NAICS code → MERGE (confidence: 0.90)
        e) If name similarity >85 (high confidence even without location) → MERGE (confidence: 0.88)
        f) If name similarity 70-85 AND different locations → FLAG FOR REVIEW
        g) If name similarity <70 → KEEP SEPARATE

        Args:
            dry_run: If True, don't actually merge, just report what would happen
            verbose: If True, log detailed comparison information

        Returns:
            ResolutionStats with merge statistics
        """
        self.stats = ResolutionStats()
        self.review_queue = []

        # Get all active entities
        entities = self.db.query(Entity).filter(
            Entity.merged_into_id.is_(None)
        ).all()

        self.stats.total_entities_start = len(entities)
        logger.info(f"Starting entity resolution with {len(entities)} entities")
        if verbose:
            logger.info("Verbose mode enabled - showing all comparisons")

        processed_pairs = set()

        for entity in entities:
            # Skip if already merged in this run
            if entity.merged_into_id is not None:
                continue

            matches = self.find_potential_duplicates(entity, threshold=70.0)

            for match in matches:
                # Create unique pair key to avoid processing same pair twice
                pair_key = tuple(sorted([match.entity_a.id, match.entity_b.id]))
                if pair_key in processed_pairs:
                    continue
                processed_pairs.add(pair_key)

                # Skip if either entity was already merged
                if match.entity_a.merged_into_id or match.entity_b.merged_into_id:
                    continue

                confidence = match.confidence

                # Get normalized names for comparison
                norm_a = self.normalize_name(match.entity_a.canonical_name)
                norm_b = self.normalize_name(match.entity_b.canonical_name)
                names_identical = (norm_a == norm_b and norm_a != "")

                if verbose:
                    logger.info(f"\n  Comparing:")
                    logger.info(f"    A: '{match.entity_a.canonical_name}' → '{norm_a}'")
                    logger.info(f"    B: '{match.entity_b.canonical_name}' → '{norm_b}'")
                    logger.info(f"    Similarity: {match.similarity_score:.1f}%")
                    logger.info(f"    Names identical after normalization: {names_identical}")
                    logger.info(f"    Shared location: {match.shared_location}")
                    logger.info(f"    Shared NAICS: {match.shared_naics}")
                    logger.info(f"    Shared identifiers: {match.shared_identifiers}")

                # Determine merge action based on decision tree
                if match.shared_identifiers:
                    # a) Identifier match → definitive merge
                    self.stats.identifier_matches += 1
                    if not dry_run:
                        canonical, duplicate = self.determine_canonical_entity(
                            match.entity_a, match.entity_b
                        )
                        self.merge_entities(
                            source=duplicate,
                            target=canonical,
                            confidence_score=confidence,
                            merge_reason=MergeReason.IDENTIFIER_MATCH,
                            details={"identifiers": match.shared_identifiers},
                        )
                    self.stats.high_confidence_merges += 1
                    logger.info(
                        f"[MERGE-IDENTIFIER] {match.entity_a.canonical_name} <-> "
                        f"{match.entity_b.canonical_name} ({match.match_reason})"
                    )

                elif names_identical and len(norm_a.split()) >= 2:
                    # b) Normalized names are IDENTICAL → merge (Corp vs Corporation case)
                    # Require at least 2 words to avoid over-matching (e.g., "aerospace")
                    self.stats.high_confidence_merges += 1
                    if not dry_run:
                        canonical, duplicate = self.determine_canonical_entity(
                            match.entity_a, match.entity_b
                        )
                        self.merge_entities(
                            source=duplicate,
                            target=canonical,
                            confidence_score=0.98,
                            merge_reason=MergeReason.NAME_SIMILARITY,
                            details={
                                "similarity": match.similarity_score,
                                "normalized_name": norm_a,
                                "reason": "identical_after_normalization"
                            },
                        )
                    logger.info(
                        f"[MERGE-IDENTICAL] {match.entity_a.canonical_name} <-> "
                        f"{match.entity_b.canonical_name} (normalized: '{norm_a}')"
                    )

                elif match.similarity_score >= 90 and match.shared_location:
                    # c) Name >90 AND same state → merge
                    self.stats.name_location_matches += 1
                    if not dry_run:
                        canonical, duplicate = self.determine_canonical_entity(
                            match.entity_a, match.entity_b
                        )
                        self.merge_entities(
                            source=duplicate,
                            target=canonical,
                            confidence_score=confidence,
                            merge_reason=MergeReason.NAME_AND_LOCATION,
                            details={"similarity": match.similarity_score},
                        )
                    self.stats.high_confidence_merges += 1
                    logger.info(
                        f"[MERGE-NAME+LOCATION] {match.entity_a.canonical_name} <-> "
                        f"{match.entity_b.canonical_name} (score: {match.similarity_score:.1f})"
                    )

                elif match.similarity_score >= 90 and match.shared_naics:
                    # d) Name >90 AND same NAICS → merge
                    self.stats.name_naics_matches += 1
                    if not dry_run:
                        canonical, duplicate = self.determine_canonical_entity(
                            match.entity_a, match.entity_b
                        )
                        self.merge_entities(
                            source=duplicate,
                            target=canonical,
                            confidence_score=confidence,
                            merge_reason=MergeReason.NAME_AND_NAICS,
                            details={"similarity": match.similarity_score},
                        )
                    self.stats.medium_confidence_merges += 1
                    logger.info(
                        f"[MERGE-NAME+NAICS] {match.entity_a.canonical_name} <-> "
                        f"{match.entity_b.canonical_name} (score: {match.similarity_score:.1f})"
                    )

                elif match.similarity_score >= 95:
                    # e) Name >95 → very high confidence merge even without location/NAICS
                    # But flag for review if they have DIFFERENT known locations
                    loc_a = self.extract_state(match.entity_a.headquarters_location)
                    loc_b = self.extract_state(match.entity_b.headquarters_location)

                    if loc_a and loc_b and loc_a != loc_b:
                        # Different known locations - flag for review
                        self.review_queue.append(match)
                        self.stats.flagged_for_review += 1
                        logger.info(
                            f"[REVIEW-DIFF-LOCATION] {match.entity_a.canonical_name} ({loc_a}) <-> "
                            f"{match.entity_b.canonical_name} ({loc_b}) (score: {match.similarity_score:.1f})"
                        )
                    else:
                        # No conflicting locations - merge
                        self.stats.high_confidence_merges += 1
                        if not dry_run:
                            canonical, duplicate = self.determine_canonical_entity(
                                match.entity_a, match.entity_b
                            )
                            self.merge_entities(
                                source=duplicate,
                                target=canonical,
                                confidence_score=0.95,
                                merge_reason=MergeReason.NAME_SIMILARITY,
                                details={"similarity": match.similarity_score},
                            )
                        logger.info(
                            f"[MERGE-HIGH-SIMILARITY] {match.entity_a.canonical_name} <-> "
                            f"{match.entity_b.canonical_name} (score: {match.similarity_score:.1f})"
                        )

                elif match.similarity_score >= 85:
                    # f) Name 85-95 → flag for review (need more signals)
                    self.review_queue.append(match)
                    self.stats.flagged_for_review += 1
                    logger.info(
                        f"[REVIEW-HIGH] {match.entity_a.canonical_name} <-> "
                        f"{match.entity_b.canonical_name} (score: {match.similarity_score:.1f})"
                    )

                elif match.similarity_score >= 70:
                    # f) Name 70-85 → flag for review
                    self.review_queue.append(match)
                    self.stats.flagged_for_review += 1
                    logger.info(
                        f"[REVIEW] {match.entity_a.canonical_name} <-> "
                        f"{match.entity_b.canonical_name} (score: {match.similarity_score:.1f})"
                    )

                # g) Name <70 → keep separate (no action needed)

        # Calculate final entity count
        final_count = self.db.query(Entity).filter(
            Entity.merged_into_id.is_(None)
        ).count()
        self.stats.total_entities_end = final_count

        # Log summary
        logger.info("=" * 60)
        logger.info("ENTITY RESOLUTION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Starting entities: {self.stats.total_entities_start}")
        logger.info(f"Final entities: {self.stats.total_entities_end}")
        logger.info(f"High-confidence merges (>0.9): {self.stats.high_confidence_merges}")
        logger.info(f"  - Identifier matches: {self.stats.identifier_matches}")
        logger.info(f"  - Name + location: {self.stats.name_location_matches}")
        logger.info(f"  - Name + NAICS: {self.stats.name_naics_matches}")
        logger.info(f"Medium-confidence merges (0.7-0.9): {self.stats.medium_confidence_merges}")
        logger.info(f"Flagged for review: {self.stats.flagged_for_review}")
        logger.info("=" * 60)

        return self.stats

    def export_review_queue(self, path: Optional[Path] = None) -> Path:
        """
        Export ambiguous matches to CSV for manual review.

        Columns:
        - entity_a_id, entity_a_name, entity_a_data
        - entity_b_id, entity_b_name, entity_b_data
        - similarity_score
        - suggested_action (merge/keep_separate)

        Returns:
            Path to the created CSV file
        """
        if path is None:
            path = settings.project_root / "data" / "review_queue.csv"

        path.parent.mkdir(parents=True, exist_ok=True)

        def entity_summary(e: Entity) -> str:
            """Create summary string for entity."""
            parts = []
            if e.cage_code:
                parts.append(f"CAGE:{e.cage_code}")
            if e.duns_number:
                parts.append(f"DUNS:{e.duns_number}")
            if e.headquarters_location:
                parts.append(f"Loc:{e.headquarters_location}")
            parts.append(f"Contracts:{len(e.contracts)}")
            parts.append(f"Funding:{len(e.funding_events)}")
            return " | ".join(parts)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "entity_a_id", "entity_a_name", "entity_a_data",
                "entity_b_id", "entity_b_name", "entity_b_data",
                "similarity_score", "match_reason", "suggested_action", "decision"
            ])

            for match in self.review_queue:
                suggested = "merge" if match.similarity_score >= 85 else "keep_separate"
                writer.writerow([
                    match.entity_a.id,
                    match.entity_a.canonical_name,
                    entity_summary(match.entity_a),
                    match.entity_b.id,
                    match.entity_b.canonical_name,
                    entity_summary(match.entity_b),
                    f"{match.similarity_score:.1f}",
                    match.match_reason,
                    suggested,
                    "",  # Decision column for manual input
                ])

        logger.info(f"Exported {len(self.review_queue)} items to {path}")
        return path

    def apply_manual_decisions(self, csv_path: Path) -> dict:
        """
        Apply manual merge decisions from reviewed CSV.

        Expected CSV format:
        - decision column should be "merge" or "keep_separate" or empty

        Returns:
            Dict with counts of actions taken
        """
        results = {"merged": 0, "kept_separate": 0, "skipped": 0}

        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                decision = row.get("decision", "").strip().lower()

                if not decision:
                    results["skipped"] += 1
                    continue

                entity_a_id = row["entity_a_id"]
                entity_b_id = row["entity_b_id"]

                # Fetch entities
                entity_a = self.db.query(Entity).filter(Entity.id == entity_a_id).first()
                entity_b = self.db.query(Entity).filter(Entity.id == entity_b_id).first()

                if not entity_a or not entity_b:
                    logger.warning(f"Entity not found: {entity_a_id} or {entity_b_id}")
                    results["skipped"] += 1
                    continue

                # Skip if either is already merged
                if entity_a.merged_into_id or entity_b.merged_into_id:
                    logger.warning(f"Entity already merged: {entity_a_id} or {entity_b_id}")
                    results["skipped"] += 1
                    continue

                if decision == "merge":
                    canonical, duplicate = self.determine_canonical_entity(entity_a, entity_b)
                    self.merge_entities(
                        source=duplicate,
                        target=canonical,
                        confidence_score=float(row.get("similarity_score", 0)) / 100.0,
                        merge_reason=MergeReason.MANUAL,
                        details={"csv_row": row},
                    )
                    results["merged"] += 1
                    logger.info(f"[MANUAL MERGE] {entity_a.canonical_name} <-> {entity_b.canonical_name}")

                elif decision == "keep_separate":
                    results["kept_separate"] += 1
                    logger.info(f"[KEEP SEPARATE] {entity_a.canonical_name} <-> {entity_b.canonical_name}")

                else:
                    results["skipped"] += 1

        logger.info(f"Manual decisions applied: {results}")
        return results

    def get_merge_history(self, entity_id: str) -> list[EntityMerge]:
        """Get merge history for an entity."""
        return self.db.query(EntityMerge).filter(
            or_(
                EntityMerge.source_entity_id == entity_id,
                EntityMerge.target_entity_id == entity_id
            )
        ).order_by(EntityMerge.created_at.desc()).all()
