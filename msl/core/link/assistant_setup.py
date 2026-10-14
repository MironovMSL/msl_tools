# core/link/assistant_setup.py
"""How a coding assistant is told about our MCP server (msl/run_maya_mcp.py) -
Qt-free. A checkout carries `.mcp.json`; an INSTALLED copy has none (install
copies `msl/` only), so the hub hands out what an assistant needs instead:

    claude_command()          the one line to type for Claude Code (user scope:
                              every project on this computer sees the server)
    config_text()             the JSON block other assistants' MCP settings take
    write_project_config()    `.mcp.json` written into (merged into) a folder

All of them name this install's own Python and script by full path, so they
keep working whatever folder the assistant runs in.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from msl_tools.msl.core.fs.safe_json import read_json_object, write_json_atomic

SERVER_NAME = "msl-maya"
PROJECT_FILE = ".mcp.json"


def console_python(executable: str | None = None) -> str:
    """The console Python next to the one running (the hub runs under pythonw.exe, which
    has no stdin / stdout - an MCP server talks through them)."""
    running = Path(executable or sys.executable)
    console = running.with_name("python.exe") if running.name.lower() == "pythonw.exe" else running
    return str(console if console.exists() else running)


def server_script() -> str:
    """This install's msl/run_maya_mcp.py."""
    return str(Path(__file__).resolve().parents[2] / "run_maya_mcp.py")


def server_entry(python: str | None = None, script: str | None = None) -> dict:
    """The server as MCP settings write it: {"command": python, "args": [script]}."""
    return {"command": python or console_python(), "args": [script or server_script()]}


def claude_command(entry: dict | None = None) -> str:
    """The line that adds the server to Claude Code for this user, in every project."""
    entry = entry or server_entry()
    return 'claude mcp add --scope user %s -- %s' % (
        SERVER_NAME, " ".join('"%s"' % part for part in [entry["command"], *entry["args"]]))


def config_text(entry: dict | None = None) -> str:
    """{"mcpServers": {"msl-maya": ...}} as text - what most assistants' MCP settings take."""
    return json.dumps({"mcpServers": {SERVER_NAME: entry or server_entry()}}, indent=2)


def write_project_config(folder, entry: dict | None = None) -> Path:
    """Puts the server into `<folder>/.mcp.json` - the other servers already there stay.

    Raises:
        OSError (incl. safe_json.JsonUnavailable): the file can't be read or written; a
            file that exists but can't be read is never written over.
    """
    path = Path(folder) / PROJECT_FILE
    data = read_json_object(path) if path.exists() else {}
    servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
    servers[SERVER_NAME] = entry or server_entry()
    data["mcpServers"] = servers
    write_json_atomic(path, data, indent=2)
    return path
