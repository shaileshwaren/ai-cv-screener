"""
update_table_id.py — Update NocoDB table ID in .env file

Usage:
  python update_table_id.py <new_table_id>
  
Example:
  python update_table_id.py m9x2y3z4a5b6c7d8
"""

import sys
import os
from pathlib import Path

def update_env_file(new_table_id: str, new_base_id: str = None):
    """Update the .env file with new NocoDB IDs."""
    
    env_path = Path(".env")
    
    if not env_path.exists():
        print(f"❌ .env file not found at {env_path.absolute()}")
        return False
    
    # Read current .env
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Update lines
    updated = False
    base_updated = False
    new_lines = []
    
    for line in lines:
        if line.startswith("NOCODB_CANDIDATES_TABLE_ID="):
            new_lines.append(f"NOCODB_CANDIDATES_TABLE_ID={new_table_id}\n")
            updated = True
            print(f"✅ Updated NOCODB_CANDIDATES_TABLE_ID to: {new_table_id}")
        elif new_base_id and line.startswith("NOCODB_BASE_ID="):
            new_lines.append(f"NOCODB_BASE_ID={new_base_id}\n")
            base_updated = True
            print(f"✅ Updated NOCODB_BASE_ID to: {new_base_id}")
        else:
            new_lines.append(line)
    
    # If not found, append
    if not updated:
        new_lines.append(f"\nNOCODB_CANDIDATES_TABLE_ID={new_table_id}\n")
        print(f"✅ Added NOCODB_CANDIDATES_TABLE_ID: {new_table_id}")
    
    if new_base_id and not base_updated:
        new_lines.append(f"NOCODB_BASE_ID={new_base_id}\n")
        print(f"✅ Added NOCODB_BASE_ID: {new_base_id}")
    
    # Write back
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    
    return True


def main():
    if len(sys.argv) < 2:
        print("\n" + "="*70)
        print("  Update NocoDB Table ID")
        print("="*70)
        print("\nUsage:")
        print("  python update_table_id.py <table_id> [base_id]")
        print("\nExample:")
        print("  python update_table_id.py m9x2y3z4a5b6c7d8")
        print("  python update_table_id.py m9x2y3z4a5b6c7d8 pg7tczt9uewzmz5")
        print("\nTo find your table ID:")
        print("  1. Open your NocoDB table in browser")
        print("  2. Look at the URL:")
        print("     https://app.nocodb.com/nc/<base_id>/<table_id>")
        print("  3. Copy the table_id from the URL")
        print()
        return 1
    
    new_table_id = sys.argv[1].strip()
    new_base_id = sys.argv[2].strip() if len(sys.argv) > 2 else None
    
    print("\n" + "="*70)
    print("  Updating NocoDB Configuration")
    print("="*70 + "\n")
    
    if update_env_file(new_table_id, new_base_id):
        print("\n" + "="*70)
        print("  ✅ Configuration Updated!")
        print("="*70)
        print("\nNext steps:")
        print("  1. Run: python verify_nocodb.py")
        print("  2. If successful, your pipeline is ready to use!")
        print()
        return 0
    else:
        return 1


if __name__ == "__main__":
    exit(main())
