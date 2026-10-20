# Installation Guide

This guide will walk you through setting up Deimos on your local machine.

## Prerequisites

- **Python 3.11+** from [python.org](https://www.python.org/downloads/). On Windows, tick
  "Add python.exe to PATH" in the installer.
- **A Groq API key** from [console.groq.com/keys](https://console.groq.com/keys).
- Optional: a **Tavily** key (web search), a **TypeSafe** key (Jev decisions), and a
  **Supabase** project (long-term memory).

## 1. Install

**macOS, Linux, WSL**

```bash
curl -fsSL https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.ps1 | iex
```

The installer:

1. finds Python 3.11 or newer,
2. creates a private environment in `~/.deimos/venv` (so nothing touches your other Python projects),
3. installs the latest Deimos from GitHub into it, and
4. adds a `deimos` command to your PATH: a link in `~/.local/bin` on macOS/Linux, or
   `%USERPROFILE%\.deimos\bin` on Windows. Only `deimos` is added, not the environment's
   `python` or `pip`.

Open a new terminal afterwards so the command is found. Running the installer again updates an
existing install. Options (set as environment variables before running it): `DEIMOS_REF` to install
another branch, `DEIMOS_HOME` to change the install folder, `DEIMOS_NO_MODIFY_PATH=1` to leave your
PATH alone.

**Update:** `deimos update`. **Uninstall:** delete `~/.deimos` and the `deimos` command
(`~/.local/bin/deimos`, or remove `%USERPROFILE%\.deimos\bin` from your user PATH on Windows).

## 2. Configuration

The first time you run `deimos` it asks for your keys and saves them to `~/.deimos/.env`.
Change them later with `deimos setup`. Keys are read from, in order of priority:

1. environment variables,
2. a `.env` next to the source (for a development checkout),
3. `~/.deimos/.env`.

All settings:

```env
# Required
GROQ_API_KEY=your_groq_api_key

# Optional features
TAVILY_API_KEY=your_tavily_api_key        # web search
TYPESAFE_API_KEY=your_typesafe_api_key    # Jev structured decisions (falls back to Groq)

# Optional long-term memory (see section 4)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
DEIMOS_USER_ID=your-user-uuid

# Optional tuning
LLM_MODEL=openai/gpt-oss-120b
LLM_MODEL_FAST=openai/gpt-oss-20b
MAX_ITERATIONS=30
PLAN_MODE_DEFAULT=true
```

Behaviour settings (permission mode, tool output limit, hooks) live in `~/.deimos/settings.json`
or a project's `.deimos/settings.json`; see the [User Guide](user_guide.md).

## 3. Developing Deimos

```bash
git clone https://github.com/kunal-shetty/deimos && cd deimos
python -m pip install -e ".[dev]"
python -m pytest
```

In a git checkout, `deimos update` pulls and reinstalls the checkout instead of downloading.

## 4. Supabase Database Setup (optional)

Long-term memory needs a Supabase project with the following schema. Without it, Deimos runs with memory off. Run the following SQL in your Supabase SQL Editor:

```sql
-- Users Table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Conversations Table
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ
);

-- Messages Table
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content JSONB,
    importance INT DEFAULT 0,
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Semantic Memory Table (General Facts)
CREATE TABLE semantic_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.75,
    frequency INT DEFAULT 1,
    last_updated TIMESTAMPTZ DEFAULT now()
);

-- Project Memory Table (Project-Specific Facts)
CREATE TABLE project_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    project_name TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.75,
    last_updated TIMESTAMPTZ DEFAULT now()
);

-- Episodic Memory Table (Session Summaries)
CREATE TABLE episodic_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Archive Memory Table (Compressed Long-term Context)
CREATE TABLE archive_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    level INT NOT NULL,
    summary TEXT,
    source_ids UUID[],
    created_at TIMESTAMPTZ DEFAULT now()
);
```

## 5. Running Deimos

Once installed and configured, you can start the agent:

```bash
deimos
```

To launch the monitoring dashboard:
```bash
deimos dashboard
```
