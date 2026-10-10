# tools/maya/controls/scene.py
"""The Maya side of the Controls tool (maya.cmds, no Qt): building controls from shapes, placing
them on what is selected, their offsets (groups or the offsetParentMatrix), editing their shapes.
Every action the user starts is ONE undo step (`_Chunk`)."""
import re
from collections import namedtuple

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
        elif degree == 1 and len(points) > 3 and all(abs(a - b) < 1e-6 for a, b in zip(points[0], points[-1])):
            # a polygon: Maya keeps it as an OPEN line that ends where it starts (so do we, when we
            # build one) — as a shape it is closed, without the repeated point: moving its first
            # corner in the editor must not leave the last one behind and open it
            curves.append(shape_data.Curve(points[:-1], 1, True))
        else:
            curves.append(shape_data.Curve(points, degree, False))
    return curves


def position(transform: str):
    return tuple(cmds.xform(transform, query=True, worldSpace=True, rotatePivot=True))


FIT_ROOM = 1.2          # a fitted control stands this much clear of what it is made for
BOX_SHAPES = 300        # an object with more shapes under it than this is measured by Maya's own box


def _placed(node: str):
    """The node's world matrix without its scale and shear: where a control matched to it stands."""
    import maya.api.OpenMaya as om
    placed = om.MTransformationMatrix(_matrix(node))
    placed.setScale((1.0, 1.0, 1.0), om.MSpace.kWorld)
    placed.setShear((0.0, 0.0, 0.0), om.MSpace.kWorld)
    return placed.asMatrix()


def local_box(target: str) -> "tuple | None":
    """The box around the object AND everything under it (a group has no shape of its own), in the
    object's OWN axes and in world units — (x0, y0, z0, x1, y1, z1) about its pivot; a turned object
    doesn't swell it, as a world box would. None when there is nothing to measure."""
    import maya.api.OpenMaya as om
    below = cmds.listRelatives(target, allDescendents=True, fullPath=True) or []
    shapes = cmds.ls(below, shapes=True, long=True, noIntermediate=True) if below else []
    if not shapes:
        return None
    frame = _placed(target).inverse()
    low, high = [float("inf")] * 3, [float("-inf")] * 3
    if len(shapes) > BOX_SHAPES:
        box = cmds.exactWorldBoundingBox(target)
        corners = [om.MPoint(x, y, z) * frame for x in (box[0], box[3]) for y in (box[1], box[4])
                   for z in (box[2], box[5])]
    else:
        corners = []
        for shape in shapes:
            a, b = cmds.getAttr(shape + ".boundingBoxMin")[0], cmds.getAttr(shape + ".boundingBoxMax")[0]
            if any(lo > hi for lo, hi in zip(a, b)):
                continue                # an empty shape
            holder = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
            to_frame = _matrix(holder) * frame
            corners += [om.MPoint(x, y, z) * to_frame for x in (a[0], b[0]) for y in (a[1], b[1])
                        for z in (a[2], b[2])]
    if not corners:
        return None
    # about the PIVOT, not the transform's origin: a control is matched to the rotate pivot
    pivot = om.MPoint(*position(target)) * frame
    for corner in corners:
        for index, value in enumerate((corner.x - pivot.x, corner.y - pivot.y, corner.z - pivot.z)):
            low[index], high[index] = min(low[index], value), max(high[index], value)
    return tuple(low) + tuple(high)


def fit_size(target: str, axis: "str | None" = None) -> float:
    """How big a control for `target` reads well; 1 when there is nothing to measure.
    A joint: by its radius. Anything else: by its box in its own axes (`local_box`: its children
    counted, its turn not), ACROSS the axis the control faces — a ring around a long cylinder fits
    its girth, not its length (`axis` None: its longest side) — reaching from the pivot to the box's
    far side plus a little room, but never more than the box is wide (a pivot far away)."""
    if cmds.objectType(target, isAType="joint"):
        return max(0.1, cmds.getAttr(target + ".radius") * 2.0)
    box = local_box(target)
    if box is None:
        return 1.0
    across = [index for index in range(3) if axis not in AXIS_INDEX or index != AXIS_INDEX[axis]]
    reach = 0.0
    for wanted in (across, [0, 1, 2]):          # a box flat across the axis: its longest side after all
        for index in wanted:
            low, high = box[index], box[index + 3]
            reach = max(reach, min(max(abs(low), abs(high)), high - low))
        if reach > 1e-6:
            return reach * FIT_ROOM
    return 1.0


AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


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
        if cmds.objectType(control, isAType="joint"):
            # a control that is a joint: Maya keeps its turn in jointOrient when it is parented — the
            # group above it holds the turn now, so that is zero too
            cmds.setAttr(control + ".jointOrient", 0, 0, 0)
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
    if cmds.objectType(control, isAType="joint"):
        cmds.setAttr(control + ".jointOrient", 0, 0, 0)       # it was part of the local matrix just moved


def _uuid(node: str) -> str:
    return cmds.ls(node, uuid=True)[0]


def _path(uuid: str) -> str:
    """The long name NOW of the node with this uuid (parenting changes long names)."""
    found = cmds.ls(uuid, long=True) or []
    return found[0] if found else ""


DRIVES = ("none", "shape", "constraint", "matrix")


def target_look(target: str, axis: "str | None" = None) -> dict:
    """What a preview needs to draw the object a control is made for, in the object's OWN axes (a
    control matched to it has the same): its kind ("joint" with `radius` and `bones` = where its child
    joints are; else "box" with `local_box`, or "null"), its short `name`, world `position` and `fit`
    (fit_size for a control facing `axis`)."""
    look = {"name": target.rpartition("|")[2], "position": position(target), "fit": fit_size(target, axis),
            "kind": "null"}
    if cmds.objectType(target, isAType="joint"):
        children = cmds.listRelatives(target, children=True, type="joint", fullPath=True) or []
        look.update(kind="joint", radius=cmds.getAttr(target + ".radius"),
                    bones=[tuple(cmds.getAttr(child + ".translate")[0]) for child in children[:6]])
    else:
        box = local_box(target)
        if box is not None:
            look.update(kind="box", box=box)
    return look


def targets_look(targets: list, limit: int = 12, axis: "str | None" = None) -> list:
    """`target_look` of the first `limit` targets, each with `matrix` — where it stands in the FIRST
    one's axes (position and rotation only, 16 numbers) — and `parent`: the index of the nearest listed
    target above it, -1 for none (whose control a chained control goes under). A target may be a Part
    (see `selection_targets`): its kind is "part"."""
    import maya.api.OpenMaya as om
    shown = list(targets[:limit])
    looks, base = [], None
    for target in shown:
        if isinstance(target, Part):
            look = {"name": target.label, "position": target.position, "fit": part_size(target), "kind": "part"}
            world = om.MMatrix(target.matrix)
            if base is None:
                base = world.inverse()
            look["matrix"] = list(world * base)
            look["parent"] = -1
            looks.append(look)
            continue
        look = target_look(target, axis)
        world = _placed(target)
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
           drive: str = "none", notes: "list | None" = None, rgb=None, as_joint: bool = False,
           hide_joint: bool = False) -> list:
    """A control of `shape` for each target (or one at the origin): named by the template, as big
    as `size` (times the target's own size when `fit`), facing `axis`, matched to the target's
    position and rotation; its offsets (`offset_mode` "groups" / "matrix" / "none"); under the
    control of the nearest target above it when `chain`; colored by its side (`side_color`), else in
    `rgb` if given, else left in Maya's default color.

    `drive` = what the control does to its target: "none" (it only stands there), "constraint"
    (parent + scale constraints), "matrix" (through the target's offsetParentMatrix, no constraint
    node), or "shape" — no new object at all: the curves become shapes of the target itself (a joint
    picked by its own curve). Targets that can't be driven (locked or connected channels) are named
    in `notes`.

    A target may be a Part (a vertex, an edge, a face… — see `selection_targets`): the control stands
    where the part is, turned as the Part says (on a mesh: facing away from the surface), "fit" is
    the part's own size; a part can't be driven, chained or given the curve.

    `as_joint`: each control is a JOINT node (its bone not drawn, only its curve) instead of a plain
    transform — rigs built of joints all through; its zero groups stay plain groups. `hide_joint`
    (with drive "shape"): the joint that gets the curve stops drawing its bone. One undo step.
    Returns the controls (long names)."""
    made = []           # (target, control uuid)
    whole = [target for target in targets if not isinstance(target, Part)]
    if drive == "shape" and whole:
        return shapes_onto(shape, whole, size, axis, fit, side_color, sides, rgb, hide_joint)
    with _Chunk():
        for index, target in enumerate(targets or [None]):
            part = target if isinstance(target, Part) else None
            target = None if part else target
            where = part.position if part else (position(target) if target else None)
            label = part.label if part else (target.rpartition("|")[2] if target else "")
            name = control_name(template, label, where, sides, index + 1)
            own = part_size(part) if part else (fit_size(target, axis) if target else 1.0)
            scale = size * (own if fit else 1.0)
            curves = shape_data.scaled(shape_data.oriented(shape.curves, axis), scale)
            control = cmds.ls(cmds.createNode("joint" if as_joint else "transform", name=name, skipSelect=True),
                              long=True)[0]
            if as_joint:
                cmds.setAttr(control + ".drawStyle", JOINT_HIDDEN)
            add_shapes(control, curves)
            if part:
                cmds.xform(control, worldSpace=True, matrix=list(part.matrix))
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


JOINT_AS_BONE, JOINT_HIDDEN = 0, 2          # a joint's drawStyle: Bone / None


def shapes_onto(shape: shape_data.Shape, targets: list, size: float, axis: str, fit: bool, side_color: bool,
                sides, rgb=None, hide_joint: bool = False) -> list:
    """The curves as shapes OF the targets themselves (no control object): a joint that is picked
    and animated by its own curve. A target that wears a curve already gets this one INSTEAD (its
    color kept) — doing it twice doesn't pile curves up. `hide_joint`: the joint's own bone is no
    longer drawn (drawStyle None), only its curve. One undo step; the targets."""
    with _Chunk():
        for target in targets:
            scale = size * (fit_size(target, axis) if fit else 1.0)
            curves = shape_data.scaled(shape_data.oriented(shape.curves, axis), scale)
            if curve_shapes(target):
                _swap_shapes(target, curves)
            else:
                made = add_shapes(target, curves)
                color = SIDE_COLORS[sides.of(position(target))] if side_color else rgb
                if color is not None:
                    for node in made:
                        cmds.setAttr(node + ".overrideEnabled", 1)
                        cmds.setAttr(node + ".overrideRGBColors", 1)
                        cmds.setAttr(node + ".overrideColorRGB", *color)
            if hide_joint and cmds.objectType(target, isAType="joint"):
                _set(target + ".drawStyle", JOINT_HIDDEN)
        cmds.select(targets, replace=True)
    return list(targets)


def joint_controls(nodes: list) -> list:
    """The joints among `nodes` that wear a curve: joints that are controls."""
    return [node for node in nodes if cmds.objectType(node, isAType="joint") and curve_shapes(node)]


def bones_hidden(joints: list) -> bool:
    """True when none of these joints draws its bone (drawStyle None)."""
    return bool(joints) and all(cmds.getAttr(joint + ".drawStyle") == JOINT_HIDDEN for joint in joints)


def set_bones_hidden(joints: list, hidden: bool) -> int:
    """The joints draw their bones again, or stop (only their curves are seen). One undo step."""
    with _Chunk():
        done = sum(_set(joint + ".drawStyle", JOINT_HIDDEN if hidden else JOINT_AS_BONE) for joint in joints)
    return done


def strip_shapes(nodes: list) -> list:
    """The curves taken OFF the objects again: their curve shapes are removed; a joint is drawn as a
    bone again. What Drive = Shape did, undone (a plain control is left an empty transform).
    One undo step; the objects that had a curve (short names)."""
    stripped = []
    with _Chunk():
        for node in nodes:
            shapes = curve_shapes(node)
            if not shapes:
                continue
            cmds.delete(shapes)
            if cmds.objectType(node, isAType="joint"):
                _set(node + ".drawStyle", JOINT_AS_BONE)
            stripped.append(node.rpartition("|")[2])
    return stripped


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


# ------------------------------------------------------------------ driving with controls that exist

def find_target(control: str) -> tuple:
    """The object a control was made for, found by its NAME: lf_arm_ctrl -> the one transform called
    lf_arm or lf_arm_<something> that is no control and no group of the control's own (a joint is
    preferred when there are several). Returns (target or "", why not)."""
    short = control.rpartition("|")[2]
    namespace, sep, name = short.rpartition(":")
    stem = name.rpartition("_")[0] or name
    found = []
    for pattern in (stem, stem + "_*"):
        found += cmds.ls(namespace + sep + pattern, long=True, type="transform") or []
    pool = []
    for node in found:
        if node == control or node in pool or is_ghost(node) or curve_shapes(node):
            continue
        if control.startswith(node + "|") or node.startswith(control + "|"):
            continue                # its zero groups above it, what hangs under it
        pool.append(node)
    joints = [node for node in pool if cmds.objectType(node, isAType="joint")]
    pool = joints or pool
    if len(pool) == 1:
        return pool[0], ""
    return "", f"nothing is called {stem}_…" if not pool else f"{len(pool)} objects are called {stem}_…"


def pair_up(selected: list) -> tuple:
    """(control, object) pairs out of a selection, and what couldn't be paired (texts):
    only controls selected -> each with the object found by its name (`find_target`);
    controls AND objects -> by the order they were picked in: the 1st control with the 1st object…,
    or ONE control with every object."""
    controls = [node for node in selected if curve_shapes(node)]
    objects = [node for node in selected if not curve_shapes(node)]
    if not controls:
        return [], ["select a control (its object is found by its name), or a control and its object"]
    if not objects:
        pairs, problems = [], []
        for control in controls:
            target, why = find_target(control)
            if target:
                pairs.append((control, target))
            else:
                problems.append(f"{control.rpartition('|')[2]}: {why}")
        return pairs, problems
    if len(controls) == 1:
        return [(controls[0], target) for target in objects], []
    if len(controls) != len(objects):
        return [], [f"{len(controls)} controls and {len(objects)} objects: pick as many of each, or one control"]
    return list(zip(controls, objects)), []


def drive_pairs(pairs: list, mode: str, notes: "list | None" = None) -> int:
    """Each object follows its control from now on — `mode` "constraint" or "matrix" — staying where
    it is. One undo step; how many were tied. What couldn't be is named in `notes`."""
    tie = drive_by_constraint if mode == "constraint" else drive_by_matrix
    done = 0
    with _Chunk():
        for control, target in pairs:
            problem = tie(control, target)
            if problem:
                if notes is not None:
                    notes.append(f"{target.rpartition('|')[2]}: {problem}")
            else:
                done += 1
    return done


def _drivers(target: str) -> list:
    """What ties `target` to controls: (the node to remove, the controls it reads) for its parent /
    scale constraints and for a multMatrix into its offsetParentMatrix."""
    found = []
    for node in cmds.listRelatives(target, children=True, fullPath=True,
                                   type=("parentConstraint", "scaleConstraint")) or []:
        sources = cmds.listConnections(node + ".target", source=True, destination=False) or []
        found.append((node, {each for each in cmds.ls(sources, long=True) if each != node}))
    for node in cmds.listConnections(target + ".offsetParentMatrix", source=True, destination=False,
                                     type="multMatrix") or []:
        sources = cmds.listConnections(node + ".matrixIn", source=True, destination=False) or []
        found.append((node, set(cmds.ls(sources, long=True))))
    return found


def driven_by(control: str) -> list:
    """The objects this control drives (through a constraint or the matrix), long names."""
    found = []
    for node in set(cmds.listConnections(control, source=False, destination=True,
                                         type="constraint") or []):
        found += cmds.listRelatives(node, parent=True, fullPath=True) or []
    for node in set(cmds.listConnections(control + ".worldMatrix", source=False, destination=True,
                                         type="multMatrix") or []):
        found += cmds.ls(cmds.listConnections(node + ".matrixSum", source=False, destination=True) or [], long=True)
    return [node for index, node in enumerate(found) if node != control and node not in found[:index]]


def _untie(target: str, control: "str | None" = None) -> int:
    """Removes what ties `target` to `control` (to any control when None); it stays where it stands."""
    removed = 0
    for node, controls in _drivers(target):
        if control is not None and control not in controls:
            continue
        if cmds.nodeType(node) == "multMatrix":
            world = cmds.xform(target, query=True, worldSpace=True, matrix=True)
            cmds.disconnectAttr(node + ".matrixSum", target + ".offsetParentMatrix")
            cmds.setAttr(target + ".offsetParentMatrix", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], type="matrix")
            cmds.xform(target, worldSpace=True, matrix=world)
        if cmds.objExists(node):
            cmds.delete(node)
        removed += 1
    return removed


def undrive(selected: list) -> list:
    """Unties what is selected, from either end: a selected OBJECT is freed of every control that
    drives it; a selected CONTROL lets go of every object it drives. The objects stay where they
    stand. One undo step; the objects that were freed (short names)."""
    freed = []
    with _Chunk():
        for node in selected:
            if _untie(node):
                freed.append(node)
            for target in driven_by(node):
                if _untie(target, node) and target not in freed:
                    freed.append(target)
    return [node.rpartition("|")[2] for node in freed]


def links_of(control: str) -> dict:
    """What a control that EXISTS is tied into: {"groups": its zero groups, top first,
    "matrix_zero": it is zeroed in its offsetParentMatrix, "driven": [(object, "constraint" /
    "matrix")] it drives}."""
    driven = []
    for target in driven_by(control):
        kinds = {cmds.nodeType(driver) for driver, controls in _drivers(target) if control in controls}
        driven.append((target, "matrix" if "multMatrix" in kinds else "constraint"))
    held = has_offset_matrix(control) and not cmds.listConnections(control + ".offsetParentMatrix", source=True,
                                                                   destination=False)
    return {"groups": _zero_stack(control), "matrix_zero": bool(held), "driven": driven}


def flat_axis(control: str) -> str:
    """The axis a control's shape faces: the one its CVs hardly leave ("Y" for a shape with depth)."""
    points = [point for shape in curve_shapes(control) for point in _points(shape)]
    if not points:
        return "Y"
    extents = [max(point[i] for point in points) - min(point[i] for point in points) for i in range(3)]
    thin = min(range(3), key=lambda index: extents[index])
    return "XYZ"[thin] if extents[thin] < 0.15 * max(extents) else "Y"


def world_reach(control: str) -> float:
    """How far the control's shape reaches from its pivot, in world units."""
    import maya.api.OpenMaya as om
    scale = om.MTransformationMatrix(_matrix(control)).scale(om.MSpace.kWorld)
    return _reach(control) * max(abs(value) for value in scale)


# ------------------------------------------------------------------ where the selection is

PARTS_AT_ONCE = 200         # this many selected objects / points / edges / faces are worked on at a time
LOCATORS_AT_ONCE = PARTS_AT_ONCE

# One selected thing, where it is: `owner` = the object it belongs to, `position` in the world, `source`
# = the object to take the turn from ("" for a PART of an object), `normal` = the surface's unit normal
# there (a part of a mesh, when asked for), `size` = the part's own size (when asked for), `item` =
# what was selected.
Spot = namedtuple("Spot", "owner position source normal size item")
# A part of an object as something Create works on, in place of an object: `label` = what the control
# is named after, `matrix` = where it stands and how it is turned (16 numbers), `size` = what "fit"
# multiplies by (0 = unknown), `item` = what to select when its ghost is picked (a name or several).
Part = namedtuple("Part", "label position matrix size owner item")

_RANGE = re.compile(r"^(.*)\.(vtx|e|f)\[(\d+)(?::(\d+))?\]$")
_MESH_PART = re.compile(r"^(vtx|e|f)\[(\d+)\]$")


def _name_stem(owner: str) -> str:
    """The object's short name without its namespace and its kind suffix: lf_arm_jnt -> lf_arm."""
    from msl_tools.msl.tools.maya.controls.naming import EXTRA_ENDS
    from msl_tools.msl.tools.maya.rename import rules
    short = owner.rpartition("|")[2].rpartition(":")[2]
    stem, sep, tail = short.rpartition("_")
    ends = set(rules.DEFAULT_TYPE_SUFFIXES.values()) | set(EXTRA_ENDS)
    return stem if (sep and stem and tail in ends) else short


def _picked(limit: int) -> tuple:
    """The selection in the order picked, the ranges of mesh parts opened up — but never more than
    `limit` names: all the vertices of a mesh are a hundred thousand, and this runs on every change
    of the selection. Returns (the names, how many things are selected)."""
    items, total = [], 0
    for item in cmds.ls(orderedSelection=True, long=True) or []:
        match = _RANGE.match(item)
        if match:
            first = int(match.group(3))
            last = int(match.group(4) or first)
            total += last - first + 1
            for index in range(first, min(last, first + limit - len(items) - 1) + 1):
                items.append(f"{match.group(1)}.{match.group(2)}[{index}]")
        elif "." in item:
            flat = cmds.ls(item, flatten=True, long=True) or []
            total += len(flat)
            items.extend(flat[:max(0, limit - len(items))])
        else:
            total += 1
            if len(items) < limit:
                items.append(item)
    return items, total


class _Meshes:
    """The meshes of one reading of the selection, asked through the API: quick for hundreds of parts."""

    def __init__(self):
        self._found = {}

    def of(self, node: str):
        """(dag path, MFnMesh) of the mesh `node` is or holds; None when it is no mesh."""
        if node not in self._found:
            import maya.api.OpenMaya as om
            entry = None
            try:
                shape = node
                if not cmds.objectType(node, isAType="shape"):
                    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, type="mesh", fullPath=True) or []
                    shape = shapes[0] if shapes else ""
                if shape and cmds.nodeType(shape) == "mesh":
                    dag = om.MSelectionList().add(shape).getDagPath(0)
                    entry = (dag, om.MFnMesh(dag))
            except (RuntimeError, ValueError):
                entry = None
            self._found[node] = entry
        return self._found[node]


def _mesh_part(mesh, kind: str, index: int, normals: bool, sizes: bool) -> tuple:
    """(where, the normal or None, its own size) of a vertex / an edge / a face, in the world.
    Its size: a face = from its middle to its farthest corner; an edge = half its length; a vertex =
    half the way to its neighbours (controls on neighbouring vertices just touch)."""
    import maya.api.OpenMaya as om
    dag, mesh_fn = mesh
    world = om.MSpace.kWorld
    normal, size = None, 0.0
    if kind == "vtx":
        where = mesh_fn.getPoint(index, world)
        if normals:
            normal = mesh_fn.getVertexNormal(index, True, world)
        if sizes:
            walker = om.MItMeshVertex(dag)
            walker.setIndex(index)
            near = list(walker.getConnectedVertices())
            if near:
                size = 0.5 * sum(where.distanceTo(mesh_fn.getPoint(other, world)) for other in near) / len(near)
    elif kind == "e":
        walker = om.MItMeshEdge(dag)
        walker.setIndex(index)
        a, b = walker.point(0, world), walker.point(1, world)
        where = om.MPoint((a.x + b.x) / 2.0, (a.y + b.y) / 2.0, (a.z + b.z) / 2.0)
        if normals:
            normal = mesh_fn.getVertexNormal(walker.vertexId(0), True, world) + \
                mesh_fn.getVertexNormal(walker.vertexId(1), True, world)
        size = a.distanceTo(b) / 2.0
    else:
        corners = [mesh_fn.getPoint(corner, world) for corner in mesh_fn.getPolygonVertices(index)]
        where = om.MPoint(sum(p.x for p in corners) / len(corners), sum(p.y for p in corners) / len(corners),
                          sum(p.z for p in corners) / len(corners))
        if normals:
            normal = mesh_fn.getPolygonNormal(index, world)
        size = max(where.distanceTo(corner) for corner in corners)
    if normal is not None:
        normal = om.MVector(normal)
        normal = None if normal.length() < 1e-9 else tuple(normal.normal())
    return (where.x, where.y, where.z), normal, size


def selection_spots(normals: bool = False, sizes: bool = False, limit: int = PARTS_AT_ONCE) -> tuple:
    """Where the selection is, one Spot per selected thing, in the order picked — at most `limit` of
    them — and how many things are selected in all.
    An object = its pivot, and its turn; a vertex, a CV, a lattice point = where it is (a UV: its
    vertex — Maya's xform answers that); an edge or a face = the middle of its points. For the parts
    of a mesh, when asked: the surface's `normal` there and the part's own `size`."""
    items, total = _picked(limit)
    meshes = _Meshes()
    spots = []
    for item in items:
        node, dot, part = item.partition(".")
        if is_ghost(node) or not cmds.objExists(node):
            continue
        owner = node
        if cmds.objectType(node, isAType="shape"):
            owner = (cmds.listRelatives(node, parent=True, fullPath=True) or [""])[0]
        if not owner or not cmds.objectType(owner, isAType="transform"):
            continue
        if not dot:
            spots.append(Spot(owner, position(owner), owner, None, 0.0, item))
            continue
        match = _MESH_PART.match(part)
        mesh = meshes.of(node) if match else None
        if mesh:
            try:
                where, normal, size = _mesh_part(mesh, match.group(1), int(match.group(2)), normals, sizes)
            except (RuntimeError, ValueError, IndexError):
                continue
            spots.append(Spot(owner, where, "", normal, size, item))
            continue
        try:
            flat = cmds.xform(item, query=True, worldSpace=True, translation=True) or []
        except RuntimeError:
            continue                # something selected that stands nowhere in the world
        points = [flat[index:index + 3] for index in range(0, len(flat) - 2, 3)]
        if points:
            spots.append(Spot(owner, tuple(sum(point[i] for point in points) / len(points) for i in range(3)),
                              "", None, 0.0, item))
    return spots, total


def part_matrix(where, normal=None, axis: str = "Y") -> tuple:
    """Standing at `where`, the world's axes — or, with a `normal`, its `axis` along it (16 numbers)."""
    x, y, z = shape_data.frame_along(normal, axis) if normal else ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return tuple(x) + (0.0,) + tuple(y) + (0.0,) + tuple(z) + (0.0,) + tuple(where) + (1.0,)


def part_size(part) -> float:
    """What "fit" multiplies by for a part of an object: its own size; a tenth of the object's when
    it has none (a lattice point, a surface's CV)."""
    return part.size if part.size > 1e-6 else 0.1 * fit_size(part.owner)


def _numbered(spots: list) -> list:
    """A name for each spot, after the object it belongs to: lf_arm for the object lf_arm_jnt itself;
    crate_01, crate_02… when several PARTS of one object are among them."""
    parts = {}
    for spot in spots:
        if not spot.source:
            parts[spot.owner] = parts.get(spot.owner, 0) + 1
    numbers, names = {}, []
    for spot in spots:
        name = _name_stem(spot.owner)
        if not spot.source and parts[spot.owner] > 1:
            numbers[spot.owner] = numbers.get(spot.owner, 0) + 1
            name += f"_{numbers[spot.owner]:02d}"
        names.append(name)
    return names


def selection_points() -> tuple:
    """Every POINT of the selection in the world — an object's pivot, a vertex, both ends of an edge,
    the corners of a face — however many there are (Maya is asked once for all the parts), with the
    object the first selected thing belongs to and what is selected."""
    items = [item for item in cmds.ls(orderedSelection=True, long=True) or []
             if not is_ghost(item.partition(".")[0])]
    points, parts, owner = [], [], ""
    for item in items:
        node, dot, _part = item.partition(".")
        if not cmds.objExists(node):
            continue
        holder = node
        if cmds.objectType(node, isAType="shape"):
            holder = (cmds.listRelatives(node, parent=True, fullPath=True) or [""])[0]
        if not holder or not cmds.objectType(holder, isAType="transform"):
            continue
        owner = owner or holder
        if dot:
            parts.append(item)
        else:
            points.append(position(holder))
    flat = []
    if parts:
        try:
            flat = cmds.xform(parts, query=True, worldSpace=True, translation=True) or []
        except RuntimeError:
            for item in parts:              # one of them stands nowhere in the world: the others still do
                try:
                    flat += cmds.xform(item, query=True, worldSpace=True, translation=True) or []
                except RuntimeError:
                    pass
    points += [tuple(flat[index:index + 3]) for index in range(0, len(flat) - 2, 3)]
    return points, owner, tuple(items)


def _middle(points: list) -> tuple:
    """(the middle of the box around the points, the normal of the plane they lie in or None, how far
    the farthest of them is from that middle — across the normal when there is one)."""
    low = [min(point[i] for point in points) for i in range(3)]
    high = [max(point[i] for point in points) for i in range(3)]
    middle = tuple((a + b) / 2.0 for a, b in zip(low, high))
    normal = shape_data.plane_normal(points)
    reach = 0.0
    for point in points:
        away = [a - b for a, b in zip(point, middle)]
        if normal:
            along = sum(a * b for a, b in zip(away, normal))
            away = [a - along * b for a, b in zip(away, normal)]
        reach = max(reach, sum(value * value for value in away) ** 0.5)
    return middle, normal, reach


def selection_targets(axis: str = "Y", middle: bool = False) -> list:
    """What Create works on, in the order picked: an object's long name for each selected object —
    and for the CVs of a curve, which stand for their curve: a control being reshaped must not get
    controls on its points — and a Part for each selected vertex, edge, face, lattice point or surface
    CV (on a mesh it faces away from the surface: its `axis` along the normal there).
    `middle`: ONE Part instead, in the middle of everything selected — it faces across the plane the
    spots lie in and reaches just past them: a ring around a limb from its edge loop."""
    if middle:
        points, owner, items = selection_points()
        if len(points) > 1:
            where, normal, reach = _middle(points)
            return [Part(_name_stem(owner), where, part_matrix(where, normal, axis), reach * FIT_ROOM, owner, items)]
    spots, _total = selection_spots(normals=True, sizes=True)
    if not spots:
        return []
    curves = {}
    for spot in spots:
        if spot.owner not in curves:
            curves[spot.owner] = bool(curve_shapes(spot.owner))
    whole = [bool(spot.source) or curves[spot.owner] for spot in spots]
    names = _numbered([spot for spot, plain in zip(spots, whole) if not plain])
    found = []
    for spot, plain in zip(spots, whole):
        if plain:
            if spot.owner not in found:
                found.append(spot.owner)
        else:
            found.append(Part(names.pop(0), spot.position, part_matrix(spot.position, spot.normal, axis),
                              spot.size, spot.owner, spot.item))
    return found


# ------------------------------------------------------------------ locators and joints on what is selected

def locators_on_selection(center: bool = False, along_normal: bool = False, axis: str = "Y") -> tuple:
    """Locators where the selection is: one on each selected object (at its pivot, turned like it) and
    on each selected vertex, CV, edge or face (its middle), named after the object (lf_arm_jnt ->
    lf_arm_loc; several on one object: head_01_loc, head_02_loc…) — or, `center`, ONE in the middle
    of all of it (the middle of the box around the spots, so an edge loop's center whatever the
    density of its points). `along_normal`: on a mesh the locator's `axis` runs along the surface's
    normal there (the one in the middle: across the plane the spots lie in); else the world's axes.
    At most LOCATORS_AT_ONCE at a time; they end up selected. One undo step.
    Returns (the locators, how many things were selected)."""
    from msl_tools.msl.tools.maya.rename import rules
    suffix = rules.DEFAULT_TYPE_SUFFIXES.get("locator", "loc")
    if center:
        points, owner, items = selection_points()
        if not points:
            return [], 0
        total = _picked(0)[1]               # now: making the locator changes the selection
        with _Chunk():
            where, normal, _reach_out = _middle(points)
            locator = cmds.spaceLocator(name=f"{_name_stem(owner)}_center_{suffix}")[0]
            cmds.xform(locator, worldSpace=True, matrix=list(part_matrix(where, normal if along_normal else None, axis)))
            made = [cmds.ls(locator, long=True)[0]]
            cmds.select(made, replace=True)
        return made, total
    spots, total = selection_spots(normals=along_normal)
    if not spots:
        return [], 0
    made = []
    with _Chunk():
        for spot, name in zip(spots, _numbered(spots)):
            locator = cmds.spaceLocator(name=f"{name}_{suffix}")[0]
            if spot.source:
                cmds.setAttr(locator + ".rotateOrder", cmds.getAttr(spot.source + ".rotateOrder"))
                cmds.matchTransform(locator, spot.source, position=True, rotation=True)
            else:
                cmds.xform(locator, worldSpace=True, matrix=list(part_matrix(spot.position, spot.normal, axis)))
            made.append(cmds.ls(locator, long=True)[0])
        cmds.select(made, replace=True)
    return made, total


def joints_on_selection(chain: bool = True) -> tuple:
    """Joints where the selection is, in the order picked (objects — locators set out for a skeleton —
    or vertices, edges, faces), named after what they stand on (lf_arm_loc -> lf_arm_jnt).
    `chain`: each under the one before it, every bone's X down to the next joint and its Y up (Maya's
    own "orient joint", xyz / yup), the last one as its bone. Not `chain`: separate joints, each
    turned like its object. They end up selected, the first one first. One undo step.
    Returns (the joints, how many things were selected)."""
    from msl_tools.msl.tools.maya.rename import rules
    suffix = rules.DEFAULT_TYPE_SUFFIXES.get("joint", "jnt")
    spots, total = selection_spots()
    if not spots:
        return [], 0
    uuids = []
    with _Chunk():
        for spot, name in zip(spots, _numbered(spots)):
            cmds.select(clear=True)             # else Maya hangs the new joint under what is selected
            joint = cmds.joint(name=f"{name}_{suffix}", position=spot.position)
            uuid = _uuid(joint)
            if chain and uuids:
                cmds.parent(_path(uuid), _path(uuids[-1]))
            elif not chain and spot.source:
                cmds.matchTransform(_path(uuid), spot.source, rotation=True)
                cmds.makeIdentity(_path(uuid), apply=True, rotate=True)     # the turn goes into jointOrient
            uuids.append(uuid)
        if chain and len(uuids) > 1:
            cmds.joint(_path(uuids[0]), edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True,
                       zeroScaleOrient=True)
            cmds.setAttr(_path(uuids[-1]) + ".jointOrient", 0, 0, 0)
        made = [_path(uuid) for uuid in uuids]
        cmds.select(made, replace=True)
    return made, total


def states(selected: list, limit: int = 40) -> dict:
    """What is already true of the selected objects, for the SELECTED buttons to show:
    {"constraint": n, "matrix": n} = how many are tied that way (as the object, or as the control),
    {"zero_groups": n, "zero_matrix": n} = how many are zeroed that way, {"on_top": n}."""
    found = {"constraint": 0, "matrix": 0, "zero_groups": 0, "zero_matrix": 0, "on_top": 0}
    for node in selected[:limit]:
        kinds = {cmds.nodeType(driver) for driver, _controls in _drivers(node)}
        for target in driven_by(node):
            kinds |= {cmds.nodeType(driver) for driver, controls in _drivers(target) if node in controls}
        found["matrix"] += "multMatrix" in kinds
        found["constraint"] += bool(kinds - {"multMatrix"})
        found["zero_groups"] += bool(_zero_stack(node))
        if has_offset_matrix(node) and not cmds.listConnections(node + ".offsetParentMatrix", source=True,
                                                                 destination=False):
            found["zero_matrix"] += 1
        shapes = curve_shapes(node)
        found["on_top"] += bool(shapes) and all(
            cmds.attributeQuery("alwaysDrawOnTop", node=shape, exists=True) and cmds.getAttr(shape + ".alwaysDrawOnTop")
            for shape in shapes)
    return found


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


def shift(controls: list, offset) -> int:
    """Every CV of the controls' shapes moved by `offset` in the control's OWN axes: the shape goes
    off its pivot (or back), the control and its channels stay. One undo step; how many shapes."""
    return edit_points(controls, lambda points: [tuple(a + b for a, b in zip(point, offset)) for point in points])


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


def twin_name(control: str, sides, axis: str = "X") -> str:
    """What the control's mirror is called (short, with its namespace): the other side's name by the
    Rename tool's rules (lf_arm_ctrl -> rt_arm_ctrl, arm_L -> arm_R). A name that says NO side — a
    control not named yet — gets the side word of where its mirror stands in front (arm_ctrl at +X ->
    rt_arm_ctrl), or "_mirror" at its end when the mirror stands on the same side (a control in the
    middle, a mirror across Y or Z)."""
    from msl_tools.msl.tools.maya.rename import rules
    short = control.rpartition("|")[2]
    namespace, sep, name = short.rpartition(":")
    other = rules.mirror(name, sides)
    if other == name:
        here = position(control)
        there = tuple(value * sign for value, sign in zip(here, _REFLECT[axis]))
        word = sides.text(there)
        other = f"{word}_{name}" if (word and sides.of(there) != sides.of(here)) else f"{name}_mirror"
    return namespace + sep + other


def other_side(control: str, sides, axis: str = "X") -> str:
    """The long name of the control's mirror (`twin_name`) when it is in the scene, else ""."""
    found = cmds.ls(twin_name(control, sides, axis), long=True, type="transform") or []
    return found[0] if len(found) == 1 and found[0] != control else ""


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
    the source zeroes through is used the same way. A control whose name says no side is mirrored too
    (see `twin_name`). Returns the new control."""
    import maya.api.OpenMaya as om
    short = control.rpartition("|")[2]
    mirrored = twin_name(control, sides, axis)
    stack = _zero_stack(control)
    above = _mirrored_parent(stack[0] if stack else control, sides)
    made = None
    for node in stack + [control]:
        world = _behavior_mirror(om.MMatrix(cmds.getAttr(node + ".worldMatrix[0]")), axis)
        # its zero groups are named after it (<control>_offset): after its mirror, too
        name = mirrored if node == control else mirrored + node.rpartition("|")[2][len(short):]
        copy = cmds.createNode(cmds.nodeType(node), name=name, skipSelect=True)
        copy = cmds.ls(copy, long=True)[0]
        if cmds.objectType(node, isAType="joint"):          # a joint control: its copy is drawn (or not) alike
            cmds.setAttr(copy + ".drawStyle", cmds.getAttr(node + ".drawStyle"))
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
            twin = other_side(control, sides, axis)
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
            twin = other_side(control, sides, axis)
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
