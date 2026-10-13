"""Entry point of the MCP server that lets a coding assistant see the Mayas
connected to MSL Tools: which are running, and what their Script Editors report.

Started by the assistant itself (see .mcp.json at the root), BY PATH:
`python <root>/msl/run_maya_mcp.py`. It talks MCP on stdin / stdout
(core/link/mcp_stdio.py) and asks the running hub over its assistant channel
(core/link/assistant.py) — it never talks to Maya, imports no Qt, and reads
the hub's config file without writing it.

The hub must be running with the assistant access switched on; until then
every tool answers with what to do about it.
"""
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # <root>/msl/run_maya_mcp.py -> <root>


def _make_package_importable() -> None:
    """`import msl_tools.msl...` from this checkout / install, whatever its folder is called
    (msl_tools is a namespace package: a module whose __path__ is the folder is enough)."""
    if ROOT.name == "msl_tools":
        if str(ROOT.parent) not in sys.path:
            sys.path.insert(0, str(ROOT.parent))
        return
    package = types.ModuleType("msl_tools")
    package.__path__ = [str(ROOT)]
    sys.modules["msl_tools"] = package


_make_package_importable()

from msl_tools.msl import __version__  # noqa: E402
from msl_tools.msl.core.link import assistant  # noqa: E402
from msl_tools.msl.core.link.mcp_stdio import StdioServer, Tool  # noqa: E402

CONFIG_FILE = ROOT / "configs" / "desktop" / assistant.CONFIG_NAME / "config.json"

INSTRUCTIONS = ("Tools for the Autodesk Maya sessions connected to the MSL Tools hub on this machine. "
                "Call maya_sessions first: it lists the running Mayas with their pid. maya_log reads what "
                "a Maya's Script Editor reported (errors and warnings; plain prints only while the hub's "
                "log switch is on All).")


class MayaTools:
    """The tools, as methods. One client for the life of the process; the address is read
    again whenever there is no connection (the hub may have been switched on since)."""

    def __init__(self, config_file=CONFIG_FILE):
        self._config_file = config_file
        self._client = None

    def _ask(self, name: str, **data) -> dict:
        if self._client is None:
            port, token, enabled = assistant.read_address(self._config_file)
            if not port or not token or not enabled:
                raise assistant.AssistantError(
                    "The assistant access of MSL Tools is switched off (or the hub never ran here). "
                    "Start MSL Tools and switch it on: Maya Gate > Sessions.")
            self._client = assistant.AssistantClient(port, token)
        try:
            return self._client.request(name, **data)
        except assistant.AssistantError:
            self._client.close()
            self._client = None   # the next call reads the address again
            raise

    def _only_pid(self) -> int:
        sessions = self._ask(assistant.SESSIONS)["sessions"]
        if len(sessions) == 1:
            return int(sessions[0]["pid"])
        if not sessions:
            raise assistant.AssistantError("No Maya is connected to MSL Tools.")
        raise assistant.AssistantError("Several Mayas are connected - say which one with `pid`:\n"
                                       + "\n".join(_session_line(session) for session in sessions))

    def sessions(self) -> str:
        sessions = self._ask(assistant.SESSIONS)["sessions"]
        if not sessions:
            return "No Maya is connected to MSL Tools."
        return "\n".join(_session_line(session) for session in sessions)

    def log(self, pid: int = 0, after: int = 0, limit: int = 100, problems_only: bool = False) -> str:
        pid = int(pid) or self._only_pid()
        levels = ["error", "warning"] if problems_only else None
        answer = self._ask(assistant.READ_LOG, pid=pid, after=int(after), limit=int(limit), levels=levels)
        if not answer.get("known"):
            raise assistant.AssistantError("MSL Tools knows no Maya with pid %d." % pid)
        entries = answer.get("entries") or []
        lines = ["%s  %-7s  %s" % (time.strftime("%H:%M:%S", time.localtime(entry["time"])),
                                   entry["level"], entry["text"]) for entry in entries]
        lines.append("[pid %d: %d entries; last=%d - pass it as `after` to read only what comes next]"
                     % (pid, len(entries), answer.get("last", 0)))
        return "\n".join(lines)


def _session_line(session: dict) -> str:
    minutes = int(session.get("connected_seconds", 0)) // 60
    marks = [mark for mark, on in (("unsaved changes", session.get("modified")), ("BUSY", session.get("busy")),
                                   ("boost", session.get("boosted")), ("console", session.get("console"))) if on]
    return "pid %s  Maya %s  %s  scene: %s  connected %d min  errors %d, warnings %d%s" % (
        session.get("pid"), session.get("version"), session.get("environment") or "(no environment)",
        session.get("scene") or "untitled", minutes, session.get("errors", 0), session.get("warnings", 0),
        "  [%s]" % ", ".join(marks) if marks else "")


def build_server(tools: MayaTools) -> StdioServer:
    return StdioServer("msl-maya", __version__, instructions=INSTRUCTIONS, tools=[
        Tool("maya_sessions",
             "List the Maya sessions connected to the MSL Tools hub: pid, Maya version, environment, open "
             "scene, unsaved changes, busy, and how many errors / warnings each has reported.",
             tools.sessions),
        Tool("maya_log",
             "Read what a Maya's Script Editor reported to MSL Tools: errors, warnings, tracebacks (and "
             "plain output while the hub's log switch is on All), oldest first. Returns the newest `limit` "
             "entries after `after`, and the `last` sequence number to pass as `after` next time.",
             tools.log,
             properties={
                 "pid": {"type": "integer", "description": "The Maya's process id (from maya_sessions). "
                                                           "May be left out while exactly one Maya is connected."},
                 "after": {"type": "integer", "description": "Only entries newer than this sequence number "
                                                             "(the `last` of an earlier call). Default 0: all kept."},
                 "limit": {"type": "integer", "description": "At most this many entries, the newest "
                                                             "(default 100, at most %d)." % assistant.MAX_READ},
                 "problems_only": {"type": "boolean", "description": "Only errors and warnings."}}),
    ])


def main() -> None:
    build_server(MayaTools()).serve()


if __name__ == "__main__":
    main()
