# tools/maya/rename/scene.py
"""The Maya side of the rename tool (maya.cmds, no Qt): which objects, what they are, and the
rename itself.

Objects are carried by their UUID: a rename changes the long names of everything below the renamed
object, a UUID stays. One operation = ONE undo step (an undo chunk), whatever the number of
objects. A namespace is kept unless the change asks to drop it. A shape is never in the list when
its transform is: Maya renames the shape with it ("armShape").
"""
from __future__ import annotations

from maya import cmds

from msl_tools.msl.tools.maya.rename.rules import Change, Node

SCOPE_SELECTED = "Selected"
SCOPE_HIERARCHY = "Hierarchy"
SCOPE_ALL = "All"
SCOPES = (SCOPE_SELECTED, SCOPE_HIERARCHY, SCOPE_ALL)

UNDO_NAME = "MSL Rename"


def selection() -> list[str]:
    """Long names of the selected objects, in the order they were selected (the window switches
    Maya's "track selection order" on; without it the order is Maya's own)."""
    plain = cmds.ls(selection=True, long=True) or []
    ordered = cmds.ls(orderedSelection=True, long=True) or []
    return ordered if set(ordered) == set(plain) else plain


def paths(scope: str = SCOPE_SELECTED) -> list[str]:
    """Long names of the objects `scope` takes: the selection; the selection with everything below
    it (shapes left to their transforms); every renameable node of the scene."""
    if scope == SCOPE_ALL:
        found = cmds.ls(long=True) or []
        skip = set(cmds.ls(defaultNodes=True) or []) | set(cmds.ls(readOnly=True, long=True) or [])
        found = [path for path in found if path not in skip]
    elif scope == SCOPE_HIERARCHY:
        found = []
        for path in selection():
            found.append(path)
            below = cmds.listRelatives(path, allDescendents=True, fullPath=True) or []
            found.extend(reversed(below))  # listRelatives gives the deepest first
    else:
        found = selection()
    return _without_followers(_unique(_transforms_of_shapes(found)))


def _transforms_of_shapes(items: list[str]) -> list[str]:
    """A selected SHAPE stands for its transform: the transform is what gets the name, Maya
    renames the shape with it ("armShape"). An instanced shape (several parents) stays itself."""
    result = []
    for path in items:
        try:
            if "|" in path and cmds.objectType(path, isAType="shape")                     and len(cmds.listRelatives(path, allParents=True) or []) == 1:
                path = path.rpartition("|")[0]
        except RuntimeError:
            pass
        result.append(path)
    return result


def _unique(items: list[str]) -> list[str]:
    seen, result = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _without_followers(items: list[str]) -> list[str]:
    """Shapes whose transform is in the list too go out: Maya renames them with it."""
    kept = set(items)
    result = []
    for path in items:
        try:
            if "|" in path and cmds.objectType(path, isAType="shape"):
                parent = path.rpartition("|")[0]
                if parent in kept:
                    continue
        except RuntimeError:
            continue  # a name Maya can't address itself (it happens with non-Latin letters)
        result.append(path)
    return result


def nodes(items: list[str]) -> list[Node]:
    """A Node for each long name (in that order)."""
    result = []
    referenced_ok = hasattr(cmds, "referenceQuery")
    for path in items:
        try:
            node = _node(path, referenced_ok)
        except RuntimeError:
            continue  # gone, or a name Maya can't address itself
        if node is not None:
            result.append(node)
    return result


def _node(path: str, referenced_ok: bool) -> "Node | None":
    if not cmds.objExists(path):
        return None
    short = path.rpartition("|")[2]
    namespace, _sep, name = short.rpartition(":")
    namespace = namespace + ":" if namespace else ""
    node_type = cmds.nodeType(path)
    shapes = cmds.listRelatives(path, shapes=True, fullPath=True, noIntermediate=True) or [] if "|" in path else []
    shape_type = cmds.nodeType(shapes[0]) if shapes else ""
    position = (0.0, 0.0, 0.0)
    siblings: tuple = ()
    if "|" in path:
        try:
            position = tuple(cmds.xform(path, query=True, worldSpace=True, rotatePivot=True) or position)
        except RuntimeError:
            pass  # a shape or a node without a pivot
        parent = path.rpartition("|")[0]
        others = (cmds.listRelatives(parent, children=True) if parent else cmds.ls(assemblies=True)) or []
        siblings = tuple(other.rpartition(":")[2] for other in others
                         if other.rpartition("|")[2] != short
                         and (other.rpartition(":")[0] + ":" if ":" in other else "") == namespace)
    locked = ""
    if referenced_ok and cmds.referenceQuery(path, isNodeReferenced=True):
        locked = "referenced"
    elif (cmds.lockNode(path, query=True, lock=True) or [False])[0]:
        locked = "locked node"
    elif cmds.ls(path, readOnly=True):
        locked = "read-only"
    uuid = (cmds.ls(path, uuid=True) or [""])[0]
    return Node(path=path, name=name, namespace=namespace, type=node_type, shape_type=shape_type,
                position=position, locked=locked, uuid=uuid, siblings=siblings)


def current(node: Node) -> str:
    """The long name of `node` NOW (its UUID's), or "" if it is gone."""
    if node.uuid:
        found = cmds.ls(node.uuid, long=True) or []
        if found:
            return found[0]
    return node.path if cmds.objExists(node.path) else ""


def apply(changes: list[Change], drop_namespace: bool = False) -> list[tuple[Change, str, str]]:
    """Renames what `changes` say, as one undo step. Returns (change, the name Maya gave, error)
    for every change that was tried — Maya may number a name that is taken."""
    done = []
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for change in changes:
            if not change.changes and not (drop_namespace and change.node.namespace and change.state == "same"):
                continue
            path = current(change.node)
            if not path:
                done.append((change, "", "the object is gone"))
                continue
            target = (":" if drop_namespace else change.node.namespace) + change.new
            try:
                given = cmds.rename(path, target)
                done.append((change, given.rpartition("|")[2], ""))
            except RuntimeError as error:
                done.append((change, "", str(error).strip()))
    finally:
        cmds.undoInfo(closeChunk=True)
    return done


def select(items: list[str], add: bool = False) -> None:
    existing = [item for item in items if cmds.objExists(item)]
    if existing:
        cmds.select(existing, add=add, replace=not add)
    elif not add:
        cmds.select(clear=True)


def select_nodes(items: list[Node]) -> None:
    select([path for path in (current(node) for node in items) if path])


def skin_joints(items: list[str]) -> list[str]:
    """The joints the skinClusters of `items` (meshes, their transforms) are bound to."""
    joints = []
    for path in items:
        history = cmds.listHistory(path, pruneDagObjects=True) or []
        for cluster in cmds.ls(history, type="skinCluster") or []:
            for joint in cmds.skinCluster(cluster, query=True, influence=True) or []:
                long = (cmds.ls(joint, long=True) or [joint])[0]
                if long not in joints:
                    joints.append(long)
    return joints


def make_set(name: str, items: list[str]) -> str:
    """A Maya object set of `items` (the outliner shows it)."""
    existing = [item for item in items if cmds.objExists(item)]
    return cmds.sets(existing, name=name or "mslRenameSet")


def not_unique(items: list[str]) -> list[str]:
    """Those of `items` whose short name another DAG object of the scene has too — the reason for
    Maya's "More than one object matches name"."""
    counts: dict = {}
    for path in cmds.ls(dag=True, long=True) or []:
        short = path.rpartition("|")[2]
        counts[short] = counts.get(short, 0) + 1
    return [path for path in items if counts.get(path.rpartition("|")[2], 0) > 1]


def look_in() -> list[str]:
    """Where a check looks: the selection with everything under it — the whole scene's DAG
    objects when nothing is selected."""
    if selection():
        return paths(SCOPE_HIERARCHY)
    found = _without_followers(cmds.ls(dag=True, long=True) or [])
    skip = set(cmds.ls(defaultNodes=True, long=True) or [])
    return [path for path in found if path not in skip]
