"""
discover_nocodb_tables.py — Discover all tables in NocoDB base

This will list all tables in your NocoDB base so we can identify the new one.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOCODB_TOKEN = os.getenv("NOCODB_TOKEN")
NOCODB_BASE_ID = os.getenv("NOCODB_BASE_ID")
NOCODB_BASE_URL = "https://app.nocodb.com"

def main():
    headers = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    print("\n" + "="*70)
    print("  NocoDB Tables Discovery")
    print("="*70)
    
    # Get base info with all tables
    print(f"\nFetching tables from base: {NOCODB_BASE_ID}")
    r = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/projects/{NOCODB_BASE_ID}", headers=headers)
    
    if r.status_code != 200:
        print(f"❌ Failed to fetch base: {r.status_code}")
        return 1
    
    base_data = r.json()
    tables = base_data.get("tables", [])
    
    print(f"\nFound {len(tables)} table(s):\n")
    
    for idx, table in enumerate(tables, 1):
        table_id = table.get("id", "")
        table_title = table.get("title", "")
        table_name = table.get("table_name", "")
        table_type = table.get("type", "")
        
        print(f"{idx}. {table_title}")
        print(f"   ID: {table_id}")
        print(f"   Table Name: {table_name}")
        print(f"   Type: {table_type}")
        
        # Test access to this table
        test_url = f"{NOCODB_BASE_URL}/api/v1/db/data/noco/{NOCODB_BASE_ID}/{table_id}?limit=1"
        r_test = requests.get(test_url, headers=headers)
        
        if r_test.status_code == 200:
            data = r_test.json()
            count = len(data.get("list", []))
            print(f"   Status: ✅ Accessible ({count} record(s) found)")
            
            if count > 0:
                columns = list(data["list"][0].keys())
                print(f"   Columns ({len(columns)}): {', '.join(columns[:10])}")
                if len(columns) > 10:
                    print(f"              ... and {len(columns) - 10} more")
        else:
            print(f"   Status: ❌ Not accessible ({r_test.status_code})")
        
        print()
    
    # Check for candidates-related tables
    print("="*70)
    print("Looking for 'candidates' tables...")
    print("="*70 + "\n")
    
    candidates_tables = [t for t in tables if "candidate" in t.get("title", "").lower() or "candidate" in t.get("table_name", "").lower()]
    
    if candidates_tables:
        print(f"Found {len(candidates_tables)} candidates-related table(s):\n")
        for table in candidates_tables:
            print(f"✓ {table.get('title')} (ID: {table.get('id')})")
            
            # Test this table
            test_url = f"{NOCODB_BASE_URL}/api/v1/db/data/noco/{NOCODB_BASE_ID}/{table.get('id')}?limit=1"
            r_test = requests.get(test_url, headers=headers)
            
            if r_test.status_code == 200:
                data = r_test.json()
                count = len(data.get("list", []))
                print(f"  Status: ✅ WORKING ({count} record(s))")
                
                if count > 0:
                    columns = list(data["list"][0].keys())
                    print(f"  Columns: {len(columns)} total")
                    print(f"  Sample: {', '.join(columns[:5])}...")
                    
                print(f"\n  💡 To use this table, update your .env file:")
                print(f"     NOCODB_CANDIDATES_TABLE_ID={table.get('id')}")
            else:
                print(f"  Status: ❌ Error {r_test.status_code}")
            
            print()
    else:
        print("No candidates tables found. Please check the table name.")
    
    return 0

if __name__ == "__main__":
    exit(main())
