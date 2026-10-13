# core/link/maya_snippets.py
"""Ready-made questions to a Maya - code the assistant's tools send through
run_python instead of the assistant writing it each time - and how their
answers are told. Qt-free; the code itself runs inside Maya (so: maya.cmds
only, Python 3.9-valid, and READ-ONLY - nothing here changes a scene).

A snippet prints one line `MARK + <json>`; `parse()` finds it in what the
run printed. Each snippet is a template: fill it with `%` and a dict.
"""
from __future__ import annotations

import json

MARK = "MSL_ANSWER "
LIST_SHOWN = 40   # names of a list told before "... and N more"


def parse(output: str) -> dict | None:
    """The answer a snippet printed (None if there is none: the code failed before)."""
    for line in str(output).splitlines():
        if line.startswith(MARK):
            try:
                answer = json.loads(line[len(MARK):])
            except ValueError:
                return None
            return answer if isinstance(answer, dict) else None
    return None


# What is in the scene: the file, time, units, how many of what, the selection, what stands at
# the top of the hierarchy, namespaces and references.
SCENE_CODE = '''
import json
import maya.cmds as cmds
def _msl_scene():
    def count(**flags):
        return len(cmds.ls(**flags) or [])
    startup = [camera for camera in ("persp", "top", "front", "side") if cmds.objExists(camera)]
    top = []
    for node in cmds.ls(assemblies=True) or []:
        if node in startup:
            continue
        shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True) or []
        kind = cmds.nodeType(shapes[0]) if shapes else ("joint" if cmds.nodeType(node) == "joint" else "group")
        top.append([node, kind, len(cmds.listRelatives(node, allDescendents=True, type="transform") or [])])
    namespaces = [name for name in cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or []
                  if name not in ("UI", "shared")]
    answer = {
        "file": cmds.file(query=True, sceneName=True), "modified": bool(cmds.file(query=True, modified=True)),
        "time_unit": cmds.currentUnit(query=True, time=True), "linear": cmds.currentUnit(query=True, linear=True),
        "up": cmds.upAxis(query=True, axis=True), "frame": cmds.currentTime(query=True),
        "playback": [cmds.playbackOptions(query=True, minTime=True), cmds.playbackOptions(query=True, maxTime=True)],
        "range": [cmds.playbackOptions(query=True, animationStartTime=True),
                  cmds.playbackOptions(query=True, animationEndTime=True)],
        "counts": {"transforms": count(type="transform") - len(startup), "joints": count(type="joint"),
                   "meshes": count(type="mesh", noIntermediate=True), "curves": count(type="nurbsCurve", noIntermediate=True),
                   "locators": count(type="locator"), "cameras": count(cameras=True) - len(startup),
                   "lights": count(lights=True), "constraints": count(type="constraint"),
                   "skin clusters": count(type="skinCluster"), "blend shapes": count(type="blendShape"),
                   "anim curves": count(type="animCurve"), "materials": count(materials=True),
                   "file textures": count(type="file")},
        "selection": cmds.ls(selection=True) or [],
        "top": top, "namespaces": namespaces, "references": cmds.file(query=True, reference=True) or [],
    }
    print(%(mark)r + json.dumps(answer, default=str))
_msl_scene()
del _msl_scene
'''

# One node: what it is, where it stands in the hierarchy, its values, its own attributes, what
# feeds it and what it feeds.
NODE_CODE = '''
import json
import maya.cmds as cmds
def _msl_node(name):
    found = cmds.ls(name, long=True) or []
    if len(found) != 1:
        print(%(mark)r + json.dumps({"found": found}))
        return
    node = found[0]
    kind = cmds.nodeType(node)
    answer = {"found": found, "name": node, "type": kind, "inherits": cmds.nodeType(node, inherited=True) or [],
              "locked": bool(cmds.lockNode(node, query=True, lock=True)[0]),
              "referenced": bool(cmds.referenceQuery(node, isNodeReferenced=True))}
    if cmds.objectType(node, isAType="dagNode"):
        answer["parent"] = (cmds.listRelatives(node, parent=True, fullPath=True) or [""])[0]
        answer["children"] = cmds.listRelatives(node, children=True, type="transform") or []
        answer["shapes"] = [[shape, cmds.nodeType(shape)] for shape in cmds.listRelatives(node, shapes=True) or []]
    if cmds.objectType(node, isAType="transform"):
        values = {}
        for attribute in ("translate", "rotate", "scale"):
            values[attribute] = [round(value, 4) for value in cmds.getAttr(node + "." + attribute)[0]]
        values["visibility"] = bool(cmds.getAttr(node + ".visibility"))
        values["rotate order"] = cmds.getAttr(node + ".rotateOrder", asString=True)
        values["world pivot"] = [round(value, 4) for value in cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)]
        box = cmds.exactWorldBoundingBox(node)
        if box[3] >= box[0]:   # nothing to measure under it (a bare joint, an empty group): Maya's box is inside out
            values["world size"] = [round(box[3] - box[0], 4), round(box[4] - box[1], 4), round(box[5] - box[2], 4)]
        if kind == "joint":
            values["joint orient"] = [round(value, 4) for value in cmds.getAttr(node + ".jointOrient")[0]]
        answer["values"] = values
        answer["closed"] = [channel for channel in ("tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz", "v")
                            if cmds.getAttr(node + "." + channel, lock=True)]
    own = []
    for attribute in cmds.listAttr(node, userDefined=True) or []:
        try:
            value = cmds.getAttr(node + "." + attribute)
        except Exception:
            value = "?"
        own.append([attribute, cmds.getAttr(node + "." + attribute, type=True), value])
    answer["own"] = own
    def pairs(**flags):
        listed = cmds.listConnections(node, plugs=True, connections=True, skipConversionNodes=True, **flags) or []
        return [[listed[index], listed[index + 1]] for index in range(0, len(listed) - 1, 2)]
    answer["in"] = pairs(source=True, destination=False)
    answer["out"] = pairs(source=False, destination=True)
    print(%(mark)r + json.dumps(answer, default=str))
_msl_node(%(node)r)
del _msl_node
'''


def _some(names, shown: int = LIST_SHOWN) -> str:
    names = [str(name) for name in names]
    more = len(names) - shown
    return ", ".join(names[:shown]) + (" ... and %d more" % more if more > 0 else "")


def tell_scene(answer: dict) -> str:
    """SCENE_CODE's answer as text."""
    lines = ["Scene: %s%s" % (answer.get("file") or "untitled", "  (unsaved changes)" if answer.get("modified") else ""),
             "Time: %s, frame %s, playback %s-%s, range %s-%s   Units: %s, %s up" % (
                 answer.get("time_unit"), answer.get("frame"), *(answer.get("playback") or ["?", "?"]),
                 *(answer.get("range") or ["?", "?"]), answer.get("linear"), answer.get("up"))]
    counts = [(key, value) for key, value in (answer.get("counts") or {}).items() if value]
    lines.append("Holds: " + (", ".join("%s %s" % (value, key) for key, value in counts) or "nothing"))
    selection = answer.get("selection") or []
    lines.append("Selected (%d): %s" % (len(selection), _some(selection) or "nothing"))
    top = answer.get("top") or []
    lines.append("Top of the hierarchy (%d):" % len(top))
    for name, kind, under in top[:LIST_SHOWN]:
        lines.append("  %s  [%s]%s" % (name, kind, "  %d under it" % under if under else ""))
    if len(top) > LIST_SHOWN:
        lines.append("  ... and %d more" % (len(top) - LIST_SHOWN))
    if answer.get("namespaces"):
        lines.append("Namespaces: " + _some(answer["namespaces"]))
    if answer.get("references"):
        lines.append("References: " + _some(answer["references"], 10))
    return "\n".join(lines)


def tell_node(answer: dict, asked: str) -> str:
    """NODE_CODE's answer as text."""
    found = answer.get("found") or []
    if not found:
        return "No node is called “%s” in that scene." % asked
    if len(found) > 1:
        return "%d nodes are called “%s” - give the full path of one:\n%s" % (
            len(found), asked, "\n".join("  " + path for path in found[:LIST_SHOWN]))
    marks = [mark for mark, on in (("LOCKED node", answer.get("locked")), ("referenced", answer.get("referenced"))) if on]
    lines = ["%s  [%s]%s" % (answer.get("name"), answer.get("type"), "  (%s)" % ", ".join(marks) if marks else "")]
    if "parent" in answer:
        lines.append("Parent: %s" % (answer.get("parent") or "the world"))
        children = answer.get("children") or []
        lines.append("Children (%d): %s" % (len(children), _some(children) or "none"))
        if answer.get("shapes"):
            lines.append("Shapes: " + ", ".join("%s [%s]" % (name, kind) for name, kind in answer["shapes"]))
    for key, value in (answer.get("values") or {}).items():
        lines.append("  %-13s %s" % (key, value))
    if answer.get("closed"):
        lines.append("Locked channels: " + ", ".join(answer["closed"]))
    own = answer.get("own") or []
    if own:
        lines.append("Its own attributes (%d):" % len(own))
        lines += ["  %s  [%s] = %s" % (name, kind, value) for name, kind, value in own[:LIST_SHOWN]]
    for title, key, arrow in (("Fed by", "in", "<-"), ("Feeds", "out", "->")):
        links = answer.get(key) or []
        if links:
            lines.append("%s (%d):" % (title, len(links)))
            lines += ["  %s %s %s" % (here, arrow, there) for here, there in links[:LIST_SHOWN]]
            if len(links) > LIST_SHOWN:
                lines.append("  ... and %d more" % (len(links) - LIST_SHOWN))
    return "\n".join(lines)
