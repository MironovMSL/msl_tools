# tools/maya/animation/xform.py
"""XFORM TOOLS as data (no Qt, no Maya): what a copied world space / relationship holds, which copied frame a paste
takes, and on which frames a paste is keyed.

A copy travels like Transfer's (the same format, kinds "xform_world" / "xform_relationship": the clipboard as text
and a file beside it, so another Maya pastes it too):
    {"format": "msl_transfer", "kind": ..., "frame": the frame it was taken on, "parent": the parent's long name
     (relationship), "objects": [{"name", "path", "frames": {"<frame>": 16 numbers}}]}
A world copy's matrix = the object's world turn with its ROTATE PIVOT as the position; a relationship's = that
matrix over the parent's world matrix (child x parent^-1). One frame copied = used on every frame; a playback range
copied = each frame takes its own, a frame outside it the nearest.

MEASURED on the reference (Maya 2025, its buttons with a real mouse; 2026-10-22), and ours does the same:
    COPY RELATIONSHIP      the selected objects (children) to the LAST selected (the parent), on this frame -
                           right click: on every frame of the playback range
    PASTE RELATIONSHIP     each selected child (the last selected = the parent, never moved) put where the copied
                           relationship and the parent's place NOW say: on the current frame values only (auto key:
                           a key on the channels already animated); a span highlighted with keys inside = keyed on
                           every key frame of the child or the parent inside it, a span with none = every frame of it
                           baked; right click: Next Frame (one frame on, keyed), All Keys (every key frame of either),
                           Bake Frames (every frame of the playback range)
    COPY / PASTE WORLD SPACE   the same with the world: the copied object's rotate pivot and turn given to what is
                           selected when pasting (one copied object onto every selected; several by name, else by
                           order); its All Keys = the object's own key frames
    move and turn only - scale is left (as Align)
Deliberately different: the reference's "Multi Frame Xform Lightning Mode" (on by default) drops a moved rotate
pivot on All Keys / Bake Frames (measured: its keys at frame 10 were 7.061 / -0.354 where the single paste - and the
same paste with the mode off - gave 6.923 / -0.686); ours is always exact.
"""
from __future__ import annotations

WORLD = "xform_world"
RELATIONSHIP = "xform_relationship"
NOW, NEXT, ALL, BAKE = "now", "next", "all", "bake"


def frame_key(frame: float) -> str:
    return f"{float(frame):g}"


def at(frames: dict, frame: float) -> "list | None":
    """The copied matrix for `frame`: its own, else the nearest copied frame's (one frame copied = always it)."""
    if not frames:
        return None
    own = frames.get(frame_key(frame))
    if own is not None:
        return own
    nearest = min(frames, key=lambda key: abs(float(key) - float(frame)))
    return frames[nearest]


def plan(mode: str, keys: list, now: float, span: "tuple | None" = None,
         playback: "tuple | None" = None) -> "list | None":
    """The frames a paste keys, in order; None = the current frame, NOT keyed (values only, auto key aside).
    `keys` = the key times that count (the object's, and a relationship's parent's); `span` = the highlighted
    one (first, last - both in); `playback` = the playback range."""
    times = sorted({round(float(time), 6) for time in keys})
    if mode == NEXT:
        return [float(now) + 1.0]
    if mode == ALL:
        return times
    if mode == BAKE:
        start, end = playback or (now, now)
        return [float(frame) for frame in range(int(round(start)), int(round(end)) + 1)]
    if span:
        start, end = span
        inside = [time for time in times if start - 1e-6 <= time <= end + 1e-6]
        return inside or [float(frame) for frame in range(int(round(start)), int(round(end)) + 1)]
    return None


def describe(kind: str, count: int, frames: int = 0) -> str:
    what = "relationship" if kind == RELATIONSHIP else "world space"
    text = f"Pasted the {what} onto {count} object{'s' if count != 1 else ''}"
    if frames:
        text += f" on {frames} frame{'s' if frames != 1 else ''}"
    return text
