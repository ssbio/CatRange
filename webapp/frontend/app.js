// CatRange hosted-service frontend logic.
// Talks to the FastAPI backend at CATRANGE_API_BASE + "/api" (see
// config.js). CATRANGE_API_BASE is "" for a same-origin deployment (the
// default single-host docker-compose.yml layout) or an absolute URL when
// the frontend is hosted separately from the backend (e.g. a static host
// like Hostinger Premium Web Hosting alongside a backend on another
// server).

const API_BASE = `${window.CATRANGE_API_BASE || ""}/api`;
const MAX_INTERACTIVE_PAIRS = 10;

function qs(id) {
  return document.getElementById(id);
}

function initLandingPage() {
  const form = qs("job-form");
  if (!form) return;

  const modeSelect = qs("mode");
  const interactiveBlock = qs("interactive-block");
  const csvBlock = qs("csv-block");
  const statusEl = qs("form-status");
  const submitBtn = qs("submit-btn");

  function syncModeVisibility() {
    const mode = modeSelect.value;
    interactiveBlock.hidden = mode !== "interactive";
    csvBlock.hidden = mode !== "csv";
  }
  modeSelect.addEventListener("change", syncModeVisibility);
  syncModeVisibility();

  // "Show results for" kcat/KM toggle — mirrors CatPred's UX. CatRange
  // always predicts both values together; this only records which one(s)
  // the user wants highlighted, so at least one box must stay checked.
  const targetKcat = qs("target-kcat");
  const targetKm = qs("target-km");
  if (targetKcat && targetKm) {
    [targetKcat, targetKm].forEach((box) => {
      box.addEventListener("change", () => {
        if (!targetKcat.checked && !targetKm.checked) {
          box.checked = true;
        }
        // Fallback for browsers without :has() support.
        box.closest(".toggle-pill").classList.toggle("is-checked", box.checked);
      });
      box.closest(".toggle-pill").classList.toggle("is-checked", box.checked);
    });
  }

  function parsePairs(sequencesRaw, smilesRaw) {
    const sequences = sequencesRaw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const smilesList = smilesRaw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (sequences.length !== smilesList.length) {
      throw new Error(
        `Sequences (${sequences.length}) and SMILES (${smilesList.length}) must have the same number of lines, in matching order.`
      );
    }
    return sequences.map((sequence, i) => ({ sequence, smiles: smilesList[i] }));
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    statusEl.textContent = "";
    statusEl.className = "form-status";
    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting…";

    try {
      const mode = modeSelect.value;
      const email = qs("email").value.trim();
      const formData = new FormData();
      formData.append("mode", mode);
      if (email) formData.append("email", email);

      // Which kinetic value(s) the user wants highlighted (both by default).
      // CatRange always computes both kcat and KM together — this is purely
      // a results-display preference, not a change to what gets computed.
      const preferredTargets = [];
      if (!targetKcat || targetKcat.checked) preferredTargets.push("kcat");
      if (!targetKm || targetKm.checked) preferredTargets.push("km");
      formData.append("preferred_targets", preferredTargets.join(","));

      if (mode === "interactive") {
        const pairs = parsePairs(qs("sequences").value, qs("smiles-list").value);
        if (!pairs.length) {
          throw new Error("Enter at least one sequence and one matching SMILES.");
        }
        if (pairs.length > MAX_INTERACTIVE_PAIRS) {
          throw new Error(`Interactive mode accepts up to ${MAX_INTERACTIVE_PAIRS} pairs. Use Bulk CSV for more.`);
        }
        formData.append("pairs_json", JSON.stringify(pairs));
      } else if (mode === "csv") {
        const fileInput = qs("csv-file");
        if (!fileInput.files.length) {
          throw new Error("Choose a CSV file to upload.");
        }
        formData.append("csv_file", fileInput.files[0]);
      }
      // mode === "demo" needs no extra payload.

      const response = await fetch(`${API_BASE}/jobs`, {
        method: "POST",
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));

      if (response.status === 503) {
        statusEl.className = "form-status error";
        statusEl.textContent =
          payload.detail ||
          "The lab's queue is full right now. Please use the Colab notebook above instead.";
        return;
      }
      if (!response.ok) {
        throw new Error(payload.detail || `Submission failed (HTTP ${response.status}).`);
      }

      statusEl.className = "form-status success";
      statusEl.innerHTML = `Job submitted. <a href="job.html?id=${encodeURIComponent(payload.job_id)}">View job status</a>`;
      form.reset();
      syncModeVisibility();
    } catch (err) {
      statusEl.className = "form-status error";
      statusEl.textContent = err.message || String(err);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit job";
    }
  });
}

function initJobPage() {
  const idDisplay = qs("job-id-display");
  if (!idDisplay) return;

  const params = new URLSearchParams(window.location.search);
  const jobId = params.get("id");
  const statusLine = qs("status-line");
  const detailEl = qs("progress-detail");
  const resultsLink = qs("results-link");
  const downloadLink = qs("download-link");

  if (!jobId) {
    idDisplay.textContent = "unknown";
    statusLine.textContent = "No job ID was given in the URL.";
    return;
  }
  idDisplay.textContent = jobId;

  const TERMINAL_STATES = new Set(["done", "failed", "rejected"]);
  let timer = null;

  async function poll() {
    try {
      const response = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`);
      if (response.status === 404) {
        statusLine.textContent = "Job not found. It may have expired or the link is incorrect.";
        return;
      }
      const job = await response.json();
      statusLine.textContent = `Status: ${job.status}`;
      detailEl.textContent = job.detail || "";

      if (job.status === "done" && job.download_url) {
        // job.download_url from the API is a path like "/api/jobs/<id>/download";
        // prefix it with CATRANGE_API_BASE so it still resolves when the
        // frontend and backend are hosted on different origins.
        downloadLink.href = `${window.CATRANGE_API_BASE || ""}${job.download_url}`;
        resultsLink.hidden = false;
      }

      if (!TERMINAL_STATES.has(job.status)) {
        timer = setTimeout(poll, 4000);
      }
    } catch (err) {
      statusLine.textContent = "Could not reach the CatRange service. Retrying…";
      timer = setTimeout(poll, 8000);
    }
  }

  poll();
  window.addEventListener("beforeunload", () => timer && clearTimeout(timer));
}

initLandingPage();
initJobPage();
