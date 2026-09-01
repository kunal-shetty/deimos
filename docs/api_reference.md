# API Reference

The Deimos Dashboard provides a set of REST endpoints to inspect the agent's internal state.

**Base URL**: `http://127.0.0.1:8420`

## Conversations

### List Conversations
`GET /api/conversations?limit=30`
- **Returns**: List of conversations with `id`, `title`, `started_at`, and `ended_at`.

### Get Messages
`GET /api/conversations/{conversation_id}/messages`
- **Returns**: All messages for the given conversation, ordered by `created_at`.

## Memory

### Get Semantic Facts
`GET /api/memory/facts`
- **Returns**: All durable facts known about the user, ordered by confidence.

### Get Project Facts
`GET /api/memory/projects`
- **Returns**: Facts grouped by project name.

### Get Episodic Summaries
`GET /api/memory/episodic?limit=10`
- **Returns**: The most recent session summaries.

## Planning

### List Plans
`GET /api/plans?project_dir=path`
- **Returns**: All plans found in the `.deimos/plans/` directory of the specified project.

## System

### Get Status
`GET /api/status`
- **Returns**: Configuration status (Supabase, User ID) and the current working directory.
