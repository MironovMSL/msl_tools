# core/link/assistant_guard.py
"""What stands between an assistant and a Maya, besides the hub's switches -
Qt-free: a look at the code it wants to run (does it save, open, close, delete?),
and a journal of what it did.

`risks(code)` reads the code as Python (ast), never runs it. It is a guard
against a MISTAKE - an assistant saving over a file while it only meant to
look - not a wall: code written to hide what it does gets through. What it
finds is put to the user by the hub before anything is sent to Maya.
"""
from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path

# cmds.file(...) flags that change what is on disk or which scene is open (long and short names).
_FILE_FLAGS = {
    "save": "saves the scene", "s": "saves the scene",
    "rename": "gives the scene another file name", "rn": "gives the scene another file name",
    "newFile": "starts a new scene (the open one goes)", "new": "starts a new scene (the open one goes)",
    "open": "opens another scene (the open one goes)", "o": "opens another scene (the open one goes)",
    "exportAll": "writes a scene file", "ea": "writes a scene file",
    "exportSelected": "writes a scene file", "es": "writes a scene file",
    "exportAnim": "writes a file", "exportSelectedAnim": "writes a file",
    "removeReference": "removes a reference", "rr": "removes a reference",
    "unloadReference": "unloads a reference", "ur": "unloads a reference",
}
_FILE_QUERY = ("query", "q")
# A call of this name, whatever it is called on.
_CALLS = {
    "quit": "closes Maya",
    "saveFile": "saves the scene", "saveAs": "saves the scene", "newFile": "starts a new scene (the open one goes)",
    "openFile": "opens another scene (the open one goes)", "exportAll": "writes a scene file",
    "exportSelected": "writes a scene file", "sysFile": "moves or deletes files",
    "remove": None, "unlink": "deletes a file", "rmdir": "deletes a folder", "removedirs": "deletes folders",
    "rmtree": "deletes a folder with everything in it",
    "system": None, "popen": None, "Popen": "starts another program", "startfile": "starts another program",
}
# ... only when called on one of these modules (os.remove yes, a list's .remove no).
_ON_MODULE = {"remove": ("os", "deletes a file"), "system": ("os", "starts another program"),
              "popen": ("os", "starts another program")}
_SUBPROCESS = ("run", "call", "check_call", "check_output")
_HIDDEN = {"exec": "runs code the hub cannot read", "eval": "runs code the hub cannot read",
           "__import__": "loads a module by a name the hub cannot read"}
_MEL = re.compile(r"\bfile\b[^;]*\s-(s|save|new|newFile|o|open|rn|rename|ea|es|exportAll|exportSelected)\b"
                  r"|\b(quit|sysFile|NewScene|SaveScene|SaveSceneAs|OpenScene)\b")
_MEL_SAYS = "runs MEL that saves, opens or closes"


def _name(node) -> str:
    """`a.b.c` of a call's function ("" for anything else)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif parts:
        parts.append("?")   # called on something that is no plain name: Path(folder).unlink()
    return ".".join(reversed(parts))


def _on(keyword: ast.keyword) -> bool:
    """A keyword argument that isn't plainly switched off (`save=False`)."""
    return not (isinstance(keyword.value, ast.Constant) and keyword.value.value in (False, None, 0))


def risks(code: str) -> list[str]:
    """What `code` would do that deserves a question first, in plain words - [] for
    nothing (also for code that isn't valid Python: Maya will refuse that itself)."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return []
    found: list[str] = []

    def note(text: str) -> None:
        if text and text not in found:
            found.append(text)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        last = name.rsplit(".", 1)[-1] if name else ""
        base = name.rsplit(".", 1)[0] if "." in name else ""
        if last == "file" and base:   # cmds.file(...), mc.file(...), pm.file(...)
            flags = {keyword.arg: keyword for keyword in node.keywords if keyword.arg}
            if not any(key in flags and _on(flags[key]) for key in _FILE_QUERY):
                for flag, text in _FILE_FLAGS.items():
                    if flag in flags and _on(flags[flag]):
                        note(text)
        elif last in _ON_MODULE:
            module, text = _ON_MODULE[last]
            if base.rsplit(".", 1)[-1] == module:
                note(text)
        elif last in _SUBPROCESS and base.rsplit(".", 1)[-1] == "subprocess":
            note("starts another program")
        elif last in _CALLS and _CALLS[last] and (base or last in ("quit",)):
            note(_CALLS[last])
        elif name in _HIDDEN:
            note(_HIDDEN[name])
        elif last == "eval" and base.rsplit(".", 1)[-1] == "mel":   # mel.eval("file -save")
            text = node.args[0] if node.args else None
            if isinstance(text, ast.Constant) and isinstance(text.value, str):
                if _MEL.search(text.value):
                    note(_MEL_SAYS)
            else:
                note("runs MEL the hub cannot read")
    return found


class Journal:
    """What the assistant did, appended to a text file a day - so it can be read after the
    hub was closed. Never raises: a journal that can't be written must not stop the work."""

    KEPT_DAYS = 60
    BODY_LINES = 400     # of one entry's code / outcome

    def __init__(self, folder: str | os.PathLike):
        self.folder = Path(folder)
        self._swept = False

    def file_for(self, moment: float | None = None) -> Path:
        return self.folder / (time.strftime("%Y-%m-%d", time.localtime(moment)) + ".log")

    def record(self, what: str, where: str = "", body: str = "", outcome: str = "", moment: float | None = None) -> None:
        """Appends one entry: `what` happened (one line), `where` (the Maya), the code or
        details, and how it ended."""
        moment = time.time() if moment is None else moment
        lines = ["", "=== %s  %s%s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(moment)), what,
                                       "  |  " + where if where else "")]
        for title, text in (("", body), ("--- outcome", outcome)):
            text = str(text or "").rstrip("\n")
            if not text:
                continue
            if title:
                lines.append(title)
            rows = text.split("\n")
            lines += rows[:self.BODY_LINES]
            if len(rows) > self.BODY_LINES:
                lines.append("... %d more lines" % (len(rows) - self.BODY_LINES))
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self.file_for(moment), "a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(lines) + "\n")
            self._sweep(moment)
        except OSError:
            pass

    def _sweep(self, moment: float) -> None:
        """Once per run: files older than KEPT_DAYS go."""
        if self._swept:
            return
        self._swept = True
        for path in self.folder.glob("*.log"):
            try:
                if moment - path.stat().st_mtime > self.KEPT_DAYS * 86400:
                    path.unlink()
            except OSError:
                pass
