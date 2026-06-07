"""
Central LLM client. All pipeline stages call through here so that
every prompt/response pair is automatically logged for the audit trail.
"""
import json
import os
import structlog
import anthropic

log = structlog.get_logger()

# Model split: cheap+fast for bulk extraction, capable for final reasoning
HAIKU  = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def call(
    *,
    model: str,
    system: str,
    prompt: str,
    run_id: str,
    stage: str,
    max_tokens: int = 2048,
) -> str:
    """
    Make one LLM call and return the text response.
    Logs the full prompt and response under run_id + stage for auditability.
    temperature=0 ensures reproducibility.
    """
    client = _get_client()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    output = response.content[0].text

    log.info(
        "llm_call",
        run_id=run_id,
        stage=stage,
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        prompt=prompt,
        response=output,
    )

    return output


def call_json(
    *,
    model: str,
    system: str,
    prompt: str,
    run_id: str,
    stage: str,
    max_tokens: int = 2048,
) -> dict | list:
    """
    Same as call() but parses the response as JSON.
    The system prompt must instruct the model to respond with raw JSON only.
    """
    raw = call(
        model=model,
        system=system,
        prompt=prompt,
        run_id=run_id,
        stage=stage,
        max_tokens=max_tokens,
    )

    # Strip markdown code fences if the model wraps its JSON in ```json ... ```
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()

    return json.loads(text)


# Convenience shortcuts used by each stage

def haiku_json(*, system: str, prompt: str, run_id: str, stage: str, max_tokens: int = 2048) -> dict | list:
    return call_json(model=HAIKU, system=system, prompt=prompt, run_id=run_id, stage=stage, max_tokens=max_tokens)


def sonnet_json(*, system: str, prompt: str, run_id: str, stage: str, max_tokens: int = 2048) -> dict | list:
    return call_json(model=SONNET, system=system, prompt=prompt, run_id=run_id, stage=stage, max_tokens=max_tokens)
