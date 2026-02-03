"""
Entity Resolution Module

Hybrid entity resolution combining:
- Identifier-based matching (CAGE, DUNS, EIN)
- Fuzzy name matching (rapidfuzz)
- Contextual signals (location, technology tags)
"""

from processing.entity_resolution.resolver import EntityResolver
from processing.entity_resolution.matchers import (
    IdentifierMatcher,
    FuzzyNameMatcher,
    MatchResult,
    MatchType,
)

__all__ = [
    "EntityResolver",
    "IdentifierMatcher",
    "FuzzyNameMatcher",
    "MatchResult",
    "MatchType",
]
