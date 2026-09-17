"""Entry point for the `hcc-poller` container.

Runs an RQ worker on the `catrange-hcc` queue (so `hcc_submit.submit_job` is
executed there instead of blocking the API request), plus — once real HCC
submission is implemented — would run a periodic `squeue`/`sacct` polling
loop for any job with runner="hcc" in status queued/running. That polling
loop is not implemented yet (see hcc_submit.py); this module only wires up
the queue consumer so the plumbing works end-to-end as soon as it is.
"""

from __future__ import annotations

import logging
import os

from redis import Redis
from rq import Worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("catrange.hcc_poller")


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    redis_conn = Redis.from_url(redis_url)
    logger.info("hcc-poller listening on queue 'catrange-hcc' (%s)", redis_url)
    worker = Worker(["catrange-hcc"], connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
