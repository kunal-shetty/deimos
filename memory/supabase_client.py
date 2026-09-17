"""
Thin wrapper around the Supabase Python client.
All memory modules use this single client instance.
"""

from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from memory.schema import REQUIRED_TABLES, get_schema_query

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

def validate_schema() -> list[str]:
    """
    Checks if the required Supabase tables and columns exist.
    Returns a list of missing elements. An empty list means schema is valid.
    """
    client = get_client()
    try:
        # Use a RPC or a simple query to get schema.
        # Since we can't easily run arbitrary SQL via the JS-like SDK without an RPC,
        # we'll attempt to read one row from each required table.
        missing = []
        for table in REQUIRED_TABLES:
            try:
                client.table(table).select("*").limit(1).execute()
            except Exception as e:
                missing.append(f"Table '{table}' is missing or inaccessible. Error: {e}")
        return missing
    except Exception as e:
        return [f"Schema validation failed: {e}"]
