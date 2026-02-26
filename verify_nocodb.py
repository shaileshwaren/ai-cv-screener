"""Quick verification of NocoDB table access"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOCODB_TOKEN = os.getenv("NOCODB_TOKEN")
NOCODB_BASE_ID = os.getenv("NOCODB_BASE_ID")
TABLE_ID = os.getenv("NOCODB_CANDIDATES_TABLE_ID")
NOCODB_BASE_URL = "https://app.nocodb.com"

headers = {"xc-token": NOCODB_TOKEN}
url = f"{NOCODB_BASE_URL}/api/v1/db/data/noco/{NOCODB_BASE_ID}/{TABLE_ID}?limit=5"

print(f"\nTesting NocoDB table access...")
print(f"URL: {url}\n")

r = requests.get(url, headers=headers)

print(f"Status Code: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    records = data.get("list", [])
    print(f"✅ SUCCESS - Table is accessible!")
    print(f"Found {len(records)} record(s)")
    if records:
        print(f"\nFirst record columns: {list(records[0].keys())}")
else:
    print(f"❌ FAILED - Table not accessible")
    print(f"Response: {r.text[:500]}")
