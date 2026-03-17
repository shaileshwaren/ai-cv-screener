#!/usr/bin/env python3
"""
generate_submission_report.py - Candidate Submission Report Generator.

Generates a professional .docx submission report for a candidate and uploads
it directly to the Airtable `ai_docx` attachment field.

Usage:
    python3 generate_submission_report.py <job_id> <candidate_id>

Architecture:
    1. Fetch Airtable record (ai_detailed_json, ai_summary, full_name, job_name)
    2. Load rubric JSON (for category classification: technical vs soft_skill)
    3. Fetch CV text from Manatal (for LLM metadata inference)
    4. LLM infers candidate metadata (location, nationality, relevant experience)
    5. Build .docx via build_report.js (Node/docx library — schema-valid XML)
    6. Upload .docx directly to Airtable ai_docx attachment field

Note (future fix):
    Category field (technical/soft_skill) should be carried through into
    ai_detailed_json during scoring so rubric re-fetch is not needed here.

CHANGE LOG:
    2026-03-13 14:45 - Added generate_report_bytes() — returns (docx_bytes, filename)
                       for FastAPI streaming download. generate_report() unchanged.
    2026-03-12 — Initial version. Uses Node.js/docx for schema-valid .docx output.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI
from pyairtable import Api

from config import (
    AIRTABLE_BASE_ID,
    AIRTABLE_TABLE_ID,
    AIRTABLE_TOKEN,
    MANATAL_API_TOKEN,
    OPENAI_API_KEY,
    RUBRIC_DIR,
    TIER1_MODEL,
    api_get,
    extract_resume_url_from_candidate,
    load_rubric_json,
    resume_text_from_file,
    safe_filename,
    download_file,
)

# Path to the JS builder — same directory as this script
JS_BUILDER = Path(__file__).parent / "build_report.js"


# ══════════════════════════════════════════════════════════════════════════════
# .docx builder — calls Node.js build_report.js
# ══════════════════════════════════════════════════════════════════════════════

def build_docx(payload: Dict) -> bytes:
    """
    Pipe JSON payload to build_report.js via stdin.
    Returns raw .docx bytes from stdout.
    """
    if not JS_BUILDER.exists():
        raise FileNotFoundError(f"build_report.js not found at {JS_BUILDER}")

    result = subprocess.run(
        ["node", str(JS_BUILDER)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        timeout=60,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"build_report.js failed:\n{stderr}")

    if not result.stdout:
        raise RuntimeError("build_report.js produced no output")

    return result.stdout


# ══════════════════════════════════════════════════════════════════════════════
# LLM: infer candidate metadata from CV text
# ══════════════════════════════════════════════════════════════════════════════

def infer_candidate_metadata(oa: OpenAI, resume_text: str, job_name: str) -> Dict[str, str]:
    """
    Ask LLM to extract location, nationality, relevant experience from CV.
    Missing fields get placeholder strings for recruiter to fill in.
    """
    prompt = f"""You are a recruitment assistant. Read the CV below and extract the following fields.
Return ONLY a JSON object with exactly these keys:
- "location": candidate's current city and country (e.g. "Kuala Lumpur, Malaysia"). If not found, use "[Location — please verify]"
- "nationality": candidate's nationality (e.g. "Malaysian"). If not found, use "[Nationality — please verify]"
- "relevant_experience": years of experience directly relevant to the role of {job_name} (e.g. "10 Years"). Count only directly relevant years. If unclear, use "[Experience — please verify]"

Return only valid JSON. No explanation, no markdown, no backticks.

CV:
{resume_text[:6000]}"""

    try:
        r = oa.chat.completions.create(
            model=TIER1_MODEL,
            messages=[
                {"role": "system", "content": "Return only valid JSON. No markdown, no explanation."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        text = (r.choices[0].message.content or "{}").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"  ⚠️  Metadata inference failed: {e}")
        return {
            "location":            "[Location — please verify]",
            "nationality":         "[Nationality — please verify]",
            "relevant_experience": "[Experience — please verify]",
        }


# ══════════════════════════════════════════════════════════════════════════════
# Airtable helpers
# ══════════════════════════════════════════════════════════════════════════════

def fetch_airtable_record(table, candidate_id: int, job_id: int) -> Optional[Dict]:
    """Fetch Airtable record by candidate_id + job_id pair."""
    match_id = f"{candidate_id}{job_id}"
    try:
        results = table.all(formula=f"{{match_id}}='{match_id}'")
        if results:
            return results[0]
    except Exception:
        pass
    try:
        formula = f"AND({{candidate_id}}={candidate_id}, {{job_id}}={job_id})"
        results = table.all(formula=formula)
        if results:
            return results[0]
    except Exception as e:
        print(f"  ❌ Airtable fetch failed: {e}")
    return None


def upload_docx_to_airtable(record_id: str, docx_bytes: bytes, filename: str) -> bool:
    """
    Upload .docx directly to Airtable ai_docx attachment field
    via Airtable's direct multipart upload endpoint.
    """
    upload_url = (
        f"https://content.airtable.com/v0/{AIRTABLE_BASE_ID}"
        f"/{record_id}/ai_docx/uploadAttachment"
    )
    try:
        resp = requests.post(
            upload_url,
            headers={"Authorization": f"Bearer {AIRTABLE_TOKEN}"},
            files={
                "file": (
                    filename,
                    io.BytesIO(docx_bytes),
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document",
                )
            },
            timeout=60,
        )
        if resp.status_code in (200, 201):
            print(f"  ✅ Uploaded {filename} to ai_docx")
            return True
        else:
            print(f"  ❌ Upload failed [{resp.status_code}]: {resp.text[:300]}")
            return False
    except Exception as e:
        print(f"  ❌ Upload exception: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Core generation function
# ══════════════════════════════════════════════════════════════════════════════

def generate_report(job_id: int, candidate_id: int) -> int:
    """
    Core generation function.
    Importable by FastAPI endpoint with zero changes.
    Returns 0 on success, non-zero on failure.
    """
    print(f"\n{'='*60}")
    print(f"SUBMISSION REPORT GENERATOR")
    print(f"{'='*60}")
    print(f"Job ID:       {job_id}")
    print(f"Candidate ID: {candidate_id}")
    print(f"{'='*60}\n")

    # ── 1. Validate credentials ───────────────────────────────────────────────
    for var, val in [
        ("AIRTABLE_TOKEN",    AIRTABLE_TOKEN),
        ("AIRTABLE_BASE_ID",  AIRTABLE_BASE_ID),
        ("AIRTABLE_TABLE_ID", AIRTABLE_TABLE_ID),
        ("MANATAL_API_TOKEN", MANATAL_API_TOKEN),
        ("OPENAI_API_KEY",    OPENAI_API_KEY),
    ]:
        if not val:
            print(f"ERROR: {var} is not set in .env", file=sys.stderr)
            return 2

    # ── 2. Load rubric ────────────────────────────────────────────────────────
    rubric_path = Path(RUBRIC_DIR) / f"rubric_{job_id}.json"
    if not rubric_path.exists():
        print(f"ERROR: Rubric not found: {rubric_path}", file=sys.stderr)
        return 2
    rubric = load_rubric_json(str(rubric_path))
    print(f"  ✅ Rubric loaded")

    # Classify soft_skill IDs from rubric
    soft_skill_ids: set = set()
    for item in rubric.get("requirements", {}).get("must_have", []):
        if item.get("category", "").lower() == "soft_skill":
            soft_skill_ids.add(item.get("id", ""))

    # ── 3. Fetch Airtable record ──────────────────────────────────────────────
    api_obj = Api(AIRTABLE_TOKEN)
    table   = api_obj.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID)
    record  = fetch_airtable_record(table, candidate_id, job_id)

    if not record:
        print(
            f"ERROR: No Airtable record for candidate_id={candidate_id}, job_id={job_id}",
            file=sys.stderr,
        )
        return 2

    record_id     = record["id"]
    fields        = record.get("fields", {})
    full_name     = fields.get("full_name",  f"Candidate {candidate_id}")
    job_name      = fields.get("job_name",   f"Job {job_id}")
    ai_summary    = fields.get("ai_summary", "No summary available.")
    overall_score = float(fields.get("t2_score", 0))
    recommendation = (
        "PASS"   if overall_score >= 75 else
        "REVIEW" if overall_score >= 65 else
        "FAIL"
    )

    raw_json = fields.get("ai_detailed_json", "{}")
    try:
        detailed_json = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except Exception:
        detailed_json = {}

    print(f"  ✅ Airtable record: {full_name} | {job_name} | Score: {overall_score}")

    # ── 4. Fetch CV from Manatal ──────────────────────────────────────────────
    resume_text = ""
    try:
        candidate_data = api_get(f"/candidates/{candidate_id}/")
        resume_url     = extract_resume_url_from_candidate(candidate_data)
        if resume_url:
            ext = Path(resume_url.split("?")[0]).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = Path(tmp.name)
            download_file(resume_url, tmp_path)
            resume_text = resume_text_from_file(tmp_path)
            tmp_path.unlink(missing_ok=True)
            print(f"  ✅ CV fetched ({len(resume_text)} chars)")
        else:
            print(f"  ⚠️  No resume URL for candidate {candidate_id}")
    except Exception as e:
        print(f"  ⚠️  CV fetch failed: {e}")

    # ── 5. Infer metadata via LLM ─────────────────────────────────────────────
    oa = OpenAI(api_key=OPENAI_API_KEY)
    if resume_text.strip():
        print(f"  🤖 Inferring metadata from CV...")
        metadata = infer_candidate_metadata(oa, resume_text, job_name)
    else:
        metadata = {
            "location":            "[Location — please verify]",
            "nationality":         "[Nationality — please verify]",
            "relevant_experience": "[Experience — please verify]",
        }
        print(f"  ⚠️  No CV text — using placeholders")

    print(f"     Location:    {metadata.get('location')}")
    print(f"     Nationality: {metadata.get('nationality')}")
    print(f"     Experience:  {metadata.get('relevant_experience')}")

    # ── 6. Split scored items by category ────────────────────────────────────
    all_must_have    = detailed_json.get("must_have",    [])
    compliance       = detailed_json.get("compliance",   [])
    nice_to_have     = detailed_json.get("nice_to_have", [])
    technical_items  = [i for i in all_must_have if i.get("id") not in soft_skill_ids]
    soft_skill_items = [i for i in all_must_have if i.get("id") in soft_skill_ids]

    # ── 7. Build .docx via Node.js ────────────────────────────────────────────
    payload = {
        "full_name":           full_name,
        "job_name":            job_name,
        "overall_score":       overall_score,
        "recommendation":      recommendation,
        "ai_summary":          ai_summary,
        "compliance":          compliance,
        "technical":           technical_items,
        "soft_skill":          soft_skill_items,
        "nice_to_have":        nice_to_have,
        "location":            metadata.get("location",            "[Location — please verify]"),
        "nationality":         metadata.get("nationality",         "[Nationality — please verify]"),
        "relevant_experience": metadata.get("relevant_experience", "[Experience — please verify]"),
        "report_date":         datetime.now().strftime("%d %B %Y"),
        "show_risk":           False,
    }

    print(f"  📄 Building .docx...")
    try:
        docx_bytes = build_docx(payload)
    except Exception as e:
        print(f"  ❌ .docx build failed: {e}", file=sys.stderr)
        return 1
    print(f"  ✅ .docx built ({len(docx_bytes):,} bytes)")

    # ── 8. Upload to Airtable ────────────────────────────────────────────────
    filename = safe_filename(f"{full_name}_{job_name}_submission") + ".docx"
    print(f"  ⬆️  Uploading to Airtable ai_docx...")
    success = upload_docx_to_airtable(record_id, docx_bytes, filename)

    if success:
        print(f"\n✅ Done!")
        print(f"   Candidate : {full_name}")
        print(f"   Role      : {job_name}")
        print(f"   File      : {filename}")
        return 0
    else:
        fallback = Path(f"./{filename}")
        fallback.write_bytes(docx_bytes)
        print(f"\n⚠️  Airtable upload failed. Saved locally: {fallback}")
        return 1


def generate_report_bytes(job_id: int, candidate_id: int):
    """
    Same as generate_report() but returns (docx_bytes, filename) instead of
    uploading to Airtable. Used by FastAPI to stream the file as a download.
    Returns (bytes, str) on success, raises Exception on failure.
    """
    # ── 1. Validate credentials ───────────────────────────────────────────────
    for var, val in [
        ("AIRTABLE_TOKEN",    AIRTABLE_TOKEN),
        ("AIRTABLE_BASE_ID",  AIRTABLE_BASE_ID),
        ("AIRTABLE_TABLE_ID", AIRTABLE_TABLE_ID),
        ("MANATAL_API_TOKEN", MANATAL_API_TOKEN),
        ("OPENAI_API_KEY",    OPENAI_API_KEY),
    ]:
        if not val:
            raise RuntimeError(f"{var} is not set")

    # ── 2. Load rubric ────────────────────────────────────────────────────────
    rubric_path = Path(RUBRIC_DIR) / f"rubric_{job_id}.json"
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")
    rubric = load_rubric_json(str(rubric_path))

    soft_skill_ids: set = set()
    for item in rubric.get("requirements", {}).get("must_have", []):
        if item.get("category", "").lower() == "soft_skill":
            soft_skill_ids.add(item.get("id", ""))

    # ── 3. Fetch Airtable record ──────────────────────────────────────────────
    api_obj = Api(AIRTABLE_TOKEN)
    table   = api_obj.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID)
    record  = fetch_airtable_record(table, candidate_id, job_id)
    if not record:
        raise LookupError(f"No Airtable record for candidate_id={candidate_id}, job_id={job_id}")

    fields        = record.get("fields", {})
    full_name     = fields.get("full_name",  f"Candidate {candidate_id}")
    job_name      = fields.get("job_name",   f"Job {job_id}")
    ai_summary    = fields.get("ai_summary", "No summary available.")
    overall_score = float(fields.get("t2_score", 0))
    recommendation = (
        "PASS"   if overall_score >= 75 else
        "REVIEW" if overall_score >= 65 else
        "FAIL"
    )

    raw_json = fields.get("ai_detailed_json", "{}")
    try:
        detailed_json = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except Exception:
        detailed_json = {}

    # ── 4. Fetch CV from Manatal ──────────────────────────────────────────────
    resume_text = ""
    try:
        candidate_data = api_get(f"/candidates/{candidate_id}/")
        resume_url     = extract_resume_url_from_candidate(candidate_data)
        if resume_url:
            ext = Path(resume_url.split("?")[0]).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = Path(tmp.name)
            download_file(resume_url, tmp_path)
            resume_text = resume_text_from_file(tmp_path)
            tmp_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"  ⚠️  CV fetch failed: {e}")

    # ── 5. Infer metadata via LLM ─────────────────────────────────────────────
    oa = OpenAI(api_key=OPENAI_API_KEY)
    if resume_text.strip():
        metadata = infer_candidate_metadata(oa, resume_text, job_name)
    else:
        metadata = {
            "location":            "[Location — please verify]",
            "nationality":         "[Nationality — please verify]",
            "relevant_experience": "[Experience — please verify]",
        }

    # ── 6. Split scored items by category ────────────────────────────────────
    all_must_have    = detailed_json.get("must_have",    [])
    compliance       = detailed_json.get("compliance",   [])
    nice_to_have     = detailed_json.get("nice_to_have", [])
    technical_items  = [i for i in all_must_have if i.get("id") not in soft_skill_ids]
    soft_skill_items = [i for i in all_must_have if i.get("id") in soft_skill_ids]

    # ── 7. Build .docx ────────────────────────────────────────────────────────
    payload = {
        "full_name":           full_name,
        "job_name":            job_name,
        "overall_score":       overall_score,
        "recommendation":      recommendation,
        "ai_summary":          ai_summary,
        "compliance":          compliance,
        "technical":           technical_items,
        "soft_skill":          soft_skill_items,
        "nice_to_have":        nice_to_have,
        "location":            metadata.get("location",            "[Location — please verify]"),
        "nationality":         metadata.get("nationality",         "[Nationality — please verify]"),
        "relevant_experience": metadata.get("relevant_experience", "[Experience — please verify]"),
        "report_date":         datetime.now().strftime("%d %B %Y"),
        "show_risk":           False,
    }

    docx_bytes = build_docx(payload)
    filename   = safe_filename(f"{full_name}_{job_name}_submission") + ".docx"
    return docx_bytes, filename


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate candidate submission report and upload to Airtable"
    )
    parser.add_argument("job_id",       help="Manatal Job ID (numeric)")
    parser.add_argument("candidate_id", help="Manatal Candidate ID (numeric)")
    args = parser.parse_args()

    if not args.job_id.isdigit():
        print(f"ERROR: job_id must be numeric, got: {args.job_id}", file=sys.stderr)
        return 2
    if not args.candidate_id.isdigit():
        print(f"ERROR: candidate_id must be numeric, got: {args.candidate_id}", file=sys.stderr)
        return 2

    return generate_report(
        job_id       = int(args.job_id),
        candidate_id = int(args.candidate_id),
    )


if __name__ == "__main__":
    raise SystemExit(main())
