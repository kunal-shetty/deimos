import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
ROOT_DIR = Path(__file__).parent
WORKSPACE_DIR = ROOT_DIR / "workspace"
PROMPTS_DIR = ROOT_DIR / "prompts"

# LLM
LLM_API_KEY = os.getenv("GROQ_API_KEY")
LLM_PROVIDER = "groq"
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

# Agent
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "30"))
