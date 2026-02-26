"""
sync_nocodb.py — Standalone NocoDB column-sync utility.

Ensures all columns in the Supabase `candidates` table are present and
visible in the NocoDB Candidates view. Run after schema changes.

Usage:
  python sync_nocodb.py
"""

import os
import sys
import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

NOCODB_TOKEN = os.getenv("NOCODB_TOKEN", "")
NOCODB_BASE_URL = "https://app.nocodb.com"
TABLE_ID = os.getenv("NOCODB_CANDIDATES_TABLE_ID", "mvdxvcoapwtlmtx")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")

UIDT_MAP = {
    "candidate_id": "Number",
    "job_id": "Number",
    "org_id": "Number",
    "ai_score": "Number",
    "email": "Email",
    "resume_file": "URL",
    "updated_at": "DateTime",
    "created_at": "DateTime",
}


def step(msg: str) -> None:
    print(f"\n{'─'*50}")
    print(f"  {msg}")
    print(f"{'─'*50}")


def main() -> int:
    if not NOCODB_TOKEN:
        print("ERROR: NOCODB_TOKEN not set in .env")
        return 1
    if not SUPABASE_DB_URL:
        print("ERROR: SUPABASE_DB_URL not set in .env")
        return 1

    HEADERS = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}

    # ── 1. Reload PostgREST schema cache ────────────────────────────────
    step("1/3  Reloading Supabase schema cache")
    try:
        conn = psycopg2.connect(SUPABASE_DB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT pg_notify('pgrst', 'reload schema');")
        cur.close()
        conn.close()
        print("  ✅ Schema cache reloaded")
    except Exception as e:
        print(f"  ⚠️  Schema reload warning: {e}")

    # ── 2. Fetch Supabase candidates columns ─────────────────────────────
    step("2/3  Fetching Supabase columns")
    try:
        conn = psycopg2.connect(SUPABASE_DB_URL)
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='candidates' ORDER BY ordinal_position;"
        )
        supabase_cols = {r[0] for r in cur.fetchall()}
        cur.close()
        conn.close()
        print(f"  Found {len(supabase_cols)} Supabase columns")
    except Exception as e:
        print(f"  ❌ Could not fetch Supabase columns: {e}")
        return 1

    # ── 3. Sync to NocoDB ────────────────────────────────────────────────
    step("3/3  Syncing NocoDB column visibility")
    r = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}", headers=HEADERS)
    if r.status_code != 200:
        print(f"  ❌ Failed to fetch NocoDB table: {r.status_code} {r.text}")
        return 1

    nocodb_cols = {
        c["column_name"]: c["id"]
        for c in r.json().get("columns", [])
        if c.get("column_name")
    }

    added = []
    for col in sorted(supabase_cols):
        if col in nocodb_cols or col == "embedding":
            continue
        uidt = UIDT_MAP.get(col, "LongText")
        r2 = requests.post(
            f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}/columns",
            headers=HEADERS,
            json={"column_name": col, "title": col.replace("_", " ").title(), "uidt": uidt},
        )
        if r2.status_code in (200, 201):
            added.append(col)
        else:
            print(f"  ⚠️  Could not add column '{col}': {r2.status_code}")

    if added:
        print(f"  ✅ Added to NocoDB: {added}")
    else:
        print("  ✅ NocoDB already in sync with Supabase")

    print("\n✅ NocoDB sync complete!\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
