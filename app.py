#!/usr/bin/env python3
"""
app.py — Web app for Render deployment.

Exposes health check and an endpoint to trigger the recruitment pipeline.
Run with: uvicorn app:app --host 0.0.0.0 --port 8000

On Render, PORT is set automatically; use: uvicorn app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Query, Form, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="Airtable Recruitment Pipeline",
    description="Trigger the AI recruitment pipeline (Manatal → OpenAI → Airtable)",
    version="2.0.0",
)

# Allow browser to load the page and call /run from any origin (e.g. same Render URL)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# AI Recruitment System dashboard (matches reference UI)
RUN_UI_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Recruitment System</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, sans-serif; margin: 0; background: #f5f5f5; color: #1a1a1a; }
    .header { background: #2d3748; color: white; padding: 1.25rem 1.5rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }
    .header h1 { margin: 0; font-size: 1.5rem; font-weight: 700; display: flex; align-items: center; gap: 0.5rem; }
    .header .subtitle { font-size: 0.85rem; opacity: 0.9; margin-top: 0.25rem; }
    .live { display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.85rem; color: #48bb78; }
    .live::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: #48bb78; }
    .container { max-width: 1100px; margin: 0 auto; padding: 1.5rem; }
    .card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem; }
    .card h2 { margin: 0 0 1rem; font-size: 1.1rem; font-weight: 600; }
    .run-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 1rem; }
    .field { display: flex; flex-direction: column; gap: 0.35rem; }
    .field label { font-size: 0.75rem; font-weight: 600; color: #718096; text-transform: uppercase; letter-spacing: 0.02em; }
    .field input, .field select { padding: 0.5rem 0.75rem; font-size: 0.95rem; border: 1px solid #cbd5e0; border-radius: 6px; min-width: 140px; }
    .btn-run { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.5rem 1.25rem; font-size: 0.95rem; font-weight: 600; background: #805ad5; color: white; border: none; border-radius: 6px; cursor: pointer; }
    .btn-run:hover:not(:disabled) { background: #6b46c1; }
    .btn-run:disabled { opacity: 0.6; cursor: not-allowed; }
    .btn-run svg { width: 16px; height: 16px; }
    .status-bar { padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1rem; display: none; align-items: center; gap: 0.5rem; }
    .status-bar.success { background: #c6f6d5; color: #276749; display: flex; }
    .status-bar.error { background: #fed7d7; color: #c53030; display: flex; }
    .status-bar.running { background: #bee3f8; color: #2b6cb0; display: flex; }
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
    .stat { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; }
    .stat .label { font-size: 0.7rem; font-weight: 600; color: #718096; text-transform: uppercase; letter-spacing: 0.02em; margin-bottom: 0.25rem; }
    .stat .value { font-size: 1.5rem; font-weight: 700; }
    .stat .value.blue { color: #3182ce; }
    .stat .value.purple { color: #805ad5; }
    .stat .value.green { color: #38a169; }
    .stat .value.black { color: #1a1a1a; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 0.75rem 1rem; border-bottom: 1px solid #e2e8f0; }
    th { font-size: 0.7rem; font-weight: 600; color: #718096; text-transform: uppercase; letter-spacing: 0.02em; }
    tr.row-clickable { cursor: pointer; }
    tr.row-clickable:hover { background: #f7fafc; }
    tr.expanded + tr.detail-row td { padding: 0; vertical-align: top; background: #fafafa; }
    .detail-cell { padding: 1rem 1.5rem !important; }
    .detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; }
    .detail-block { background: white; border: 1px solid #e2e8f0; border-radius: 6px; padding: 1rem; }
    .detail-block h4 { margin: 0 0 0.5rem; font-size: 0.8rem; font-weight: 600; color: #4a5568; display: flex; align-items: center; gap: 0.5rem; }
    .detail-block p { margin: 0; font-size: 0.9rem; line-height: 1.5; color: #2d3748; }
    .detail-block.summary h4 { color: #4a5568; }
    .detail-block.strengths h4 { color: #276749; }
    .detail-block.gaps h4 { color: #c05621; }
    .score-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 36px; padding: 0.25rem 0.5rem; border-radius: 9999px; font-weight: 600; font-size: 0.9rem; }
    .score-badge.high { background: #c6f6d5; color: #276749; }
    .score-badge.mid { background: #feebc8; color: #c05621; }
    .score-badge.low { background: #fed7d7; color: #c53030; }
    .link-view { color: #805ad5; text-decoration: none; font-weight: 500; }
    .link-view:hover { text-decoration: underline; }
    .meta { font-size: 0.8rem; color: #718096; margin-top: 0.2rem; }
    #results-section { display: none; }
    #results-section.visible { display: block; }
    #table-wrap { overflow-x: auto; }
    .field-static { padding: 0.5rem 0.75rem; font-size: 0.95rem; color: #4a5568; background: #edf2f7; border-radius: 6px; min-width: 140px; }
    .field-file { padding: 0.35rem 0; font-size: 0.9rem; }
    .job-rows { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1rem; }
    .job-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.75rem; padding: 0.75rem; background: #f7fafc; border-radius: 8px; border: 1px solid #e2e8f0; }
    .job-row .field { min-width: 0; }
    .job-row .field.job-id { flex: 1; min-width: 120px; }
    .job-row .field.rubric { flex: 1; min-width: 180px; }
    .job-row .btn-remove { flex-shrink: 0; padding: 0.5rem 0.75rem; font-size: 0.85rem; background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; color: #718096; cursor: pointer; }
    .job-row .btn-remove:hover { background: #fed7d7; color: #c53030; border-color: #feb2b2; }
    .add-job-wrap { margin-bottom: 1rem; }
    .terminal { background: #1a202c; color: #e2e8f0; font-family: ui-monospace, monospace; font-size: 0.8rem; padding: 1rem; border-radius: 8px; min-height: 200px; max-height: 400px; overflow: auto; white-space: pre-wrap; word-break: break-all; margin-bottom: 1rem; }
    .terminal-title { font-size: 0.75rem; font-weight: 600; color: #718096; text-transform: uppercase; letter-spacing: 0.02em; margin-bottom: 0.5rem; }
    .badge-pill { display: inline-flex; align-items: center; padding: 0.15rem 0.5rem; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; background: #ebf8ff; color: #2b6cb0; text-transform: uppercase; letter-spacing: 0.02em; }
  </style>
</head>
<body>
  <header class="header">
    <div>
      <h1><span aria-hidden="true">&#129302;</span> AI Recruitment System</h1>
      <p class="subtitle">Powered by GPT-4o-mini &middot; Manatal ATS &middot; Airtable</p>
    </div>
    <span class="live" id="live-status">Live</span>
  </header>
  <main class="container">
    <section class="card">
      <h2>Run AI Candidate Scoring</h2>
      <form id="form">
        <div class="job-rows" id="job-rows"></div>
        <div class="add-job-wrap">
          <button type="button" class="btn-run" id="btn-add-job" style="background: #4a5568;">+ Add job</button>
        </div>
        <div class="run-row" style="margin-top: 1rem;">
          <div class="field">
            <label>PIPELINE STAGE</label>
            <input type="text" id="stage-input" class="field-input-stage" value="New Candidates" placeholder="New Candidates" />
          </div>
          <div class="field">
            <label>TIER 2 CUTOFF (%)</label>
            <input type="number" id="cutoff-input" class="field-input-cutoff" min="0" max="100" placeholder="60 = default" style="min-width: 120px;" />
          </div>
          <button type="submit" class="btn-run" id="btn">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
            Run AI Scoring
          </button>
        </div>
      </form>
    </section>
    <div class="status-bar" id="status-bar"></div>
    <section class="card">
      <div class="terminal-title">Terminal</div>
      <div class="terminal" id="terminal">No output yet. Run AI Scoring to see pipeline logs.</div>
    </section>
    <section id="stats-section" class="stats" style="display: none;"></section>
    <section class="card" id="results-section">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
        <h2>Candidate Results</h2>
        <span class="meta" id="results-meta"></span>
      </div>
      <div id="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>CANDIDATE</th>
              <th>CURRENT ROLE</th>
              <th>SCORE</th>
              <th>STAGE</th>
              <th>RESUME</th>
            </tr>
          </thead>
          <tbody id="results-body"></tbody>
        </table>
      </div>
    </section>
    <section class="card" id="tier1-section" style="display: none;">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
        <h2>Report Results</h2>
        <span class="badge-pill">High-scoring &amp; rescored</span>
      </div>
      <span class="meta" id="tier1-meta"></span>
      <div id="tier1-table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>CANDIDATE</th>
              <th>CURRENT ROLE</th>
              <th>NEW SCORE</th>
              <th>STAGE</th>
              <th>RESUME</th>
              <th>REPORT</th>
            </tr>
          </thead>
          <tbody id="tier1-body"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    var pollInterval = null;
    var logPollInterval = null;
    var rowCount = 0;
    function $(id) { return document.getElementById(id); }
    function addJobRow(jobIdVal) {
      var container = $("job-rows");
      var row = document.createElement("div");
      row.className = "job-row";
      row.dataset.rowId = (++rowCount);
      var jobId = "job_id_" + row.dataset.rowId;
      var rubricId = "rubric_" + row.dataset.rowId;
      row.innerHTML = '<div class="field job-id"><label for="' + jobId + '">JOB ID</label><input type="text" id="' + jobId + '" class="job-id-input" placeholder="e.g. 3419430" required></div>' +
        '<div class="field rubric"><label for="' + rubricId + '">RUBRIC (optional)</label><input type="file" id="' + rubricId + '" class="rubric-input" accept=".json"></div>' +
        '<button type="button" class="btn-remove" aria-label="Remove job">Remove</button>';
      row.querySelector(".job-id-input").value = jobIdVal || "";
      row.querySelector(".btn-remove").addEventListener("click", function() {
        if (container.querySelectorAll(".job-row").length > 1) row.remove();
      });
      container.appendChild(row);
    }
    function initJobRows() {
      var container = $("job-rows");
      container.innerHTML = "";
      addJobRow("3419430");
    }
    document.addEventListener("DOMContentLoaded", function() {
      initJobRows();
      $("btn-add-job").addEventListener("click", function() { addJobRow(""); });
    });
    function showStatus(msg, type) {
      var bar = $("status-bar");
      bar.textContent = msg;
      bar.className = "status-bar " + (type || "success");
      bar.style.display = "flex";
    }
    function stopPolling() {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = null;
    }
    var logStreamSource = null;
    var logPollFallbackInterval = null;
    var lastLogLength = 0;
    function stopLogStream() {
      if (logStreamSource) { logStreamSource.close(); logStreamSource = null; }
      if (logPollFallbackInterval) { clearInterval(logPollFallbackInterval); logPollFallbackInterval = null; }
    }
    function startLogStream() {
      stopLogStream();
      var el = $("terminal");
      el.textContent = "";
      lastLogLength = 0;
      var sseReceived = false;
      var url = "/logs/stream";
      logStreamSource = new EventSource(url);
      logStreamSource.onmessage = function(e) {
        sseReceived = true;
        var line = e.data;
        el.textContent += line + "\n";
        el.scrollTop = el.scrollHeight;
      };
      logStreamSource.addEventListener("done", function() {
        if (logStreamSource) { logStreamSource.close(); logStreamSource = null; }
      });
      logStreamSource.onerror = function() {
        if (logStreamSource) { logStreamSource.close(); logStreamSource = null; }
        startLogPollFallback();
      };
      setTimeout(function() {
        if (!sseReceived && logStreamSource) {
          logStreamSource.close();
          logStreamSource = null;
          startLogPollFallback();
        }
      }, 2500);
    }
    function startLogPollFallback() {
      if (logPollFallbackInterval) return;
      var el = $("terminal");
      function poll() {
        fetch("/logs").then(function(r) { return r.json(); }).then(function(data) {
          var logs = data.logs || "";
          if (lastLogLength === 0) {
            el.textContent = logs;
            lastLogLength = logs.length;
          } else if (logs.length > lastLogLength) {
            el.textContent += logs.slice(lastLogLength);
            lastLogLength = logs.length;
          }
          el.scrollTop = el.scrollHeight;
          if (!data.running && logPollFallbackInterval) {
            clearInterval(logPollFallbackInterval);
            logPollFallbackInterval = null;
          }
        }).catch(function() {});
      }
      poll();
      logPollFallbackInterval = setInterval(poll, 300);
    }
    function renderStats(candidates) {
      var n = candidates.length;
      var scores = candidates.map(function(c) { return c.ai_score != null ? Number(c.ai_score) : 0; }).filter(function(s) { return !isNaN(s); });
      var total = n;
      var avg = scores.length ? Math.round(scores.reduce(function(a,b){ return a+b; }, 0) / scores.length) : 0;
      var top = scores.length ? Math.max.apply(null, scores) : 0;
      var errors = 0;
      var section = $("stats-section");
      section.innerHTML = '<div class="stat"><div class="label">Total Processed</div><div class="value blue">' + total + '</div></div>' +
        '<div class="stat"><div class="label">Average Score</div><div class="value purple">' + avg + '</div></div>' +
        '<div class="stat"><div class="label">Top Score</div><div class="value green">' + top + '</div></div>' +
        '<div class="stat"><div class="label">Errors</div><div class="value black">' + errors + '</div></div>';
      section.style.display = "grid";
    }
    function scoreClass(s) {
      if (s >= 70) return "high";
      if (s >= 50) return "mid";
      return "low";
    }
    function renderTable(candidates) {
      var tbody = $("results-body");
      tbody.innerHTML = "";
      candidates.forEach(function(c, i) {
        var score = c.ai_score != null ? Number(c.ai_score) : 0;
        var scoreCl = scoreClass(isNaN(score) ? 0 : score);
        var row = document.createElement("tr");
        row.className = "row-clickable";
        row.dataset.idx = i;
        row.innerHTML = "<td>" + (i + 1) + "</td>" +
          "<td><strong>" + (c.full_name || "—") + "</strong><div class=\"meta\">" + (c.email || "") + "</div></td>" +
          "<td><strong>" + (c.job_name || "—") + "</strong><div class=\"meta\">" + (c.org_name || "") + "</div></td>" +
          "<td><span class=\"score-badge " + scoreCl + "\">" + (isNaN(score) ? "—" : score) + "</span></td>" +
          "<td>" + (c.match_stage_name || "—") + "</td>" +
          "<td>" + (c.resume_file ? "<a class=\"link-view\" href=\"" + c.resume_file + "\" target=\"_blank\" rel=\"noopener\">View</a>" : "—") + "</td>";
        row.addEventListener("click", function() {
          var next = row.nextElementSibling;
          if (next && next.classList.contains("detail-row")) {
            next.remove();
            row.classList.remove("expanded");
            return;
          }
          document.querySelectorAll("tr.expanded").forEach(function(r) {
            var n = r.nextElementSibling;
            if (n && n.classList.contains("detail-row")) n.remove();
            r.classList.remove("expanded");
          });
          var detailRow = document.createElement("tr");
          detailRow.className = "detail-row";
          var td = document.createElement("td");
          td.colSpan = 6;
          td.className = "detail-cell";
          td.innerHTML = "<div class=\"detail-grid\">" +
            "<div class=\"detail-block summary\"><h4>&#128214; Summary</h4><p>" + (c.ai_summary || "—") + "</p></div>" +
            "<div class=\"detail-block strengths\"><h4>&#10004; Strengths</h4><p>" + (c.ai_strengths || "—") + "</p></div>" +
            "<div class=\"detail-block gaps\"><h4>&#9888; Gaps</h4><p>" + (c.ai_gaps || "—") + "</p></div>" +
            "</div>";
          detailRow.appendChild(td);
          row.after(detailRow);
          row.classList.add("expanded");
        });
        tbody.appendChild(row);
      });
      $("results-section").classList.add("visible");
      $("results-meta").textContent = candidates.length + " candidates · sorted by score";
    }
    function renderTier1Table(candidates) {
      var section = $("tier1-section");
      var tbody = $("tier1-body");
      var meta = $("tier1-meta");
      if (!section || !tbody || !meta) return;
      if (!candidates || !candidates.length) {
        section.style.display = "none";
        tbody.innerHTML = "";
        meta.textContent = "";
        return;
      }
      section.style.display = "block";
      meta.textContent = candidates.length + " candidates with reports";
      tbody.innerHTML = "";
      candidates.forEach(function(c, i) {
        var score = c.ai_report_score != null ? Number(c.ai_report_score) : (c.ai_score != null ? Number(c.ai_score) : 0);
        var scoreCl = scoreClass(isNaN(score) ? 0 : score);
        var row = document.createElement("tr");
        row.innerHTML =
          "<td>" + (i + 1) + "</td>" +
          "<td><strong>" + (c.full_name || "—") + "</strong><div class=\"meta\">" + (c.email || "") + "</div></td>" +
          "<td><strong>" + (c.job_name || "—") + "</strong><div class=\"meta\">" + (c.org_name || "") + "</div></td>" +
          "<td><span class=\"score-badge " + scoreCl + "\">" + (isNaN(score) ? "—" : score) + "</span></td>" +
          "<td>Report</td>" +
          "<td>" + (c.resume_file ? "<a class=\"link-view\" href=\"" + c.resume_file + "\" target=\"_blank\" rel=\"noopener\">View</a>" : "—") + "</td>" +
          "<td>" + (c.ai_report_html ? "<a class=\"link-view\" href=\"" + c.ai_report_html + "\" target=\"_blank\" rel=\"noopener\">View report</a>" : "N/A") + "</td>";
        tbody.appendChild(row);
      });
    }
    function pollResults(jobId) {
      stopPolling();
      pollInterval = setInterval(function() {
        Promise.all([
          fetch("/results?job_ids=" + encodeURIComponent(jobId)).then(function(r) { return r.json(); }),
          fetch("/logs").then(function(r) { return r.json(); })
        ]).then(function(results) {
          var data = results[0];
          var logState = results[1];
          var list = data.candidates || [];
          var running = logState && logState.running;
          if (list.length > 0) {
            renderStats(list);
            renderTable(list);
            var tier = data.tier1 || list.filter(function(c) { return c.ai_report_html; });
            renderTier1Table(tier);
            if (running) {
              showStatus(list.length + " candidate(s) scored. Generating report...", "running");
            } else {
              stopPolling();
              if (tier.length > 0) {
                showStatus("Done. Reports generated", "success");
              } else {
                showStatus(list.length + " candidate(s) scored. Click any row to expand details.", "success");
              }
            }
          }
        }).catch(function() {});
      }, 5000);
    }
    $("form").addEventListener("submit", function(e) {
      e.preventDefault();
      var rows = document.querySelectorAll(".job-row");
      var jobIds = [];
      var formData = new FormData();
      var stageInput = document.getElementById("stage-input");
      var stageVal = (stageInput && stageInput.value) ? stageInput.value.trim() : "";
      formData.append("stage", stageVal || "New Candidates");
      var cutoffInput = document.getElementById("cutoff-input");
      if (cutoffInput && cutoffInput.value !== "" && !isNaN(parseInt(cutoffInput.value, 10))) {
        var n = parseInt(cutoffInput.value, 10);
        if (n >= 0 && n <= 100) formData.append("min_score_for_report", String(n));
      }
      rows.forEach(function(row) {
        var idInput = row.querySelector(".job-id-input");
        var rubricInput = row.querySelector(".rubric-input");
        var jid = (idInput && idInput.value) ? idInput.value.trim() : "";
        if (jid) {
          jobIds.push(jid);
          if (rubricInput && rubricInput.files && rubricInput.files[0])
            formData.append("rubric_" + jid, rubricInput.files[0]);
        }
      });
      var jobIdStr = jobIds.join(", ");
      if (!jobIdStr) return;
      formData.append("job_ids", jobIdStr);
      var btn = $("btn");
      btn.disabled = true;
      $("terminal").textContent = "Starting pipeline…";
      showStatus("Running AI scoring. Watch the terminal below.", "running");
      fetch("/run/form", { method: "POST", body: formData })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.status === "accepted" || data.job_ids) {
            showStatus("Pipeline started. Watch the terminal for live output.", "running");
            startLogStream();
            pollResults(jobIdStr);
            setTimeout(function() {
              if (pollInterval) {
                showStatus("Still running. Results will appear when scoring finishes.", "running");
              }
            }, 60000);
          } else {
            showStatus("Error: " + (data.detail || data.error || "Unknown"), "error");
          }
        })
        .catch(function(err) {
          showStatus("Error: " + err.message, "error");
        })
        .finally(function() { btn.disabled = false; });
    });
    fetch("/health").then(function(r) { return r.json(); }).then(function() { $("live-status").textContent = "Live"; }).catch(function() { $("live-status").textContent = "Offline"; });
  </script>
</body>
</html>
"""

HERE = Path(__file__).resolve().parent
PIPELINE_SCRIPT = HERE / "online_pipeline.py"
RUBRIC_DIR = HERE / "rubrics"

# Optional: job IDs to use when running via cron (set RENDER_CRON_JOB_IDS in Render)
CRON_JOB_IDS = os.getenv("RENDER_CRON_JOB_IDS", "").strip()

# Pipeline log capture for terminal UI (thread-safe: main reads, pipeline thread writes)
_pipe_state: dict = {"logs": [], "running": False}
_pipe_lock = threading.Lock()

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
    stage: str | None = Field(default=None, description="Pipeline stage (e.g. New Candidates). Uses TARGET_STAGE_NAME if not set.")
    min_score_for_report: int | None = Field(default=None, description="Tier 2 cutoff 0-100. If not set, config default (60) is used.")
    skip_scoring: bool = False
    skip_upload: bool = False
    skip_reports: bool = False


def _normalize_job_ids(job_ids: str | list[str]) -> str:
    if isinstance(job_ids, list):
        return ", ".join(str(j).strip() for j in job_ids)
    return str(job_ids).strip()


def _run_pipeline_sync(
    job_ids: str,
    skip_scoring: bool,
    skip_upload: bool,
    skip_reports: bool,
    stage: str | None = None,
    min_score_for_report: int | None = None,
) -> int:
    """Run online_pipeline.py in current process. Returns exit code."""
    # Use unbuffered mode so logs flush line-by-line
    cmd = [sys.executable, "-u", str(PIPELINE_SCRIPT), job_ids]
    if skip_scoring:
        cmd.append("--skip-scoring")
    if skip_upload:
        cmd.append("--skip-upload")
    if skip_reports:
        cmd.append("--skip-reports")
    env = os.environ.copy()
    # Ensure all Python subprocesses run unbuffered so terminal gets real-time output
    env["PYTHONUNBUFFERED"] = "1"
    if stage:
        env["TARGET_STAGE_NAME"] = stage
    if min_score_for_report is not None:
        env["MIN_SCORE_FOR_REPORT"] = str(min_score_for_report)
    result = subprocess.run(cmd, cwd=str(HERE), env=env)
    return result.returncode


def _run_pipeline_with_logs(
    job_ids: str,
    skip_scoring: bool = False,
    skip_upload: bool = False,
    skip_reports: bool = False,
    stage: str | None = None,
    min_score_for_report: int | None = None,
) -> None:
    """Run pipeline and capture stdout/stderr to _pipe_state for terminal UI."""
    with _pipe_lock:
        _pipe_state["logs"] = [f"Pipeline started for job(s): {job_ids}", ""]
        _pipe_state["running"] = True
    # Use unbuffered mode so logs flush line-by-line
    cmd = [sys.executable, "-u", str(PIPELINE_SCRIPT), job_ids]
    if skip_scoring:
        cmd.append("--skip-scoring")
    if skip_upload:
        cmd.append("--skip-upload")
    if skip_reports:
        cmd.append("--skip-reports")
    env = os.environ.copy()
    # Ensure all Python subprocesses run unbuffered so terminal gets real-time output
    env["PYTHONUNBUFFERED"] = "1"
    if stage:
        env["TARGET_STAGE_NAME"] = stage
    if min_score_for_report is not None:
        env["MIN_SCORE_FOR_REPORT"] = str(min_score_for_report)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(HERE),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if proc.stdout:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                with _pipe_lock:
                    _pipe_state["logs"].append(line.rstrip())
        proc.wait()
    except Exception as e:
        with _pipe_lock:
            _pipe_state["logs"].append(f"[ERROR] {e}")
    finally:
        with _pipe_lock:
            _pipe_state["running"] = False


@app.get("/", response_class=HTMLResponse)
def root():
    """Run Pipeline UI — open this link in the browser to trigger the pipeline."""
    return RUN_UI_HTML


@app.get("/api")
def api_info():
    """JSON API info for scripts."""
    return {
        "service": "airtable-pipeline",
        "docs": "/docs",
        "health": "/health",
        "run": "POST /run with body: { \"job_ids\": \"3419430\" }",
    }


@app.get("/health")
def health():
    """Health check for Render (and load balancers)."""
    return {"status": "ok"}


@app.get("/results")
def get_results(
    job_id: str | None = Query(None, description="Single job ID (legacy)"),
    job_ids: str | None = Query(None, description="Comma-separated job IDs for multiple jobs"),
):
    """Return scored candidates for one or more jobs from Airtable (for the dashboard UI)."""
    try:
        from config import Config
        from airtable_client import AirtableClient
    except ImportError:
        raise HTTPException(status_code=500, detail="Config or AirtableClient not available")

    if not Config.AIRTABLE_TOKEN:
        raise HTTPException(status_code=503, detail="Airtable not configured")

    raw = (job_ids or job_id or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="job_id or job_ids is required")

    ids_str = [s.strip() for s in raw.split(",") if s.strip()]
    try:
        jids = [int(x) for x in ids_str]
    except ValueError:
        raise HTTPException(status_code=400, detail="job_id(s) must be numeric")
    if not jids:
        raise HTTPException(status_code=400, detail="At least one job_id is required")

    try:
        client = AirtableClient()
        formula = "OR(" + ",".join(f"{{job_id}}={jid}" for jid in jids) + ")"
        records = client.get_records_by_formula(formula)

        rows = []
        for rec in records:
            f = rec.get("fields", {})
            # Normalise ai_report_html: Airtable stores it as attachments list
            report_html = None
            attachments = f.get("ai_report_html")
            if isinstance(attachments, list) and attachments:
                report_html = attachments[0].get("url")

            rows.append({
                "candidate_id": f.get("candidate_id"),
                "job_id": f.get("job_id"),
                "job_name": f.get("job_name"),
                "org_name": f.get("organisation_name"),
                "full_name": f.get("full_name"),
                "email": f.get("email"),
                "resume_file": f.get("resume_file"),
                "match_stage_name": f.get("match_stage_name"),
                "ai_score": f.get("tier2_score") or f.get("tier1_score"),
                "ai_summary": f.get("ai_summary"),
                "ai_strengths": f.get("ai_strengths"),
                "ai_gaps": f.get("ai_gaps"),
                "ai_report_html": report_html,
            })

        # Sort by score descending
        rows.sort(key=lambda c: (c.get("ai_score") or 0), reverse=True)
        tier1 = [c for c in rows if c.get("ai_report_html")]
        return {"candidates": rows, "tier1": tier1, "job_id": jids[0], "job_ids": jids}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/logs")
def get_logs():
    """Return captured pipeline stdout for the terminal UI."""
    with _pipe_lock:
        logs = list(_pipe_state["logs"])
        running = _pipe_state["running"]
    return {"logs": "\n".join(logs), "running": running}


@app.get("/logs/stream")
async def logs_stream():
    """Stream log lines as Server-Sent Events so the UI shows output line-by-line like a terminal."""
    async def generate():
        last_idx = 0
        last_keepalive = 0
        while True:
            with _pipe_lock:
                logs = list(_pipe_state["logs"])
                running = _pipe_state["running"]
            while last_idx < len(logs):
                line = logs[last_idx]
                last_idx += 1
                for part in line.split("\n"):
                    yield f"data: {part}\n"
                yield "\n"
            if not running and last_idx >= len(logs):
                yield "event: done\ndata: ok\n\n"
                return
            # Keepalive so proxies (e.g. Render) flush the stream
            last_keepalive += 1
            if last_keepalive >= 6:  # ~0.5s at 0.08 sleep
                yield ": keepalive\n\n"
                last_keepalive = 0
            await asyncio.sleep(0.08)
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/run/form")
async def run_pipeline_form(request: Request):
    """
    Trigger the pipeline from the dashboard form.
    Form fields: job_ids (comma-separated), stage, and optional rubric_<job_id> file per job.
    Each rubric_<job_id> is saved as rubrics/rubric_<job_id>.json.
    """
    form = await request.form()
    job_ids = form.get("job_ids")
    if not job_ids or not str(job_ids).strip():
        raise HTTPException(status_code=400, detail="job_ids is required")
    job_ids_norm = _normalize_job_ids(str(job_ids).strip())
    stage = str(form.get("stage") or "New Candidates").strip()
    min_score_raw = form.get("min_score_for_report")
    min_score_for_report: int | None = None
    if min_score_raw is not None and str(min_score_raw).strip() != "":
        try:
            n = int(str(min_score_raw).strip())
            if 0 <= n <= 100:
                min_score_for_report = n
        except ValueError:
            pass

    RUBRIC_DIR.mkdir(parents=True, exist_ok=True)
    for key in form.keys():
        if not key.startswith("rubric_") or key == "rubric_":
            continue
        job_id = key[7:].strip()
        if not job_id:
            continue
        value = form.get(key)
        if value is not None and hasattr(value, "read"):
            content = await value.read()
            path = RUBRIC_DIR / f"rubric_{job_id}.json"
            path.write_bytes(content)

    def _run():
        _run_pipeline_with_logs(
            job_ids_norm,
            skip_scoring=False,
            skip_upload=False,
            skip_reports=False,
            stage=stage or "New Candidates",
            min_score_for_report=min_score_for_report,
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {
        "status": "accepted",
        "message": "Pipeline started. Watch the terminal for output.",
        "job_ids": job_ids_norm,
    }


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
        _run_pipeline_with_logs(
            job_ids,
            request.skip_scoring,
            request.skip_upload,
            request.skip_reports,
            request.stage,
            request.min_score_for_report,
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {
        "status": "accepted",
        "message": "Pipeline started in background. Watch the terminal for output.",
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
        request.stage,
        request.min_score_for_report,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=f"Pipeline exited with code {code}")
    return {"status": "completed", "job_ids": job_ids}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
