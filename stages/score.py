import structlog

from models import DimensionScore, RiskDimension

log = structlog.get_logger()

# Weights must sum to 1.0
# Higher weight = more influence on the composite score
DIMENSION_WEIGHTS: dict[RiskDimension, float] = {
    RiskDimension.FINANCIAL_SOUNDNESS:    0.25,
    RiskDimension.GOVERNANCE:             0.20,
    RiskDimension.COMPLIANCE:             0.20,
    RiskDimension.OPERATIONAL_RESILIENCE: 0.15,
    RiskDimension.CYBERSECURITY:          0.10,
    RiskDimension.BUSINESS_MODEL:         0.10,
}


def run(dimension_scores: list[DimensionScore], run_id: str) -> float:
    """
    Stage 5 — SCORE
    Compute a weighted composite score from all dimension scores.
    Returns a float in [1.0, 5.0].
    """
    assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

    scores_by_dim = {ds.dimension: ds.score for ds in dimension_scores}

    composite = sum(
        scores_by_dim[dim] * weight
        for dim, weight in DIMENSION_WEIGHTS.items()
    )

    log.info(
        "composite_score",
        run_id=run_id,
        composite=round(composite, 3),
        breakdown={dim.value: scores_by_dim[dim] for dim in RiskDimension},
    )

    return round(composite, 3)
