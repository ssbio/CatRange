# Build context is the repository root (see webapp/docker-compose.yml).
#
# NOTE: This image needs a GPU-capable host with the NVIDIA container
# runtime configured (see webapp/README.md) for `--device cuda`. It will
# still run on CPU (`local.device: cpu` in settings.yaml) but much slower.
FROM python:3.12-slim

# git/curl: needed by inference/clean_inference.py to clone CLEAN and
# bootstrap its own isolated venv (via `uv`) on first run.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

COPY webapp/worker/requirements.txt ./worker-requirements.txt
COPY inference/requirements.txt ./inference-requirements.txt
RUN pip install --no-cache-dir -r inference-requirements.txt -r worker-requirements.txt

# Shared config/db/job code + the existing inference pipeline (unmodified).
COPY webapp/common ./common
COPY inference ./inference

COPY webapp/worker/run_job.py ./run_job.py
COPY webapp/worker/hcc_submit.py ./hcc_submit.py
COPY webapp/worker/hcc_poller.py ./hcc_poller.py

ENV PYTHONPATH=/app

# Default: local RQ worker consuming submitted jobs. The hcc-poller service
# overrides this command (see webapp/docker-compose.yml).
CMD ["rq", "worker", "catrange-local", "--url", "redis://redis:6379/0"]
