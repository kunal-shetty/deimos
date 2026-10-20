import os
from pathlib import Path
from dotenv import load_dotenv

# Paths
ROOT_DIR = Path(__file__).parent
PROMPTS_DIR = ROOT_DIR / "prompts"
LOCAL_DIR = Path.home() / ".deimos"
ENV_FILE = LOCAL_DIR / ".env"  # written by `deimos setup`

# Settings come from the environment first, then a .env next to the source
# (a development checkout), then ~/.deimos/.env (an installed copy).
# load_dotenv never overrides a variable that is already set.
load_dotenv(ROOT_DIR / ".env")
load_dotenv(ENV_FILE)

# LLM
LLM_API_KEY = os.getenv("GROQ_API_KEY")
LLM_PROVIDER = "groq"
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
# Smaller, cheaper model for side jobs: plan steps aside, titles, summaries,
# fact extraction and the Groq fallback for structured decisions
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", "openai/gpt-oss-20b")

# Structured decisions (TypeSafe Jev). Unset key -> Groq fallback only.
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")
JEV_MODEL = os.getenv("JEV_MODEL", "jev-latest")

# Web Search
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Agent
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "30"))
CONTEXT_SAFE_LIMIT = int(os.getenv("CONTEXT_SAFE_LIMIT", "100000")) # tokens

# Supabase / Memory
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEIMOS_USER_ID = os.getenv("DEIMOS_USER_ID")  # uuid of the row in `users` table

# Local files (input history, etc — not synced to Supabase)
INPUT_HISTORY_FILE = LOCAL_DIR / "input_history"
MODEL_FILE = LOCAL_DIR / "model.txt"

# If a model was previously set via /model, it overrides LLM_MODEL above
if MODEL_FILE.exists():
    saved_model = MODEL_FILE.read_text(encoding="utf-8").strip()
    if saved_model:
        LLM_MODEL = saved_model

# Dashboard (FastAPI)
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8420"))

# MCP servers — comma-separated list of server URLs the user has configured
MCP_SERVERS_FILE = LOCAL_DIR / "mcp_servers.json"

# Plan mode
PLAN_MODE_DEFAULT = os.getenv("PLAN_MODE_DEFAULT", "true").lower() == "true"