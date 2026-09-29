import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import os
import sys
from auth.manager import AuthManager

app = FastAPI()
auth_manager = AuthManager()

@app.get("/callback")
async def callback(code: str = None, error: str = None):
    if error:
        return HTMLResponse(content=f"<h1>Authentication Error</h1><p>{error}</p>", status_code=400)

    if not code:
        return HTMLResponse(content="<h1>Error</h1><p>No authorization code provided.</p>", status_code=400)

    # In a real flow, we would exchange this code for tokens via Supabase
    # For implementation purposes, we simulate the exchange here
    # and save the session.

    # Mock data for demonstration of the flow
    mock_session = {
        "user_id": "auth-mock-id-123",
        "access_token": "mock-jwt-access-token",
        "refresh_token": "mock-refresh-token",
        "email": "user@example.com"
    }

    auth_manager.save_session(mock_session)

    return HTMLResponse(content="<h1>Login Successful!</h1><p>You can now close this window and return to Deimos.</p>")

def start_callback_server():
    """Runs the server in a temporary blocking mode."""
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="error")
