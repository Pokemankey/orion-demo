import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import structlog

from models import (
    AuthorizationLevel,
    DimensionScore,
    FollowUpQuestion,
    ReviewerPayload,
    Submission,
)

log = structlog.get_logger()

OUTPUT_DIR = Path("output")


def run(
    submission: Submission,
    dimension_scores: list[DimensionScore],
    composite: float,
    level: AuthorizationLevel,
    rationale: str,
    questions: list[FollowUpQuestion],
    run_id: str,
) -> ReviewerPayload:
    """
    Stage 8 — EMIT
    Assemble and validate the ReviewerPayload, write it locally, POST to review API.
    """
    payload = ReviewerPayload(
        run_id=run_id,
        applicant_id=submission.applicant_id,
        firm_name=submission.firm_name,
        dimension_scores=dimension_scores,
        composite_score=composite,
        authorization_level=level,
        authorization_rationale=rationale,
        follow_up_questions=questions,
        metadata={
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "document_count": len(submission.documents),
            "declared_activities": submission.declared_activities,
        },
    )

    _write_local(payload, run_id)
    _post_to_api(payload, run_id)

    log.info(
        "emit_complete",
        run_id=run_id,
        applicant_id=submission.applicant_id,
        authorization_level=level.value,
        composite_score=composite,
    )

    return payload


def _write_local(payload: ReviewerPayload, run_id: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{run_id}.json"
    out_path.write_text(
        payload.model_dump_json(indent=2),
        encoding="utf-8",
    )
    log.info("payload_written", run_id=run_id, path=str(out_path))


def _post_to_api(payload: ReviewerPayload, run_id: str) -> None:
    url = os.environ.get("REVIEW_API_URL", "http://localhost:8000/assessments")

    try:
        response = httpx.post(
            url,
            content=payload.model_dump_json(),
            headers={"Content-Type": "application/json"},
            timeout=10.0,
        )
        response.raise_for_status()
        log.info("api_post_success", run_id=run_id, status=response.status_code, url=url)
    except httpx.HTTPStatusError as e:
        log.error("api_post_http_error", run_id=run_id, status=e.response.status_code, url=url)
    except httpx.RequestError as e:
        log.warning("api_post_failed", run_id=run_id, url=url, error=str(e))
