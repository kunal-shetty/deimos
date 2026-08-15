"""
MCP server configuration storage.

Servers are stored in ~/.deimos/mcp_servers.json as a list of:
  {"name": "asana", "type": "sse"|"stdio", "url": "...", "command": "...", "args": [...]}

This file only handles config persistence — actual connection/tool-calling
lives in mcp/client.py.
"""

import json
from config import LOCAL_DIR, MCP_SERVERS_FILE


def load_servers() -> list[dict]:
    if not MCP_SERVERS_FILE.exists():
        return []
    try:
        return json.loads(MCP_SERVERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_servers(servers: list[dict]):
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    MCP_SERVERS_FILE.write_text(json.dumps(servers, indent=2), encoding="utf-8")


def add_server(name: str, server_type: str, **kwargs) -> dict:
    """
    Add a new MCP server config.
    server_type: 'sse' (needs url) or 'stdio' (needs command, optional args)
    """
    servers = load_servers()

    # Replace if name already exists
    servers = [s for s in servers if s["name"] != name]

    entry = {"name": name, "type": server_type, **kwargs}
    servers.append(entry)
    save_servers(servers)
    return entry


def remove_server(name: str) -> bool:
    servers = load_servers()
    new_servers = [s for s in servers if s["name"] != name]
    if len(new_servers) == len(servers):
        return False
    save_servers(new_servers)
    return True


def get_server(name: str) -> dict | None:
    for s in load_servers():
        if s["name"] == name:
            return s
    return None