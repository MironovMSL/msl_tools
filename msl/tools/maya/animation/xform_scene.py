# tools/maya/animation/xform_scene.py
"""XFORM TOOLS in the scene (the rules and the measurements: xform.py).

Copy World Space / Copy Xform Relationship keep, per selected object, a matrix (its world turn with its rotate
pivot as the position; a relationship's over its parent's world matrix) for this frame - or for every frame of the
playback range - on the clipboard as text and in a file (transfer_scene's two homes), so another Maya pastes it too.
A paste puts each object there by its own channels (align_scene.put_to: rotate order, rotate axis, joint orient,
the parent, locked / driven channels left); one undo step ("MSL Xform").
"""
from __future__ import annotations

from maya import cmds

from msl_tools.msl.tools.maya.animation import align_scene as al
from msl_tools.msl.tools.maya.animation import keys_scene
from msl_tools.msl.tools.maya.animation import scene
from msl_tools.msl.tools.maya.animation import transfer as tf
from msl_tools.msl.tools.maya.animation import transfer_scene as ts
from msl_tools.msl.tools.maya.animation import xform as xf

UNDO_NAME = "MSL Xform"
NO_COPY = "Nothing copied yet: Copy {} first (here or in another Maya)"
MOVE_TURN = ("translate", "rotate")


def _transforms() -> list:
    return [node for node in scene.selected_objects() if cmds.objectType(node, isAType="transform")]


def _playback() -> tuple:
    return (float(cmds.playbackOptions(query=True, minTime=True)),
            float(cmds.playbackOptions(query=True, maxTime=True)))


def _frames_to_copy(whole_range: bool) -> list:
    now = float(cmds.currentTime(query=True))
    if not whole_range:
        return [now]
    start, end = _playback()
    return [float(frame) for frame in range(int(round(start)), int(round(end)) + 1)]


# --------------------------------------------------------------------------- copy

def copy_world(whole_range: bool = False, say: bool = False) -> str:
    """Copy Xform World Space: the selected objects' world places on this frame (or every playback frame)."""
    objects = _transforms()
    if not objects:
        return keys_scene._done("Select the objects whose world space to copy", say)
    data = _copy(xf.WORLD, objects, None, whole_range)
    return keys_scene._done(f"World space copied: {len(objects)} object{'s' if len(objects) != 1 else ''}"
                            f"{_range_note(data)} - paste here or in another Maya", say)


def copy_relationship(whole_range: bool = False, say: bool = False) -> str:
    """Copy Xform Relationship: the selected objects (children) to the LAST selected (their parent)."""
    objects = _transforms()
    if len(objects) < 2:
        return keys_scene._done("Select the children, then their parent - last", say)
    data = _copy(xf.RELATIONSHIP, objects[:-1], objects[-1], whole_range)
    count = len(objects) - 1
    return keys_scene._done(f"Relationship copied: {count} object{'s' if count != 1 else ''} to "
                            f"{tf.short_name(objects[-1])}{_range_note(data)}", say)


def copy_world_range(say: bool = False) -> str:
    return copy_world(True, say)


def copy_relationship_range(say: bool = False) -> str:
    return copy_relationship(True, say)


def _range_note(data: dict) -> str:
    count = len(data["objects"][0]["frames"]) if data["objects"] else 0
    return f" on {count} frames" if count > 1 else ""


def _copy(kind: str, objects: list, parent, whole_range: bool) -> dict:
    now = float(cmds.currentTime(query=True))
    items = [{"name": tf.short_name(node), "path": node, "frames": {}} for node in objects]
    times = _frames_to_copy(whole_range)
    try:
        for time in times:
            if len(times) > 1:
                cmds.currentTime(time, update=True)
            above = al._matrix(f"{parent}.worldMatrix[0]").inverse() if parent else None
            for item in items:
                matrix = al.pivot_matrix(item["path"])
                if above is not None:
                    matrix = matrix * above
                item["frames"][xf.frame_key(time)] = list(matrix)
    finally:
        if len(times) > 1:
            cmds.currentTime(now, update=True)
    data = {"format": tf.FORMAT, "version": tf.VERSION, "kind": kind, "frame": now, "objects": items}
    if parent:
        data["parent"] = parent
    ts._store(data)
    return data


# --------------------------------------------------------------------------- paste

def paste_world(mode: str = xf.NOW, say: bool = False) -> str:
    """Paste Xform World Space onto the selection (`mode` NOW / NEXT / ALL / BAKE - xform.plan)."""
    data = ts._fetch(xf.WORLD)
    if not data:
        return keys_scene._done(NO_COPY.format("Xform World Space"), say)
    targets = _transforms()
    if not targets:
        return keys_scene._done("Select where to paste the world space", say)
    pairs = tf.pair([item["path"] for item in data["objects"]], targets)
    if not pairs:
        return keys_scene._done("The copied names fit none of the selected objects", say)
    jobs = [(node, data["objects"][index]["frames"], None, ts._curves(node)) for index, node in pairs]
    return _paste(xf.WORLD, jobs, mode, say)


def paste_relationship(mode: str = xf.NOW, say: bool = False) -> str:
    """Paste Xform Relationship: the selected children put by the copied relationship to the LAST selected (the
    parent, never moved)."""
    data = ts._fetch(xf.RELATIONSHIP)
    if not data:
        return keys_scene._done(NO_COPY.format("Xform Relationship"), say)
    objects = _transforms()
    if len(objects) < 2:
        return keys_scene._done("Select the children, then their parent - last", say)
    parent, children = objects[-1], objects[:-1]
    pairs = tf.pair([item["path"] for item in data["objects"]], children)
    if not pairs:
        return keys_scene._done("The copied names fit none of the selected children", say)
    jobs = [(node, data["objects"][index]["frames"], parent, ts._curves(node)) for index, node in pairs]
    return _paste(xf.RELATIONSHIP, jobs, mode, say)


def paste_world_next(say: bool = False) -> str:
    return paste_world(xf.NEXT, say)


def paste_world_all_keys(say: bool = False) -> str:
    return paste_world(xf.ALL, say)


def paste_world_bake(say: bool = False) -> str:
    return paste_world(xf.BAKE, say)


def paste_relationship_next(say: bool = False) -> str:
    return paste_relationship(xf.NEXT, say)


def paste_relationship_all_keys(say: bool = False) -> str:
    return paste_relationship(xf.ALL, say)


def paste_relationship_bake(say: bool = False) -> str:
    return paste_relationship(xf.BAKE, say)


def _key_times(node: str) -> list:
    return [time for curve in ts._curves(node).values()
            for time in (cmds.keyframe(curve, query=True, timeChange=True) or [])]


def _put(node: str, frames: dict, parent, time: float) -> list:
    import maya.api.OpenMaya as om
    copied = xf.at(frames, time)
    if copied is None:
        return []
    matrix = om.MMatrix(copied)
    if parent:
        matrix = matrix * al._matrix(f"{parent}.worldMatrix[0]")
    there = om.MPoint(matrix[12], matrix[13], matrix[14])
    return al.put_to(node, al._turn(matrix), there, MOVE_TURN)


def _paste(kind: str, jobs: list, mode: str, say: bool) -> str:
    now = float(cmds.currentTime(query=True))
    span = scene.timeline_range()
    span = (span[0], span[1] - 1.0) if span else None
    plans = []
    for node, frames, parent, curves in jobs:
        keys = _key_times(node) + (_key_times(parent) if parent else [])
        plans.append((node, frames, parent, curves, xf.plan(mode, keys, now, span, _playback())))
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        if all(times is None for *_rest, times in plans):
            autokey = cmds.autoKeyframe(query=True, state=True)
            for node, frames, parent, curves, _times in plans:
                for attribute in _put(node, frames, parent, now):
                    if autokey and attribute in curves:
                        cmds.setKeyframe(node, attribute=attribute, time=now)
            return keys_scene._done(xf.describe(kind, len(jobs)), say)
        every = sorted({time for *_rest, times in plans for time in (times or [])})
        for time in every:            # frame by frame: a parent's motion is followed
            cmds.currentTime(time, update=True)
            for node, frames, parent, _curves, times in plans:
                if times and time in times:
                    for attribute in _put(node, frames, parent, time):
                        cmds.setKeyframe(node, attribute=attribute, time=time)
        cmds.currentTime(every[-1] if mode == xf.NEXT else now, update=True)
    finally:
        cmds.undoInfo(closeChunk=True)
    return keys_scene._done(xf.describe(kind, len(jobs), len(every)), say)
