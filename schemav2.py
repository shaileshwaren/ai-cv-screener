#schemav2.py - Airtable schema viewer using the new metadata API

import requests
import os
import sys
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

AIRTABLE_API_KEY = os.getenv("AIRTABLE_TOKEN")

headers = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}


def parse_airtable_url(url: str) -> tuple[str, str]:
    """Extract base_id and table_id from an Airtable URL."""
    path = urlparse(url).path.strip("/").split("/")
    if len(path) < 2 or not path[0].startswith("app") or not path[1].startswith("tbl"):
        raise ValueError(f"Invalid Airtable URL: {url}\nExpected format: https://airtable.com/appXXX/tblXXX/...")
    return path[0], path[1]


def get_table_schema(base_id: str, table_id: str) -> dict:
    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    tables = response.json().get("tables", [])
    target_table = next((t for t in tables if t["id"] == table_id), None)

    if not target_table:
        raise ValueError(f"Table ID '{table_id}' not found in base '{base_id}'")

    return target_table


def get_table_name(base_id: str, table_id: str) -> str:
    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    tables = response.json().get("tables", [])
    table = next((t for t in tables if t["id"] == table_id), None)

    if not table:
        raise ValueError(f"Table ID '{table_id}' not found")

    return table["name"]


def print_schema(schema: dict):
    print(f"Table: {schema['name']} (ID: {schema['id']})")
    primary_field_id = schema.get('primaryFieldId')
    primary_field = next((f for f in schema.get("fields", []) if f["id"] == primary_field_id), None)
    print(f"Primary field: {primary_field['name'] if primary_field else 'N/A'}")

    print("\nFields:")
    for field in schema.get("fields", []):
        field_type = field.get("type", "unknown")
        field_name = field["name"]
        options = field.get("options", {})

        print(f"  - {field_name}: {field_type}")

        description = field.get("description")
        if description:
            print(f"      description: {description}")

        if field_type == "multipleRecordLinks":
    
            print(f"      -> linked to table: {options.get('linkedTableId')}")
        elif field_type in ("singleSelect", "multipleSelects"):
            choices = [c["name"] for c in options.get("choices", [])]
            print(f"      -> choices: {choices}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python schema.py <airtable_url>")
        print("Example: python schema.py https://airtable.com/appklHzqCQw8iGDVC/tblJ2OkvaWI7vi0vI/viwtBaczS9iTToRf3?blocks=hide")
        sys.exit(1)

    BASE_ID, TABLE_ID = parse_airtable_url(sys.argv[1])
    print(f"Base ID: {BASE_ID}")
    print(f"Table ID: {TABLE_ID}\n")

    name = get_table_name(BASE_ID, TABLE_ID)
    print(f"Table name: {name}")
    schema = get_table_schema(BASE_ID, TABLE_ID)
    print_schema(schema)