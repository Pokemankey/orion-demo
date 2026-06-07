import structlog
from pydantic import ValidationError

import llm
from models import DimensionScore, FollowUpQuestion, RiskDimension

log = structlog.get_logger()

# Generate questions for dimensions that scored at or below this threshold
QUESTION_THRESHOLD = 3

_QUESTIONS_SYSTEM = """You are a regulatory analyst at ORION preparing a follow-up request for an applicant firm.
Write specific, answerable questions that would resolve gaps in the submitted evidence.
Questions should reference what was missing or inconsistent — not generic checklists.
Respond with raw JSON only. No explanation, no markdown."""


def run(dimension_scores: list[DimensionScore], run_id: str) -> list[FollowUpQuestion]:
    """
    Stage 7 — QUESTIONS
    For each dimension scoring <= QUESTION_THRESHOLD or with no signals,
    ask Sonnet to generate targeted follow-up questions.
    """
    questions: list[FollowUpQuestion] = []

    for ds in dimension_scores:
        no_evidence = len(ds.signals_used) == 0
        low_score = ds.score <= QUESTION_THRESHOLD

        if not (no_evidence or low_score):
            continue

        generated = _generate_questions(ds, run_id)
        questions.extend(generated)
        log.info(
            "questions_generated",
            run_id=run_id,
            dimension=ds.dimension.value,
            count=len(generated),
        )

    log.info("questions_complete", run_id=run_id, total=len(questions))
    return questions


def _generate_questions(ds: DimensionScore, run_id: str) -> list[FollowUpQuestion]:
    if ds.signals_used:
        evidence_text = "\n".join(f'- "{s.fact}"' for s in ds.signals_used)
    else:
        evidence_text = "No evidence was found for this dimension in the submission."

    prompt = f"""Dimension: {ds.dimension.value}
Score: {ds.score}/5
Assessment: {ds.rationale}

Evidence found:
{evidence_text}

Generate 1–3 specific follow-up questions to resolve the gaps or weaknesses identified above.
Each question should be directly answerable by the applicant firm with documentation.

Respond with a JSON array:
[
  {{
    "dimension": "{ds.dimension.value}",
    "question": "<specific question>",
    "reason": "<one sentence: what gap or inconsistency this resolves>"
  }}
]"""

    try:
        raw = llm.sonnet_json(
            system=_QUESTIONS_SYSTEM,
            prompt=prompt,
            run_id=run_id,
            stage=f"questions_{ds.dimension.value}",
        )
    except Exception as e:
        log.warning("question_generation_failed", run_id=run_id, dimension=ds.dimension.value, error=str(e))
        return []

    questions = []
    for item in raw if isinstance(raw, list) else []:
        try:
            questions.append(FollowUpQuestion.model_validate(item))
        except ValidationError:
            pass

    return questions
