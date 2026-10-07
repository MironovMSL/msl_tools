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
            found.extend(_below(path))
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


def _below(path: str) -> list[str]:
    """Everything under `path` in the Outliner's order: each child, then what is under it."""
    found = []
    for child in cmds.listRelatives(path, children=True, fullPath=True) or []:
        found.append(child)
        found.extend(_below(child))
    return found


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
    children: dict = {}  # parent -> its children, asked once (a hierarchy has many siblings)
    for path in items:
        try:
            node = _node(path, referenced_ok, children)
        except RuntimeError:
            continue  # gone, or a name Maya can't address itself
        if node is not None:
            result.append(node)
    return result


def _node(path: str, referenced_ok: bool, children: dict) -> "Node | None":
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
        if parent not in children:
            children[parent] = (cmds.listRelatives(parent, children=True) if parent
                                else cmds.ls(assemblies=True)) or []
        others = children[parent]
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
    parent_name = path.rpartition("|")[0].rpartition("|")[2].rpartition(":")[2] if "|" in path else ""
    root_name = path.split("|")[1].rpartition(":")[2] if path.startswith("|") else ""
    return Node(path=path, name=name, namespace=namespace, type=node_type, shape_type=shape_type,
                position=position, locked=locked, uuid=uuid, siblings=siblings, parent=parent_name, root=root_name)


def selection_uuids() -> set:
    """The uuids of what is selected (cheap: one call) — to tell whether the selection is still the
    one the tool made itself."""
    return set(cmds.ls(selection=True, uuid=True) or [])


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


def set_locked(items: list[Node], locked: bool) -> tuple[int, int]:
    """Locks (or unlocks) the nodes — a locked node can't be renamed, deleted or re-parented,
    and Maya shows that nowhere. One undo step. Referenced nodes are left alone (their file
    decides). Returns (changed, skipped)."""
    changed = skipped = 0
    cmds.undoInfo(openChunk=True, chunkName="MSL Lock" if locked else "MSL Unlock")
    try:
        for item in items:
            path = current(item)
            if not path or cmds.referenceQuery(path, isNodeReferenced=True):
                skipped += 1
                continue
            try:
                if bool((cmds.lockNode(path, query=True, lock=True) or [False])[0]) != locked:
                    cmds.lockNode(path, lock=locked)
                    changed += 1
            except RuntimeError:
                skipped += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    return changed, skipped


def locked_ones(items: list[str]) -> list[str]:
    """Those of `items` that are locked nodes."""
    found = []
    for path in items:
        try:
            if (cmds.lockNode(path, query=True, lock=True) or [False])[0]:
                found.append(path)
        except RuntimeError:
            pass
    return found


def select(items: list[str], add: bool = False) -> None:
    existing = [item for item in items if cmds.objExists(item)]
    if existing:
        cmds.select(existing, add=add, replace=not add)
    elif not add:
        cmds.select(clear=True)


def select_nodes(items: list[Node]) -> None:
    select([path for path in (current(node) for node in items) if path])


def show(item: Node) -> None:
    """Selects the object and frames it in the viewport under the pointer / the active one (as F)."""
    path = current(item)
    if not path:
        return
    cmds.select(path, replace=True)
    try:
        cmds.viewFit(animate=True)
    except RuntimeError:
        pass  # no viewport (a batch Maya)


def frame_selection() -> None:
    """Frames what is selected in the viewport (as F)."""
    try:
        cmds.viewFit(animate=True)
    except RuntimeError:
        pass  # no viewport (a batch Maya)


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
    return [path for path in found if path not in skip and not _startup_camera(path)]


def _startup_camera(path: str) -> bool:
    """persp / top / front / side: Maya's own, not the user's to name."""
    try:
        cameras = cmds.listRelatives(path, shapes=True, type="camera", fullPath=True) or []
        return bool(cameras) and bool(cmds.camera(cameras[0], query=True, startupCamera=True))
    except RuntimeError:
        return False


def shapes_of(items: list[Node]) -> tuple[list[Node], list[str]]:
    """The (non-intermediate) shapes of `items` and the name each should have: "<transform>Shape",
    the second "<transform>Shape1" (Maya's way). In the transforms' order."""
    from msl_tools.msl.tools.maya.rename.rules import shape_name
    found, names = [], []
    for item in items:
        path = current(item)
        if not path or "|" not in path:
            continue
        shapes = cmds.listRelatives(path, shapes=True, fullPath=True, noIntermediate=True) or []
        for index, shape in enumerate(nodes(shapes)):
            found.append(shape)
            names.append(shape_name(path.rpartition("|")[2].rpartition(":")[2], index))
    return found, names


def named(short_names: list[str]) -> list[str]:
    """Long names of the objects with these short names (each may match several)."""
    found = []
    for name in short_names:
        try:
            found.extend(cmds.ls(name, long=True) or [])
        except RuntimeError:
            pass
    return _unique(found)


def all_short_names() -> set:
    """Every DAG object's short name in the scene, without namespaces — the names a new one
    must not repeat."""
    return {path.rpartition("|")[2].rpartition(":")[2] for path in cmds.ls(dag=True, long=True) or []}


def related(items: list[Node], suffixes: dict) -> tuple[list[Node], list[str], list[str]]:
    """The nodes that belong to `items` and are named after them: the shading group + material of
    a mesh ("body_SG", "body_mtl"), its skinCluster ("body_skin"), its blendShape ("body_bs"), the
    constraints under an object ("arm_parCon"...). The object's kind suffix is taken off first
    (body_geo -> body). A shading group / material that other objects use too is left alone (no
    one object's name fits it), Maya's own (initialShadingGroup, lambert1...) as well.
    Returns (nodes, their new names, notes of what was left alone)."""
    defaults = set(cmds.ls(defaultNodes=True) or []) | {"initialShadingGroup", "initialParticleSE", "lambert1",
                                                         "standardSurface1", "particleCloud1"}
    words = {text for text in suffixes.values() if text} | {"ctrl", "drv", "offset"}  # roles a base leaves too
    found, names, notes, seen = [], [], [], set()

    def add(node_name: str, new: str) -> None:
        if node_name in seen or node_name in defaults or not cmds.objExists(node_name):
            return
        seen.add(node_name)
        made = nodes([(cmds.ls(node_name, long=True) or [node_name])[0]])
        if made:
            found.append(made[0])
            names.append(new)

    for item in items:
        path = current(item)
        if not path or "|" not in path:
            continue
        name = path.rpartition("|")[2].rpartition(":")[2]
        head, sep, tail = name.rpartition("_")
        base = head if sep and head and tail in words else name
        shapes = cmds.listRelatives(path, shapes=True, fullPath=True, noIntermediate=True) or []
        for shape in shapes:
            for group in dict.fromkeys(cmds.listConnections(shape, type="shadingEngine") or []):
                if group in defaults:
                    continue
                members = {(cmds.listRelatives(member, parent=True, fullPath=True) or [member])[0].split(".")[0]
                           if cmds.objectType(member.split(".")[0], isAType="shape") else member.split(".")[0]
                           for member in (cmds.sets(group, query=True) or [])}
                members = {(cmds.ls(member, long=True) or [member])[0] for member in members}
                if len(members) > 1:
                    notes.append(f"{group}: used by {len(members)} objects — left alone")
                    continue
                add(group, f"{base}_SG")
                for material in cmds.listConnections(group + ".surfaceShader", source=True, destination=False) or []:
                    users = set(cmds.listConnections(material, type="shadingEngine") or [])
                    if len(users) > 1:
                        notes.append(f"{material}: used by {len(users)} shading groups — left alone")
                    else:
                        add(material, f"{base}_mtl")
            history = cmds.listHistory(shape, pruneDagObjects=True) or []
            for cluster in cmds.ls(history, type="skinCluster") or []:
                add(cluster, f"{base}_skin")
            for blend in cmds.ls(history, type="blendShape") or []:
                add(blend, f"{base}_bs")
        for constraint in cmds.listRelatives(path, type="constraint", fullPath=True) or []:
            kind = cmds.nodeType(constraint)
            add(constraint.rpartition("|")[2], f"{base}_{suffixes.get(kind) or kind}")
    return found, names, list(dict.fromkeys(notes))  # a shared group is met once per object using it
