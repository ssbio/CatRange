"""Tiny SQLite-backed job store shared by the API, worker, and HCC poller.

SQLite is enough here: all writers live on one host, sharing the `/data`
volume, and job volume for a lab-scale service is small. If this ever needs
multi-host writers, swap this module for a Postgres-backed one without
touching callers (the functions below are the only public surface).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    runner TEXT NOT NULL,
    mode TEXT NOT NULL,
    email TEXT,
    detail TEXT,
    error TEXT,
    input_path TEXT,
    output_path TEXT,
    hcc_slurm_job_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    meta_json TEXT
);
"""

# Valid job.status values:
#   queued    -> accepted, waiting for a local worker or HCC slot
#   running   -> actively executing (local subprocess or HCC squeue RUNNING)
#   done      -> results are available at output_path
#   failed    -> pipeline error; see `error`
#   rejected  -> never queued at all (capacity full, no HCC configured);
#                kept only for observability, not shown to users as "their" job
STATUSES = ("queued", "running", "done", "failed", "rejected")
ACTIVE_STATUSES = ("queued", "running")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    return Path(get_settings().storage.data_dir) / "catrange.sqlite3"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


@dataclass
class Job:
    id: str
    status: str
    runner: str
    mode: str
    email: Optional[str] = None
    detail: Optional[str] = None
    error: Optional[str] = None
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    hcc_slurm_job_id: Optional[str] = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            status=row["status"],
            runner=row["runner"],
            mode=row["mode"],
            email=row["email"],
            detail=row["detail"],
            error=row["error"],
            input_path=row["input_path"],
            output_path=row["output_path"],
            hcc_slurm_job_id=row["hcc_slurm_job_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            meta=json.loads(row["meta_json"] or "{}"),
        )


def create_job(
    *,
    mode: str,
    runner: str,
    email: str | None = None,
    input_path: str | None = None,
    detail: str = "Queued.",
    meta: dict[str, Any] | None = None,
) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        status="queued",
        runner=runner,
        mode=mode,
        email=email,
        input_path=input_path,
        detail=detail,
        meta=meta or {},
    )
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs
                (id, status, runner, mode, email, detail, error,
                 input_path, output_path, hcc_slurm_job_id,
                 created_at, updated_at, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.status,
                job.runner,
                job.mode,
                job.email,
                job.detail,
                job.error,
                job.input_path,
                job.output_path,
                job.hcc_slurm_job_id,
                job.created_at,
                job.updated_at,
                json.dumps(job.meta),
            ),
        )
    return job


def get_job(job_id: str) -> Optional[Job]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields = dict(fields)
    if "meta" in fields:
        fields["meta_json"] = json.dumps(fields.pop("meta"))
    fields["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE jobs SET {columns} WHERE id = ?",
            (*fields.values(), job_id),
        )


def count_active_jobs(runner: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE runner = ? AND status IN (?, ?)",
            (runner, *ACTIVE_STATUSES),
        ).fetchone()
    return int(row["n"])


def list_active_jobs(runner: str) -> list[Job]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE runner = ? AND status IN (?, ?) ORDER BY created_at",
            (runner, *ACTIVE_STATUSES),
        ).fetchall()
    return [Job.from_row(row) for row in rows]
