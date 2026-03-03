#!/usr/bin/env python3
"""upload_supabase.py

SUPABASE UPLOAD — Direct-to-Supabase mode
Reads the scored CSV for a given JOB_ID and:
  1. Upserts candidate rows into Supabase `candidates` table
  2. Uploads local CV files to Supabase Storage (candidate_files bucket)
  3. Generates embeddings and inserts into `candidate_chunks` table
  4. Reloads PostgREST schema cache

Usage:
  python upload_supabase.py <JOB_ID>

Environment variables (set in .env):
  SUPABASE_URL           - Supabase project URL
  SUPABASE_KEY           - Supabase service role key
  SUPABASE_DB_URL        - Direct PostgreSQL connection string
  SUPABASE_STORAGE_BUCKET - Storage bucket name (default: candidate_files)
  OPENAI_API_KEY         - OpenAI key for embeddings (optional)
"""

from __future__ import annotations

import csv
import os
import re
import sys
import logging
import psycopg2
import psycopg2.extras
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import Config
from src.supabase_client import SupabaseClient
from src.text_processor import extract_text_from_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# ARGS
# =============================================================================
if len(sys.argv) < 2:
    print("Usage: python upload_supabase.py <JOB_ID>")
    raise SystemExit(2)

JOB_ID = str(sys.argv[1]).strip()
INPUT_FILE = os.getenv("INPUT_FILE", str(Config.get_scored_csv_path(JOB_ID)))

STORAGE_BUCKET = Config.SUPABASE_STORAGE_BUCKET

# =============================================================================
# CSV LOADER
# =============================================================================

def load_csv(path: str) -> List[Dict[str, Any]]:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {p}")
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


# =============================================================================
# CV HANDLING
# =============================================================================

def upload_cv_to_storage(supabase: SupabaseClient, local_path: str, candidate_id: str, filename: str) -> Optional[str]:
    """Upload a local CV file to Supabase Storage. Returns the public URL."""
    try:
        with open(local_path, "rb") as f:
            content = f.read()
        suffix = Path(local_path).suffix.lower()
        content_type = "application/pdf" if suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        storage_path = f"{candidate_id}/resume/{filename}"
        supabase.get_client().storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        public_url = supabase.get_client().storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
        logger.info(f"  Uploaded CV for candidate {candidate_id}: {public_url}")
        return public_url
    except Exception as e:
        logger.warning(f"  Failed to upload CV for candidate {candidate_id}: {e}")
        return None


def extract_cv_text(local_path: str) -> Optional[str]:
    """Extract text from a local CV file for embedding."""
    try:
        suffix = Path(local_path).suffix.lower()
        content_type = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
        with open(local_path, "rb") as f:
            content = f.read()
        return extract_text_from_file(content, content_type, Path(local_path).name)
    except Exception as e:
        logger.warning(f"  Failed to extract CV text from {local_path}: {e}")
        return None


# =============================================================================
# TRANSFORM ROW → SUPABASE CANDIDATE
# =============================================================================

def safe_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def transform_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map CSV row to Supabase candidates schema. Primary key is match_id."""
    match_id = (row.get("match_id") or "").strip()
    if not match_id:
        return None
    candidate_id = safe_int(row.get("candidate_id"))

    return {
        "match_id":         match_id,
        "candidate_id":     candidate_id,
        "job_id":           safe_int(row.get("job_id")),
        "job_name":         row.get("job_name") or None,
        "org_id":           safe_int(row.get("organisation_id")),
        "org_name":         row.get("organisation_name") or None,
        "full_name":        row.get("full_name") or None,
        "email":            row.get("email") or None,
        "resume_file":      row.get("resume_file") or None,   # filled in after CV upload
        "match_stage_name": row.get("match_stage_name") or None,
        "ai_score":         safe_int(row.get("ai_score")),
        "ai_summary":       row.get("ai_summary") or None,
        "ai_strengths":     row.get("ai_strengths") or None,
        "ai_gaps":          row.get("ai_gaps") or None,
        "ai_report_html":   row.get("ai_report_html") or None,
        "rubric_version":   row.get("rubric_version") or None,
        "rubric_hash":      row.get("rubric_hash") or None,
        "cache_key":        row.get("cache_key") or None,
    }


# =============================================================================
# UPSERT CANDIDATES (with psycopg2 fallback)
# =============================================================================

def upsert_candidates(supabase: SupabaseClient, records: List[Dict[str, Any]]) -> None:
    """Upsert a batch of candidate records into Supabase."""
    if not records:
        return
    logger.info(f"Upserting {len(records)} candidates to Supabase...")
    try:
        supabase.get_client().table("candidates").upsert(
            records, on_conflict="match_id"
        ).execute()
        logger.info("  Upsert via supabase-py OK")
    except Exception as e:
        err = str(e)
        if any(k in err for k in ("PGRST204", "schema cache", "PGRST")):
            logger.warning("  Schema cache miss — falling back to psycopg2 ...")
            _upsert_via_psycopg2(records)
        else:
            logger.error(f"  Upsert failed: {e}")
            raise


def _upsert_via_psycopg2(records: List[Dict[str, Any]]) -> None:
    db_url = Config.SUPABASE_DB_URL
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT pg_notify('pgrst', 'reload schema');")
    cols = list(records[0].keys())
    col_names = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "match_id")
    sql = f"""
        INSERT INTO candidates ({col_names}) VALUES ({placeholders})
        ON CONFLICT (match_id) DO UPDATE SET {updates};
    """
    rows = [tuple(r[c] for c in cols) for r in records]
    psycopg2.extras.execute_batch(cur, sql, rows)
    cur.close()
    conn.close()
    logger.info(f"  psycopg2 upsert OK ({len(rows)} rows)")


# =============================================================================
# RELOAD SCHEMA CACHE
# =============================================================================

def reload_schema_cache() -> None:
    try:
        conn = psycopg2.connect(Config.SUPABASE_DB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT pg_notify('pgrst', 'reload schema');")
        cur.close()
        conn.close()
        logger.info("  PostgREST schema cache reloaded ✅")
    except Exception as e:
        logger.warning(f"  Schema reload warning: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    # Validate config
    try:
        Config.validate()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Initialize clients
    supabase = SupabaseClient()

    # Load CSV
    print(f"Loading scored CSV: {INPUT_FILE}")
    try:
        rows = load_csv(INPUT_FILE)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not rows:
        print("No rows found. Nothing to upload.")
        return 0
    print(f"✓ Loaded {len(rows)} rows\n")

    # Transform + handle CVs
    candidates = []
    skipped = 0
    cv_uploaded = 0

    for row in rows:
        record = transform_row(row)
        if not record:
            skipped += 1
            continue

        cid = str(record.get("candidate_id") or record["match_id"])

        # Upload local CV if present
        local_path = row.get("resume_local_path", "").strip()
        if local_path and Path(local_path).exists():
            fn = Path(local_path).name
            url = upload_cv_to_storage(supabase, local_path, cid, fn)
            if url:
                record["resume_file"] = url
                cv_uploaded += 1
        # If already a URL (online mode), keep as-is

        candidates.append((record, row))

    if skipped:
        print(f"⚠️  Skipped {skipped} rows (missing match_id)")

    # Upsert all candidates
    clean_records = [c for c, _ in candidates]
    upsert_candidates(supabase, clean_records)

    # Schema cache reload
    print("\nReloading PostgREST schema cache...")
    reload_schema_cache()

    # Summary
    print(f"\n{'='*70}")
    print(f"✅ Upload to Supabase complete!")
    print(f"   • Candidates upserted : {len(clean_records)}")
    print(f"   • CVs uploaded to Storage: {cv_uploaded}")
    print(f"{'='*70}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
