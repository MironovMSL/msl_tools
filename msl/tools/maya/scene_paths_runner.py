# -*- coding: utf-8 -*-
# tools/maya/scene_paths_runner.py
"""Runs INSIDE mayapy for the hub's Scenes > Paths tab: the paths of binary scenes (.mb), which
can't be read as text - listed ("list") or swapped for variables and saved ("apply").

SELF-CONTAINED on purpose (the standard library and maya only; Python-2.7-valid and plain ASCII:
a scene from Maya 2020 is opened by a Maya 2020): started by path, `mayapy scene_paths_runner.py
<task.json>` - no msl_tools on the path is assumed.

The task file (written by core/scene_paths/mb_paths.py):
    {"mode": "list" | "apply", "roots": [["WG_ANIM", "E:/branches/Animation"], ...],   deepest first
                                         ("list" is given none: the hub sorts the paths by its roots)
     "scenes": [{"path": ..., "size": 123, "mtime_ns": 456,          size / mtime: apply refuses a changed file
                 "relink": {"file2.fileTextureName" | "rigRN": <a found file's new path>},
                 "writes": {<key>: <its new path>}}, ...],   which paths to swap and through which variable
                                                          (each must be one of the path's options; absent = all, deepest)
     "result": <a JSON file written at the end>, "progress": <a JSON-lines file, one line per scene>}

What is looked at, in each scene:
- its own references (`file -q -r`): the reference node's file name as written (unresolved);
- every attribute Maya's File Path Editor knows (`filePathEditor -listRegisteredTypes`) plus
  file / AlembicNode / gpuCache ones, on nodes of THIS scene, and on referenced nodes only where
  this scene holds a setAttr EDIT of that attribute - a path the referenced file itself holds
  belongs to that file (fix it there), exactly like the text road for .ma.

"apply" changes in memory and SAVES the scene in place (same type); the hub copies the old file
aside first. A reference is reloaded under its new name (an unloaded one is unloaded again).
Script nodes are not run when a scene opens.
"""
import json
import os
import sys
import time
import traceback

STARTED = time.time()
EXTRA_TYPES = ("file.fileTextureName", "AlembicNode.abc_File", "gpuCache.cacheFileName")


def text(value):
    try:
        return value if isinstance(value, str) else value.encode("utf-8")   # Python 2: unicode -> str
    except Exception:
        return str(value)


class Runner(object):
    def __init__(self, task):
        """`task`: the task file's path - or the task itself, a dict (scene_paths_tool.py: the open scene)."""
        if isinstance(task, dict):
            self.task = task
        else:
            with open(task, "r") as handle:
                self.task = json.load(handle)
        self.roots = [(str(name), str(value).replace("\\", "/").rstrip("/")) for name, value in self.task["roots"]]
        self.apply = self.task.get("mode") == "apply"
        self.results = []

    def say(self, event, **data):
        data["event"] = event
        data["t"] = round(time.time() - STARTED, 2)
        line = json.dumps(data)
        path = self.task.get("progress")
        if path:
            try:
                with open(path, "a") as handle:
                    handle.write(line + "\n")
            except (IOError, OSError):
                pass

    def root_of(self, path):
        """(root name, root value) whose folder starts `path` - the deepest - or None."""
        found = self.roots_of(path)
        return found[0] if found else None

    def roots_of(self, path):
        """Every (root name, root value) whose folder starts `path`, deepest first (self.roots is in that
        order): a path under E:/a/b can be written through a variable of E:/a/b or one of E:/a."""
        lowered = path.replace("\\", "/").lower()
        return [(name, value) for name, value in self.roots
                if lowered == value.lower() or lowered.startswith(value.lower() + "/")]

    @staticmethod
    def pick(uses, writes):
        """Applies the user's choices to the uses about to be swapped: `writes` {key: new path} names the
        ones to swap and how (a new path that isn't one of the use's options is refused - the use stays);
        None = every use as found (its deepest root). Returns the keys refused."""
        if writes is None:
            return []
        refused = []
        for use in uses:
            if use["state"] != "change":
                continue
            key = use["plug"] or use["node"]
            new = writes.get(key)
            if new is None:
                use["state"], use["note"] = "left", "left as it is"
            elif new in [option[1] for option in use.get("options") or []]:
                use["new"] = new
            else:
                use["state"], use["note"] = "left", "not one of its variables"
                refused.append(key)
        return refused

    def new_path(self, path, root):
        shown = path.replace("\\", "/")
        return "$" + root[0] + shown[len(root[1]):]

    # --- one scene ----------------------------------------------------------------------------------

    def run(self):
        import maya.cmds as cmds
        for plugin in ("AbcImport", "gpuCache", "mtoa"):
            try:
                cmds.loadPlugin(plugin, quiet=True)
            except Exception:
                pass
        for scene in self.task["scenes"]:
            self.say("scene_start", path=scene["path"])
            result = {"path": scene["path"], "error": "", "uses": [], "changed": 0}
            try:
                self.scene(cmds, scene, result)
            except Exception as error:
                result["error"] = "Maya: {0}".format(error)
                result["traceback"] = traceback.format_exc()
            self.results.append(result)
            self.say("scene_done", path=scene["path"], error=result["error"], uses=len(result["uses"]))
        with open(self.task["result"], "w") as handle:
            json.dump({"scenes": self.results}, handle)

    def scene(self, cmds, scene, result):
        path = scene["path"]
        if self.apply:
            info = os.stat(path)   # (Python 2.7 has no st_mtime_ns: compared to the millisecond)
            if info.st_size != scene.get("size") or abs(info.st_mtime - scene.get("mtime_ns", 0) / 1e9) > 0.001:
                result["error"] = "changed since it was read - read it again first"
                return
        cmds.file(path, open=True, force=True, prompt=False, ignoreVersion=True, executeScriptNodes=False)
        uses = result["uses"]
        references = self.references(cmds, uses)
        self.attributes(cmds, uses, references)
        result["refused"] = self.pick(uses, scene.get("writes"))
        relink = scene.get("relink") or {}
        for use in uses:   # missing files the hub found again: the whole path becomes the found one
            new = relink.get(use["plug"] or use["node"])
            if new and not use.get("inside"):
                use["state"], use["new"] = "change", new
        if not self.apply or not any(use["state"] == "change" for use in uses):
            return
        changed = 0
        for use in uses:
            if use["state"] != "change":
                continue
            if use["kind"] == "reference":
                loaded = cmds.referenceQuery(use["node"], isLoaded=True)
                cmds.file(use["new"], loadReference=use["node"])
                if not loaded:
                    cmds.file(unloadReference=use["node"])
            else:
                plug = use["plug"]
                if cmds.getAttr(plug, lock=True):
                    use["state"], use["note"] = "left", "locked"
                    continue
                cmds.setAttr(plug, use["new"], type="string")
            changed += 1
        file_type = (cmds.file(query=True, type=True) or ["mayaBinary"])[0]
        cmds.file(save=True, force=True, type=file_type)
        result["changed"] = changed

    def references(self, cmds, uses):
        """The scene's own references; returns {reference node: set of "node.attr" its setAttr edits name}."""
        edited = {}
        for reference in cmds.file(query=True, reference=True) or []:
            node = cmds.referenceQuery(reference, referenceNode=True)
            written = text(cmds.referenceQuery(node, filename=True, unresolvedName=True, withoutCopyNumber=True))
            self.add(uses, "reference", node, "", written)
            plugs = set()
            for edit in cmds.referenceQuery(node, editStrings=True, editCommand="setAttr", failedEdits=True,
                                            successfulEdits=True) or []:
                parts = text(edit).split()
                if len(parts) > 1:
                    plugs.add(parts[1].split("|")[-1])
            edited[node] = plugs
        return edited

    def attributes(self, cmds, uses, edited):
        kinds = list(EXTRA_TYPES)
        for registered in cmds.filePathEditor(query=True, listRegisteredTypes=True) or []:
            if "." in registered and registered not in kinds:
                kinds.append(registered)
        seen = set()
        for kind in kinds:
            node_type, attribute = kind.split(".", 1)
            try:
                nodes = cmds.ls(type=node_type, long=False) or []
            except Exception:
                continue   # a plug-in's type that isn't loaded
            for node in nodes:
                plug = "{0}.{1}".format(node, attribute)
                if plug in seen or not cmds.objExists(plug):
                    continue
                seen.add(plug)
                try:
                    value = text(cmds.getAttr(plug) or "")
                except Exception:
                    continue
                if not value:
                    continue
                state_note = ""
                use_kind = "texture" if node_type == "file" else "attribute"
                if cmds.referenceQuery(node, isNodeReferenced=True):
                    reference = cmds.referenceQuery(node, referenceNode=True)
                    short = "{0}.{1}".format(node.split("|")[-1], attribute)
                    if short in edited.get(reference, ()):
                        use_kind = "reference edit"
                    else:
                        state_note = "inside the referenced file - fix it there"
                self.add(uses, use_kind, node, attribute, value, plug=plug, left=state_note)

    def add(self, uses, kind, node, attribute, path, plug="", left=""):
        roots = self.roots_of(path)
        root = roots[0] if roots else None
        use = {"kind": kind, "node": text(node), "attribute": text(attribute), "path": path, "plug": plug,
               "new": "", "root": "", "state": "outside", "note": left, "inside": bool(left),
               # every way to write it: [root name, new path], deepest first - the user may pick another
               "options": [] if left else [[name, self.new_path(path, (name, value))] for name, value in roots]}
        if path.startswith("$"):
            use["state"] = "variable"
        elif root is not None:
            use["root"] = root[0]
            if left:
                use["state"] = "left"
            else:
                use["state"], use["new"] = "change", self.new_path(path, root)
        elif not (len(path) > 2 and (path[1] == ":" or path[:2] in ("//", "\\\\"))):
            return   # a relative path / a plain name: nothing a root could stand for
        uses.append(use)


def main(task_path):
    import maya.standalone
    maya.standalone.initialize(name="python")
    try:
        Runner(task_path).run()
    except Exception:
        sys.__stderr__.write(traceback.format_exc())
        os._exit(1)
    os._exit(0)  # standalone's own shutdown is slow and noisy; everything is written


if __name__ == "__main__":
    main(sys.argv[1])
