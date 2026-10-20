-- Deimos memory search: full-text search across facts, project facts,
-- session summaries and past user messages.
--
-- Run once in the Supabase SQL editor. Safe to run again.

-- ── Search columns (kept up to date by Postgres) ────────────────────────────

ALTER TABLE semantic_memories ADD COLUMN IF NOT EXISTS search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', key || ' ' || value)) STORED;
CREATE INDEX IF NOT EXISTS semantic_memories_search_idx ON semantic_memories USING GIN (search);

ALTER TABLE project_memories ADD COLUMN IF NOT EXISTS search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', project_name || ' ' || key || ' ' || value)) STORED;
CREATE INDEX IF NOT EXISTS project_memories_search_idx ON project_memories USING GIN (search);

ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(summary, ''))) STORED;
CREATE INDEX IF NOT EXISTS episodic_memories_search_idx ON episodic_memories USING GIN (search);

-- User messages are stored as a JSON string; assistant turns as an object with "content"
ALTER TABLE messages ADD COLUMN IF NOT EXISTS search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(
        CASE WHEN jsonb_typeof(content) = 'string' THEN content #>> '{}' ELSE content ->> 'content' END,
        ''))) STORED;
CREATE INDEX IF NOT EXISTS messages_search_idx ON messages USING GIN (search);

-- ── Ranked search ───────────────────────────────────────────────────────────
-- score = text relevance x weight (confidence or importance) x recency decay,
-- where recency halves every `half_life` days: slowly for durable facts,
-- quickly for individual messages.

CREATE OR REPLACE FUNCTION search_memories(
    p_user_id UUID,
    p_query TEXT,
    p_limit INT DEFAULT 8,
    p_exclude_conversation UUID DEFAULT NULL
)
RETURNS TABLE (kind TEXT, id UUID, project_name TEXT, body TEXT, created_at TIMESTAMPTZ, score REAL)
LANGUAGE sql STABLE AS $$
    WITH q AS (
        -- OR the words together so any overlap matches; ranking sorts out the best
        SELECT NULLIF(replace(plainto_tsquery('english', p_query)::text, ' & ', ' | '), '')::tsquery AS query
    ),
    hits AS (
        SELECT 'fact'::text AS kind, m.id, NULL::text AS project_name,
               m.key || ': ' || m.value AS body, coalesce(m.last_updated, now()) AS created_at,
               ts_rank_cd(m.search, q.query) * (0.5 + coalesce(m.confidence, 0.5)) AS relevance,
               365.0 AS half_life
        FROM semantic_memories m, q
        WHERE m.user_id = p_user_id AND m.search @@ q.query
      UNION ALL
        SELECT 'project', p.id, p.project_name,
               p.key || ': ' || p.value, coalesce(p.last_updated, now()),
               ts_rank_cd(p.search, q.query) * (0.5 + coalesce(p.confidence, 0.5)),
               365.0
        FROM project_memories p, q
        WHERE p.user_id = p_user_id AND p.search @@ q.query
      UNION ALL
        SELECT 'session', e.id, NULL,
               e.summary, coalesce(e.created_at, now()),
               ts_rank_cd(e.search, q.query) * 0.8,
               60.0
        FROM episodic_memories e, q
        WHERE e.user_id = p_user_id AND e.search @@ q.query
          AND e.conversation_id IS DISTINCT FROM p_exclude_conversation
      UNION ALL
        SELECT 'message', msg.id, NULL,
               left(CASE WHEN jsonb_typeof(msg.content) = 'string' THEN msg.content #>> '{}'
                         ELSE msg.content ->> 'content' END, 500),
               coalesce(msg.created_at, now()),
               ts_rank_cd(msg.search, q.query) * (0.2 + coalesce(msg.importance, 0) / 10.0),
               30.0
        FROM messages msg JOIN conversations c ON c.id = msg.conversation_id, q
        WHERE c.user_id = p_user_id AND msg.role = 'user' AND msg.search @@ q.query
          AND msg.conversation_id IS DISTINCT FROM p_exclude_conversation
    )
    SELECT kind, id, project_name, body, created_at,
           (relevance * power(0.5, extract(epoch FROM now() - created_at) / 86400.0 / half_life))::real AS score
    FROM hits
    ORDER BY score DESC NULLS LAST
    LIMIT p_limit;
$$;
