# tools/maya/animation/space_scene.py
"""ATTRIBUTE SPACE SWITCHER in the scene (the rules and the measurements: space.py).

A switch is an enum attribute of a control shown in the Channel Box (+ the rotate order, for the selection's
switcher). Switching keeps the control where it was in the WORLD: its rotate pivot and turn are read before, the
switch is set, and align_scene.put_to puts it back by its own move / turn channels. One undo step ("MSL Space").
"""
from __future__ import annotations

from dataclasses import dataclass

from maya import cmds

from msl_tools.msl.tools.maya.animation import align_scene as al
from msl_tools.msl.tools.maya.animation import keys_scene
from msl_tools.msl.tools.maya.animation import scene
from msl_tools.msl.tools.maya.animation import space as sp
from msl_tools.msl.tools.maya.animation import transfer_scene as ts

UNDO_NAME = "MSL Space"
ROTATE_ORDER = "rotateOrder"
MOVE_TURN = ("translate", "rotate")
ROTATES = ("rotateX", "rotateY", "rotateZ")
CONTROLS_AT_MOST = 400


@dataclass
class Switch:
    node: str            # long name
    attribute: str       # "space" / "rotateOrder"
    names: list          # the values' names
    current: int

    @property
    def title(self) -> str:
        return f"{self.node.split('|')[-1]} {sp.nice(self.attribute)}"


# --------------------------------------------------------------------------- finding them

def _enum_switches(node: str) -> list:
    found = []
    attributes = (cmds.listAttr(node, userDefined=True, keyable=True) or []) + \
        (cmds.listAttr(node, userDefined=True, channelBox=True) or [])
    for attribute in dict.fromkeys(attributes):
        plug = f"{node}.{attribute}"
        try:
            if cmds.attributeQuery(attribute, node=node, attributeType=True) != "enum" or cmds.getAttr(plug, lock=True):
                continue
            names = (cmds.attributeQuery(attribute, node=node, listEnum=True) or [""])[0].split(":")
        except RuntimeError:
            continue
        if len(names) < 2:          # a separator line, not a switch
            continue
        found.append(Switch(node, attribute, [n.split("=")[0] for n in names], int(cmds.getAttr(plug))))
    return found


def selection_switches() -> list:
    """The selected controls' switches: their enum attributes and their rotate order."""
    out = []
    for node in scene.selected_objects():
        if not cmds.objectType(node, isAType="transform"):
            continue
        out += _enum_switches(node)
        if not cmds.getAttr(f"{node}.{ROTATE_ORDER}", lock=True):
            out.append(Switch(node, ROTATE_ORDER, list(sp.ORDERS), int(cmds.getAttr(f"{node}.{ROTATE_ORDER}"))))
    return out


def asset_of(node: str) -> tuple:
    """(the rig's name, its controls): everything under the top of the node's hierarchy - or, for a control at the
    top of the scene, the controls of its namespace - that has curve shapes."""
    top = node.split("|")[1] if node.startswith("|") else node
    namespace = top.rpartition(":")[0]
    if cmds.listRelatives(f"|{top}", children=True, type="transform"):
        candidates = cmds.listRelatives(f"|{top}", allDescendents=True, type="transform", fullPath=True) or []
        candidates.append(f"|{top}")
        name = top.split(":")[-1]
    else:
        candidates = cmds.ls(f"{namespace}:*" if namespace else "*", type="transform", long=True) or []
        name = namespace or node.split("|")[-1].split(":")[-1].split("_")[0]
    controls = [c for c in candidates if cmds.listRelatives(c, shapes=True, type="nurbsCurve")]
    return name, sorted(controls)[:CONTROLS_AT_MOST]


def asset_switches() -> tuple:
    """(the rig's name, the enum switches of every control of the selection's rig) - no rotate orders."""
    objects = scene.selected_objects()
    if not objects:
        return "", []
    name, controls = asset_of(objects[0])
    out = []
    for control in controls:
        out += _enum_switches(control)
    return name, out


# --------------------------------------------------------------------------- switching

def _key_times(node: str) -> list:
    return sorted({round(t, 6) for curve in ts._curves(node).values()
                   for t in (cmds.keyframe(curve, query=True, timeChange=True) or [])})


def _place(node: str):
    import maya.api.OpenMaya as om
    matrix = al.pivot_matrix(node)
    return al._turn(matrix), om.MPoint(matrix[12], matrix[13], matrix[14])


def switch(node: str, attribute: str, value: int, all_keys: bool = False, say: bool = False) -> str:
    """The switch set to `value` with the control kept where it is: on this frame (auto key: the switch and the
    animated channels keyed), or keyed on every key frame of the control."""
    if attribute == ROTATE_ORDER:
        return rotate_order(node, value, say)
    plug = f"{node}.{attribute}"
    names = (cmds.attributeQuery(attribute, node=node, listEnum=True) or [""])[0].split(":")
    label = f"{node.split('|')[-1]} {sp.nice(attribute)} = {names[value].split('=')[0] if value < len(names) else value}"
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        if not all_keys:
            turn, point = _place(node)
            cmds.setAttr(plug, value)
            done = al.put_to(node, turn, point, MOVE_TURN)
            if cmds.autoKeyframe(query=True, state=True):
                now = float(cmds.currentTime(query=True))
                animated = set(ts._curves(node))
                cmds.setKeyframe(node, attribute=attribute, time=now)
                for channel in done:
                    if channel in animated:
                        cmds.setKeyframe(node, attribute=channel, time=now)
            return keys_scene._done(f"{label} - kept in place", say)
        times = _key_times(node) or [float(cmds.currentTime(query=True))]
        now = float(cmds.currentTime(query=True))
        places = {}
        for time in times:               # where it is on each key BEFORE anything changes
            cmds.currentTime(time, update=True)
            places[time] = _place(node)
        for time in times:
            cmds.currentTime(time, update=True)
            cmds.setKeyframe(node, attribute=attribute, time=time, value=value)
            cmds.setAttr(plug, value)
            for channel in al.put_to(node, *places[time], MOVE_TURN):
                cmds.setKeyframe(node, attribute=channel, time=time)
        cmds.currentTime(now, update=True)
    finally:
        cmds.undoInfo(closeChunk=True)
    return keys_scene._done(f"{label} on {len(times)} key{'s' if len(times) != 1 else ''} - kept in place", say)


def rate(node: str) -> dict:
    """{order: "Best" | "Good" | "OK" | ""} for the control's own animation (space.rate_orders)."""
    now = sp.ORDERS[int(cmds.getAttr(f"{node}.{ROTATE_ORDER}"))]
    times = _key_times(node)
    if not times:
        rotation = tuple(cmds.getAttr(f"{node}.rotate")[0])
        return sp.rate_orders([rotation], [rotation], now)
    first, last = int(round(times[0])), int(round(times[-1]))
    frames = [tuple(cmds.getAttr(f"{node}.rotate", time=f)[0]) for f in range(first, last + 1)]
    keys = [tuple(cmds.getAttr(f"{node}.rotate", time=t)[0]) for t in times]
    return sp.rate_orders(frames, keys, now)


def rotate_order(node: str, order: int, say: bool = False) -> str:
    """The rotate order changed with the turn kept on every key frame of the control (rx / ry / rz keyed there;
    the order itself is not keyed); a control without keys keeps its turn on this frame."""
    times = _key_times(node)
    now = float(cmds.currentTime(query=True))
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        places = {}
        for time in times or [now]:
            if times:
                cmds.currentTime(time, update=True)
            places[time] = _place(node)
        cmds.setAttr(f"{node}.{ROTATE_ORDER}", order)
        for time in times or [now]:
            if times:
                cmds.currentTime(time, update=True)
            done = al.put_to(node, places[time][0], places[time][1], ("rotate",))
            if times:
                for channel in done:
                    cmds.setKeyframe(node, attribute=channel, time=time)
        if times:
            cmds.currentTime(now, update=True)
    finally:
        cmds.undoInfo(closeChunk=True)
    text = f"{node.split('|')[-1]} rotate order {sp.ORDERS[order]}"
    text += f" on {len(times)} key{'s' if len(times) != 1 else ''}" if times else ""
    if not (cmds.getAttr(f"{node}.{ROTATE_ORDER}", keyable=True) or
            cmds.getAttr(f"{node}.{ROTATE_ORDER}", channelBox=True)):
        text += " · it isn't shown to the animator: a pipeline may not keep it - set it back before publishing"
    return keys_scene._done(text, say)
