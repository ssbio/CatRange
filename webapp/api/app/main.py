"""FastAPI service backing catrange.sahassbio.com.

Endpoints:
  POST /api/jobs           submit a new job (demo / interactive / csv mode)
  GET  /api/jobs/{id}      poll job status
  GET  /api/jobs/{id}/download   fetch the finished inference_results.csv
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from redis import Redis
from rq import Queue

from common.config import get_settings
from common.db import create_job, get_job, update_job
from common.resource_guard import route_new_job
from common.validation import (
    ValidationError,
    pairs_to_csv_text,
    validate_csv_bytes,
    validate_pairs,
)

logger = logging.getLogger("catrange.api")

app = FastAPI(title="CatRange hosted-service API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_redis: Redis | None = None
_queue: Queue | None = None


def _queue_client() -> Queue:
    global _redis, _queue
    if _queue is None:
        import os

        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis = Redis.from_url(redis_url)
        _queue = Queue("catrange-local", connection=_redis)
    return _queue


def _data_dir() -> Path:
    return Path(get_settings().storage.data_dir)


def _demo_csv_path() -> Path:
    # inference/examples/demo_pairs.csv ships in the repo and is copied into
    # the worker image; the API only needs to reference it by the same
    # relative path so the worker can resolve it locally.
    return Path("inference/examples/demo_pairs.csv")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/jobs")
async def submit_job(
    mode: str = Form(...),
    email: str | None = Form(default=None),
    pairs_json: str | None = Form(default=None),
    csv_file: UploadFile | None = File(default=None),
):
    if mode not in ("demo", "interactive", "csv"):
        raise HTTPException(status_code=400, detail="mode must be demo, interactive, or csv.")

    # --- Validate input up front, before touching the queue/disk. ----------
    input_relpath: str | None = None
    csv_text: str | None = None

    try:
        if mode == "interactive":
            if not pairs_json:
                raise ValidationError("Missing pairs_json for interactive mode.")
            pairs = json.loads(pairs_json)
            validate_pairs(pairs)
            csv_text = pairs_to_csv_text(pairs)
        elif mode == "csv":
            if csv_file is None:
                raise ValidationError("Missing csv_file for CSV mode.")
            raw = await csv_file.read()
            validate_csv_bytes(raw)
            csv_text = raw.decode("utf-8-sig")
        # mode == "demo" uses the bundled demo CSV; nothing to validate here.
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="pairs_json was not valid JSON.") from exc

    # --- Decide whether/where this job can run. -----------------------------
    decision = route_new_job()
    if not decision.accepted:
        raise HTTPException(status_code=503, detail=decision.message)

    # --- Accepted: persist input, create the job record, enqueue it. -------
    job = create_job(mode=mode, runner=decision.runner, email=email or None, detail=decision.message)
    job_dir = _data_dir() / "jobs" / job.id
    job_dir.mkdir(parents=True, exist_ok=True)

    if mode == "demo":
        input_relpath = str(_demo_csv_path())
    else:
        input_path = job_dir / "input.csv"
        input_path.write_text(csv_text, encoding="utf-8")
        input_relpath = str(input_path)

    update_job(job.id, input_path=input_relpath)

    if decision.runner == "local":
        _queue_client().enqueue(
            "run_job.execute",
            job.id,
            job_timeout="6h",
        )
    else:  # hcc
        # Handed off to the hcc-poller container (which owns the paramiko/
        # SSH dependency) via its own Redis queue, so the API image never
        # needs HCC-specific libraries or credentials.
        import os

        from rq import Queue as _Queue

        hcc_queue = _Queue("catrange-hcc", connection=Redis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0")
        ))
        hcc_queue.enqueue("hcc_submit.submit_job", job.id, job_timeout="30m")

    return {"job_id": job.id, "status": "queued", "runner": decision.runner, "detail": decision.message}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    payload = {
        "job_id": job.id,
        "status": job.status,
        "runner": job.runner,
        "mode": job.mode,
        "detail": job.detail,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
    if job.status == "done" and job.output_path:
        payload["download_url"] = f"/api/jobs/{job.id}/download"
    return payload


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str):
    job = get_job(job_id)
    if job is None or job.status != "done" or not job.output_path:
        raise HTTPException(status_code=404, detail="Results are not available.")
    output_path = Path(job.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Result file is missing.")
    return FileResponse(output_path, filename="inference_results.csv", media_type="text/csv")
