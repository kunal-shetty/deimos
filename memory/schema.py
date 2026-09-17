"""
Schema definition for Deimos memory.
Used for validation and potential migrations.
"""

REQUIRED_TABLES = {
    "users": ["id", "created_at"],
    "conversations": ["id", "user_id", "title", "started_at", "ended_at"],
    "messages": ["id", "conversation_id", "role", "content", "importance", "summary", "created_at"],
    "semantic_memories": ["id", "user_id", "key", "value", "confidence", "frequency", "last_updated"],
    "project_memories": ["id", "user_id", "project_name", "key", "value", "confidence", "last_updated"],
    "episodic_memories": ["id", "user_id", "conversation_id", "summary", "created_at"],
    "archive_memories": ["id", "user_id", "level", "summary", "source_ids", "created_at"],
}

def get_schema_query():
    """
    Returns a SQL query that lists all tables and their columns
    in the public schema.
    """
    return """
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, ordinal_position;
    """
