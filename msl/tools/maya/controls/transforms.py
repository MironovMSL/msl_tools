# tools/maya/controls/transforms.py
"""Transforms of the selected objects (maya.cmds, no Qt) — the TRANSFORMS card's scene side: match
objects to another one, values back to rest, freeze, and a place in the world copied from one object
and given to others. Every change is ONE undo step; an object that can't take it (locked or
connected channels) is left and named, never raised."""
from maya import cmds

UNDO_NAME = "MSL Controls"
MOVE, TURN, SCALE = ("tx", "ty", "tz"), ("rx", "ry", "rz"), ("sx", "sy", "sz")
PARTS = {"move": MOVE, "rotate": TURN, "scale": SCALE}


class _Chunk:
    def __enter__(self):
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)

    def __exit__(self, *_exc):
        cmds.undoInfo(closeChunk=True)
        return False


def _short(node: str) -> str:
    return node.rpartition("|")[2]


def _free(node: str, attrs) -> bool:
    """Can these channels be set: none locked, none fed by a connection."""
    for attr in attrs:
        plug = f"{node}.{attr}"
        if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, source=True, destination=False):
            return False
    return True


def _attrs(move: bool, rotate: bool, scale: bool) -> tuple:
    return (MOVE if move else ()) + (TURN if rotate else ()) + (SCALE if scale else ())


def match(nodes: list, move: bool = True, rotate: bool = True, scale: bool = False) -> tuple:
    """Every selected object but the LAST is put where the last one is — its place, its turn and / or
    its scale, in the world (Maya's matchTransform). (how many were matched, the names left: locked or
    driven channels)."""
    if len(nodes) < 2:
        return 0, []
    target, done, left = nodes[-1], 0, []
    with _Chunk():
        for node in nodes[:-1]:
            if not _free(node, _attrs(move, rotate, scale)):
                left.append(_short(node))
                continue
            try:
                cmds.matchTransform(node, target, position=move, rotation=rotate, scale=scale)
                done += 1
            except RuntimeError:
                left.append(_short(node))
    return done, left


def reset(nodes: list, move: bool = True, rotate: bool = True, scale: bool = True) -> tuple:
    """Move and rotate back to 0, scale to 1 — channel by channel; a locked or driven one is left.
    (how many channels were changed, how many were left)."""
    done = left = 0
    with _Chunk():
        for node in nodes:
            for attr in _attrs(move, rotate, scale):
                plug = f"{node}.{attr}"
                if not cmds.attributeQuery(attr, node=node, exists=True):
                    continue
                if not _free(node, (attr,)):
                    left += 1
                    continue
                rest = 1.0 if attr in SCALE else 0.0
                if abs(cmds.getAttr(plug) - rest) > 1e-9:
                    try:
                        cmds.setAttr(plug, rest)
                        done += 1
                    except RuntimeError:
                        left += 1
    return done, left


def freeze(nodes: list, move: bool = True, rotate: bool = True, scale: bool = True) -> tuple:
    """Maya's Freeze Transformations: what the channels hold is baked into the object (its points, a
    joint's orient) and the channels read rest again. (how many were frozen, [name: why not])."""
    done, left = 0, []
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


def world_place(node: str) -> dict:
    """Where an object stands in the world, to be given to others: its world matrix (and its name,
    for the status line). Plain data."""
    return {"name": _short(node), "matrix": [float(value) for value in cmds.xform(node, query=True, worldSpace=True,
                                                                                    matrix=True)]}


def set_world_place(nodes: list, place: dict) -> tuple:
    """The copied place given to every object: each stands, turns and is scaled in the WORLD as the
    copied one did, whatever it is parented under. Parents first (a child set before its parent would
    be carried away again). (how many, the names left)."""
    done, left = 0, []
    matrix = list(place.get("matrix") or [])
    if len(matrix) != 16:
        return 0, [_short(node) for node in nodes]
    with _Chunk():
        for node in sorted(nodes, key=lambda path: path.count("|")):
            if not _free(node, MOVE + TURN + SCALE):
                left.append(_short(node))
                continue
            try:
                cmds.xform(node, worldSpace=True, matrix=matrix)
                done += 1
            except RuntimeError:
                left.append(_short(node))
    return done, left
