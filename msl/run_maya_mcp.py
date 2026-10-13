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
import tempfile
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
from msl_tools.msl.core.link.mcp_stdio import Picture, StdioServer, Tool  # noqa: E402

CONFIG_FILE = ROOT / "configs" / "desktop" / assistant.CONFIG_NAME / "config.json"

INSTRUCTIONS = ("Tools for the Autodesk Maya sessions connected to the MSL Tools hub on this machine. "
                "Call maya_sessions first: it lists the running Mayas with their pid. maya_log reads what "
                "a Maya's Script Editor reported (errors and warnings; plain prints only while the hub's "
                "log switch is on All). maya_run_python runs Python in a Maya the user allowed it for - "
                "it is their live scene: do not change or save it unless they asked.")


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
                    "Start MSL Tools and switch it on: the robot's head in the window's header.")
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


    def run_python(self, code: str = "", pid: int = 0, timeout: int = assistant.RUN_SECONDS_DEFAULT) -> str:
        if not str(code).strip():
            raise assistant.AssistantError("No code was given.")
        sessions = self._ask(assistant.SESSIONS)["sessions"]   # also: the connection is fresh for the one send
        pid = int(pid) or self._only_pid()
        session = next((entry for entry in sessions if entry.get("pid") == pid), None)
        if session is None:
            raise assistant.AssistantError("No Maya with pid %d is connected to MSL Tools." % pid)
        least, most = assistant.RUN_SECONDS
        seconds = min(max(int(timeout), least), most)
        # Sent ONCE: a request repeated after a broken line could run the code twice.
        answer = self._ask(assistant.RUN_PYTHON, wait=seconds + 10, again=False, pid=pid, code=str(code),
                           seconds=seconds)
        output = str(answer.get("output") or "").rstrip("\n")
        if answer.get("traceback"):
            raise assistant.AssistantError("\n".join(part for part in (output, str(answer["traceback"]).rstrip("\n"))
                                                     if part))
        parts = [part for part in (output, "# Result: %s" % answer["result"] if answer.get("result") else "") if part]
        return "\n".join(parts) or "(ran; no output, no result)"


    def launch_report(self, pid: int = 0) -> str:
        pid = int(pid) or self._only_pid()
        return str(self._ask(assistant.LAUNCH_REPORT, wait=25, pid=pid).get("text") or "(Maya sent an empty report)")

    def reload_code(self, pid: int = 0) -> str:
        pid = int(pid) or self._only_pid()
        answer = self._ask(assistant.RELOAD_CODE, wait=30, again=False, pid=pid)
        return ("Reloaded: %s msl_tools modules were dropped in Maya %d; they are imported fresh on next use. "
                "Its link to MSL Tools restarts - the session is back in a moment; windows of msl_tools that "
                "were open still run the old code until reopened." % (answer.get("modules", "?"), pid))

    def viewport_image(self, pid: int = 0, width: int = 960) -> Picture:
        pid = int(pid) or self._only_pid()
        width = min(max(int(width), 160), 1920)
        target = self._picture_file("viewport_%d" % pid)
        output = self.run_python(code=VIEWPORT_CODE % {"path": str(target), "width": width}, pid=pid, timeout=60)
        if not target.is_file():
            raise assistant.AssistantError("Maya made no picture: %s" % output)
        return Picture(str(target), "%s\nSaved as %s" % (output.split("\n# Result")[0], target))


    def _picture_file(self, name: str) -> Path:
        """Where a new picture goes: %TEMP%/msl_tools/assistant, the oldest ones of its kind swept."""
        folder = Path(tempfile.gettempdir()) / "msl_tools" / "assistant"
        folder.mkdir(parents=True, exist_ok=True)
        kind = name.split("_")[0]
        for old in sorted(folder.glob(kind + "_*.png"), key=lambda path: path.stat().st_mtime)[:-VIEWPORT_KEPT]:
            try:
                old.unlink()
            except OSError:
                pass
        return folder / ("%s_%s.png" % (name, time.strftime("%H%M%S")))

    def window_image(self, pid: int = 0, window: str = "") -> "Picture | str":
        pid = int(pid) or self._only_pid()
        target = self._picture_file("window_%d" % pid)
        output = self.run_python(code=WINDOW_CODE % {"path": str(target), "wanted": str(window)}, pid=pid, timeout=60)
        text = output.split("\n# Result")[0]
        if not target.is_file():
            return text   # the list of windows (none named, none or several matched)
        return Picture(str(target), "%s\nSaved as %s" % (text, target))

    def hub_screenshot(self, tool: str = "") -> Picture:
        answer = self._ask(assistant.HUB_SCREENSHOT, wait=20, tool=str(tool))
        return Picture(str(answer["path"]), "MSL Tools hub, tool “%s”, %sx%s\nSaved as %s" % (
            answer.get("tool"), answer.get("width"), answer.get("height"), answer["path"]))

    def hub_info(self) -> str:
        answer = self._ask(assistant.HUB_INFO)
        return ("Maya versions installed: %s\nEnvironments: %s\nHub tools: %s" % tuple(
            ", ".join(answer.get(key) or []) or "none" for key in ("versions", "environments", "tools")))

    def launch(self, version: str = "", environment: str = "Dev", scene: str = "", wait: int = 180) -> str:
        before = {entry.get("pid") for entry in self._ask(assistant.SESSIONS)["sessions"]}
        self._ask(assistant.LAUNCH_MAYA, again=False, version=str(version), environment=str(environment),
                  scene=str(scene))
        deadline = time.time() + min(max(int(wait), 0), 600)
        while time.time() < deadline:   # it joins the hub once it is up (about half a minute)
            time.sleep(2.0)
            new = [entry for entry in self._ask(assistant.SESSIONS)["sessions"] if entry.get("pid") not in before]
            if new:
                return "Started and connected:\n" + "\n".join(_session_line(entry) for entry in new)
        return ("Maya %s was started in “%s” but has not connected to MSL Tools yet - "
                "call maya_sessions in a while." % (version, environment))

    def close(self, pid: int = 0) -> str:
        if not int(pid):
            raise assistant.AssistantError("Say which Maya to close with `pid` (from maya_sessions).")
        self._ask(assistant.CLOSE_MAYA, wait=25, again=False, pid=int(pid))
        return "Maya %d is closing." % int(pid)


VIEWPORT_KEPT = 20   # pictures of a kind left in %TEMP%/msl_tools/assistant
# Runs in Maya: a picture of one of its windows as it is on screen - an msl_tools window (Rename,
# Controls, Playblast ...) or any other. `wanted` is looked for in each visible window's title,
# class and object name; with none, several or no match it only lists the windows.
WINDOW_CODE = '''
def _msl_window(path, wanted):
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets
    windows = [w for w in QtWidgets.QApplication.instance().allWidgets()
               if w.isWindow() and w.isVisible() and w.width() > 40 and w.height() > 40
               and not isinstance(w, QtWidgets.QMenu)]
    def name(w):
        return "%%s  [%%s%%s]  %%dx%%d" %% (w.windowTitle() or "(no title)", type(w).__name__,
                                         " #" + w.objectName() if w.objectName() else "", w.width(), w.height())
    key = wanted.strip().lower()
    found = [w for w in windows if key and key in (w.windowTitle() + " " + type(w).__name__ + " " + w.objectName()).lower()]
    if len(found) != 1:
        print("No window was named." if not key else "%%d windows match %%r." %% (len(found), wanted))
        print("Visible windows:")
        for w in (found or windows):
            print("  " + name(w))
        return
    window = found[0]
    shot = window.grab()
    image = QtGui.QImage(shot.size(), QtGui.QImage.Format_RGB888)
    image.fill(QtGui.QColor(58, 58, 58))   # a rounded window's see-through corners, on Maya's grey
    painter = QtGui.QPainter(image)
    painter.drawPixmap(0, 0, shot)
    painter.end()
    image.save(path, "PNG")
    print("Window " + name(window))
_msl_window(%(path)r, %(wanted)r)
del _msl_window
'''
# Runs in Maya: one frame of a model panel as it is (the one with the focus, else the first on
# screen) into a PNG. A playblast of ONE frame at the current time - nothing in the scene is
# changed, and its "modified" mark is put back in case Maya set it.
VIEWPORT_CODE = '''
import maya.cmds as cmds
def _msl_viewport(path, width):
    panels = [p for p in [cmds.getPanel(withFocus=True)] + (cmds.getPanel(visiblePanels=True) or [])
              if p and cmds.getPanel(typeOf=p) == "modelPanel"]
    if not panels:
        raise RuntimeError("no 3D viewport is on screen in this Maya")
    panel = panels[0]
    ratio = float(cmds.control(panel, query=True, height=True)) / max(cmds.control(panel, query=True, width=True), 1)
    height = max(int(width * ratio) // 2 * 2, 2)
    modified = cmds.file(query=True, modified=True)
    try:
        cmds.playblast(frame=[cmds.currentTime(query=True)], format="image", compression="png",
                       completeFilename=path, editorPanelName=panel, widthHeight=[width, height], percent=100,
                       viewer=False, showOrnaments=True, offScreen=True, forceOverwrite=True, quality=100)
    finally:
        cmds.file(modified=modified)
    try:   # a playblast PNG has alpha 0 everywhere (it shows as white): keep the colors, drop the alpha
        try:
            from PySide6 import QtGui
        except ImportError:
            from PySide2 import QtGui
        image = QtGui.QImage(path)
        if not image.isNull():
            image.convertToFormat(QtGui.QImage.Format_RGB888).save(path, "PNG")
    except Exception:
        pass
    camera = cmds.modelPanel(panel, query=True, camera=True)
    print("Viewport %%s, camera %%s, frame %%s, %%dx%%d" %% (panel, camera, cmds.currentTime(query=True), width, height))
_msl_viewport(%(path)r, %(width)d)
del _msl_viewport
'''


def _session_line(session: dict) -> str:
    minutes = int(session.get("connected_seconds", 0)) // 60
    marks = [mark for mark, on in (("unsaved changes", session.get("modified")), ("BUSY", session.get("busy")),
                                   ("boost", session.get("boosted")),
                                   ("runs code", session.get("runs_code"))) if on]
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
        Tool("maya_run_python",
             "Run Python in a connected Maya, in its main thread, as its Script Editor would: names persist "
             "in __main__, the value of a final expression is the result, one undo step. Returns what the "
             "code printed and its result; a traceback comes back as the tool's error. The code and its "
             "outcome are shown to the user in MSL Tools and in Maya's Script Editor. It runs in the user's "
             "LIVE scene: read freely, but change the scene only when the user asked for it. Works only in "
             "sessions marked [runs code] by maya_sessions (the user allows it in MSL Tools).",
             tools.run_python,
             properties={
                 "code": {"type": "string", "description": "The Python to run (maya.cmds etc. are importable)."},
                 "pid": {"type": "integer", "description": "The Maya's process id (from maya_sessions). "
                                                           "May be left out while exactly one Maya is connected."},
                 "timeout": {"type": "integer", "description": "Seconds to wait for Maya (default %d, %d to %d). "
                                                               "Maya is blocked while the code runs."
                                                               % ((assistant.RUN_SECONDS_DEFAULT,)
                                                                  + assistant.RUN_SECONDS)}},
             required=("code",)),
        Tool("maya_viewport_image",
             "Look at a Maya's 3D viewport: returns a picture of it as it is now (the panel with the focus, "
             "else the first on screen), with its camera and frame. Nothing in the scene changes. Use it to "
             "SEE the result of what was done instead of guessing. Needs a session marked [runs code].",
             tools.viewport_image,
             properties={
                 "pid": {"type": "integer", "description": "The Maya's process id; may be left out while "
                                                           "exactly one Maya is connected."},
                 "width": {"type": "integer", "description": "Picture width in pixels (default 960, 160 to 1920)."}}),
        Tool("maya_window_image",
             "Look at a WINDOW inside a Maya - an msl_tools tool (Rename, Controls, Playblast ...) or any "
             "other - as it is on screen: its real theme, font and layout. Give part of its title or class "
             "name in `window`; without it (or when several match) it lists the visible windows instead. "
             "The window must already be open. Needs a session marked [runs code].",
             tools.window_image,
             properties={
                 "pid": {"type": "integer", "description": "The Maya's process id; may be left out while "
                                                           "exactly one Maya is connected."},
                 "window": {"type": "string", "description": "Part of the window's title, class or object "
                                                             "name (case does not matter), e.g. \"controls\"."}}),
        Tool("hub_screenshot",
             "Look at the MSL Tools hub's own window as it is on screen (real theme, font, layout). `tool` "
             "opens that tool's page first, as a click on its sidebar tile would (ids from hub_info, e.g. "
             "maya_gate, media, batch); without it the page that is open is shown. Read-only otherwise.",
             tools.hub_screenshot,
             properties={"tool": {"type": "string", "description": "Id of the hub tool to open first; "
                                                                   "leave out for the page open now."}}),
        Tool("hub_info",
             "What can be asked of the hub: the Maya versions installed here, the Maya Gate environments, "
             "and the ids of the hub's tools.",
             tools.hub_info),
        Tool("maya_launch",
             "Start a Maya from the hub, as a click on its version tile would: that environment's "
             "variables, userSetup and boost. Waits until it has connected (about half a minute) and "
             "returns its session line with the pid. Needs the user to have allowed the assistant to act "
             "(the hub's switch). Start one only when the user asked for it or the task needs its own Maya.",
             tools.launch,
             properties={
                 "version": {"type": "string", "description": "Maya's year, e.g. \"2026\" (see hub_info)."},
                 "environment": {"type": "string", "description": "A Maya Gate environment (see hub_info). "
                                                                  "Default \"Dev\"."},
                 "scene": {"type": "string", "description": "Full path of a .ma / .mb scene to open; "
                                                            "leave out for an empty scene."},
                 "wait": {"type": "integer", "description": "Seconds to wait for it to connect "
                                                            "(default 180, 0 = don't wait)."}},
             required=("version",)),
        Tool("maya_close",
             "Close a connected Maya. Maya refuses while its scene has unsaved changes - nothing is ever "
             "discarded this way. Close only a Maya you started, or one the user asked you to close.",
             tools.close,
             properties={"pid": {"type": "integer", "description": "The Maya's process id (from maya_sessions)."}},
             required=("pid",)),
        Tool("maya_launch_report",
             "A Maya's launch report (read-only): its environment, preference folders, the variables MSL "
             "Tools set, userSetup files, boost (plug-ins loaded / skipped / failed), loaded plug-ins and "
             "modules. For questions like 'why is this plug-in not loaded' or 'which paths does Maya see'.",
             tools.launch_report,
             properties={"pid": {"type": "integer", "description": "The Maya's process id; may be left out "
                                                                   "while exactly one Maya is connected."}}),
        Tool("maya_reload_code",
             "Make a Maya drop its msl_tools modules so the next use imports the code as it is on disk now - "
             "after editing msl_tools' Maya-side code. Its session leaves and rejoins within a moment; "
             "msl_tools windows already open keep the old code until reopened. Needs [runs code].",
             tools.reload_code,
             properties={"pid": {"type": "integer", "description": "The Maya's process id; may be left out "
                                                                   "while exactly one Maya is connected."}}),
    ])


def main() -> None:
    build_server(MayaTools()).serve()


if __name__ == "__main__":
    main()
