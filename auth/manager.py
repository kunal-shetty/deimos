import os
import json
import webbrowser
from pathlib import Path
from typing import Optional
import requests
from config import SUPABASE_URL, SUPABASE_KEY

class AuthManager:
    """Handles OAuth2 flow, token persistence, and session lifecycle."""

    SESSION_FILE = Path.home() / ".deimos" / "session.json"

    def __init__(self):
        self.current_session: Optional[dict] = self._load_session()

    def _load_session(self) -> Optional[dict]:
        if self.SESSION_FILE.exists():
            try:
                return json.loads(self.SESSION_FILE.read_text())
            except Exception:
                return None
        return None

    def save_session(self, session_data: dict):
        self.SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.SESSION_FILE.write_text(json.dumps(session_data, indent=2))
        self.current_session = session_data

    def logout(self):
        if self.SESSION_FILE.exists():
            self.SESSION_FILE.unlink()
        self.current_session = None

    def get_access_token(self) -> Optional[str]:
        if not self.current_session:
            return None
        return self.current_session.get("access_token")

    def get_user_id(self) -> Optional[str]:
        if not self.current_session:
            return None
        return self.current_session.get("user_id")

    def is_authenticated(self) -> bool:
        return self.current_session is not None and self.get_access_token() is not None

    def initiate_login(self):
        """Open browser to Supabase auth page."""
        # In a real implementation, this URL would be constructed using
        # Supabase's auth.signInWithOAuth() or a direct link to the provider.
        # For now, we define the redirect target.
        auth_url = f"{SUPABASE_URL}/auth/v1/authorize?provider=google&redirect_to=http://localhost:8080/callback"
        webbrowser.open(auth_url)
        return auth_url
