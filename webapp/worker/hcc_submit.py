"""HCC UNL 'ssbio' partition submitter — inert stub until configured.

Real implementation sketch (left for the lab to finish once credentials
exist, see webapp/README.md > "Enabling the HCC fallback"):

  1. SSH to `hcc.ssh_host` as `hcc.ssh_user` using `hcc.ssh_key_path`
     (paramiko or a plain `ssh`/`scp` subprocess both work).
  2. `scp`/sftp the job's input CSV to
     `{hcc.remote_work_dir}/{job_id}/input.csv`.
  3. Write and submit an sbatch script requesting the `ssbio` partition
     (and `hcc.account` / `hcc.qos` if set) that runs the same
     `inference/catrange_inference.py` command used locally (see
     `worker/run_job.py`), from a checkout/venv already provisioned on HCC.
  4. Record the returned Slurm job ID via
     `update_job(job_id, hcc_slurm_job_id=...)`.
  5. `hcc_poller.py` (run as a separate long-lived process) periodically
     `squeue`/`sacct`s that job ID, and on completion `scp`s the results CSV
     back into `{data_dir}/jobs/{job_id}/inference_results.csv` and marks the
     job done/failed.

None of that runs today: `settings.hcc.enabled` is `false` by default and
`common.resource_guard.route_new_job` never routes to "hcc" while it is
false, so this module only needs to exist, not to actually work yet.
"""

from __future__ import annotations

import logging

from common.config import get_settings
from common.db import update_job

logger = logging.getLogger("catrange.hcc")


def submit_job(job_id: str) -> None:
    settings = get_settings()
    if not settings.hcc.enabled:
        logger.warning(
            "hcc_submit.submit_job called for %s but HCC is not enabled in "
            "settings.yaml; marking failed instead of silently hanging.",
            job_id,
        )
        update_job(
            job_id,
            status="failed",
            error=(
                "HCC fallback is not configured yet. This job should not have "
                "been routed here — please report this as a bug."
            ),
        )
        return

    # See the module docstring: real SSH/sbatch submission is not
    # implemented yet. Fail loudly and clearly rather than pretend to work.
    update_job(
        job_id,
        status="failed",
        error=(
            "HCC submission is enabled in settings.yaml but not yet "
            "implemented in webapp/worker/hcc_submit.py. Finish the "
            "submit_job()/poll_job() TODOs described in this file before "
            "enabling hcc.enabled."
        ),
    )
