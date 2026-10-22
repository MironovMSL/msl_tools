# tools/maya/animation/mirror.py
"""MIRROR as data (no Qt, no Maya): which side a control is on, which control a mirrored pose goes from and to,
and the sign each channel takes on the way.

MEASURED on the reference (Maya 2025, its buttons clicked with a real mouse; 2026-10-22), and ours does the same:
    MIRROR POSE      a selected control's pose goes, mirrored, onto its OPPOSITE (found by name: lf_ <-> rt_ ...);
                     both of a pair selected = they SWAP (each takes the other's, read before anything is written);
                     a control with no side (spine) is mirrored onto ITSELF
    MIRROR TO RIGHT  for every selected control's pair the RIGHT one takes the left one's pose (either side may be
    MIRROR TO LEFT   the one selected); the left one the right one's. Controls with no side are left alone
    MIRROR ALL KEYS  the same pairs, but the whole ANIMATION: the target's curves replaced by the source's, every
                     value and tangent angle with the channel's sign (tangent types kept); a channel the source has
                     no curve on loses the target's curve and takes the source's value
    THE SIGNS        one per channel (the reference keeps a table of them per control; "a rig that needs translateX
                     to go into translateY will never work" - so do we): translate and rotate from the two
                     controls' axes AT REST (a posed control - ry 170 - gave the same signs), scale and every other
                     attribute +1 (copied as it is). World-aligned pairs and a control on the middle line:
                     -tx ty tz rx -ry -rz; pairs mirrored with Maya's joint "Behavior": -tx -ty -tz rx ry rz.
The rule behind both: the mirror plane M (x -> -x for the X axis). A translate axis a of the source becomes M a,
so its channel's sign is the side M a lies on of the target's same axis b: round(M a . b). A rotation is a
pseudo-vector - mirrored it is -M a -, so the rotate channel's sign is the opposite one.
A frame here = three axis vectors (x, y, z), each a 3-tuple in the world.
"""
from __future__ import annotations

import re

LEFT, RIGHT, CENTER = "left", "right", "center"
TRANSLATE = ("translateX", "translateY", "translateZ")
ROTATE = ("rotateX", "rotateY", "rotateZ")
AXES = "XYZ"
POSE, TO_RIGHT, TO_LEFT = "pose", "right", "left"
# below this the two axes are no mirror of each other (a rig built otherwise): the sign is still the nearer one,
# but the channel is reported
ALIGNED = 0.7

_LEFT_WORDS = {"lf", "l", "left", "lft"}
_RIGHT_WORDS = {"rt", "r", "right", "rgt"}
_CAMEL = re.compile(r"(?:^(left|right|Left|Right)(?=[A-Z0-9]|$))|(?:(?<=[a-z0-9])(Left|Right)(?=[A-Z0-9]|$))")


def name_side(name: str, left_words=(), right_words=()) -> str:
    """LEFT / RIGHT / "" by the name alone: a whole "_" part that is a side word (lf_arm, arm_L, left_hand;
    the user's own side words too), else camelCase Left / Right (leftArm, armRight). No side word = ""."""
    short = name.split("|")[-1].split(":")[-1]
    lefts = _LEFT_WORDS | {word.lower() for word in left_words if word}
    rights = _RIGHT_WORDS | {word.lower() for word in right_words if word}
    for part in short.split("_"):
        lower = part.lower()
        if lower in lefts:
            return LEFT
        if lower in rights:
            return RIGHT
    match = _CAMEL.search(short)
    if match:
        return LEFT if (match.group(1) or match.group(2)).lower() == "left" else RIGHT
    return ""


def _reflect(vector, axis: str) -> tuple:
    index = AXES.index(axis)
    return tuple(-value if i == index else value for i, value in enumerate(vector))


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _unit(vector) -> tuple:
    length = _dot(vector, vector) ** 0.5
    return tuple(value / length for value in vector) if length > 1e-9 else (0.0, 0.0, 0.0)


def channel_signs(source_translate, target_translate, source_rotate=None, target_rotate=None,
                  axis: str = "X") -> tuple:
    """({channel: +1 / -1} for translate and rotate X Y Z, [channels whose axes are no mirror of each other]).
    `*_translate` = the frame the translate channels move along, `*_rotate` the frame the rotate channels turn
    about (a joint's orient lies between them); a rotate frame left out = the translate one."""
    source_rotate = source_rotate or source_translate
    target_rotate = target_rotate or target_translate
    signs, loose = {}, []
    for index in range(3):
        for channels, source, target, flip in ((TRANSLATE, source_translate, target_translate, 1),
                                               (ROTATE, source_rotate, target_rotate, -1)):
            dot = _dot(_reflect(_unit(source[index]), axis), _unit(target[index]))
            signs[channels[index]] = (1 if dot >= 0 else -1) * flip
            if abs(dot) < ALIGNED:
                loose.append(channels[index])
    return signs, loose


def sign_of(signs: dict, attribute: str) -> int:
    """The sign an attribute's value takes: from the table for translate / rotate, +1 for anything else."""
    return int(signs.get(attribute, 1)) or 1


def mirrored_row(row: list, sign: int) -> list:
    """A key row of transfer's format (time, value, in type, out type, in angle, out angle, ...) mirrored: the
    value and both tangent angles take the sign, everything else stays."""
    if sign == 1:
        return list(row)
    row = list(row)
    row[1] = -row[1]
    row[4] = -row[4]
    row[5] = -row[5]
    return row


def pairs(selected: list, opposite, side, mode: str = POSE) -> tuple:
    """([(source, target)], [selected nodes with no opposite]) for a mirror of `selected` (long names).
    `opposite(node)` -> its opposite's long name (the node itself for a middle control), "" when there is none;
    `side(node)` -> LEFT / RIGHT / CENTER.
    POSE: each selected onto its opposite, both of a pair selected = both ways (a swap), a middle one onto
    itself. TO_RIGHT / TO_LEFT: each pair once, from the left one to the right one (or back); middle ones left."""
    out, alone, seen = [], [], set()
    for node in selected:
        other = opposite(node)
        if not other:
            alone.append(node)
            continue
        if mode == POSE:
            pair = (node, other)            # the other of a selected pair adds the way back: a swap
        elif other == node or side(node) == CENTER:
            continue
        else:
            left, right = (node, other) if side(node) == LEFT else (other, node)
            pair = (left, right) if mode == TO_RIGHT else (right, left)
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out, alone


def describe(count: int, alone: int, what: str = "pose") -> str:
    text = f"Mirrored the {what} of {count} control{'s' if count != 1 else ''}"
    if alone:
        text += f" · {alone} without an opposite left"
    return text
