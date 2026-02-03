"""
Hybrid Entity Resolver

Combines identifier matching and fuzzy name matching with configurable thresholds.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from config.logging import logger
from config.settings import settings
from processing.models import Entity, EntityType
from processing.entity_resolution.matchers import (
    IdentifierMatcher,
    FuzzyNameMatcher,
    MatchResult,
    MatchType,
)


@dataclass
class ResolverConfig:
    """Configuration for entity resolution."""
    # Minimum confidence to auto-accept a match
    auto_accept_threshold: float = 0.90

    # Minimum confidence to consider a match (below this = no match)
    match_threshold: float = 0.70

    # Threshold for flagging as "needs review"
    review_threshold: float = 0.85

    # Fuzzy matching threshold (0-100 for rapidfuzz)
    fuzzy_threshold: int = 85

    # Whether to create new entities for non-matches
    create_if_not_found: bool = True


class EntityResolver:
    """
    Hybrid entity resolver combining multiple matching strategies.

    Resolution strategy:
    1. Try identifier match first (CAGE, DUNS, EIN) - authoritative
    2. If no identifier match, try fuzzy name matching
    3. Boost confidence with contextual signals (location, tags)
    4. Return match with confidence score

    Usage:
        resolver = EntityResolver(db)
        result = resolver.resolve(
            name="Anduril Industries, Inc.",
            cage_code="8GNK6",
        )
        if result.is_match:
            entity = result.entity
    """

    def __init__(
        self,
        db: Session,
        config: Optional[ResolverConfig] = None,
    ):
        self.db = db
        self.config = config or ResolverConfig(
            fuzzy_threshold=settings.FUZZY_MATCH_THRESHOLD
        )
        self.identifier_matcher = IdentifierMatcher(db)
        self.fuzzy_matcher = FuzzyNameMatcher(db, self.config.fuzzy_threshold)

    def resolve(
        self,
        name: str,
        cage_code: Optional[str] = None,
        duns_number: Optional[str] = None,
        ein: Optional[str] = None,
        entity_type: Optional[EntityType] = None,
        location: Optional[str] = None,
        technology_tags: Optional[list[str]] = None,
    ) -> MatchResult:
        """
        Resolve an entity using hybrid matching.

        Args:
            name: Entity name (required)
            cage_code: CAGE code if known
            duns_number: DUNS number if known
            ein: EIN if known
            entity_type: Expected entity type
            location: Location hint for disambiguation
            technology_tags: Technology tags for context

        Returns:
            MatchResult with matched entity and confidence
        """
        logger.debug(f"Resolving entity: {name}")

        # Step 1: Try identifier match (authoritative)
        if cage_code or duns_number or ein:
            id_result = self.identifier_matcher.match(
                cage_code=cage_code,
                duns_number=duns_number,
                ein=ein,
            )
            if id_result.is_match:
                logger.debug(f"Identifier match found: {id_result}")

                # Cross-validate with name if we have a name
                if name:
                    name_score = self.fuzzy_matcher.match_against_variants(
                        name, id_result.entity
                    )
                    if name_score < 50:
                        # Name doesn't match identifier - flag for review
                        logger.warning(
                            f"Identifier matched but name mismatch: "
                            f"'{name}' vs '{id_result.entity.canonical_name}' "
                            f"(score: {name_score})"
                        )
                        id_result.details["name_mismatch"] = True
                        id_result.details["name_score"] = name_score

                return id_result

        # Step 2: Try fuzzy name match
        if name:
            entity_type_str = entity_type.value if entity_type else None
            fuzzy_result = self.fuzzy_matcher.match(
                name=name,
                entity_type=entity_type_str,
                location_hint=location,
            )

            if fuzzy_result.is_match:
                # Apply contextual boosts
                confidence = self._apply_contextual_boosts(
                    fuzzy_result,
                    location=location,
                    technology_tags=technology_tags,
                )
                fuzzy_result.confidence = confidence
                fuzzy_result.details["boosted_confidence"] = confidence

                # Only return if above threshold
                if confidence >= self.config.match_threshold:
                    logger.debug(f"Fuzzy match found: {fuzzy_result}")
                    return fuzzy_result

        # No match found
        logger.debug(f"No match found for: {name}")
        return MatchResult()

    def resolve_or_create(
        self,
        name: str,
        entity_type: EntityType,
        cage_code: Optional[str] = None,
        duns_number: Optional[str] = None,
        ein: Optional[str] = None,
        location: Optional[str] = None,
        technology_tags: Optional[list[str]] = None,
        founded_date: Optional[date] = None,
    ) -> tuple[Entity, bool]:
        """
        Resolve entity or create new one if not found.

        Args:
            name: Entity name
            entity_type: Entity type
            ... other entity attributes

        Returns:
            Tuple of (entity, created) where created is True if new entity
        """
        result = self.resolve(
            name=name,
            cage_code=cage_code,
            duns_number=duns_number,
            ein=ein,
            entity_type=entity_type,
            location=location,
            technology_tags=technology_tags,
        )

        if result.is_match and result.confidence >= self.config.auto_accept_threshold:
            # High confidence match - return existing entity
            # Optionally update with new information
            self._update_entity_if_needed(
                result.entity,
                name=name,
                cage_code=cage_code,
                duns_number=duns_number,
                ein=ein,
                location=location,
                technology_tags=technology_tags,
            )
            return result.entity, False

        elif result.is_match and result.confidence >= self.config.match_threshold:
            # Medium confidence - log for potential review but use the match
            logger.info(
                f"Medium confidence match ({result.confidence:.2f}): "
                f"'{name}' -> '{result.entity.canonical_name}'"
            )
            return result.entity, False

        else:
            # No match or low confidence - create new entity
            if not self.config.create_if_not_found:
                raise ValueError(f"No match found for '{name}' and create disabled")

            entity = self._create_entity(
                name=name,
                entity_type=entity_type,
                cage_code=cage_code,
                duns_number=duns_number,
                ein=ein,
                location=location,
                technology_tags=technology_tags,
                founded_date=founded_date,
            )
            logger.info(f"Created new entity: {entity}")
            return entity, True

    def _apply_contextual_boosts(
        self,
        result: MatchResult,
        location: Optional[str] = None,
        technology_tags: Optional[list[str]] = None,
    ) -> float:
        """Apply contextual signal boosts to confidence score."""
        confidence = result.confidence
        entity = result.entity

        # Location match boost (+5%)
        if location and entity.headquarters_location:
            if self.fuzzy_matcher._locations_match(location, entity.headquarters_location):
                confidence = min(1.0, confidence + 0.05)
                result.matched_on.append("location")

        # Technology overlap boost (+3% per matching tag, max +10%)
        if technology_tags and entity.technology_tags:
            entity_tags = set(t.lower() for t in entity.technology_tags)
            input_tags = set(t.lower() for t in technology_tags)
            overlap = len(entity_tags & input_tags)
            if overlap > 0:
                boost = min(0.10, overlap * 0.03)
                confidence = min(1.0, confidence + boost)
                result.matched_on.append("technology_tags")

        return confidence

    def _update_entity_if_needed(
        self,
        entity: Entity,
        name: str,
        cage_code: Optional[str] = None,
        duns_number: Optional[str] = None,
        ein: Optional[str] = None,
        location: Optional[str] = None,
        technology_tags: Optional[list[str]] = None,
    ):
        """Update entity with new information if available."""
        updated = False

        # Add name variant if not already present
        normalized_name = self.fuzzy_matcher._normalize_name(name)
        canonical_normalized = self.fuzzy_matcher._normalize_name(entity.canonical_name)

        if normalized_name != canonical_normalized:
            variants = entity.name_variants or []
            existing_normalized = [
                self.fuzzy_matcher._normalize_name(v) for v in variants
            ]
            if normalized_name not in existing_normalized:
                variants.append(name)
                entity.name_variants = variants
                updated = True

        # Fill in missing identifiers
        if cage_code and not entity.cage_code:
            entity.cage_code = cage_code
            updated = True
        if duns_number and not entity.duns_number:
            entity.duns_number = duns_number
            updated = True
        if ein and not entity.ein:
            entity.ein = ein
            updated = True

        # Update location if missing
        if location and not entity.headquarters_location:
            entity.headquarters_location = location
            updated = True

        # Merge technology tags
        if technology_tags:
            existing_tags = set(entity.technology_tags or [])
            new_tags = set(technology_tags)
            merged = existing_tags | new_tags
            if merged != existing_tags:
                entity.technology_tags = list(merged)
                updated = True

        if updated:
            self.db.commit()
            logger.debug(f"Updated entity: {entity.canonical_name}")

    def _create_entity(
        self,
        name: str,
        entity_type: EntityType,
        cage_code: Optional[str] = None,
        duns_number: Optional[str] = None,
        ein: Optional[str] = None,
        location: Optional[str] = None,
        technology_tags: Optional[list[str]] = None,
        founded_date: Optional[date] = None,
    ) -> Entity:
        """Create a new entity."""
        entity = Entity(
            canonical_name=name,
            name_variants=[],
            entity_type=entity_type,
            cage_code=cage_code,
            duns_number=duns_number,
            ein=ein,
            headquarters_location=location,
            founded_date=founded_date,
            technology_tags=technology_tags or [],
        )
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity


class EntityMerger:
    """
    Merges duplicate entities and consolidates their data.
    """

    def __init__(self, db: Session):
        self.db = db

    def merge(self, primary: Entity, duplicate: Entity) -> Entity:
        """
        Merge duplicate entity into primary entity.

        - Transfers all relationships (contracts, funding, signals)
        - Merges name variants
        - Fills missing fields from duplicate
        - Deletes duplicate entity

        Args:
            primary: Entity to keep
            duplicate: Entity to merge and delete

        Returns:
            Updated primary entity
        """
        logger.info(
            f"Merging entity '{duplicate.canonical_name}' into '{primary.canonical_name}'"
        )

        # Merge name variants
        variants = set(primary.name_variants or [])
        variants.add(duplicate.canonical_name)
        variants.update(duplicate.name_variants or [])
        primary.name_variants = list(variants)

        # Fill missing identifiers
        if not primary.cage_code and duplicate.cage_code:
            primary.cage_code = duplicate.cage_code
        if not primary.duns_number and duplicate.duns_number:
            primary.duns_number = duplicate.duns_number
        if not primary.ein and duplicate.ein:
            primary.ein = duplicate.ein

        # Fill missing metadata
        if not primary.headquarters_location and duplicate.headquarters_location:
            primary.headquarters_location = duplicate.headquarters_location
        if not primary.founded_date and duplicate.founded_date:
            primary.founded_date = duplicate.founded_date

        # Merge technology tags
        primary_tags = set(primary.technology_tags or [])
        dup_tags = set(duplicate.technology_tags or [])
        primary.technology_tags = list(primary_tags | dup_tags)

        # Transfer relationships
        for funding in duplicate.funding_events:
            funding.entity_id = primary.id
        for contract in duplicate.contracts:
            contract.entity_id = primary.id
        for signal in duplicate.signals:
            signal.entity_id = primary.id

        # Delete duplicate
        self.db.delete(duplicate)
        self.db.commit()

        logger.info(f"Merge complete. Primary entity now has {len(primary.name_variants)} name variants")
        return primary

    def find_potential_duplicates(
        self,
        threshold: float = 0.85,
        limit: int = 100,
    ) -> list[tuple[Entity, Entity, float]]:
        """
        Find potential duplicate entities based on name similarity.

        Returns list of (entity1, entity2, similarity_score) tuples.
        """
        entities = self.db.query(Entity).all()
        fuzzy_matcher = FuzzyNameMatcher(self.db, int(threshold * 100))

        duplicates = []
        checked = set()

        for i, e1 in enumerate(entities):
            for e2 in entities[i + 1:]:
                pair_key = tuple(sorted([e1.id, e2.id]))
                if pair_key in checked:
                    continue
                checked.add(pair_key)

                # Check name similarity
                score = fuzzy_matcher.match_against_variants(
                    e1.canonical_name, e2
                ) / 100.0

                if score >= threshold:
                    # Also check if they share identifiers
                    if (e1.cage_code and e1.cage_code == e2.cage_code) or \
                       (e1.duns_number and e1.duns_number == e2.duns_number) or \
                       (e1.ein and e1.ein == e2.ein):
                        score = 1.0  # Definite duplicate

                    duplicates.append((e1, e2, score))

                if len(duplicates) >= limit:
                    break

            if len(duplicates) >= limit:
                break

        # Sort by score descending
        duplicates.sort(key=lambda x: x[2], reverse=True)
        return duplicates
