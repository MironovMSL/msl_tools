# tools/maya/animation/transfer_scene.py
"""ANIM / POSE TRANSFER in the scene (the rules and the measurements: transfer.py).

Copy Animation / Copy Pose put the copy on the system clipboard AS TEXT and into a file beside it
(`%TEMP%/msl_tools/animation/transfer_<kind>.json`); Paste reads the clipboard when it holds a copy of ours, else
that file - so a copy made in one Maya pastes in another (on this computer through the file, anywhere through the
text). Export / Import write and read the same text as a file of the user's choice. Every paste is ONE undo step
("MSL Transfer").
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from maya import cmds

from msl_tools.msl.tools.maya.animation import keys_scene
from msl_tools.msl.tools.maya.animation import scene
from msl_tools.msl.tools.maya.animation import transfer as tf

UNDO_NAME = "MSL Transfer"
NOTHING_SELECTED = "Select the objects to copy"
NO_COPY = "Nothing copied yet: Copy Animation / Copy Pose first (here or in another Maya)"


def folder() -> Path:
    return Path(tempfile.gettempdir()) / "msl_tools" / "animation"


def _file(kind: str) -> Path:
    return folder() / f"transfer_{kind}.json"


# --------------------------------------------------------------------------- the copy's two homes

def _store(data: dict) -> None:
    """The copy on the clipboard (text) and in its file."""
    text = tf.to_text(data)
    try:
        import msl_tools.msl.ui.qt_bindings as qt
        qt.QtWidgets.QApplication.clipboard().setText(text)
    except Exception:
        pass
    try:
        from msl_tools.msl.core.fs.safe_json import write_json_atomic
        folder().mkdir(parents=True, exist_ok=True)
        write_json_atomic(_file(data["kind"]), data)
    except Exception:
        pass


def _fetch(kind: str) -> "dict | None":
    """The copy to paste: the clipboard's when it holds one of ours of that kind, else the file's."""
    try:
        import msl_tools.msl.ui.qt_bindings as qt
        data = tf.from_text(qt.QtWidgets.QApplication.clipboard().text(), kind)
        if data:
            return data
    except Exception:
        pass
    path = _file(kind)
    if path.is_file():
        try:
            return tf.from_text(path.read_text(encoding="utf-8"), kind)
        except OSError:
            return None
    return None


# --------------------------------------------------------------------------- reading the scene

def _curves(node: str) -> dict:
    """{attribute: anim curve} - the node's channels driven straight by an anim curve."""
    found = {}
    pairs = cmds.listConnections(node, type="animCurve", connections=True, source=True, destination=False) or []
    for plug, curve in zip(pairs[0::2], pairs[1::2]):
        attribute = plug.split(".", 1)[1]
        if cmds.nodeType(curve) in ("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT"):
            found[attribute] = curve
    return found


def _key_rows(curve: str, start: float, end: float) -> list:
    times = cmds.keyframe(curve, query=True, timeChange=True) or []
    values = cmds.keyframe(curve, query=True, valueChange=True) or []
    rows = []
    for index, (time, value) in enumerate(zip(times, values)):
        if not tf.in_span(time, start, end):
            continue
        span = dict(index=(index, index))
        query = lambda **flag: (cmds.keyTangent(curve, query=True, **span, **flag) or [None])[0]
        rows.append([float(time), float(value), query(inTangentType=True), query(outTangentType=True),
                     float(query(inAngle=True)), float(query(outAngle=True)), float(query(inWeight=True)),
                     float(query(outWeight=True)), bool(query(lock=True)), bool(query(weightLock=True)),
                     bool(cmds.getAttr(f"{curve}.keyBreakdown[{index}]")),
                     bool(cmds.getAttr(f"{curve}.keyTickDrawSpecial[{index}]"))])
    return rows


def _pose_attributes(node: str) -> list:
    """Every channel of the Channel Box (keyable + shown), single numbers only."""
    names = (cmds.listAttr(node, keyable=True, scalar=True) or []) + \
        (cmds.listAttr(node, channelBox=True, scalar=True) or [])
    seen, out = set(), []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _span() -> tuple:
    """What a copy takes: the highlighted span (its last whole frame), else the animation range (measured)."""
    highlight = scene.timeline_range()
    if highlight:
        return highlight[0], highlight[1] - 1.0
    return (float(cmds.playbackOptions(query=True, animationStartTime=True)),
            float(cmds.playbackOptions(query=True, animationEndTime=True)))


# --------------------------------------------------------------------------- copy

def copy_animation(say: bool = False) -> str:
    objects = scene.selected_objects()
    if not objects:
        return keys_scene._done(NOTHING_SELECTED, say)
    start, end = _span()
    items, keys = [], 0
    for node in objects:
        channels = {}
        for attribute, curve in _curves(node).items():
            rows = _key_rows(curve, start, end)
            if not rows:
                continue
            channels[attribute] = {
                "keys": rows, "weighted": bool((cmds.keyTangent(curve, query=True, weightedTangents=True) or [0])[0]),
                "pre": int(cmds.getAttr(f"{curve}.preInfinity")),
                "post": int(cmds.getAttr(f"{curve}.postInfinity"))}
            keys += len(rows)
        if channels:
            static = {}
            for attribute in _pose_attributes(node):
                if attribute in channels:
                    continue
                try:
                    value = cmds.getAttr(f"{node}.{attribute}")
                except (RuntimeError, ValueError):
                    continue
                if isinstance(value, (bool, int, float)):
                    static[attribute] = float(value)
            items.append({"name": tf.short_name(node), "path": node, "channels": channels, "static": static})
    if not items:
        return keys_scene._done(f"No keys on the selection in frames {start:g}-{end:g}", say)
    data = {"format": tf.FORMAT, "version": tf.VERSION, "kind": tf.ANIMATION, "start": start, "end": end,
            "objects": items}
    _store(data)
    return keys_scene._done(f"Animation copied: {tf.describe(data)} - paste here or in another Maya", say)


def copy_pose(say: bool = False) -> str:
    objects = scene.selected_objects()
    if not objects:
        return keys_scene._done(NOTHING_SELECTED, say)
    items = []
    for node in objects:
        channels = {}
        for attribute in _pose_attributes(node):
            try:
                value = cmds.getAttr(f"{node}.{attribute}")
            except (RuntimeError, ValueError):
                continue
            if isinstance(value, (bool, int, float)):
                channels[attribute] = {"value": float(value)}
        if channels:
            items.append({"name": tf.short_name(node), "path": node, "channels": channels})
    if not items:
        return keys_scene._done("No channels on the selection", say)
    data = {"format": tf.FORMAT, "version": tf.VERSION, "kind": tf.POSE,
            "frame": float(cmds.currentTime(query=True)), "objects": items}
    _store(data)
    return keys_scene._done(f"Pose copied: {tf.describe(data)} - paste here or in another Maya", say)


# --------------------------------------------------------------------------- paste

def _targets(data: dict) -> list:
    """[(copied item, target node)]: the selection paired with the copy (transfer.pair); nothing selected = the
    objects of the copied names in this scene."""
    items = data["objects"]
    selected = scene.selected_objects()
    if selected:
        return [(items[index], node) for index, node in tf.pair([item["path"] for item in items], selected)]
    found, taken = [], set()
    for item in items:
        if cmds.objExists(item["path"]):
            matches = cmds.ls(item["path"], long=True)
        else:
            matches = cmds.ls(item["name"], f"*:{item['name']}", long=True) or []
        if len(matches) == 1 and matches[0] not in taken:      # each target once: the first copied object wins
            taken.add(matches[0])
            found.append((item, matches[0]))
    return found


def _settable(node: str, attribute: str) -> bool:
    plug = f"{node}.{attribute}"
    return cmds.objExists(plug) and cmds.getAttr(plug, settable=True)


def _put_keys(node: str, attribute: str, channel: dict, offset: float) -> int:
    """The copied keys onto node.attribute, `offset` frames later, with their tangents, weights, locks and colors."""
    rows = channel.get("keys") or []
    plug = f"{node}.{attribute}"
    for row in rows:
        cmds.setKeyframe(node, attribute=attribute, time=row[0] + offset, value=row[1])
    curve = (cmds.listConnections(plug, type="animCurve", source=True, destination=False) or [None])[0]
    if curve is None:
        return 0
    if channel.get("weighted"):
        cmds.keyTangent(curve, edit=True, weightedTangents=True)
    times = cmds.keyframe(curve, query=True, timeChange=True) or []
    for row in rows:
        time = row[0] + offset
        index = next((i for i, t in enumerate(times) if abs(t - time) < 1e-4), None)
        if index is None:
            continue
        span = dict(index=(index, index))
        in_type, out_type = row[2], row[3]
        weighted = bool(channel.get("weighted"))
        cmds.keyTangent(curve, edit=True, lock=False, **span)
        if weighted:
            cmds.keyTangent(curve, edit=True, weightLock=False, **span)
        flags = {"inTangentType": in_type, "outTangentType": out_type}
        if in_type == "fixed":
            flags["inAngle"] = row[4]
        if out_type == "fixed":
            flags["outAngle"] = row[5]
        if channel.get("weighted"):
            flags["inWeight"], flags["outWeight"] = row[6], row[7]
        cmds.keyTangent(curve, edit=True, **span, **flags)
        cmds.keyTangent(curve, edit=True, lock=row[8], **span)
        if weighted:
            cmds.keyTangent(curve, edit=True, weightLock=row[9], **span)
        cmds.keyframe(curve, edit=True, breakdown=row[10], **span)
        cmds.setAttr(f"{curve}.keyTickDrawSpecial[{index}]", row[11])
    for side in ("pre", "post"):
        try:
            cmds.setAttr(f"{curve}.{side}Infinity", int(channel.get(side, 0)))
        except (RuntimeError, TypeError, ValueError):
            pass
    return len(rows)


def paste_animation(mode: str = "insert", say: bool = False) -> str:
    """"insert": the copy's start on the current frame (or the highlighted span's start), the target cleared over
    the span it lands on; "replace": the target's animation replaced by the copy on its own frames (measured)."""
    data = _fetch(tf.ANIMATION)
    if not data:
        return keys_scene._done(NO_COPY, say)
    pairs = _targets(data)
    if not pairs:
        return keys_scene._done("Select where to paste (or have objects of the copied names in the scene)", say)
    now = float(cmds.currentTime(query=True))
    offset, clear_from, clear_to = tf.landing(data["start"], data["end"], now, scene.timeline_range())
    if mode == "replace":
        offset = 0.0
    keys, missing = 0, set()
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for item, node in pairs:
            for attribute, curve in _curves(node).items():
                if mode == "replace":
                    cmds.cutKey(curve, clear=True)
                    # a channel the copy has no keys on takes the copied object's value there (measured: a target's
                    # own curve on tz went, and tz took the source's 0)
                    value = (item.get("static") or {}).get(attribute)
                    if attribute not in item["channels"] and value is not None and _settable(node, attribute):
                        cmds.setAttr(f"{node}.{attribute}", value)
                else:
                    end = clear_to - 1e-3 if scene.timeline_range() else clear_to
                    cmds.cutKey(curve, time=(clear_from, end), clear=True)
            for attribute, channel in item["channels"].items():
                if not _settable(node, attribute):
                    missing.add(attribute)
                    continue
                keys += _put_keys(node, attribute, channel, offset)
    finally:
        cmds.undoInfo(closeChunk=True)
    where = "on their own frames" if mode == "replace" else f"from frame {data['start'] + offset:g}"
    text = (f"Animation pasted ({'replace' if mode == 'replace' else 'insert'}): {keys} keys onto "
            f"{len(pairs)} object{'s' if len(pairs) != 1 else ''} {where}")
    if missing:
        text += f" · not on the target: {', '.join(sorted(missing)[:4])}"
    return keys_scene._done(text, say)


def paste_insert(say: bool = False) -> str:
    return paste_animation("insert", say)


def paste_replace(say: bool = False) -> str:
    return paste_animation("replace", say)


def paste_pose(say: bool = False) -> str:
    """The copied values set; with Maya's auto key on the animated channels get a key on this frame (measured)."""
    data = _fetch(tf.POSE)
    if not data:
        return keys_scene._done(NO_COPY, say)
    pairs = _targets(data)
    if not pairs:
        return keys_scene._done("Select where to paste (or have objects of the copied names in the scene)", say)
    autokey = cmds.autoKeyframe(query=True, state=True)
    now = float(cmds.currentTime(query=True))
    count, keyed = 0, 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for item, node in pairs:
            animated = _curves(node)
            for attribute, channel in item["channels"].items():
                if not _settable(node, attribute):
                    continue
                value = channel["value"]
                try:
                    cmds.setAttr(f"{node}.{attribute}", value)
                except RuntimeError:
                    continue
                if autokey and attribute in animated:
                    cmds.setKeyframe(node, attribute=attribute, time=now)
                    keyed += 1
                count += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    text = f"Pose pasted: {count} channels onto {len(pairs)} object{'s' if len(pairs) != 1 else ''}"
    if keyed:
        text += f" · {keyed} keyed (auto key)"
    return keys_scene._done(text, say)


# --------------------------------------------------------------------------- files

def export_copy(kind: str, path: str) -> str:
    data = _fetch(kind)
    if not data:
        return NO_COPY
    Path(path).write_text(tf.to_text(data), encoding="utf-8")
    return f"Exported: {tf.describe(data)} -> {Path(path).name}"


def import_copy(kind: str, path: str) -> str:
    """A file written by Export becomes the copy (clipboard + file), ready to paste."""
    try:
        data = tf.from_text(Path(path).read_text(encoding="utf-8"), kind)
    except OSError as error:
        return f"Can't read {Path(path).name}: {error}"
    if not data:
        return f"{Path(path).name} holds no {kind} copied with MSL Animation"
    _store(data)
    return f"Imported: {tf.describe(data)} - ready to paste"
