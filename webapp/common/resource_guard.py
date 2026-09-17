"""Decide where (or whether) a newly submitted job should run.

Decision order, evaluated at submission time:

1. If the local queue (jobs with runner="local" in status queued/running) is
   below `local.max_queue_depth`, accept the job locally. The actual
   concurrency limit (`local.max_concurrent_jobs`) is enforced by only
   running that many RQ worker replicas, so jobs beyond that simply wait in
   Redis's queue — no extra bookkeeping needed here.
2. Otherwise, if HCC is enabled and below its own concurrency limit, submit
   to the `ssbio` partition instead.
3. Otherwise, reject outright (no job record beyond an observability entry)
   and tell the caller to use Colab directly rather than wait indefinitely.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import get_settings
from .db import count_active_jobs


@dataclass
class RoutingDecision:
    accepted: bool
    runner: str  # "local" | "hcc" | "" (rejected)
    message: str


def route_new_job() -> RoutingDecision:
    settings = get_settings()

    local_active = count_active_jobs("local")
    if local_active < settings.local.max_queue_depth:
        return RoutingDecision(
            accepted=True,
            runner="local",
            message="Queued on the lab's local GPU server.",
        )

    if settings.hcc.enabled:
        hcc_active = count_active_jobs("hcc")
        if hcc_active < settings.hcc.max_concurrent_jobs:
            return RoutingDecision(
                accepted=True,
                runner="hcc",
                message=f"Submitted to the HCC '{settings.hcc.partition}' partition.",
            )

    return RoutingDecision(
        accepted=False,
        runner="",
        message=(
            "The lab's job queue is full right now and no additional compute "
            "(HCC) is available. Please run the notebook yourself in Google "
            f"Colab instead: {settings.site.colab_url}"
        ),
    )
