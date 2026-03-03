"""
Supabase client wrapper for database operations.
"""
import os
from typing import Any, Dict, Optional

from supabase import Client, create_client


class SupabaseClient:
    """Wrapper class for Supabase operations."""

    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")

        self.client: Client = create_client(url, key)

    def get_client(self) -> Client:
        """Return the raw Supabase client instance."""
        return self.client

    # =========================
    # Rubrics
    # =========================
    def get_rubric(self, job_id: str, table: str = "rubrics") -> Dict[str, Any]:
        """Fetch the rubric JSON for a given job_id from Supabase.

        Assumes a `rubrics` table with columns:
          - job_id (text / int, comparable to the provided job_id)
          - rubric (jsonb)
          - rubric_version (text, optional)
        """
        # Query the latest rubric for this job (by rubric_version desc if present)
        query = (
            self.client.table(table)
            .select("*")
            .eq("job_id", job_id)
            .order("rubric_version", desc=True)
            .limit(1)
        )
        resp = query.execute()
        rows = getattr(resp, "data", None) or []
        if not rows:
            raise LookupError(f"No rubric found in '{table}' for job_id={job_id!r}")

        row = rows[0]
        rubric = row.get("rubric")
        if not isinstance(rubric, dict):
            raise TypeError(f"Rubric row for job_id={job_id!r} missing valid 'rubric' JSON")
        return rubric

    def upsert_rubric(
        self,
        job_id: str,
        rubric: Dict[str, Any],
        rubric_version: Optional[str] = None,
        table: str = "rubrics",
    ) -> None:
        """Upsert a rubric into the rubrics table.

        Uses (job_id, rubric_version) as the natural key when rubric_version is provided,
        otherwise upserts on job_id only (latest wins).
        """
        payload: Dict[str, Any] = {
            "job_id": job_id,
            "rubric": rubric,
        }
        if rubric_version:
            payload["rubric_version"] = rubric_version

        on_conflict = "job_id,rubric_version" if rubric_version else "job_id"
        self.client.table(table).upsert(payload, on_conflict=on_conflict).execute()
