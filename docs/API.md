# CatRange API guide

**Experimental service:** the stable API base is
`https://api.sahassbio.com/catrange/v1`. Check [live readiness](https://api.sahassbio.com/catrange/v1/ready)
before submitting. [Interactive API reference](https://api.sahassbio.com/catrange/docs).

## Access

Request an individual research API key from the service operator at
`info@catrange.sahassbio.com`. Keys are provisioned by the operator; there is no
automatic registration page. Keep your key private and store it in a file with
permissions `600`, outside your project repository. Never embed a key in a
public notebook, browser JavaScript, or a GitHub issue.

Send `Authorization: Bearer <your-key>` on job requests. Documentation and
readiness and aggregate activity counts are public. A key can only access jobs
submitted under its own client identity through this gateway. Existing website job IDs continue working on the
website; they are not automatically imported into the gateway.
Treat Job IDs and emailed result links as private: the existing website still
uses those links to grant access to retained results.

## Submit a CSV

CSV files need `sequence` and `smiles` columns. `Isomeric SMILES` is also accepted
instead of `smiles`. Optional `sequence_id` and `substrate_id` columns label the
results. Protein sequences must contain 9–1,022 amino acids, and SMILES strings
2–512 characters. Invalid rows remain in the output with skip reasons.

Submission uses **multipart form data**, not a JSON request body:

| Field | Meaning |
| --- | --- |
| `mode` | `csv` for an uploaded file; `interactive` for up to 10 pairs |
| `csv_file` | CSV upload, up to 5,000 rows and 15 MiB |
| `pairs_json` | For interactive mode: JSON list of objects containing `sequence`, `smiles`, and optional identifiers |
| `compute` | `cpu` (default) or `auto`; GPU is currently disabled |
| `preferred_targets` | Defaults to `kcat,km` |
| `force_rerun` | Defaults to `false`; set `true` to bypass prediction caching |
| `email` | Optional completion notification address |

Also send an `Idempotency-Key` header containing a unique identifier for this
logical submission. **Reuse that identifier and the same inputs when retrying
the same submission.** A new identifier means a new submission, even if the
inputs are identical. Multipart boundaries do not affect retry matching.
Use 8–128 ASCII letters, digits, dots, underscores, colons, or hyphens.
Completed submission responses can be replayed for eight days. After that,
the key returns `410`; a compact record prevents it from creating another job.

```python
from pathlib import Path
import uuid
import httpx

base = "https://api.sahassbio.com/catrange/v1"
key = Path("~/.config/ssbio/research-api-key").expanduser().read_text().strip()
submission_id = str(uuid.uuid4())  # Save this before sending; reuse it on retry.

with httpx.Client(timeout=60, follow_redirects=False) as client:
    with open("inputs.csv", "rb") as file:
        response = client.post(
            f"{base}/jobs",
            headers={"Authorization": f"Bearer {key}",
                     "Idempotency-Key": submission_id},
            data={"mode": "csv", "compute": "cpu"},
            files={"csv_file": ("inputs.csv", file, "text/csv")},
        )
    response.raise_for_status()
    job = response.json()
    print(job["job_id"], job["status"])
```

For a complete command-line example that saves the job response, polls, and
downloads the CSV, use [predict.py](../examples/api/predict.py). It reads a key from
a private file rather than accepting a key on the command line.

```bash
python -m pip install httpx
python examples/api/predict.py --input inputs.csv --output predictions.csv \
  --api-key-file ~/.config/ssbio/research-api-key
```

## Progress and results

| Method and path, relative to the API base | Purpose |
| --- | --- |
| `GET /ready` | Current backend readiness and available compute choices |
| `GET /metrics` | Public successful-row totals for each parameter, including cached results |
| `POST /jobs` | Submit inputs; returns a full `job_id` |
| `GET /jobs/{job_id}` | Status, queue/compute timing, cache information, and result links |
| `GET /jobs/{job_id}/results` | JSON dashboard results, limited to 10 rows / 1 MiB |
| `GET /jobs/{job_id}/download` | Finished CSV, including bulk jobs |
| `POST /jobs/{job_id}/rerun` | Fresh prediction from retained inputs; requires a new `Idempotency-Key` |
| `POST /jobs/{job_id}/notification-email` | Add an address using JSON `{"email":"you@example.org"}` |

Poll approximately every 10 seconds. A cache hit can finish immediately.
Otherwise jobs pass through queueing and execution before `done` or a failure
state. Use the returned links; do not assume backend-specific hostnames.

Activity counters count each successful parameter result once per completed job;
downloads do not increment them. Computed and cached results have separate
subtotals. Tracking includes the results still retained at activation, so older
deleted results are missing from this baseline. These are not lifetime totals.
Collection can lag by about a minute; an outage is marked stale or unavailable.

Retained result files are normally cleaned up seven days after completion.
Availability within that period is best effort and is not guaranteed. Download
and keep your own copy promptly; the service is not an archive and cannot
guarantee recovery of lost data. Gateway ownership and retry records are
separate metadata; they do not extend result retention.

## Resources and fair use

Clients do not need local models, a GPU, or cluster credentials. Requests share
the hosted CatRange queue. The current backend runs one worker at a time with
capacity for five unfinished jobs total. Read `/ready` for live limits.

| Valid workload | CPU cores | RAM | Maximum Job duration |
| --- | --- | --- | --- |
| Up to 10 pairs, sequences no longer than 512 amino acids | 2 | 16 GiB | 30 minutes |
| Other jobs with at most 500 pairs and 100 unique sequences | 4 | 16–24 GiB | 1 hour |
| Larger jobs within the upload limit | 8 | 16–24 GiB | 6 hours |

RAM rises to 24 GiB for longer valid sequences. These are resource assignments
and execution deadlines, not runtime estimates or completion guarantees.
Default gateway keys permit 120 authenticated requests per minute and 10 new
submission attempts per UTC day. Operators may assign different limits.
Retries with the same idempotency key do not count as new submission attempts.

## Errors and retries

- `401`: missing or invalid API key.
- `403`: the key is not permitted to use this tool, or the requested compute
  option is unavailable.
- `404`: the job does not belong to this key, or does not exist.
- `409`: an idempotency conflict, submission still in progress, or an uncertain
  upstream submission outcome. Inspect the response and keep the same key.
- `410`: results have expired.
- `410` with `idempotency_expired`: the submission replay record has expired;
  the original key will not create another job.
- `413`: request or upload too large.
- `429`: a per-key quota was reached; respect `Retry-After`.
- `502` / `503` / `504`: the upstream service is unavailable or its outcome is
  uncertain. Do not automatically submit with a new idempotency key.

If a submission times out after the backend may have accepted it, the gateway
keeps the attempt reserved to avoid duplicate compute. Ask the operator to
reconcile it; a new idempotency key would risk creating another job. Read-only
polling can be retried with backoff. Automatic multi-provider failover is not
enabled.

## Scientific interpretation and citation

CatRange predicts kinetic **ranges**, not experimentally measured rate
constants. Use the reported bounds, units, and confidence fields. Adjacent-bin
visual guides are not calibrated confidence intervals, and midpoints do not
replace the range prediction. CLEAN screening remains part of the pipeline.

See [CatRange's README and citation](https://github.com/ssbio/CatRange#readme)
for the current paper and scientific source. The shared gateway is operated by
SSBio Lab. Copyright © 2026 SahaSSBio.
