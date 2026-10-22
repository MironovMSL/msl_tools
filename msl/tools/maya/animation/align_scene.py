# tools/maya/animation/align_scene.py
"""ALIGN OBJECTS in the scene (the rules and the measurements: align.py).

Each object is put onto the last selected one by its own channels: the turn first - the target's world rotation
(its scale taken out) brought into the object's rotate order between its rotate axis, joint orient and parent,
the Euler solution nearest to what the object had -, then the move: the object's rotate pivot carried onto the
target's in its parent's space. Locked or driven channels are left. Keys are set frame by frame (the time is
put back after); one undo step ("MSL Align").
"""
from __future__ import annotations

from maya import cmds

from msl_tools.msl.tools.maya.animation import align as al
from msl_tools.msl.tools.maya.animation import keys_scene
from msl_tools.msl.tools.maya.animation import scene
from msl_tools.msl.tools.maya.animation import transfer_scene as ts

UNDO_NAME = "MSL Align"
CHANNELS = ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ")
SCALES = ("scaleX", "scaleY", "scaleZ")
WHOLE = ("translate", "rotate")       # what a plain Align takes (measured: scale is left)
ORDERS = "xyz yzx zxy xzy yxz zyx".split()


def _matrix(plug: str):
    import maya.api.OpenMaya as om
    return om.MMatrix(cmds.getAttr(plug))


def _turn(matrix):
    """The rotation part of a matrix (scale and shear taken out)."""
    import maya.api.OpenMaya as om
    return om.MTransformationMatrix(matrix).rotation(asQuaternion=True).asMatrix()


def _parent(node: str):
    """The space the object's channels live in: offset parent matrix x the parent's world matrix."""
    parent = _matrix(f"{node}.parentMatrix[0]")
    if cmds.attributeQuery("offsetParentMatrix", node=node, exists=True):
        parent = _matrix(f"{node}.offsetParentMatrix") * parent
    return parent


def _free(node: str, attribute: str) -> bool:
    plug = f"{node}.{attribute}"
    if cmds.getAttr(plug, lock=True):
        return False
    source = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    return all(cmds.nodeType(item).startswith("animCurve") for item in source)


def _rotate_axis(node: str):
    import maya.api.OpenMaya as om
    values = cmds.getAttr(f"{node}.rotateAxis")[0]
    return om.MEulerRotation(*[om.MAngle(v, om.MAngle.uiUnit()).asRadians() for v in values]).asMatrix()


def _orient(node: str):
    import maya.api.OpenMaya as om
    if cmds.nodeType(node) != "joint":
        return om.MMatrix()
    values = cmds.getAttr(f"{node}.jointOrient")[0]
    return om.MEulerRotation(*[om.MAngle(v, om.MAngle.uiUnit()).asRadians() for v in values]).asMatrix()


def put(node: str, target: str, parts=WHOLE) -> list:
    """`node` put onto `target` on the current frame - the `parts` of "translate", "rotate", "scale" (measured on
    the reference's menu: Orientation turns the object about its pivot and leaves its move, Position carries its
    rotate pivot over and leaves its turn, Scale = the target's world scale over the object's parent's, axis by
    axis); the channels it set."""
    import maya.api.OpenMaya as om
    world = _matrix(f"{target}.worldMatrix[0]")
    there = om.MPoint(cmds.xform(target, query=True, worldSpace=True, rotatePivot=True))
    scale = om.MTransformationMatrix(world).scale(om.MSpace.kWorld) if "scale" in parts else None
    return put_to(node, _turn(world), there, parts, scale)


def pivot_matrix(node: str):
    """The node's place as one matrix: its world turn, its ROTATE PIVOT as the position (what Align, the world
    space copy and the relationship copy carry - measured)."""
    import maya.api.OpenMaya as om
    matrix = om.MMatrix(_turn(_matrix(f"{node}.worldMatrix[0]")))
    x, y, z = cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)
    matrix[12], matrix[13], matrix[14] = x, y, z
    return matrix


def put_to(node: str, turn, there, parts=WHOLE, scale=None) -> list:
    """`node` given the world turn `turn` (a rotation matrix) with its rotate pivot at `there` (an MPoint), on the
    current frame - by its own channels; the channels it set."""
    import maya.api.OpenMaya as om
    unit = om.MAngle.uiUnit()
    parent = _parent(node)
    done = []
    if "rotate" in parts:
        order = cmds.getAttr(f"{node}.rotateOrder")
        # world turn = rotate axis x rotate x joint orient x parent  ->  rotate = Ra^-1 x W x (Jo x P)^-1
        local = _rotate_axis(node).inverse() * turn * (_orient(node) * _turn(parent)).inverse()
        now = [om.MAngle(v, unit).asRadians() for v in cmds.getAttr(f"{node}.rotate")[0]]
        euler = om.MTransformationMatrix(local).rotation().reorder(order)
        euler = euler.closestSolution(om.MEulerRotation(*now, order))
        for attribute, value in zip(CHANNELS[3:], (euler.x, euler.y, euler.z)):
            if _free(node, attribute):
                cmds.setAttr(f"{node}.{attribute}", om.MAngle(value).asUnits(unit))
                done.append(attribute)
    if "scale" in parts and scale is not None:
        above = om.MTransformationMatrix(parent).scale(om.MSpace.kWorld)
        for attribute, value, under in zip(SCALES, scale, above):
            if _free(node, attribute) and abs(under) > 1e-12:
                cmds.setAttr(f"{node}.{attribute}", value / under)
                done.append(attribute)
    if "translate" in parts:
        # the object's rotate pivot onto `there`, the difference brought into the parent's space
        here = om.MPoint(cmds.xform(node, query=True, worldSpace=True, rotatePivot=True))
        shift = (om.MPoint(there) - here) * parent.inverse()
        for attribute, delta in zip(CHANNELS[:3], (shift.x, shift.y, shift.z)):
            if not _free(node, attribute):
                continue
            if abs(delta) > 1e-12:
                plug = f"{node}.{attribute}"
                cmds.setAttr(plug, cmds.getAttr(plug) + om.MDistance(delta).asUnits(om.MDistance.uiUnit()))
            done.append(attribute)
    return done


def _key_times(node: str) -> list:
    times = []
    for curve in ts._curves(node).values():
        times += cmds.keyframe(curve, query=True, timeChange=True) or []
    return times


def _picked() -> tuple:
    objects = scene.selected_objects()
    objects = [node for node in objects if cmds.objectType(node, isAType="transform")]
    if len(objects) < 2:
        return [], ""
    return objects[:-1], objects[-1]


def _parts(part: str) -> tuple:
    return WHOLE if not part else (part,)


def align(part: str = "", say: bool = False) -> str:
    """Align Objects: on the current frame, or keyed on the key frames inside a highlighted span. `part`
    "translate" / "rotate" / "scale" = only that (the reference's Position / Orientation / Scale)."""
    movers, target = _picked()
    if not movers:
        return keys_scene._done("Select the objects to align, then the one to align them to - last", say)
    span = scene.timeline_range()
    if span:
        return _keyed(movers, target, (span[0], span[1] - 1.0), say, _parts(part))
    autokey = cmds.autoKeyframe(query=True, state=True)
    now = float(cmds.currentTime(query=True))
    keyed = 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for node in movers:
            animated = set(ts._curves(node))
            for attribute in put(node, target, _parts(part)):
                if autokey and attribute in animated:
                    cmds.setKeyframe(node, attribute=attribute, time=now)
                    keyed += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    text = al.describe(len(movers), part=part)
    return keys_scene._done(text + (f" · {keyed} keyed (auto key)" if keyed else ""), say)


def align_all_keys(part: str = "", say: bool = False) -> str:
    """Align Objects All Keys: keyed on every frame where the object or the last selected has a key (`part` as
    in `align`)."""
    movers, target = _picked()
    if not movers:
        return keys_scene._done("Select the objects to align, then the one to align them to - last", say)
    return _keyed(movers, target, None, say, _parts(part))


def _keyed(movers: list, target: str, span, say: bool, parts=WHOLE) -> str:
    now = float(cmds.currentTime(query=True))
    plan = [(node, al.frames(_key_times(node), _key_times(target), span)) for node in movers]
    every = sorted({time for _node, times in plan for time in times})
    if not every:
        where = f"in frames {span[0]:g}-{span[1]:g}" if span else "on them"
        return keys_scene._done(f"No keys {where} to align on", say)
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for time in every:            # frame by frame, so each object follows its target's motion
            cmds.currentTime(time, update=True)
            for node, times in plan:
                if time in times:
                    for attribute in put(node, target, parts):
                        cmds.setKeyframe(node, attribute=attribute, time=time)
        cmds.currentTime(now, update=True)
    finally:
        cmds.undoInfo(closeChunk=True)
    return keys_scene._done(al.describe(len(movers), len(every), parts[0] if len(parts) == 1 else ""), say)
