# tools/maya/scene_paths_tool.py
"""Inside Maya: the OPEN scene's absolute paths swapped for the variables Maya Gate gave this Maya
("E:/branches/Animation/..." -> "$WG_ANIM/...") — MSL > Paths to Variables, the hotkey
MSLPathsToVariables; and, for scene_defaults.py's check on opening, how many paths could be.

The variables are this Maya's own: the launch names them (MSL_GATE_VARIABLES) and its environment
holds their values — nothing to type. Only those that name ONE folder can stand for one
(core/scene_paths/roots.py), and Maya's own (MAYA_*, PYTHON*, ...) are left out: a scene's paths
under MAYA_APP_DIR aren't meant to move with it.

The paths are found by the same code the hub's Paths tab reads binary scenes with
(scene_paths_runner.py, `Runner.references` / `.attributes`): the scene's own references, every
file attribute Maya's File Path Editor knows (+ file / Alembic / gpuCache), and on referenced nodes
only what THIS scene holds an edit of — a path the referenced file holds belongs to that file.

The scene is NOT saved: that stays the user's. The attributes change in one undo step; a reference
reloaded under its new name can't be undone by Ctrl+Z — and reloading one EMPTIES Maya's undo queue
(measured, mayapy 2024), so references go first and the attributes after them. The question says so. Runs in Maya 2023+ (Python 3.9-valid), no Qt.
"""
from __future__ import annotations

import os

from msl_tools.msl.core.link import variables
from msl_tools.msl.core.scene_paths.roots import roots_from
from msl_tools.msl.tools.maya.scene_paths_runner import Runner

TITLE = "MSL · Paths to variables"
SHOWN = 8                                   # paths named in the question; the rest are counted
MAYA_OWN = ("MAYA_", "PYTHON", "XBMLANG", "MTOA", "ARNOLD", "REDSHIFT", "QT_")   # not a scene's folders


def roots_here(environment=None) -> list:
    """The roots this Maya has: the variables its launch set that name one folder ([] when Maya Gate
    didn't start it), deepest first."""
    environment = os.environ if environment is None else environment
    names = [name for name in str(environment.get(variables.VARIABLES, "")).split(os.pathsep) if name]
    values = {name: environment.get(name, "") for name in names
              if name and not name.upper().startswith(MAYA_OWN)}
    return roots_from(values)


def collect(cmds, roots: list) -> list:
    """Every absolute path of the open scene as the runner describes it (dicts: kind, node, attribute,
    path, plug, state "change" / "variable" / "outside" / "left", new)."""
    runner = Runner({"mode": "list", "roots": [[root.name, root.value] for root in roots], "scenes": []})
    uses: list = []
    edited = runner.references(cmds, uses)
    runner.attributes(cmds, uses, edited)
    return uses


def _where(use: dict) -> str:
    return "%s.%s" % (use["node"], use["attribute"]) if use.get("attribute") else use.get("node", "")


def paths_to_variables() -> int:
    """MSL > Paths to Variables: shows what would change, asks, swaps. Returns how many paths changed."""
    from maya import cmds
    roots = roots_here()
    if not roots:
        started = bool(os.environ.get(variables.VARIABLES))
        cmds.confirmDialog(title=TITLE, button=["OK"], message=(
            "This Maya’s environment has no variable that names one folder.\n\nAdd one in Maya Gate › Variables "
            "(e.g. WG_ANIM = E:/branches/Animation) and start Maya from there." if started else
            "This Maya wasn’t started from Maya Gate, so it has no variables of an environment to use."))
        return 0
    uses = collect(cmds, roots)
    changes = [use for use in uses if use["state"] == "change"]
    left = [use for use in uses if use["state"] == "left"]
    through = [use for use in uses if use["state"] == "variable"]
    if not changes:
        message = "Nothing to change: no path of this scene starts with %s." % " or ".join(
            root.value for root in roots)
        if through:
            message += "\n%d path%s already through a variable." % (len(through), "s are" if len(through) != 1 else " is")
        if left:
            message += "\n%d under them live in referenced files — fix those files." % len(left)
        cmds.confirmDialog(title=TITLE, message=message, button=["OK"])
        return 0
    lines = ["%d paths of this scene become variables:" % len(changes) if len(changes) != 1
             else "1 path of this scene becomes a variable:"]
    lines += ["    $%s  =  %s" % (root.name, root.value) for root in roots
              if any(use["new"].startswith("$" + root.name) for use in changes)]
    lines.append("")
    for use in changes[:SHOWN]:
        lines.append("  %s:  %s" % (_where(use), use["new"]))
    if len(changes) > SHOWN:
        lines.append("  … and %d more" % (len(changes) - SHOWN))
    references = [use for use in changes if use["kind"] == "reference"]
    lines.append("")
    if left:
        lines.append("%d path%s under them live in referenced files and stay — fix those files."
                     % (len(left), "s" if len(left) != 1 else ""))
    if references:
        lines.append("%d reference%s reloaded under the new name — Ctrl+Z doesn’t undo that part, and "
                     "reloading clears what Ctrl+Z could undo before." % (len(references),
                                                                          "s are" if len(references) != 1 else " is"))
    lines.append("The scene isn’t saved — save it when it looks right.")
    if cmds.confirmDialog(title=TITLE, message="\n".join(lines), button=["Replace", "Cancel"],
                          defaultButton="Replace", cancelButton="Cancel", dismissString="Cancel") != "Replace":
        return 0
    changed, skipped = apply(cmds, changes)
    text = "%d path%s now through a variable" % (changed, "s" if changed != 1 else "")
    if skipped:
        text += "; %d left (locked): %s" % (len(skipped), ", ".join(skipped[:4]))
    print("MSL Paths to variables: " + text + ".")
    try:
        cmds.inViewMessage(assistMessage="<hl>Paths</hl>: " + text, position="topCenter", fade=True,
                           fadeStayTime=4000)
    except Exception:
        pass
    return changed


def apply(cmds, changes: list) -> tuple:
    """Swaps the paths: the references FIRST (reloading one is a file operation that empties Maya's
    undo queue — done after the attributes it took their undo with it), then the attributes in ONE undo
    step. Returns (how many changed, plugs left because they are locked)."""
    changed, skipped = 0, []
    for use in changes:
        if use["kind"] != "reference":
            continue
        loaded = cmds.referenceQuery(use["node"], isLoaded=True)
        cmds.file(use["new"], loadReference=use["node"])
        if not loaded:
            cmds.file(unloadReference=use["node"])
        changed += 1
    attributes = [use for use in changes if use["kind"] != "reference"]
    if attributes:
        cmds.undoInfo(openChunk=True, chunkName="MSL Paths to variables")
        try:
            for use in attributes:
                if not cmds.objExists(use["plug"]) or cmds.getAttr(use["plug"], lock=True):
                    skipped.append(use["plug"])
                    continue
                cmds.setAttr(use["plug"], use["new"], type="string")
                changed += 1
        finally:
            cmds.undoInfo(closeChunk=True)
    return changed, skipped


def referenced_files(cmds, uses: list) -> list:
    """The files of this scene's references that hold paths of their own (a texture of a rig): those are
    fixed in the file, not in this scene. [{"file": path, "count": n}], the most first. What Maya shows
    for such a path may be where IT found the file (a rig written with D:/AnimBase/... shows E:/...), so
    the count is of paths, not of a kind - the file itself says what it holds."""
    counts: dict = {}
    for use in uses:
        if not use.get("inside") or not use.get("node"):
            continue
        try:
            path = cmds.referenceQuery(use["node"], filename=True, withoutCopyNumber=True)
        except Exception:
            continue
        counts[path] = counts.get(path, 0) + 1
    return [{"file": path, "count": count} for path, count in sorted(counts.items(), key=lambda item: -item[1])]


def count_changes(cmds=None) -> tuple:
    """(how many paths of the open scene could become a variable, the roots) — for the check on opening."""
    if cmds is None:
        from maya import cmds
    roots = roots_here()
    if not roots:
        return 0, roots
    return sum(1 for use in collect(cmds, roots) if use["state"] == "change"), roots
