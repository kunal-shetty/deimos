# Installation Guide

This guide will walk you through setting up Deimos on your local machine.

## Prerequisites

- **Python 3.11+**: Ensure you have Python installed.
- **Git**: Required for version control and updating Deimos.
- **Supabase Account**: Deimos uses Supabase for its long-term memory system.
- **Tavily API Key**: Required for web search capabilities.
- **LLM API Key**: A Groq API key (or other supported provider) for the core intelligence.

## 1. Quick Install (Unix/Bash)

If you are on Linux, macOS, or using Git Bash/WSL on Windows, you can install Deimos with a single command:

```bash
curl -sSL https://deimos.sh/install | sh
```

This script creates a private virtual environment in `~/.deimos/venv` and symlinks the `deimos` command to your path.

## 2. Manual Installation (Windows/PowerShell)

If you prefer to install manually on Windows:

1. **Clone the repository**:
   ```powershell
   git clone https://github.com/your-repo/deimos.git
   cd deimos
   ```

2. **Create a virtual environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```powershell
   pip install .
   ```

## 3. Environment Configuration

Create a `.env` file in the root directory:

```env
# LLM Config
GROQ_API_KEY=your_groq_api_key
LLM_MODEL=llama-3.3-70b-versatile

# Supabase Config
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
DEIMOS_USER_ID=your-user-uuid

# Web Search
TAVILY_API_KEY=your_tavily_api_key

# Agent Settings
MAX_ITERATIONS=30
PLAN_MODE_DEFAULT=true
```

## 4. Supabase Database Setup

Deimos requires a specific schema to manage its episodic and semantic memory. Run the following SQL in your Supabase SQL Editor:

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
deimos assemble
```

To launch the monitoring dashboard:
```bash
deimos dashboard
```
