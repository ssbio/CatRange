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

## Confirmed: catrange.sahassbio.com is on Hostinger Premium Web Hosting

That plan (File Manager, PHP, MySQL, Git, SSH access, Cron Jobs) is
**shared hosting** — SSH access there is for managing your own files, not a
general-purpose Linux server. It cannot run Docker, a persistent Python
process, or a GPU workload. See
[Hostinger's supported languages](https://www.hostinger.com/support/which-programming-languages-and-frameworks-are-supported-at-hostinger/):
no Docker, no long-running custom services.

This means the deployment **must be split across two hosts**:

| Piece | Where it goes | What to upload/deploy |
| --- | --- | --- |
| Static landing page + job status page | Hostinger `public_html` | Only the 5 files in `webapp/frontend/`: `index.html`, `job.html`, `styles.css`, `app.js`, `config.js` |
| API + worker + Redis + model files | A separate Linux server with Docker (and ideally a GPU) | The `webapp/` folder (minus `frontend/`, which isn't needed there) |

**Do not upload the whole repository to `public_html`.** Upload only the 5
files listed above from `webapp/frontend/`.

```
webapp/
  docker-compose.yml
  nginx/            reverse proxy + TLS termination for the API (backend server only)
  frontend/         <-- THIS is what goes to Hostinger public_html
    index.html
    job.html
    styles.css
    app.js
    config.js        <-- edit this one file to point at your backend's URL
  common/           shared config/DB/job-queue code (used by api + worker)
  api/              FastAPI job-submission/status service (backend server only)
  worker/           runs inference/catrange_inference.py (backend server only)
  config/
    settings.example.yaml   copy to settings.yaml and fill in real values
```

## Deploying the frontend to Hostinger

1. In hPanel, open **File Manager** (or connect via the plan's SFTP/SSH) and
   go to the document root for the `catrange` subdomain (usually
   `public_html/catrange` if it's a subdomain of `sahassbio.com`, or the
   subdomain's own root if Hostinger created a separate one — check
   **Domains → Subdomains** in hPanel for the exact path).
2. Upload exactly these files from `webapp/frontend/` into that folder,
   flat (no subfolder):
   - `index.html`
   - `job.html`
   - `styles.css`
   - `app.js`
   - `config.js`
3. Edit `config.js` (via File Manager's code editor, or edit locally and
   re-upload) and set:

   ```js
   window.CATRANGE_API_BASE = "https://api.catrange.sahassbio.com";
   ```

   using the hostname you set up for the backend below. Leaving it as `""`
   only works if frontend and backend share one origin, which isn't the
   case here.
4. That's the entire Hostinger-side deployment. No PHP, no MySQL, no cron
   jobs, no `.git` needed — this plan's extra features (Git, cron, MySQL)
   are unused by CatRange.

## What you need for the backend server (not Hostinger)

The API/worker/model-weights piece needs an actual Linux server you (or
your lab/university) control with SSH + Docker — e.g. a lab GPU box, a
university-provided VM, or a cloud VPS/GPU instance. Concretely:

1. **A server** with Docker + Docker Compose installed, reachable from the
   internet on ports 80/443. A GPU (NVIDIA, with the
   [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
   installed) is strongly recommended — CatRange's embedding models
   (ESM-C, ChemBERTa) run far faster on GPU. CPU-only works but is slow for
   Bulk-large jobs.
2. **A second DNS record**, added in the same Hostinger DNS panel, for a
   hostname dedicated to the backend — e.g. `api.catrange.sahassbio.com` —
   pointing at that server (A record → its public IPv4, or CNAME → its
   hostname). Keep `catrange.sahassbio.com` itself pointed at Hostinger for
   the static frontend; the backend needs its own subdomain since one DNS
   name can't point at two different hosts.
3. Once that DNS resolves, obtain a TLS certificate for `api.catrange.
   sahassbio.com` (see below) — the browser will otherwise block the
   frontend's cross-origin requests to a plain-HTTP API.
4. (Optional) SMTP credentials for job-complete emails.
5. (Optional, later) HCC UNL `ssbio` partition SSH credentials for the
   overflow fallback — see "Requesting HCC access" below for exactly what
   to ask for, and an important caveat about what HCC can and can't do
   here.

## First deploy (backend server)

```bash
cd webapp
cp config/settings.example.yaml config/settings.yaml
# edit config/settings.yaml: leave site.base_url as
# https://catrange.sahassbio.com (the frontend's Hostinger URL — it's only
# used to build job-status links inside notification emails) and confirm
# local.max_concurrent_jobs matches your server's GPU count.

docker compose build
docker compose up -d redis api worker nginx
```

Visit `http://api.catrange.sahassbio.com/` once DNS has propagated — you should
see the landing page (served over plain HTTP at this point).

### Enabling HTTPS

1. Confirm `http://api.catrange.sahassbio.com/.well-known/acme-challenge/`
   is reachable (the default `nginx/conf.d/catrange.conf` already serves
   it — just update the `server_name` in that file from
   `catrange.sahassbio.com` to `api.catrange.sahassbio.com` first, since the
   frontend now lives on Hostinger under the bare `catrange` name).
2. Issue the first certificate:

   ```bash
   docker compose run --rm certbot certonly --webroot \
     -w /var/www/certbot -d api.catrange.sahassbio.com \
     --email you@sahassbio.com --agree-tos --no-eff-email
   ```

3. Edit `nginx/conf.d/catrange.conf`: replace the "STEP 1" plain-HTTP
   server block with the "STEP 2" HTTPS pair that is already written out
   (commented) at the bottom of that file (updating `server_name` and the
   certificate paths there too), then:

   ```bash
   docker compose restart nginx
   docker compose up -d certbot   # keeps the cert renewed every 12h
   ```

   Since the frontend is on Hostinger, not this server, you can drop the
   `location / { root /usr/share/nginx/html; ... }` static-file block from
   `catrange.conf` entirely — this nginx only needs to serve the ACME
   challenge and reverse-proxy `/api/`.

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

## Requesting HCC access (for the batch-job fallback only — not the whole app)

Your third alternative — "host the complete app on HCC and point DNS at
it" — **will not work as described**, and I'd recommend dropping it. HPC
clusters like HCC's Swan/Crane/Anvil are Slurm batch schedulers: compute
nodes generally have no public IP, no open inbound ports, and policies
against long-running listening services (an always-on nginx+FastAPI+Redis
stack answering public HTTP/HTTPS traffic isn't what a batch partition is
for). Login nodes are shared/multi-tenant and also aren't meant to run a
persistent public-facing web service. So the persistent app (frontend
backend server above) still needs its own dedicated VM — HCC's role stays
what this stack already designs it as: an **overflow batch-compute target**
that `worker/hcc_submit.py` submits individual CatRange jobs to via
`sbatch`, polled by `worker/hcc_poller.py`, when the dedicated server's own
queue is full.

With that scoped correctly, here's exactly what to ask HCC (or whichever
cluster, e.g. Anvil) for:

1. **A dedicated (non-personal) service account** for CatRange job
   submission — not a lab member's personal login, so credentials can
   rotate without depending on one person.
2. **SSH key-based (non-interactive) login** for that account from your
   backend server's IP, since jobs will be submitted unattended (no
   password prompt).
3. **Confirmation of the exact Slurm identifiers** to use in `sbatch`:
   partition name (e.g. `ssbio`), and any required `--account` / `--qos`
   values for your lab's allocation.
4. **GPU node availability and specs** on that partition (GPU model, VRAM,
   how many are allocated to your group) — needed to size how many jobs
   `hcc.max_concurrent_jobs` in `config/settings.yaml` should allow at once.
5. **Whether Docker or only Apptainer/Singularity is supported.** Most HPC
   centers, including typical HCC/Anvil setups, do **not** allow Docker on
   compute nodes — only Apptainer/Singularity containers or plain
   module/conda environments. This means `worker/hcc_submit.py`'s eventual
   implementation must run the pipeline via an Apptainer image or a
   cluster-native Python environment (conda/venv + modules), **not**
   `docker compose` — the current `webapp/worker/Dockerfile` cannot be
   reused as-is on HCC; treat it only as the source-of-truth for which
   pip packages/versions are needed, and rebuild an equivalent
   Apptainer/conda environment from `inference/requirements.txt`.
6. **Outbound internet access from compute nodes**, or lack thereof. The
   pipeline downloads CatRange's model weights from Hugging Face and CLEAN's
   pretrained files on first run; many HPC compute nodes are firewalled off
   from arbitrary outbound internet. If that's the case here, ask whether
   there's a shared/group storage path where those files can be pre-staged
   once (by hand or via a login-node/data-transfer-node download) so job
   scripts can read them locally instead of re-downloading each time.
7. **Storage/quota** for: pre-staged model weights (a few GB), a working
   directory for job inputs/outputs (`hcc.remote_work_dir` in
   `settings.yaml`), and whether that should live under `/work`, a group
   allocation, or elsewhere per HCC's storage tiers.
8. **Wall-time limits** on the `ssbio` partition/QOS, to confirm large
   "Bulk-large" CSV jobs will fit before being killed.
9. **Whom to contact and their account-request process/docs** (you already
   have a candidate reference — confirm with your PI/HCC liaison whether
   `ssbio` is UNL's own Holland Computing Center allocation or a different
   cluster like Purdue Anvil, since the two have different account/request
   procedures).

Once you have those answers, come back and I can fill in
`config/settings.yaml`'s `hcc:` block and finish
`worker/hcc_submit.py`/`worker/hcc_poller.py` for real (currently a
documented stub that fails fast rather than silently hanging — see below).

To turn the fallback on once implemented:

1. Put the private key at `webapp/secrets/hcc/id_ed25519` (already
   gitignored and already mounted read-only into the `hcc-poller`
   container in `docker-compose.yml`).
2. Fill in `hcc.ssh_host`, `hcc.ssh_user`, `hcc.ssh_key_path`
   (`/secrets/hcc/id_ed25519` inside the container), `hcc.account`,
   `hcc.qos` in `config/settings.yaml`, and set `hcc.enabled: true`.
3. Finish the TODOs described in `worker/hcc_submit.py` (SSH/scp the input
   file, submit an appropriate job — via Apptainer or a cluster conda/venv
   environment, not Docker — that runs the same
   `inference/catrange_inference.py` command as `worker/run_job.py`, and
   poll `squeue`/`sacct` for completion in `worker/hcc_poller.py`). This is
   left unimplemented deliberately — real HCC credentials weren't available
   when this stack was built, and the exact job template depends on the
   answers above.
4. `docker compose up -d --build hcc-poller`.

Until step 3 is done, any job that resource_guard would have routed to HCC
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

Since nginx no longer serves the frontend by default (see above), test the
two pieces separately:

```bash
cd webapp
cp config/settings.example.yaml config/settings.yaml
docker compose up --build
# backend/API now listening at http://localhost/api/... (nginx on 80/443)
```

Then serve the frontend locally with any static-file server and point it at
that backend, e.g.:

```bash
cd webapp/frontend
# edit config.js: window.CATRANGE_API_BASE = "http://localhost";
python3 -m http.server 8080
# visit http://localhost:8080/index.html
```

Submit a "Demo" job from the landing page; `local.device: auto` falls back
to CPU automatically if no GPU is present, so this works (slowly) on a
laptop for smoke-testing the API/worker/queue wiring end-to-end. Remember to
revert `config.js` to the real backend URL before uploading it to Hostinger.
