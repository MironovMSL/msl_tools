# tools/maya/labels/layout.py
"""A layout of labels as plain data (no Qt, no Maya).

    Layout   a name, the namespace it was last built for, its columns
    Column   one mslLabels node: where it stands (HUD corner + offset, or 3D at an `anchor`
             object), how it looks (font, size, header), how it is sized, its lines
    Line     one "label  value" line: the attribute shown ("arm_ctrl.ikFk", WITHOUT a namespace),
             its color and opacity, or keys that set them by the value

Attribute paths are kept without the rig's namespace, so one layout fits every copy of a rig:
`with_namespace()` puts one in when the layout is built, `without_namespace()` takes it out when a
layout is read back from the scene.

A layout goes to and from JSON as a dict (`to_dict` / `from_dict`); reading is forgiving — a key
that is missing takes its default, one of the wrong kind too, an unknown key is ignored — so a
layout saved by an older or newer version still reads.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

FORMAT = "msl_labels"
VERSION = 1

HUD, SPACE = "hud", "3d"
MODES = (SPACE, HUD)  # in the node's order: displayMode 0 = 3D, 1 = HUD
TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT = "top_left", "top_right", "bottom_left", "bottom_right"
CORNERS = (TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT)  # the node's `corner` order
MANUAL, AUTO = "manual", "auto"
SCALE_MODES = (MANUAL, AUTO)
SMOOTH, STEPS = "smooth", "steps"
BLENDS = (SMOOTH, STEPS)
OTHER_CORNER = {TOP_LEFT: TOP_RIGHT, TOP_RIGHT: TOP_LEFT, BOTTOM_LEFT: BOTTOM_RIGHT, BOTTOM_RIGHT: BOTTOM_LEFT}

Color = tuple[float, float, float]


@dataclass
class Line:
    attribute: str = ""            # "node.attribute", without the rig's namespace; "" = nothing shown yet
    label: str = ""                # "" = the attribute's own name
    color: Color = (1.0, 1.0, 1.0)
    opacity: float = 1.0
    show: bool = True
    decimals: int = -1             # -1 = at most two, trailing zeros dropped
    color_keys: list[tuple[float, Color]] = field(default_factory=list)   # (value, color)
    opacity_keys: list[tuple[float, float]] = field(default_factory=list)  # (value, opacity)
    blend: str = SMOOTH

    @property
    def node(self) -> str:
        """The node part of `attribute` ("arm_ctrl" of "arm_ctrl.ikFk")."""
        return self.attribute.split(".", 1)[0]


@dataclass
class Column:
    name: str = "labels"
    mode: str = HUD
    corner: str = TOP_LEFT
    x: int = 40                    # HUD: pixels in from the corner; 3D: moved on the screen by this
    y: int = 40
    anchor: str = ""               # 3D: the object it stands at, without the rig's namespace
    font: str = "Consolas"
    size: int = 14
    spacing: int = 4
    header: str = ""               # "" = no header
    header_color: Color = (1.0, 0.82, 0.4)
    header_scale: float = 1.15
    header_opacity: float = 1.0
    scale_mode: str = MANUAL
    scale: float = 1.0
    reference_height: int = 1080
    distance_scale: float = 0.0    # 3D: > 0 = smaller with the camera's distance
    camera: str = ""               # "" = every camera
    lines: list[Line] = field(default_factory=list)


@dataclass
class Layout:
    name: str = "labels"
    namespace: str = ""            # the rig's namespace it was last built for; "" = none
    columns: list[Column] = field(default_factory=list)

    def column(self, name: str) -> Column | None:
        return next((column for column in self.columns if column.name == name), None)


# --- namespaces ---------------------------------------------------------------------------------

def _split(path: str) -> tuple[str, str]:
    """"a|b.attr" -> ("a|b", ".attr"); a path without an attribute -> (path, "")."""
    node, dot, attribute = path.partition(".")
    return node, dot + attribute


def with_namespace(path: str, namespace: str) -> str:
    """`path` ("arm_ctrl.ikFk", "|grp|arm_ctrl", "arm_ctrl") with `namespace` in front of every
    name in it: "hero:arm_ctrl.ikFk". An empty namespace changes nothing."""
    namespace = namespace.strip(":")
    if not namespace or not path:
        return path
    node, attribute = _split(path)
    parts = [(namespace + ":" + part) if part else part for part in node.split("|")]
    return "|".join(parts) + attribute


def without_namespace(path: str, namespace: str | None = None) -> str:
    """`path` with `namespace` taken off every name in it ("hero:arm_ctrl.ikFk" -> "arm_ctrl.ikFk");
    None = whatever namespace each name has ("a:b:arm_ctrl" -> "arm_ctrl"). Names in another
    namespace than the one given keep theirs."""
    if not path:
        return path
    node, attribute = _split(path)
    parts = []
    for part in node.split("|"):
        if namespace is None:
            part = part.rsplit(":", 1)[-1]
        else:
            prefix = namespace.strip(":") + ":"
            if prefix != ":" and part.startswith(prefix):
                part = part[len(prefix):]
        parts.append(part)
    return "|".join(parts) + attribute


# --- mirroring ----------------------------------------------------------------------------------

def mirror_line(line: Line, rename: Callable[[str], str]) -> Line:
    """A copy of `line` for the other side: its attribute's node renamed by `rename` (Rename's
    `rules.mirror`: lf_arm_ctrl -> rt_arm_ctrl), a label that names a side renamed too."""
    other = copy.deepcopy(line)
    if line.attribute:
        node, attribute = _split(line.attribute)
        other.attribute = "|".join(rename(part) if part else part for part in node.split("|")) + attribute
    if line.label:
        other.label = rename(line.label)
    return other


def mirror_column(column: Column, rename: Callable[[str], str], flip_corner: bool = True) -> Column:
    """A copy of `column` for the other side: its lines mirrored, its name, header and anchor
    renamed, and (HUD, `flip_corner`) moved to the other side of the screen."""
    other = copy.deepcopy(column)
    other.name = rename(column.name)
    other.header = rename(column.header) if column.header else ""
    other.anchor = rename(column.anchor) if column.anchor else ""
    other.lines = [mirror_line(line, rename) for line in column.lines]
    if flip_corner and column.mode == HUD:
        other.corner = OTHER_CORNER.get(column.corner, column.corner)
    return other


# --- checks -------------------------------------------------------------------------------------

def problems(layout: Layout) -> list[str]:
    """What would make the layout build wrong, one line each (an empty list = nothing)."""
    found = []
    seen = set()
    for column in layout.columns:
        if column.name in seen:
            found.append(f"Two columns are called “{column.name}”.")
        seen.add(column.name)
        if column.mode == SPACE and not column.anchor:
            found.append(f"“{column.name}” stands in the scene (3D) but at no object.")
        if not column.lines and not column.header:
            found.append(f"“{column.name}” shows nothing: no header, no lines.")
        empty = sum(1 for line in column.lines if not line.attribute)
        if empty:
            found.append(f"“{column.name}”: {empty} line(s) show no attribute.")
    return found


# --- to and from plain data ---------------------------------------------------------------------

def _number(value: Any, default: float, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _whole(value: Any, default: int, low: int | None = None, high: int | None = None) -> int:
    return int(round(_number(value, default, low, high)))


def _text(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    return value if value in choices else default


def _color(value: Any, default: Color) -> Color:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(_number(part, fallback, 0.0, 1.0) for part, fallback in zip(value, default))
    return default


def _color_keys(value: Any) -> list[tuple[float, Color]]:
    keys = []
    for key in value if isinstance(value, list) else []:
        if (isinstance(key, (list, tuple)) and len(key) == 2
                and isinstance(key[0], (int, float)) and not isinstance(key[0], bool)
                and isinstance(key[1], (list, tuple)) and len(key[1]) == 3):
            keys.append((float(key[0]), _color(key[1], (1.0, 1.0, 1.0))))
    return sorted(keys, key=lambda key: key[0])


def _opacity_keys(value: Any) -> list[tuple[float, float]]:
    keys = []
    for key in value if isinstance(value, list) else []:
        if (isinstance(key, (list, tuple)) and len(key) == 2
                and all(isinstance(part, (int, float)) and not isinstance(part, bool) for part in key)):
            keys.append((float(key[0]), min(1.0, max(0.0, float(key[1])))))
    return sorted(keys, key=lambda key: key[0])


def line_to_dict(line: Line) -> dict[str, Any]:
    return {"attribute": line.attribute, "label": line.label, "color": list(line.color),
            "opacity": line.opacity, "show": line.show, "decimals": line.decimals,
            "color_keys": [[value, list(color)] for value, color in line.color_keys],
            "opacity_keys": [[value, opacity] for value, opacity in line.opacity_keys],
            "blend": line.blend}


def line_from_dict(data: Any) -> Line:
    data = data if isinstance(data, dict) else {}
    default = Line()
    return Line(attribute=_text(data.get("attribute")), label=_text(data.get("label")),
                color=_color(data.get("color"), default.color),
                opacity=_number(data.get("opacity"), default.opacity, 0.0, 1.0),
                show=data.get("show") if isinstance(data.get("show"), bool) else default.show,
                decimals=_whole(data.get("decimals"), default.decimals, -1, 6),
                color_keys=_color_keys(data.get("color_keys")),
                opacity_keys=_opacity_keys(data.get("opacity_keys")),
                blend=_choice(data.get("blend"), BLENDS, default.blend))


_COLUMN_FIELDS = ("name", "mode", "corner", "x", "y", "anchor", "font", "size", "spacing", "header",
                  "header_color", "header_scale", "header_opacity", "scale_mode", "scale",
                  "reference_height", "distance_scale", "camera")


def column_to_dict(column: Column) -> dict[str, Any]:
    data = {name: getattr(column, name) for name in _COLUMN_FIELDS}
    data["header_color"] = list(column.header_color)
    data["lines"] = [line_to_dict(line) for line in column.lines]
    return data


def column_from_dict(data: Any) -> Column:
    data = data if isinstance(data, dict) else {}
    default = Column()
    lines = data.get("lines")
    return Column(name=_text(data.get("name"), default.name) or default.name,
                  mode=_choice(data.get("mode"), MODES, default.mode),
                  corner=_choice(data.get("corner"), CORNERS, default.corner),
                  x=_whole(data.get("x"), default.x), y=_whole(data.get("y"), default.y),
                  anchor=_text(data.get("anchor")),
                  font=_text(data.get("font"), default.font) or default.font,
                  size=_whole(data.get("size"), default.size, 4, 96),
                  spacing=_whole(data.get("spacing"), default.spacing, 0, 96),
                  header=_text(data.get("header")),
                  header_color=_color(data.get("header_color"), default.header_color),
                  header_scale=_number(data.get("header_scale"), default.header_scale, 0.3, 4.0),
                  header_opacity=_number(data.get("header_opacity"), default.header_opacity, 0.0, 1.0),
                  scale_mode=_choice(data.get("scale_mode"), SCALE_MODES, default.scale_mode),
                  scale=_number(data.get("scale"), default.scale, 0.05, 20.0),
                  reference_height=_whole(data.get("reference_height"), default.reference_height, 100),
                  distance_scale=_number(data.get("distance_scale"), default.distance_scale, 0.0),
                  camera=_text(data.get("camera")),
                  lines=[line_from_dict(line) for line in lines] if isinstance(lines, list) else [])


def to_dict(layout: Layout) -> dict[str, Any]:
    return {"format": FORMAT, "version": VERSION, "name": layout.name, "namespace": layout.namespace,
            "columns": [column_to_dict(column) for column in layout.columns]}


def from_dict(data: Any) -> Layout:
    data = data if isinstance(data, dict) else {}
    columns = data.get("columns")
    return Layout(name=_text(data.get("name"), "labels") or "labels",
                  namespace=_text(data.get("namespace")).strip(":"),
                  columns=[column_from_dict(column) for column in columns] if isinstance(columns, list) else [])


def is_layout(data: Any) -> bool:
    """Whether `data` (a JSON object read from a file or the clipboard) is a layout of ours."""
    return isinstance(data, dict) and data.get("format") == FORMAT


# --- files --------------------------------------------------------------------------------------

def save(path: str | Path, layout: Layout) -> None:
    """Writes the layout as JSON (atomically: a failed write leaves the old file whole)."""
    from msl_tools.msl.core.fs.safe_json import write_json_atomic
    write_json_atomic(path, to_dict(layout))


def load(path: str | Path) -> Layout:
    """Reads a layout file. Raises ValueError when the file is no layout of ours; a file that
    isn't JSON at all is NOT moved aside (it isn't ours)."""
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{Path(path).name} can't be read as a labels layout: {error}") from error
    if not is_layout(data):
        raise ValueError(f"{Path(path).name} is no labels layout.")
    return from_dict(data)
