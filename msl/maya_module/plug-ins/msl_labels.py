# maya_module/plug-ins/msl_labels.py
"""Maya plug-in: `mslLabels`, a node that shows attribute values in the viewport, live —
a column of lines "label  value" with an optional header, either fixed on the screen
(HUD) or standing next to the node in the scene (3D: it follows the node, the text
always faces the camera). Because the viewport draws it, the values are seen while
animating, and a playblast simply contains them.

Self-contained on purpose: it imports nothing of msl_tools and no Qt, so Maya can
load it by name through the Maya module whatever else is installed. Viewport 2.0 only.

Each element of the `line` array is one line:
    line[n].value    connect any attribute into it ("ctrl.ikFk" -> "node.line[0].value");
                     the value is read from the CONNECTED attribute, so an enum shows its
                     field's name, an angle / a length / a time the scene's units, a switch
                     on / off, a vector "(x, y, z)", a string as it is
    line[n].label    the text before the value; empty = the connected attribute's name
    line[n].color    the line's color
    line[n].opacity  0 = invisible .. 1 = solid
    line[n].show     off = the line is skipped (it keeps its connection)
    line[n].decimals digits after the point; -1 = at most two, trailing zeros dropped
    line[n].colorKeys    a gradient by the VALUE: [value, r, g, b,  value, r, g, b, ...] —
                         at least one key = the line's color comes from them, not `color`
    line[n].opacityKeys  the same for opacity: [value, opacity, value, opacity, ...]
    line[n].blend        between two keys: smooth (blended) / steps (the key at or below the
                         value holds until the next one — "red from 1.2 on")
Keys are in the units the line shows (degrees, the scene's length unit, an enum's index, a
switch 0 / 1), in any order; below the first key the first holds, above the last the last.
A value that is no single number (a vector, a string) keeps `color` / `opacity`.
Lines are drawn in the order of their indices. Labels are padded to the longest one,
so with a fixed-width font (Consolas, the default) the values form a column.

The column's place: `displayMode` HUD = `screenX` / `screenY` pixels in from the corner
`corner` names (top left / top right / bottom left / bottom right); 3D = at the node's
own position in the scene, moved by `screenX` / `screenY` pixels on the screen (nothing
is drawn while the node is behind the camera).

Size: `fontSize` is the height of the letters' box in pixels, times `scale`, under one of two
rules (`scaleMode`) — and the same rule moves `screenX` / `screenY` (without `scale`):
  Manual = screen pixels as big as Maya's own interface: times Maya's interface scale, so a
           150 % screen shows them 1.5 times as big, like Maya's menus. For working.
  Auto   = a part of the picture: times the viewport's height / `referenceHeight`, whatever
           the screen — a playblast of 960 x 540 or 3840 x 2160 (Maya hands the draw the
           playblast's size) and every machine get the same picture. For playblasts.
Maya itself scales the font by its interface scale (see UI_SCALE); the node takes that out
again, so both rules mean what they say. `lineSpacing` is the room between lines, scaled like
the text. The top of the capitals lies `screenY` under the viewport's top (a top corner).
In 3D, `distanceScale` > 0 makes the text smaller with the camera's distance (perspective).

`camera` = the name of the only camera that shows the labels; "" = every camera.

Text is drawn as ASCII: any other character shows as "?" (text2d garbles it).

A failed draw keeps its traceback in the environment variable MSL_LABELS_ERROR (Maya
swallows a draw's exceptions) and says so in the Script Editor once.
"""
import os

import maya.api.OpenMaya as om
import maya.api.OpenMayaRender as omr
import maya.api.OpenMayaUI as omui


def maya_useNewAPI():
    """Tells Maya this plug-in uses the Python API 2.0."""


NODE_NAME = "mslLabels"
NODE_ID = om.MTypeId(0x0007F7A2)  # from the range for plug-ins that stay in-house (the shot mask is ...A1)
DRAW_CLASSIFICATION = "drawdb/geometry/mslLabels"
DRAW_REGISTRANT = "mslLabelsPlugin"

MODE_3D, MODE_HUD = 0, 1
TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT = 0, 1, 2, 3
SCALE_MANUAL, SCALE_AUTO = 0, 1
NO_VALUE = "-"          # a line nothing is connected to
UNKNOWN = "?"           # a value that can't be read
# text2d's point is the bottom of the text's box (under the descenders): with it this far under a
# line's top, the top of the capitals lies ON the line's top (measured, Maya 2026: capitals are
# 0.65 of the font size, the descent 0.23)
BASELINE_PART = 0.88
LINE_PART = 1.2         # a line's height, as a part of the font size
MIN_PIXELS = 4.0        # no text smaller than this
DISTANCE_LIMIT = 4.0    # 3D with distanceScale: at most this many times bigger (or smaller)
# Maya's interface scale (Preferences > Interface > scaling), read when the plug-in loads: Maya
# multiplies every font size given to MUIDrawManager by it — in playblasts too (measured, Maya
# 2026 at 150 %: the same 1920 x 1080 playblast got letters 1.46 times as big)
UI_SCALE = [1.0]
ERROR_VARIABLE = "MSL_LABELS_ERROR"  # environment variable of this process: the last failed draw's traceback
STATE_VARIABLE = "MSL_LABELS_STATE"  # ... and how far drawing got: "prepared", "drawn"


def number_text(value, decimals=-1):
    """A number for reading: `decimals` digits, or (-1) at most two with no trailing zeros."""
    if decimals >= 0:
        text = "%.*f" % (decimals, value)
        return text[1:] if text.startswith("-") and float(text) == 0.0 else text
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def plug_text(plug, decimals=-1):
    """The value of `plug` as text, the way the Channel Box would say it."""
    attribute = plug.attribute()
    try:
        if plug.isCompound:
            return "(" + ", ".join(plug_text(plug.child(index), decimals)
                                   for index in range(plug.numChildren())) + ")"
        if attribute.hasFn(om.MFn.kEnumAttribute):
            return om.MFnEnumAttribute(attribute).fieldName(plug.asShort())
        if attribute.hasFn(om.MFn.kUnitAttribute):
            kind = om.MFnUnitAttribute(attribute).unitType()
            if kind == om.MFnUnitAttribute.kAngle:
                # no degree sign: text2d draws a non-ASCII character as a run of garbage (Maya 2026)
                return number_text(plug.asMAngle().asUnits(om.MAngle.uiUnit()), decimals)
            if kind == om.MFnUnitAttribute.kDistance:
                return number_text(plug.asMDistance().asUnits(om.MDistance.uiUnit()), decimals)
            if kind == om.MFnUnitAttribute.kTime:
                return number_text(plug.asMTime().asUnits(om.MTime.uiUnit()), decimals)
            return number_text(plug.asDouble(), decimals)
        if attribute.hasFn(om.MFn.kNumericAttribute):
            kind = om.MFnNumericAttribute(attribute).numericType()
            if kind == om.MFnNumericData.kBoolean:
                return "on" if plug.asBool() else "off"
            if kind in (om.MFnNumericData.kFloat, om.MFnNumericData.kDouble, om.MFnNumericData.kAddr):
                return number_text(plug.asDouble(), decimals)
            return str(plug.asInt())
        if attribute.hasFn(om.MFn.kTypedAttribute):
            if om.MFnTypedAttribute(attribute).attrType() == om.MFnData.kString:
                return plug.asString()
    except Exception:
        return UNKNOWN
    return UNKNOWN


def plug_number(plug):
    """The value of `plug` as one number in the units the line shows it in; None if it is
    no single number (a vector, a string, a message)."""
    attribute = plug.attribute()
    try:
        if plug.isCompound:
            return None
        if attribute.hasFn(om.MFn.kEnumAttribute):
            return float(plug.asShort())
        if attribute.hasFn(om.MFn.kUnitAttribute):
            kind = om.MFnUnitAttribute(attribute).unitType()
            if kind == om.MFnUnitAttribute.kAngle:
                return plug.asMAngle().asUnits(om.MAngle.uiUnit())
            if kind == om.MFnUnitAttribute.kDistance:
                return plug.asMDistance().asUnits(om.MDistance.uiUnit())
            if kind == om.MFnUnitAttribute.kTime:
                return plug.asMTime().asUnits(om.MTime.uiUnit())
            return plug.asDouble()
        if attribute.hasFn(om.MFn.kNumericAttribute):
            kind = om.MFnNumericAttribute(attribute).numericType()
            if kind == om.MFnNumericData.kBoolean:
                return 1.0 if plug.asBool() else 0.0
            if kind in (om.MFnNumericData.kFloat, om.MFnNumericData.kDouble, om.MFnNumericData.kAddr):
                return plug.asDouble()
            return float(plug.asInt())
    except Exception:
        return None
    return None


def parse_keys(values, width):
    """A flat list of numbers -> keys sorted by value: [(value, (part, ...)), ...], each key
    `width` numbers long (the value first); an unfinished last key is dropped."""
    values = list(values)
    keys = [(values[at], tuple(values[at + 1:at + width]))
            for at in range(0, len(values) - width + 1, width)]
    return sorted(keys, key=lambda key: key[0])


def sample(keys, value, steps=False):
    """What the keys give at `value`: blended between the two around it, or (`steps`) the one at
    or below it; the first / last key outside them. None without keys."""
    if not keys:
        return None
    if value <= keys[0][0]:
        return keys[0][1]
    for (low, low_parts), (high, high_parts) in zip(keys, keys[1:]):
        if value < high:
            if steps or high <= low:
                return low_parts
            part = (value - low) / (high - low)
            return tuple(a + (b - a) * part for a, b in zip(low_parts, high_parts))
    return keys[-1][1]


def _keys(list_plug, width):
    """The keys a number-list plug holds ([] when empty)."""
    try:
        data = list_plug.asMObject()
    except RuntimeError:  # never set
        return []
    if data.isNull():
        return []
    return parse_keys(om.MFnDoubleArrayData(data).array(), width)


def _points(pixels):
    """The font size to give MUIDrawManager for letters `pixels` high: Maya scales it by UI_SCALE itself."""
    return max(1, int(round(pixels / UI_SCALE[0])))


def _read_ui_scale():
    try:
        from maya import cmds
        value = float(cmds.mayaDpiSetting(query=True, realScaleValue=True))
        UI_SCALE[0] = value if value > 0.0 else 1.0
    except Exception:  # mayapy and batch Maya have no interface: 1
        UI_SCALE[0] = 1.0


def _drawable(text):
    """`text` as text2d can draw it: a non-ASCII character becomes "?" — given as it is,
    Maya 2026 draws a run of garbage (half the character table) after it."""
    return text.encode("ascii", "replace").decode("ascii")


def _failed():
    """Keeps the traceback of a failed draw, and tells the user once (a draw runs many times a second)."""
    import traceback
    first = not os.environ.get(ERROR_VARIABLE)
    text = traceback.format_exc()
    os.environ[ERROR_VARIABLE] = text  # Maya swallows a draw's exception: kept where a tool can read it
    if first:
        om.MGlobal.displayError("MSL labels: drawing failed. " + text.strip().splitlines()[-1])


class LabelsNode(omui.MPxLocatorNode):
    """The node: only attributes — everything is drawn by LabelsDrawOverride."""

    line = None
    value = None
    label = None
    color = None
    opacity = None
    show = None
    decimals = None
    color_keys = None
    opacity_keys = None
    blend = None
    display_mode = None
    corner = None
    screen_x = None
    screen_y = None
    font_name = None
    font_size = None
    line_spacing = None
    header_text = None
    header_scale = None
    header_color = None
    header_opacity = None
    scale_mode = None
    scale = None
    reference_height = None
    distance_scale = None
    camera = None

    @staticmethod
    def creator():
        return LabelsNode()

    @staticmethod
    def initialize():
        # short names carry a prefix: a locator already has "bb", "tb", ... of its own,
        # and a clash makes addAttribute fail without a word
        typed, numeric, enum = om.MFnTypedAttribute(), om.MFnNumericAttribute(), om.MFnEnumAttribute()
        compound, generic = om.MFnCompoundAttribute(), om.MFnGenericAttribute()

        def string(long_name, short_name, default="", add=True):
            attribute = typed.create(long_name, short_name, om.MFnData.kString, om.MFnStringData().create(default))
            if add:
                om.MPxNode.addAttribute(attribute)
            return attribute

        def number(long_name, short_name, kind, default, low=None, high=None, add=True):
            attribute = numeric.create(long_name, short_name, kind, default)
            if low is not None:
                numeric.setMin(low)
            if high is not None:
                numeric.setMax(high)
            if add:
                om.MPxNode.addAttribute(attribute)
            return attribute

        def color(long_name, short_name, default, add=True):
            attribute = numeric.createColor(long_name, short_name)
            numeric.default = default
            if add:
                om.MPxNode.addAttribute(attribute)
            return attribute

        def choice(long_name, short_name, names, default=0, add=True):
            attribute = enum.create(long_name, short_name, default)
            for index, name in enumerate(names):
                enum.addField(name, index)
            if add:
                om.MPxNode.addAttribute(attribute)
            return attribute

        def number_list(long_name, short_name):
            return typed.create(long_name, short_name, om.MFnData.kDoubleArray,
                                om.MFnDoubleArrayData().create(om.MDoubleArray()))

        # the value: a generic input, so any attribute can be connected into it; its own data
        # is never read — the draw asks the CONNECTED plug (enum names, units)
        value = generic.create("value", "mlv")
        for kind in (om.MFnNumericData.kBoolean, om.MFnNumericData.kByte, om.MFnNumericData.kChar,
                     om.MFnNumericData.kShort, om.MFnNumericData.kInt, om.MFnNumericData.kInt64,
                     om.MFnNumericData.kFloat, om.MFnNumericData.kDouble,
                     om.MFnNumericData.k2Short, om.MFnNumericData.k2Int, om.MFnNumericData.k2Float,
                     om.MFnNumericData.k2Double, om.MFnNumericData.k3Short, om.MFnNumericData.k3Int,
                     om.MFnNumericData.k3Float, om.MFnNumericData.k3Double):
            generic.addNumericType(kind)
        generic.addDataType(om.MFnData.kString)
        generic.storable = False  # nothing of its own to keep: the connection is what matters
        generic.keyable = False
        LabelsNode.value = value
        LabelsNode.label = string("label", "mlla", add=False)
        LabelsNode.color = color("color", "mlco", (1.0, 1.0, 1.0), add=False)
        LabelsNode.opacity = number("opacity", "mlop", om.MFnNumericData.kFloat, 1.0, 0.0, 1.0, add=False)
        LabelsNode.show = number("show", "mlsh", om.MFnNumericData.kBoolean, True, add=False)
        LabelsNode.decimals = number("decimals", "mlde", om.MFnNumericData.kInt, -1, -1, 6, add=False)
        LabelsNode.color_keys = number_list("colorKeys", "mlck")
        LabelsNode.opacity_keys = number_list("opacityKeys", "mlok")
        LabelsNode.blend = choice("blend", "mlbl", ("smooth", "steps"), add=False)
        LabelsNode.line = compound.create("line", "mlln")
        for child in (LabelsNode.value, LabelsNode.label, LabelsNode.color, LabelsNode.opacity,
                      LabelsNode.show, LabelsNode.decimals, LabelsNode.color_keys,
                      LabelsNode.opacity_keys, LabelsNode.blend):
            compound.addChild(child)
        compound.array = True
        compound.usesArrayDataBuilder = True
        om.MPxNode.addAttribute(LabelsNode.line)

        LabelsNode.display_mode = choice("displayMode", "mldm", ("3D", "HUD"), MODE_HUD)
        LabelsNode.corner = choice("corner", "mlcr", ("topLeft", "topRight", "bottomLeft", "bottomRight"))
        LabelsNode.screen_x = number("screenX", "mlsx", om.MFnNumericData.kInt, 40)
        LabelsNode.screen_y = number("screenY", "mlsy", om.MFnNumericData.kInt, 40)
        LabelsNode.font_name = string("fontName", "mlfn", "Consolas")
        LabelsNode.font_size = number("fontSize", "mlfs", om.MFnNumericData.kInt, 14, 4, 96)
        LabelsNode.line_spacing = number("lineSpacing", "mlls", om.MFnNumericData.kInt, 4, 0, 96)
        LabelsNode.header_text = string("headerText", "mlht")  # "" = no header
        LabelsNode.header_scale = number("headerScale", "mlhs", om.MFnNumericData.kFloat, 1.15, 0.3, 4.0)
        LabelsNode.header_color = color("headerColor", "mlhc", (1.0, 0.82, 0.4))
        LabelsNode.header_opacity = number("headerOpacity", "mlho", om.MFnNumericData.kFloat, 1.0, 0.0, 1.0)
        LabelsNode.scale_mode = choice("scaleMode", "mlsm", ("manual", "auto"), SCALE_MANUAL)
        LabelsNode.scale = number("scale", "mlsc", om.MFnNumericData.kFloat, 1.0, 0.05, 20.0)
        LabelsNode.reference_height = number("referenceHeight", "mlrh", om.MFnNumericData.kInt, 1080, 100)
        # 3D only: > 0 = the camera distance at which the text is fontSize; nearer = bigger, farther =
        # smaller (at most DISTANCE_LIMIT either way); 0 = as big wherever it stands
        LabelsNode.distance_scale = number("distanceScale", "mlds", om.MFnNumericData.kFloat, 0.0, 0.0)
        LabelsNode.camera = string("camera", "mlcam")  # "" = every camera

    def excludeAsLocator(self):
        return False  # stays visible when Show > Locators is off: it is no rigging locator


class _LabelsData(om.MUserData):
    """What one draw needs, read from the node in prepareForDraw."""

    def __init__(self):
        super(_LabelsData, self).__init__(False)  # not deleted by Maya after the draw: reused
        self.visible = False
        self.origin = (0.0, 0.0)  # the top-left (or top-right) corner of the column, in viewport pixels
        self.right = False        # the text runs leftwards from the origin (a right corner)
        self.font_name = "Consolas"
        self.font_size = 14
        self.step = 18.0          # from one line's top to the next one's
        self.header = None        # (text, font size, MColor) or None
        self.lines = []           # (text, MColor)


class LabelsDrawOverride(omr.MPxDrawOverride):
    """Draws the node: a column of 2D text over the viewport."""

    @staticmethod
    def creator(obj):
        return LabelsDrawOverride(obj)

    def __init__(self, obj):
        # always dirty: the connected values change without this node being told
        super(LabelsDrawOverride, self).__init__(obj, None, True)

    def supportedDrawAPIs(self):
        return omr.MRenderer.kAllDevices

    def hasUIDrawables(self):
        return True

    def isBounded(self, obj_path, camera_path):
        return False  # never culled: in HUD it isn't anywhere in the scene, in 3D it is only a point

    def prepareForDraw(self, obj_path, camera_path, frame_context, old_data):
        data = old_data if isinstance(old_data, _LabelsData) else _LabelsData()
        try:
            os.environ.setdefault(STATE_VARIABLE, "prepared")
            return self._prepare(data, obj_path, camera_path, frame_context)
        except Exception:
            _failed()
            data.visible = False
            return data

    @staticmethod
    def _prepare(data, obj_path, camera_path, frame_context):
        node = obj_path.node()

        def plug(attribute):
            return om.MPlug(node, attribute)

        def rgba(color_plug, opacity):
            return om.MColor((color_plug.child(0).asFloat(), color_plug.child(1).asFloat(),
                              color_plug.child(2).asFloat(), opacity))

        wanted = plug(LabelsNode.camera).asString()
        camera_name = om.MFnDagNode(camera_path.transform()).name()
        data.visible = not wanted or wanted.split("|")[-1].split(":")[-1] == camera_name.split(":")[-1]
        if not data.visible:
            return data

        _x, _y, view_width, view_height = frame_context.getViewportDimensions()
        three_d = plug(LabelsNode.display_mode).asShort() == MODE_3D
        position = om.MPoint() * obj_path.inclusiveMatrix()
        # `screen`: viewport pixels per "pixel" of the node's own numbers (offsets);
        # `factor`: the same for the text's size (the node's scale on top)
        if plug(LabelsNode.scale_mode).asShort() == SCALE_AUTO:
            screen = float(view_height) / max(1, plug(LabelsNode.reference_height).asInt())
        else:
            screen = UI_SCALE[0]  # as big as Maya's own interface on this screen
        factor = screen * plug(LabelsNode.scale).asFloat()
        distance_scale = plug(LabelsNode.distance_scale).asFloat()
        if three_d and distance_scale > 0.0 and not om.MFnCamera(camera_path).isOrtho():
            eye = om.MPoint() * camera_path.inclusiveMatrix()
            factor *= min(DISTANCE_LIMIT, max(1.0 / DISTANCE_LIMIT,
                                               distance_scale / max(1e-6, eye.distanceTo(position))))
        data.font_name = plug(LabelsNode.font_name).asString() or "Consolas"
        data.font_size = max(MIN_PIXELS, plug(LabelsNode.font_size).asInt() * factor)
        data.step = data.font_size * LINE_PART + plug(LabelsNode.line_spacing).asInt() * factor

        lines = []  # (label, value, MColor)
        array = plug(LabelsNode.line)
        indices = sorted(array.getExistingArrayAttributeIndices())
        for index in indices:
            element = array.elementByLogicalIndex(index)
            if not element.child(LabelsNode.show).asBool():
                continue
            source = element.child(LabelsNode.value).source()
            label = element.child(LabelsNode.label).asString()
            color = rgba(element.child(LabelsNode.color), element.child(LabelsNode.opacity).asFloat())
            if source.isNull:
                text = NO_VALUE
            else:
                text = plug_text(source, element.child(LabelsNode.decimals).asInt())
                if not label:
                    label = source.partialName(useLongNames=True)
                color = LabelsDrawOverride._keyed_color(element, source, color)
            lines.append((label, text, color))
        width = max([len(label) for label, _text, _color in lines] or [0])
        data.lines = [(_drawable((label.ljust(width) + "  " + text) if label else text), color)
                      for label, text, color in lines]
        header = _drawable(plug(LabelsNode.header_text).asString())
        data.header = None
        if header:
            data.header = (header, max(MIN_PIXELS, data.font_size * plug(LabelsNode.header_scale).asFloat()),
                           rgba(plug(LabelsNode.header_color), plug(LabelsNode.header_opacity).asFloat()))
        if not data.lines and data.header is None:
            data.visible = False
            return data

        offset_x = plug(LabelsNode.screen_x).asInt() * screen
        offset_y = plug(LabelsNode.screen_y).asInt() * screen
        if not three_d:
            corner = plug(LabelsNode.corner).asShort()
            data.right = corner in (TOP_RIGHT, BOTTOM_RIGHT)
            x = view_width - offset_x if data.right else offset_x
            if corner in (TOP_LEFT, TOP_RIGHT):
                top = view_height - offset_y
            else:  # the column's BOTTOM is offset_y up from the viewport's bottom
                top = offset_y + LabelsDrawOverride._height(data)
            data.origin = (x, top)
            return data

        # 3D: the node's own position, projected onto the viewport (y up, like the HUD)
        data.right = False
        clip = position * frame_context.getMatrix(omr.MFrameContext.kViewProjMtx)
        if clip.w <= 1e-6:  # behind the camera
            data.visible = False
            return data
        screen_x = (clip.x / clip.w * 0.5 + 0.5) * view_width
        screen_y = (clip.y / clip.w * 0.5 + 0.5) * view_height
        data.origin = (screen_x + offset_x, screen_y + offset_y)
        return data

    @staticmethod
    def _keyed_color(element, source, color):
        """`color` with what the line's keys give at the source's value put in its place."""
        color_keys = _keys(element.child(LabelsNode.color_keys), 4)
        opacity_keys = _keys(element.child(LabelsNode.opacity_keys), 2)
        if not color_keys and not opacity_keys:
            return color
        value = plug_number(source)
        if value is None:
            return color
        steps = element.child(LabelsNode.blend).asShort() == 1
        rgb = sample(color_keys, value, steps) or (color.r, color.g, color.b)
        opacity = sample(opacity_keys, value, steps)
        alpha = min(1.0, max(0.0, opacity[0])) if opacity else color.a
        return om.MColor((rgb[0], rgb[1], rgb[2], alpha))

    @staticmethod
    def _height(data):
        """How tall the column is: the header's line (if any) and every line."""
        height = len(data.lines) * data.step
        if data.header is not None:
            height += data.header[1] * LINE_PART + (data.step - data.font_size * LINE_PART)
        return height

    def addUIDrawables(self, obj_path, draw_manager, frame_context, data):
        if not isinstance(data, _LabelsData) or not data.visible:
            return
        try:
            self._draw(draw_manager, data)
            os.environ[STATE_VARIABLE] = "drawn"
        except Exception:
            _failed()

    @staticmethod
    def _draw(draw_manager, data):
        x, top = data.origin
        alignment = omr.MUIDrawManager.kRight if data.right else omr.MUIDrawManager.kLeft
        draw_manager.beginDrawable()
        draw_manager.setFontName(data.font_name)
        if data.header is not None:
            text, size, color = data.header
            draw_manager.setFontSize(_points(size))
            draw_manager.setColor(color)
            # text2d places the BASELINE
            draw_manager.text2d(om.MPoint(x, top - size * BASELINE_PART), text, alignment)
            top -= size * LINE_PART + (data.step - data.font_size * LINE_PART)
        draw_manager.setFontSize(_points(data.font_size))
        for text, color in data.lines:
            if color.a > 0.0:
                draw_manager.setColor(color)
                draw_manager.text2d(om.MPoint(x, top - data.font_size * BASELINE_PART), text, alignment)
            top -= data.step
        draw_manager.endDrawable()


def initializePlugin(plugin):
    _read_ui_scale()
    plugin_fn = om.MFnPlugin(plugin, "MSL Tools", "1.0", "Any")
    plugin_fn.registerNode(NODE_NAME, NODE_ID, LabelsNode.creator, LabelsNode.initialize,
                           om.MPxNode.kLocatorNode, DRAW_CLASSIFICATION)
    omr.MDrawRegistry.registerDrawOverrideCreator(DRAW_CLASSIFICATION, DRAW_REGISTRANT, LabelsDrawOverride.creator)


def uninitializePlugin(plugin):
    plugin_fn = om.MFnPlugin(plugin)
    omr.MDrawRegistry.deregisterDrawOverrideCreator(DRAW_CLASSIFICATION, DRAW_REGISTRANT)
    plugin_fn.deregisterNode(NODE_ID)
