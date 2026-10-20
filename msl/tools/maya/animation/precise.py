# tools/maya/animation/precise.py
"""Precise − / +: values changed by an exact step — measured on the reference (Maya 2025, 2026-10-20):

    picked KEYS (anywhere: the Graph Editor need not be on screen)   -> each key's value ± the step
    channels picked in the CHANNEL BOX (any section, on the objects it lists):
        not animated                     -> the value ± the step
        animated, a key on this frame    -> that key's value ± the step
        animated, no key on this frame   -> left alone (no key is added, autokey or not)
Both at once are both done, but a curve whose picked key is on this frame changes once, not twice.
The step is in the channel's own units (a rotation: degrees), the tangents stay as they are.
Nothing picked anywhere = nothing (the reference does nothing either). One undo step.

The step's size: the reference's modifiers on its − / + buttons give a tenth of the field (Ctrl+Shift = +,
Ctrl+Alt = −) or five times it (Shift+Alt = +, Ctrl+Shift+Alt = −), Ctrl alone = −, Shift alone = +. Ours keep the
button's own sign: Ctrl = FINE (a tenth), Shift = COARSE (five times); hotkeys for each of the six.
"""
from __future__ import annotations

from maya import cmds

UNDO_NAME = "MSL Precise"


def _picked_keys() -> dict:
    """{curve: [times]} of every picked key (time curves only)."""
    picked = {}
    for curve in cmds.keyframe(query=True, name=True, selected=True) or []:
        if not cmds.nodeType(curve).startswith(("animCurveTA", "animCurveTL", "animCurveTU", "animCurveTT")):
            continue
        times = cmds.keyframe(curve, query=True, selected=True, timeChange=True) or []
        if times:
            picked[curve] = [float(t) for t in times]
    return picked


def _curve_of(plug: str) -> str:
    """The anim curve feeding `plug` directly ("" = none - also when something else drives it)."""
    sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    for source in sources:
        if cmds.nodeType(source).startswith("animCurveT"):
            return source
    return ""


def _driven(plug: str) -> bool:
    sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    return any(not cmds.nodeType(source).startswith("animCurve") for source in sources)


def precise(step: float, times: float = 1.0, say: bool = False) -> str:
    """Adds `step` x `times` (negative = takes it off) to the picked keys and the Channel Box's picked channels
    (`times`: FINE / COARSE / 1)."""
    from msl_tools.msl.tools.maya.scripts.reset_attributes import picked_channels
    from msl_tools.msl.tools.maya.animation.keys_scene import _done
    step = float(step) * float(times)
    keys = _picked_keys()
    channels = picked_channels()
    if not keys and not channels:
        return _done("Nothing picked: pick channels in the Channel Box or keys in the Graph Editor", say)
    now = float(cmds.currentTime(query=True))
    changed_keys, changed_values, left = 0, 0, 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for curve, times in keys.items():
            for time in times:
                cmds.keyframe(curve, edit=True, time=(time, time), relative=True, valueChange=step)
                changed_keys += 1
        for node, attribute in channels:
            plug = f"{node}.{attribute}"
            try:
                if not cmds.attributeQuery(attribute.split("[")[0], node=node, exists=True) or \
                        cmds.getAttr(plug, lock=True) or _driven(plug):
                    left += 1
                    continue
                curve = _curve_of(plug)
                if curve:
                    if curve in keys and any(abs(t - now) < 1e-6 for t in keys[curve]):
                        continue                      # its key here has just been changed
                    if not cmds.keyframe(curve, query=True, time=(now, now), keyframeCount=True):
                        left += 1                     # animated, no key here: the reference leaves it
                        continue
                    cmds.keyframe(curve, edit=True, time=(now, now), relative=True, valueChange=step)
                    changed_keys += 1
                    continue
                value = cmds.getAttr(plug)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    left += 1
                    continue
                cmds.setAttr(plug, value + step)
                changed_values += 1
            except (RuntimeError, ValueError, TypeError):
                left += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    if not (changed_keys or changed_values):
        return _done("Nothing changed: the picked channels have no key on this frame (or are locked / driven)", say)
    parts = []
    if changed_keys:
        parts.append(f"{changed_keys} key{'s' if changed_keys != 1 else ''}")
    if changed_values:
        parts.append(f"{changed_values} value{'s' if changed_values != 1 else ''}")
    text = f"Precise {'+' if step > 0 else '−'}{abs(step):g}: " + ", ".join(parts)
    if left:
        text += f" · {left} left (no key here, locked or driven)"
    return _done(text, say)
