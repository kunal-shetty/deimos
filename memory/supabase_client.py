"""
Thin wrapper around the Supabase Python client.
All memory modules use this single client instance.
"""

from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY


_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be set in .env"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client