# tools/maya/animation/default_pose.py
"""Default pose: reset the selected objects' channels, and a PREFERRED default pose kept by the user.

What the reference does, measured (Maya 2025, 2026-10-20), and ours does the same:
    Reset Pose        every keyable channel AND every non-keyable one shown in the Channel Box (visibility
                      too) back to its default; attributes hidden from the Channel Box are left
    Reset Translation / Rotation / Scale / all three   only translate / rotate / scale X Y Z
    locked channels are left (and channels something other than keys drives)
    autokey ON  -> an animated channel gets a KEY on the current frame (an existing key there takes the value,
                   a new one Maya's default tangents); a channel without keys only takes the value
    autokey OFF -> values only, no key (an animated channel springs back at the next frame change)
    one undo step
The default is the user's SNAPSHOT where one is kept (Snapshot Preferred Default Pose: each channel's value as
it was when snapshot), else the node's `default_<attribute>` (as tools/maya/scripts/reset_attributes.py), else
Maya's own default. Blend to Default and Scale From Default use the same (scene.py asks `default_for`).

Deliberately different from the reference: it keeps a snapshot under the node's full name (a second copy of
the rig in another namespace was reset to Maya's defaults, not the snapshot); ours keys it by the name WITHOUT
the namespace (and without the path), so every copy of a rig of the same naming shares it - the user's ask.
Kept in configsMayaMng "animation": `default_pose` {name: {attribute: value}}.
"""
from __future__ import annotations

from maya import cmds

UNDO_NAME = "MSL Reset Pose"
KEY = "default_pose"
PREFIX = "default_"
PARTS = {
    "translate": ("translateX", "translateY", "translateZ"),
    "rotate": ("rotateX", "rotateY", "rotateZ"),
    "scale": ("scaleX", "scaleY", "scaleZ"),
}
PARTS["trs"] = PARTS["translate"] + PARTS["rotate"] + PARTS["scale"]
TITLES = {"all": "pose", "translate": "translation", "rotate": "rotation", "scale": "scale",
          "trs": "translation, rotation and scale"}

_store_override = None      # tests put a plain dict here instead of the config


def short_name(node: str) -> str:
    """`|grp|hero:arm_ctrl` -> `arm_ctrl`: the key a snapshot is kept under."""
    return node.split("|")[-1].split(":")[-1]


def _config():
    from msl_tools.msl.core.resources import Resources
    return Resources().configsMayaMng.get_config("animation", defaults={"settings": {}})


def _read() -> dict:
    if _store_override is not None:
        return _store_override
    try:
        data = _config().data.get(KEY)
    except Exception:          # no config to be had: no snapshot
        return {}
    return data if isinstance(data, dict) else {}


def _write(store: dict) -> None:
    if _store_override is not None:
        _store_override.clear()
        _store_override.update(store)
        return
    _config()[KEY] = store


def kept_names() -> list:
    return sorted(_read())


def _long(node: str, attribute: str) -> str:
    try:
        return cmds.attributeQuery(attribute.split("[")[0], node=node, longName=True)
    except RuntimeError:
        return attribute


def default_for(node: str, attribute: str, store: dict | None = None):
    """The value `node.attribute` goes back to: the snapshot's, else `default_<attribute>`, else Maya's
    default. None = none to be had (a compound, a text)."""
    store = _read() if store is None else store
    name = _long(node, attribute)
    kept = (store.get(short_name(node)) or {}).get(name)
    if isinstance(kept, (int, float)) and not isinstance(kept, bool):
        return float(kept)
    for extra in (PREFIX + name, PREFIX + attribute):
        try:
            if cmds.attributeQuery(extra, node=node, exists=True):
                value = cmds.getAttr(f"{node}.{extra}")
                if isinstance(value, (int, float)):
                    return float(value)
        except (RuntimeError, ValueError):
            break
    try:
        values = cmds.attributeQuery(name, node=node, listDefault=True)
    except RuntimeError:
        return None
    return float(values[0]) if values and len(values) == 1 else None


def channels(node: str, which: str = "all") -> list:
    """The long names `which` covers on `node`: "all" = keyable + shown in the Channel Box; else PARTS."""
    if which != "all":
        return [name for name in PARTS[which] if cmds.attributeQuery(name, node=node, exists=True)]
    names = list(cmds.listAttr(node, keyable=True) or [])
    names += [name for name in cmds.listAttr(node, channelBox=True) or [] if name not in names]
    return list(dict.fromkeys(_long(node, name) for name in names if "." not in name))


def _sources(plug: str) -> list:
    return cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []


def _selected() -> list:
    return cmds.ls(selection=True, objectsOnly=True, long=True, type="transform") or []


def reset(which: str = "all", say: bool = False) -> str:
    """The selected objects' channels (`which`: all / translate / rotate / scale / trs) back to their default;
    autokey on = animated channels keyed on this frame. One undo step."""
    from msl_tools.msl.tools.maya.animation.keys_scene import _done
    nodes = _selected()
    if not nodes:
        return _done("Select objects to reset", say)
    store = _read()
    autokey = bool(cmds.autoKeyframe(query=True, state=True))
    now = cmds.currentTime(query=True)
    changed, keyed, left = 0, 0, 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for node in nodes:
            for name in channels(node, which):
                plug = f"{node}.{name}"
                try:
                    if cmds.getAttr(plug, lock=True):
                        left += 1
                        continue
                    sources = _sources(plug)
                    if any(not cmds.nodeType(s).startswith("animCurve") for s in sources):
                        left += 1           # a constraint, an expression ... drives it
                        continue
                    value = cmds.getAttr(plug)
                    if isinstance(value, (list, tuple)) or isinstance(value, str):
                        continue
                    default = default_for(node, name, store)
                    if default is None:
                        continue
                    animated = bool(sources)
                    if animated and autokey:
                        cmds.setKeyframe(node, attribute=name, time=now, value=default)
                        cmds.setAttr(plug, default)     # the plug shows it now, not after a frame change
                        keyed += 1
                    elif abs(float(value) - default) > 1e-9:
                        cmds.setAttr(plug, default)
                    else:
                        continue
                    changed += 1
                except (RuntimeError, ValueError, TypeError):
                    left += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    text = f"Reset {TITLES.get(which, which)}: {changed} channel{'s' if changed != 1 else ''} on " \
           f"{len(nodes)} object{'s' if len(nodes) != 1 else ''}"
    if keyed:
        text += f" ({keyed} keyed - autokey)"
    if left:
        text += f" · {left} locked / driven - left"
    return _done(text, say)


def snapshot(say: bool = False) -> str:
    """The selected objects' channels as they are now kept as their preferred default pose (by name without the
    namespace); a snapshot of one object replaces its earlier one."""
    from msl_tools.msl.tools.maya.animation.keys_scene import _done
    nodes = _selected()
    if not nodes:
        return _done("Select the objects whose pose is their default", say)
    store = dict(_read())
    count = 0
    for node in nodes:
        pose = {}
        for name in channels(node):
            try:
                value = cmds.getAttr(f"{node}.{name}")
            except (RuntimeError, ValueError):
                continue
            if isinstance(value, (int, float)):
                pose[name] = round(float(value), 6)
        store[short_name(node)] = pose
        count += len(pose)
    _write(store)
    return _done(f"Default pose kept: {len(nodes)} object{'s' if len(nodes) != 1 else ''}, {count} channels - "
                 f"Reset and Blend to Default use it", say)


def forget(everything: bool = False, say: bool = False) -> str:
    """Forgets the preferred default pose of the selected objects (or of every object)."""
    from msl_tools.msl.tools.maya.animation.keys_scene import _done
    store = dict(_read())
    if everything:
        gone = len(store)
        store = {}
    else:
        names = [short_name(node) for node in _selected()]
        gone = sum(1 for name in names if store.pop(name, None) is not None)
    if not gone:
        return _done("No default pose kept for " + ("any object" if everything else "the selected objects"), say)
    _write(store)
    return _done(f"Default pose forgotten: {gone} object{'s' if gone != 1 else ''} - back to the rig's own", say)
