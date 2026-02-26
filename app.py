#!/usr/bin/env python3
"""
app.py — Web app for Render deployment.

Exposes health check and an endpoint to trigger the recruitment pipeline.
Run with: uvicorn app:app --host 0.0.0.0 --port 8000

On Render, PORT is set automatically; use: uvicorn app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="Supabase-NocoDB Recruitment Pipeline",
    description="Trigger the AI recruitment pipeline (Manatal → OpenAI → Supabase → NocoDB)",
    version="1.0.0",
)

# Allow browser to load the page and call /run from any origin (e.g. same Render URL)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Simple Run Pipeline UI (HTML)
RUN_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Run Pipeline</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.25rem; margin-bottom: 0.5rem; }
    p { color: #555; font-size: 0.9rem; margin-bottom: 1.25rem; }
    label { display: block; font-weight: 600; margin-bottom: 0.35rem; }
    input[type="text"] { width: 100%; padding: 0.5rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 6px; }
    button { margin-top: 1rem; padding: 0.6rem 1.2rem; font-size: 1rem; background: #2563eb; color: white; border: none; border-radius: 6px; cursor: pointer; }
    button:hover { background: #1d4ed8; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    #result { margin-top: 1.25rem; padding: 0.75rem; border-radius: 6px; font-size: 0.9rem; display: none; }
    #result.success { background: #dcfce7; color: #166534; display: block; }
    #result.error { background: #fee2e2; color: #991b1b; display: block; }
    .links { margin-top: 2rem; font-size: 0.85rem; }
    .links a { color: #2563eb; text-decoration: none; }
    .links a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <h1>Run recruitment pipeline</h1>
  <p>Enter job ID(s), then click Run. Pipeline runs in the background; check Render logs for output.</p>
  <form id="form">
    <label for="job_ids">Job ID(s) (comma-separated)</label>
    <input type="text" id="job_ids" name="job_ids" value="3419430" placeholder="3419430 or 3419430, 3261113" required>
    <button type="submit" id="btn">Run pipeline</button>
  </form>
  <div id="result"></div>
  <div class="links">
    <a href="/health">Health</a> &middot; <a href="/docs">API docs</a>
  </div>
  <script>
    document.getElementById("form").onsubmit = async (e) => {
      e.preventDefault();
      var btn = document.getElementById("btn");
      var result = document.getElementById("result");
      btn.disabled = true;
      result.className = result.textContent = "";
      result.style.display = "none";
      try {
        var jobIds = document.getElementById("job_ids").value.trim();
        var r = await fetch("/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_ids: jobIds })
        });
        var data = await r.json().catch(() => ({}));
        if (r.ok) {
          result.className = "success";
          result.textContent = "Pipeline started for job(s): " + (data.job_ids || jobIds) + ". Check Render logs for progress.";
        } else {
          result.className = "error";
          result.textContent = data.detail || data.error || "Request failed: " + r.status;
        }
      } catch (err) {
        result.className = "error";
        result.textContent = "Error: " + err.message;
      }
      btn.disabled = false;
    };
  </script>
</body>
</html>
"""

HERE = Path(__file__).resolve().parent
PIPELINE_SCRIPT = HERE / "online_pipeline.py"

# Optional: job IDs to use when running via cron (set RENDER_CRON_JOB_IDS in Render)
CRON_JOB_IDS = os.getenv("RENDER_CRON_JOB_IDS", "").strip()

# Minimal error page so Render never shows a raw stack trace
ERROR_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Error</title></head><body><h1>Something went wrong</h1><p>Check Render logs. <a href="/">Try again</a>.</p></body></html>"""


@app.exception_handler(Exception)
def catch_all(_request: Request, exc: Exception):
    """Return a simple error page for unexpected errors (not HTTPException)."""
    if isinstance(exc, HTTPException):
        raise exc
    return HTMLResponse(content=ERROR_HTML, status_code=500)


class RunRequest(BaseModel):
    """Request body for POST /run."""

    job_ids: str | list[str] = Field(
        ...,
        description="Job ID(s): string like '3419430' or '3419430, 3261113', or list ['3419430', '3261113']",
    )
    skip_scoring: bool = False
    skip_upload: bool = False
    skip_reports: bool = False


def _normalize_job_ids(job_ids: str | list[str]) -> str:
    if isinstance(job_ids, list):
        return ", ".join(str(j).strip() for j in job_ids)
    return str(job_ids).strip()


def _run_pipeline_sync(job_ids: str, skip_scoring: bool, skip_upload: bool, skip_reports: bool) -> int:
    """Run online_pipeline.py in current process. Returns exit code."""
    cmd = [sys.executable, str(PIPELINE_SCRIPT), job_ids]
    if skip_scoring:
        cmd.append("--skip-scoring")
    if skip_upload:
        cmd.append("--skip-upload")
    if skip_reports:
        cmd.append("--skip-reports")
    result = subprocess.run(cmd, cwd=str(HERE))
    return result.returncode


@app.get("/", response_class=HTMLResponse)
def root():
    """Run Pipeline UI — open this link in the browser to trigger the pipeline."""
    return RUN_UI_HTML


@app.get("/api")
def api_info():
    """JSON API info for scripts."""
    return {
        "service": "supabase-nocodb-pipeline",
        "docs": "/docs",
        "health": "/health",
        "run": "POST /run with body: { \"job_ids\": \"3419430\" }",
    }


@app.get("/health")
def health():
    """Health check for Render (and load balancers)."""
    return {"status": "ok"}


@app.post("/run")
def run_pipeline(request: RunRequest):
    """
    Trigger the recruitment pipeline for the given job IDs.

    Runs the pipeline in a background thread so the request returns quickly
    (avoids Render request timeout). Check Render logs for pipeline output.
    """
    job_ids = _normalize_job_ids(request.job_ids)
    if not job_ids:
        raise HTTPException(status_code=400, detail="job_ids is required")

    def _run():
        _run_pipeline_sync(
            job_ids,
            request.skip_scoring,
            request.skip_upload,
            request.skip_reports,
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {
        "status": "accepted",
        "message": "Pipeline started in background. Check Render logs for output.",
        "job_ids": job_ids,
    }


@app.post("/run/sync")
def run_pipeline_sync(request: RunRequest):
    """
    Run the pipeline synchronously (request blocks until done).

    Use for short runs or when you need to wait for completion.
    May hit Render request timeout (~5 min on free tier) for long runs.
    """
    job_ids = _normalize_job_ids(request.job_ids)
    if not job_ids:
        raise HTTPException(status_code=400, detail="job_ids is required")

    code = _run_pipeline_sync(
        job_ids,
        request.skip_scoring,
        request.skip_upload,
        request.skip_reports,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=f"Pipeline exited with code {code}")
    return {"status": "completed", "job_ids": job_ids}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
