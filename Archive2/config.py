#!/usr/bin/env python3
"""
config.py - Configuration, utilities, API helpers, and extraction functions.

Shared by scoring.py and main.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from pypdf import PdfReader
import docx
from dotenv import load_dotenv

load_dotenv()

# =========================
# CONFIG (edit here)
# =========================

# Two-Tier Configuration
TIER1_MODEL = "gpt-4o-mini"          # Fast screening
TIER2_MODEL = "gpt-4o"          # Detailed evaluation (change to "gpt-4o" for better quality)
TIER1_PASS_THRESHOLD = 65            # Candidates >= 65 proceed to Tier 2

# Job selection
TARGET_STAGE_NAME = "Processing"
PAGE_SIZE = 100

# Paths
EXPORT_PATH = os.getenv("EXPORT_PATH", "export")
RUBRIC_DIR  = os.getenv("RUBRIC_DIR",  "rubrics")
CACHE_FILE  = os.getenv("CACHE_FILE",  "scored_cache.json")

# Behavior
SKIP_ALREADY_SCORED = True
FORCE_RESCORE = False
DOWNLOAD_RESUMES = True

# Limits
MAX_RESUME_CHARS = 30_000
MAX_RUBRIC_CHARS = 50_000

# Airtable
WRITE_TO_AIRTABLE = True
AIRTABLE_BATCH_SIZE = 10
AIRTABLE_RETRY_ATTEMPTS = 3

# CSV Backup
WRITE_CSV_BACKUP = True

BASE_URL = "https://api.manatal.com/open/v3"

# =========================
# Secrets (from .env)
# =========================
MANATAL_API_TOKEN = os.getenv("MANATAL_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_ID = os.getenv("AIRTABLE_TABLE_ID")


# =========================
# Utility helpers
# =========================
def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def safe_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\-. ]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:180] if s else "export"


def clip(s: str, n: int) -> str:
    s = s or ""
    return s[:n]


# =========================
# Rubric + cache
# =========================
def load_rubric_json(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Rubric JSON not found: {p}")
    rubric_text = p.read_text(encoding="utf-8", errors="ignore")
    rubric_text = rubric_text[:MAX_RUBRIC_CHARS]
    return json.loads(rubric_text)


def rubric_compact_json(rubric: dict) -> str:
    return json.dumps(rubric, ensure_ascii=False, separators=(",", ":"))


def load_cache(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(path: str, data: dict) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================
# HTTP / Manatal helpers
# =========================
def manatal_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Token {MANATAL_API_TOKEN}",
        "accept": "application/json",
    }


def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, headers=manatal_headers(), params=params, timeout=60)
    if not resp.ok:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        raise RuntimeError(f"GET {url} failed: {resp.status_code}\n{body}")
    return resp.json()


def fetch_all_paginated(
    path: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_path = path
    next_params = dict(params or {})
    next_params.setdefault("page_size", PAGE_SIZE)

    while True:
        data = api_get(next_path, params=next_params)

        if isinstance(data, list):
            items.extend(data)
            break

        if isinstance(data, dict) and "results" in data:
            items.extend(data.get("results") or [])
            nxt = data.get("next")
            if not nxt:
                break

            m = re.search(r"https?://[^/]+(/open/v3/.*)$", str(nxt))
            if not m:
                raise RuntimeError(f"Pagination 'next' not recognized: {nxt}")
            rel = m.group(1).replace("/open/v3", "")
            next_path = rel
            next_params = {}
            continue

        raise RuntimeError(f"Unexpected response shape for {path}: {data}")

    return items


# =========================
# Extraction helpers
# =========================
def extract_stage_name(match: Dict[str, Any]) -> Optional[str]:
    for key in ("job_pipeline_stage", "stage"):
        v = match.get(key)
        if isinstance(v, dict) and v.get("name"):
            return str(v["name"])
    return None


def extract_candidate_id(match: Dict[str, Any]) -> Optional[int]:
    v = match.get("candidate")
    if isinstance(v, int):
        return v
    if isinstance(v, dict) and isinstance(v.get("id"), int):
        return v["id"]
    return None


def get_job_and_org(
    job_id: str,
) -> Tuple[Dict[str, Any], str, Optional[int], Optional[str], str]:
    job = api_get(f"/jobs/{job_id}/")
    job_name = (
        job.get("position_name")
        or job.get("name")
        or job.get("title")
        or f"job_{job_id}"
    )

    org_id: Optional[int] = None
    org_name: Optional[str] = None
    org = job.get("organization")

    if isinstance(org, dict):
        if isinstance(org.get("id"), int):
            org_id = org["id"]
        if org.get("name"):
            org_name = str(org["name"])
    elif isinstance(org, int):
        org_id = org
        try:
            org_obj = api_get(f"/organizations/{org_id}/")
            if isinstance(org_obj, dict) and org_obj.get("name"):
                org_name = str(org_obj["name"])
        except Exception:
            org_name = None

    org_name = org_name or job.get("organization_name") or job.get("client_name")
    jd_text = (
        job.get("job_description")
        or job.get("description")
        or job.get("details")
        or ""
    )

    return job, str(job_name), org_id, org_name, str(jd_text or "")


def maybe_fill_org_from_match(
    match: Dict[str, Any],
    org_id: Optional[int],
    org_name: Optional[str],
) -> Tuple[Optional[int], Optional[str]]:
    if org_name:
        return org_id, org_name
    mo = match.get("organization")
    if isinstance(mo, dict):
        if isinstance(mo.get("id"), int) and not org_id:
            org_id = mo["id"]
        if mo.get("name") and not org_name:
            org_name = str(mo["name"])
    return org_id, org_name


def extract_resume_url_from_candidate(candidate: Dict[str, Any]) -> Optional[str]:
    for k in ("resume_file", "resume_url", "resume", "cv_url", "cv_file", "cv"):
        v = candidate.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    res = candidate.get("resume")
    if isinstance(res, dict):
        for kk in ("resume_file", "url", "file"):
            v = res.get(kk)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return None


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=90)
    if not resp.ok:
        raise RuntimeError(f"Download failed: {resp.status_code}")
    dest.write_bytes(resp.content)


def resume_text_from_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    elif ext in (".docx", ".doc"):
        try:
            doc = docx.Document(str(path))
            return "\n".join(para.text for para in doc.paragraphs)
        except Exception:
            return ""
    elif ext == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""

def clear_cache_for_job(cache_path: str, job_id: str, tier: str = "all") -> int:
    cache = load_cache(cache_path)
    before = len(cache)
    if tier == "all":
        cache = {k: v for k, v in cache.items() if not k.startswith(f"{job_id}-")}
    else:
        suffix = f"-{tier}"
        cache = {k: v for k, v in cache.items()
                 if not (k.startswith(f"{job_id}-") and k.endswith(suffix))}
    save_cache(cache_path, cache)
    return before - len(cache)