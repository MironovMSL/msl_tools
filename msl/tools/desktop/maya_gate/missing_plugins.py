# tools/desktop/maya_gate/missing_plugins.py
"""Lines of a Maya's log that say a scene asked for a plug-in Maya doesn't have - read so the Sessions tab
can say it ONCE, above the log, with what fixes it, instead of a run of red lines.

    file: E:/.../Rig_Shiba_01.ma line 11: RuntimeError: file <maya console> line 1:
        Plug-in, "evoattrib", was not found on MAYA_PLUG_IN_PATH.

Such a line is no error of the scene: Maya opens it without the plug-in (its nodes, if any, come back as
unknown nodes) - so the tab keeps it in the log as a WARNING and it doesn't count as an unread error.
The file named is the one whose `requires` line asks (a shot's reference: the rig). Arnold's own "The
MtoA plug-in needed for this scene is not loaded" is read too: in a boosted Maya, that is boost having
left Arnold out, and loading it fixes it. Qt-free.
"""
from __future__ import annotations

import re

_MISSING = re.compile(r'Plug-in,\s*"([^"]+)",\s*was not found on MAYA_PLUG_IN_PATH')
_FILE = re.compile(r"file:\s*(.+?\.m[ab])\s+line\s+\d+", re.IGNORECASE)
_ARNOLD = "The MtoA plug-in needed for this scene is not loaded"
ARNOLD = "mtoa"


def missing_plugin(text: str) -> tuple[str, str] | None:
    """(the plug-in, the file that asks for it - "" when the line names none), or None for any other line."""
    match = _MISSING.search(text)
    if match is None:
        return None
    where = _FILE.search(text)
    return match.group(1), (where.group(1).strip() if where else "")


def needs_arnold(text: str) -> bool:
    return _ARNOLD in text


def summary(missing: dict, scene: str = "") -> str:
    """One line for `missing` {plug-in: file}: "5 plug-ins missing, asked for by Rig.ma — not errors" (Maya opens
    the scene without them; the tooltip lists them)."""
    if not missing:
        return ""
    files = sorted({file for file in missing.values() if file}, key=str.lower)
    names = [_base(file) for file in files]
    count = len(missing)
    text = f"{count} plug-in{'s' if count != 1 else ''} missing"
    if names:
        own = [name for file, name in zip(files, names) if scene and _same(file, scene)]
        text += ", asked for by " + ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        if own and len(names) == 1:
            text += " (the open scene)"
    return text + " — not errors"


def files_of(missing: dict, scene: str = "") -> list:
    """The files that ask for the plug-ins, other than the open scene (those are fixed in the file)."""
    return sorted({file for file in missing.values() if file and not (scene and _same(file, scene))}, key=str.lower)


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _same(one: str, other: str) -> bool:
    return one.replace("\\", "/").lower() == other.replace("\\", "/").lower()
