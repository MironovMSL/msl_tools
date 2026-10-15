# tools/maya/labels/scene.py
"""The Maya side of Labels (maya.cmds, no Qt): a Layout built into the scene, read back, removed.

A built layout is a group at the top of the scene — "<layout>_labels", with the namespace in
front when it was built for one: "hero_arm_labels" — tagged with the layout's name and namespace
(attributes TAG / NAMESPACE_TAG), holding one transform per column, each with an mslLabels shape
(the column's name in COLUMN_TAG). The group, not its name, is what is looked for: Maya may have
numbered the name.

A 3D column stands at its anchor because the anchor's worldMatrix drives the column transform's
offsetParentMatrix — the labels stay in their group and still follow the object.

Building is ONE undo step; building a layout again replaces the group built before for the same
layout and namespace. An attribute or anchor that isn't in the scene is not an error: its line is
made without a connection (it shows "-") and it is named in BuildResult.missing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from maya import cmds

from msl_tools.msl.tools.maya.labels import layout as lay

PLUGIN = "msl_labels"
NODE_TYPE = "mslLabels"
TAG = "mslLabelsLayout"            # on the group: the layout's name
NAMESPACE_TAG = "mslLabelsNamespace"  # on the group: the namespace it was built for
COLUMN_TAG = "mslLabelsColumn"     # on a column's transform: the column's name
UNDO_NAME = "MSL Labels"


@dataclass
class BuildResult:
    group: str
    missing: list[str] = field(default_factory=list)  # attributes / anchors not found, as looked for


def ensure_plugin() -> None:
    """Loads the plug-in (by name: Maya Gate's module path finds it without the trust question)."""
    if not cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        try:
            cmds.loadPlugin(PLUGIN, quiet=True)
        except RuntimeError as error:
            raise RuntimeError("The MSL Labels plug-in can't be loaded - start Maya from MSL Tools "
                               "(Maya Gate puts it on Maya's plug-in path).") from error


def _safe(text: str) -> str:
    """A name Maya takes: letters, digits, "_" (anything else becomes "_")."""
    text = re.sub(r"[^A-Za-z0-9_]", "_", text).strip("_") or "labels"
    return text if not text[0].isdigit() else "_" + text


def _tag(node: str, attribute: str, value: str) -> None:
    if not cmds.attributeQuery(attribute, node=node, exists=True):
        cmds.addAttr(node, longName=attribute, dataType="string")
    cmds.setAttr(f"{node}.{attribute}", value, type="string")


def _read_tag(node: str, attribute: str) -> str | None:
    if not cmds.attributeQuery(attribute, node=node, exists=True):
        return None
    return cmds.getAttr(f"{node}.{attribute}") or ""


# --- what is in the scene -----------------------------------------------------------------------

def rigs() -> list[str]:
    """Every group of built labels in the scene (long names)."""
    found = []
    for node in cmds.ls(type="transform", long=True) or []:
        if _read_tag(node, TAG) is not None:
            found.append(node)
    return found


def find(name: str, namespace: str = "") -> str | None:
    """The group built for layout `name` and `namespace`, or None."""
    namespace = namespace.strip(":")
    for group in rigs():
        if _read_tag(group, TAG) == name and (_read_tag(group, NAMESPACE_TAG) or "") == namespace:
            return group
    return None


def namespaces() -> list[str]:
    """The scene's own namespaces (Maya's UI / shared left out), nested ones as "a:b"."""
    names = cmds.namespaceInfo(":", listOnlyNamespaces=True, recurse=True) or []
    return sorted(name for name in names if name not in ("UI", "shared"))


# --- building -----------------------------------------------------------------------------------

def build(layout: lay.Layout, namespace: str | None = None, undo: bool = True) -> BuildResult:
    """Builds `layout` into the scene for `namespace` (None = the layout's own) as one undo step,
    replacing what was built before for the same layout and namespace. `undo=False`: outside
    the undo queue — the window's live update after every edit (a hundred small edits must not
    fill Ctrl+Z; the undo queue itself is left as it was)."""
    ensure_plugin()
    namespace = (layout.namespace if namespace is None else namespace).strip(":")
    if not undo:
        was = cmds.undoInfo(query=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            return _build(layout, namespace)
        finally:
            cmds.undoInfo(stateWithoutFlush=was)
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        return _build(layout, namespace)
    finally:
        cmds.undoInfo(closeChunk=True)


def _build(layout: lay.Layout, namespace: str) -> BuildResult:
    old = find(layout.name, namespace)
    selection = cmds.ls(selection=True, long=True) or []
    if old:
        cmds.delete(old)
    prefix = (_safe(namespace.replace(":", "_")) + "_") if namespace else ""
    name = _safe(layout.name)
    name = name if name.lower().endswith("labels") else name + "_labels"
    group = cmds.group(empty=True, world=True, name=prefix + name)
    _tag(group, TAG, layout.name)
    _tag(group, NAMESPACE_TAG, namespace)
    result = BuildResult(group=cmds.ls(group, long=True)[0])
    for column in layout.columns:
        _build_column(result, column, namespace)
    # cmds.group selects the new group: put back what the user had selected (what still exists)
    kept = [node for node in selection if cmds.objExists(node)]
    cmds.select(kept, replace=True) if kept else cmds.select(clear=True)
    return result


def _build_column(result: BuildResult, column: lay.Column, namespace: str) -> None:
    transform = cmds.createNode("transform", name=_safe(column.name) + "_labels", parent=result.group,
                                skipSelect=True)
    shape = cmds.createNode(NODE_TYPE, name=_safe(column.name) + "_labelsShape", parent=transform,
                            skipSelect=True)
    _tag(transform, COLUMN_TAG, column.name)
    values = {"displayMode": lay.MODES.index(column.mode), "corner": lay.CORNERS.index(column.corner),
              "screenX": column.x, "screenY": column.y, "fontSize": column.size,
              "lineSpacing": column.spacing, "headerScale": column.header_scale,
              "headerOpacity": column.header_opacity, "scaleMode": lay.SCALE_MODES.index(column.scale_mode),
              "scale": column.scale, "referenceHeight": column.reference_height,
              "distanceScale": column.distance_scale}
    for attribute, value in values.items():
        cmds.setAttr(f"{shape}.{attribute}", value)
    for attribute, value in (("fontName", column.font), ("headerText", column.header),
                             ("camera", lay.with_namespace(column.camera, namespace) if column.camera else "")):
        cmds.setAttr(f"{shape}.{attribute}", value, type="string")
    cmds.setAttr(f"{shape}.headerColor", *column.header_color, type="double3")
    if column.anchor:
        anchor = lay.with_namespace(column.anchor, namespace)
        if cmds.objExists(anchor) and cmds.attributeQuery("worldMatrix", node=anchor, exists=True):
            cmds.connectAttr(f"{anchor}.worldMatrix[0]", f"{transform}.offsetParentMatrix")
        else:
            result.missing.append(anchor)
    for index, line in enumerate(column.lines):
        _build_line(result, shape, index, line, namespace)


def _build_line(result: BuildResult, shape: str, index: int, line: lay.Line, namespace: str) -> None:
    element = f"{shape}.line[{index}]"
    cmds.setAttr(f"{element}.label", line.label, type="string")
    cmds.setAttr(f"{element}.color", *line.color, type="double3")
    cmds.setAttr(f"{element}.opacity", line.opacity)
    cmds.setAttr(f"{element}.show", line.show)
    cmds.setAttr(f"{element}.decimals", line.decimals)
    cmds.setAttr(f"{element}.blend", lay.BLENDS.index(line.blend))
    if line.color_keys:
        flat = [number for value, color in line.color_keys for number in (value, *color)]
        cmds.setAttr(f"{element}.colorKeys", flat, type="doubleArray")
    if line.opacity_keys:
        flat = [number for key in line.opacity_keys for number in key]
        cmds.setAttr(f"{element}.opacityKeys", flat, type="doubleArray")
    if not line.attribute:
        return
    source = lay.with_namespace(line.attribute, namespace)
    cmds.setAttr(f"{element}.attribute", source, type="string")  # kept even when it isn't found
    try:
        exists = cmds.objExists(source)
    except RuntimeError:
        exists = False
    if not exists:
        result.missing.append(source)
        return
    cmds.connectAttr(source, f"{element}.value", force=True)


# --- reading back -------------------------------------------------------------------------------

def capture(group: str) -> lay.Layout:
    """The layout a group of built labels holds now — with what was changed on its nodes by hand
    since it was built. Attribute paths come back without the namespace it was built for."""
    name = _read_tag(group, TAG)
    if name is None:
        raise ValueError(f"{group} is no group of MSL labels.")
    namespace = _read_tag(group, NAMESPACE_TAG) or ""
    columns = []
    for transform in cmds.listRelatives(group, children=True, type="transform", fullPath=True) or []:
        shapes = cmds.listRelatives(transform, shapes=True, type=NODE_TYPE, fullPath=True) or []
        if shapes:
            columns.append(_capture_column(transform, shapes[0], namespace))
    return lay.Layout(name=name, namespace=namespace, columns=columns)


def _get(plug: str):
    return cmds.getAttr(plug)


def _color(plug: str) -> lay.Color:
    return tuple(float(part) for part in cmds.getAttr(plug)[0])


def _source(plug: str) -> str:
    sources = cmds.listConnections(plug, source=True, destination=False, plugs=True, skipConversionNodes=True)
    return sources[0] if sources else ""


def _capture_column(transform: str, shape: str, namespace: str) -> lay.Column:
    anchor = _source(f"{transform}.offsetParentMatrix")
    camera = _get(f"{shape}.camera") or ""
    column = lay.Column(
        name=_read_tag(transform, COLUMN_TAG) or transform.rsplit("|", 1)[-1],
        mode=lay.MODES[_get(f"{shape}.displayMode")], corner=lay.CORNERS[_get(f"{shape}.corner")],
        x=_get(f"{shape}.screenX"), y=_get(f"{shape}.screenY"),
        anchor=lay.without_namespace(anchor.split(".", 1)[0], namespace) if anchor else "",
        font=_get(f"{shape}.fontName") or "Consolas", size=_get(f"{shape}.fontSize"),
        spacing=_get(f"{shape}.lineSpacing"), header=_get(f"{shape}.headerText") or "",
        header_color=_color(f"{shape}.headerColor"), header_scale=_get(f"{shape}.headerScale"),
        header_opacity=_get(f"{shape}.headerOpacity"),
        scale_mode=lay.SCALE_MODES[_get(f"{shape}.scaleMode")], scale=_get(f"{shape}.scale"),
        reference_height=_get(f"{shape}.referenceHeight"), distance_scale=_get(f"{shape}.distanceScale"),
        camera=lay.without_namespace(camera, namespace) if camera else "")
    for index in cmds.getAttr(f"{shape}.line", multiIndices=True) or []:
        column.lines.append(_capture_line(f"{shape}.line[{index}]", namespace))
    return column


def _keys(plug: str, width: int) -> list:
    values = list(cmds.getAttr(plug) or [])
    keys = []
    for at in range(0, len(values) - width + 1, width):
        rest = values[at + 1:at + width]
        keys.append((float(values[at]), tuple(float(part) for part in rest) if width > 2 else float(rest[0])))
    return sorted(keys, key=lambda key: key[0])


def _capture_line(element: str, namespace: str) -> lay.Line:
    # what it is connected to; else what it was meant to show (not found when it was built)
    source = _source(f"{element}.value") or _get(f"{element}.attribute") or ""
    return lay.Line(attribute=lay.without_namespace(source, namespace) if source else "",
                    label=_get(f"{element}.label") or "", color=_color(f"{element}.color"),
                    opacity=_get(f"{element}.opacity"), show=bool(_get(f"{element}.show")),
                    decimals=_get(f"{element}.decimals"), color_keys=_keys(f"{element}.colorKeys", 4),
                    opacity_keys=_keys(f"{element}.opacityKeys", 2),
                    blend=lay.BLENDS[_get(f"{element}.blend")])


# --- what the window asks -----------------------------------------------------------------------

def selected_channels() -> list[str]:
    """"node.attribute" of every channel picked in the Channel Box, for each selected object —
    the order Maya lists them in (the objects in the order picked)."""
    objects = cmds.ls(orderedSelection=True, objectsOnly=True) or []
    names = []
    for box_flag in ("selectedMainAttributes", "selectedShapeAttributes", "selectedHistoryAttributes",
                     "selectedOutputAttributes"):
        names += cmds.channelBox("mainChannelBox", query=True, **{box_flag: True}) or []
    found = []
    for node in objects:
        for name in names:
            if cmds.attributeQuery(name, node=node, exists=True):
                long_name = cmds.attributeQuery(name, node=node, longName=True)
                found.append(f"{node}.{long_name}")
    return list(dict.fromkeys(found))


def selected_object() -> str:
    """The first selected object's name ("" = nothing selected)."""
    objects = cmds.ls(orderedSelection=True, objectsOnly=True) or []
    return objects[0] if objects else ""


def value_text(path: str, decimals: int = -1) -> str:
    """What a line shows for `path` now, roughly as the node draws it ("-" = no such attribute)."""
    try:
        if not path or not cmds.objExists(path):
            return "-"
        value = cmds.getAttr(path, asString=True) if _is_enum(path) else cmds.getAttr(path)
    except (RuntimeError, ValueError):
        return "-"
    return _text(value, decimals)


def value_number(path: str) -> float | None:
    """`path`'s value as one number (an enum's index, a switch 0 / 1); None = none / not a number."""
    try:
        if not path or not cmds.objExists(path):
            return None
        value = cmds.getAttr(path)
    except (RuntimeError, ValueError):
        return None
    if isinstance(value, bool):
        return float(value)
    return float(value) if isinstance(value, (int, float)) else None


def value_range(path: str) -> tuple[float, float] | None:
    """The attribute's own minimum and maximum, when it has both (a 0..1 switch, an enum: 0..last)."""
    try:
        node, attribute = path.split(".", 1)
        if _is_enum(path):
            fields = cmds.attributeQuery(attribute, node=node, listEnum=True)[0].split(":")
            return 0.0, float(max(1, len(fields) - 1))
        if cmds.attributeQuery(attribute, node=node, minExists=True) and \
                cmds.attributeQuery(attribute, node=node, maxExists=True):
            low = cmds.attributeQuery(attribute, node=node, minimum=True)[0]
            high = cmds.attributeQuery(attribute, node=node, maximum=True)[0]
            if high > low:
                return float(low), float(high)
    except (RuntimeError, ValueError, IndexError, TypeError):
        pass
    return None


def _is_enum(path: str) -> bool:
    try:
        return cmds.getAttr(path, type=True) == "enum"
    except (RuntimeError, ValueError):
        return False


def _text(value, decimals: int) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (list, tuple)):
        parts = value[0] if len(value) == 1 and isinstance(value[0], (list, tuple)) else value
        return "(" + ", ".join(_text(part, decimals) for part in parts) + ")"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if decimals >= 0:
            text = "%.*f" % (decimals, value)
            return text[1:] if text.startswith("-") and float(text) == 0.0 else text
        text = ("%.2f" % value).rstrip("0").rstrip(".")
        return "0" if text in ("-0", "") else text
    return str(value)


def remove(group: str) -> None:
    """Deletes a group of built labels (one undo step). Nothing it showed is touched."""
    if _read_tag(group, TAG) is None:
        raise ValueError(f"{group} is no group of MSL labels.")
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        cmds.delete(group)
    finally:
        cmds.undoInfo(closeChunk=True)
