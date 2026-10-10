# tools/maya/controls/ghost.py
"""The ghost: what Create would make, shown in Maya's own viewport ON the selected objects before
anything is made (maya.cmds / OpenMaya, no Qt).

The ghosts are real curves under one group (`scene.GHOST_GROUP`), but helpers of the SESSION, never
part of the user's scene: built through the API (no selection change, nothing in the undo queue),
hidden in the Outliner, taken out for the moment of a save or an export (measured, Maya 2025: the
"do not write" flag alone still wrote them), and the scene's "modified" mark is put back. `show()`
replaces them, `clear()` removes them.

They are drawn in the COLOR the control will get (the user tried grey templates for a moment and came
back: grey can be lost against the viewport's background), so they are ordinary, pickable curves — a
"reference" display type can't be picked but is drawn black whatever its color (measured). A click on
a ghost therefore means the object it stands for: `redirect_selection()` swaps one for the other.
`show(grey=True)` is the template form (Maya's grey, can't be picked), kept but not used.
"""
from maya import cmds
import maya.api.OpenMaya as om

from msl_tools.msl.tools.maya.controls import colors, scene
from msl_tools.msl.tools.maya.controls import shapes as shape_data

GROUP = scene.GHOST_GROUP
LIMIT = 60          # more selected objects than this: the first ones get a ghost


class _Quiet:
    """Inside: nothing reaches the undo queue, and the scene's "modified" mark is put back."""

    def __enter__(self):
        self._modified = cmds.file(query=True, modified=True)
        self._undo_was_on = cmds.undoInfo(query=True, stateWithoutFlush=True)   # put back as it WAS
        cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *_exc):
        if self._undo_was_on:
            cmds.undoInfo(stateWithoutFlush=True)
        if not self._modified:
            cmds.file(modified=False)
        return False


_targets = {}        # ghost transform (short name) -> the uuid of the object it stands for


def _before_save(*_args) -> None:
    clear()


def _watch_saves() -> None:
    """The ghosts step out before a save / an export. The callbacks are kept on maya.cmds, so the
    ones of the code before a "Reload Code" are removed, not doubled."""
    for callback in getattr(cmds, "_msl_controls_ghost_callbacks", []):
        try:
            om.MMessage.removeCallback(callback)
        except RuntimeError:
            pass
    cmds._msl_controls_ghost_callbacks = [om.MSceneMessage.addCallback(when, _before_save)
                                          for when in (om.MSceneMessage.kBeforeSave, om.MSceneMessage.kBeforeExport)]


_watch_saves()


def redirect_selection() -> bool:
    """A picked ghost stands for its object: every selected ghost (or a part of one) is swapped for
    the object it was made for. True when the selection was changed."""
    picked = cmds.ls(selection=True, long=True) or []
    if not any(scene.is_ghost(item) for item in picked):
        return False
    wanted = []
    for item in picked:
        if scene.is_ghost(item):
            parts = item.partition(".")[0].split("|")
            found = cmds.ls(_targets.get(parts[2] if len(parts) > 2 else "", ""), long=True) if len(parts) > 2 else []
            item = found[0] if found else ""
        if item and item not in wanted:
            wanted.append(item)
    with _Quiet():
        if wanted:
            cmds.select(wanted, replace=True)
        else:
            cmds.select(clear=True)
    return True


def exists() -> bool:
    return cmds.objExists("|" + GROUP)


def clear() -> None:
    """No ghosts. Safe to call any time."""
    _targets.clear()
    if exists():
        with _Quiet():
            try:
                cmds.delete("|" + GROUP)
            except RuntimeError:
                pass


def _helper(node: str) -> None:
    for attr, value in (("doNotWrite", True), ("hiddenInOutliner", True)):
        if cmds.attributeQuery(attr, node=node, exists=True):
            cmds.setAttr(f"{node}.{attr}", value)


def _knots(count: int, degree: int, closed: bool) -> list:
    """The knots of a curve of `count` CVs (as built: a periodic one has its first `degree` CVs again)."""
    if degree <= 1:
        return list(range(count))
    if closed:
        return list(range(-degree + 1, count))          # count = points + degree
    inner = count - degree
    return [0] * degree + list(range(1, inner)) + [inner] * degree


def _add_curve(parent: str, curve: shape_data.Curve) -> str:
    """One curve as a shape of `parent`, made through the API: the selection stays, undo knows nothing."""
    points = [tuple(point) for point in curve.points]
    degree = max(1, min(curve.degree, len(points) - 1))
    periodic = curve.closed and degree > 1
    if periodic:
        points = points + points[:degree]
    elif curve.closed:
        points = points + points[:1]
    holder = om.MSelectionList().add(parent).getDependNode(0)
    form = om.MFnNurbsCurve.kPeriodic if periodic else om.MFnNurbsCurve.kOpen
    made = om.MFnNurbsCurve().create(om.MPointArray([om.MPoint(*point) for point in points]),
                                     om.MDoubleArray([float(knot) for knot in _knots(len(points), degree, periodic)]),
                                     degree, form, False, False, holder)
    return om.MFnDagNode(made).fullPathName()


def _square(half: float) -> shape_data.Curve:
    return shape_data.Curve([(-half, 0.0, -half), (half, 0.0, -half), (half, 0.0, half), (-half, 0.0, half)], 1, True)


def _zero_curves(mode: str, count: int, reach: float) -> list:
    """Zero as lines around the control, in the plane it faces +Y in: "groups" = one frame per group,
    nested; "matrix" = the corners of one frame (brackets)."""
    if mode == "groups":
        return [_square(reach * (1.2 + 0.17 * index)) for index in range(min(max(1, count), 4))]
    if mode == "matrix":
        half, arm = reach * 1.2, reach * 0.45
        return [shape_data.Curve([(x * (half - arm), 0.0, z * half), (x * half, 0.0, z * half),
                                  (x * half, 0.0, z * (half - arm))], 1, False)
                for x in (-1, 1) for z in (-1, 1)]
    return []


def _drive_curves(drive: str, reach: float) -> list:
    """A small mark at the pivot of a control that will DRIVE its object: a diamond for constraints,
    a little cube for the matrix."""
    size = reach * 0.14
    if drive == "constraint":
        x, y, z = (size, 0, 0), (0, size, 0), (0, 0, size)
        nx, ny, nz = (-size, 0, 0), (0, -size, 0), (0, 0, -size)
        return [shape_data.Curve([y, x, ny, nx, y, z, ny, nz, y, x, z, nx, nz, x], 1, False)]
    if drive == "matrix":
        h = size * 0.8
        corners = [(-h, -h, -h), (h, -h, -h), (h, -h, h), (-h, -h, h), (-h, h, -h), (h, h, -h), (h, h, h), (-h, h, h)]
        return [shape_data.Curve([corners[i] for i in (0, 1, 2, 3, 0, 4, 5, 1, 5, 6, 2, 6, 7, 3, 7, 4)], 1, False)]
    return []


def _colored(node: str, rgb, width: float) -> None:
    _helper(node)
    if rgb is not None:
        cmds.setAttr(node + ".overrideEnabled", 1)
        cmds.setAttr(node + ".overrideRGBColors", 1)
        cmds.setAttr(node + ".overrideColorRGB", *rgb[:3])
    if cmds.attributeQuery("lineWidth", node=node, exists=True):
        cmds.setAttr(node + ".lineWidth", width)


def show(shape: shape_data.Shape, targets: list, size: float, axis: str, fit: bool, color_of=None,
         line_width: float = 2.0, grey: bool = False, zero: tuple = ("none", 0), drive: str = "none") -> int:
    """A ghost of the control each target would get: the shape facing `axis`, as big as `size` (times
    the target's own when `fit`), standing where the target stands, in the color it will get —
    `color_of(position)` -> (r, g, b), or None for Maya's default; `grey` = a template instead (it
    can't be picked). Around it, thin: how it will be zeroed (`zero` = ("groups", how many) -> nested
    frames, ("matrix", 1) -> brackets) and, at its pivot, a mark when it will drive its object (`drive`
    "constraint" / "matrix"). Replaces the ghosts there were; how many are shown."""
    targets = [target for target in targets if not scene.is_ghost(target)][:LIMIT]
    if not targets:
        clear()
        return 0
    with _Quiet():
        if exists():
            cmds.delete("|" + GROUP)
        _targets.clear()
        group = cmds.createNode("transform", name=GROUP, skipSelect=True)
        group = cmds.ls(group, long=True)[0]
        _helper(group)
        for index, target in enumerate(targets):
            reach = size * (scene.fit_size(target, axis) if fit else 1.0)
            ghost = cmds.createNode("transform", name=f"{GROUP}_{index + 1}", parent=group, skipSelect=True)
            ghost = cmds.ls(ghost, long=True)[0]
            cmds.setAttr(ghost + ".rotateOrder", cmds.getAttr(target + ".rotateOrder"))
            cmds.matchTransform(ghost, target, position=True, rotation=True)
            _helper(ghost)
            _targets[ghost.rpartition("|")[2]] = cmds.ls(target, uuid=True)[0]
            rgb = color_of(scene.position(target)) if color_of else None
            for curve in shape_data.scaled(shape_data.oriented(shape.curves, axis), reach):
                node = _add_curve(ghost, curve)
                _helper(node)
                if grey:
                    # a template: Maya's own quiet grey, and it can't be picked
                    cmds.setAttr(node + ".overrideEnabled", 1)
                    cmds.setAttr(node + ".overrideDisplayType", 1)
                elif rgb is not None:           # None: Maya's default color, as the control will be
                    cmds.setAttr(node + ".overrideEnabled", 1)
                    cmds.setAttr(node + ".overrideRGBColors", 1)
                    cmds.setAttr(node + ".overrideColorRGB", *rgb[:3])
                if cmds.attributeQuery("lineWidth", node=node, exists=True):
                    cmds.setAttr(node + ".lineWidth", line_width)
            for curve in shape_data.oriented(_zero_curves(zero[0], zero[1], reach), axis):
                _colored(_add_curve(ghost, curve), colors.GHOST_ZERO, 1.0)
            for curve in _drive_curves(drive, reach):
                _colored(_add_curve(ghost, curve), colors.GHOST_DRIVE, 1.5)
    return len(targets)
