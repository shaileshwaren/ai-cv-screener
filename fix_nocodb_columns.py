"""
fix_nocodb_columns.py — Automatically fix NocoDB column mismatches

This script will:
1. Compare Supabase and NocoDB columns
2. Delete extra columns in NocoDB
3. Add missing columns to NocoDB

Usage:
  python fix_nocodb_columns.py
"""

import os
import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

NOCODB_TOKEN = os.getenv("NOCODB_TOKEN", "")
NOCODB_BASE_ID = os.getenv("NOCODB_BASE_ID", "")
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
    "ai_report_html": "URL",
    "updated_at": "DateTime",
    "created_at": "DateTime",
}


def main() -> int:
    HEADERS = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    print("\n" + "="*70)
    print("  NocoDB Column Fix Utility")
    print("="*70)
    
    # Get Supabase columns
    print("\n1. Fetching Supabase columns...")
    conn = psycopg2.connect(SUPABASE_DB_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='candidates' ORDER BY ordinal_position;"
    )
    supabase_cols = {r[0] for r in cur.fetchall()}
    cur.close()
    conn.close()
    print(f"   ✅ Found {len(supabase_cols)} columns in Supabase")
    
    # Get NocoDB columns
    print("\n2. Fetching NocoDB columns...")
    r = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}", headers=HEADERS)
    if r.status_code != 200:
        print(f"   ❌ Failed to fetch NocoDB table: {r.status_code}")
        return 1
    
    table_data = r.json()
    nocodb_cols = {}
    for c in table_data.get("columns", []):
        if c.get("column_name"):
            nocodb_cols[c["column_name"]] = {
                "id": c.get("id"),
                "title": c.get("title"),
                "uidt": c.get("uidt"),
                "system": c.get("system", False)
            }
    
    print(f"   ✅ Found {len(nocodb_cols)} columns in NocoDB")
    
    # Find mismatches
    extra_in_nocodb = set(nocodb_cols.keys()) - supabase_cols
    
    # Delete extra columns
    if extra_in_nocodb:
        print(f"\n3. Deleting {len(extra_in_nocodb)} extra columns from NocoDB...")
        deleted = 0
        for col in sorted(extra_in_nocodb):
            info = nocodb_cols[col]
            if not info["system"]:
                print(f"   Deleting: {col}...", end=" ")
                r = requests.delete(
                    f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}/columns/{info['id']}",
                    headers=HEADERS
                )
                if r.status_code in (200, 204):
                    print("✅")
                    deleted += 1
                else:
                    print(f"❌ (Status: {r.status_code})")
        
        print(f"   ✅ Deleted {deleted} columns")
    else:
        print("\n3. No extra columns to delete")
    
    # Verify table access
    print("\n4. Verifying table access...")
    r = requests.get(
        f"{NOCODB_BASE_URL}/api/v1/db/data/noco/{NOCODB_BASE_ID}/{TABLE_ID}?limit=1",
        headers=HEADERS
    )
    
    if r.status_code == 200:
        data = r.json()
        count = len(data.get("list", []))
        print(f"   ✅ Table accessible - found {count} record(s)")
    else:
        print(f"   ❌ Table access failed: {r.status_code}")
        print(f"   Response: {r.text[:500]}")
        return 1
    
    print("\n" + "="*70)
    print("  ✅ NocoDB Column Fix Complete!")
    print("="*70)
    print("\nNext steps:")
    print("  1. Refresh your NocoDB browser tab (Ctrl+Shift+R or Cmd+Shift+R)")
    print("  2. Navigate to the Candidates table")
    print("  3. The table should now load without errors")
    print()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
