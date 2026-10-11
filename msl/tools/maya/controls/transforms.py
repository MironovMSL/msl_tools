# tools/maya/controls/transforms.py
"""Transforms of the selected objects (maya.cmds, no Qt) — the TRANSFORMS card's scene side.

Everything works on a CHOICE OF CHANNELS: {"tx": 1, "ry": -1, …} — the channels taken, each with its
sign (-1 = the value goes over inverted: what a mirrored control needs). In the WORLD the objects are
put where another one stands (Maya's matchTransform, channel by channel; a sign means nothing there);
LOCALLY the channels' own numbers go over.

A POSE is plain data (JSON): [{"name", "values": {channel: number}, "matrix": the world matrix}] —
copied from objects, pasted onto others, in this Maya or another one (it travels as text).

Every change is ONE undo step; an object that can't take it (a locked or driven channel) is left
and named, never raised."""
import json

from maya import cmds

UNDO_NAME = "MSL Controls"
MOVE, TURN, SCALE = ("tx", "ty", "tz"), ("rx", "ry", "rz"), ("sx", "sy", "sz")
CHANNELS = MOVE + TURN + SCALE
POSE_MARK = "msl_pose"
_MATCH_FLAGS = {"tx": "positionX", "ty": "positionY", "tz": "positionZ", "rx": "rotationX", "ry": "rotationY",
                "rz": "rotationZ", "sx": "scaleX", "sy": "scaleY", "sz": "scaleZ"}


class _Chunk:
    def __enter__(self):
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)

    def __exit__(self, *_exc):
        cmds.undoInfo(closeChunk=True)
        return False


def _short(node: str) -> str:
    return node.rpartition("|")[2]


def _bare(name: str) -> str:
    """A name without its path and namespace: how a pose finds its object in another scene."""
    return name.rpartition("|")[2].rpartition(":")[2]


def _can_set(node: str, attr: str) -> bool:
    plug = f"{node}.{attr}"
    if not cmds.attributeQuery(attr, node=node, exists=True) or cmds.getAttr(plug, lock=True):
        return False
    # keys are fine (the value is set at the current time); another connection drives it
    return not any(not cmds.nodeType(source).startswith("animCurve")
                   for source in cmds.listConnections(plug, source=True, destination=False) or [])


def values_of(node: str) -> dict:
    """{channel: its number} of the nine channels the object has."""
    return {attr: float(cmds.getAttr(f"{node}.{attr}")) for attr in CHANNELS
            if cmds.attributeQuery(attr, node=node, exists=True)}


def _set_values(node: str, values: dict, channels: dict) -> tuple:
    """The chosen channels of one object set from `values` (each times its sign). (set, left)."""
    done = left = 0
    for attr, sign in channels.items():
        if attr not in values:
            continue
        if not _can_set(node, attr):
            left += 1
            continue
        try:
            cmds.setAttr(f"{node}.{attr}", values[attr] * (-1.0 if sign < 0 else 1.0))
            done += 1
        except RuntimeError:
            left += 1
    return done, left


def _match_world(node: str, target: str, channels: dict) -> bool:
    flags = {_MATCH_FLAGS[attr]: True for attr in channels if attr in _MATCH_FLAGS}
    if not flags or not all(_can_set(node, attr) for attr in channels):
        return False
    try:
        cmds.matchTransform(node, target, **flags)
        return True
    except RuntimeError:
        return False


# ------------------------------------------------------------------ match, reset, freeze

def match(nodes: list, channels: dict, world: bool = True) -> tuple:
    """Every selected object but the LAST takes the last one's transform on the chosen channels: in
    the world it is put where the last one stands; locally it gets the last one's channel values
    (signs applied). (how many objects, the names left)."""
    if len(nodes) < 2 or not channels:
        return 0, []
    target, done, left = nodes[-1], 0, []
    source = values_of(target)
    with _Chunk():
        for node in nodes[:-1]:
            before = values_of(node)
            if world:
                ok = _match_world(node, target, channels)
            else:
                changed, skipped = _set_values(node, source, channels)
                ok = bool(changed) or not skipped
            if not ok:
                left.append(_short(node))
            elif any(abs(value - before.get(attr, value)) > 1e-6 for attr, value in values_of(node).items()):
                done += 1          # (an object that was there already is not counted: see `matched`)
    return done, left


def matched(nodes: list, channels: dict, world: bool = True) -> int:
    """How many of the selected objects (but the last) ALREADY hold the last one's transform on the
    chosen channels — what a Match that changed nothing has to say."""
    if len(nodes) < 2:
        return 0
    target, count = nodes[-1], 0
    source = values_of(target)
    for node in nodes[:-1]:
        if world:
            import maya.api.OpenMaya as om
            same = om.MMatrix(cmds.getAttr(node + ".worldMatrix[0]")).isEquivalent(
                om.MMatrix(cmds.getAttr(target + ".worldMatrix[0]")), 1e-5)
        else:
            mine = values_of(node)
            same = all(abs(mine.get(attr, 0.0) - source.get(attr, 0.0) * (-1.0 if sign < 0 else 1.0)) <= 1e-6
                       for attr, sign in channels.items())
        count += same
    return count


def reset(nodes: list, channels: dict) -> tuple:
    """The chosen channels back to rest (0, scale 1); a locked or driven one is left.
    (how many channels were changed, how many were left)."""
    done = left = 0
    with _Chunk():
        for node in nodes:
            for attr in channels:
                if not cmds.attributeQuery(attr, node=node, exists=True):
                    continue
                rest = 1.0 if attr in SCALE else 0.0
                plug = f"{node}.{attr}"
                if abs(cmds.getAttr(plug) - rest) <= 1e-9:
                    continue
                if not _can_set(node, attr):
                    left += 1
                    continue
                try:
                    cmds.setAttr(plug, rest)
                    done += 1
                except RuntimeError:
                    left += 1
    return done, left


def freeze(nodes: list, channels: dict) -> tuple:
    """Maya's Freeze Transformations for the GROUPS that have a channel chosen (move, rotate, scale:
    Maya freezes a whole group, not one axis). (how many were frozen, [name: why not])."""
    move, rotate, scale = (any(attr in channels for attr in group) for group in (MOVE, TURN, SCALE))
    done, left = 0, []
    if not (move or rotate or scale):
        return 0, []
    with _Chunk():
        for node in nodes:
            try:
                cmds.makeIdentity(node, apply=True, translate=move, rotate=rotate, scale=scale, normal=0,
                                  preserveNormals=True)
                done += 1
            except RuntimeError as error:
                reason = str(error).strip().splitlines()[-1] if str(error).strip() else "Maya refused"
                left.append(f"{_short(node)}: {reason}")
    return done, left


# ------------------------------------------------------------------ a pose: copied, pasted, kept as text

def pose_of(nodes: list) -> dict:
    """The objects' pose as plain data: each one's name, its nine channel values and where it stands
    in the world."""
    objects = []
    for node in nodes:
        objects.append({"name": _short(node), "values": values_of(node),
                        "matrix": [float(value) for value in cmds.xform(node, query=True, worldSpace=True, matrix=True)]})
    return {POSE_MARK: 1, "objects": objects}


def pose_text(pose: dict) -> str:
    return json.dumps(pose, indent=1)


def pose_from_text(text: str) -> "dict | None":
    """A pose out of a text (the clipboard's, a file's) — None when the text is no pose."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or POSE_MARK not in data or not isinstance(data.get("objects"), list):
        return None
    objects = []
    for entry in data["objects"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("values"), dict):
            continue
        values = {}
        for attr, value in entry["values"].items():
            if attr in CHANNELS and isinstance(value, (int, float)):
                values[attr] = float(value)
        matrix = entry.get("matrix")
        if not (isinstance(matrix, list) and len(matrix) == 16 and all(isinstance(v, (int, float)) for v in matrix)):
            matrix = None
        objects.append({"name": str(entry.get("name", "")), "values": values, "matrix": matrix})
    return {POSE_MARK: 1, "objects": objects} if objects else None


def mirrored_pose(pose: dict, other_name) -> dict:
    """The pose for the OTHER side: every object under its other-side name (`other_name(name)` — the
    Rename tool's rule: lf_arm_ctrl -> rt_arm_ctrl; a name that says no side keeps it, so a middle
    control takes its own values back, inverted where the grid says so). The values themselves are not
    touched here: pasted locally, the channels taken INVERTED go over with the other sign. No world
    matrix is kept — a mirrored pose is a thing of the channels."""
    objects = []
    for entry in pose.get("objects") or []:
        namespace, sep, name = str(entry.get("name", "")).rpartition(":")
        objects.append({"name": namespace + sep + other_name(name), "values": dict(entry.get("values") or {}),
                        "matrix": None})
    return {POSE_MARK: 1, "objects": objects}


def pair_pose(nodes: list, pose: dict) -> tuple:
    """Which copied object each selected one takes: (pairs [(node, entry)], how — "one" / "name" /
    "order" / ""). ONE copied object goes onto every selected one; several are matched by NAME
    (without path and namespace — the same rig in another scene, a referenced copy), and when no
    name fits but there are as many as selected, by the ORDER they were picked in."""
    entries = list(pose.get("objects") or [])
    if not entries or not nodes:
        return [], ""
    if len(entries) == 1:
        return [(node, entries[0]) for node in nodes], "one"
    by_name = {_bare(entry["name"]): entry for entry in entries}
    named = [(node, by_name[_bare(node)]) for node in nodes if _bare(node) in by_name]
    if named:
        return named, "name"
    if len(entries) == len(nodes):
        return list(zip(nodes, entries)), "order"
    return [], ""


def apply_pose(nodes: list, pose: dict, channels: dict, world: bool = False) -> tuple:
    """The copied pose given to the selected objects on the chosen channels (see `pair_pose`). In the
    world each object is put where its copied one STOOD (through a helper placed there, so it works
    whatever the object is parented under — parents first); locally the channel values go over, signs
    applied. (how many objects, the names left, how they were paired)."""
    pairs, how = pair_pose(nodes, pose)
    if not pairs or not channels:
        return 0, [], how
    done, left = 0, []
    with _Chunk():
        helper = None
        try:
            for node, entry in sorted(pairs, key=lambda pair: pair[0].count("|")):
                if world and entry.get("matrix"):
                    if helper is None:
                        helper = cmds.createNode("transform", name="mslPoseHelper#", skipSelect=True)
                    cmds.xform(helper, worldSpace=True, matrix=entry["matrix"])
                    ok = _match_world(node, helper, channels)
                else:
                    changed, skipped = _set_values(node, entry["values"], channels)
                    ok = bool(changed) or not skipped
                if ok:
                    done += 1
                else:
                    left.append(_short(node))
        finally:
            if helper is not None and cmds.objExists(helper):
                cmds.delete(helper)
    return done, left, how


# ------------------------------------------------------------------ from one side to the other

def side_pairs(nodes: list, find_twin) -> list:
    """[(left, right)] of the selected objects and their other-side twins (`find_twin(node)` -> the
    twin's long name or ""), each pair once. LEFT is the one standing further along +X (Maya's
    convention: a character faces +Z, its left is at +X)."""
    pairs, seen = [], set()
    for node in nodes:
        twin = find_twin(node)
        if not twin or twin == node or node in seen or twin in seen:
            continue
        seen.update((node, twin))
        x_node = cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)[0]
        x_twin = cmds.xform(twin, query=True, worldSpace=True, rotatePivot=True)[0]
        pairs.append((node, twin) if x_node >= x_twin else (twin, node))
    return pairs


def transfer_sides(pairs: list, direction: str, channels: dict) -> tuple:
    """The chosen channels' values carried between the two sides of each pair (their own numbers,
    signs applied): "left" -> the left one's onto the right, "right" -> the other way, "swap" -> both
    exchange. (how many pairs, the names left)."""
    done, left = 0, []
    with _Chunk():
        for one, other in pairs:
            first, second = values_of(one), values_of(other)
            jobs = {"left": [(other, first)], "right": [(one, second)],
                    "swap": [(other, first), (one, second)]}[direction]
            ok = True
            for node, values in jobs:
                changed, skipped = _set_values(node, values, channels)
                if skipped and not changed:
                    ok = False
                    left.append(_short(node))
            done += ok
    return done, left
