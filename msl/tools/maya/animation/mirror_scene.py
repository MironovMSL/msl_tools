# tools/maya/animation/mirror_scene.py
"""MIRROR in the scene (the rules and the measurements: mirror.py).

The opposite of a control is found by its NAME (the Rename tool's rule and the user's own side words: lf_arm_ctrl
<-> rt_arm_ctrl, arm_L <-> arm_R); a name with no side word is a middle control, its own opposite.
The channel signs come from the two controls' axes AT REST - the frame the translate channels move in (the parent's
world matrix x the offset parent matrix) and the one the rotate channels turn about (that x a joint's orient) - so
the pose they hold now does not matter. SNAPSHOT MIRROR SETTINGS keeps the signs of the selected controls as their
axes are NOW (the rig in its default pose - for rigs whose rest frames say nothing, e.g. offsets in set-driven
groups), under the name without namespace in configsMayaMng "animation" `mirror` {name: {channel: sign}}; a kept
sign wins over the worked-out one, and one channel can be flipped by hand (its right-click menu).

What is mirrored, as measured on the reference:
    nothing highlighted  the values on the current frame; with Maya's auto key on, a channel gets a key there when
                         it or the source's channel is animated
    a highlighted span   keys: on the target, the keys inside the span are replaced by the source's, at the source's
                         key times there (its tangents mirrored), auto key or not
    Mirror All Keys      the whole animation, curves replaced
Every action is ONE undo step ("MSL Mirror").
"""
from __future__ import annotations

from maya import cmds

from msl_tools.msl.tools.maya.animation import keys_scene
from msl_tools.msl.tools.maya.animation import mirror as mr
from msl_tools.msl.tools.maya.animation import scene
from msl_tools.msl.tools.maya.animation import transfer_scene as ts

UNDO_NAME = "MSL Mirror"
KEY = "mirror"
NOTHING_SELECTED = "Select the controls to mirror"

_store_override = None      # tests put a plain dict here instead of the config


# --------------------------------------------------------------------------- sides and opposites

def _sides():
    from msl_tools.msl.tools.maya.rename import rules
    try:
        from msl_tools.msl.core.resources import Resources
        saved = Resources().configsMayaMng.get_config("rename")["settings"]
        return rules.Sides.from_settings(saved.get("sides"))
    except Exception:
        return rules.Sides()


def side(node: str, sides=None) -> str:
    sides = sides or _sides()
    found = mr.name_side(node, [sides.prefixes.get(mr.LEFT, "")], [sides.prefixes.get(mr.RIGHT, "")])
    return found or mr.CENTER


def opposite(node: str, sides=None) -> str:
    """The long name of the control on the other side, the node itself for a middle one, "" when the other side's
    name is not in the scene (or not one node)."""
    from msl_tools.msl.tools.maya.rename import rules
    sides = sides or _sides()
    if side(node, sides) == mr.CENTER:
        return node
    # the whole path mirrored first (a rig of groups named by side), else the node's own name alone
    parts = node.split("|")
    whole = "|".join(_mirrored_part(part, rules, sides) for part in parts)
    if whole != node and cmds.objExists(whole):
        found = cmds.ls(whole, long=True) or []
        if len(found) == 1:
            return found[0]
    short = _mirrored_part(parts[-1], rules, sides)
    found = cmds.ls(short, long=True, type="transform") or []
    return found[0] if len(found) == 1 and found[0] != node else ""


def _mirrored_part(part: str, rules, sides) -> str:
    namespace, sep, name = part.rpartition(":")
    return namespace + sep + rules.mirror(name, sides) if part else part


# --------------------------------------------------------------------------- signs

def _read() -> dict:
    if _store_override is not None:
        return _store_override
    try:
        from msl_tools.msl.tools.maya.animation import default_pose
        data = default_pose._config().data.get(KEY)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write(store: dict) -> None:
    if _store_override is not None:
        _store_override.clear()
        _store_override.update(store)
        return
    from msl_tools.msl.tools.maya.animation import default_pose
    default_pose._config()[KEY] = store


def _rows(matrix) -> tuple:
    values = list(matrix)
    return tuple(tuple(values[row * 4: row * 4 + 3]) for row in range(3))


def rest_frames(node: str) -> tuple:
    """(translate frame, rotate frame) of a control at rest, each three world axis vectors."""
    import maya.api.OpenMaya as om
    parent = om.MMatrix(cmds.getAttr(f"{node}.parentMatrix[0]"))
    if cmds.attributeQuery("offsetParentMatrix", node=node, exists=True):
        parent = om.MMatrix(cmds.getAttr(f"{node}.offsetParentMatrix")) * parent
    rotate = parent
    if cmds.nodeType(node) == "joint":
        orient = [om.MAngle(value, om.MAngle.uiUnit()).asRadians()
                  for value in cmds.getAttr(f"{node}.jointOrient")[0]]
        rotate = om.MEulerRotation(*orient).asMatrix() * parent
    return _rows(parent), _rows(rotate)


def now_frames(node: str) -> tuple:
    """The control's axes as they are NOW (for a snapshot of a rig in its default pose)."""
    import maya.api.OpenMaya as om
    world = _rows(om.MMatrix(cmds.getAttr(f"{node}.worldMatrix[0]")))
    return world, world


def signs(source: str, target: str, sides=None, store: dict | None = None) -> dict:
    """{channel: sign} for a value going from `source` to `target`: the kept snapshot of the target (else of the
    source), else worked out from the two controls' rest axes."""
    store = _read() if store is None else store
    for node in (target, source):
        kept = store.get(mr_short(node))
        if isinstance(kept, dict) and kept:
            return {key: int(value) for key, value in kept.items()}
    sides = sides or _sides()
    source_t, source_r = rest_frames(source)
    target_t, target_r = rest_frames(target)
    return mr.channel_signs(source_t, target_t, source_r, target_r, sides.axis)[0]


def mr_short(node: str) -> str:
    return node.split("|")[-1].split(":")[-1]


# --------------------------------------------------------------------------- snapshot

def snapshot(say: bool = False) -> str:
    """Keep the signs of the selected controls (and their opposites) as their axes are now."""
    objects = scene.selected_objects()
    if not objects:
        return keys_scene._done("Select controls of the rig in its default pose (T-pose)", say)
    sides = _sides()
    store = dict(_read())
    count, loose, alone = 0, [], 0
    done = set()
    for node in objects:
        other = opposite(node, sides)
        if not other:
            alone += 1
            continue
        if node in done:
            continue
        node_t, node_r = now_frames(node)
        other_t, other_r = now_frames(other)
        found, bad = mr.channel_signs(node_t, other_t, node_r, other_r, sides.axis)
        for one in {node, other}:       # the signs are the same both ways
            done.add(one)
            store[mr_short(one)] = found
            count += 1
        loose += [f"{mr_short(node)}.{channel}" for channel in bad]
    _write(store)
    text = f"Mirror settings kept for {count} control{'s' if count != 1 else ''}"
    if alone:
        text += f" · {alone} without an opposite"
    if loose:
        text += f" · not mirror images: {', '.join(loose[:4])}{'…' if len(loose) > 4 else ''}"
    return keys_scene._done(text, say)


def kept(node: str) -> dict:
    return dict(_read().get(mr_short(node)) or {})


def flip_channel(channel: str, say: bool = False) -> str:
    """FIX MIRROR SETTING: the sign of one channel turned over for the selected controls (their worked-out signs
    are kept first, so the others stay as they were)."""
    objects = scene.selected_objects()
    if not objects:
        return keys_scene._done("Select the controls whose channel mirrors the wrong way", say)
    sides = _sides()
    store = dict(_read())
    names = []
    for node in objects:
        other = opposite(node, sides) or node
        current = signs(node, other, sides, store)
        current[channel] = -int(current.get(channel, 1))
        for one in {node, other}:
            store[mr_short(one)] = dict(current)
            names.append(mr_short(one))
    _write(store)
    return keys_scene._done(f"{channel} now mirrors the other way on {', '.join(sorted(set(names)))}", say)


def forget(every: bool = False, say: bool = False) -> str:
    if every:
        _write({})
        return keys_scene._done("Mirror settings forgotten - signs are worked out from the rig again", say)
    sides = _sides()
    store = dict(_read())
    gone = 0
    for node in scene.selected_objects():
        for one in {node, opposite(node, sides) or node}:
            gone += store.pop(mr_short(one), None) is not None
    _write(store)
    return keys_scene._done(f"Mirror settings of {gone} control{'s' if gone != 1 else ''} forgotten", say)


# --------------------------------------------------------------------------- what is mirrored

def _channels(source: str, target: str) -> list:
    """The source's Channel Box channels the target has and can take."""
    return [attribute for attribute in ts._pose_attributes(source) if ts._settable(target, attribute)]


def _value(node: str, attribute: str, time=None):
    try:
        value = cmds.getAttr(f"{node}.{attribute}", time=time) if time is not None \
            else cmds.getAttr(f"{node}.{attribute}")
    except (RuntimeError, ValueError):
        return None
    return float(value) if isinstance(value, (bool, int, float)) else None


def _pairs(mode: str) -> tuple:
    objects = scene.selected_objects()
    sides = _sides()
    found, alone = mr.pairs(objects, lambda node: opposite(node, sides), lambda node: side(node, sides), mode)
    return found, alone, sides


def mirror_pose(mode: str = mr.POSE, say: bool = False) -> str:
    """Mirror Pose (mode POSE) / Mirror to Right / Mirror to Left: values on this frame, or keys in a highlighted
    span."""
    if not scene.selected_objects():
        return keys_scene._done(NOTHING_SELECTED, say)
    found, alone, sides = _pairs(mode)
    if not found:
        return keys_scene._done("No opposite found for the selection (named lf_ / rt_, _L / _R, Left / Right ...)",
                                say)
    span = scene.timeline_range()
    # everything is read before anything is written: a selected pair swaps
    reads = []
    if span:
        start, end = span[0], span[1] - 1.0
        for source, target in found:
            reads.append((source, target, signs(source, target, sides), _span_read(source, target, start, end)))
    else:
        for source, target in found:
            values = {attribute: _value(source, attribute) for attribute in _channels(source, target)}
            reads.append((source, target, signs(source, target, sides), values))
    keyed = 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for source, target, table, data in reads:
            if span:
                keyed += _span_write(target, table, data, span[0], span[1] - 1.0)
            else:
                keyed += _now_write(source, target, table, data)
    finally:
        cmds.undoInfo(closeChunk=True)
    text = mr.describe(len(found), len(alone), "keys" if span else "pose")
    if span:
        text += f" in frames {span[0]:g}-{span[1] - 1:g}"
    elif keyed:
        text += f" · {keyed} keyed (auto key)"
    return keys_scene._done(text, say)


def _now_write(source: str, target: str, table: dict, values: dict) -> int:
    autokey = cmds.autoKeyframe(query=True, state=True)
    animated = set(ts._curves(source)) | set(ts._curves(target)) if autokey else set()
    now = float(cmds.currentTime(query=True))
    keyed = 0
    for attribute, value in values.items():
        if value is None:
            continue
        try:
            cmds.setAttr(f"{target}.{attribute}", value * mr.sign_of(table, attribute))
        except RuntimeError:
            continue
        if attribute in animated:
            cmds.setKeyframe(target, attribute=attribute, time=now)
            keyed += 1
    return keyed


def _span_read(source: str, target: str, start: float, end: float) -> dict:
    curves = ts._curves(source)
    rows = {attribute: ts._key_rows(curve, start, end) for attribute, curve in curves.items()}
    times = sorted({row[0] for found in rows.values() for row in found})
    if not times:
        now = float(cmds.currentTime(query=True))
        times = [now] if start - 1e-6 <= now <= end + 1e-6 else []
    data = {}
    for attribute in _channels(source, target):
        own = {row[0]: row for row in rows.get(attribute, [])}
        data[attribute] = {"rows": list(own.values()),
                           "others": {time: _value(source, attribute, time) for time in times if time not in own},
                           "weighted": bool(curves.get(attribute) and
                                            (cmds.keyTangent(curves[attribute], query=True,
                                                             weightedTangents=True) or [0])[0])}
    return data


def _span_write(target: str, table: dict, data: dict, start: float, end: float) -> int:
    count = 0
    for attribute, channel in data.items():
        sign = mr.sign_of(table, attribute)
        curve = ts._curves(target).get(attribute)
        infinity = {"pre": 0, "post": 0}
        if curve:
            infinity = {"pre": int(cmds.getAttr(f"{curve}.preInfinity")),
                        "post": int(cmds.getAttr(f"{curve}.postInfinity"))}
            cmds.cutKey(target, attribute=attribute, time=(start, end), clear=True)
        rows = [mr.mirrored_row(row, sign) for row in channel["rows"]]
        if rows:
            count += ts._put_keys(target, attribute, dict(infinity, keys=rows, weighted=channel["weighted"]), 0.0)
        for time, value in channel["others"].items():
            if value is not None:
                cmds.setKeyframe(target, attribute=attribute, time=time, value=value * sign)
                count += 1
    return count


def mirror_to_right(say: bool = False) -> str:
    return mirror_pose(mr.TO_RIGHT, say)


def mirror_to_left(say: bool = False) -> str:
    return mirror_pose(mr.TO_LEFT, say)


def mirror_all_keys(say: bool = False) -> str:
    """The whole animation of each selected control onto its opposite (both of a pair = a swap, a middle control
    onto itself): the target's curves replaced, a channel the source has no curve on takes its value."""
    if not scene.selected_objects():
        return keys_scene._done(NOTHING_SELECTED, say)
    found, alone, sides = _pairs(mr.POSE)
    if not found:
        return keys_scene._done("No opposite found for the selection (named lf_ / rt_, _L / _R, Left / Right ...)",
                                say)
    reads = []
    for source, target in found:
        curves = ts._curves(source)
        data = {}
        for attribute in _channels(source, target):
            curve = curves.get(attribute)
            if curve:
                data[attribute] = {
                    "keys": ts._key_rows(curve, float("-inf"), float("inf")),
                    "weighted": bool((cmds.keyTangent(curve, query=True, weightedTangents=True) or [0])[0]),
                    "pre": int(cmds.getAttr(f"{curve}.preInfinity")),
                    "post": int(cmds.getAttr(f"{curve}.postInfinity"))}
            else:
                data[attribute] = {"value": _value(source, attribute)}
        reads.append((target, signs(source, target, sides), data))
    keys = 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for target, table, data in reads:
            for attribute, channel in data.items():
                sign = mr.sign_of(table, attribute)
                if ts._curves(target).get(attribute):
                    cmds.cutKey(target, attribute=attribute, clear=True)
                if "keys" in channel:
                    channel = dict(channel, keys=[mr.mirrored_row(row, sign) for row in channel["keys"]])
                    keys += ts._put_keys(target, attribute, channel, 0.0)
                elif channel["value"] is not None:
                    try:
                        cmds.setAttr(f"{target}.{attribute}", channel["value"] * sign)
                    except RuntimeError:
                        pass
    finally:
        cmds.undoInfo(closeChunk=True)
    return keys_scene._done(mr.describe(len(found), len(alone), "animation") + f" · {keys} keys", say)


def select_opposite(say: bool = False) -> str:
    """The opposites of the selected controls selected instead (a middle one stays)."""
    objects = scene.selected_objects()
    if not objects:
        return keys_scene._done(NOTHING_SELECTED, say)
    sides = _sides()
    found = [opposite(node, sides) for node in objects]
    picked = [node for node in found if node]
    if picked:
        cmds.select(list(dict.fromkeys(picked)), replace=True)
    missing = len(found) - len(picked)
    text = f"Selected {len(picked)} opposite{'s' if len(picked) != 1 else ''}"
    return keys_scene._done(text + (f" · {missing} without one" if missing else ""), say)
