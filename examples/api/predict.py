#!/usr/bin/env python3
"""Submit one CatRange CSV, poll, and download; requires httpx.

No automatic retry of POST requests. Preserve the printed submission ID and
reuse --idempotency-key with unchanged input after a connection failure.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import uuid

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--api-base", default="https://api.sahassbio.com/catrange/v1")
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=21600)
    args = parser.parse_args()
    base = args.api_base.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        parser.error("--api-base must be an HTTPS URL without credentials")
    if args.output.exists() or args.output.with_suffix(args.output.suffix + ".job.json").exists():
        parser.error("Output or job record already exists; choose a new output filename")
    key = args.api_key_file.expanduser().read_text().strip()
    if not key or "\n" in key or "\r" in key:
        parser.error("Invalid API key file")
    if args.input.stat().st_size > 15 * 1024 * 1024:
        parser.error("CSV upload exceeds 15 MiB")
    if args.wait_seconds < 1:
        parser.error("--wait-seconds must be positive")
    submission_id = args.idempotency_key or str(uuid.uuid4())
    print(f"Submission ID (reuse on retry): {submission_id}", file=sys.stderr)
    deadline = time.monotonic() + args.wait_seconds
    with httpx.Client(headers={"Authorization": f"Bearer {key}"},
                      timeout=60, follow_redirects=False) as client:
        with args.input.open("rb") as source:
            response = client.post(
                f"{base}/jobs", headers={"Idempotency-Key": submission_id},
                data={"mode": "csv", "compute": "cpu",
                      "force_rerun": str(args.force_rerun).lower()},
                files={"csv_file": ("inputs.csv", source, "text/csv")},
            )
        response.raise_for_status()
        job = response.json()
        job_id = str(uuid.UUID(job["job_id"]))
        record = args.output.with_suffix(args.output.suffix + ".job.json")
        # Job record includes the retry identifier, never the API key.
        with os.fdopen(os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            json.dump({"submission_id": submission_id, "job_id": job_id,
                       "api_base": base, "response": job}, handle, indent=2)
        print(f"Job ID: {job_id}", file=sys.stderr)
        delay = 10
        while job["status"] != "done":
            if job["status"] in {"failed", "rejected", "expired", "cancelled"}:
                print(f"Job ended: {job['status']}. See {record}", file=sys.stderr)
                return 1
            if time.monotonic() >= deadline:
                print(f"Stopped waiting. Job may still be running; see {record}", file=sys.stderr)
                return 2
            print(f"Status: {job['status']}", file=sys.stderr)
            time.sleep(min(delay, max(0, deadline - time.monotonic())))
            response = client.get(f"{base}/jobs/{job_id}")
            if response.status_code in {429, 502, 503, 504}:
                retry = response.headers.get("Retry-After", "10")
                delay = int(retry) if retry.isdigit() and 0 < int(retry) <= 86400 else 10
                continue  # Read-only polling is safe to retry.
            response.raise_for_status()
            delay = 10
            job = response.json()
        # Build an owned-job URL rather than forwarding credentials to a URL
        # returned by an upstream service. Redirects are intentionally disabled.
        partial = args.output.with_suffix(args.output.suffix + ".part")
        with client.stream("GET", f"{base}/jobs/{job_id}/download") as response:
            response.raise_for_status()
            with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as target:
                for chunk in response.iter_bytes():
                    target.write(chunk)
        partial.replace(args.output)
        print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        print(f"Request stopped ({type(exc).__name__}). Keep the submission ID; "
              "do not retry a submission with a new ID automatically.", file=sys.stderr)
        raise SystemExit(1)
