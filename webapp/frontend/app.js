// CatRange hosted-service frontend logic.
// Talks to the FastAPI backend under /api, mounted by nginx alongside this
// static site.

const API_BASE = "/api";
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

  function parsePairs(raw) {
    return raw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const idx = line.indexOf(",");
        if (idx === -1) return null;
        return {
          sequence: line.slice(0, idx).trim(),
          smiles: line.slice(idx + 1).trim(),
        };
      });
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

      if (mode === "interactive") {
        const pairs = parsePairs(qs("pairs").value);
        if (!pairs.length) {
          throw new Error("Enter at least one sequence,SMILES pair.");
        }
        if (pairs.some((p) => p === null)) {
          throw new Error(
            "Each line must be 'sequence,Isomeric SMILES' separated by a comma."
          );
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
        downloadLink.href = job.download_url;
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
