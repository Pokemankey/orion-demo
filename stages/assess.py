import structlog
from pydantic import ValidationError

import llm
from models import DimensionScore, ExtractedSignal, RiskDimension

log = structlog.get_logger()

DIMENSION_DESCRIPTIONS = {
    RiskDimension.FINANCIAL_SOUNDNESS:    "capital ratios, liquidity, leverage, financial stability indicators",
    RiskDimension.GOVERNANCE:             "board composition, ownership structure, conflicts of interest, management quality",
    RiskDimension.OPERATIONAL_RESILIENCE: "BCP/DR plans, SLAs, incident history, operational continuity measures",
    RiskDimension.CYBERSECURITY:          "security certifications, controls, breach history, technology risk",
    RiskDimension.COMPLIANCE:             "regulatory violations, sanctions, AML/KYC procedures, regulatory history",
    RiskDimension.BUSINESS_MODEL:         "nature of activities, systemic exposure, revenue sources, client types",
}

_ASSESS_SYSTEM = """You are a senior regulatory risk analyst at ORION, a public financial authority.
Your task is to score an applicant firm on a specific risk dimension based on extracted evidence.
Be conservative: when evidence is ambiguous or missing, score lower.
Respond with raw JSON only. No explanation, no markdown."""

_RUBRIC = """Scoring rubric (1–5):
5 — Very low risk: strong, consistent evidence of sound controls and compliance
4 — Low risk: adequate evidence with only minor gaps
3 — Moderate risk: mixed evidence, some concerns requiring monitoring
2 — High risk: significant concerns, weak or incomplete controls
1 — Very high risk: critical deficiencies, major red flags, or near-total absence of evidence"""


def run(
    signals_by_dimension: dict[RiskDimension, list[ExtractedSignal]],
    run_id: str,
) -> list[DimensionScore]:
    """
    Stage 4 — ASSESS
    Score each risk dimension 1–5 using Sonnet.
    Dimensions with no signals are scored 1 (absence of evidence is itself a risk signal).
    """
    scores: list[DimensionScore] = []

    for dimension in RiskDimension:
        signals = signals_by_dimension.get(dimension, [])
        score = _score_dimension(dimension, signals, run_id)
        scores.append(score)
        log.info(
            "dimension_scored",
            run_id=run_id,
            dimension=dimension.value,
            score=score.score,
        )

    return scores


def _score_dimension(
    dimension: RiskDimension,
    signals: list[ExtractedSignal],
    run_id: str,
) -> DimensionScore:
    """Ask Sonnet to score one dimension based on its signals."""
    if signals:
        evidence_text = "\n".join(f'- "{s.fact}" (source: {s.source_path}, page {s.page})' for s in signals)
    else:
        evidence_text = "No evidence found for this dimension in the submitted documents."

    prompt = f"""Dimension: {dimension.value}
Covers: {DIMENSION_DESCRIPTIONS[dimension]}

{_RUBRIC}

Evidence extracted from the submission:
{evidence_text}

Score this dimension and explain your reasoning. Reference specific facts from the evidence.
If no evidence was found, score 1 and note that information is missing.

Respond with this JSON object:
{{
  "score": <integer 1–5>,
  "rationale": "<2–4 sentences explaining the score, referencing specific evidence>"
}}"""

    try:
        raw = llm.sonnet_json(system=_ASSESS_SYSTEM, prompt=prompt, run_id=run_id, stage=f"assess_{dimension.value}")
    except Exception as e:
        log.warning("assessment_failed", run_id=run_id, dimension=dimension.value, error=str(e))
        return DimensionScore(
            dimension=dimension,
            score=1,
            rationale=f"Assessment failed due to an error: {e}",
            signals_used=signals,
        )

    try:
        return DimensionScore(
            dimension=dimension,
            score=int(raw["score"]),
            rationale=raw["rationale"],
            signals_used=signals,
        )
    except (KeyError, ValueError, ValidationError) as e:
        log.warning("assessment_parse_failed", run_id=run_id, dimension=dimension.value, error=str(e))
        return DimensionScore(
            dimension=dimension,
            score=1,
            rationale="Assessment response could not be parsed.",
            signals_used=signals,
        )
