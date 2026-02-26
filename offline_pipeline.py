#!/usr/bin/env python3
"""offline_pipeline.py

OFFLINE PIPELINE - Multi-Job Support
Processes local CV files from job-specific folders

Folder Structure:
  local_input/
    job_3419430/
      config_3419430.txt
      cv1.pdf
      cv2.pdf
    job_3544944/
      config_3544944.txt
      cv3.pdf

Usage:
  # Single job
  python offline_pipeline.py 3419430
  
  # Multiple jobs (comma-separated)
  python offline_pipeline.py "3419430, 3544944, 3600123"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
GENERATE_OFFLINE = HERE / "generate_offline_input.py"
PYTHON8 = HERE / "python8.py"
UPLOAD_AIRTABLE = HERE / "upload_airtable.py"
GENERATE_REPORTS = HERE / "generate_detailed_reports.py"
LOCAL_INPUT_DIR = HERE / "local_input"


def run_step(step_num: int, total_steps: int, description: str, cmd: list[str]) -> None:
    """Run a pipeline step with formatted output."""
    print(f"\n{'='*70}")
    print(f"[STEP {step_num}/{total_steps}] {description}")
    print(f"{'='*70}")
    print(f"Command: {' '.join(cmd)}\n")
    subprocess.run(cmd, check=True)


def warn_missing_env() -> None:
    """Warn about missing environment variables."""
    required = ["OPENAI_API_KEY", "AIRTABLE_TOKEN"]
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
        "generate_offline_input.py": GENERATE_OFFLINE,
        "python8.py": PYTHON8,
        "upload_airtable.py": UPLOAD_AIRTABLE,
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


def load_job_config(job_folder: Path, job_id: str) -> dict:
    """Load config_{job_id}.txt and optionally advanced_config_{job_id}.txt from job folder."""
    config = {}
    
    # Load main config file (required)
    config_file = job_folder / f"config_{job_id}.txt"
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    
    with config_file.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            
            # Parse key = value
            if "=" not in line:
                print(f"[WARN] Line {line_num} ignored (no '=' found): {line}")
                continue
            
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            
            # Skip empty values
            if not value:
                continue
            
            # Convert boolean strings
            if value.lower() in ("true", "yes", "1"):
                value = True
            elif value.lower() in ("false", "no", "0"):
                value = False
            # Convert numeric strings
            elif value.isdigit():
                value = int(value)
            
            config[key] = value
    
    # Load advanced config file (optional)
    advanced_config_file = job_folder / f"advanced_config_{job_id}.txt"
    if advanced_config_file.exists():
        with advanced_config_file.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                
                # Parse key = value
                if "=" not in line:
                    continue
                
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                
                # Skip empty values
                if not value:
                    continue
                
                # Convert boolean strings
                if value.lower() in ("true", "yes", "1"):
                    value = True
                elif value.lower() in ("false", "no", "0"):
                    value = False
                # Convert numeric strings
                elif value.isdigit():
                    value = int(value)
                
                # Advanced config overrides main config
                config[key] = value
    
    return config


def process_single_job(job_id: str, job_folder: Path, config: dict, global_args: argparse.Namespace) -> bool:
    """Process a single job. Returns True if successful, False otherwise."""
    
    # Extract config values
    job_name = config.get("job_name")
    org_id = config.get("org_id")
    org_name = config.get("org_name")
    
    # Auto-infer JD file path: jd_{job_id}.txt (can be overridden in advanced config)
    jd_file = config.get("jd_file", f"jd_{job_id}.txt")
    
    skip_scoring = global_args.skip_scoring or config.get("skip_scoring", False)
    skip_upload = global_args.skip_upload or config.get("skip_upload", False)
    skip_reports = global_args.skip_reports or config.get("generate_reports", True) == False
    
    # Validate required fields
    if not job_name:
        print(f"ERROR: job_name is required in config file")
        return False
    
    # Set paths
    cv_folder = str(job_folder)  # CVs are in the job folder itself
    
    # Auto-infer rubric path (can be overridden in advanced config)
    rubric = config.get("rubric", f"rubrics/rubric_{job_id}.yaml")
    
    # JD file can be relative to job folder or absolute
    jd_file_path = job_folder / jd_file
    if not jd_file_path.exists():
        # Try as absolute path
        jd_file_path = Path(jd_file)
        if not jd_file_path.exists():
            print(f"ERROR: JD file not found: {jd_file}")
            print(f"       Tried: {job_folder / jd_file} and {jd_file}")
            return False
    
    print(f"\nJob ID: {job_id}")
    print(f"Job Name: {job_name}")
    if org_id:
        print(f"Org ID: {org_id}")
    if org_name:
        print(f"Org Name: {org_name}")
    print(f"CV Folder: {cv_folder}")
    print(f"Rubric: {rubric}")
    print(f"JD File: {jd_file_path}\n")
    
    # Validate rubric exists
    rubric_path = Path(rubric).expanduser().resolve()
    if not rubric_path.exists():
        print(f"ERROR: Rubric file not found: {rubric_path}")
        print(f"       Make sure rubrics/rubric_{job_id}.yaml exists")
        return False
    
    # Check for CVs in folder
    cv_files = list(job_folder.glob("*.pdf")) + list(job_folder.glob("*.docx"))
    if not cv_files:
        print(f"WARNING: No CV files found in {job_folder}")
        print(f"         Skipping job {job_id}")
        return False
    
    # Save JSON output in the job folder
    offline_json_path = job_folder / f"job_{job_id}.json"
    
    # Calculate total steps
    total_steps = 1  # Always generate offline JSON
    if not skip_scoring:
        total_steps += 1
    if not skip_upload:
        total_steps += 1
    if not skip_reports:
        total_steps += 1
    
    step_num = 1
    
    try:
        # ========================================
        # STEP 1: Generate Offline JSON (extract CV info)
        # ========================================
        cmd = [
            sys.executable,
            str(GENERATE_OFFLINE),
            "--job-id", str(job_id),
            "--job-name", job_name,
            "--cv-folder", cv_folder,
            "--rubric", rubric,
            "--jd-file", str(jd_file_path),
            "--output", str(offline_json_path),  # Save JSON in job folder
        ]
        
        # Add optional args
        if org_id:
            cmd.extend(["--org-id", str(org_id)])
        if org_name:
            cmd.extend(["--org-name", org_name])
        
        run_step(step_num, total_steps, "Generate Offline JSON (extract CV info)", cmd)
        step_num += 1
        
        # ========================================
        # STEP 2: AI Scoring (python8.py)
        # ========================================
        if not skip_scoring:
            cmd = [sys.executable, str(PYTHON8), str(job_id), "--offline", str(offline_json_path)]
            run_step(step_num, total_steps, "AI Scoring (score candidates against rubric)", cmd)
            step_num += 1
        else:
            print(f"\nSkipped: AI Scoring")
        
        # ========================================
        # STEP 3: Upload to Airtable
        # ========================================
        if not skip_upload:
            cmd = [sys.executable, str(UPLOAD_AIRTABLE), str(job_id), "--offline"]
            run_step(step_num, total_steps, "Upload to Airtable", cmd)
            step_num += 1
        else:
            print(f"\nSkipped: Airtable Upload")
        
        # ========================================
        # STEP 4: Generate Detailed Reports
        # ========================================
        if not skip_reports:
            cmd = [sys.executable, str(GENERATE_REPORTS), str(job_id)]
            run_step(step_num, total_steps, "Generate Detailed Reports", cmd)
            step_num += 1
        else:
            print(f"\nSkipped: Detailed Reports")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Job {job_id} failed at step")
        print(f"Exit code: {e.returncode}")
        return False


def print_summary(results: dict[str, bool]) -> None:
    """Print summary of all job results."""
    print(f"\n{'='*70}")
    print("MULTI-JOB PIPELINE SUMMARY")
    print(f"{'='*70}\n")
    
    successful = [jid for jid, success in results.items() if success]
    failed = [jid for jid, success in results.items() if not success]
    
    print(f"Total Jobs: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}\n")
    
    if successful:
        print("Successful Jobs:")
        for jid in successful:
            print(f"  - {jid}")
        print()
    
    if failed:
        print("Failed Jobs:")
        for jid in failed:
            print(f"  - {jid}")
        print()
    
    print(f"{'='*70}\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Offline Pipeline: Process local CVs for specified jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single job
  python offline_pipeline.py 3419430

  # Process multiple jobs (comma-separated)
  python offline_pipeline.py "3419430, 3544944, 3600123"
        """
    )
    
    parser.add_argument("job_ids", help="Job IDs to process (comma-separated for multiple)")
    parser.add_argument("--skip-scoring", action="store_true", help="Skip AI scoring step")
    parser.add_argument("--skip-upload", action="store_true", help="Skip Airtable upload step")
    parser.add_argument("--skip-reports", action="store_true", help="Skip detailed report generation")
    
    args = parser.parse_args(argv[1:])
    
    # Validate required scripts exist
    validate_files_exist()
    
    # Parse comma-separated job IDs
    job_ids = [jid.strip() for jid in args.job_ids.split(",")]
    
    print("\n" + "="*70)
    print("OFFLINE PIPELINE - MULTI-JOB MODE")
    print("="*70)
    print(f"\nProcessing {len(job_ids)} job(s): {', '.join(job_ids)}\n")
    
    warn_missing_env()
    
    results = {}
    for idx, job_id in enumerate(job_ids, 1):
        print(f"\n{'='*70}")
        print(f"Processing Job {idx} of {len(job_ids)}: {job_id}")
        print(f"{'='*70}\n")
        
        job_folder = LOCAL_INPUT_DIR / f"job_{job_id}"
        
        # Validate job folder exists
        if not job_folder.exists():
            print(f"ERROR: Job folder not found: {job_folder}")
            print(f"       Expected folder: local_input/job_{job_id}/")
            results[job_id] = False
            continue
        
        # Load job config
        try:
            config = load_job_config(job_folder, job_id)
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            results[job_id] = False
            continue
        
        # Process job
        success = process_single_job(job_id, job_folder, config, args)
        results[job_id] = success
    
    # Print summary
    print_summary(results)
    
    # Return 0 if all succeeded, 1 if any failed
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except KeyboardInterrupt:
        print("\n\nWARNING: Pipeline interrupted by user")
        raise SystemExit(130)
