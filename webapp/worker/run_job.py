"""RQ task: run one CatRange job through the existing source-inference CLI.

This intentionally shells out to `inference/catrange_inference.py` (the same
script documented in the main README as "Method 3: Source-code command")
rather than importing its internals, so the worker container gets exactly
the same input-validation -> CLEAN -> CatRange -> merged-results behavior
that a user gets running the notebook's underlying pipeline themselves.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from common.config import get_settings
from common.db import get_job, update_job
from common.email_utils import send_job_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("catrange.worker")

REPO_ROOT = Path(__file__).resolve().parent
INFERENCE_SCRIPT = REPO_ROOT / "inference" / "catrange_inference.py"
MODELS_DIR = REPO_ROOT / "inference" / "models"
CLEAN_WORK_DIR = REPO_ROOT / ".clean_runtime"


def execute(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        logger.error("Job %s not found; nothing to run.", job_id)
        return

    settings = get_settings()
    data_dir = Path(settings.storage.data_dir)
    job_dir = data_dir / "jobs" / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "inference_results.csv"
    log_path = job_dir / "run.log"

    update_job(job.id, status="running", detail="Running CLEAN + CatRange pipeline...")

    input_path = job.input_path
    if not input_path:
        update_job(job.id, status="failed", error="No input file recorded for this job.")
        return

    command = [
        sys.executable,
        str(INFERENCE_SCRIPT),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--models-dir",
        str(MODELS_DIR),
        "--device",
        settings.local.device,
        "--clean-work-dir",
        str(CLEAN_WORK_DIR),
    ]

    logger.info("Running job %s: %s", job.id, " ".join(command))
    with log_path.open("w", encoding="utf-8") as log_file:
        result = subprocess.run(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=REPO_ROOT,
        )

    if result.returncode == 0 and output_path.exists():
        update_job(
            job.id,
            status="done",
            output_path=str(output_path),
            detail="Done. Results are ready to download.",
        )
        if job.email:
            send_job_notification(job.email, job.id, "done")
    else:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        update_job(
            job.id,
            status="failed",
            error=f"Pipeline exited with code {result.returncode}.\n{tail}",
            detail="The pipeline failed. See error details.",
        )
        if job.email:
            send_job_notification(job.email, job.id, "failed")
