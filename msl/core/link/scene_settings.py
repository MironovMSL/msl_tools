# core/link/scene_settings.py
"""The rest of what Maya Gate's Scene tab sets for an environment (beside the frame rate, which is
scene_rate.py's): the playback range and units of new scenes, the up axis, playback speed, the
tangents of new keys, auto key. Shared by the hub (the tab, the launch) and Maya
(tools/maya/scene_defaults.py) — standard library only, Python 3.9-valid.

Each setting is a short word in the config and in its launch variable; "" = "as is": Maya's own
preference is left alone and nothing is passed.

Measured with mayapy 2024 (a throwaway MAYA_APP_DIR): File > New takes the linear unit and the
playback range from Maya's preferences (optionVars workingUnitLinear(Default), playbackMin / Max /
MinRange / MaxRange and their *Default), so those are written; the up axis, the key tangents and
auto key outlast File > New on their own.
"""
from __future__ import annotations

import re

from msl_tools.msl.core.link import variables

# key -> (what the tab shows, what Maya is given)
SPEEDS = {"every": ("Every frame", 0.0), "realtime": ("Real-time", 1.0), "half": ("× 0.5", 0.5), "double": ("× 2", 2.0)}
UNITS = {"mm": "mm", "cm": "cm", "m": "m"}
UP_AXES = {"y": "Y", "z": "Z"}
# key -> (shown, in tangent, out tangent)
TANGENTS = {"auto": ("Auto", "auto", "auto"), "spline": ("Spline", "spline", "spline"),
            "clamped": ("Clamped", "clamped", "clamped"), "linear": ("Linear", "linear", "linear"),
            "flat": ("Flat", "flat", "flat"), "plateau": ("Plateau", "plateau", "plateau"),
            "stepped": ("Stepped", "auto", "step")}
AUTO_KEY = {"on": "On", "off": "Off"}

KEYS = ("range", "units", "up", "speed", "tangents", "autokey")
_VARIABLE = {"range": variables.SCENE_RANGE, "units": variables.SCENE_UNITS, "up": variables.SCENE_UP,
             "speed": variables.SCENE_SPEED, "tangents": variables.SCENE_TANGENTS, "autokey": variables.SCENE_AUTO_KEY}
_CHOICES = {"units": UNITS, "up": UP_AXES, "speed": SPEEDS, "tangents": TANGENTS, "autokey": AUTO_KEY}
_RANGE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:-|–|—|\.\.|\s|to)\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_range(text: str):
    """(start, end) of "1-120" / "1 120" / "1..120" / "1–120"; None for anything else or start >= end."""
    match = _RANGE.match(str(text or ""))
    if not match:
        return None
    start, end = float(match.group(1)), float(match.group(2))
    if start >= end:
        return None
    return (int(start) if start.is_integer() else start, int(end) if end.is_integer() else end)


def range_text(value) -> str:
    """The stored form of a range: "1 120" ("" for none)."""
    return "%s %s" % value if value else ""


def cleaned(stored) -> dict:
    """Every key of `stored` (a config node / dict) that holds a known value; the rest as ""."""
    result = {}
    for key in KEYS:
        value = str((stored.get(key, "") if stored is not None else "") or "").strip()
        if key == "range":
            value = range_text(parse_range(value))
        elif value not in _CHOICES[key]:
            value = ""
        result[key] = value
    return result


def to_environment(settings: dict) -> dict:
    """The launch variables of `settings` (only the ones set)."""
    found = cleaned(settings)
    return {_VARIABLE[key]: value for key, value in found.items() if value}


def from_environment(environment) -> dict:
    """What a launch asked for, read back inside Maya ({key: "" or the value})."""
    return cleaned({key: environment.get(name, "") for key, name in _VARIABLE.items()})


def describe(settings: dict) -> list:
    """The settings that are set, in plain words: ["range 1–120", "units m", ...]."""
    found = cleaned(settings)
    words = []
    if found["range"]:
        start, end = parse_range(found["range"])
        words.append("range %s–%s" % (start, end))
    if found["units"]:
        words.append("units %s" % found["units"])
    if found["up"]:
        words.append("%s up" % UP_AXES[found["up"]])
    if found["speed"]:
        words.append("playback %s" % SPEEDS[found["speed"]][0].lower())
    if found["tangents"]:
        words.append("%s keys" % TANGENTS[found["tangents"]][0].lower())
    if found["autokey"]:
        words.append("auto key %s" % found["autokey"])
    return words
