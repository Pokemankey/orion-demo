# ORION Authorization Review Pipeline

Reviews a firm's authorization submission (a JSON manifest + referenced PDF/DOCX/XLSX
documents) and produces a reviewer-ready risk assessment: per-dimension risk ratings,
a weighted composite score, a recommended authorization level, and follow-up questions.
The result is written locally and POSTed to an external review API.

## Environment variables

Copy the example file and fill in your key:

```bash
cp .env.example .env
```

| Variable              | Required | Default                             | Notes                                                             |
| --------------------- | -------- | ----------------------------------- | ----------------------------------------------------------------- |
| `ANTHROPIC_API_KEY`   | **Yes**  | —                                   | Your Anthropic API key. The pipeline makes live Claude calls.     |
| `REVIEW_API_URL`      | No       | `http://localhost:8000/assessments` | Where results are delivered. Docker overrides this automatically. |
| `EXTRACT_CONCURRENCY` | No       | `10`                                | Parallel LLM calls during extraction.                             |

A single run uses ~22 LLM calls (Haiku for extraction, Sonnet for assessment) and
takes ~100s on the sample fixture.

---

## Run with Docker (one line)

Requires Docker Desktop running. This builds the image, starts the mock review API,
runs the pipeline against the sample submission, and delivers the result:

```bash
docker compose up --build --abort-on-container-exit --exit-code-from pipeline
```

`.env` is loaded automatically via `env_file`. The `--abort-on-container-exit`
flags make the command self-terminate when the pipeline finishes (otherwise the
API server keeps running — use a plain `docker compose up --build` if you want it
to stay up).

---

## Run locally

Requires Python 3.12+.

**1. Install dependencies**

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

**2. (Optional) Regenerate the sample documents.** The PDF/DOCX/XLSX fixtures are
included in the repo, so you can skip this. Run it only if you want to recreate them:

```bash
python generate_fixtures.py
```

**3. Start the mock review API** in one terminal (leave it running):

```bash
python mock_review_api.py        # listens on http://localhost:8000
```

**4. Run the pipeline** in a second terminal:

```bash
python main.py --submission fixtures/submission.json
```

> **Note:** the mock API uses port 8000. If you see `address already in use`, a
> previous run's server is still up — stop it before starting a new one.

---

## Output

| Path                            | Contents                                                             |
| ------------------------------- | -------------------------------------------------------------------- |
| `output/<run_id>.json`          | The reviewer-ready assessment payload.                               |
| `output/received/<run_id>.json` | The same payload as received by the review API.                      |
| `output/traces/<run_id>.jsonl`  | Full audit trace — every LLM prompt and response, keyed by `run_id`. |

Logs are also emitted as structured JSON to stdout (captured by CloudWatch Logs /
Cloud Logging in a serverless deployment).
