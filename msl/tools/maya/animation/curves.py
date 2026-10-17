# tools/maya/animation/curves.py
"""What the sliders DO to keys, as arithmetic (no Qt, no Maya).

Everything works on a `Block`: a run of keys of ONE animation curve that a slider acts on (keys
next to each other on that curve), with what lies around it — the key before and after the run
(and the one past each, for the infinity blend), the attribute's default, the value at the frame
picked in the window, the values before the tool's last change, and a way to read the curve at
any time (for the time offset). `apply(mode, block, weight)` returns the run's new values.

The weight goes from -1 (all the way left) to 1 (all the way right), past that with overshoot
(the window allows -2..2). 0 always means "nothing changes", except for the Tweener, which is a
POSITION between the neighbors (0 = half way) — as in the classic tween machine.

The modes (`MODES`) come in two families, as two sliders in the window:
    POSE   where the keys' values go — toward the neighbors, the default, a frame, the infinity
           of the curve, the values before the last change; the Tweener
    CURVE  the shape of the run — pull to / push from the straight line, scale about a pivot,
           smooth / rough, ease in / out, noise / wave, offset in time, connect to a neighbor
In each the left side is the first word of the name: Pull | Push, Smooth | Rough, Ease In | Out.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable

POSE = "pose"
CURVE = "curve"

TWEEN_FRACTIONS = (0.0, 1 / 8, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 3 / 4, 5 / 6, 7 / 8, 1.0)
BLEND_MARKS = (-1.0, -0.75, -0.5, -0.25, -0.1, 0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
OFFSET_FRAMES = 10.0     # how far the time offset reaches at a full weight
NOISE_PART = 0.25        # how big noise / wave get at a full weight, as a part of the run's own range
EASE_MAX_POWER = 10.0    # the ease's shape at a full weight: u ** 10 - a key half way lands next to its neighbor
EASE_CURVE = 2.5         # how the power grows with the weight (1 + 9 * weight ** 2.5)
EASE_BLEND = 0.25        # from this weight on the run IS the ease; below it, it blends in from the keys as they are


@dataclass(frozen=True)
class Mode:
    key: str
    title: str
    short: str          # what the slider's knob reads
    family: str         # POSE / CURVE
    tip: str
    left: str           # what the left side does, the right side does
    right: str
    marks: tuple = BLEND_MARKS    # the weights a click on the track snaps to
    modifier: str = ""            # held while pressing the slider: this mode instead of the picked one


MODES = (
    Mode("tween", "Tweener", "TW", POSE, "An inbetween: the key's value between the keys before and after it, "
         "by the classic fractions (a click on a mark).", "toward the key before", "toward the key after",
         tuple(2 * fraction - 1 for fraction in TWEEN_FRACTIONS)),
    Mode("neighbors", "Blend to Neighbors", "BN", POSE, "From the pose as it is toward the key before (left) or "
         "after (right).", "toward the key before", "toward the key after", modifier="Shift"),
    Mode("default", "Blend to Default", "BD", POSE, "Toward the rig's default pose (right) or away from it "
         "(left).", "away from the default", "toward the default", modifier="Alt+Shift"),
    Mode("frame", "Blend to Frame", "BF", POSE, "Toward the pose at the frame picked under the sliders (right) or "
         "away from it (left).", "away from that frame", "toward that frame", modifier="Ctrl"),
    Mode("infinity", "Blend to Infinity", "BI", POSE, "Toward where the curve would go on in a straight line: "
         "from the two keys before (left) or the two after (right).", "the line from before",
         "the line from after", modifier="Ctrl+Alt"),
    Mode("undo", "Blend to Undo", "BU", POSE, "Toward the values before the last change made with these sliders "
         "(right) - undo only a part of it - or away from them (left).", "away from before",
         "back to before", modifier="Ctrl+Shift"),
    Mode("pull_push", "Pull | Push", "PP", CURVE, "Soften (left: toward the straight line between the keys "
         "around) or exaggerate (right) the run.", "pull to the straight line", "push away from it",
         modifier="Alt"),
    Mode("scale_average", "Scale From Average", "SA", CURVE, "Scale the keys about their average: left "
         "flattens (all the way: the average), right exaggerates.", "toward the average", "away from it"),
    Mode("scale_default", "Scale From Default", "SD", CURVE, "Scale the keys about the attribute's default "
         "value: left releases the pose, right intensifies it.", "toward the default", "away from it",
         modifier="Alt+Shift"),
    Mode("scale_left", "Scale From Neighbor Left", "SL", CURVE, "Scale the keys about the key before the run - "
         "good for anticipations and overshoots.", "toward the key before", "away from it"),
    Mode("scale_right", "Scale From Neighbor Right", "SR", CURVE, "Scale the keys about the key after the run.",
         "toward the key after", "away from it"),
    Mode("scale_frame", "Scale From Frame", "SF", CURVE, "Scale the keys about the value at the frame picked "
         "under the sliders.", "toward that frame's value", "away from it", modifier="Ctrl"),
    Mode("smooth_rough", "Smooth | Rough", "SM", CURVE, "Soften the run (left; a few times turns dead keys "
         "into moving holds, cleans noisy mocap) or make it harsher (right).", "smoother", "rougher",
         modifier="Shift"),
    Mode("ease", "Ease In | Out", "EA", CURVE, "Respace the run between the keys around it in an ease that gets "
         "stronger along the slider - at 100 % the keys hug the neighbor they ease into: left eases in (slow "
         "start), right eases out (slow end).", "ease in", "ease out",
         modifier="Ctrl+Shift"),
    Mode("time_offset", "Time Offsetter", "TO", CURVE, f"Slide the motion in time without moving the keys "
         f"(a full weight: {OFFSET_FRAMES:g} frames).", "earlier", "later", modifier="Ctrl+Alt"),
    Mode("stagger", "Time Offsetter Stagger", "TS", CURVE, "Like the Time Offsetter, spread over the selected "
         "objects in the order they were picked: quick overlap down a chain.", "earlier, one after another",
         "later, one after another"),
    Mode("noise_wave", "Noise | Wave", "NW", CURVE, "Add noise (left) or a wave - up, down, up - (right) to the "
         "run.", "noise", "wave"),
    Mode("connect", "Connect to Neighbors", "CN", CURVE, "Move the run so its first key meets the key before "
         "(left) or its last key meets the key after (right), fading along the run.", "to the key before",
         "to the key after"),
)

BY_KEY = {mode.key: mode for mode in MODES}
POSE_MODES = tuple(mode for mode in MODES if mode.family == POSE)
CURVE_MODES = tuple(mode for mode in MODES if mode.family == CURVE)


def mode_for_modifiers(family: str, modifiers: str) -> "Mode | None":
    """The mode a slider of that family switches to while these modifiers are held ("Ctrl+Shift"),
    or None (the picked one stays)."""
    wanted = normalize_modifiers(modifiers)
    if not wanted:
        return None
    for mode in MODES:
        if mode.family == family and mode.modifier and normalize_modifiers(mode.modifier) == wanted:
            return mode
    return None


def normalize_modifiers(text: str) -> str:
    parts = {part.strip().lower() for part in (text or "").split("+") if part.strip()}
    return "+".join(name for name in ("ctrl", "alt", "shift") if name in parts)


# --------------------------------------------------------------------------- the slider's feel

def weight_at(position: float, limit: float = 1.0) -> float:
    """The weight at a place on the slider's track (-1 = the left end, 1 = the right end): it grows
    with the square of the distance, so the middle is fine work and the ends move a lot - as the
    reference tools feel. `limit` is the weight at an end (2 with overshoot)."""
    position = max(-1.0, min(1.0, float(position)))
    return math.copysign(position * position * limit, position)


def position_of(weight: float, limit: float = 1.0) -> float:
    """Where on the track a weight lies (the inverse of `weight_at`): for drawing the marks."""
    if limit <= 0:
        return 0.0
    part = max(-1.0, min(1.0, float(weight) / limit))
    return math.copysign(math.sqrt(abs(part)), part)


def weight_text(mode: "Mode | str", weight: float) -> str:
    """A weight as people read it for that mode: the Tweener's place between the neighbors ("33%"),
    the time offset in frames ("+2.5 fr"), else how far it went ("+40%")."""
    key = mode.key if isinstance(mode, Mode) else mode
    if key == "tween":
        return f"{(weight + 1) * 50:.0f}%"
    if key in ("time_offset", "stagger"):
        return f"{weight * OFFSET_FRAMES:+.1f} fr"
    return f"{weight * 100:+.0f}%"


# --------------------------------------------------------------------------- the data

@dataclass
class Block:
    """A run of keys of one curve and what lies around it. Times in frames, values in what the
    curve holds (the window's units - degrees for a rotation, as the Graph Editor shows them)."""

    times: list
    values: list
    before: "tuple | None" = None        # (time, value) of the key before the run
    after: "tuple | None" = None         # (time, value) of the key after it
    before2: "tuple | None" = None       # the key before `before`
    after2: "tuple | None" = None        # the key after `after`
    default: float = 0.0
    frame_value: "float | None" = None   # the curve's value at the frame picked in the window
    undo_values: "list | None" = None    # the run's values before the tools' last change
    evaluate: "Callable | None" = None   # time -> the curve's value there (as it was before the drag)
    order: int = 0                       # its object's place in the selection, and how many there are
    count: int = 1
    seed: int = 0                        # keeps noise the same during one drag

    def anchors(self) -> tuple:
        """The two ends the run hangs between: the keys around it, else its own first / last key."""
        start = self.before if self.before is not None else (self.times[0], self.values[0])
        end = self.after if self.after is not None else (self.times[-1], self.values[-1])
        return start, end


def _line(start: tuple, end: tuple, time: float) -> float:
    (t0, v0), (t1, v1) = start, end
    if t1 == t0:
        return v0
    return v0 + (v1 - v0) * (time - t0) / (t1 - t0)


def _toward(value: float, target: float, weight: float) -> float:
    """Right (weight > 0): toward the target; left: away from it (as far again at -1)."""
    return value + (target - value) * weight


def _toward_sides(value: float, left: "float | None", right: "float | None", weight: float) -> float:
    """Left: toward `left`, right: toward `right` (each by how far the weight goes)."""
    target = left if weight < 0 else right
    if target is None:
        return value
    return value + (target - value) * abs(weight)


def _scale(value: float, pivot: "float | None", weight: float) -> float:
    if pivot is None:
        return value
    return pivot + (value - pivot) * (1.0 + weight)


def _smoothed(block: Block) -> list:
    start, end = block.anchors()
    values = [start[1] if block.before is not None else block.values[0]] + list(block.values) + \
             [end[1] if block.after is not None else block.values[-1]]
    return [(values[i - 1] + 2 * values[i] + values[i + 1]) / 4.0 for i in range(1, len(values) - 1)]


def ease_power(weight: float) -> float:
    """The ease's power for a weight: 1 (a straight line) at 0, EASE_MAX_POWER at 1, more past it.
    Measured on the reference (a key half way between 0 and 10): 25 % -> 3.66 / 6.34, 50 % -> 1.96 /
    8.04, 75 % -> 0.22 / 9.78, 100 % -> 0.01 / 9.99 - a power that grows like this, not a fixed one."""
    weight = min(abs(float(weight)), 2.0)
    return 1.0 + (EASE_MAX_POWER - 1.0) * weight ** EASE_CURVE


def _eased(block: Block, weight: float) -> list:
    (t0, v0), (t1, v1) = block.anchors()
    if t1 == t0:
        return list(block.values)
    power = ease_power(weight)
    out = []
    for time in block.times:
        u = max(0.0, min(1.0, (time - t0) / (t1 - t0)))
        shape = u ** power if weight < 0 else 1.0 - (1.0 - u) ** power
        out.append(v0 + (v1 - v0) * shape)
    return out


def _infinity(near: "tuple | None", far: "tuple | None", time: float) -> "float | None":
    if near is None:
        return None
    if far is None or far[0] == near[0]:
        return near[1]
    return _line(far, near, time)


def _amplitude(block: Block) -> float:
    values = list(block.values) + [key[1] for key in (block.before, block.after) if key is not None]
    spread = max(values) - min(values) if values else 0.0
    return (spread if spread > 1e-9 else 1.0) * NOISE_PART


def apply(mode: "Mode | str", block: Block, weight: float) -> list:
    """The run's new values for this weight (a list as long as `block.values`)."""
    key = mode.key if isinstance(mode, Mode) else mode
    values = [float(value) for value in block.values]
    weight = float(weight)
    if not values:
        return []
    if key == "tween":
        if block.before is None or block.after is None:
            return values
        fraction = (weight + 1.0) / 2.0
        return [block.before[1] + (block.after[1] - block.before[1]) * fraction for _ in values]
    if weight == 0.0:
        return values
    if key == "neighbors":
        left = block.before[1] if block.before is not None else None
        right = block.after[1] if block.after is not None else None
        return [_toward_sides(value, left, right, weight) for value in values]
    if key == "default":
        return [_toward(value, block.default, weight) for value in values]
    if key == "frame":
        if block.frame_value is None:
            return values
        return [_toward(value, block.frame_value, weight) for value in values]
    if key == "infinity":
        out = []
        for time, value in zip(block.times, values):
            left = _infinity(block.before, block.before2, time)
            right = _infinity(block.after, block.after2, time)
            out.append(_toward_sides(value, left, right, weight))
        return out
    if key == "undo":
        if not block.undo_values or len(block.undo_values) != len(values):
            return values
        return [_toward(value, before, weight) for value, before in zip(values, block.undo_values)]
    if key == "pull_push":
        start, end = block.anchors()
        out = []
        for time, value in zip(block.times, values):
            straight = _line(start, end, time)
            out.append(straight + (value - straight) * (1.0 + weight))
        return out
    if key == "scale_average":
        average = sum(values) / len(values)
        return [_scale(value, average, weight) for value in values]
    if key == "scale_default":
        return [_scale(value, block.default, weight) for value in values]
    if key == "scale_left":
        return [_scale(value, block.before[1] if block.before else None, weight) for value in values]
    if key == "scale_right":
        return [_scale(value, block.after[1] if block.after else None, weight) for value in values]
    if key == "scale_frame":
        return [_scale(value, block.frame_value, weight) for value in values]
    if key == "smooth_rough":
        smooth = _smoothed(block)
        if weight < 0:
            return [value + (target - value) * -weight for value, target in zip(values, smooth)]
        return [value + (value - target) * weight for value, target in zip(values, smooth)]
    if key == "ease":
        # the reference sets the ease outright (the keys as they are don't count); here it blends in
        # over the first EASE_BLEND of the slider, so a small pull never jumps the keys
        eased = _eased(block, weight)
        blend = min(1.0, abs(weight) / EASE_BLEND)
        return [value + (target - value) * blend for value, target in zip(values, eased)]
    if key in ("time_offset", "stagger"):
        if block.evaluate is None:
            return values
        share = 1.0
        if key == "stagger":
            share = block.order / (block.count - 1) if block.count > 1 else 0.0
        shift = weight * OFFSET_FRAMES * share
        return [float(block.evaluate(time - shift)) for time in block.times]
    if key == "noise_wave":
        amplitude = _amplitude(block) * abs(weight)
        if weight < 0:
            rng = random.Random(block.seed)
            return [value + amplitude * rng.uniform(-1.0, 1.0) for value in values]
        return [value + amplitude * (1.0 if index % 2 == 0 else -1.0) for index, value in enumerate(values)]
    if key == "connect":
        side = block.before if weight < 0 else block.after
        if side is None:
            return values
        edge = values[0] if weight < 0 else values[-1]
        delta = (side[1] - edge) * abs(weight)
        first, last = block.times[0], block.times[-1]
        out = []
        for time, value in zip(block.times, values):
            if last == first:
                fade = 1.0
            elif weight < 0:
                fade = (last - time) / (last - first)
            else:
                fade = (time - first) / (last - first)
            out.append(value + delta * fade)
        return out
    raise KeyError(f"unknown slider mode: {key}")


def split_runs(indices) -> list:
    """Picked key indices of one curve -> runs of consecutive ones ([1, 2, 3, 7] -> [[1, 2, 3], [7]])."""
    runs = []
    for index in sorted(set(int(i) for i in indices)):
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def block_from_keys(times, values, run, **extra) -> Block:
    """The Block of one run (key indices, consecutive) of a curve whose keys are `times` / `values`."""
    first, last = run[0], run[-1]

    def key(index):
        return (float(times[index]), float(values[index])) if 0 <= index < len(times) else None

    return Block(times=[float(times[i]) for i in run], values=[float(values[i]) for i in run],
                 before=key(first - 1), after=key(last + 1), before2=key(first - 2), after2=key(last + 2), **extra)
