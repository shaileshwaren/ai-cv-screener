#!/usr/bin/env python3
"""Run supabase_migration_match_id_pk.sql against the Supabase DB using SUPABASE_DB_URL from .env."""
from __future__ import annotations

import sys
from pathlib import Path

# Load .env via config
from config import Config

MIGRATION_FILE = Path(__file__).resolve().parent / "supabase_migration_match_id_pk.sql"


def main() -> int:
    if not Config.SUPABASE_DB_URL:
        print("SUPABASE_DB_URL is not set in .env. Cannot run migration.")
        return 2
    sql = MIGRATION_FILE.read_text(encoding="utf-8")
    # Split into statements (skip comments and empty)
    statements = []
    for part in sql.split(";"):
        part = part.strip()
        if not part:
            continue
        # Skip if only comments (no actual SQL)
        lines = [l for l in part.splitlines() if l.strip() and not l.strip().startswith("--")]
        if not lines:
            continue
        stmt = part if part.rstrip().endswith(";") else part + ";"
        statements.append(stmt)
    if not statements:
        print("No statements to run.")
        return 0
    try:
        import psycopg2
        conn = psycopg2.connect(Config.SUPABASE_DB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        for i, stmt in enumerate(statements, 1):
            try:
                cur.execute(stmt)
                print(f"  OK: statement {i}")
            except Exception as e:
                print(f"  Statement {i} failed: {e}")
                cur.close()
                conn.close()
                return 1
        cur.close()
        conn.close()
        print("Migration completed successfully.")
        return 0
    except ImportError:
        print("psycopg2 not installed. Run: pip install psycopg2-binary")
        return 2
    except Exception as e:
        print(f"Migration failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
