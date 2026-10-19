# tools/maya/animation/keys.py
"""Keys and timing as arithmetic on key TIMES - no Maya, no Qt (keys_scene.py applies it to curves).

Every function takes plain lists of times (frames, in order) and says where keys go, or why not. The rules
were measured on the reference tool key for key (CLAUDE.md, Animation tool, phase 2):

    nudge          picked keys move by N; landing on another key replaces it, PASSING one refuses the lot
    inbetweens     N frames go in (or out) after each anchor: the current frame, each picked key, or every
                   key time inside a highlighted range; a removal that would reach the key before is refused
    spacing        the key times in play laid out N apart from the first ("Set Inbetween")
    bake           a grid from a start every N frames; keys off it inside the span go
    snap           to the nearest whole frame, half way going DOWN (8.5 -> 8); two on one frame = one
    paste times    merge / replace / insert key times copied from elsewhere
    infinity       the times a cycle's keys come back at inside a range
"""
from __future__ import annotations

import math

SAME = 1e-4            # two times this close are one
SEAM = 0.01            # frames before a plain cycle's seam where the ending key of a pass is put (the jump kept)

RED, YELLOW, GREEN = "red", "yellow", "green"
COLORS = (RED, YELLOW, GREEN)
COLOR_FLAGS = {RED: (False, False), YELLOW: (False, True), GREEN: (True, False)}   # (breakdown, tickDrawSpecial)


def same(a: float, b: float) -> bool:
    return abs(a - b) < SAME


def color_of(breakdown: bool, special: bool) -> str:
    """A key's color as the reference draws it: green = Maya's breakdown, yellow = its special tick, else red."""
    if breakdown:
        return GREEN
    return YELLOW if special else RED


# --------------------------------------------------------------------------- nudge

def nudge(times: list, picked: list, offset: float) -> "dict | None":
    """{index: new time} for the keys `picked` (indices into `times`) moved by `offset`, plus {index: None}
    for an unpicked key a moved one lands on exactly (it is replaced). None when a moved key would PASS an
    unpicked key (measured: the reference then moves nothing at all)."""
    chosen = set(picked)
    if not chosen or abs(offset) < SAME:
        return {}
    still = [(i, t) for i, t in enumerate(times) if i not in chosen]
    moves = {}
    for index in sorted(chosen):
        old, new = times[index], times[index] + offset
        low, high = min(old, new), max(old, new)
        for other, time in still:
            if low < time < high and not same(time, new):
                return None
        moves[index] = new
    landed = {new for new in moves.values()}
    for other, time in still:
        if any(same(time, new) for new in landed):
            moves[other] = None
    return moves


def nearest_key(all_times, now: float, direction: int) -> "float | None":
    """The key time nearest to `now` on one side (direction +1: after it, -1: before it), over all curves."""
    side = [t for t in all_times if (t - now) * direction > SAME]
    if not side:
        return None
    return min(side) if direction > 0 else max(side)


# --------------------------------------------------------------------------- inbetweens

def inbetween(times: list, anchors, amount: float) -> "list | None":
    """New times when `amount` frames go in after every anchor (negative: come out): a key moves by
    amount x the number of anchors BEFORE it. None when a removal would bring a key onto or past the one
    before it (measured: refused as a whole)."""
    anchors = sorted(anchors)
    new = [t + amount * sum(1 for a in anchors if t > a + SAME) for t in times]
    for before, after in zip(new, new[1:]):
        if after - before < SAME:
            return None
    return new


def spaced(times_in_play, step: float) -> dict:
    """{old time: new time}: the times in play (the union over curves, in order) laid out `step` apart from
    the first one ("Set Inbetween"); keys after them stay where they are."""
    ordered = sorted(set(round(t, 6) for t in times_in_play))
    if not ordered or step <= 0:
        return {}
    return {t: ordered[0] + i * step for i, t in enumerate(ordered)}


def remap(times: list, mapping: dict) -> "list | None":
    """`times` with every time found in `mapping` changed; None when the result is out of order or has two
    keys on one time (a key left behind by the spacing would be passed)."""
    new = []
    for t in times:
        hit = next((value for key, value in mapping.items() if same(key, t)), None)
        new.append(t if hit is None else hit)
    for before, after in zip(new, new[1:]):
        if after - before < SAME:
            return None
    return new


# --------------------------------------------------------------------------- bake

def bake_grid(start: float, end: float, step: float) -> list:
    """start, start + step, ... up to end (the end itself only when the grid reaches it)."""
    if step <= 0 or end < start:
        return []
    count = int(math.floor((end - start) / step + SAME))
    return [round(start + i * step, 6) for i in range(count + 1)]


def bake_plan(times: list, start: float, end: float, step: float) -> tuple:
    """(times to key, indices to remove) for baking a curve on `step` over [start, end]: the grid is keyed,
    keys inside the span that are off the grid go, keys outside stay."""
    grid = bake_grid(start, end, step)
    removed = [i for i, t in enumerate(times)
               if start - SAME <= t <= end + SAME and not any(same(t, g) for g in grid)]
    return grid, removed


# --------------------------------------------------------------------------- snap

def snap_frame(time: float) -> float:
    """The whole frame a key snaps to: the nearest, half way going down (measured: 8.5 -> 8, 4.5 -> 4)."""
    return float(math.ceil(time - 0.5 - 1e-9))


def snap_plan(times: list, candidates=None) -> dict:
    """{frame: [indices]} of the keys that are not on a whole frame (or all of `candidates`), grouped by the
    frame they snap to; a key already on that frame joins its group (one key per frame stays)."""
    indices = range(len(times)) if candidates is None else candidates
    groups: dict = {}
    for index in indices:
        t = times[index]
        if same(t, round(t)):
            continue
        groups.setdefault(snap_frame(t), []).append(index)
    for frame, members in groups.items():
        for index, t in enumerate(times):
            if same(t, frame) and index not in members:
                members.append(index)
    return groups


# --------------------------------------------------------------------------- key times copied

MERGE, REPLACE, INSERT = "merge", "replace", "insert"


def paste_times(copied, times: list, mode: str, now: float = 0.0) -> tuple:
    """(times to key, indices to remove) for pasting `copied` key times onto a curve with `times`:
    merge = they are added; replace = added, and keys INSIDE their span that are not on one of them go
    (keys outside stay); insert = replace with the copied times shifted so the first is `now`."""
    copied = sorted(set(round(t, 6) for t in copied))
    if not copied:
        return [], []
    if mode == INSERT:
        copied = [round(t - copied[0] + now, 6) for t in copied]
    removed = []
    if mode in (REPLACE, INSERT):
        low, high = copied[0], copied[-1]
        removed = [i for i, t in enumerate(times)
                   if low - SAME <= t <= high + SAME and not any(same(t, c) for c in copied)]
    added = [c for c in copied if not any(same(c, t) for t in times)]
    return added, removed


def union(*time_lists) -> list:
    out = []
    for times in time_lists:
        for t in times:
            if not any(same(t, o) for o in out):
                out.append(t)
    return sorted(out)


# --------------------------------------------------------------------------- infinity

CONSTANT, LINEAR, CYCLE, CYCLE_OFFSET, OSCILLATE = 0, 1, 3, 4, 5   # Maya's preInfinity / postInfinity values


def infinity_times(times: list, start: float, end: float, pre: int, post: int) -> list:
    """[(time, source index, pass)] of the keys a cycling curve repeats inside [start, end]: pass 0 is the
    curve itself (not listed), -1 / +1 ... the passes before / after it. Oscillate runs every other pass
    backwards (the source index then counts from the end). Constant and linear infinity repeat nothing."""
    if len(times) < 2:
        return []
    first, last = times[0], times[-1]
    period = last - first
    if period < SAME:
        return []
    out = []
    for direction, kind in ((-1, pre), (1, post)):
        if kind not in (CYCLE, CYCLE_OFFSET, OSCILLATE):
            continue
        n = 1
        while True:
            shift = direction * n * period
            if (direction < 0 and last + shift < start - SAME) or (direction > 0 and first + shift > end + SAME):
                break
            backwards = kind == OSCILLATE and n % 2 == 1
            for i, t in enumerate(times):
                source = len(times) - 1 - i if backwards else i
                time = (first + last - t if backwards else t) + shift
                if start - SAME <= time <= end + SAME:
                    out.append((round(time, 6), source, direction * n))
            n += 1
            if n > 10000:
                break
    return sorted(out)


def infinity_keys(times: list, values: list, start: float, end: float, pre: int, post: int) -> list:
    """[(time, value, source index)] of the real keys that bake a cycling curve's infinity into [start, end].
    A pass's value is its source key's, plus the curve's rise per pass for cycle with offset. Where two passes
    meet on one time (a seam) with DIFFERENT values - a plain cycle of a curve that doesn't end where it began -
    the key of the pass farther out is put SEAM frames farther out, so the jump stays a jump (the reference
    keeps it with two keys 0.0001 apart); with equal values one key is enough. Keys already on the curve
    are not listed."""
    rise = values[-1] - values[0] if values else 0.0
    keys = []
    for time, source, n in infinity_times(times, start, end, pre, post):
        kind = post if n > 0 else pre
        value = values[source] + (rise * n if kind == CYCLE_OFFSET else 0.0)
        keys.append((time, value, source, n))
    taken = [(t, v, 0) for t, v in zip(times, values)]
    out = []
    for time, value, source, n in sorted(keys, key=lambda k: abs(k[3])):
        clash = next((other for other in taken if same(other[0], time)), None)
        if clash is not None:
            if abs(clash[1] - value) < 1e-6:
                continue
            time = round(time + (SEAM if n > 0 else -SEAM), 6)
        taken.append((time, value, n))
        out.append((time, value, source))
    return sorted(out)
