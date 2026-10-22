# tools/maya/animation/transfer.py
"""ANIM / POSE TRANSFER as data (no Qt, no Maya): what a copy holds, how it goes into text and back, which copied
object goes onto which target, and where a paste lands in time.

A copy is plain data, so it travels: the window puts it on the system clipboard AS TEXT (another Maya - also on
another computer, through a chat - reads it back) and into a file (another Maya on this computer finds it even
after the clipboard was used for something else). `to_text` / `from_text`; `from_text` refuses anything that is not
a copy of ours.

    {"format": "msl_transfer", "version": 1, "kind": "animation" | "pose",
     "start": first frame of the copied span, "end": its last, "frame": the frame a pose was taken on,
     "objects": [{"name": short name without namespace, "path": long name,
                  "channels": {attribute: {"value": now, "keys": [[time, value, in type, out type, in angle,
                               out angle, in weight, out weight, lock, weight lock, breakdown, special tick], ...],
                               "weighted": bool, "pre": infinity, "post": infinity}}}]}

MEASURED on the reference (Maya 2025, its buttons clicked with a real mouse; 2026-10-22):
    COPY ANIMATION   the selected objects' keys inside the timeline's highlighted span, else inside the animation
                     range (the time slider's start / end, keys outside the playback range included);
    PASTE INSERT     the copy shifted so its span's START lands on the current frame - or on the start of a span
                     highlighted when pasting; the target's keys inside the span it lands on are cleared first, on
                     every animated channel of the target (a curve left with no key goes);
    PASTE REPLACE    the target's animation REPLACED: every curve cleared, the copy put in on its own frames;
    COPY POSE        every channel of the Channel Box at the current frame;
    PASTE POSE       the values set; with Maya's auto key on, the channels that are animated get a key there (as
                     Maya's auto key would), the others only the value;
    ONE object copied goes onto each selected one (another name, another namespace alike).
"""
from __future__ import annotations

import json

FORMAT = "msl_transfer"
VERSION = 1
ANIMATION = "animation"
POSE = "pose"


def short_name(path: str) -> str:
    """The node's own name without its path and namespace: "|rig|ns:arm_ctrl" -> "arm_ctrl"."""
    return path.split("|")[-1].split(":")[-1]


def to_text(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"))


def from_text(text: str, kind: str = "") -> "dict | None":
    """The copy in `text`, or None when it is no copy of ours (of that `kind`, if given)."""
    if not text or FORMAT not in text[:200]:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("objects"), list):
        return None
    if kind and data.get("kind") != kind:
        return None
    return data


def describe(data: dict) -> str:
    """A copy in a few words: "3 objects, 42 keys, frames 1-48"."""
    objects = data.get("objects") or []
    count = len(objects)
    if data.get("kind") == POSE:
        channels = sum(len(item.get("channels") or {}) for item in objects)
        return (f"{count} object{'s' if count != 1 else ''}, {channels} channel{'s' if channels != 1 else ''} "
                f"(frame {data.get('frame', 0):g})")
    keys = sum(len(channel.get("keys") or []) for item in objects for channel in (item.get("channels") or {}).values())
    return (f"{count} object{'s' if count != 1 else ''}, {keys} key{'s' if keys != 1 else ''}, frames "
            f"{data.get('start', 0):g}-{data.get('end', 0):g}")


def pair(copied: list, targets: list) -> list:
    """[(copied index, target)] - which copied object goes onto which target (names: long paths).
    ONE copied object: onto every target (measured). Else by the name without path and namespace (the same rig in
    another scene or namespace); targets no copied name fits are left out. Nothing fits by name and the counts are
    equal: by the order picked."""
    if not copied or not targets:
        return []
    if len(copied) == 1:
        return [(0, target) for target in targets]
    by_name = {}
    for index, path in enumerate(copied):
        by_name.setdefault(short_name(path), index)
    pairs = [(by_name[short_name(target)], target) for target in targets if short_name(target) in by_name]
    if not pairs and len(copied) == len(targets):
        pairs = list(enumerate(targets))
    return pairs


def landing(start: float, end: float, now: float, highlight: "tuple | None" = None) -> tuple:
    """Where a PASTE INSERT lands: (offset, clear from, clear to). The copy's start goes to the start of the span
    highlighted when pasting, else to the current frame (measured); the target is cleared over the highlighted span,
    else over as long a span as the copy's."""
    if highlight:
        begin, finish = float(highlight[0]), float(highlight[1])
        return begin - start, begin, finish
    return now - start, now, now + (end - start)


def in_span(time: float, start: float, end: float) -> bool:
    return start - 1e-6 <= time <= end + 1e-6
