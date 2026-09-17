# CatRange hosted service (catrange.sahassbio.com)

This directory contains a self-contained Docker Compose stack that runs
CatRange as a small web service: a landing page, a job-submission API, and a
worker that executes the same pipeline as the
[Colab notebook](https://colab.research.google.com/github/ssbio/CatRange/blob/main/CatRange_Inference_Interface.ipynb)
(via `inference/catrange_inference.py`) on the lab's own hardware instead of
the user's Google account.

**Google Colab remains the recommended default** for most users (see the
main [README](../README.md#hosted-service)). This service exists for people
who can't or don't want to use Colab directly.

```
webapp/
  docker-compose.yml
  nginx/            reverse proxy + static frontend + TLS termination
  frontend/         static landing page (index.html) + job status page (job.html)
  common/           shared config/DB/job-queue code (used by api + worker)
  api/              FastAPI job-submission/status service
  worker/           Papermill-free* worker that runs inference/catrange_inference.py
                    (*it calls the CLI directly, not the interactive .ipynb — see
                    the "Why not literally run the notebook" note below)
  config/
    settings.example.yaml   copy to settings.yaml and fill in real values
```

## What you need to provide (manual steps I can't do for you)

1. **A server** with Docker + Docker Compose installed, reachable from the
   internet on ports 80/443. A GPU (NVIDIA, with the
   [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
   installed) is strongly recommended — CatRange's embedding models
   (ESM-C, ChemBERTa) run far faster on GPU. CPU-only works but is slow for
   Bulk-large jobs.
2. **DNS**: in Hostinger's DNS panel for `sahassbio.com`, add either:
   - an **A record**: `catrange` → the server's public IPv4 address, or
   - a **CNAME record**: `catrange` → the server's hostname (if it already
     has a stable DNS name, e.g. from a cloud provider).

   If Hostinger's own hosting plan turns out to be **shared/cPanel
   hosting** (no Docker/SSH access), it *cannot* run this stack. In that
   case, only point DNS at wherever the Docker host actually lives (a
   separate lab machine, a university VM, or a cloud VPS) — Hostinger would
   then just be the domain registrar/DNS provider, not the app host. If you
   do have Hostinger VPS/Cloud with SSH+Docker access, you can run this
   stack directly on it.
3. Once DNS resolves, obtain a TLS certificate (see below).
4. (Optional) SMTP credentials for job-complete emails.
5. (Optional, later) HCC UNL `ssbio` partition SSH credentials for the
   overflow fallback.

## First deploy

```bash
cd webapp
cp config/settings.example.yaml config/settings.yaml
# edit config/settings.yaml: at minimum confirm site.base_url and
# local.max_concurrent_jobs match your server's GPU count.

docker compose build
docker compose up -d redis api worker nginx
```

Visit `http://catrange.sahassbio.com/` once DNS has propagated — you should
see the landing page (served over plain HTTP at this point).

### Enabling HTTPS

1. Confirm `http://catrange.sahassbio.com/.well-known/acme-challenge/` is
   reachable (the default `nginx/conf.d/catrange.conf` already serves it).
2. Issue the first certificate:

   ```bash
   docker compose run --rm certbot certonly --webroot \
     -w /var/www/certbot -d catrange.sahassbio.com \
     --email you@sahassbio.com --agree-tos --no-eff-email
   ```

3. Edit `nginx/conf.d/catrange.conf`: replace the "STEP 1" plain-HTTP
   server block with the "STEP 2" HTTPS pair that is already written out
   (commented) at the bottom of that file, then:

   ```bash
   docker compose restart nginx
   docker compose up -d certbot   # keeps the cert renewed every 12h
   ```

## Sizing local GPU concurrency

`config/settings.yaml`'s `local.max_concurrent_jobs` **must match** how many
`worker` replicas you run, since RQ's own queuing (not custom code) is what
enforces the concurrency limit:

```bash
docker compose up -d --scale worker=1   # 1 GPU -> 1 worker replica
```

`local.max_queue_depth` controls how many jobs may sit in the local queue
(queued + running) before new submissions are redirected to HCC (if
configured) or told to use Colab instead of waiting indefinitely.

## Enabling the HCC fallback

Not configured out of the box — `hcc.enabled: false` in
`settings.example.yaml`. To turn it on:

1. Get a dedicated (non-personal) HCC account for CatRange jobs and an SSH
   keypair authorized for it on an HCC login node (Swan/Crane), scoped to
   the `ssbio` partition/allocation.
2. Put the private key at `webapp/secrets/hcc/id_ed25519` (this path is
   already gitignored and already mounted read-only into the `hcc-poller`
   container in `docker-compose.yml`).
3. Fill in `hcc.ssh_host`, `hcc.ssh_user`, `hcc.ssh_key_path`
   (`/secrets/hcc/id_ed25519` inside the container), `hcc.account`,
   `hcc.qos` in `config/settings.yaml`, and set `hcc.enabled: true`.
4. Finish the TODOs described in `worker/hcc_submit.py` (SSH/scp the input
   file, submit an `sbatch` script that runs the same
   `inference/catrange_inference.py` command as `worker/run_job.py`, and
   poll `squeue`/`sacct` for completion in `worker/hcc_poller.py`). This is
   left unimplemented deliberately — real HCC credentials weren't available
   when this stack was built, and the exact sbatch template depends on how
   the `ssbio` allocation is set up.
5. `docker compose up -d --build hcc-poller`.

Until step 4 is done, any job that resource_guard would have routed to HCC
instead fails fast with a clear "not implemented yet" error rather than
hanging — this only happens once the local queue is already full, since
`hcc.enabled` stays `false` by default.

## Enabling email notifications

1. Create an app password for a lab Gmail account (or use another SMTP
   provider).
2. In `config/settings.yaml`, set `email.enabled: true` and fill in
   `smtp_username` / `smtp_password` (an app password, never the main
   account password) and `from_address`.
3. `docker compose restart worker`.

Users can still always retrieve results from the job's status page
(`/job.html?id=...`) with no email required — email is purely a
convenience notification.

## Why not literally run the interactive `.ipynb` via Papermill

The Colab notebook collects input through `ipywidgets` (mode pickers,
file-upload widgets), which have no meaning in a headless run. Rather than
fight the widget UI with Papermill parameter injection, the worker calls
`inference/catrange_inference.py` directly — the same script the notebook
documents as its underlying CLI ("Method 3: Source-code command" in the
main README) — producing identical output columns for Bulk/Bulk-large mode.

## Data retention

Job inputs/outputs live under the `catrange_data` Docker volume
(`{data_dir}/jobs/{job_id}/`). `config/settings.yaml`'s
`storage.job_ttl_days` documents the intended retention policy; add a
scheduled cleanup (e.g. a cron job or a small compose `command` on a
one-shot container) that deletes job directories older than that if/when
volume growth becomes a concern — no automatic cleanup job ships yet.

## Local testing without a GPU server

```bash
cd webapp
cp config/settings.example.yaml config/settings.yaml
docker compose up --build
# visit http://localhost/ (nginx listens on 80/443 per docker-compose.yml)
```

Submit a "Demo" job from the landing page; `local.device: auto` falls back
to CPU automatically if no GPU is present, so this works (slowly) on a
laptop for smoke-testing the API/worker/queue wiring end-to-end.
