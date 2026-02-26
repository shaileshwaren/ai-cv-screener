#!/usr/bin/env python3
"""
run_cron.py — Entrypoint for Render Cron Job.

Reads job IDs from RENDER_CRON_JOB_IDS (e.g. "3419430, 3261113") and runs
the online pipeline. Use this as startCommand for a Render cron service.

Example render.yaml cron:
  startCommand: python run_cron.py
  envVars:
    - key: RENDER_CRON_JOB_IDS
      value: "3419430, 3261113"
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE = HERE / "online_pipeline.py"
JOB_IDS = os.getenv("RENDER_CRON_JOB_IDS", "3419430").strip()

if __name__ == "__main__":
    if not JOB_IDS:
        print("RENDER_CRON_JOB_IDS is not set. Set it in Render Dashboard or render.yaml.")
        sys.exit(2)
    cmd = [sys.executable, str(PIPELINE), JOB_IDS]
    sys.exit(subprocess.run(cmd, cwd=str(HERE)).returncode)
