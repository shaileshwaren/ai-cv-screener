"""
discover_nocodb_bases.py — Discover all NocoDB bases and tables

This will list all your NocoDB bases and their tables.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOCODB_TOKEN = os.getenv("NOCODB_TOKEN")
NOCODB_BASE_URL = "https://app.nocodb.com"

def main():
    headers = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    print("\n" + "="*70)
    print("  NocoDB Bases & Tables Discovery")
    print("="*70)
    
    # Get all bases/projects
    print("\nFetching all bases...")
    r = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/projects", headers=headers)
    
    if r.status_code != 200:
        print(f"❌ Failed to fetch bases: {r.status_code}")
        print(f"Response: {r.text[:500]}")
        return 1
    
    bases = r.json()
    if isinstance(bases, dict):
        bases = bases.get("list", [])
    
    print(f"\nFound {len(bases)} base(s):\n")
    
    for idx, base in enumerate(bases, 1):
        base_id = base.get("id", "")
        base_title = base.get("title", "")
        
        print(f"\n{'='*70}")
        print(f"BASE {idx}: {base_title}")
        print(f"ID: {base_id}")
        print(f"{'='*70}")
        
        # Get tables for this base
        r_tables = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/projects/{base_id}", headers=headers)
        
        if r_tables.status_code != 200:
            print(f"  ⚠️  Could not fetch tables: {r_tables.status_code}")
            continue
        
        base_data = r_tables.json()
        tables = base_data.get("tables", [])
        
        print(f"\nTables in this base: {len(tables)}\n")
        
        for t_idx, table in enumerate(tables, 1):
            table_id = table.get("id", "")
            table_title = table.get("title", "")
            table_name = table.get("table_name", "")
            
            print(f"  {t_idx}. {table_title}")
            print(f"     ID: {table_id}")
            print(f"     Table Name: {table_name}")
            
            # Test access
            test_url = f"{NOCODB_BASE_URL}/api/v1/db/data/noco/{base_id}/{table_id}?limit=1"
            r_test = requests.get(test_url, headers=headers)
            
            if r_test.status_code == 200:
                data = r_test.json()
                count = len(data.get("list", []))
                print(f"     Status: ✅ Accessible ({count} record(s))")
                
                if count > 0:
                    columns = list(data["list"][0].keys())
                    print(f"     Columns: {', '.join(columns[:8])}")
                    if len(columns) > 8:
                        print(f"              ... and {len(columns) - 8} more")
                    
                    # Check if this looks like candidates table
                    if any(col in columns for col in ["candidate_id", "full_name", "ai_score"]):
                        print(f"\n     🎯 THIS LOOKS LIKE YOUR CANDIDATES TABLE!")
                        print(f"     💡 Update your .env file:")
                        print(f"        NOCODB_BASE_ID={base_id}")
                        print(f"        NOCODB_CANDIDATES_TABLE_ID={table_id}")
            else:
                print(f"     Status: ❌ Not accessible ({r_test.status_code})")
            
            print()
    
    print("\n" + "="*70)
    print("Discovery Complete")
    print("="*70 + "\n")
    
    return 0

if __name__ == "__main__":
    exit(main())
