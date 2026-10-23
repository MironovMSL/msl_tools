# tools/maya/animation/space.py
"""ATTRIBUTE SPACE SWITCHER as data (no Qt, no Maya): the switches' names, and how good each rotate order would be
for an animation.

MEASURED on the reference (Maya 2025, its pop-ups clicked with a real mouse; 2026-10-23), and ours does the same:
    THE SWITCHES      of the SELECTED controls: every enum attribute of their own shown in the Channel Box (one that
                      drives nothing - "Fk Ik" - too) and the Rotate Order; the ASSET switcher lists the enum switches
                      of every control of the selection's rig, without the rotate order
    A VALUE PICKED    "Current key(s)" (Alt) = this frame: the value set and the control put back where it was in the
                      world (its rotate pivot and turn - move / turn channels; scale left); with Maya's auto key on the
                      switch and the channels already animated are keyed, off = values only. A highlighted span or
                      picked keys change nothing in this - the current frame only.
                      "All keys" (Ctrl) = on EVERY frame the control has a key on (its own keys only - not the space
                      target's): the switch keyed there with the new value and all six move / turn channels keyed so
                      it stays where it was on each of them
    ROTATE ORDER      all keys only: the order set (not keyed) and the turn kept on every key frame, rx / ry / rz keyed
                      there; each order rated Best / Good / OK / nothing
THE RATING is OURS: the gimbal risk of each order = the largest middle-axis angle over every frame from the
control's first key to its last; Best = the least of them (ties within TIE), Good under GOOD (30), OK under FAIR (45),
nothing from 45 on. The reference's own rule was NOT found: on 18 probes rated by it (108 ratings) this one agrees on
90 - every lone turn of the middle axis (30 / 40 = OK, 45 and more = nothing; orders it doesn't turn = Best) - and
differs on mixed turns, where no single measure (largest or mean middle angle, its share of the turn, at keys or on
every frame, in either Euler convention) separated its labels.
"""
from __future__ import annotations

import math
import re

ORDERS = ("xyz", "yzx", "zxy", "xzy", "yxz", "zyx")
GOOD, FAIR, TIE = 30.0, 45.0, 0.5
BEST, GOOD_LABEL, OK_LABEL = "Best", "Good", "OK"


def nice(attribute: str) -> str:
    """fkIk -> "Fk Ik", follow_space -> "Follow Space", rotateOrder -> "Rotate Order"."""
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", attribute).replace("_", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words)


# --------------------------------------------------------------------------- rotations (degrees, Maya's orders)

def _turn(axis: str, degrees: float) -> list:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    if axis == "x":
        return [[1, 0, 0], [0, c, s], [0, -s, c]]
    if axis == "y":
        return [[c, 0, -s], [0, 1, 0], [s, 0, c]]
    return [[c, s, 0], [-s, c, 0], [0, 0, 1]]


def _times(a, b) -> list:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def matrix(rotation, order: str) -> list:
    """The row-vector matrix of an Euler rotation (x, y, z degrees) in a rotate order, as Maya builds it (the first
    axis of the order turns first)."""
    values = dict(zip("xyz", rotation))
    result = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for axis in order:
        result = _times(result, _turn(axis, values[axis]))
    return result


def euler(m, order: str, near=None) -> tuple:
    """The (x, y, z) degrees of a rotation matrix in `order`; of its two solutions the one nearer `near`."""
    i, j, k = ("xyz".index(axis) for axis in order)
    sign = 1.0 if (j - i) % 3 == 1 else -1.0
    # m[i][k] = sign * sin(middle) for Maya's row-vector matrices with the first axis turning first
    middle = math.asin(max(-1.0, min(1.0, -sign * m[i][k])))
    if abs(math.cos(middle)) > 1e-9:
        first = math.atan2(sign * m[j][k], m[k][k])
        last = math.atan2(sign * m[i][j], m[i][i])
    else:
        first = math.atan2(-sign * m[k][j], m[j][j])
        last = 0.0
    solutions = [(first, middle, last), (first + math.pi, math.pi - middle, last + math.pi)]
    out = []
    for a, b, c in solutions:
        values = {}
        values[order[0]], values[order[1]], values[order[2]] = (math.degrees(a), math.degrees(b), math.degrees(c))
        out.append(tuple(values[axis] for axis in "xyz"))
    if near is None:
        return tuple(_wrap(v) for v in out[0])
    return min((_closest(candidate, near) for candidate in out), key=lambda c: sum(abs(x - y) for x, y in zip(c, near)))


def _wrap(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def _closest(values, near) -> tuple:
    return tuple(v + 360.0 * round((n - v) / 360.0) for v, n in zip(values, near))


def middle_angle(rotation, order: str, now: str = "xyz") -> float:
    """|the middle axis' angle| of a rotation (given in order `now`) put into `order` - 90 = gimbal locked."""
    values = euler(matrix(rotation, now), order)
    return abs(values["xyz".index(order[1])])


def rate_orders(frames: list, keys: list, now: str) -> dict:
    """{order: "Best" | "Good" | "OK" | ""} for an animation: `frames` = the rotation on every frame from the first
    key to the last (in the order `now`); `keys` is kept for callers that have no frames (one pose)."""
    frames = frames or keys
    worst = {order: max((middle_angle(r, order, now) for r in frames), default=0.0) for order in ORDERS}
    labels = {order: (GOOD_LABEL if value < GOOD else OK_LABEL if value < FAIR else "")
              for order, value in worst.items()}
    least = min(worst.values())
    for order, value in worst.items():
        if labels[order] and value <= least + TIE:
            labels[order] = BEST
    return labels
