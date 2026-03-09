"""src/supabase_client.py — compatibility shim (Supabase removed, now uses Airtable).

Any remaining imports of SupabaseClient are redirected to AirtableClient.
"""
from airtable_client import AirtableClient as SupabaseClient  # noqa: F401
