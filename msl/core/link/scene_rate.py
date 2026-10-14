# core/link/scene_rate.py
"""Frame rates as Maya names them, and the rate a scene FILE was saved at -
Qt-free, shared by the hub (Maya Gate's Scene tab) and Maya
(tools/maya/scene_defaults.py), so: standard library only, Python 3.9-valid.

Maya keeps a scene's rate as a time unit name ("film" = 24 fps); a .ma file
says it near its top: `currentUnit -l centimeter -a degree -t ntsc;`.
"""
from __future__ import annotations

import re

# The rates offered, as frames per second -> Maya's time unit.
UNITS = {"24": "film", "25": "pal", "30": "ntsc", "48": "show", "50": "palf", "60": "ntscf"}
RATES = {unit: fps for fps, unit in UNITS.items()}

HEADER_BYTES = 256 * 1024   # a .ma file's currentUnit line comes long before this
_MA_UNIT = re.compile(rb"currentUnit\b[^;]*?-t\s+\"?([\w.]+)")


def unit_for(fps: str) -> str:
    """Maya's time unit of `fps` ("30" -> "ntsc"); "" for a rate not offered."""
    return UNITS.get(str(fps).strip(), "")


def describe(unit: str) -> str:
    """A time unit for people: "film" -> "24 fps"; one Maya names by its rate ("23.976fps") as it is."""
    if unit in RATES:
        return "%s fps" % RATES[unit]
    return unit.replace("fps", " fps") if unit.endswith("fps") else unit


def file_unit(path: str) -> str:
    """The time unit a .ma scene was saved with ("" for a .mb, an unreadable file, or none found).
    Only the file's head is read."""
    if not str(path).lower().endswith(".ma"):
        return ""
    try:
        with open(path, "rb") as handle:
            head = handle.read(HEADER_BYTES)
    except (OSError, ValueError):
        return ""
    found = _MA_UNIT.search(head)
    return found.group(1).decode("ascii", "replace") if found else ""
