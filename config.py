#!/usr/bin/env python3
"""config.py

Centralized configuration for the Airtable recruitment pipeline.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

import requests


def _safe_int_for_threshold(val: Any) -> Optional[int]:
    """Parse an integer threshold from Airtable or env; None if missing/invalid."""
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        m = re.search(r"-?\d+", s)
        return int(m.group()) if m else None


def _safe_float_for_floor(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d*\.?\d+", s)
        return float(m.group()) if m else None


def _fetch_airtable_pipeline_settings_fields() -> Dict[str, Any]:
    """GET pipeline settings row where {Recordnum}=1; empty dict if unavailable."""
    table = os.getenv("AIRTABLE_PIPELINE_SETTINGS_TABLE_ID", "").strip()
    base = os.getenv("AIRTABLE_BASE_ID", "").strip()
    token = os.getenv("AIRTABLE_TOKEN", "").strip()
    if not table or not base or not token:
        return {}

    url = f"https://api.airtable.com/v0/{base}/{table}"
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"filterByFormula": "{Recordnum}=1", "maxRecords": 1},
            timeout=30,
        )
        if not r.ok:
            print(f"[WARN] Pipeline settings Airtable GET failed: {r.status_code}\n{r.text[:200]}")
            return {}
        data = r.json()
        recs = data.get("records") or []
        if not recs:
            return {}
        return recs[0].get("fields") or {}
    except Exception as e:
        print(f"[WARN] Pipeline settings fetch error: {e}")
        return {}


def _env_int_pass(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        m = re.search(r"-?\d+", v)
        return int(m.group()) if m else default


def _env_tier2_pass(t1: int) -> int:
    """TIER2_PASS_THRESHOLD when set and numeric; otherwise same as Tier 1."""
    v = os.getenv("TIER2_PASS_THRESHOLD", "").strip()
    if not v:
        return t1
    if not any(c.isdigit() for c in v):
        return t1
    try:
        return int(v)
    except ValueError:
        m = re.search(r"-?\d+", v)
        return int(m.group()) if m else t1


def _env_floor_default() -> float:
    # Prefer clearer key; keep legacy env name for compatibility.
    v = os.getenv("MUST_HAVE_FLOOR_RULE", os.getenv("TIER2_MUST_HAVE_FLOOR", "2.0")).strip()
    if not v:
        return 2.0
    try:
        return float(v)
    except ValueError:
        m = re.search(r"-?\d*\.?\d+", v)
        return float(m.group()) if m else 2.0


def _merge_pipeline_thresholds() -> Tuple[int, int, float]:
    # Prefer the clearer key; fall back to legacy PASS_THRESHOLD for compatibility.
    t1 = _env_int_pass("TIER1_PASS_THRESHOLD", _env_int_pass("PASS_THRESHOLD", 60))
    t2 = _env_tier2_pass(t1)
    floor = _env_floor_default()
    fields = _fetch_airtable_pipeline_settings_fields()

    for key, target in (
        ("tier1_pass_threshold", "t1"),
        ("tier2_pass_threshold", "t2"),
    ):
        if key not in fields:
            continue
        parsed = _safe_int_for_threshold(fields[key])
        if parsed is not None and parsed != 0:
            if target == "t1":
                t1 = parsed
            else:
                t2 = parsed

    if "tier2_must_have_floor" in fields:
        fp = _safe_float_for_floor(fields["tier2_must_have_floor"])
        if fp is not None and fp != 0.0:
            floor = fp

    return t1, t2, floor


_T1, _T2, _FLOOR = _merge_pipeline_thresholds()


class Config:
    """Global configuration settings."""

    # =========================
    # Paths
    # =========================
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = Path(os.getenv("EXPORT_PATH", str(BASE_DIR / "output")))
    RUBRIC_DIR = Path(os.getenv("RUBRIC_DIR", str(BASE_DIR / "rubrics")))
    OFFLINE_INPUT_DIR = BASE_DIR / "offline_input"
    REPORTS_DIR = OUTPUT_DIR / "reports"
    UPLOAD_DIR = OUTPUT_DIR / "upload"

    CACHE_FILE = Path(os.getenv("CACHE_FILE", str(OUTPUT_DIR / "scored_cache.json")))

    # =========================
    # API Keys & Tokens
    # =========================
    MANATAL_API_TOKEN = os.getenv("MANATAL_API_TOKEN", "").strip()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN", "").strip()

    # =========================
    # Airtable Configuration
    # =========================
    AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "app285aKVVr7JYL43").strip()
    AIRTABLE_TABLE_ID = os.getenv("AIRTABLE_CANDIDATE_TABLE_ID", "tblJ2OkvaWI7vi0vI").strip()
    AIRTABLE_JOB_TABLE_ID = os.getenv("AIRTABLE_JOB_TABLE_ID", "tblCV6w4fGex9VgzK").strip()
    AIRTABLE_PIPELINE_SETTINGS_TABLE_ID = os.getenv("AIRTABLE_PIPELINE_SETTINGS_TABLE_ID", "").strip()

    # Airtable field names
    AIRTABLE_CV_FIELD = "CV"
    AIRTABLE_UNIQUE_KEY_FIELD = "match_id"

    # Airtable limits
    AIRTABLE_BATCH_SIZE = 10
    AIRTABLE_UPLOAD_MAX_BYTES = 5 * 1024 * 1024  # 5 MB limit for direct uploads

    # =========================
    # OpenAI Configuration
    # =========================
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    REPORT_OPENAI_MODEL = os.getenv("REPORT_OPENAI_MODEL", "gpt-4o")

    # =========================
    # Manatal API Configuration
    # =========================
    MANATAL_BASE_URL = "https://api.manatal.com/open/v3"
    MANATAL_PAGE_SIZE = 100

    # =========================
    # Pipeline Settings
    # =========================
    TARGET_STAGE_NAME  = os.getenv("TARGET_STAGE_NAME",  "New Candidates")
    TARGET_STAGE_AFTER = os.getenv("TARGET_STAGE_AFTER", "AI Screened")
    TARGET_STAGE_FAIL  = os.getenv("TARGET_STAGE_FAIL",  "Processed")

    # Skip matches with dropped_at set (still listed under a stage in some Manatal views)
    _edm = os.getenv("EXCLUDE_DROPPED_MATCHES", "true").strip().lower()
    EXCLUDE_DROPPED_MATCHES = _edm in ("1", "true", "yes", "on")

    DOWNLOAD_RESUMES = True
    SKIP_ALREADY_SCORED = True
    FORCE_RESCORE = False

    CV_EXTENSIONS = {".pdf", ".docx", ".doc"}

    # =========================
    # Content Limits
    # =========================
    MAX_RESUME_CHARS = int(os.getenv("MAX_RESUME_CHARS", "30000"))
    MAX_JD_CHARS = int(os.getenv("MAX_JD_CHARS", "12000"))
    MAX_RUBRIC_CHARS = int(os.getenv("MAX_RUBRIC_CHARS", "50000"))
    MAX_RESUME_CHARS_INFO_EXTRACTION = 15000

    # =========================
    # Scoring Settings (Tier 1 / Tier 2 — merged from env + optional Airtable row)
    # =========================
    TIER1_PASS_THRESHOLD = _T1
    TIER2_PASS_THRESHOLD = _T2
    MUST_HAVE_FLOOR_RULE = _FLOOR
    TIER2_MUST_HAVE_FLOOR = MUST_HAVE_FLOOR_RULE  # legacy alias
    PASS_THRESHOLD = TIER1_PASS_THRESHOLD
    MIN_SCORE_FOR_REPORT = TIER1_PASS_THRESHOLD

    # =========================
    # Field Mappings (CSV → Airtable)
    # =========================
    FIELD_MAP = {
        "organisation_id":   "organisation_id",
        "organisation_name": "organisation_name",
        "job_id":            "job_id",
        "job_name":          "job_name",
        "created_at":        "created_at",
        "updated_at":        "updated_at",
        "match_stage_name":  "match_stage_name",
        "candidate_id":      "candidate_id",
        "full_name":         "full_name",
        "email":             "email",
        "cv_text":           "cv_text",
        "t1_score":          "t1_score",
        "ai_summary":        "ai_summary",
        "ai_strengths":      "ai_strengths",
        "ai_gaps":           "ai_gaps",
        "rubric_version":    "rubric_version",
        "rubric_hash":       "rubric_hash",
        "cache_key":         "cache_key",
    }

    # Field type definitions for upload normalisation
    TEXT_FIELDS = {
        "organisation_name",
        "job_name",
        "created_at", "updated_at",
        "match_stage_name",
        "full_name", "email",
        "cv_text",
        "ai_summary", "ai_strengths", "ai_gaps",
        "rubric_version", "rubric_hash",
        "cache_key",
    }

    NUMBER_FIELDS = {
        "t1_score", "t2_score",
        "organisation_id", "job_id", "candidate_id",
    }

    # =========================
    # Validation
    # =========================

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration is present."""
        required = {
            "OPENAI_API_KEY":  cls.OPENAI_API_KEY,
            "AIRTABLE_TOKEN":  cls.AIRTABLE_TOKEN,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing)}\n"
                f"Set these in your .env file or as environment variables."
            )

    @classmethod
    def validate_online_mode(cls) -> None:
        """Validate configuration for online mode (requires Manatal API)."""
        cls.validate()
        if not cls.MANATAL_API_TOKEN:
            raise ValueError(
                "MANATAL_API_TOKEN required for online mode.\n"
                "Set it in your .env file: MANATAL_API_TOKEN=your_token_here"
            )

    @classmethod
    def ensure_dirs(cls) -> None:
        """Create required directories if they don't exist."""
        cls.OUTPUT_DIR.mkdir(exist_ok=True)
        cls.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        cls.REPORTS_DIR.mkdir(exist_ok=True)
        cls.OFFLINE_INPUT_DIR.mkdir(exist_ok=True)
        cls.RUBRIC_DIR.mkdir(exist_ok=True)

    @classmethod
    def get_rubric_path(cls, job_id: str) -> Path:
        json_path = cls.RUBRIC_DIR / f"rubric_{job_id}.json"
        if json_path.exists():
            return json_path
        return cls.RUBRIC_DIR / f"rubric_{job_id}.yaml"

    @classmethod
    def get_offline_json_path(cls, job_id: str) -> Path:
        return cls.OFFLINE_INPUT_DIR / f"job_{job_id}.json"

    @classmethod
    def get_scored_csv_path(cls, job_id: str, stage_name: str = None) -> Path:
        stage = stage_name or cls.TARGET_STAGE_NAME
        return cls.UPLOAD_DIR / f"manatal_job_{job_id}_{stage}_scored.csv"

    @classmethod
    def get_scored_json_path(cls, job_id: str, stage_name: str = None) -> Path:
        stage = stage_name or cls.TARGET_STAGE_NAME
        return cls.UPLOAD_DIR / f"manatal_job_{job_id}_{stage}_scored.json"
