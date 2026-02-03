"""
Entity matching strategies for resolution.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from processing.models import Entity, EntityType


class MatchType(Enum):
    """Type of match found."""
    EXACT_IDENTIFIER = "exact_identifier"  # CAGE, DUNS, or EIN match
    FUZZY_NAME = "fuzzy_name"              # Name similarity match
    COMBINED = "combined"                   # Multiple signals combined
    NO_MATCH = "no_match"


@dataclass
class MatchResult:
    """Result of an entity matching attempt."""
    entity: Optional[Entity] = None
    match_type: MatchType = MatchType.NO_MATCH
    confidence: float = 0.0
    matched_on: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def is_match(self) -> bool:
        return self.entity is not None and self.confidence > 0

    def __repr__(self) -> str:
        if self.entity:
            return f"<MatchResult({self.entity.canonical_name}, {self.match_type.value}, conf={self.confidence:.2f})>"
        return "<MatchResult(no match)>"


class IdentifierMatcher:
    """
    Matches entities based on authoritative identifiers.

    Priority order:
    1. CAGE code - DoD-specific, highly reliable
    2. DUNS number - Universal business identifier
    3. EIN - Tax ID, less commonly available
    """

    def __init__(self, db: Session):
        self.db = db

    def match(
        self,
        cage_code: Optional[str] = None,
        duns_number: Optional[str] = None,
        ein: Optional[str] = None,
    ) -> MatchResult:
        """
        Find entity by identifier match.

        Returns match with confidence 1.0 for identifier matches (authoritative).
        """
        # Normalize inputs
        cage_code = self._normalize_cage(cage_code)
        duns_number = self._normalize_duns(duns_number)
        ein = self._normalize_ein(ein)

        matched_on = []

        # Try CAGE code first (most specific for defense)
        if cage_code:
            entity = self.db.query(Entity).filter(Entity.cage_code == cage_code).first()
            if entity:
                return MatchResult(
                    entity=entity,
                    match_type=MatchType.EXACT_IDENTIFIER,
                    confidence=1.0,
                    matched_on=["cage_code"],
                    details={"cage_code": cage_code},
                )

        # Try DUNS number
        if duns_number:
            entity = self.db.query(Entity).filter(Entity.duns_number == duns_number).first()
            if entity:
                return MatchResult(
                    entity=entity,
                    match_type=MatchType.EXACT_IDENTIFIER,
                    confidence=1.0,
                    matched_on=["duns_number"],
                    details={"duns_number": duns_number},
                )

        # Try EIN
        if ein:
            entity = self.db.query(Entity).filter(Entity.ein == ein).first()
            if entity:
                return MatchResult(
                    entity=entity,
                    match_type=MatchType.EXACT_IDENTIFIER,
                    confidence=1.0,
                    matched_on=["ein"],
                    details={"ein": ein},
                )

        return MatchResult()

    def _normalize_cage(self, code: Optional[str]) -> Optional[str]:
        """Normalize CAGE code (5 alphanumeric characters)."""
        if not code:
            return None
        code = re.sub(r"[^A-Za-z0-9]", "", code.upper())
        return code if len(code) == 5 else None

    def _normalize_duns(self, number: Optional[str]) -> Optional[str]:
        """Normalize DUNS number (9 digits, sometimes with dashes)."""
        if not number:
            return None
        number = re.sub(r"[^0-9]", "", number)
        return number if len(number) == 9 else None

    def _normalize_ein(self, ein: Optional[str]) -> Optional[str]:
        """Normalize EIN (9 digits, XX-XXXXXXX format)."""
        if not ein:
            return None
        ein = re.sub(r"[^0-9]", "", ein)
        return ein if len(ein) == 9 else None


class FuzzyNameMatcher:
    """
    Matches entities using fuzzy string matching on names.

    Uses rapidfuzz for high-performance fuzzy matching with multiple algorithms:
    - Token sort ratio: Handles word reordering
    - Token set ratio: Handles partial matches
    - Weighted ratio: Standard similarity
    """

    # Common suffixes to normalize
    CORPORATE_SUFFIXES = [
        r"\bInc\.?$", r"\bIncorporated$", r"\bCorp\.?$", r"\bCorporation$",
        r"\bLLC$", r"\bL\.L\.C\.?$", r"\bLtd\.?$", r"\bLimited$",
        r"\bLLP$", r"\bL\.L\.P\.?$", r"\bLP$", r"\bL\.P\.?$",
        r"\bCo\.?$", r"\bCompany$", r"\bPC$", r"\bP\.C\.?$",
        r",\s*$",  # Trailing commas
    ]

    def __init__(self, db: Session, threshold: int = 85):
        """
        Initialize fuzzy matcher.

        Args:
            db: Database session
            threshold: Minimum score (0-100) to consider a match
        """
        self.db = db
        self.threshold = threshold
        self._entity_cache: Optional[list[tuple[str, str]]] = None

    def match(
        self,
        name: str,
        entity_type: Optional[str] = None,
        location_hint: Optional[str] = None,
    ) -> MatchResult:
        """
        Find best matching entity by name.

        Checks both canonical names and all name variants.

        Args:
            name: Entity name to match
            entity_type: Optional filter by entity type
            location_hint: Optional location to boost matches

        Returns:
            MatchResult with best match and confidence score
        """
        if not name or len(name.strip()) < 2:
            return MatchResult()

        normalized_name = self._normalize_name(name)

        # Find best match considering all name variants
        entity_id, score = self._find_best_match_with_variants(
            normalized_name, entity_type
        )

        if not entity_id or score < self.threshold:
            return MatchResult()

        # Get the actual entity
        entity = self.db.query(Entity).filter(Entity.id == entity_id).first()
        if not entity:
            return MatchResult()

        # Boost score if location matches
        confidence = score / 100.0
        if location_hint and entity.headquarters_location:
            if self._locations_match(location_hint, entity.headquarters_location):
                confidence = min(1.0, confidence + 0.05)

        return MatchResult(
            entity=entity,
            match_type=MatchType.FUZZY_NAME,
            confidence=confidence,
            matched_on=["name"],
            details={
                "input_name": name,
                "normalized_name": normalized_name,
                "matched_name": entity.canonical_name,
                "raw_score": score,
            },
        )

    def match_against_variants(self, name: str, entity: Entity) -> float:
        """
        Check how well a name matches an entity's name variants.

        Returns best match score (0-100).
        """
        normalized = self._normalize_name(name)
        names_to_check = [self._normalize_name(entity.canonical_name)]

        if entity.name_variants:
            names_to_check.extend(
                self._normalize_name(v) for v in entity.name_variants
            )

        best_score = 0
        for variant in names_to_check:
            score = self._combined_scorer(normalized, variant)
            best_score = max(best_score, score)

        return best_score

    def _get_candidates(self, entity_type: Optional[str] = None) -> dict[str, str]:
        """
        Get candidate entities for matching.

        Returns dict mapping entity_id -> normalized name (canonical + best variant).
        Each entity is represented once with its canonical name for matching,
        but match_against_variants is used for detailed scoring.
        """
        query = self.db.query(Entity.id, Entity.canonical_name, Entity.name_variants)
        if entity_type:
            # Convert string to EntityType enum for comparison
            try:
                entity_type_enum = EntityType(entity_type)
                query = query.filter(Entity.entity_type == entity_type_enum)
            except ValueError:
                pass  # Invalid entity type, don't filter

        candidates = {}
        for entity_id, canonical_name, name_variants in query.all():
            # Store canonical name
            candidates[entity_id] = self._normalize_name(canonical_name)

        return candidates

    def _find_best_match_with_variants(
        self,
        normalized_name: str,
        entity_type: Optional[str] = None,
    ) -> tuple[Optional[str], float]:
        """
        Find the best matching entity considering all name variants.

        Returns (entity_id, score) tuple.
        """
        query = self.db.query(Entity)
        if entity_type:
            # Convert string to EntityType enum for comparison
            try:
                entity_type_enum = EntityType(entity_type)
                query = query.filter(Entity.entity_type == entity_type_enum)
            except ValueError:
                pass  # Invalid entity type, don't filter

        best_entity_id = None
        best_score = 0.0

        for entity in query.all():
            # Check canonical name
            canonical_normalized = self._normalize_name(entity.canonical_name)
            score = self._combined_scorer(normalized_name, canonical_normalized)

            # Check all variants and keep best score
            if entity.name_variants:
                for variant in entity.name_variants:
                    variant_normalized = self._normalize_name(variant)
                    variant_score = self._combined_scorer(normalized_name, variant_normalized)
                    score = max(score, variant_score)

            if score > best_score:
                best_score = score
                best_entity_id = entity.id

        return best_entity_id, best_score

    def _normalize_name(self, name: str) -> str:
        """
        Normalize company name for comparison.

        - Uppercase
        - Remove corporate suffixes
        - Normalize whitespace
        - Remove special characters
        """
        if not name:
            return ""

        normalized = name.upper().strip()

        # Remove corporate suffixes
        for pattern in self.CORPORATE_SUFFIXES:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)

        # Normalize whitespace and special chars
        normalized = re.sub(r"[^\w\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    def _combined_scorer(self, s1: str, s2: str, **kwargs) -> float:
        """
        Combined scoring using multiple fuzzy algorithms.

        Weights:
        - Token sort ratio: 40% (handles word reordering)
        - Token set ratio: 40% (handles partial matches)
        - Ratio: 20% (standard similarity)

        Note: **kwargs accepts score_cutoff and other params from rapidfuzz.
        """
        token_sort = fuzz.token_sort_ratio(s1, s2)
        token_set = fuzz.token_set_ratio(s1, s2)
        ratio = fuzz.ratio(s1, s2)

        return (token_sort * 0.4) + (token_set * 0.4) + (ratio * 0.2)

    def _locations_match(self, loc1: str, loc2: str) -> bool:
        """Check if two locations are likely the same."""
        # Simple state/city matching
        loc1_parts = set(loc1.upper().replace(",", " ").split())
        loc2_parts = set(loc2.upper().replace(",", " ").split())

        # Check for common elements (city or state)
        common = loc1_parts & loc2_parts
        return len(common) >= 1
