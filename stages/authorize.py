import structlog

import llm
from models import AuthorizationLevel, DimensionScore, RiskDimension

log = structlog.get_logger()

# Score thresholds for authorization levels (composite is in [1.0, 5.0])
THRESHOLDS = {
    AuthorizationLevel.FULL:        3.5,
    AuthorizationLevel.CONDITIONAL: 2.5,
    AuthorizationLevel.DEFERRED:    1.5,
    # below 1.5 → REJECTED
}

# Any dimension at or below this score triggers a hard downgrade
HARD_FAIL_SCORE = 1
HARD_FAIL_LEVEL = AuthorizationLevel.DEFERRED

_AUTHORIZE_SYSTEM = """You are a senior regulatory officer at ORION.
Write a concise authorization decision narrative for a human reviewer.
Be direct and factual. Reference specific risk dimensions.
Respond with raw JSON only. No explanation, no markdown."""


def run(
    dimension_scores: list[DimensionScore],
    composite: float,
    run_id: str,
) -> tuple[AuthorizationLevel, str]:
    """
    Stage 6 — AUTHORIZE
    Determine authorization level from composite score and hard-fail rules.
    Then ask Sonnet to write a rationale narrative for the reviewer.
    Returns (authorization_level, rationale_string).
    """
    level = _determine_level(dimension_scores, composite)

    log.info("authorization_level", run_id=run_id, level=level.value, composite=composite)

    rationale = _write_rationale(dimension_scores, composite, level, run_id)

    return level, rationale


def _determine_level(
    dimension_scores: list[DimensionScore],
    composite: float,
) -> AuthorizationLevel:
    # Hard fail: any dimension at score 1 caps the decision at DEFERRED
    hard_fails = [ds for ds in dimension_scores if ds.score <= HARD_FAIL_SCORE]
    if hard_fails:
        return HARD_FAIL_LEVEL

    # Otherwise map composite score to level
    if composite >= THRESHOLDS[AuthorizationLevel.FULL]:
        return AuthorizationLevel.FULL
    elif composite >= THRESHOLDS[AuthorizationLevel.CONDITIONAL]:
        return AuthorizationLevel.CONDITIONAL
    elif composite >= THRESHOLDS[AuthorizationLevel.DEFERRED]:
        return AuthorizationLevel.DEFERRED
    else:
        return AuthorizationLevel.REJECTED


def _write_rationale(
    dimension_scores: list[DimensionScore],
    composite: float,
    level: AuthorizationLevel,
    run_id: str,
) -> str:
    scores_text = "\n".join(
        f"- {ds.dimension.value}: {ds.score}/5 — {ds.rationale}"
        for ds in dimension_scores
    )

    prompt = f"""Authorization decision: {level.value}
Composite score: {composite:.2f} / 5.00

Dimension scores:
{scores_text}

Write a 3–5 sentence narrative for a human reviewer explaining this authorization decision.
Reference the most significant dimensions. If CONDITIONAL or DEFERRED, name what conditions or gaps must be resolved.

Respond with this JSON object:
{{
  "rationale": "<narrative text>"
}}"""

    try:
        raw = llm.sonnet_json(system=_AUTHORIZE_SYSTEM, prompt=prompt, run_id=run_id, stage="authorize")
        return raw["rationale"]
    except Exception as e:
        log.warning("rationale_generation_failed", run_id=run_id, error=str(e))
        return f"Authorization level {level.value} assigned based on composite score {composite:.2f}."
