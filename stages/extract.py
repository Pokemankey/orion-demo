import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import structlog
from pydantic import ValidationError

import llm
from models import DocumentChunk, ExtractedSignal, RiskDimension

log = structlog.get_logger()

# Per-chunk extraction is the only stage whose runtime scales with document
# size, so it is the bottleneck under a fixed serverless execution limit.
# The calls are I/O-bound (network round-trips to the LLM), so a thread pool
# collapses wall-clock time without needing async. Cap concurrency to stay
# within provider rate limits; override via EXTRACT_CONCURRENCY.
EXTRACT_CONCURRENCY = int(os.environ.get("EXTRACT_CONCURRENCY", "10"))

# Descriptions fed into the prompt so the model knows what each dimension covers
DIMENSION_DESCRIPTIONS = {
    RiskDimension.FINANCIAL_SOUNDNESS:    "capital ratios, liquidity, leverage, financial stability indicators",
    RiskDimension.GOVERNANCE:             "board composition, ownership structure, conflicts of interest, management quality",
    RiskDimension.OPERATIONAL_RESILIENCE: "BCP/DR plans, SLAs, incident history, operational continuity measures",
    RiskDimension.CYBERSECURITY:          "security certifications, controls, breach history, technology risk",
    RiskDimension.COMPLIANCE:             "regulatory violations, sanctions, AML/KYC procedures, regulatory history",
    RiskDimension.BUSINESS_MODEL:         "nature of activities, systemic exposure, revenue sources, client types",
}

_EXTRACT_SYSTEM = """You are a regulatory analyst extracting facts from financial authorization documents.
Your job is to identify facts that are relevant to specific risk dimensions.
Only extract facts that are explicitly stated — do not infer or speculate.
Respond with raw JSON only. No explanation, no markdown."""

_MERGE_SYSTEM = """You are a regulatory analyst consolidating extracted facts.
Your job is to deduplicate a list of facts for one risk dimension.
Keep all distinct facts. Remove only true duplicates or near-duplicates that state the same thing.
Respond with raw JSON only. No explanation, no markdown."""


def run(
    chunks: list[DocumentChunk],
    run_id: str,
) -> dict[RiskDimension, list[ExtractedSignal]]:
    """
    Stage 3 — EXTRACT
    Pass 1: extract raw signals from every chunk using Haiku.
    Pass 2: merge and deduplicate signals per dimension using Haiku.
    Returns a dict mapping each dimension to its deduplicated signal list.
    """
    # Pass 1 — extract from each chunk, in parallel.
    # Chunks are independent, so we fan out across a thread pool and gather.
    raw_signals: list[ExtractedSignal] = []
    if chunks:
        max_workers = min(EXTRACT_CONCURRENCY, len(chunks))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # executor.map preserves input order; ordering keeps runs reproducible
            for signals in pool.map(lambda c: _extract_chunk(c, run_id), chunks):
                raw_signals.extend(signals)

    log.info(
        "extraction_pass1_complete",
        run_id=run_id,
        raw_signal_count=len(raw_signals),
        chunk_count=len(chunks),
        concurrency=min(EXTRACT_CONCURRENCY, len(chunks)) if chunks else 0,
    )

    # Group by dimension before merging
    by_dimension: dict[RiskDimension, list[ExtractedSignal]] = defaultdict(list)
    for signal in raw_signals:
        by_dimension[signal.dimension].append(signal)

    # Pass 2 — merge/dedup per dimension
    merged: dict[RiskDimension, list[ExtractedSignal]] = {}
    for dimension in RiskDimension:
        signals = by_dimension.get(dimension, [])
        if not signals:
            merged[dimension] = []
            log.info("no_signals_found", run_id=run_id, dimension=dimension.value)
            continue
        merged[dimension] = _merge_signals(dimension, signals, run_id)

    total = sum(len(v) for v in merged.values())
    log.info("extraction_complete", run_id=run_id, merged_signal_count=total)
    return merged


def _extract_chunk(chunk: DocumentChunk, run_id: str) -> list[ExtractedSignal]:
    """Ask Haiku to extract all relevant signals from a single chunk."""
    dimension_list = "\n".join(
        f"- {dim.value}: {desc}" for dim, desc in DIMENSION_DESCRIPTIONS.items()
    )

    prompt = f"""Extract all facts relevant to the following risk dimensions from the document excerpt below.
For each fact, output one JSON object. Return a JSON array.
If no relevant facts are found, return an empty array [].

Risk dimensions:
{dimension_list}

Output format (JSON array):
[
  {{"dimension": "<dimension_value>", "fact": "<extracted fact in plain language>", "source_path": "{chunk.source_path}", "page": {chunk.page}}}
]

Document excerpt (source: {chunk.source_path}, page {chunk.page}):
---
{chunk.text}
---"""

    try:
        raw = llm.haiku_json(system=_EXTRACT_SYSTEM, prompt=prompt, run_id=run_id, stage="extract_chunk")
    except Exception as e:
        log.warning("chunk_extraction_failed", run_id=run_id, source=chunk.source_path, page=chunk.page, error=str(e))
        return []

    signals = []
    for item in raw if isinstance(raw, list) else []:
        try:
            signals.append(ExtractedSignal.model_validate(item))
        except ValidationError:
            pass  # skip malformed items rather than crashing the whole chunk

    return signals


def _merge_signals(
    dimension: RiskDimension,
    signals: list[ExtractedSignal],
    run_id: str,
) -> list[ExtractedSignal]:
    """Ask Haiku to deduplicate and consolidate signals for one dimension."""
    signals_text = "\n".join(
        f'- "{s.fact}" (source: {s.source_path}, page {s.page})' for s in signals
    )

    prompt = f"""Dimension: {dimension.value}

Below are facts extracted from multiple document chunks. Deduplicate them.
Keep all distinct facts. Remove only true duplicates.

Return a JSON array in this format:
[
  {{"dimension": "{dimension.value}", "fact": "<fact>", "source_path": "<path>", "page": <number>}}
]

Facts to consolidate:
{signals_text}"""

    try:
        raw = llm.haiku_json(system=_MERGE_SYSTEM, prompt=prompt, run_id=run_id, stage=f"merge_{dimension.value}")
    except Exception as e:
        log.warning("merge_failed", run_id=run_id, dimension=dimension.value, error=str(e))
        return signals  # fall back to unmerged signals rather than losing data

    merged = []
    for item in raw if isinstance(raw, list) else []:
        try:
            merged.append(ExtractedSignal.model_validate(item))
        except ValidationError:
            pass

    return merged if merged else signals  # same fallback: never return empty if we had input
