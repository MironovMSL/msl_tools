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
            stood_for = _targets.get(parts[2], "") if len(parts) > 2 else ""
            names = list(stood_for) if isinstance(stood_for, (list, tuple)) else [stood_for]
            item = ""
            for found in (cmds.ls([name for name in names if name], long=True) or []) if any(names) else []:
                if found not in wanted:
                    wanted.append(found)
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


def _zero_curves(mode: str, count: int, reach: float) -> list:
    """Zero, drawn BESIDE the control (never around it: frames read as part of the shape), in the
    plane a flat shape lies in (XZ, before it is turned to its axis): "groups" = small diamonds on a
    stem, one per group, the top group farthest — the way null groups look in Maya; "matrix" = one
    pair of brackets there. The stem runs from the shape's rim."""
    if mode not in ("groups", "matrix"):
        return []
    size = reach * 0.17           # big enough to be found in a scene (0.11 got lost)
    first = -(reach + size * 2.4)
    step = size * 2.7
    curves = []
    if mode == "matrix":
        for side in (-1, 1):
            curves.append(shape_data.Curve([(side * size * 0.45, 0.0, first - size), (side * size, 0.0, first - size),
                                            (side * size, 0.0, first + size), (side * size * 0.45, 0.0, first + size)],
                                           1, False))
        curves.append(shape_data.Curve([(0.0, 0.0, -reach), (0.0, 0.0, first + size)], 1, False))
        return curves
    amount = min(max(1, count), 5)
    for index in range(amount):
        centre = first - index * step
        curves.append(shape_data.Curve([(0.0, 0.0, centre - size), (size, 0.0, centre), (0.0, 0.0, centre + size),
                                        (-size, 0.0, centre)], 1, True))
        below = -reach if index == 0 else first - (index - 1) * step - size
        curves.append(shape_data.Curve([(0.0, 0.0, below), (0.0, 0.0, centre + size)], 1, False))
    return curves


def _drive_curves(drive: str, reach: float, to=None) -> list:
    """"This control drives its object", as an ARROW from the control to the object: solid for
    constraints, dashes for the matrix. The two stand in one place, so the arrow leaves the shape's
    rim and bends in to the pivot (the plane XZ, before the turn to the axis); `to` = where the object
    is in the control's own axes, when it is NOT there: then a straight arrow to it."""
    if drive not in ("constraint", "matrix"):
        return []
    if to is None:
        start, bend, end = (0.0, 0.0, reach), (reach * 0.8, 0.0, reach * 0.8), (reach * 0.2, 0.0, 0.0)
        points = []
        for index in range(11):
            t = index / 10.0
            points.append(tuple((1 - t) ** 2 * a + 2 * (1 - t) * t * b + t * t * c
                                for a, b, c in zip(start, bend, end)))
    else:
        points = [tuple(value * index / 12.0 for value in to) for index in range(13)]
    tip, before = points[-1], points[-2]
    along = [a - b for a, b in zip(tip, before)]
    length = sum(value * value for value in along) ** 0.5 or 1.0
    along = [value / length for value in along]
    up = (0.0, 1.0, 0.0) if abs(along[1]) < 0.9 else (1.0, 0.0, 0.0)
    across = [along[1] * up[2] - along[2] * up[1], along[2] * up[0] - along[0] * up[2],
              along[0] * up[1] - along[1] * up[0]]
    head = reach * 0.16
    wings = [tuple(tip[i] - along[i] * head + side * across[i] * head * 0.55 for i in range(3)) for side in (1, -1)]
    curves = [shape_data.Curve([wings[0], tip, wings[1]], 1, False)]
    if drive == "matrix":
        curves += [shape_data.Curve([points[index], points[index + 1]], 1, False)
                   for index in range(0, len(points) - 1, 2)]
    else:
        curves.append(shape_data.Curve(points, 1, False))
    return curves


def _colored(node: str, rgb, width: float) -> None:
    _helper(node)
    if rgb is not None:
        cmds.setAttr(node + ".overrideEnabled", 1)
        cmds.setAttr(node + ".overrideRGBColors", 1)
        cmds.setAttr(node + ".overrideColorRGB", *rgb[:3])
    if cmds.attributeQuery("lineWidth", node=node, exists=True):
        cmds.setAttr(node + ".lineWidth", width)


def show(shape: shape_data.Shape, targets: list, size: float, axis: str, fit: bool, color_of=None,
         line_width: float = 2.0, grey: bool = False, zero: tuple = ("none", 0), drive: str = "none",
         links: "list | tuple" = ()) -> int:
    """A ghost of the control each target would get: the shape facing `axis`, as big as `size` (times
    the target's own when `fit`), standing where the target stands, in the color it will get —
    `color_of(position)` -> (r, g, b), or None for Maya's default; `grey` = a template instead (it
    can't be picked). Beside it, thin: how it will be zeroed (`zero` = ("groups", how many) -> diamonds
    on a stem, ("matrix", 1) -> brackets) and an arrow to the object when it will drive it (`drive`
    "constraint" solid / "matrix" dashed).

    `links` = controls that EXIST: the same marks for what is already true of them (their zero groups
    or matrix, an arrow to each object they drive — straight to it when it stands elsewhere), and no
    shape: the control is there. Replaces the ghosts there were; how many are shown."""
    targets = [target for target in targets
               if isinstance(target, scene.Part) or not scene.is_ghost(target)][:LIMIT]
    tied = []
    for control in [node for node in links if not scene.is_ghost(node)][:LIMIT]:
        info = scene.links_of(control)
        if info["groups"] or info["matrix_zero"] or info["driven"]:
            tied.append((control, info))
    if not targets and not tied:
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
            part = target if isinstance(target, scene.Part) else None
            own = scene.part_size(part) if part else scene.fit_size(target, axis)
            reach = size * (own if fit else 1.0)
            ghost = cmds.createNode("transform", name=f"{GROUP}_{index + 1}", parent=group, skipSelect=True)
            ghost = cmds.ls(ghost, long=True)[0]
            if part:                # a vertex, an edge, a face: it stands there, turned as the Part says
                cmds.xform(ghost, worldSpace=True, matrix=list(part.matrix))
                _targets[ghost.rpartition("|")[2]] = part.item
                where = part.position
            else:
                cmds.setAttr(ghost + ".rotateOrder", cmds.getAttr(target + ".rotateOrder"))
                cmds.matchTransform(ghost, target, position=True, rotation=True)
                _targets[ghost.rpartition("|")[2]] = cmds.ls(target, uuid=True)[0]
                where = scene.position(target)
            _helper(ghost)
            rgb = color_of(where) if color_of else None
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
                _colored(_add_curve(ghost, curve), colors.GHOST_ZERO, 1.5)
            for curve in shape_data.oriented(_drive_curves("none" if part else drive, reach), axis):
                _colored(_add_curve(ghost, curve), colors.GHOST_DRIVE, 1.5)
        for index, (control, info) in enumerate(tied):
            ghost = cmds.createNode("transform", name=f"{GROUP}_link_{index + 1}", parent=group, skipSelect=True)
            ghost = cmds.ls(ghost, long=True)[0]
            cmds.setAttr(ghost + ".rotateOrder", cmds.getAttr(control + ".rotateOrder"))
            cmds.matchTransform(ghost, control, position=True, rotation=True)
            _helper(ghost)
            _targets[ghost.rpartition("|")[2]] = cmds.ls(control, uuid=True)[0]
            reach = scene.world_reach(control)
            facing = scene.flat_axis(control)
            marks = ("groups", len(info["groups"])) if info["groups"] else \
                ("matrix", 1) if info["matrix_zero"] else ("none", 0)
            for curve in shape_data.oriented(_zero_curves(marks[0], marks[1], reach), facing):
                _colored(_add_curve(ghost, curve), colors.GHOST_ZERO, 1.5)
            frame = scene._placed(control).inverse()
            for target, kind in info["driven"][:6]:
                spot = om.MPoint(*scene.position(target)) * frame
                away = (spot.x, spot.y, spot.z)
                if max(abs(value) for value in away) > reach * 0.3:
                    arrows = _drive_curves(kind, reach, to=away)
                else:
                    arrows = shape_data.oriented(_drive_curves(kind, reach), facing)
                for curve in arrows:
                    _colored(_add_curve(ghost, curve), colors.GHOST_DRIVE, 1.5)
    return len(targets) + len(tied)
