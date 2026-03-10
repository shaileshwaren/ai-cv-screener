#!/usr/bin/env python3
# python8.py - AI Scoring Script (Updated to use consolidated modules)
from __future__ import annotations

import csv
import json
import os
import re
import sys
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import OpenAI

# Import from consolidated modules
from config import Config
from utils import sha256_text, safe_filename, clip, extract_resume_text
from airtable_client import AirtableClient


# =========================
# Constants
# =========================
BASE_URL = Config.MANATAL_BASE_URL


# =========================
# Offline input loader
# =========================
def load_offline_input(path: str) -> Dict[str, Any]:
    """Load offline input JSON for local testing (no Manatal API required)."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Offline input not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if "candidates" not in data or not isinstance(data["candidates"], list):
        raise ValueError("Offline input JSON must contain a list field: candidates")
    return data


# =========================
# Rubric + cache
# =========================
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


def load_job_description_for_scoring(job_id: str, offline_data: dict) -> str:
    """Load JD from external file or JSON (same priority as generate_detailed_reports.py)
    
    Priority:
    1. offline_input/jd_{job_id}.txt (job-specific file)
    2. offline_input/jd.txt (generic file)
    3. offline_data["jd_text"] (embedded in JSON)
    """
    # Priority 1: Job-specific external file
    jd_file_specific = Path(f"offline_input/jd_{job_id}.txt")
    if jd_file_specific.exists():
        print(f"📄 Loading JD from {jd_file_specific}")
        return jd_file_specific.read_text(encoding="utf-8")
    
    # Priority 2: Generic JD file
    jd_file_generic = Path("offline_input/jd.txt")
    if jd_file_generic.exists():
        print(f"📄 Loading JD from {jd_file_generic}")
        return jd_file_generic.read_text(encoding="utf-8")
    
    # Priority 3: Embedded in JSON (fallback)
    jd_text = str(offline_data.get("jd_text") or "")
    if jd_text:
        print(f"📄 Loading JD from offline JSON (embedded)")
        return jd_text
    
    print("⚠️  WARNING: No JD found!")
    return ""


# =========================
# Manatal API helpers
# =========================
def manatal_headers() -> dict:
    return {
        "Authorization": f"Token {Config.MANATAL_API_TOKEN}",
        "Content-Type": "application/json",
    }


def api_get(endpoint: str) -> Any:
    url = BASE_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    resp = requests.get(url, headers=manatal_headers(), timeout=60)
    if not resp.ok:
        raise RuntimeError(f"Manatal GET {endpoint} failed: {resp.status_code}\n{resp.text[:500]}")
    return resp.json()


def fetch_all_paginated(endpoint: str, params: Optional[dict] = None) -> List[dict]:
    out = []
    url = BASE_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    p = params or {}
    while url:
        resp = requests.get(url, headers=manatal_headers(), params=p, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"Manatal GET paginated failed: {resp.status_code}\n{resp.text[:500]}")
        data = resp.json()
        results = data.get("results") or []
        out.extend(results)
        url = data.get("next")
        p = {}
    return out


# =========================
# Match/candidate helpers
# =========================
def extract_stage_name(match: Dict[str, Any]) -> Optional[str]:
    ps = match.get("job_pipeline_stage")
    if isinstance(ps, dict):
        return str(ps.get("name"))
    if isinstance(ps, str):
        return ps
    st = match.get("stage")
    if isinstance(st, dict):
        return str(st.get("name"))
    if isinstance(st, str):
        return st
    return None


def extract_candidate_id(match: Dict[str, Any]) -> Optional[int]:
    v = match.get("candidate")
    if isinstance(v, int):
        return v
    if isinstance(v, dict) and isinstance(v.get("id"), int):
        return v["id"]
    return None


def get_job_and_org(job_id: str) -> Tuple[Dict[str, Any], str, Optional[int], Optional[str], str]:
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

    # org as object
    if isinstance(org, dict):
        if isinstance(org.get("id"), int):
            org_id = org["id"]
        if org.get("name"):
            org_name = str(org["name"])

    # org as id
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
    org_name: Optional[str]
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
    # common fields in exports / payloads
    for k in ("resume_file", "resume_url", "resume", "cv_url", "cv_file", "cv"):
        v = candidate.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v

    # sometimes resume is nested object
    res = candidate.get("resume")
    if isinstance(res, dict):
        for kk in ("resume_file", "url", "file"):
            v = res.get(kk)
            if isinstance(v, str) and v.startswith("http"):
                return v

    return None


# =========================
# Resume download
# =========================
def download_file(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, headers=manatal_headers(), timeout=120, stream=True)
    if not resp.ok:
        raise RuntimeError(f"Download failed {resp.status_code}: {url}\n{resp.text[:500]}")
    with out_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)
    return out_path


# =========================
# LLM scoring – Tier 1
# =========================
def llm_score_tier1(oa: OpenAI, rubric_json: str, resume_text: str) -> Dict[str, Any]:
    """Tier 1 screening: returns score + brief summary, strengths, gaps.

    Scoring rules come entirely from the rubric. The response is a compact
    JSON so it stays fast and cheap while providing enough context to populate
    the Airtable Candidate record immediately at Step 2.
    Detailed per-criterion re-scoring happens at Step 3 for high scorers.
    """
    prompt = (
        "Score this resume strictly against the rubric below.\n"
        "Return ONLY this JSON object — no markdown, no extra text:\n"
        "{\n"
        '  "score": <integer 0-100>,\n'
        '  "summary": "<1-2 sentences: overall fit for the role>",\n'
        '  "strengths": "<comma-separated list, max 3 key strengths>",\n'
        '  "gaps": "<comma-separated list, max 3 key gaps>"\n'
        "}\n\n"
        f"RUBRIC:\n{rubric_json[:8000]}\n\n"
        f"RESUME:\n{clip(resume_text, Config.MAX_RESUME_CHARS)}"
    )

    _empty: Dict[str, Any] = {"score": 0, "ai_summary": "", "ai_strengths": "", "ai_gaps": ""}

    try:
        r = oa.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical recruiter. "
                        "Respond ONLY with valid JSON matching the exact schema requested. "
                        "No markdown, no code fences, no extra keys."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        text = (r.choices[0].message.content or "").strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            if text.startswith("json"):
                text = text[4:].strip()

        data = json.loads(text)
        score = max(0, min(100, int(data.get("score", 0))))
        return {
            "score": score,
            "ai_summary":   str(data.get("summary", "")).strip(),
            "ai_strengths": str(data.get("strengths", "")).strip(),
            "ai_gaps":      str(data.get("gaps", "")).strip(),
        }
    except Exception as e:
        print(f"  Tier 1 scoring error: {e}")
        # Fall back to integer-only prompt so we still get a score
        try:
            r2 = oa.chat.completions.create(
                model=Config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "Return ONLY a single integer 0-100. Nothing else."},
                    {"role": "user", "content": (
                        "Score this resume against the rubric. Return ONLY an integer 0-100.\n\n"
                        f"RUBRIC:\n{rubric_json[:8000]}\n\n"
                        f"RESUME:\n{clip(resume_text, Config.MAX_RESUME_CHARS)}"
                    )},
                ],
                temperature=0.1,
                max_tokens=10,
            )
            text2 = (r2.choices[0].message.content or "").strip()
            m = re.search(r"\d+", text2)
            fallback_score = max(0, min(100, int(m.group()))) if m else 0
            return {**_empty, "score": fallback_score}
        except Exception:
            return _empty


# =========================
# Main
# =========================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score Manatal job candidates (online via API or offline via JSON input)."
    )
    parser.add_argument("job_id", help="Manatal JOB_ID (must match rubrics/rubric_<JOB_ID>.json)")
    parser.add_argument("--offline", default="", help="Path to offline input JSON (skips Manatal API)")
    args = parser.parse_args()

    job_id = str(args.job_id).strip()
    offline_path = (args.offline or "").strip()

    if not job_id.isdigit():
        print(f"ERROR: JOB_ID must be numeric, got: {job_id}", file=sys.stderr)
        return 2

    # Validate configuration
    try:
        if offline_path:
            Config.validate()  # Only need OpenAI + Airtable
        else:
            Config.validate_online_mode()  # Needs Manatal too
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Ensure output directories exist
    Config.ensure_dirs()

    export_dir = Config.OUTPUT_DIR
    upload_dir = Config.UPLOAD_DIR

    # Load rubric: Airtable is the primary source of truth; local file is fallback only
    rubric = None
    try:
        at = AirtableClient()
        rubric = at.get_rubric(job_id)
        if rubric:
            print(f"Loaded rubric from Airtable for job_id={job_id}")
    except Exception as e:
        print(f"[WARN] Airtable rubric load failed: {e}")

    if not rubric:
        rubric_path = Config.get_rubric_path(job_id)
        if rubric_path.exists():
            try:
                rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
                print(f"[WARN] Airtable rubric not found — loaded from local file: {rubric_path}")
            except Exception as e:
                print(f"ERROR: Failed to parse local rubric at {rubric_path}: {e}", file=sys.stderr)
                return 2
        else:
            print(
                f"ERROR: No rubric found for job_id={job_id!r}.\n"
                "Run generate_rubric.py first to upload a rubric to Airtable.",
                file=sys.stderr,
            )
            return 2

    rubric_json = rubric_compact_json(rubric)
    # Version is in metadata.version for new JSON schema; fall back to top-level
    rubric_version = str(
        rubric.get("metadata", {}).get("version")
        or rubric.get("version", "unknown")
    )
    rubric_hash = sha256_text(rubric_json)[:12]

    # Cache load
    cache = load_cache(str(Config.CACHE_FILE))

    oa = OpenAI(api_key=Config.OPENAI_API_KEY)

    # Job info + JD + matches (online or offline)
    stage_name_override: Optional[str] = None

    if offline_path:
        offline = load_offline_input(offline_path)

        offline_job_id = str(offline.get("job_id", job_id)).strip()
        if offline_job_id and offline_job_id != job_id:
            print(f"ERROR: Offline input job_id mismatch: expected {job_id}, got {offline_job_id}", file=sys.stderr)
            return 2

        job_name = str(offline.get("job_name") or f"job_{job_id}")
        org_id = offline.get("organisation_id")
        org_name = offline.get("organisation_name")
        stage_name_override = str(offline.get("stage_name") or Config.TARGET_STAGE_NAME)

        # Build a Manatal-like matches list from offline candidates
        matches = []
        for c in offline.get("candidates", []):
            cid = c.get("candidate_id")
            if cid is None:
                continue
            matches.append(
                {
                    "created_at": c.get("created_at"),
                    "updated_at": c.get("updated_at"),
                    "job_pipeline_stage": {"name": stage_name_override},
                    "candidate": {
                        "id": int(cid),
                        "full_name": c.get("full_name"),
                        "email": c.get("email"),
                        # offline-only fields:
                        "resume_local_path": c.get("resume_local_path", ""),
                        "resume_file": c.get("resume_file", ""),
                    },
                    # optional organization override
                    "organization": {
                        "id": c.get("organisation_id"),
                        "name": c.get("organisation_name"),
                    }
                    if (c.get("organisation_id") or c.get("organisation_name"))
                    else None,
                }
            )
    else:
        _, job_name, org_id, org_name, _ = get_job_and_org(job_id)  # JD not needed
        matches = fetch_all_paginated(f"/jobs/{job_id}/matches/", params={"page_size": Config.MANATAL_PAGE_SIZE})

    # Calculate total candidates in target stage
    total_in_stage = sum(
        1 for m in matches 
        if extract_stage_name(m) == Config.TARGET_STAGE_NAME and extract_candidate_id(m) is not None
    )
    
    print(f"\nFound {total_in_stage} candidates in '{Config.TARGET_STAGE_NAME}' stage to process\n")

    base = safe_filename(f"manatal_job_{job_id}_{Config.TARGET_STAGE_NAME}")
    rows: List[Dict[str, Any]] = []
    current_num = 0

    for match in matches:
        stage_name = extract_stage_name(match)
        if stage_name != Config.TARGET_STAGE_NAME:
            continue

        candidate_id = extract_candidate_id(match)
        if not candidate_id:
            continue
            
        match_id = f"{job_id}-{candidate_id}"

        current_num += 1

        org_id, org_name = maybe_fill_org_from_match(match, org_id, org_name)

        candidate_obj = match.get("candidate")

        # Offline mode embeds candidate data inside match["candidate"].
        if offline_path and isinstance(candidate_obj, dict):
            candidate = candidate_obj
        else:
            candidate = api_get(f"/candidates/{candidate_id}/")

        full_name = candidate.get("full_name")
        email = candidate.get("email")

        # Offline mode uses a local resume path; online mode uses a resume URL.
        resume_local_path = str(candidate.get("resume_local_path") or "").strip()
        resume_url = str(candidate.get("resume_file") or "").strip() if resume_local_path else ""
        if not resume_local_path:
            resume_url = extract_resume_url_from_candidate(candidate)

        resume_text = ""

        # Unique cache key includes rubric + JD hash
        # Cache key: job + candidate + rubric (no JD hash - rubric is single source of truth)
        cache_key = f"{job_id}-{candidate_id}-{rubric_hash}"

        if Config.SKIP_ALREADY_SCORED and not Config.FORCE_RESCORE and cache_key in cache:
            cached = cache[cache_key]
            # Support both new (tier1_score) and legacy (ai_score) cache entries
            tier1_score = int(cached.get("tier1_score", cached.get("ai_score", 0)))
            score = {
                "ai_score":     tier1_score,
                "tier1_score":  tier1_score,
                "ai_summary":   cached.get("ai_summary", ""),
                "ai_strengths": cached.get("ai_strengths", ""),
                "ai_gaps":      cached.get("ai_gaps", ""),
            }
            resume_local_path = cached.get("resume_local_path", "")
            print(f"Skipped (cached): {current_num}/{total_in_stage}. {full_name} (ID: {candidate_id}) -> Tier1: {tier1_score}")
        else:
            t1_result: Dict[str, Any] = {"score": 0, "ai_summary": "", "ai_strengths": "", "ai_gaps": ""}

            def _run_tier1(text: str) -> Dict[str, Any]:
                if not text.strip():
                    return {"score": 0, "ai_summary": "", "ai_strengths": "", "ai_gaps": ""}
                return llm_score_tier1(oa, rubric_json, text)

            if resume_local_path:
                try:
                    p = Path(resume_local_path).expanduser()
                    if not p.is_absolute():
                        p = (Path.cwd() / p).resolve()
                    resume_text = extract_resume_text(p)
                    t1_result = _run_tier1(resume_text)
                except Exception as e:
                    print(f"  Resume parse error: {e}")

            elif resume_url and Config.DOWNLOAD_RESUMES:
                ext = Path(resume_url.split("?")[0]).suffix or ".pdf"
                out = export_dir / "resumes" / f"{candidate_id}-{safe_filename(full_name or str(candidate_id))}{ext}"
                try:
                    download_file(resume_url, out)
                    resume_local_path = str(out)
                    resume_text = extract_resume_text(out)
                    t1_result = _run_tier1(resume_text)
                except Exception as e:
                    print(f"  Resume download/parse error: {e}")

            # No resume available — fill all CV-dependent fields with a clear notice
            no_resume = not resume_text.strip()
            if no_resume:
                print(f"  [WARN] No resume found for {full_name} (ID: {candidate_id}) — CV-dependent fields set to notice")
                t1_result = {
                    "score":        0,
                    "ai_summary":   "No resume attached. CV-based scoring could not be completed.",
                    "ai_strengths": "No resume attached.",
                    "ai_gaps":      "No resume attached — unable to assess gaps.",
                }
                resume_text = "No resume attached."

            tier1_score = int(t1_result.get("score", 0))
            score = {
                "ai_score":     tier1_score,
                "tier1_score":  tier1_score,
                "ai_summary":   t1_result.get("ai_summary", ""),
                "ai_strengths": t1_result.get("ai_strengths", ""),
                "ai_gaps":      t1_result.get("ai_gaps", ""),
            }

            # Save to cache (include summary fields so re-runs don't re-score)
            cache[cache_key] = {
                "job_id":           job_id,
                "candidate_id":     candidate_id,
                "rubric_version":   rubric_version,
                "rubric_hash":      rubric_hash,
                "tier1_score":      tier1_score,
                "ai_score":         tier1_score,
                "ai_summary":       score["ai_summary"],
                "ai_strengths":     score["ai_strengths"],
                "ai_gaps":          score["ai_gaps"],
                "resume_local_path": resume_local_path,
            }
            save_cache(str(Config.CACHE_FILE), cache)
            no_resume_flag = "  [no resume]" if no_resume else ""
            print(f"Scored: {current_num}/{total_in_stage}. {full_name} (ID: {candidate_id}) -> Tier1: {tier1_score}{no_resume_flag}")

        tier1_score = int(score.get("tier1_score", score.get("ai_score", 0)))
        tier1_status = "PASS" if tier1_score >= Config.MIN_SCORE_FOR_REPORT else "FAIL"

        rows.append({
            "organisation_id": org_id,
            "organisation_name": org_name,
            "job_id": job_id,
            "job_name": job_name,
            "match_id": match_id,
            "created_at": match.get("created_at"),
            "updated_at": match.get("updated_at"),
            "match_stage_name": stage_name,
            "candidate_id": candidate_id,
            "full_name": full_name,
            "email": email,
            "resume_file": resume_url,
            "resume_local_path": resume_local_path,
            "cv_text":      clip(resume_text, Config.MAX_RESUME_CHARS) if resume_text else "No resume attached.",
            "tier1_score":  tier1_score,
            "tier1_status": tier1_status,
            "ai_score":     tier1_score,
            "ai_summary":   score.get("ai_summary", ""),
            "ai_strengths": score.get("ai_strengths", ""),
            "ai_gaps":      score.get("ai_gaps", ""),
            "ai_report_html": "",
            "rubric_version": rubric_version,
            "rubric_hash": rubric_hash,
            "cache_key": cache_key,
        })

    # Write outputs
    json_path = upload_dir / f"{base}_scored.json"
    csv_path  = upload_dir / f"{base}_scored.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    fieldnames = [
        "organisation_id", "organisation_name", "job_id", "job_name", "match_id",
        "created_at", "updated_at", "match_stage_name",
        "candidate_id", "full_name", "email",
        "resume_file", "resume_local_path",
        "cv_text",
        "tier1_score", "tier1_status",
        "ai_score", "ai_summary", "ai_strengths", "ai_gaps", "ai_report_html",
        "rubric_version", "rubric_hash", "cache_key",
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"\nDone. Rows: {len(rows)}")
    print(f"JSON: {json_path}")
    print(f"CSV : {csv_path}")
    print(f"Cache: {Config.CACHE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
