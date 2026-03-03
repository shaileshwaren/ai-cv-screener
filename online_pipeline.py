#!/usr/bin/env python3
"""online_pipeline.py

ONLINE PIPELINE - Multi-Job Mode
Fetches candidates from Manatal API and processes multiple jobs

Workflow (per job):
1) AI scoring (python8.py) - fetches from Manatal API automatically
2) Upload to Supabase (upload_supabase.py) - direct upsert + embeddings
3) Generate detailed reports (generate_detailed_reports.py)

Usage:
  # Single job
  python online_pipeline.py 3419430
  
  # Multiple jobs (comma-separated)
  python online_pipeline.py "3419430, 3261113"
  
  # With optional flags
  python online_pipeline.py 3419430 --skip-upload --skip-reports
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PYTHON8 = HERE / "python8.py"
UPLOAD_SUPABASE = HERE / "upload_supabase.py"
GENERATE_REPORTS = HERE / "generate_detailed_reports.py"
CONFIG_FILE = HERE / "online_config.txt"
ADVANCED_CONFIG_FILE = HERE / "online_advanced_config.txt"


def run_step(step_num: int, total_steps: int, description: str, cmd: list[str]) -> None:
    """Run a pipeline step with formatted output."""
    print(f"\n{'='*70}")
    print(f"[STEP {step_num}/{total_steps}] {description}")
    print(f"{'='*70}")
    print(f"Command: {' '.join(cmd)}\n")
    subprocess.run(cmd, check=True)


def warn_missing_env() -> None:
    """Warn about missing environment variables."""
    required = ["OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_DB_URL", "MANATAL_API_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]

    if missing:
        print(
            "\n[WARN] Missing environment variables: "
            + ", ".join(missing)
            + "\n       Set them in .env file or as environment variables.\n"
        )


def validate_files_exist() -> None:
    """Validate that all required scripts exist."""
    scripts = {
        "python8.py": PYTHON8,
        "upload_supabase.py": UPLOAD_SUPABASE,
        "generate_detailed_reports.py": GENERATE_REPORTS,
    }

    missing = []
    for name, path in scripts.items():
        if not path.exists():
            missing.append(f"{name} not found at {path}")

    if missing:
        print("ERROR: Missing required scripts:")
        for msg in missing:
            print(f"  - {msg}")
        print(f"\nEnsure all scripts are in the same folder: {HERE}")
        sys.exit(2)


def load_config() -> dict:
    """Load online_config.txt and optionally online_advanced_config.txt."""
    config = {}

    if not CONFIG_FILE.exists():
        return {
            "stage_name": "Processing",
            "skip_scoring": False,
            "skip_upload": False,
            "generate_reports": True
        }

    for cfg_file in [CONFIG_FILE, ADVANCED_CONFIG_FILE]:
        if not cfg_file.exists():
            continue
        with cfg_file.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    print(f"[WARN] Line {line_num} ignored (no '=' found): {line}")
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not value:
                    continue
                if value.lower() in ("true", "yes", "1"):
                    value = True
                elif value.lower() in ("false", "no", "0"):
                    value = False
                elif value.isdigit():
                    value = int(value)
                config[key] = value

    return config


def process_single_job(job_id: str, config: dict, global_args: argparse.Namespace) -> bool:
    """Process a single job. Returns True if successful, False otherwise."""

    stage_name = config.get("stage_name", "Processing")
    skip_scoring = global_args.skip_scoring or config.get("skip_scoring", False)
    skip_upload = global_args.skip_upload or config.get("skip_upload", False)
    skip_reports = global_args.skip_reports or config.get("generate_reports", True) == False

    print(f"\n{'='*70}")
    print(f"Processing Job: {job_id}")
    print(f"{'='*70}")
    print(f"Stage: {stage_name}")
    print(f"INFO: Job name, org ID, and org name will be fetched from Manatal API")
    print(f"{'='*70}\n")

    total_steps = sum([not skip_scoring, not skip_upload, not skip_reports])
    step_num = 1

    try:
        # ── STEP 1: AI Scoring ───────────────────────────────────────────
        if not skip_scoring:
            run_step(step_num, total_steps, "AI Scoring (fetch from Manatal + score against rubric)",
                     [sys.executable, str(PYTHON8), str(job_id)])
            step_num += 1
        else:
            print("\nSkipped: AI Scoring")

        # ── STEP 2: Upload to Supabase ───────────────────────────────────
        if not skip_upload:
            run_step(step_num, total_steps, "Upload to Supabase (upsert + embeddings + NocoDB sync)",
                     [sys.executable, str(UPLOAD_SUPABASE), str(job_id)])
            step_num += 1
        else:
            print("\nSkipped: Supabase Upload")

        # ── STEP 3: Generate Detailed Reports ────────────────────────────
        if not skip_reports:
            run_step(step_num, total_steps, "Generate Detailed Reports",
                     [sys.executable, str(GENERATE_REPORTS), str(job_id)])
            step_num += 1
        else:
            print("\nSkipped: Detailed Reports")

        print(f"\n{'='*70}")
        print(f"Job {job_id} completed successfully!")
        print(f"{'='*70}\n")
        return True

    except subprocess.CalledProcessError as e:
        print(f"\n{'='*70}")
        print(f"ERROR: Job {job_id} failed at step")
        print(f"{'='*70}")
        print(f"Exit code: {e.returncode}")
        print(f"Command: {' '.join(e.cmd)}")
        print(f"\nContinuing with next job...\n")
        return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Online Pipeline: Fetch and process candidates from Manatal API → Supabase → NocoDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single job
  python online_pipeline.py 3419430

  # Process multiple jobs (comma-separated)
  python online_pipeline.py "3419430, 3261113, 3600123"
  
  # Skip specific steps
  python online_pipeline.py 3419430 --skip-upload --skip-reports
        """
    )

    parser.add_argument("job_ids", help="Job IDs to process (comma-separated for multiple)")
    parser.add_argument("--skip-scoring", action="store_true", help="Skip AI scoring step")
    parser.add_argument("--skip-upload", action="store_true", help="Skip Supabase upload step")
    parser.add_argument("--skip-reports", action="store_true", help="Skip detailed report generation")

    args = parser.parse_args(argv[1:])

    validate_files_exist()

    job_ids = [jid.strip() for jid in args.job_ids.split(",")]

    print(f"\n{'='*70}")
    print("ONLINE PIPELINE - SUPABASE/NOCODB MODE")
    print(f"{'='*70}\n")
    print(f"Processing {len(job_ids)} job(s): {', '.join(job_ids)}\n")

    warn_missing_env()
    config = load_config()

    successful_jobs = []
    failed_jobs = []

    for idx, job_id in enumerate(job_ids, 1):
        print(f"\n{'='*70}")
        print(f"Processing Job {idx} of {len(job_ids)}: {job_id}")
        print(f"{'='*70}\n")

        try:
            success = process_single_job(job_id, config, args)
            if success:
                successful_jobs.append(job_id)
            else:
                failed_jobs.append(job_id)
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            print(f"       Skipping job {job_id}\n")
            failed_jobs.append(job_id)
        except Exception as e:
            print(f"ERROR: Unexpected error for job {job_id}: {e}")
            print(f"       Skipping job {job_id}\n")
            failed_jobs.append(job_id)

    print(f"\n{'='*70}")
    print("MULTI-JOB PIPELINE SUMMARY")
    print(f"{'='*70}\n")
    print(f"Total Jobs: {len(job_ids)}")
    print(f"Successful: {len(successful_jobs)}")
    print(f"Failed: {len(failed_jobs)}\n")

    if successful_jobs:
        print("Successful Jobs:")
        for job_id in successful_jobs:
            print(f"  - {job_id}")
        print()

    if failed_jobs:
        print("Failed Jobs:")
        for job_id in failed_jobs:
            print(f"  - {job_id}")
        print()

    print(f"{'='*70}\n")
    return 1 if failed_jobs else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except KeyboardInterrupt:
        print("\n\nWARNING: Pipeline interrupted by user")
        raise SystemExit(130)
