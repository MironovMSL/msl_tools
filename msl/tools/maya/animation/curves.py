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
TANGENT = "tangent"

TWEEN_FRACTIONS = (0.0, 1 / 8, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 3 / 4, 5 / 6, 7 / 8, 1.0)
# The reference's marks, MEASURED (a probe of 11 keys, 5 picked, every mark clicked): 0.05, 0.15, 0.5 and 1 a
# side on both sliders. On the CURVE slider whatever EXAGGERATES (push, rough, scale) goes twice as far: at the
# end the distance from the line / the smooth curve / the pivot is three times what it was (`STRONG`).
BLEND_MARKS = (-1.0, -0.5, -0.15, -0.05, 0.05, 0.15, 0.5, 1.0)
STRONG = 2.0
# The time offset - MEASURED on the reference: the keys stay on their frames and take the value the curve has that
# many frames away - the marks 0.5 / 1 / 2 / 3 frames, the END 10 (a 60-key wave: the key on frame 12 took frame
# 2's value, exactly), a drag growing about with the square of the distance. A zigzag showed the curve wrapping
# round as a CYCLE between its first and last key, so nothing sticks at the ends. The stagger (five links of a
# tail, picked tip-first and root-first: the same result) goes ROOT TO TIP - the tip the whole shift, each link
# toward the root a step less (10 / 8 / 6 / 4 / 2 at the end); siblings by name.
OFFSET_FRAMES = 10.0     # how far the time offset reaches at a full weight
OFFSET_MARKS = tuple(sign * frames / OFFSET_FRAMES for sign in (-1.0, 1.0)
                     for frames in (0.5, 1.0, 2.0, 3.0, OFFSET_FRAMES))    # 0.5, 1, 2, 3 frames, the end
NOISE_PART = 1.0         # noise / wave at a full weight: the run's own range (max - min) - measured
# The ease's power by weight - MEASURED on the reference (keys 3 / 5 / 7 / 9 between unpicked 0 at 1 and 10 at
# 11, its knob and marks clicked): the knob = a straight line, the marks 1.45, 2.35, 5.5 and 10 (u ** 10 at the
# end: the keys hug the neighbor they ease into); between them the power runs evenly in log space; past 100 %
# (overshoot) it goes on to 30.
EASE_POWERS = ((0.0, 1.0), (0.25, 1.45), (0.5, 2.35), (0.75, 5.5), (1.0, 10.0), (2.0, 30.0))
EASE_MARKS = (-1.0, -0.75, -0.5, -0.25, 0.25, 0.5, 0.75, 1.0)


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
    Mode("blend_ease", "Blend to Ease", "BE", POSE, "Tighten the spacing by forcing the ease: each key goes "
         "toward the key before (left) or after (right) - the ones near it nearly all the way, the far ones "
         "hardly - more strongly the further out (measured on the reference: 1 - u ** (10 x weight)).",
         "ease out of the key before", "ease into the key after", modifier="Ctrl+Shift"),
    Mode("frame", "Blend to Frame", "BF", POSE, "Toward the pose at one of TWO frames - the grey squares at the "
         "slider's ends (hover: the frame; click: take the current frame; wheel: +-1; right click: type it): left "
         "toward the left one's pose, right toward the right one's.", "toward the left frame",
         "toward the right frame", modifier="Ctrl"),
    Mode("infinity", "Blend to Infinity", "BI", POSE, "Toward where the curve would go on in a straight line: "
         "left the line the two keys AFTER the run point along (carried back), right the line of the two keys "
         "BEFORE it (carried on) - great for handles.", "the line from after", "the line from before",
         modifier="Ctrl+Alt"),
    Mode("undo", "Blend to Undo", "BU", POSE, "Toward the values before the last change made with these sliders "
         "(right) - undo only a part of it - or away from them (left).", "away from before",
         "back to before"),
    Mode("buffer", "Blend to Buffer", "BB", POSE, "Toward Maya's buffer curve - the snapshot taken in the Graph "
         "Editor (Curves > Buffer Curve Snapshot), drawn there as a dark line: try things, then pull back to "
         "it as far as you like (right) or away from it (left).", "away from the buffer", "toward the buffer",
         modifier="Ctrl+Alt+Shift"),
    Mode("pull_push", "Pull | Push", "PP", CURVE, "Soften (left: all the way = the straight line between the "
         "keys around) or exaggerate (right: up to three times as far from that line) the run.",
         "pull to the straight line", "push away from it",
         modifier="Alt"),
    Mode("scale_average", "Scale From Average", "SA", CURVE, "Scale the keys about the middle of their range: half "
         "way left flattens them, all the way inverts, right exaggerates up to three times.",
         "flatten, invert", "exaggerate"),
    Mode("scale_default", "Scale From Default", "SD", CURVE, "Scale the keys about the attribute's default "
         "value: left releases the pose, right intensifies it.", "toward the default", "away from it",
         modifier="Alt+Shift"),
    Mode("scale_left", "Scale From Neighbor Left", "SL", CURVE, "Scale the keys about the key before the run - "
         "good for anticipations and overshoots.", "toward the key before", "away from it"),
    Mode("scale_right", "Scale From Neighbor Right", "SR", CURVE, "Scale the keys about the key after the run.",
         "toward the key after", "away from it"),
    Mode("scale_frame", "Scale From Frame", "SF", CURVE, "Scale the keys about the value at a frame - the grey "
         "square at the slider's left end (hover: the frame; click: take the current frame; wheel: +-1).",
         "toward that frame's value", "away from it", modifier="Ctrl"),
    Mode("smooth_rough", "Smooth | Rough", "SM", CURVE, "Soften the run (left; a few times turns dead keys "
         "into moving holds, cleans noisy mocap) or make it harsher (right).", "smoother", "rougher",
         modifier="Shift"),
    Mode("ease", "Ease In | Out", "EA", CURVE, "Lay the keys out anew between the unpicked keys around them - "
         "their own values don't count: the knob alone lines them up straight, further out the ease gets "
         "stronger, at 100 % they hug the neighbor they ease into. Left eases in (slow start), right eases "
         "out (slow end).", "ease in", "ease out", EASE_MARKS, modifier="Ctrl+Shift"),
    Mode("time_offset", "Time Offsetter", "TO", CURVE, f"Slide the motion along the curve while the keys stay on "
         f"their frames: each key takes the value the curve has a little earlier or later (the marks: 0.5, 1, 2, 3 "
         f"frames, the end {OFFSET_FRAMES:g}), the curve wrapping round like a cycle so its ends never stick.",
         "earlier", "later", OFFSET_MARKS, modifier="Ctrl+Alt"),
    Mode("stagger", "Time Offsetter Stagger", "TS", CURVE, "The Time Offsetter spread down a chain: the object "
         "deepest in the hierarchy (the tip) gets the whole shift, each one toward the root a step less "
         "(objects side by side: by name) - overlap in one pull, whatever order they were picked in.",
         "earlier, root to tip", "later, root to tip", OFFSET_MARKS),
    Mode("noise_wave", "Noise | Wave", "NW", CURVE, "Add noise (left) or a wave - down, up, down ... - (right) to the "
         "run, as big as the run's own range at the end.", "noise", "wave"),
    Mode("gap", "Gap Stitcher", "GS", CURVE, "Stitch the biggest jump between two keys of the run: the keys on "
         "either side lean toward each other, most at the jump and fading to the run's ends, so two chunks of "
         "animation join without going floaty. Both sides of the slider do the same.", "stitch", "stitch"),
    Mode("simplify_bake", "Simplify | Bake Keys", "SB", CURVE, "Left removes the keys that matter least (the ones "
         "left keep their values: the curve keeps its shape - good for mocap); right adds keys on whole frames "
         "along the curve as it is (every 2 frames half way, every frame at the end).", "fewer keys",
         "more keys", modifier="Ctrl+Alt+Shift"),
    Mode("connect", "Connect to Neighbors", "CN", CURVE, "Move the whole run as one, until its first key meets "
         "the key before (left) or its last key meets the key after (right).", "to the key before",
         "to the key after"),
)

# The TANGENT slider (tangents_scene.TangentDrag does the work, not `apply`): each mode blends the picked keys'
# tangent ANGLES toward what one tangent tool would give them - measured on the reference (a probe with fixed random
# tangents, every mark clicked): angle = now + weight x (target - now) on each side, held to +-90 degrees; the left
# side goes AWAY from the target ("negative values force easing" for Flat); the marks those of the other sliders; at
# the right end a native kind (auto, spline, ...) is SET as that kind, the others stay fixed.
TANGENT_MODES = (
    Mode("t_best_guess", "Blend to Best Guess", "BG", TANGENT, "Toward the tangents Best guess would give: clamped "
         "on the ends and the extremes, auto between.", "away from it", "toward best guess", modifier="Ctrl+Alt"),
    Mode("t_polished", "Blend to Polished", "PO", TANGENT, "Toward Polished: smooth, kept by the keys, overshoots "
         "kept to a minimum.", "away from it", "toward polished", modifier="Ctrl"),
    Mode("t_flow", "Blend to Flow", "FL", TANGENT, "Toward Flow: momentum carried from the neighbors - the "
         "movement flows on, even if that costs a little overshoot.", "away from it", "toward flow",
         modifier="Shift"),
    Mode("t_bounce", "Blend to Bounce", "BO", TANGENT, "Toward Bounce: sharp, straight at the neighbors - 'hitting "
         "a wall', no easing in or out.", "away from it", "toward bounce", modifier="Alt"),
    Mode("t_auto", "Blend to Auto", "AU", TANGENT, "Toward Maya's Auto tangents (at the right end they ARE auto).",
         "away from it", "toward auto", modifier="Ctrl+Shift"),
    Mode("t_spline", "Blend to Spline", "SP", TANGENT, "Toward Maya's Spline tangents (at the right end they ARE "
         "spline).", "away from it", "toward spline", modifier="Alt+Shift"),
    Mode("t_clamped", "Blend to Clamped", "CL", TANGENT, "Toward Maya's Clamped tangents (at the right end they "
         "ARE clamped).", "away from it", "toward clamped"),
    Mode("t_linear", "Blend to Linear", "LI", TANGENT, "Toward Maya's Linear tangents (at the right end they ARE "
         "linear).", "away from it", "toward linear"),
    Mode("t_flat", "Blend to Flat", "FT", TANGENT, "Toward flat tangents; to the left the tangents get steeper - "
         "the keys ease harder.", "steeper", "flatter", modifier="Ctrl+Alt+Shift"),
    Mode("t_plateau", "Blend to Plateau", "PL", TANGENT, "Toward Maya's Plateau tangents (at the right end they "
         "ARE plateau).", "away from it", "toward plateau"),
)

BY_KEY = {mode.key: mode for mode in MODES + TANGENT_MODES}
POSE_MODES = tuple(mode for mode in MODES if mode.family == POSE)
CURVE_MODES = tuple(mode for mode in MODES if mode.family == CURVE)


def mode_for_modifiers(family: str, modifiers: str) -> "Mode | None":
    """The mode a slider of that family switches to while these modifiers are held ("Ctrl+Shift"),
    or None (the picked one stays)."""
    wanted = normalize_modifiers(modifiers)
    if not wanted:
        return None
    for mode in MODES + TANGENT_MODES:
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


# Gap Stitcher, MEASURED on the reference (two probes: a wave with a jump of 11.5 in ten picked keys, a noisy
# curve with a drop of 6 in thirteen - 7 + 6 - keys; every mark clicked): the biggest jump between two picked keys
# is closed by half of it from each side, A = w * jump / 2, each key leaning by A * u ** p - u its place counted
# from its end of the run over HALF the run ((n + 1) / 2: a key at the middle of the run gets 1), p = 1 + 2w
# (1.1 / 1.3 / 2 / 3 at the marks). Matches both probes to 0.002.
# Simplify | Bake, MEASURED: simplify removes the keys that matter least, the rest keep their values - of 31 keys
# 30 / 29 / 22 / 12 stayed at the marks (`SIMPLIFY_PART` of the inner keys go at the end, a little slower near the
# middle; on a second probe the counts were off by at most one and 2 of 15 keys differed - the reference's own
# pick wasn't found: not the line, a spline, Maya's simplify or Douglas-Peucker); bake keys whole frames every
# round(1 / w) frames (2 half way, 1 at the end) counted back from each gap's later key, nothing when that is more
# than BAKE_LONGEST frames (the reference then put one key in the middle of the longest gap - not copied).
SIMPLIFY_PART = 0.655
SIMPLIFY_CURVE = 1.1
BAKE_LONGEST = 6
STRUCTURE_MODES = ("simplify_bake",)        # modes that add / remove keys rather than move them


def simplify_keep(times, values, weight: float) -> list:
    """The indices of the keys Simplify keeps (the first and last always): the key whose value the
    straight line between its neighbors left would miss least goes first, again and again."""
    count = len(times)
    if count <= 2:
        return list(range(count))
    remove = int(round(abs(weight) ** SIMPLIFY_CURVE * SIMPLIFY_PART * (count - 2)))
    keep = list(range(count))
    for _ in range(min(remove, count - 2)):
        best, best_error = None, None
        for position in range(1, len(keep) - 1):
            a, i, b = keep[position - 1], keep[position], keep[position + 1]
            straight = _line((times[a], values[a]), (times[b], values[b]), times[i])
            error = abs(values[i] - straight)
            if best_error is None or error < best_error:
                best, best_error = position, error
        keep.pop(best)
    return keep


def bake_times(times, weight: float) -> list:
    """The whole frames Bake adds keys on: in each gap between two keys, every `step` frames counted
    BACK from the gap's later key (measured: between keys on 5 and 12 at step 2 the reference keys 10, 8
    and 6, not 7, 9 and 11); none that are keys already."""
    if abs(weight) < 1e-9 or len(times) < 2:
        return []
    step = max(1, int(round(1.0 / abs(weight))))
    if step > BAKE_LONGEST:
        return []
    added = []
    for start, end in zip(times, times[1:]):
        frame = math.ceil(end - 1e-6) - step if abs(end - round(end)) < 1e-6 else math.floor(end)
        while frame > start + 1e-6:
            added.append(float(frame))
            frame -= step
    have = {round(time, 3) for time in times}
    return sorted(time for time in set(added) if round(time, 3) not in have)


def _gap(block: Block, weight: float) -> list:
    values = list(block.values)
    count = len(values)
    if count < 2 or weight == 0.0:
        return values
    gap = max(range(count - 1), key=lambda index: abs(values[index + 1] - values[index]))
    amount = abs(weight) * (values[gap + 1] - values[gap]) / 2.0
    power = 1.0 + 2.0 * abs(weight)
    half = (count + 1) / 2.0
    out = list(values)
    for index in range(count):
        if index <= gap:                     # this side moves toward the other, by its place from the start
            out[index] += amount * ((index + 1) / half) ** power
        else:
            out[index] -= amount * ((count - index) / half) ** power
    return out


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
    frame_value: "float | None" = None   # the curve's value at the (left) frame picked in the window
    frame_value_right: "float | None" = None   # ...and at the right one (Blend to Frame)
    undo_values: "list | None" = None    # the run's values before the tools' last change
    buffer_values: "list | None" = None  # Maya's buffer curve at the run's times (Blend to Buffer)
    evaluate: "Callable | None" = None   # time -> the curve's value there (as it was before the drag)
    order: int = 0                       # its object's place in the selection, and how many there are
    cycle: "tuple | None" = None         # (first, last) key time of the whole curve: the time offset wraps there
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
    """About a pivot, measured: the end exaggerates to 3x, half way left flattens to the pivot, the
    left end inverts (-1x)."""
    if pivot is None:
        return value
    return pivot + (value - pivot) * (1.0 + STRONG * weight)


def _smoothed(block: Block) -> list:
    start, end = block.anchors()
    values = [start[1] if block.before is not None else block.values[0]] + list(block.values) + \
             [end[1] if block.after is not None else block.values[-1]]
    return [(values[i - 1] + 2 * values[i] + values[i + 1]) / 4.0 for i in range(1, len(values) - 1)]


def ease_power(weight: float) -> float:
    """The ease's power for a weight (`EASE_POWERS`, the reference's): 1 = a straight line at 0,
    10 at 100 %, interpolated in log space between the measured steps."""
    weight = min(abs(float(weight)), EASE_POWERS[-1][0])
    for (w0, p0), (w1, p1) in zip(EASE_POWERS, EASE_POWERS[1:]):
        if weight <= w1:
            part = (weight - w0) / (w1 - w0)
            return math.exp(math.log(p0) + (math.log(p1) - math.log(p0)) * part)
    return EASE_POWERS[-1][1]


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


def _blend_ease(block: Block, weight: float, values: list) -> list:
    """Blend to Ease, measured on the reference to 0.001: with u = a key's place between the keys before and
    after (0 at the one before), left takes it toward the key before by 1 - u ** p, right toward the key after
    by 1 - (1 - u) ** p, p = 10 x |weight| - the keys near that neighbor nearly all the way, the far ones
    hardly. Without the neighbor on that side nothing moves."""
    side = block.before if weight < 0 else block.after
    if side is None or block.before is None or block.after is None or block.after[0] == block.before[0]:
        return values
    power = 10.0 * abs(weight)
    t0, t1 = block.before[0], block.after[0]
    out = []
    for time, value in zip(block.times, values):
        u = max(0.0, min(1.0, (time - t0) / (t1 - t0)))
        part = 1.0 - (u if weight < 0 else 1.0 - u) ** power
        out.append(value + (side[1] - value) * part)
    return out


def _infinity(near: "tuple | None", far: "tuple | None", time: float) -> "float | None":
    if near is None:
        return None
    if far is None or far[0] == near[0]:
        return near[1]
    return _line(far, near, time)


def _amplitude(block: Block) -> float:
    """The run's own range (measured); a run of one key (or flat) borrows its neighbors'."""
    spread = max(block.values) - min(block.values) if block.values else 0.0
    if spread <= 1e-9:
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
    if key == "gap":
        return _gap(block, weight)
    if key in STRUCTURE_MODES:              # adds / removes keys: scene.KeysDrag does it, not this
        return values
    if key == "ease":
        # the run is laid out anew between the UNPICKED keys around it - what it held doesn't count,
        # as on the reference: the knob alone (0) lines it up straight, the further out the stronger
        return _eased(block, weight)
    if weight == 0.0:
        return values
    if key == "neighbors":
        left = block.before[1] if block.before is not None else None
        right = block.after[1] if block.after is not None else None
        return [_toward_sides(value, left, right, weight) for value in values]
    if key == "default":
        return [_toward(value, block.default, weight) for value in values]
    if key == "frame":
        return [_toward_sides(value, block.frame_value, block.frame_value_right, weight) for value in values]
    if key == "blend_ease":
        return _blend_ease(block, weight, values)
    if key == "infinity":
        out = []
        for time, value in zip(block.times, values):
            # measured: left = the line of the keys AFTER the run, right = the line of those BEFORE it
            left = _infinity(block.after, block.after2, time)
            right = _infinity(block.before, block.before2, time)
            out.append(_toward_sides(value, left, right, weight))
        return out
    if key == "undo":
        if not block.undo_values or len(block.undo_values) != len(values):
            return values
        return [_toward(value, before, weight) for value, before in zip(values, block.undo_values)]
    if key == "buffer":
        if not block.buffer_values or len(block.buffer_values) != len(values):
            return values
        return [_toward(value, buffered, weight) for value, buffered in zip(values, block.buffer_values)]
    if key == "pull_push":
        start, end = block.anchors()
        out = []
        for time, value in zip(block.times, values):
            straight = _line(start, end, time)
            factor = 1.0 + (weight if weight < 0 else STRONG * weight)   # measured: pull to 0, push to 3x
            out.append(straight + (value - straight) * factor)
        return out
    if key == "scale_average":
        middle = (max(values) + min(values)) / 2.0      # measured: the middle of the range, not the mean
        return [_scale(value, middle, weight) for value in values]
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
        return [value + (value - target) * STRONG * weight for value, target in zip(values, smooth)]
    if key in ("time_offset", "stagger"):
        if block.evaluate is None:
            return values
        share = 1.0
        if key == "stagger":                 # measured: 1/3, 2/3, 3/3 of the shift for three objects
            share = (block.order + 1) / block.count if block.count > 0 else 1.0
        shift = weight * OFFSET_FRAMES * share
        return [float(block.evaluate(_wrapped(time - shift, block.cycle))) for time in block.times]
    if key == "noise_wave":
        amplitude = _amplitude(block) * abs(weight)
        if weight < 0:
            rng = random.Random(block.seed)
            return [value + amplitude * rng.uniform(-1.0, 1.0) for value in values]
        # measured: down, up, down ... starting from the first key
        return [value + amplitude * (-1.0 if index % 2 == 0 else 1.0) for index, value in enumerate(values)]
    if key == "connect":
        side = block.before if weight < 0 else block.after
        if side is None:
            return values
        # measured: the whole run moves as one, its first (last) key meeting the key before (after)
        edge = values[0] if weight < 0 else values[-1]
        delta = (side[1] - edge) * abs(weight)
        return [value + delta for value in values]
    raise KeyError(f"unknown slider mode: {key}")


def chain_ranks(nodes) -> dict:
    """{node (a long DAG path): its place root to tip} - for the stagger: by depth in the hierarchy (a
    chain's root first, its tip last), objects side by side by name. MEASURED on the reference: the
    order they were picked in doesn't count."""
    unique = sorted({node for node in nodes if node}, key=lambda node: (node.count("|"), node.rsplit("|", 1)[-1]))
    return {node: index for index, node in enumerate(unique)}


def split_runs(indices) -> list:
    """Picked key indices of one curve -> runs of consecutive ones ([1, 2, 3, 7] -> [[1, 2, 3], [7]])."""
    runs = []
    for index in sorted(set(int(i) for i in indices)):
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def _wrapped(time: float, cycle: "tuple | None") -> float:
    """A time folded back into the curve's span (first key .. last key), as a cycle."""
    if not cycle or cycle[1] <= cycle[0]:
        return time
    start, end = cycle
    return start + (time - start) % (end - start)


def block_from_keys(times, values, run, **extra) -> Block:
    """The Block of one run (key indices, consecutive) of a curve whose keys are `times` / `values`."""
    first, last = run[0], run[-1]

    def key(index):
        return (float(times[index]), float(values[index])) if 0 <= index < len(times) else None

    extra.setdefault("cycle", (float(times[0]), float(times[-1])) if len(times) > 1 else None)
    return Block(times=[float(times[i]) for i in run], values=[float(values[i]) for i in run],
                 before=key(first - 1), after=key(last + 1), before2=key(first - 2), after2=key(last + 2), **extra)
