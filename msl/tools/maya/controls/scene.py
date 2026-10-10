# tools/maya/controls/scene.py
"""The Maya side of the Controls tool (maya.cmds, no Qt): building controls from shapes, placing
them on what is selected, their offsets (groups or the offsetParentMatrix), editing their shapes.
Every action the user starts is ONE undo step (`_Chunk`)."""
from maya import cmds

from msl_tools.msl.tools.maya.controls import colors
from msl_tools.msl.tools.maya.controls import shapes as shape_data
from msl_tools.msl.tools.maya.controls.naming import control_name

UNDO_NAME = "MSL Controls"
GHOST_GROUP = "mslControlsGhost"        # ghost.py's helpers: never the user's objects


def is_ghost(path: str) -> bool:
    return path.startswith("|" + GHOST_GROUP)
SIDE_COLORS = colors.SIDE_COLORS


class _Chunk:
    """with _Chunk(): … = one undo step."""

    def __enter__(self):
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)

    def __exit__(self, *_exc):
        cmds.undoInfo(closeChunk=True)
        return False


# ------------------------------------------------------------------ reading

def selected_transforms() -> list:
    """The selected DAG transforms (a selected shape stands for its transform), long names, in order."""
    found = []
    for item in cmds.ls(orderedSelection=True, long=True) or []:
        item = item.partition(".")[0]          # selected CVs stand for their curve
        if cmds.objectType(item, isAType="shape"):
            item = (cmds.listRelatives(item, parent=True, fullPath=True) or [""])[0]
        if item and cmds.objectType(item, isAType="transform") and item not in found and not is_ghost(item):
            found.append(item)
    return found


def curve_shapes(transform: str) -> list:
    return cmds.listRelatives(transform, shapes=True, type="nurbsCurve", fullPath=True, noIntermediate=True) or []


def controls_in_selection() -> list:
    """The selected transforms that have curve shapes (the controls to edit)."""
    return [item for item in selected_transforms() if curve_shapes(item)]


def read_curves(transform: str) -> list:
    """The transform's curve shapes as shapes.Curve (object space; a periodic curve without its
    overlapping CVs)."""
    curves = []
    for shape in curve_shapes(transform):
        degree = cmds.getAttr(shape + ".degree")
        form = cmds.getAttr(shape + ".form")         # 0 open, 1 closed, 2 periodic
        points = _points(shape)
        if form == 2:
            # a periodic curve has as many CVs of its own as spans (the others repeat its first ones;
            # xform lists only those, getAttr all)
            curves.append(shape_data.Curve(points[:cmds.getAttr(shape + ".spans")], degree, True))
        elif form == 1 and degree == 1 and len(points) > 2 and points[0] == points[-1]:
            curves.append(shape_data.Curve(points[:-1], 1, True))
        else:
            curves.append(shape_data.Curve(points, degree, False))
    return curves


def position(transform: str):
    return tuple(cmds.xform(transform, query=True, worldSpace=True, rotatePivot=True))


def fit_size(target: str) -> float:
    """How big a control for `target` reads well: a joint by its radius, anything else by its
    bounding box; 1 when there is nothing to measure."""
    if cmds.objectType(target, isAType="joint"):
        return max(0.1, cmds.getAttr(target + ".radius") * 2.0)
    shapes = cmds.listRelatives(target, shapes=True, fullPath=True, noIntermediate=True) or []
    if shapes:
        box = cmds.exactWorldBoundingBox(target)
        extent = max(box[3] - box[0], box[4] - box[1], box[5] - box[2])
        if extent > 0:
            return extent * 0.6
    return 1.0


# ------------------------------------------------------------------ building

def _make_curve(curve: shape_data.Curve) -> str:
    """One curve as a new transform with its shape (Maya's own `curve`)."""
    points = [tuple(point) for point in curve.points]
    if curve.degree > 1 and curve.closed:
        degree = curve.degree
        return cmds.curve(degree=degree, periodic=True, point=points + points[:degree],
                          knot=list(range(-degree + 1, len(points) + degree)))
    if curve.closed:
        return cmds.curve(degree=1, point=points + points[:1])
    return cmds.curve(degree=max(1, curve.degree), point=points)


def add_shapes(transform: str, curves: list, keep_from: "str | None" = None) -> list:
    """Builds the curves as shapes of `transform`, named <transform>Shape, Shape1…; colors and line
    width copied from the shape `keep_from` if given. Returns the new shapes."""
    made = []
    short = transform.rpartition("|")[2]
    existing = len(curve_shapes(transform))
    for index, curve in enumerate(curves):
        temp = _make_curve(curve)
        shape = cmds.listRelatives(temp, shapes=True, fullPath=True)[0]
        shape = cmds.parent(shape, transform, shape=True, relative=True)[0]
        cmds.delete(temp)
        number = existing + index
        shape = cmds.rename(shape, f"{short}Shape" + (str(number) if number else ""))
        made.append(cmds.ls(shape, long=True)[0])
    if keep_from:
        for shape in made:
            _copy_look(keep_from, shape)
    return made


def _copy_look(source: str, target: str) -> None:
    for attr in ("overrideEnabled", "overrideRGBColors", "overrideColor", "lineWidth"):
        try:
            cmds.setAttr(f"{target}.{attr}", cmds.getAttr(f"{source}.{attr}"))
        except (RuntimeError, ValueError):
            pass
    try:
        cmds.setAttr(target + ".overrideColorRGB", *cmds.getAttr(source + ".overrideColorRGB")[0])
    except (RuntimeError, ValueError, TypeError):
        pass


def set_color(transform: str, rgb) -> None:
    """An RGB drawing override on every curve shape of the control."""
    for shape in curve_shapes(transform):
        cmds.setAttr(shape + ".overrideEnabled", 1)
        cmds.setAttr(shape + ".overrideRGBColors", 1)
        cmds.setAttr(shape + ".overrideColorRGB", *rgb)


def add_offset_groups(control: str, suffixes: list) -> list:
    """Groups above the control, top first ("<control>_<suffix>"), each where the control is now;
    the control under the last one with zero translate / rotate. Returns the groups (top first)."""
    parent = (cmds.listRelatives(control, parent=True, fullPath=True) or [None])[0]
    short = control.rpartition("|")[2]
    order = cmds.getAttr(control + ".rotateOrder")
    groups = []
    above = parent
    for suffix in suffixes:
        group = cmds.group(empty=True, name=f"{short}_{suffix}")
        cmds.setAttr(group + ".rotateOrder", order)
        cmds.matchTransform(group, control, position=True, rotation=True)
        if above:
            group = cmds.parent(group, above)[0]
        group = cmds.ls(group, long=True)[0]
        groups.append(group)
        above = group
    if groups:
        control = cmds.parent(control, groups[-1])[0]
        control = cmds.ls(control, long=True)[0]
        for attr in ("translate", "rotate"):
            cmds.setAttr(f"{control}.{attr}", 0, 0, 0)
    return groups


def move_to_offset_matrix(control: str) -> None:
    """Zero the control through its offsetParentMatrix: what its translate / rotate say moves into
    that matrix, the channels read 0 — no group above it (Maya 2020+)."""
    import maya.api.OpenMaya as om
    local = om.MMatrix(cmds.xform(control, query=True, matrix=True, objectSpace=True))
    offset = om.MMatrix(cmds.getAttr(control + ".offsetParentMatrix"))
    cmds.setAttr(control + ".offsetParentMatrix", list(local * offset), type="matrix")
    for attr, value in (("translate", 0), ("rotate", 0), ("scale", 1), ("shear", 0)):
        cmds.setAttr(f"{control}.{attr}", value, value, value)


def _uuid(node: str) -> str:
    return cmds.ls(node, uuid=True)[0]


def _path(uuid: str) -> str:
    """The long name NOW of the node with this uuid (parenting changes long names)."""
    found = cmds.ls(uuid, long=True) or []
    return found[0] if found else ""


DRIVES = ("none", "shape", "constraint", "matrix")


def target_look(target: str) -> dict:
    """What a preview needs to draw the object a control is made for, in the object's OWN axes (a
    control matched to it has the same): its kind ("joint" with `radius` and `bones` = where its child
    joints are; else "box" with its object-space bounding box, or "null"), its short `name`, world
    `position` and `fit` (fit_size)."""
    look = {"name": target.rpartition("|")[2], "position": position(target), "fit": fit_size(target),
            "kind": "null"}
    if cmds.objectType(target, isAType="joint"):
        children = cmds.listRelatives(target, children=True, type="joint", fullPath=True) or []
        look.update(kind="joint", radius=cmds.getAttr(target + ".radius"),
                    bones=[tuple(cmds.getAttr(child + ".translate")[0]) for child in children[:6]])
    else:
        # the SHAPES' boxes are in the object's own axes (the transform's own box is in its parent's:
        # it would be drawn where the object stands in the world), times the object's scale in the
        # world — a control is matched to its place and turn, never its scale
        shapes = cmds.listRelatives(target, shapes=True, fullPath=True, noIntermediate=True) or []
        if shapes:
            import maya.api.OpenMaya as om
            lows = [cmds.getAttr(shape + ".boundingBoxMin")[0] for shape in shapes]
            highs = [cmds.getAttr(shape + ".boundingBoxMax")[0] for shape in shapes]
            scale = om.MTransformationMatrix(_matrix(target)).scale(om.MSpace.kWorld)
            low = [min(each[i] for each in lows) * scale[i] for i in range(3)]
            high = [max(each[i] for each in highs) * scale[i] for i in range(3)]
            look.update(kind="box", box=tuple(min(a, b) for a, b in zip(low, high)) +
                        tuple(max(a, b) for a, b in zip(low, high)))
    return look


def targets_look(targets: list, limit: int = 12) -> list:
    """`target_look` of the first `limit` targets, each with `matrix` — where it stands in the FIRST
    one's axes (position and rotation only, 16 numbers) — and `parent`: the index of the nearest listed
    target above it, -1 for none (whose control a chained control goes under)."""
    import maya.api.OpenMaya as om
    shown = list(targets[:limit])
    looks, base = [], None
    for target in shown:
        look = target_look(target)
        placed = om.MTransformationMatrix(_matrix(target))
        placed.setScale((1.0, 1.0, 1.0), om.MSpace.kWorld)
        placed.setShear((0.0, 0.0, 0.0), om.MSpace.kWorld)
        world = placed.asMatrix()
        if base is None:
            base = world.inverse()
        look["matrix"] = list(world * base)
        look["parent"] = -1
        above = target.rpartition("|")[0]
        while above:
            if above in shown:
                look["parent"] = shown.index(above)
                break
            above = above.rpartition("|")[0]
        looks.append(look)
    return looks


def create(shape: shape_data.Shape, targets: list, template: str, size: float, axis: str, fit: bool,
           offset_mode: str, offset_names: list, chain: bool, side_color: bool, sides,
           drive: str = "none", notes: "list | None" = None, rgb=None) -> list:
    """A control of `shape` for each target (or one at the origin): named by the template, as big
    as `size` (times the target's own size when `fit`), facing `axis`, matched to the target's
    position and rotation; its offsets (`offset_mode` "groups" / "matrix" / "none"); under the
    control of the nearest target above it when `chain`; colored by its side (`side_color`), else in
    `rgb` if given, else left in Maya's default color.

    `drive` = what the control does to its target: "none" (it only stands there), "constraint"
    (parent + scale constraints), "matrix" (through the target's offsetParentMatrix, no constraint
    node), or "shape" — no new object at all: the curves become shapes of the target itself (a joint
    picked by its own curve). Targets that can't be driven (locked or connected channels) are named
    in `notes`. One undo step. Returns the controls (long names)."""
    made = []           # (target, control uuid)
    if drive == "shape" and targets:
        return shapes_onto(shape, targets, size, axis, fit, side_color, sides, rgb)
    with _Chunk():
        for index, target in enumerate(targets or [None]):
            where = position(target) if target else None
            name = control_name(template, target.rpartition("|")[2] if target else "", where, sides, index + 1)
            scale = size * (fit_size(target) if (fit and target) else 1.0)
            curves = shape_data.scaled(shape_data.oriented(shape.curves, axis), scale)
            control = cmds.ls(cmds.createNode("transform", name=name, skipSelect=True), long=True)[0]
            add_shapes(control, curves)
            if target:
                cmds.setAttr(control + ".rotateOrder", cmds.getAttr(target + ".rotateOrder"))
                cmds.matchTransform(control, target, position=True, rotation=True)
            if side_color:
                set_color(control, SIDE_COLORS.get(sides.of(where) if where else "center", SIDE_COLORS["center"]))
            elif rgb is not None:
                set_color(control, rgb)
            made.append((target, _uuid(control)))
        if chain and len(made) > 1:
            _chain(made)
        for _target, uuid in made:
            if offset_mode == "groups" and offset_names:
                add_offset_groups(_path(uuid), offset_names)
            elif offset_mode == "matrix":
                move_to_offset_matrix(_path(uuid))
        for target, uuid in made:
            if target and drive in ("constraint", "matrix"):
                problem = (drive_by_constraint if drive == "constraint" else drive_by_matrix)(_path(uuid), target)
                if problem and notes is not None:
                    notes.append(f"{target.rpartition('|')[2]}: {problem}")
        controls = [_path(uuid) for _target, uuid in made]
        cmds.select([control for control in controls if control], replace=True)
    return controls


def shapes_onto(shape: shape_data.Shape, targets: list, size: float, axis: str, fit: bool, side_color: bool,
                sides, rgb=None) -> list:
    """The curves as shapes OF the targets themselves (no control object): a joint that is picked
    and animated by its own curve. One undo step; the targets."""
    with _Chunk():
        for target in targets:
            scale = size * (fit_size(target) if fit else 1.0)
            old = curve_shapes(target)
            made = add_shapes(target, shape_data.scaled(shape_data.oriented(shape.curves, axis), scale),
                              keep_from=old[0] if old else None)
            color = SIDE_COLORS[sides.of(position(target))] if side_color else rgb
            if color is not None and not old:
                for node in made:
                    cmds.setAttr(node + ".overrideEnabled", 1)
                    cmds.setAttr(node + ".overrideRGBColors", 1)
                    cmds.setAttr(node + ".overrideColorRGB", *color)
        cmds.select(targets, replace=True)
    return list(targets)


def _settable(node: str, attrs) -> bool:
    """None of the channels is locked or has something connected into it."""
    return all(cmds.getAttr(f"{node}.{attr}{axis}", settable=True) for attr in attrs for axis in "XYZ")


def drive_by_constraint(control: str, target: str) -> str:
    """The target follows the control through a parent constraint (and a scale constraint when its
    scale is free), keeping where it is. Returns "" or why it wasn't done."""
    if not _settable(target, ("translate", "rotate")):
        return "its translate / rotate are locked or connected"
    cmds.parentConstraint(control, target, maintainOffset=True)
    if _settable(target, ("scale",)):
        cmds.scaleConstraint(control, target, maintainOffset=True)
    return ""


def drive_by_matrix(control: str, target: str) -> str:
    """The target follows the control through its offsetParentMatrix (Maya 2020+): the control's
    world matrix times the inverse of the target's parent, one multMatrix node — no constraint, the
    target's own channels read zero and stay free. Where the target stands is kept (what differs
    from the control is held in the multMatrix). It is wired to the parent the target has NOW.
    Returns "" or why it wasn't done."""
    import maya.api.OpenMaya as om
    if not _settable(target, ("translate", "rotate", "scale")):
        return "its channels are locked or connected"
    if cmds.listConnections(target + ".offsetParentMatrix", source=True, destination=False):
        return "its offsetParentMatrix is driven already"
    offset = _matrix(target) * _matrix(control, "worldInverseMatrix[0]")
    short = target.rpartition("|")[2].rpartition(":")[2]
    mult = cmds.createNode("multMatrix", name=f"{short}_drive_mm", skipSelect=True)
    if not offset.isEquivalent(om.MMatrix(), 1e-6):
        cmds.setAttr(mult + ".matrixIn[0]", list(offset), type="matrix")
    cmds.connectAttr(control + ".worldMatrix[0]", mult + ".matrixIn[1]")
    # the PARENT's inverse, not the target's own parentInverseMatrix: that one already holds the
    # target's offsetParentMatrix (measured, Maya 2025) and would feed the result back into itself
    parent = cmds.listRelatives(target, parent=True, fullPath=True) or []
    if parent:
        cmds.connectAttr(parent[0] + ".worldInverseMatrix[0]", mult + ".matrixIn[2]")
    if cmds.objectType(target, isAType="joint"):
        cmds.setAttr(target + ".jointOrient", 0, 0, 0)
        # with it on, a joint's own matrix carries its parent's inverse scale: no longer "nothing"
        _set(target + ".segmentScaleCompensate", 0)
    for attr, value in (("translate", 0), ("rotate", 0), ("scale", 1), ("shear", 0), ("rotateAxis", 0)):
        _set(f"{target}.{attr}", value, value, value)
    cmds.connectAttr(mult + ".matrixSum", target + ".offsetParentMatrix", force=True)
    return ""


def _chain(made: list) -> None:
    """Each control under the control of the nearest target above its own (an FK chain) — before
    the offsets are made, so they sit in that chain too."""
    by_target = {target: uuid for target, uuid in made if target}
    for target, uuid in made:
        parent = (target or "").rpartition("|")[0]
        while parent:
            if parent in by_target:
                cmds.parent(_path(uuid), _path(by_target[parent]))
                break
            parent = parent.rpartition("|")[0]


# ------------------------------------------------------------------ editing shapes

def _points(shape: str) -> list:
    """The shape's CVs in object space, as Maya shows them (construction history and tweaks included)."""
    flat = cmds.xform(shape + ".cv[*]", query=True, objectSpace=True, translation=True) or []
    return [tuple(flat[index:index + 3]) for index in range(0, len(flat), 3)]


def _set_points(shape: str, points: list) -> None:
    # xform, not setAttr: a curve with construction history (Maya's own circle) keeps the move as a
    # tweak — a setAttr on its CVs is overwritten when the history evaluates again
    for index, point in enumerate(points):
        cmds.xform(f"{shape}.cv[{index}]", objectSpace=True, translation=point)


def edit_points(controls: list, change) -> int:
    """`change(points) -> points` on every curve shape of the controls (object space). One undo
    step; how many shapes were changed."""
    count = 0
    with _Chunk():
        for control in controls:
            for shape in curve_shapes(control):
                _set_points(shape, change(_points(shape)))
                count += 1
    return count


def turn(controls: list, axis: str, degrees: float = 90.0) -> int:
    def change(points):
        curve = shape_data.turned([shape_data.Curve(points)], axis, degrees)[0]
        return curve.points
    return edit_points(controls, change)


def resize(controls: list, factor: float) -> int:
    return edit_points(controls, lambda points: [tuple(value * factor for value in point) for point in points])


def _swap_shapes(control: str, curves: list) -> None:
    """The control's curve shapes replaced by `curves` (its object space), keeping the old first
    shape's color and line width."""
    old = curve_shapes(control)
    if not old:
        add_shapes(control, curves)
        return
    temp = cmds.createNode("transform", skipSelect=True)
    cmds.parent(old[0], temp, shape=True, relative=True)   # the look to copy from
    keep = cmds.listRelatives(temp, shapes=True, fullPath=True)[0]
    if len(old) > 1:
        cmds.delete(old[1:])
    add_shapes(control, curves, keep_from=keep)
    cmds.delete(temp)


def replace(controls: list, shape: shape_data.Shape, axis: str) -> int:
    """The controls' shapes swapped for `shape`, as big as the old ones, keeping their color and
    line width. One undo step; how many controls."""
    done = 0
    with _Chunk():
        for control in controls:
            if not curve_shapes(control):
                continue
            _swap_shapes(control, shape_data.scaled(shape_data.oriented(shape.curves, axis), _reach(control)))
            done += 1
    return done


def _reach(control: str) -> float:
    """How far the control's CVs go from its pivot on an axis (a library shape's unit size)."""
    return max((max(abs(value) for value in point) for shape_node in curve_shapes(control)
                for point in _points(shape_node)), default=1.0) or 1.0


def add_shape(controls: list, shape: shape_data.Shape, axis: str) -> int:
    """`shape` ADDED to what each control has (as big, in its first shape's color). One undo step."""
    with _Chunk():
        for control in controls:
            old = curve_shapes(control)
            add_shapes(control, shape_data.scaled(shape_data.oriented(shape.curves, axis), _reach(control)),
                       keep_from=old[0] if old else None)
    return len(controls)


def set_curves(controls: list, curves: list) -> int:
    """Each control's shape replaced by `curves` as they are (a copied shape pasted: same size, same
    place about the pivot); each keeps its own color and line width. One undo step."""
    with _Chunk():
        for control in controls:
            _swap_shapes(control, curves)
    return len(controls)


def combine(controls: list) -> str:
    """The curves of all the selected controls become shapes of the LAST one, staying where they are
    in the world and keeping their colors; a control left empty (no shapes, no children) is removed.
    One undo step; the control that holds them now."""
    keeper = controls[-1]
    with _Chunk():
        inverse = _matrix(keeper, "worldInverseMatrix[0]")
        for control in controls[:-1]:
            sources = curve_shapes(control)
            for curve, source in zip(_moved(read_curves(control), _matrix(control) * inverse), sources):
                add_shapes(keeper, [curve], keep_from=source)
            cmds.delete(sources)
            if not cmds.listRelatives(control, children=True, fullPath=True):
                cmds.delete(control)
        cmds.select(keeper, replace=True)
    return keeper


def toggle_cvs() -> str:
    """The selected controls' CVs selected instead of the controls — so Maya's own move / rotate /
    scale edit the SHAPE and the control's channels stay as they are — or, with CVs selected, back
    to the controls. Returns "cvs", "objects" or "" (nothing to do)."""
    picked = cmds.ls(selection=True, long=True) or []
    controls = controls_in_selection()
    if not controls:
        return ""
    if any("." in item for item in picked):
        cmds.selectMode(object=True)
        cmds.select(controls, replace=True)
        return "objects"
    cmds.select(clear=True)
    cmds.hilite(controls, replace=True)
    cmds.selectMode(component=True)
    cmds.selectType(controlVertex=True)
    cmds.select([shape + ".cv[*]" for control in controls for shape in curve_shapes(control)], replace=True)
    return "cvs"


def all_controls(roots: "list | None" = None) -> list:
    """Every transform with a curve shape — under `roots` (themselves included) or in the scene."""
    if roots:
        shapes = cmds.listRelatives(roots, allDescendents=True, type="nurbsCurve", fullPath=True) or []
    else:
        shapes = cmds.ls(type="nurbsCurve", long=True) or []
    found = []
    for shape in shapes:
        if cmds.getAttr(shape + ".intermediateObject"):
            continue
        parent = (cmds.listRelatives(shape, parent=True, fullPath=True) or [""])[0]
        if parent and parent not in found and not is_ghost(parent):
            found.append(parent)
    return found


def toggle_on_top(controls: list) -> "bool | None":
    """The controls' curves drawn over everything (through the geometry) — on when any of them
    isn't, else off. One undo step; the new state, None when this Maya has no such switch."""
    shapes = [shape for control in controls for shape in curve_shapes(control)
              if cmds.attributeQuery("alwaysDrawOnTop", node=shape, exists=True)]
    if not shapes:
        return None
    state = not all(cmds.getAttr(shape + ".alwaysDrawOnTop") for shape in shapes)
    with _Chunk():
        for shape in shapes:
            _set(shape + ".alwaysDrawOnTop", state)
    return state


# ------------------------------------------------------------------ mirroring shapes

def _matrix(node: str, attr: str = "worldMatrix[0]"):
    import maya.api.OpenMaya as om
    return om.MMatrix(cmds.getAttr(f"{node}.{attr}"))


def _moved(curves: list, matrix) -> list:
    import maya.api.OpenMaya as om
    moved = []
    for curve in curves:
        points = []
        for point in curve.points:
            p = om.MPoint(*point) * matrix
            points.append((p.x, p.y, p.z))
        moved.append(shape_data.Curve(points, curve.degree, curve.closed))
    return moved


def _mirrored(curves: list, axis: str) -> list:
    flip = {"X": (-1, 1, 1), "Y": (1, -1, 1), "Z": (1, 1, -1)}[axis]
    return [shape_data.Curve([tuple(value * sign for value, sign in zip(point, flip)) for point in curve.points],
                             curve.degree, curve.closed) for curve in curves]


def other_side(control: str, sides) -> str:
    """The long name of the control on the other side (lf_arm_ctrl -> rt_arm_ctrl, arm_L -> arm_R,
    by the Rename tool's rules), "" when the name says no side or there is none."""
    from msl_tools.msl.tools.maya.rename import rules
    short = control.rpartition("|")[2]
    namespace, _sep, name = short.rpartition(":")
    other = rules.mirror(name, sides)
    if other == name:
        return ""
    found = cmds.ls((namespace + ":" if namespace else "") + other, long=True, type="transform") or []
    return found[0] if len(found) == 1 else ""


_REFLECT = {"X": (-1, 1, 1), "Y": (1, -1, 1), "Z": (1, 1, -1)}


def _behavior_mirror(matrix, axis: str):
    """A world matrix mirrored like Maya's joint mirror with "Behavior": the position across the world
    plane of `axis`, the axes turned so the scale stays positive (S·M·S — two reflections). A shape
    under it shows mirrored when its CVs' own `axis` value is negated (see `mirror_control`)."""
    import maya.api.OpenMaya as om
    sx, sy, sz = _REFLECT[axis]
    reflect = om.MMatrix([sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, 0, 0, 0, 1])
    return reflect * matrix * reflect


def _zero_stack(control: str) -> list:
    """The groups right above the control that zero it (named <control>_<something>), top first."""
    short = control.rpartition("|")[2].rpartition(":")[2]
    stack, node = [], control
    while True:
        parent = (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0]
        if not parent or not parent.rpartition("|")[2].rpartition(":")[2].startswith(short + "_") \
                or len(cmds.listRelatives(parent, children=True, type="transform") or []) != 1:
            break
        stack.insert(0, parent)
        node = parent
    return stack


def _mirror_name(node: str, sides) -> str:
    from msl_tools.msl.tools.maya.rename import rules
    short = node.rpartition("|")[2]
    namespace, sep, name = short.rpartition(":")
    return namespace + sep + rules.mirror(name, sides)


def _mirrored_parent(node: str, sides) -> "str | None":
    """Where a mirrored copy of `node` goes, walking up from its parent: the other side's twin of an
    ancestor if there is one, else the first ancestor that says no side (a middle control); the world
    (None) when neither — never under a node of the SAME side."""
    parent = (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0]
    while parent:
        name = _mirror_name(parent, sides)
        if name == parent.rpartition("|")[2]:
            return parent                      # a middle one: the copy goes under it too
        twin = cmds.ls(name, long=True, type="transform") or []
        if len(twin) == 1:
            return twin[0]
        parent = (cmds.listRelatives(parent, parent=True, fullPath=True) or [None])[0]
    return None


def mirror_control(control: str, sides, axis: str = "X", side_color: bool = False) -> str:
    """A mirrored COPY of the control on the other side (its name by Rename's rules): its zero groups
    made again, mirrored, under the twin of their parent (else the same parent); the transform
    mirrored with "behavior" (not frozen: it keeps a clean, positive-scale transform and its own
    pivot); the shape mirrored in it; colored by its side or like the source; an offsetParentMatrix
    the source zeroes through is used the same way. Returns the new control ("" = the name says no side)."""
    import maya.api.OpenMaya as om
    if _mirror_name(control, sides) == control.rpartition("|")[2]:
        return ""
    stack = _zero_stack(control)
    above = _mirrored_parent(stack[0] if stack else control, sides)
    made = None
    for node in stack + [control]:
        world = _behavior_mirror(om.MMatrix(cmds.getAttr(node + ".worldMatrix[0]")), axis)
        copy = cmds.createNode(cmds.nodeType(node), name=_mirror_name(node, sides), skipSelect=True)
        copy = cmds.ls(copy, long=True)[0]
        cmds.setAttr(copy + ".rotateOrder", cmds.getAttr(node + ".rotateOrder"))
        if above:
            copy = cmds.ls(cmds.parent(copy, above)[0], long=True)[0]
        cmds.xform(copy, worldSpace=True, matrix=list(world))
        above = copy
        made = copy
    flip = _REFLECT[axis]
    curves = [shape_data.Curve([tuple(value * sign for value, sign in zip(point, flip)) for point in curve.points],
                               curve.degree, curve.closed) for curve in read_curves(control)]
    source_shapes = curve_shapes(control)
    add_shapes(made, curves, keep_from=source_shapes[0] if source_shapes else None)
    if has_offset_matrix(control):
        move_to_offset_matrix(made)
    if side_color:
        set_color(made, SIDE_COLORS[sides.of(position(made))])
    return made


def _mirror_shape_onto(control: str, twin: str, axis: str) -> None:
    """The twin's shape made the mirror of the control's: the control's CVs in the world, mirrored
    across the world plane of `axis`, into the twin's object space; the twin keeps its look."""
    world = _moved(read_curves(control), _matrix(control))
    _swap_shapes(twin, _moved(_mirrored(world, axis), _matrix(twin, "worldInverseMatrix[0]")))


def mirror_shapes_to_twins(controls: list, sides, axis: str = "X") -> tuple:
    """Only the SHAPES: each control's other-side twin (by its name) gets the mirror of this one's
    shape — fix one side, carry it over; nothing is made, the twins keep their color, place and
    hierarchy. Either way (left -> right or right -> left: by what is selected). One undo step;
    (how many updated, names whose other side isn't there)."""
    updated, missing = 0, []
    with _Chunk():
        for control in controls:
            twin = other_side(control, sides)
            if twin and twin != control:
                _mirror_shape_onto(control, twin, axis)
                updated += 1
            else:
                missing.append(control.rpartition("|")[2])
    return updated, missing


def mirror_controls(controls: list, sides, axis: str = "X", side_color: bool = False) -> tuple:
    """Mirror each control to the other side: a new mirrored copy, or — when the other side's
    control is there already — its shape made the mirror of this one. One undo step;
    (made, updated, names that say no side)."""
    made, updated, alone = [], 0, []
    uuids = [_uuid(control) for control in sorted(controls, key=lambda path: path.count("|"))]   # parents first
    with _Chunk():
        for uuid in uuids:
            control = _path(uuid)
            twin = other_side(control, sides)
            if twin and twin != control:
                _mirror_shape_onto(control, twin, axis)
                updated += 1
                continue
            copy = mirror_control(control, sides, axis, side_color)
            if copy:
                made.append(copy)
            else:
                alone.append(control.rpartition("|")[2])
        if made:
            cmds.select(made, replace=True)
    return made, updated, alone


def flip(controls: list, axis: str) -> int:
    """Each control's shape mirrored onto itself across its OWN plane of `axis` (object space)."""
    index = "XYZ".index(axis)
    return edit_points(controls, lambda points: [tuple(-value if i == index else value for i, value in enumerate(point))
                                                 for point in points])


# ------------------------------------------------------------------ zeroing what exists

def zero_with_groups(controls: list, suffixes: list) -> int:
    """Groups above each control where it stands, its translate / rotate to 0. One undo step."""
    uuids = [_uuid(control) for control in controls]
    with _Chunk():
        for uuid in uuids:
            add_offset_groups(_path(uuid), suffixes)
    return len(uuids)


def zero_with_matrix(controls: list) -> int:
    """Each control's translate / rotate / scale moved into its offsetParentMatrix (a joint's
    jointOrient too): the channels read 0, no group. One undo step."""
    with _Chunk():
        for control in controls:
            move_to_offset_matrix(control)
            if cmds.objectType(control, isAType="joint"):
                cmds.setAttr(control + ".jointOrient", 0, 0, 0)
    return len(controls)


def matrix_to_channels(controls: list) -> int:
    """The other way: what the offsetParentMatrix holds back into the channels, the matrix empty."""
    import maya.api.OpenMaya as om
    with _Chunk():
        for control in controls:
            local = om.MMatrix(cmds.xform(control, query=True, matrix=True, objectSpace=True))
            whole = local * _matrix(control, "offsetParentMatrix")
            cmds.setAttr(control + ".offsetParentMatrix", list(om.MMatrix()), type="matrix")
            cmds.xform(control, matrix=list(whole), objectSpace=True)
    return len(controls)


def has_offset_matrix(control: str) -> bool:
    import maya.api.OpenMaya as om
    return not _matrix(control, "offsetParentMatrix").isEquivalent(om.MMatrix(), 1e-6)


# ------------------------------------------------------------------ colors

def index_palette() -> list:
    """Maya's 32 index colors as THIS Maya shows them (its palette may have been edited)."""
    found = []
    for index in range(32):
        try:
            found.append(tuple(cmds.colorIndex(index, query=True)) if index else colors.INDEX_COLORS[0])
        except RuntimeError:
            found.append(colors.INDEX_COLORS[index])
    return found


def _color_nodes(transforms: list, on_shape: bool) -> list:
    """Where a drawing override goes: the curve / any shapes of each transform when `on_shape` (a
    transform without shapes — a joint, a group — takes it itself), else the transforms."""
    nodes = []
    for transform in transforms:
        shapes = (cmds.listRelatives(transform, shapes=True, fullPath=True, noIntermediate=True) or []) if on_shape else []
        nodes.extend(shapes or [transform])
    return nodes


def _set(plug: str, *values, **kwargs) -> bool:
    """setAttr that skips a locked or connected plug instead of raising."""
    try:
        cmds.setAttr(plug, *values, **kwargs)
        return True
    except RuntimeError:
        return False


def color(transforms: list, rgb=None, index: "int | None" = None, viewport: bool = True, outliner: bool = False,
          on_shape: bool = True) -> int:
    """Colors the objects: in the viewport an RGB drawing override (`rgb`) or Maya's index color
    (`index`; 0 = back to the default), on their shapes or themselves; in the Outliner the same color
    (gamma-lifted to read alike). One undo step; how many objects."""
    if not transforms:
        return 0
    with _Chunk():
        if viewport:
            for node in _color_nodes(transforms, on_shape):
                if index is not None:
                    _set(node + ".overrideEnabled", 1 if index else 0)
                    _set(node + ".overrideRGBColors", 0)
                    _set(node + ".overrideColor", index)
                elif rgb is not None:
                    _set(node + ".overrideEnabled", 1)
                    _set(node + ".overrideRGBColors", 1)
                    _set(node + ".overrideColorRGB", *rgb)
        if outliner:
            shown = rgb if rgb is not None else (index_palette()[index] if index else None)
            for transform in transforms:
                if shown is None:
                    _set(transform + ".useOutlinerColor", 0)
                else:
                    _set(transform + ".useOutlinerColor", 1)
                    _set(transform + ".outlinerColor", *colors.to_outliner(shown))
    return len(transforms)


def color_by_side(transforms: list, sides, viewport: bool = True, outliner: bool = False, on_shape: bool = True) -> dict:
    """Each object in its side's color (left / right / center by where it stands). One undo step;
    {side: how many}."""
    counted = {}
    with _Chunk():
        for transform in transforms:
            side = sides.of(position(transform))
            counted[side] = counted.get(side, 0) + 1
            color([transform], rgb=SIDE_COLORS[side], viewport=viewport, outliner=outliner, on_shape=on_shape)
    return counted


def reset_color(transforms: list) -> int:
    """No drawing override on the objects and their shapes, no Outliner color. One undo step."""
    with _Chunk():
        for node in _color_nodes(transforms, True) + list(transforms):
            _set(node + ".overrideEnabled", 0)
            _set(node + ".overrideRGBColors", 0)
            _set(node + ".overrideColor", 0)
        for transform in transforms:
            _set(transform + ".useOutlinerColor", 0)
    return len(transforms)


def read_color(transform: str):
    """(rgb, index) the object is drawn in: its first shape's override, else its own; index None
    for an RGB override; (None, None) when it has none — then its Outliner color if it has one."""
    for node in _color_nodes([transform], True) + [transform]:
        if cmds.getAttr(node + ".overrideEnabled"):
            if cmds.getAttr(node + ".overrideRGBColors"):
                return tuple(cmds.getAttr(node + ".overrideColorRGB")[0]), None
            index = cmds.getAttr(node + ".overrideColor")
            return (index_palette()[index] if index else None), index
    if cmds.getAttr(transform + ".useOutlinerColor"):
        return colors.from_outliner(cmds.getAttr(transform + ".outlinerColor")[0]), None
    return None, None


def set_line_width(transforms: list, width: float) -> int:
    """The curves' line width (-1 = Maya's preference). One undo step; how many shapes."""
    count = 0
    with _Chunk():
        for transform in transforms:
            for shape in curve_shapes(transform):
                count += _set(shape + ".lineWidth", width)
    return count
