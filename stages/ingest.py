import json
from pathlib import Path

import structlog
from pydantic import ValidationError

import storage
from models import Submission

log = structlog.get_logger()


def run(submission_path: str, run_id: str) -> Submission:
    """
    Stage 1 — INGEST
    Load and validate the submission JSON. Verify all referenced documents exist.
    In production this would download files from object storage; here we read from disk.
    """
    path = Path(submission_path)

    if not path.exists():
        raise FileNotFoundError(f"Submission file not found: {submission_path}")

    raw = json.loads(path.read_text(encoding="utf-8"))

    try:
        submission = Submission.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"Submission JSON failed schema validation:\n{e}") from e

    # Verify every referenced document exists before we go any further.
    # storage.exists() resolves the URI against whichever backend is configured
    # (local filesystem in the demo, object storage in production).
    missing = [doc.path for doc in submission.documents if not storage.exists(doc.path)]
    if missing:
        raise FileNotFoundError(f"Referenced documents not found: {missing}")

    log.info(
        "ingest_complete",
        run_id=run_id,
        applicant_id=submission.applicant_id,
        firm_name=submission.firm_name,
        document_count=len(submission.documents),
    )

    return submission
