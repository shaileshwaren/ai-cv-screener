"""
force_nocodb_sync.py — Force NocoDB to resync with Supabase

This will trigger NocoDB to refresh its metadata from the Supabase source.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOCODB_TOKEN = os.getenv("NOCODB_TOKEN")
NOCODB_BASE_ID = os.getenv("NOCODB_BASE_ID")
TABLE_ID = os.getenv("NOCODB_CANDIDATES_TABLE_ID")
NOCODB_BASE_URL = "https://app.nocodb.com"

def main():
    headers = {"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"}
    
    print("\n" + "="*70)
    print("  Force NocoDB Metadata Sync")
    print("="*70)
    
    # Step 1: Get table metadata
    print("\n1. Fetching table metadata...")
    r = requests.get(f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}", headers=headers)
    if r.status_code != 200:
        print(f"   ❌ Failed: {r.status_code}")
        return 1
    
    table_data = r.json()
    print(f"   ✅ Table: {table_data.get('title', 'Unknown')}")
    
    # Step 2: Trigger meta sync
    print("\n2. Triggering metadata sync...")
    sync_url = f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}/meta-diff"
    r = requests.get(sync_url, headers=headers)
    
    if r.status_code == 200:
        diff = r.json()
        print(f"   ✅ Meta diff retrieved")
        print(f"   Detected changes: {diff}")
        
        # Apply the sync
        print("\n3. Applying metadata sync...")
        apply_url = f"{NOCODB_BASE_URL}/api/v1/db/meta/tables/{TABLE_ID}/meta-diff"
        r2 = requests.post(apply_url, headers=headers, json={})
        
        if r2.status_code in (200, 201):
            print(f"   ✅ Metadata synced successfully")
        else:
            print(f"   ⚠️  Sync response: {r2.status_code} - {r2.text[:200]}")
    else:
        print(f"   ⚠️  Meta diff not available: {r.status_code}")
        print(f"   This might mean the table is already in sync")
    
    # Step 3: Try alternative - reload base
    print("\n4. Reloading base connection...")
    base_url = f"{NOCODB_BASE_URL}/api/v1/db/meta/projects/{NOCODB_BASE_ID}"
    r = requests.get(base_url, headers=headers)
    
    if r.status_code == 200:
        print(f"   ✅ Base connection active")
    else:
        print(f"   ❌ Base connection issue: {r.status_code}")
    
    # Step 4: Verify access
    print("\n5. Verifying table access...")
    test_url = f"{NOCODB_BASE_URL}/api/v1/db/data/noco/{NOCODB_BASE_ID}/{TABLE_ID}?limit=1"
    r = requests.get(test_url, headers=headers)
    
    if r.status_code == 200:
        data = r.json()
        count = len(data.get("list", []))
        print(f"   ✅ SUCCESS! Table accessible - found {count} record(s)")
        
        if count > 0:
            print(f"\n   Available columns: {list(data['list'][0].keys())}")
    else:
        print(f"   ❌ Still failing: {r.status_code}")
        print(f"   Error: {r.text[:300]}")
        
        print("\n" + "="*70)
        print("  MANUAL FIX REQUIRED")
        print("="*70)
        print("\nThe NocoDB table needs to be manually refreshed:")
        print("1. Go to NocoDB web interface")
        print("2. Navigate to your base settings")
        print("3. Find the Supabase connection")
        print("4. Click 'Sync Metadata' or 'Reload' button")
        print("5. This will force NocoDB to re-read the Supabase schema")
        print("\nAlternatively, you may need to:")
        print("- Delete the table in NocoDB and re-import it from Supabase")
        print("- Or check if there are any views/filters referencing old columns")
        return 1
    
    print("\n" + "="*70)
    print("  ✅ NocoDB Sync Complete!")
    print("="*70)
    print("\nRefresh your browser and the table should work now.")
    print()
    
    return 0

if __name__ == "__main__":
    exit(main())
