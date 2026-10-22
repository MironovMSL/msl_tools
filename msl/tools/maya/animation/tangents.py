# tools/maya/animation/tangents.py
"""The Animation tool's TANGENTS as arithmetic on one curve's keys (no Qt, no Maya).

Slopes are in the curve's own units per frame (Maya's tangent angle = atan(slope), degrees). A key's
tangents are (in, out). What each tool does was MEASURED on the reference (Maya 2025, 2026-10-22):

    BEST GUESS   the first and the last key of the curve, and every strict extreme (both neighbors on one
                 side of it) -> clamped; every other key -> auto. Native types, nothing computed.
    BOUNCE       each side of a key points at its neighbor: straight at it when that neighbor's facing side is
                 bounced too (the whole selection = straight lines between the keys); else the END RULE with
                 the neighbor's tangent as it is. The curve's first key: in = linear; the last: out = linear.
    POLISHED     Flow's kernel and bounds made 4/3 as strong on the monotonic keys, a limit where one side is far
                 steeper, Maya's spline on extremes (limited too past a ratio), holds flat, the END RULE on the
                 curve's ends, Maya's spline on their outer side - see `polished_slopes`. MEASURED: exact on evenly
                 spaced curves; the extremes' limit is a measured curve (no formula found).
    FLOW         every key fixed, momentum carried forward: a kernel of the chord slopes around each key, held by
                 two bounds where the curve runs nearly straight - see `flow_slopes`. MEASURED: exact on evenly
                 spaced and random curves; a few hundredths off on some keys of nearly straight uneven runs.
    CYCLE MATCH  the curve's last key takes the first key's tangent (in AND out = the first key's in); with
                 Shift the first key takes the last key's (its out).

    END RULE     a side facing a neighbor whose own facing tangent m stays: (13 d - 4 m) / 9, d = the straight
                 slope to that neighbor - measured exact (to 0.0001) on bounce and on polished ends alike.

Which keys: `chosen` (indices) and `sides` ("in" / "out" / both). The options of the reference's right click
(First Key / Last Key / Both Ends / All Keys) only change `chosen`: see `option_indices`.
"""
from __future__ import annotations

import math

FIXED, LINEAR, AUTO, CLAMPED, SPLINE = "fixed", "linear", "auto", "clamped", "spline"
NATIVE = ("auto", "spline", "clamped", "linear", "flat", "step", "plateau")
OPTIONS = ("selected", "first", "last", "both", "all")
SIDES = ("both", "in", "out")


def angle(slope: float) -> float:
    return math.degrees(math.atan(slope))


def slope(angle_degrees: float) -> float:
    return math.tan(math.radians(angle_degrees))


def blend_angle(now: float, target: float, weight: float) -> float:
    """The tangent slider (measured): the ANGLE (degrees) moves from `now` toward `target` by `weight` - past it
    with overshoot, away from it on the left -, held to +-90."""
    return max(-90.0, min(90.0, now + weight * (target - now)))


def end_rule(d: float, m: float) -> float:
    """The tangent of a side facing a neighbor whose own facing tangent `m` stays (measured: 13/9 and 4/9).
    Toward a hold (d = 0) it is flat (measured: a hold's side stayed 0 where the formula alone gave 20 degrees);
    otherwise it is taken as it comes, also against the way to the neighbor (measured on Polished's ends)."""
    if abs(d) < 1e-12:
        return 0.0
    return (13.0 * d - 4.0 * m) / 9.0


def _segment(times, values, i: int, j: int) -> float:
    span = times[j] - times[i]
    return (values[j] - values[i]) / span if span else 0.0


def is_extreme(values, i: int) -> bool:
    """Strictly above or below BOTH neighbors (an end key is no extreme)."""
    if i <= 0 or i >= len(values) - 1:
        return False
    a, b, c = values[i - 1], values[i], values[i + 1]
    return (b > a and b > c) or (b < a and b < c)


def is_hold(values, i: int) -> bool:
    """Equal to a neighbor (part of a hold)."""
    return any(0 <= j < len(values) and abs(values[j] - values[i]) < 1e-9 for j in (i - 1, i + 1))


def is_extreme_past_hold(values, i: int) -> bool:
    """Polished's extreme (measured): a neighbor EQUAL to the key is looked past, ONE key further, then strictly
    above / below both - so a two-key top (0 10 10 0) counts, a three-key one (0 5 5 5 0) doesn't."""
    if i <= 0 or i >= len(values) - 1:
        return False
    here = values[i]
    if abs(values[i - 1] - here) < 1e-9 and abs(values[i + 1] - here) < 1e-9:
        return False                               # inside a hold (measured: the middle of 0 5 5 5 0 goes flat)

    def neighbor(step: int):
        j = i + step
        if abs(values[j] - here) < 1e-9:
            j += step
        return values[j] if 0 <= j < len(values) else None

    a, c = neighbor(-1), neighbor(1)
    if a is None or c is None:
        return False
    return (here > a and here > c) or (here < a and here < c)


def option_indices(count: int, chosen, option: str) -> list:
    """The keys a tool acts on for a right-click option: "selected" = `chosen`, "first" / "last" / "both" = the
    curve's own end keys, "all" = every key."""
    if count <= 0:
        return []
    if option == "first":
        return [0]
    if option == "last":
        return [count - 1]
    if option == "both":
        return sorted({0, count - 1})
    if option == "all":
        return list(range(count))
    return sorted(i for i in set(chosen) if 0 <= i < count)


def _wants(sides: str, side: str) -> bool:
    return sides in ("both", side)


def best_guess(values) -> list:
    """The type each key gets: clamped (ends, strict extremes) or auto."""
    last = len(values) - 1
    return [CLAMPED if i in (0, last) or is_extreme(values, i) else AUTO for i in range(len(values))]


def bounce(times, values, chosen, ins, outs, sides: str = "both") -> dict:
    """{index: (in, out)} - each a (type, slope) or None for a side left as it is. `ins` / `outs` = the slopes
    the keys have now."""
    count = len(times)
    picked = set(chosen)
    result = {}
    for i in sorted(picked):
        new_in = new_out = None
        if _wants(sides, "in"):
            if i == 0:
                new_in = (LINEAR, 0.0)
            else:
                d = _segment(times, values, i - 1, i)
                straight = (i - 1) in picked and _wants(sides, "out")
                new_in = (FIXED, d if straight else end_rule(d, outs[i - 1]))
        if _wants(sides, "out"):
            if i == count - 1:
                new_out = (LINEAR, 0.0)
            else:
                d = _segment(times, values, i, i + 1)
                straight = (i + 1) in picked and _wants(sides, "in")
                new_out = (FIXED, d if straight else end_rule(d, ins[i + 1]))
        result[i] = (new_in, new_out)
    return result


POLISH_STEEP = 25.0 / 17.0                         # the measured constant of Polished's limit (see `polish_root`)
POLISH_EXTREME = 83.0 / 17.0                       # an extreme is limited past this ratio of its two rises
# Polished's limit of an extreme, MEASURED (no closed form found): (ratio of the big rise to the small one, the
# tangent in small rises per mean interval). Read between points as linear in 1 / ratio; past the last it runs
# into POLISH_STEEP.
POLISH_EXTREME_CURVE = (
    (83.0 / 17.0, 33.0 / 17.0), (4.885, 1.9013), (4.89, 1.8749), (4.895, 1.8573), (4.9, 1.84338), (5.0, 1.71997),
    (5.1, 1.66277), (5.25, 1.60963), (5.5, 1.5564), (5.75, 1.52351), (6.0, 1.50103), (6.5, 1.47284),
    (7.0, 1.45653), (7.5, 1.44645), (8.0, 1.44004), (9.0, 1.43325), (10.0, 1.43059), (11.0, 1.42995),
    (12.0, 1.43033), (14.0, 1.43235), (16.0, 1.4348), (18.0, 1.43731), (20.0, 1.43962), (25.0, 1.4444),
    (30.0, 1.44801), (40.0, 1.453), (50.0, 1.45621), (70.0, 1.46008), (100.0, 1.46309), (150.0, 1.46551),
    (250.0, 1.46754), (500.0, 1.46903), (1000.0, 1.4698))


def polish_root(small: float, big: float) -> float:
    """Polished's limit of a monotonic key between a small rise and a big one (both > 0, in value per key):
    the smaller root of m (S - m) = 25/17 small S, S = small + big (measured exact to 1e-5); where it has none,
    S / 2."""
    total = small + big
    disc = total * total - 4.0 * POLISH_STEEP * small * total
    return (total - math.sqrt(max(disc, 0.0))) / 2.0


def polish_extreme(ratio: float) -> float:
    """The measured curve POLISH_EXTREME_CURVE at `ratio` (> POLISH_EXTREME)."""
    curve = POLISH_EXTREME_CURVE
    if ratio >= curve[-1][0]:
        last, value = curve[-1]
        return POLISH_STEEP + (value - POLISH_STEEP) * last / ratio
    for (r0, g0), (r1, g1) in zip(curve, curve[1:]):
        if r0 <= ratio <= r1:
            part = (1.0 / ratio - 1.0 / r0) / (1.0 / r1 - 1.0 / r0)
            return g0 + (g1 - g0) * part
    return curve[0][1]


def _polish_limited(times, values, i: int):
    """Polished's limit for key `i`, or None where it doesn't bite (measured, Maya 2025). Worked out on the RISES
    of the two segments, the result per frame of their mean interval. A monotonic key: when the steeper side is
    steep enough - small side on the left: 3 d_big h_big > (10 h_big + 7 h_small) d_small; on the right:
    12 d_big h_big >= (35 h_big + 28 h_small) d_small (slopes d, intervals h). An extreme: once the big rise is
    more than 83/17 times the small one; it then points along the big side."""
    left_h, right_h = times[i] - times[i - 1], times[i + 1] - times[i]
    if not left_h or not right_h:
        return None
    rise_l, rise_r = values[i] - values[i - 1], values[i + 1] - values[i]
    mean = (left_h + right_h) / 2.0
    small, big = sorted((abs(rise_l), abs(rise_r)))
    if rise_l * rise_r > 0:
        a, b = abs(rise_l / left_h), abs(rise_r / right_h)
        if a < b:
            steep = 3.0 * b * right_h > (10.0 * right_h + 7.0 * left_h) * a
        else:
            steep = 12.0 * a * left_h >= (35.0 * left_h + 28.0 * right_h) * b
        if not steep:
            return None
        return math.copysign(polish_root(small, big), rise_l) / mean
    if rise_l * rise_r < 0 and small > 0 and big > POLISH_EXTREME * small:
        along = rise_r if abs(rise_r) > abs(rise_l) else rise_l
        return math.copysign(polish_extreme(big / small) * small, along) / mean
    return None


TOP_SMALL = 1.0 / 3.0                              # the step inside a two-key top: at most this part of either side
TOP_BALANCE = (0.65, 1.55)                         # the two sides of a two-key top: how much one may differ


def two_key_top(times, values, i: int) -> bool:
    """Keys i and i + 1 make ONE top or bottom: the curve rises into i, takes a small step (rises, not slopes: measured closer) (or none) to i + 1 and
    falls after it, and the two sides are about as big. Polished gives both Maya's spline then (measured: 0 10 10
    0 and a step of 1 between sides of 6 and 8 alike); a lopsided pair is two keys of their own (a hold flat, a
    big drop next to a tiny step limited). The band TOP_BALANCE is FITTED to the measurements, not found exact:
    the reference's own rule for it was not found (sides 5 and 6 around a step of 1 fall outside it there)."""
    if i < 1 or i + 2 >= len(values):
        return False
    rise_in, step, rise_out = (values[j + 1] - values[j] for j in (i - 1, i, i + 1))
    if rise_in * rise_out >= 0 or abs(step) > TOP_SMALL * min(abs(rise_in), abs(rise_out)):
        return False
    balance = abs(rise_out) / abs(rise_in)
    return TOP_BALANCE[0] <= balance <= TOP_BALANCE[1]


def polished_slopes(times, values) -> list:
    """Polished's (type, slope) for every key between the ends (see `polished` for the ends). MEASURED on the
    reference (Maya 2025, 2026-10-22), exact on evenly spaced curves: an extreme (`is_extreme_past_hold`) gets
    Maya's spline - unless one side rises far more than the other: then its measured limit (`_polish_limited`);
    a hold goes flat; a monotonic key: the limit where one side is far steeper, else Flow's kernel held by bounds
    like Flow's but 4/3 as strong - left 14/9 d[i-1] - 4/9 m[i-1] - 11/18 F, right 14/9 d[i] - 4/9 m'[i+1] -
    11/18 F (m = the key before as it is now, m' = the key after before its turn; the curve's ends count with
    their chord); F between them stays, beyond both the nearer bound weighted by the interval on its side."""
    n = len(times)
    h = [times[j + 1] - times[j] or 1e-9 for j in range(n - 1)]
    d = [(values[j + 1] - values[j]) / h[j] for j in range(n - 1)]
    kinds = [FIXED] * n
    base = [flow_kernel(times, values, i) for i in range(n)]
    base[0], base[-1] = d[0], d[-1]
    limits = [None] * n
    for i in range(1, n - 1):
        if not is_hold(values, i):
            limits[i] = _polish_limited(times, values, i)
    paired = set()
    for i in range(1, n - 2):                      # a top / bottom two keys wide: both spline (see `two_key_top`)
        if two_key_top(times, values, i):
            paired.update((i, i + 1))
            limits[i] = limits[i + 1] = SPLINE
    settled = set()
    for i in range(1, n - 1):
        if i not in paired and is_hold(values, i):
            base[i] = 0.0                          # a hold goes flat (measured)
        elif limits[i] == SPLINE or (limits[i] is None and is_extreme(values, i)):
            kinds[i] = SPLINE
            base[i] = (values[i + 1] - values[i - 1]) / ((times[i + 1] - times[i - 1]) or 1e-9)
        elif limits[i] is not None:
            base[i] = limits[i]
        else:
            continue
        settled.add(i)
    result = list(base)
    for i in range(1, n - 1):
        if i in settled:
            continue
        own = base[i]
        left = 14.0 / 9.0 * d[i - 1] - 4.0 / 9.0 * result[i - 1] - 11.0 / 18.0 * own
        right = 14.0 / 9.0 * d[i] - 4.0 / 9.0 * base[i + 1] - 11.0 / 18.0 * own
        if min(left, right) <= own <= max(left, right):
            continue
        result[i] = left if abs(own - left) * h[i - 1] <= abs(own - right) * h[i] else right
    return list(zip(kinds, result))


def polished(times, values, chosen, ins, outs, sides: str = "both") -> dict:
    """{index: (in, out)} as `bounce`: `polished_slopes` on the keys between, worked out on the whole curve; the
    curve's ends get the END RULE on the side facing the curve and Maya's spline on the outer side."""
    count = len(times)
    picked = set(chosen)
    final_in, final_out = list(ins), list(outs)
    result = {}
    if count < 2:
        return result
    slopes = polished_slopes(times, values) if count > 2 else []
    for i in sorted(picked):
        if i in (0, count - 1):
            continue
        new = slopes[i]
        new_in = new if _wants(sides, "in") else None
        new_out = new if _wants(sides, "out") else None
        if new_in:
            final_in[i] = new[1]
        if new_out:
            final_out[i] = new[1]
        result[i] = (new_in, new_out)
    last = count - 1
    if 0 in picked:
        result[0] = ((SPLINE, 0.0) if _wants(sides, "in") else None,
                     (FIXED, end_rule(_segment(times, values, 0, 1), final_in[1])) if _wants(sides, "out") else None)
    if last in picked:
        entry = result.get(last, (None, None))
        result[last] = ((FIXED, end_rule(_segment(times, values, last - 1, last), final_out[last - 1]))
                        if _wants(sides, "in") else entry[0],
                        (SPLINE, 0.0) if _wants(sides, "out") else entry[1])
    return result


def flow_kernel(times, values, i: int) -> float:
    """The slope Flow starts from at key `i` (measured, exact on every key the bounds leave alone): the chord
    slopes d around the key, one more on each side, the curve held flat outside its keys. With even spacing
    (-d[i-2] + 5 d[i-1] + 3 d[i] + d[i+1]) / 8 - momentum carried forward: the curvature at the key before and
    the key after adds to the average of the two chords. Uneven spacing: c = 2 h[i] / (h[i-1] + h[i]),
    (-(2 - c) d[i-2] + (8 - 3c) d[i-1] + (2 + c) d[i] + c (2 h[i+1] / h[i] - 1) d[i+1]) / 8; at the curve's
    ends the missing interval counts as the one beside it."""
    n = len(times)
    h = [times[j + 1] - times[j] or 1e-9 for j in range(n - 1)]
    d = [(values[j + 1] - values[j]) / h[j] for j in range(n - 1)]

    def chord(j):
        return d[j] if 0 <= j < len(d) else 0.0

    def span(j):
        return h[max(0, min(len(h) - 1, j))]

    left, right = span(i - 1), span(i)
    if i == 0:
        left = right
    if i == n - 1:
        right = left
    c = 2.0 * right / (left + right)
    ratio = span(i + 1) / right if i + 1 < len(h) else 1.0
    return (-(2.0 - c) * chord(i - 2) + (8.0 - 3.0 * c) * chord(i - 1) + (2.0 + c) * chord(i)
            + c * (2.0 * ratio - 1.0) * chord(i + 1)) / 8.0


def flow_slopes(times, values) -> list:
    """Flow's slope on every key (measured on the reference, 2026-10-22). The kernel `flow_kernel` (F), then,
    from the second key to the one before last, left to right, two bounds:
        left  = 7/6 d[i-1] - 1/3 m[i-1] - 5/24 F[i]    (m[i-1] = the key before, as Flow already left it)
        right = 7/6 d[i]   - 1/3 F[i+1] - 5/24 F[i]    (the key after, not yet done)
    F between them stays; F beyond both takes the bound nearer to it, each distance weighted by the interval on
    its side (h[i-1] / h[i]). The bounds bite where the curve runs nearly straight (a straight line: 0.5 on the
    ends, ~0.72 between). Exact on every key of evenly spaced curves and random uneven ones; NOT FOUND: a key
    after one that its LEFT bound held, where the spacing before them changes (~5 % of keys of nearly straight,
    unevenly spaced runs - there ours is a few hundredths off)."""
    n = len(times)
    if n < 2:
        return [0.0] * n
    h = [times[j + 1] - times[j] or 1e-9 for j in range(n - 1)]
    d = [(values[j + 1] - values[j]) / h[j] for j in range(n - 1)]
    base = [flow_kernel(times, values, i) for i in range(n)]
    result = list(base)
    for i in range(1, n - 1):
        own = base[i]
        left = 7.0 / 6.0 * d[i - 1] - result[i - 1] / 3.0 - 5.0 / 24.0 * own
        right = 7.0 / 6.0 * d[i] - base[i + 1] / 3.0 - 5.0 / 24.0 * own
        if min(left, right) <= own <= max(left, right):
            continue
        result[i] = left if abs(own - left) * h[i - 1] <= abs(own - right) * h[i] else right
    return result


def flow(times, values, chosen, sides: str = "both") -> dict:
    """{index: (in, out)}: Flow's slope on each picked key (fixed), worked out on the whole curve."""
    slopes = flow_slopes(times, values)
    return {i: ((FIXED, slopes[i]) if _wants(sides, "in") else None,
                (FIXED, slopes[i]) if _wants(sides, "out") else None) for i in sorted(set(chosen))}


def cycle_match(count: int, ins, outs, to_first: bool = False) -> dict:
    """{index: (in, out)}: the last key takes the first key's IN tangent on both sides (measured); `to_first` =
    the first key takes the last key's OUT."""
    if count < 2:
        return {}
    if to_first:
        m = outs[count - 1]
        return {0: ((FIXED, m), (FIXED, m))}
    m = ins[0]
    return {count - 1: ((FIXED, m), (FIXED, m))}
