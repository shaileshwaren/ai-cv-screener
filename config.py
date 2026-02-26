#!/usr/bin/env python3
"""config.py

Centralized configuration for the Supabase-NocoDB recruitment pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


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

    # =========================
    # Supabase Configuration
    # =========================
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
    SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "").strip()
    SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "candidate_files").strip()

    # =========================
    # NocoDB Configuration
    # =========================
    NOCODB_TOKEN = os.getenv("NOCODB_TOKEN", "").strip()
    NOCODB_BASE_ID = os.getenv("NOCODB_BASE_ID", "").strip()
    NOCODB_CANDIDATES_TABLE_ID = os.getenv("NOCODB_CANDIDATES_TABLE_ID", "mvdxvcoapwtlmtx").strip()

    # =========================
    # OpenAI Configuration
    # =========================
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # =========================
    # Manatal API Configuration
    # =========================
    MANATAL_BASE_URL = "https://api.manatal.com/open/v3"
    MANATAL_PAGE_SIZE = 100

    # =========================
    # Pipeline Settings
    # =========================
    TARGET_STAGE_NAME = os.getenv("TARGET_STAGE_NAME", "Processing")

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
    # Scoring Settings
    # =========================
    MIN_SCORE_FOR_REPORT = int(os.getenv("MIN_SCORE_FOR_REPORT", "85"))
    PASS_THRESHOLD = int(os.getenv("PASS_THRESHOLD", "70"))

    # =========================
    # Field Mapping (CSV → Supabase)
    # =========================
    FIELD_MAP = {
        "organisation_id":   "org_id",
        "organisation_name": "org_name",
        "job_id":            "job_id",
        "job_name":          "job_name",
        "match_id":          "match_id",
        "created_at":        "created_at",
        "updated_at":        "updated_at",
        "match_stage_name":  "match_stage_name",
        "candidate_id":      "candidate_id",
        "full_name":         "full_name",
        "email":             "email",
        "resume_file":       "resume_file",
        "ai_score":          "ai_score",
        "ai_summary":        "ai_summary",
        "ai_strengths":      "ai_strengths",
        "ai_gaps":           "ai_gaps",
        "ai_report_html":    "ai_report_html",
        "rubric_version":    "rubric_version",
        "rubric_hash":       "rubric_hash",
        "cache_key":         "cache_key",
    }

    # =========================
    # Validation
    # =========================

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration is present."""
        required = {
            "OPENAI_API_KEY":   cls.OPENAI_API_KEY,
            "SUPABASE_URL":     cls.SUPABASE_URL,
            "SUPABASE_KEY":     cls.SUPABASE_KEY,
            "SUPABASE_DB_URL":  cls.SUPABASE_DB_URL,
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
