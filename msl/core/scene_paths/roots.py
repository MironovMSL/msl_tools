# core/scene_paths/roots.py
"""Roots: a variable that stands for a folder ("WG_ANIM" = "E:/branches/Animation").

Only a variable whose value is ONE absolute folder can be a root — not a list of folders
(MAYA_SCRIPT_PATH), not a value that names other variables (%X% / $X), not a drive or a share
on its own ("E:/" would swallow every path on the drive). Qt-free, no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_DRIVE = re.compile(r"^[A-Za-z]:/")
_UNC = re.compile(r"^//[^/]+/[^/]+")


@dataclass(frozen=True)
class Root:
    """A variable and the folder it stands for (forward slashes, no slash at the end)."""

    name: str
    value: str

    @property
    def token(self) -> str:
        """How the scene writes it: "$WG_ANIM"."""
        return f"${self.name}"


def normalized(path: str) -> str:
    """Forward slashes, runs of slashes kept only at the start of a share (//server), no slash at the end."""
    text = str(path).strip().replace("\\", "/")
    head = "//" if text.startswith("//") else ""
    body = re.sub(r"/+", "/", text[len(head):]).rstrip("/")
    return head + body


def why_not(name: str, value: str) -> str:
    """Why `name` = `value` can't be a root ("" = it can)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        return "not a name a scene can write as $NAME"
    text = str(value or "").strip()
    if not text:
        return "empty"
    if ";" in text:
        return "a list of folders, not one"
    if "%" in text or "$" in text:
        return "names other variables"
    folder = normalized(text)
    if _DRIVE.match(folder + "/"):
        return "a whole drive — it would take every path on it" if len(folder) <= 3 else ""
    if _UNC.match(folder):
        if folder.count("/") < 4:
            return "a whole share — it would take every path on it"
        return ""
    return "not an absolute folder"


def roots_from(variables: dict) -> list[Root]:
    """The variables of `variables` that can be roots, deepest folder first — so a path under two
    of them is given the more exact one."""
    found = [Root(str(name), normalized(value)) for name, value in variables.items()
             if not why_not(str(name), str(value))]
    return sorted(found, key=lambda root: (-len(root.value), root.name))
