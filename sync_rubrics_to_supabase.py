#!/usr/bin/env python3
"""sync_rubrics_to_supabase.py

One-time (or repeatable) utility to backfill local rubric files into Supabase.

Assumes a `rubrics` table with columns:
  - job_id (text or int)
  - rubric (jsonb)
  - rubric_version (text, optional)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import yaml

from config import Config
from src.supabase_client import SupabaseClient


def load_rubric_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = text[: Config.MAX_RUBRIC_CHARS]
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text) or {}
    return json.loads(text)


def extract_job_id_from_filename(path: Path) -> str:
    name = path.stem  # rubric_<JOB_ID>
    if name.startswith("rubric_"):
        return name.split("rubric_", 1)[1]
    return name


def extract_rubric_version(rubric: Dict[str, Any]) -> str:
    return str(
        rubric.get("rubric_version")
        or rubric.get("version")
        or rubric.get("metadata", {}).get("version")
        or "1.0"
    )


def main() -> int:
    Config.validate()
    supabase = SupabaseClient()

    rubrics_dir = Config.RUBRIC_DIR
    if not rubrics_dir.exists():
        print(f"Rubrics dir does not exist: {rubrics_dir}")
        return 1

    paths = sorted(
        list(rubrics_dir.glob("rubric_*.json"))
        + list(rubrics_dir.glob("rubric_*.yaml"))
        + list(rubrics_dir.glob("rubric_*.yml"))
    )
    if not paths:
        print(f"No rubric files found in {rubrics_dir}")
        return 0

    print(f"Found {len(paths)} rubric files under {rubrics_dir}")

    for p in paths:
        try:
            rubric = load_rubric_file(p)
        except Exception as e:
            print(f"❌ Failed to load {p}: {e}")
            continue

        job_id = str(rubric.get("job_id") or extract_job_id_from_filename(p)).strip()
        if not job_id:
            print(f"❌ Could not determine job_id for {p}, skipping")
            continue

        rubric_version = extract_rubric_version(rubric)

        try:
            supabase.upsert_rubric(job_id=job_id, rubric=rubric, rubric_version=rubric_version)
            print(f"✅ Upserted rubric for job_id={job_id}, version={rubric_version} from {p.name}")
        except Exception as e:
            print(f"❌ Failed to upsert rubric for job_id={job_id} from {p}: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

