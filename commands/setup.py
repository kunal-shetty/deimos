"""
`deimos setup`: ask for API keys and save them to ~/.deimos/.env.

Only the Groq key is required. Press enter to keep a value that's already
saved. Secrets are typed without echo and the file is readable only by
the current user on macOS/Linux.
"""

import os
from getpass import getpass

import requests
from dotenv import dotenv_values, set_key

from config import ENV_FILE

# (variable, prompt, required, secret)
FIELDS = [
    ("GROQ_API_KEY", "Groq API key (required, from https://console.groq.com/keys)", True, True),
    ("TAVILY_API_KEY", "Tavily API key for web search (optional)", False, True),
    ("TYPESAFE_API_KEY", "TypeSafe API key for Jev decisions (optional)", False, True),
    ("SUPABASE_URL", "Supabase project URL for long-term memory (optional)", False, False),
    ("SUPABASE_KEY", "Supabase anon key", False, True),
    ("DEIMOS_USER_ID", "Your user id (uuid of your row in the Supabase `users` table)", False, False),
]
MEMORY_FIELDS = ("SUPABASE_KEY", "DEIMOS_USER_ID")  # only asked when a Supabase URL is given


def run_setup(env_file=ENV_FILE) -> bool:
    """Interactive key entry. Returns True when a Groq key ends up saved."""
    existing = dotenv_values(env_file) if env_file.exists() else {}
    print(f"Deimos setup: keys are saved to {env_file}")
    print("Press enter to keep the current value or skip an optional one.\n")

    values = {}
    try:
        for key, label, required, secret in FIELDS:
            if key in MEMORY_FIELDS and not values.get("SUPABASE_URL"):
                continue
            current = existing.get(key) or os.environ.get(key) or ""
            while True:
                value = _ask(label, current, secret)
                if key == "GROQ_API_KEY" and value and value != current and not _groq_key_works(value):
                    print("  That key was rejected by Groq. Check it and try again.")
                    continue
                if value or not required:
                    break
                print("  This one is required.")
            if value:
                values[key] = value
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled; nothing was changed.")
        return False

    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.touch(exist_ok=True)
    if os.name != "nt":
        os.chmod(env_file, 0o600)
    for key, value in values.items():
        if value != existing.get(key):
            set_key(str(env_file), key, value, quote_mode="never")

    print(f"\nSaved to {env_file}.")
    if not values.get("SUPABASE_URL"):
        print("Long-term memory stays off until you add Supabase details (run `deimos setup` again).")
    return bool(values.get("GROQ_API_KEY"))


def _ask(label: str, current: str, secret: bool) -> str:
    if current:
        shown = f"{current[:4]}…{current[-4:]}" if secret and len(current) > 12 else ("set" if secret else current)
        label = f"{label} [{shown}]"
    from ui.terminal import stdin_is_terminal
    reader = getpass if secret and stdin_is_terminal() else input
    return reader(f"{label}: ").strip() or current


def _groq_key_works(key: str) -> bool:
    try:
        r = requests.get("https://api.groq.com/openai/v1/models",
                         headers={"Authorization": f"Bearer {key}"}, timeout=10)
    except requests.RequestException:
        return True  # can't check offline; don't block setup on it
    return r.status_code != 401
