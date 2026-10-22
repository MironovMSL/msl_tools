# tools/maya/animation/align.py
"""ALIGN OBJECTS as data (no Qt, no Maya): on which frames the selected objects are put onto the last selected one.

MEASURED on the reference (Maya 2025, its buttons clicked with a real mouse; 2026-10-22), and ours does the same:
    ALIGN OBJECTS      every selected object but the LAST put where the last one is in the WORLD: its rotate pivot
                       onto the last one's rotate pivot, its turn the last one's (scale left alone); on the current
                       frame - values only, with Maya's auto key on a key on the channels that are animated (as auto
                       key would) - or, with a span highlighted on the timeline, KEYED on every frame inside it where
                       either the object or the last one has a key (the span's own first frame only when a key is
                       there), all six move / turn channels
    ALIGN ALL KEYS     the same on every frame where either of the two has a key, the whole timeline
    THE RIGHT CLICK    each of them for one part alone: POSITION (the rotate pivot carried over, the turn left),
                       ORIENTATION (the turn, the move channels left - the object turns about its pivot), SCALE (the
                       target's world scale over the object's parent's, axis by axis; a plain Align leaves scale)
"""
from __future__ import annotations


def frames(own: list, target: list, span: "tuple | None" = None) -> list:
    """The frames an object is keyed on: every key time of its own or of the object it goes onto, inside `span`
    (first, last - both in) when given, in order."""
    times = sorted({round(float(time), 6) for time in list(own) + list(target)})
    if span:
        start, end = span
        times = [time for time in times if start - 1e-6 <= time <= end + 1e-6]
    return times


WHAT = {"translate": "position", "rotate": "orientation", "scale": "scale"}


def describe(count: int, frame_count: int = 0, part: str = "") -> str:
    what = f"the {WHAT[part]} of " if part in WHAT else ""
    text = f"Aligned {what}{count} object{'s' if count != 1 else ''} to the last selected"
    if frame_count:
        text += f" on {frame_count} frame{'s' if frame_count != 1 else ''}"
    return text
