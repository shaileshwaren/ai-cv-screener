"""
diagnose_nocodb.py — Diagnose NocoDB table issues

This script will:
1. Compare Supabase and NocoDB columns
2. Identify mismatches
3. Provide recommendations

Usage:
  python diagnose_nocodb.py
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


def main() -> int:
    HEADERS = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    print("\n" + "="*70)
    print("  NocoDB Table Diagnostic")
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
    
    print(f"   Found {len(supabase_cols)} columns in Supabase:")
    for col in sorted(supabase_cols):
        print(f"     - {col}")
    
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
    
    print(f"   Found {len(nocodb_cols)} columns in NocoDB:")
    for col, info in sorted(nocodb_cols.items()):
        system_flag = " [SYSTEM]" if info["system"] else ""
        print(f"     - {col} ({info['uidt']}){system_flag}")
    
    # Compare
    print("\n3. Comparing schemas...")
    
    missing_in_nocodb = supabase_cols - set(nocodb_cols.keys())
    extra_in_nocodb = set(nocodb_cols.keys()) - supabase_cols
    
    if missing_in_nocodb:
        print(f"\n   ⚠️  Columns in Supabase but NOT in NocoDB ({len(missing_in_nocodb)}):")
        for col in sorted(missing_in_nocodb):
            if col != "embedding":  # Skip vector column
                print(f"     - {col}")
    
    if extra_in_nocodb:
        print(f"\n   ⚠️  Columns in NocoDB but NOT in Supabase ({len(extra_in_nocodb)}):")
        for col in sorted(extra_in_nocodb):
            info = nocodb_cols[col]
            if not info["system"]:
                print(f"     - {col} (ID: {info['id']}) - CAN BE DELETED")
    
    if not missing_in_nocodb and not extra_in_nocodb:
        print("   ✅ Schemas match perfectly!")
    
    # Recommendations
    print("\n" + "="*70)
    print("  RECOMMENDATIONS")
    print("="*70)
    
    if extra_in_nocodb:
        print("\nThe following NocoDB columns should be deleted:")
        delete_ids = []
        for col in sorted(extra_in_nocodb):
            info = nocodb_cols[col]
            if not info["system"]:
                delete_ids.append((col, info["id"]))
                print(f"  - {col} (ID: {info['id']})")
        
        if delete_ids:
            print("\nWould you like to delete these columns? (y/n): ", end="")
            response = input().strip().lower()
            
            if response == 'y':
                print("\nDeleting extra columns...")
                for col_name, col_id in delete_ids:
                    r = requests.delete(
                        f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}/columns/{col_id}",
                        headers=HEADERS
                    )
                    if r.status_code in (200, 204):
                        print(f"  ✅ Deleted: {col_name}")
                    else:
                        print(f"  ❌ Failed to delete {col_name}: {r.status_code}")
                
                print("\n✅ Cleanup complete! Please refresh your NocoDB browser tab.")
            else:
                print("\nSkipped deletion. You can delete these columns manually in NocoDB.")
    
    if missing_in_nocodb:
        print("\nThe following Supabase columns are missing in NocoDB:")
        for col in sorted(missing_in_nocodb):
            if col != "embedding":
                print(f"  - {col}")
        print("\nRun 'python sync_nocodb.py' to add these columns.")
    
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
