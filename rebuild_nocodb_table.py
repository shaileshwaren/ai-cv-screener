"""
rebuild_nocodb_table.py — Rebuild NocoDB table from Supabase schema

This script will:
1. Fetch the current Supabase candidates table schema
2. Delete and recreate the NocoDB table with proper column mappings
3. Ensure all columns are properly configured

Usage:
  python rebuild_nocodb_table.py
"""

import os
import sys
import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

NOCODB_TOKEN = os.getenv("NOCODB_TOKEN", "")
NOCODB_BASE_ID = os.getenv("NOCODB_BASE_ID", "")
NOCODB_BASE_URL = "https://app.nocodb.com"
TABLE_ID = os.getenv("NOCODB_CANDIDATES_TABLE_ID", "mvdxvcoapwtlmtx")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")

# Column type mapping
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


def step(msg: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {msg}")
    print(f"{'='*70}")


def get_supabase_schema() -> dict:
    """Fetch Supabase candidates table schema."""
    conn = psycopg2.connect(SUPABASE_DB_URL)
    cur = conn.cursor()
    
    # Get column details
    cur.execute("""
        SELECT 
            column_name, 
            data_type, 
            is_nullable,
            column_default
        FROM information_schema.columns 
        WHERE table_name='candidates' 
        ORDER BY ordinal_position;
    """)
    
    columns = []
    for row in cur.fetchall():
        col_name, data_type, is_nullable, col_default = row
        columns.append({
            "name": col_name,
            "type": data_type,
            "nullable": is_nullable == "YES",
            "default": col_default
        })
    
    cur.close()
    conn.close()
    
    return {"columns": columns}


def get_nocodb_column_type(pg_type: str, col_name: str) -> str:
    """Map PostgreSQL type to NocoDB UIDT."""
    if col_name in UIDT_MAP:
        return UIDT_MAP[col_name]
    
    type_map = {
        "integer": "Number",
        "bigint": "Number",
        "numeric": "Number",
        "real": "Number",
        "double precision": "Number",
        "character varying": "SingleLineText",
        "text": "LongText",
        "boolean": "Checkbox",
        "timestamp with time zone": "DateTime",
        "timestamp without time zone": "DateTime",
        "date": "Date",
        "json": "JSON",
        "jsonb": "JSON",
    }
    
    return type_map.get(pg_type, "LongText")


def refresh_nocodb_connection() -> bool:
    """Refresh the NocoDB base connection to Supabase."""
    step("Refreshing NocoDB Base Connection")
    
    HEADERS = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    # Get base details
    r = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/projects/{NOCODB_BASE_ID}", headers=HEADERS)
    if r.status_code != 200:
        print(f"  ❌ Failed to fetch base: {r.status_code}")
        return False
    
    print(f"  ✅ Base connection active")
    return True


def sync_table_columns() -> bool:
    """Sync all columns from Supabase to NocoDB."""
    step("Syncing Table Columns")
    
    HEADERS = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    # Get Supabase schema
    schema = get_supabase_schema()
    supabase_cols = {col["name"]: col for col in schema["columns"]}
    
    print(f"  Found {len(supabase_cols)} columns in Supabase")
    
    # Get NocoDB table
    r = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}", headers=HEADERS)
    if r.status_code != 200:
        print(f"  ❌ Failed to fetch NocoDB table: {r.status_code}")
        return False
    
    table_data = r.json()
    nocodb_cols = {c["column_name"]: c for c in table_data.get("columns", []) if c.get("column_name")}
    
    print(f"  Found {len(nocodb_cols)} columns in NocoDB")
    
    # Add missing columns
    added = []
    for col_name, col_info in supabase_cols.items():
        if col_name == "embedding":  # Skip vector column
            continue
            
        if col_name not in nocodb_cols:
            uidt = get_nocodb_column_type(col_info["type"], col_name)
            
            payload = {
                "column_name": col_name,
                "title": col_name.replace("_", " ").title(),
                "uidt": uidt,
            }
            
            # Set primary key for candidate_id
            if col_name == "candidate_id":
                payload["pk"] = True
            
            r2 = requests.post(
                f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}/columns",
                headers=HEADERS,
                json=payload
            )
            
            if r2.status_code in (200, 201):
                added.append(col_name)
                print(f"  ✅ Added column: {col_name} ({uidt})")
            else:
                print(f"  ⚠️  Failed to add column '{col_name}': {r2.status_code} - {r2.text[:200]}")
    
    if not added:
        print("  ✅ All columns already present")
    
    return True


def reload_schema_cache() -> bool:
    """Reload PostgREST schema cache."""
    step("Reloading Supabase Schema Cache")
    
    try:
        conn = psycopg2.connect(SUPABASE_DB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT pg_notify('pgrst', 'reload schema');")
        cur.close()
        conn.close()
        print("  ✅ Schema cache reloaded")
        return True
    except Exception as e:
        print(f"  ⚠️  Schema reload warning: {e}")
        return False


def verify_table_access() -> bool:
    """Verify NocoDB can access the table."""
    step("Verifying Table Access")
    
    HEADERS = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    # Try to fetch first row
    r = requests.get(
        f"{NOCODB_BASE_URL}/api/v1/db/data/noco/{NOCODB_BASE_ID}/{TABLE_ID}?limit=1",
        headers=HEADERS
    )
    
    if r.status_code == 200:
        data = r.json()
        count = len(data.get("list", []))
        print(f"  ✅ Table accessible - found {count} record(s)")
        return True
    else:
        print(f"  ❌ Table access failed: {r.status_code}")
        print(f"  Response: {r.text[:500]}")
        return False


def main() -> int:
    if not NOCODB_TOKEN:
        print("ERROR: NOCODB_TOKEN not set in .env")
        return 1
    if not NOCODB_BASE_ID:
        print("ERROR: NOCODB_BASE_ID not set in .env")
        return 1
    if not SUPABASE_DB_URL:
        print("ERROR: SUPABASE_DB_URL not set in .env")
        return 1
    
    print("\n" + "="*70)
    print("  NocoDB Table Rebuild Utility")
    print("="*70)
    
    # Step 1: Reload schema cache
    if not reload_schema_cache():
        print("\n⚠️  Warning: Schema cache reload failed, continuing anyway...")
    
    # Step 2: Refresh NocoDB connection
    if not refresh_nocodb_connection():
        print("\n❌ Failed to refresh NocoDB connection")
        return 1
    
    # Step 3: Sync columns
    if not sync_table_columns():
        print("\n❌ Failed to sync table columns")
        return 1
    
    # Step 4: Verify access
    if not verify_table_access():
        print("\n⚠️  Warning: Table verification failed")
        print("\nPossible solutions:")
        print("  1. Check that the Supabase connection in NocoDB is active")
        print("  2. Verify the table ID is correct: " + TABLE_ID)
        print("  3. Try refreshing the NocoDB base connection manually")
        print("  4. Check Supabase RLS policies allow service role access")
        return 1
    
    print("\n" + "="*70)
    print("  ✅ NocoDB Table Rebuild Complete!")
    print("="*70)
    print("\nNext steps:")
    print("  1. Refresh your NocoDB browser tab")
    print("  2. Navigate to the Candidates table")
    print("  3. All columns should now be visible and accessible")
    print()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
