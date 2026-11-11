# tools/maya/scripts/scene_cleanup.py
"""Clean Unknown Plug-ins: the open scene stops asking for plug-ins this Maya doesn't have.

A scene saved where some plug-in was loaded keeps a `requires "<plug-in>"` line for it, and Maya
tries to load it on every open ("Plug-in, "evoattrib", was not found on MAYA_PLUG_IN_PATH"). The
nodes of such a plug-in come back as UNKNOWN nodes (unknown / unknownDag / unknownTransform) that
hold their data for the session and keep the requirement alive.

What it does, in this order (the other way round Maya refuses to drop a plug-in while its nodes
are there):
    1. the scene's own unknown nodes are deleted (unlocked first) - their data is lost, so when
       there are any, Maya is asked first, with how many of which plug-in;
    2. every plug-in the scene still lists as unknown (`unknownPlugin -list`) is dropped.
Left, and named: unknown nodes of a REFERENCED file (a scene can't delete them) and plug-ins that
a referenced file asks for - measured (Maya 2024): a shot lists its reference's plug-ins too, and
dropping them there changes nothing, the reference asks again on the next open. Those are cleaned
by opening that file and running this there. A referenced .ma is read as text to tell which file
asks for what; a .mb can't be read that way.

The nodes' deletion is one undo step; dropping a plug-in from the list is not undoable (Maya).
Nothing is saved: the scene is modified, the user saves it.
"""
import os
import re

from maya import cmds

UNKNOWN_TYPES = ("unknown", "unknownDag", "unknownTransform")
UNDO_NAME = "MSL Clean Unknown Plug-ins"
HEAD_BYTES = 256 * 1024          # `requires` lines stand at the top of a .ma
_REQUIRES = re.compile(r'^requires\b[^;]*?"([^"]+)"\s+"[^"]*"\s*;', re.MULTILINE)


class Outcome:
    """What a clean-up did, for the message."""

    def __init__(self):
        self.nodes = 0                 # unknown nodes deleted
        self.plugins = []              # plug-ins dropped from the scene's list
        self.refused = []              # plug-ins Maya kept (nodes of it still there)
        self.referenced = {}           # referenced file -> plug-ins / unknown nodes it brings
        self.cancelled = False

    def text(self) -> str:
        if self.cancelled:
            return "Clean unknown plug-ins: nothing changed"
        if not (self.nodes or self.plugins or self.refused or self.referenced):
            return "Clean unknown plug-ins: the scene asks for no missing plug-in"
        parts = []
        if self.nodes or self.plugins:
            done = []
            if self.nodes:
                done.append(f"{self.nodes} unknown node{'s' if self.nodes != 1 else ''} deleted")
            if self.plugins:
                done.append(f"{len(self.plugins)} plug-in{'s' if len(self.plugins) != 1 else ''} dropped")
            parts.append(", ".join(done) + " - save the scene")
        if self.referenced:
            files = ", ".join(os.path.basename(path) for path in self.referenced)
            parts.append(f"still asked for by {files}: open it and clean it there")
        if self.refused:
            parts.append(f"kept: {', '.join(self.refused)}")
        return "Clean unknown plug-ins: " + " · ".join(parts)


def run(ask: bool = True) -> Outcome:
    """Cleans the open scene; says what it did in the viewport and the Script Editor."""
    outcome = clean(ask=ask)
    _say(outcome.text())
    for path, what in outcome.referenced.items():
        print(f"MSL   {path}: " + ", ".join(sorted(what)))
    return outcome


def clean(ask: bool = True) -> Outcome:
    """The clean-up itself; `ask=False` deletes unknown nodes without the question (tests, scripts)."""
    outcome = Outcome()
    own, referenced = _unknown_nodes()
    for node, path in referenced:
        outcome.referenced.setdefault(path, set()).add(_plugin_of(node) or "unknown nodes")
    if own and ask and not cmds.about(batch=True) and not _confirmed(own):
        outcome.cancelled = True
        return outcome
    listed = cmds.unknownPlugin(query=True, list=True) or []     # before: a plug-in leaves with its last node
    if own:
        outcome.nodes = _delete(own)
    asked_by = _asked_by_references()
    for plugin in listed:
        files = [path for path, plugins in asked_by.items() if plugin in plugins]
        for path in files:
            outcome.referenced.setdefault(path, set()).add(plugin)
        if plugin in (cmds.unknownPlugin(query=True, list=True) or []):
            try:
                cmds.unknownPlugin(plugin, remove=True)
            except RuntimeError:
                if not files:
                    outcome.refused.append(plugin)
                continue
        if not files:
            outcome.plugins.append(plugin)
    return outcome


def count() -> int:
    """How many plug-ins the open scene asks for that this Maya doesn't have (0 = nothing to clean) - cheap:
    the hub's session menu shows it, sent with every scene event."""
    try:
        return len(cmds.unknownPlugin(query=True, list=True) or [])
    except RuntimeError:
        return 0


def state() -> dict:
    """What a clean-up would do, as data for the hub's question (nothing is changed):
    {"plugins": [names it drops], "nodes": [{"plugin", "count"}] of the scene's own unknown nodes,
     "referenced": [{"file", "plugins"}] - what referenced files ask for (cleaned in those files)}."""
    own, referenced = _unknown_nodes()
    counts = {}
    for node in own:
        plugin = _plugin_of(node) or "no plug-in named"
        counts[plugin] = counts.get(plugin, 0) + 1
    files = {}
    for node, path in referenced:
        files.setdefault(path, set()).add(_plugin_of(node) or "unknown nodes")
    asked_by = _asked_by_references()
    plugins = []
    for plugin in cmds.unknownPlugin(query=True, list=True) or []:
        asking = [path for path, names in asked_by.items() if plugin in names]
        for path in asking:
            files.setdefault(path, set()).add(plugin)
        if not asking:
            plugins.append(plugin)
    return {"plugins": plugins,
            "nodes": [{"plugin": plugin, "count": number}
                      for plugin, number in sorted(counts.items(), key=lambda item: -item[1])],
            "referenced": [{"file": path, "plugins": sorted(names)} for path, names in sorted(files.items())]}


def as_data(outcome: Outcome) -> dict:
    """An Outcome for the hub's reply."""
    return {"nodes": outcome.nodes, "plugins": list(outcome.plugins), "refused": list(outcome.refused),
            "referenced": [{"file": path, "plugins": sorted(names)} for path, names in sorted(outcome.referenced.items())],
            "text": outcome.text()}


def _unknown_nodes():
    """(the scene's own unknown nodes, [(referenced unknown node, its file)])."""
    own, referenced = [], []
    for node in cmds.ls(type=list(UNKNOWN_TYPES), long=True) or []:
        if cmds.referenceQuery(node, isNodeReferenced=True):
            try:
                path = cmds.referenceQuery(node, filename=True, withoutCopyNumber=True)
            except RuntimeError:
                path = "a referenced file"
            referenced.append((node, path))
        else:
            own.append(node)
    return own, referenced


def _plugin_of(node: str) -> str:
    try:
        return cmds.unknownNode(node, query=True, plugin=True) or ""
    except RuntimeError:
        return ""


def _confirmed(nodes: list) -> bool:
    """Asks before deleting unknown nodes: how many, of which plug-in."""
    counts = {}
    for node in nodes:
        plugin = _plugin_of(node) or "no plug-in named"
        counts[plugin] = counts.get(plugin, 0) + 1
    lines = [f"{count} of {plugin}" for plugin, count in sorted(counts.items(), key=lambda item: -item[1])]
    message = (f"Delete {len(nodes)} unknown node{'s' if len(nodes) != 1 else ''}?\n\n" + "\n".join(lines[:12])
               + (f"\n... and {len(lines) - 12} more" if len(lines) > 12 else "")
               + "\n\nThey are nodes of plug-ins this Maya doesn't have; what they held is lost. "
                 "One undo step. The scene is not saved.")
    answer = cmds.confirmDialog(title="MSL - Clean Unknown Plug-ins", message=message,
                                button=["Delete", "Cancel"], defaultButton="Delete",
                                cancelButton="Cancel", dismissString="Cancel")
    return answer == "Delete"


def _delete(nodes: list) -> int:
    """Deletes the nodes in one undo step; a node gone with its parent counts too."""
    deleted = 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for node in nodes:
            if not cmds.objExists(node):
                deleted += 1                     # went with an unknown parent
                continue
            try:
                cmds.lockNode(node, lock=False)
                cmds.delete(node)
                deleted += 1
            except RuntimeError as error:
                print(f"MSL   could not delete {node}: {error}")
    finally:
        cmds.undoInfo(closeChunk=True)
    return deleted


def _asked_by_references() -> dict:
    """{referenced .ma file: the plug-ins its `requires` lines name} for every loaded reference."""
    asked = {}
    for path in set(cmds.file(query=True, reference=True, withoutCopyNumber=True) or []):
        if not path.lower().endswith(".ma") or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as handle:
                head = handle.read(HEAD_BYTES).decode("latin-1")
        except OSError:
            continue
        head = head.split("\ncreateNode", 1)[0]
        asked[path] = set(_REQUIRES.findall(head))
    return asked


def _say(text: str) -> None:
    print("MSL " + text)
    try:
        cmds.inViewMessage(assistMessage=text, position="topCenter", fade=True, fadeStayTime=2400)
    except RuntimeError:
        pass
