"""
Supabase client wrapper for database operations.
"""
import os
from supabase import create_client, Client


class SupabaseClient:
    """Wrapper class for Supabase operations."""

    def __init__(self):
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')

        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")

        self.client: Client = create_client(url, key)

    def get_client(self) -> Client:
        """Return the Supabase client instance."""
        return self.client
