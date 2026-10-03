# maya_module/plug-ins/msl_shot_mask.py
"""Maya plug-in: `mslShotMask`, a node that draws a shot mask over the viewport —
bars along the top and bottom of the frame and up to six lines of text on them
(scene, camera, frame counter, ...). Because the viewport draws it, the animator
sees it while working, and a playblast simply contains it.

Self-contained on purpose: it imports nothing of msl_tools and no Qt, so Maya can
load it by path whatever else is (or isn't) installed. Viewport 2.0 only.

The text of a slot may hold tokens, filled in on every draw:
    {scene} {camera} {frame} {counter} {focal_length} {fps} {date} {user}
`{counter}` is the frame padded to `counterPadding` digits; `{frame}` is plain.

The node is driven by tools/maya/playblast/mask.py, which creates it, marks it
"do not write" (it never lands in a saved scene) and sets its attributes.
"""
import getpass
import os
import time

import maya.OpenMaya as om1  # API 1.0: the scene's file name (MFileIO has no API 2.0 form)
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.api.OpenMayaRender as omr
import maya.api.OpenMayaUI as omui


def maya_useNewAPI():
    """Tells Maya this plug-in uses the Python API 2.0."""


NODE_NAME = "mslShotMask"
NODE_ID = om.MTypeId(0x0007F7A1)  # from the range for plug-ins that stay in-house
DRAW_CLASSIFICATION = "drawdb/geometry/mslShotMask"
DRAW_REGISTRANT = "mslShotMaskPlugin"

SLOTS = ("topLeft", "topCenter", "topRight", "bottomLeft", "bottomCenter", "bottomRight")
BAR_PART = 0.075    # a bar's height as a part of the frame's height, at barScale 1
TEXT_PART = 0.030   # the text's height as a part of the frame's height, at textScale 1
PADDING_PART = 0.012  # room between the frame's side and the text
ERROR_VARIABLE = "MSL_SHOT_MASK_ERROR"  # environment variable of this process: the last failed draw's traceback
STATE_VARIABLE = "MSL_SHOT_MASK_STATE"  # ... and how far drawing got: "prepared", "drawn"


def _failed():
    """Keeps the traceback of a failed draw, and tells the user once (a draw runs many times a second)."""
    import traceback
    first = not os.environ.get(ERROR_VARIABLE)
    text = traceback.format_exc()
    os.environ[ERROR_VARIABLE] = text  # Maya swallows a draw's exception: kept where mask.py can read it
    if first:
        om.MGlobal.displayError("MSL shot mask: drawing failed. " + text.strip().splitlines()[-1])


class ShotMaskNode(omui.MPxLocatorNode):
    """The node: only attributes — everything is drawn by ShotMaskDrawOverride."""

    texts = {}
    camera = None
    aspect = None
    text_scale = None
    bar_scale = None
    bar_opacity = None
    top_bar = None
    bottom_bar = None
    text_color = None
    bar_color = None
    counter_padding = None
    font_name = None

    @staticmethod
    def creator():
        return ShotMaskNode()

    @staticmethod
    def initialize():
        # short names carry a prefix: a locator already has "bb" (bounding box), "tb", ... of its own,
        # and a clash makes addAttribute fail without a word
        typed, numeric = om.MFnTypedAttribute(), om.MFnNumericAttribute()

        def string(long_name, short_name, default=""):
            attribute = typed.create(long_name, short_name, om.MFnData.kString, om.MFnStringData().create(default))
            om.MPxNode.addAttribute(attribute)
            return attribute

        def number(long_name, short_name, kind, default, low=None, high=None):
            attribute = numeric.create(long_name, short_name, kind, default)
            if low is not None:
                numeric.setMin(low)
            if high is not None:
                numeric.setMax(high)
            om.MPxNode.addAttribute(attribute)
            return attribute

        def color(long_name, short_name, default):
            attribute = numeric.createColor(long_name, short_name)
            numeric.default = default
            om.MPxNode.addAttribute(attribute)
            return attribute

        for index, slot in enumerate(SLOTS):
            ShotMaskNode.texts[slot] = string(slot + "Text", "smt%d" % index)
        ShotMaskNode.camera = string("camera", "smcam")  # "" = every perspective camera
        ShotMaskNode.font_name = string("fontName", "smfn", "Consolas")
        ShotMaskNode.aspect = number("aspect", "smasp", om.MFnNumericData.kFloat, 0.0, 0.0)  # 0 = the whole viewport
        ShotMaskNode.text_scale = number("textScale", "smts", om.MFnNumericData.kFloat, 1.0, 0.3, 4.0)
        ShotMaskNode.bar_scale = number("barScale", "smbs", om.MFnNumericData.kFloat, 1.0, 0.3, 4.0)
        ShotMaskNode.bar_opacity = number("barOpacity", "smbo", om.MFnNumericData.kFloat, 1.0, 0.0, 1.0)
        ShotMaskNode.top_bar = number("topBar", "smtb", om.MFnNumericData.kBoolean, True)
        ShotMaskNode.bottom_bar = number("bottomBar", "smbb", om.MFnNumericData.kBoolean, True)
        ShotMaskNode.counter_padding = number("counterPadding", "smcp", om.MFnNumericData.kInt, 4, 1, 8)
        ShotMaskNode.text_color = color("textColor", "smtc", (1.0, 1.0, 1.0))
        ShotMaskNode.bar_color = color("barColor", "smbc", (0.0, 0.0, 0.0))

    def excludeAsLocator(self):
        return False  # stays visible when Show > Locators is off: it is no rigging locator


class _MaskData(om.MUserData):
    """What one draw needs, read from the node in prepareForDraw."""

    def __init__(self):
        super().__init__(False)  # not deleted by Maya after the draw: reused
        self.visible = False
        self.rect = (0.0, 0.0, 0.0, 0.0)  # x, y, width, height of the frame inside the viewport
        self.texts = {}
        self.font_name = "Consolas"
        self.font_size = 12
        self.bar_height = 0.0
        self.padding = 0.0
        self.top_bar = True
        self.bottom_bar = True
        self.text_color = om.MColor((1.0, 1.0, 1.0, 1.0))
        self.bar_color = om.MColor((0.0, 0.0, 0.0, 1.0))


class ShotMaskDrawOverride(omr.MPxDrawOverride):
    """Draws the node: 2D bars and text over the viewport."""

    _user = None

    @staticmethod
    def creator(obj):
        return ShotMaskDrawOverride(obj)

    def __init__(self, obj):
        super().__init__(obj, None, True)  # always dirty: the frame number changes without the node changing

    def supportedDrawAPIs(self):
        return omr.MRenderer.kAllDevices

    def hasUIDrawables(self):
        return True

    def isBounded(self, obj_path, camera_path):
        return False  # never culled: it isn't anywhere in the scene's space

    def prepareForDraw(self, obj_path, camera_path, frame_context, old_data):
        data = old_data if isinstance(old_data, _MaskData) else _MaskData()
        try:
            os.environ.setdefault(STATE_VARIABLE, "prepared")
            return self._prepare(data, obj_path, camera_path, frame_context)
        except Exception:
            _failed()
            data.visible = False
            return data

    def _prepare(self, data, obj_path, camera_path, frame_context):
        node = om.MFnDependencyNode(obj_path.node())

        def plug(attribute):
            return om.MPlug(obj_path.node(), attribute)

        camera = om.MFnCamera(camera_path)
        camera_name = om.MFnDagNode(camera_path.transform()).name()
        wanted = plug(ShotMaskNode.camera).asString()
        data.visible = not camera.isOrtho() and (not wanted or wanted.split("|")[-1] == camera_name)
        if not data.visible:
            return data

        _x, _y, view_width, view_height = frame_context.getViewportDimensions()
        aspect = plug(ShotMaskNode.aspect).asFloat()
        width, height = float(view_width), float(view_height)
        if aspect > 0.0 and view_height > 0:
            # the frame a playblast of this shape takes: as wide or as high as the viewport lets it
            width = min(float(view_width), view_height * aspect)
            height = width / aspect
            overscan = camera.overscan if camera.overscan > 0.0 else 1.0
            width, height = width / overscan, height / overscan
        data.rect = ((view_width - width) / 2.0, (view_height - height) / 2.0, width, height)
        data.bar_height = height * BAR_PART * plug(ShotMaskNode.bar_scale).asFloat()
        data.font_size = max(6, int(round(height * TEXT_PART * plug(ShotMaskNode.text_scale).asFloat())))
        data.padding = height * PADDING_PART
        data.top_bar = plug(ShotMaskNode.top_bar).asBool()
        data.bottom_bar = plug(ShotMaskNode.bottom_bar).asBool()
        data.font_name = plug(ShotMaskNode.font_name).asString() or "Consolas"
        text = plug(ShotMaskNode.text_color)
        data.text_color = om.MColor((text.child(0).asFloat(), text.child(1).asFloat(), text.child(2).asFloat(), 1.0))
        bar = plug(ShotMaskNode.bar_color)
        data.bar_color = om.MColor((bar.child(0).asFloat(), bar.child(1).asFloat(), bar.child(2).asFloat(),
                                    plug(ShotMaskNode.bar_opacity).asFloat()))

        frame = int(round(oma.MAnimControl.currentTime().value))
        padding = plug(ShotMaskNode.counter_padding).asInt()
        scene = os.path.splitext(os.path.basename(om1.MFileIO.currentFile()))[0] or "untitled"
        values = {"scene": scene, "camera": camera_name, "frame": str(frame),
                  "counter": ("-" if frame < 0 else "") + str(abs(frame)).zfill(padding),
                  "focal_length": "%.0f mm" % camera.focalLength, "fps": "%g" % self._fps(),
                  "date": time.strftime("%Y-%m-%d"), "user": self._user_name()}
        data.texts = {}
        for slot, attribute in ShotMaskNode.texts.items():
            text = plug(attribute).asString()
            for token, value in values.items():
                text = text.replace("{" + token + "}", value)
            data.texts[slot] = text
        return data

    @staticmethod
    def _fps():
        return om.MTime(1.0, om.MTime.kSeconds).asUnits(om.MTime.uiUnit())

    @classmethod
    def _user_name(cls):
        if cls._user is None:
            try:
                cls._user = getpass.getuser()
            except Exception:
                cls._user = ""
        return cls._user

    def addUIDrawables(self, obj_path, draw_manager, frame_context, data):
        if not isinstance(data, _MaskData) or not data.visible:
            return
        try:
            self._draw(draw_manager, data)
            os.environ[STATE_VARIABLE] = "drawn"
        except Exception:
            _failed()

    @staticmethod
    def _draw(draw_manager, data):
        x, y, width, height = data.rect
        if width <= 0.0 or height <= 0.0:
            return
        bar = data.bar_height
        draw_manager.beginDrawable()
        draw_manager.setFontName(data.font_name)
        draw_manager.setFontSize(data.font_size)
        if data.bar_color.a > 0.0:
            # A bar is the BACKGROUND BOX of an empty text: a rect2d is drawn over every text of the
            # frame, whatever the order or the depth priority — on solid bars the text was invisible.
            size = [int(round(width)), int(round(bar))]
            draw_manager.setColor(data.bar_color)
            if data.top_bar:
                draw_manager.text2d(om.MPoint(x, y + height - bar), " ", omr.MUIDrawManager.kLeft, size, data.bar_color)
            if data.bottom_bar:
                draw_manager.text2d(om.MPoint(x, y), " ", omr.MUIDrawManager.kLeft, size, data.bar_color)
        draw_manager.setFontName(data.font_name)
        draw_manager.setFontSize(data.font_size)
        draw_manager.setColor(data.text_color)
        # text2d places the BASELINE: a little under the bar's middle puts the letters in the middle
        top_line = y + height - bar / 2.0 - data.font_size * 0.36
        bottom_line = y + bar / 2.0 - data.font_size * 0.36
        columns = (("Left", x + data.padding, omr.MUIDrawManager.kLeft),
                   ("Center", x + width / 2.0, omr.MUIDrawManager.kCenter),
                   ("Right", x + width - data.padding, omr.MUIDrawManager.kRight))
        for row, line in (("top", top_line), ("bottom", bottom_line)):
            for column, at, alignment in columns:
                text = data.texts.get(row + column, "")
                if text:
                    draw_manager.text2d(om.MPoint(at, line), text, alignment)
        draw_manager.endDrawable()


def initializePlugin(plugin):
    plugin_fn = om.MFnPlugin(plugin, "MSL Tools", "1.0", "Any")
    plugin_fn.registerNode(NODE_NAME, NODE_ID, ShotMaskNode.creator, ShotMaskNode.initialize,
                           om.MPxNode.kLocatorNode, DRAW_CLASSIFICATION)
    omr.MDrawRegistry.registerDrawOverrideCreator(DRAW_CLASSIFICATION, DRAW_REGISTRANT, ShotMaskDrawOverride.creator)


def uninitializePlugin(plugin):
    plugin_fn = om.MFnPlugin(plugin)
    omr.MDrawRegistry.deregisterDrawOverrideCreator(DRAW_CLASSIFICATION, DRAW_REGISTRANT)
    plugin_fn.deregisterNode(NODE_ID)
