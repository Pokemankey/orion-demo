"""
ORION Pipeline — entry point.
Usage: python main.py --submission <path-to-submission.json>
"""
import argparse
import logging
import sys
import uuid
from pathlib import Path

import structlog
from dotenv import load_dotenv

# Load .env so local runs have ANTHROPIC_API_KEY (and optional REVIEW_API_URL)
# without a manual export. Under Docker these come from env_file instead, where
# this call is a harmless no-op. Must run before any stage reads the environment.
load_dotenv()

from stages import ingest, parse_chunk, extract, assess, score, authorize, questions, emit


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

class _Tee:
    """
    Fan a single structlog stream out to several file-like sinks.
    Used so every JSON log line lands on both stdout and the per-run file
    without configuring two separate loggers.
    """

    def __init__(self, *sinks):
        self._sinks = sinks

    def write(self, data: str) -> None:
        for sink in self._sinks:
            sink.write(data)

    def flush(self) -> None:
        for sink in self._sinks:
            sink.flush()


def _configure_logging(run_id: str) -> None:
    """
    Emits one structured-JSON log stream to two sinks:
      - stdout: the serverless-native audit channel. In production the platform
                log driver (CloudWatch Logs / Cloud Logging) captures stdout
                automatically; run_id is on every line for per-submission filtering.
      - File:   output/traces/<run_id>.jsonl — a durable per-run trace for local
                inspection. In production this artifact would be written to object
                storage via the storage layer instead of local disk.
    """
    trace_dir = Path("output") / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{run_id}.jsonl"

    trace_file = open(trace_path, "w", encoding="utf-8")  # noqa: WPS515

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=_Tee(sys.stdout, trace_file)),
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(submission_path: str) -> None:
    run_id = str(uuid.uuid4())[:8]   # short ID — readable in logs

    _configure_logging(run_id)
    log = structlog.get_logger()

    log.info("pipeline_start", run_id=run_id, submission=submission_path)

    try:
        # Stage 1 — load and validate the submission JSON
        submission = ingest.run(submission_path, run_id)

        # Stage 2 — parse documents into text chunks
        chunks = parse_chunk.run(submission, run_id)

        # Stage 3 — extract signals from chunks, merge per dimension
        signals = extract.run(chunks, run_id)

        # Stage 4 — score each dimension 1–5 with Sonnet
        dimension_scores = assess.run(signals, run_id)

        # Stage 5 — compute weighted composite score (deterministic)
        composite = score.run(dimension_scores, run_id)

        # Stage 6 — determine authorization level + write rationale
        level, rationale = authorize.run(dimension_scores, composite, run_id)

        # Stage 7 — generate follow-up questions for weak/missing dimensions
        follow_ups = questions.run(dimension_scores, run_id)

        # Stage 8 — assemble payload, write locally, POST to review API
        payload = emit.run(
            submission=submission,
            dimension_scores=dimension_scores,
            composite=composite,
            level=level,
            rationale=rationale,
            questions=follow_ups,
            run_id=run_id,
        )

        log.info(
            "pipeline_complete",
            run_id=run_id,
            authorization_level=payload.authorization_level.value,
            composite_score=payload.composite_score,
            follow_up_count=len(payload.follow_up_questions),
        )

        print(f"\n{'='*60}")
        print(f"  Run ID:              {run_id}")
        print(f"  Firm:                {payload.firm_name}")
        print(f"  Composite score:     {payload.composite_score:.2f} / 5.00")
        print(f"  Authorization level: {payload.authorization_level.value}")
        print(f"  Follow-up questions: {len(payload.follow_up_questions)}")
        print(f"  Result saved to:     output/{run_id}.json")
        print(f"  Trace log at:        output/traces/{run_id}.jsonl")
        print(f"{'='*60}\n")

    except (FileNotFoundError, ValueError) as e:
        log.error("pipeline_failed", run_id=run_id, error=str(e))
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ORION authorization pipeline")
    parser.add_argument(
        "--submission",
        required=True,
        help="Path to the submission JSON file",
    )
    args = parser.parse_args()
    run_pipeline(args.submission)


if __name__ == "__main__":
    main()
