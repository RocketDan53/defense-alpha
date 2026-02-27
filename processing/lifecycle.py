"""
Canonical lifecycle stage classification.

Used by both aperture_query.py (deal briefs) and snapshot_entities.py (daily snapshots).
Any changes here affect both systems - that's the point.
"""

from datetime import date


def classify_lifecycle(
    sbir_p1_count: int = 0,
    sbir_p2_count: int = 0,
    sbir_p3_count: int = 0,
    contract_count: int = 0,
    max_contract_value: float = 0.0,
    regd_count: int = 0,
    regd_total: float = 0.0,
    latest_activity_date: date | str | None = None,
) -> str:
    """
    Determine lifecycle stage from entity metrics.

    Stages (ordered by maturity):
      - early: No government or private traction
      - funded: Private capital raised but no SBIR
      - r_and_d: SBIR Phase I only
      - prototype: Phase II achieved or small contracts
      - growth: Multiple contracts + private capital
      - production: Phase III or large production contracts (>$1M)
      - scaling: Production contracts + continued Phase II/III + capital

    Returns lowercase stage string.
    """
    total_sbirs = sbir_p1_count + sbir_p2_count + sbir_p3_count
    has_production = max_contract_value > 1_000_000

    if has_production and total_sbirs > 2 and regd_total > 0:
        return "scaling"
    if sbir_p3_count > 0 or has_production:
        return "production"
    if contract_count > 1 and regd_total > 0:
        return "growth"
    if sbir_p2_count > 0 or (contract_count > 0 and max_contract_value <= 1_000_000):
        return "prototype"
    if total_sbirs > 0:
        return "r_and_d"
    if regd_count > 0:
        return "funded"
    return "early"
