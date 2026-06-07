"""
Mock external review API.
Accepts POST /assessments from the pipeline and saves the payload to disk.

Run with: python mock_review_api.py
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI(title="ORION Mock Review API")

RECEIVED_DIR = Path("output") / "received"


@app.post("/assessments", status_code=201)
async def receive_assessment(request: Request) -> dict:
    body = await request.body()
    payload = json.loads(body)

    run_id = payload.get("run_id", "unknown")

    RECEIVED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RECEIVED_DIR / f"{run_id}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[API] Received assessment for run_id={run_id}, firm={payload.get('firm_name')}, level={payload.get('authorization_level')}")

    return {
        "status": "received",
        "run_id": run_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/assessments/{run_id}")
async def get_assessment(run_id: str) -> dict:
    path = RECEIVED_DIR / f"{run_id}.json"
    if not path.exists():
        return Response(status_code=404)
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
