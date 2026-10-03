# maya_module/plug-ins/msl_shot_mask.py
"""Maya plug-in: `mslShotMask`, a node that draws a shot mask over the viewport —
bars along the top and bottom of the frame and up to six lines of text on them
(scene, camera, frame counter, ...). Because the viewport draws it, the animator
sees it while working, and a playblast simply contains it.

Self-contained on purpose: it imports nothing of msl_tools and no Qt, so Maya can
load it by path whatever else is (or isn't) installed. Viewport 2.0 only.

The text of a slot may hold tokens, filled in on every draw:
    {scene} {project} {camera} {focal_length} {resolution}
    {frame} {counter} {timecode} {start} {end} {range} {frames} {fps}
    {date} {time} {user} {note} {logo}
`{counter}` is the frame padded to `counterPadding` digits; `{frame}` is plain;
`{start}` / `{end}` / `{range}` / `{frames}` are the playback range; `{project}`,
`{note}` and `{resolution}` are what the tool wrote into the node.
A `|` in a slot's text starts a new line: "{scene}|{user}" is two lines, one
under the other, made as small as it takes for all of them to fit the bar.
`{logo}` is no text: the picture named by `logo` is drawn at that slot's place
(as high as LOGO_PART of a bar; text of the same slot moves aside, a centre
slot shows the logo alone).
A slot that shows the frame ({frame}, {counter}, {timecode}) is drawn in the
warning color while the current frame is outside `rangeStart`..`rangeEnd`
(with `warnRange` on) — the frames a playblast would not take.

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
LOGO_PART = 0.72      # the logo's height as a part of a bar's height
LOGO_TOKEN = "{logo}"
NEW_LINE = "|"        # in a slot's text: what follows goes on the next line
LINE_PART = 1.22      # a line's height as a part of its font size
LINES_PART = 0.9      # how much of a bar's height the lines of a slot may take
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
    note = None
    project = None
    width = None
    height = None
    logo = None
    text_opacity = None
    letterbox = None
    range_start = None
    range_end = None
    warn_range = None
    warn_color = None

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
        ShotMaskNode.note = string("note", "smnote")
        ShotMaskNode.logo = string("logo", "smlogo")  # an image file: what {logo} draws
        ShotMaskNode.project = string("project", "smprj")
        ShotMaskNode.width = number("frameWidth", "smfw", om.MFnNumericData.kInt, 0, 0)
        ShotMaskNode.height = number("frameHeight", "smfh", om.MFnNumericData.kInt, 0, 0)
        ShotMaskNode.range_start = number("rangeStart", "smrs", om.MFnNumericData.kInt, 0)
        ShotMaskNode.range_end = number("rangeEnd", "smre", om.MFnNumericData.kInt, 0)
        ShotMaskNode.warn_range = number("warnRange", "smwr", om.MFnNumericData.kBoolean, False)
        ShotMaskNode.aspect = number("aspect", "smasp", om.MFnNumericData.kFloat, 0.0, 0.0)  # 0 = the whole viewport
        ShotMaskNode.text_scale = number("textScale", "smts", om.MFnNumericData.kFloat, 1.0, 0.3, 4.0)
        ShotMaskNode.bar_scale = number("barScale", "smbs", om.MFnNumericData.kFloat, 1.0, 0.3, 4.0)
        ShotMaskNode.bar_opacity = number("barOpacity", "smbo", om.MFnNumericData.kFloat, 1.0, 0.0, 1.0)
        ShotMaskNode.text_opacity = number("textOpacity", "smto", om.MFnNumericData.kFloat, 1.0, 0.0, 1.0)
        # > 0: the bars are as high as it takes to leave a picture of this shape (2.39 = scope)
        # between them, whatever barScale says; 0 = off
        ShotMaskNode.letterbox = number("letterbox", "smlb", om.MFnNumericData.kFloat, 0.0, 0.0)
        ShotMaskNode.top_bar = number("topBar", "smtb", om.MFnNumericData.kBoolean, True)
        ShotMaskNode.bottom_bar = number("bottomBar", "smbb", om.MFnNumericData.kBoolean, True)
        ShotMaskNode.counter_padding = number("counterPadding", "smcp", om.MFnNumericData.kInt, 4, 1, 8)
        ShotMaskNode.text_color = color("textColor", "smtc", (1.0, 1.0, 1.0))
        ShotMaskNode.bar_color = color("barColor", "smbc", (0.0, 0.0, 0.0))
        ShotMaskNode.warn_color = color("warnColor", "smwc", (1.0, 0.33, 0.28))

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
        self.warn_color = om.MColor((1.0, 0.33, 0.28, 1.0))
        self.warned = set()  # the slots drawn in the warning color
        self.logo_slots = set()  # the slots that hold {logo}
        self.logo = None         # the logo's MTexture (None = no picture)
        self.logo_aspect = 1.0   # its width / height


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
        letterbox = plug(ShotMaskNode.letterbox).asFloat()
        if letterbox > 0.0 and width / letterbox < height:
            data.bar_height = (height - width / letterbox) / 2.0
            # a thin bar still has to hold its text
            data.font_size = max(6, min(data.font_size, int(data.bar_height * 0.8)))
        data.padding = height * PADDING_PART
        data.top_bar = plug(ShotMaskNode.top_bar).asBool()
        data.bottom_bar = plug(ShotMaskNode.bottom_bar).asBool()
        data.font_name = plug(ShotMaskNode.font_name).asString() or "Consolas"
        text = plug(ShotMaskNode.text_color)
        data.text_color = om.MColor((text.child(0).asFloat(), text.child(1).asFloat(), text.child(2).asFloat(),
                                     plug(ShotMaskNode.text_opacity).asFloat()))
        bar = plug(ShotMaskNode.bar_color)
        data.bar_color = om.MColor((bar.child(0).asFloat(), bar.child(1).asFloat(), bar.child(2).asFloat(),
                                    plug(ShotMaskNode.bar_opacity).asFloat()))

        warn = plug(ShotMaskNode.warn_color)
        data.warn_color = om.MColor((warn.child(0).asFloat(), warn.child(1).asFloat(), warn.child(2).asFloat(), 1.0))
        frame = int(round(oma.MAnimControl.currentTime().value))
        fps = self._fps()
        start = int(round(oma.MAnimControl.minTime().value))
        end = int(round(oma.MAnimControl.maxTime().value))
        rate = max(1, int(round(fps)))
        seconds, part = divmod(max(0, frame), rate)
        timecode = "%02d:%02d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60, part)
        frame_width, frame_height = plug(ShotMaskNode.width).asInt(), plug(ShotMaskNode.height).asInt()
        resolution = "%dx%d" % (frame_width, frame_height) if frame_width and frame_height else ""
        outside = (plug(ShotMaskNode.warn_range).asBool()
                   and not plug(ShotMaskNode.range_start).asInt() <= frame <= plug(ShotMaskNode.range_end).asInt())
        padding = plug(ShotMaskNode.counter_padding).asInt()
        scene = os.path.splitext(os.path.basename(om1.MFileIO.currentFile()))[0] or "untitled"
        values = {"scene": scene, "camera": camera_name, "frame": str(frame),
                  "counter": ("-" if frame < 0 else "") + str(abs(frame)).zfill(padding),
                  "focal_length": "%.0f mm" % camera.focalLength, "fps": "%g" % fps,
                  "date": time.strftime("%Y-%m-%d"), "user": self._user_name(),
                  "time": time.strftime("%H:%M"), "timecode": timecode, "start": str(start), "end": str(end),
                  "range": "%d-%d" % (start, end), "frames": str(end - start + 1), "resolution": resolution,
                  "note": plug(ShotMaskNode.note).asString(), "project": plug(ShotMaskNode.project).asString()}
        data.texts = {}
        data.warned = set()
        data.logo_slots = set()
        for slot, attribute in ShotMaskNode.texts.items():
            text = plug(attribute).asString()
            if outside and ("{frame}" in text or "{counter}" in text or "{timecode}" in text):
                data.warned.add(slot)
            if LOGO_TOKEN in text:
                data.logo_slots.add(slot)
                text = text.replace(LOGO_TOKEN, "").strip()
            for token, value in values.items():
                text = text.replace("{" + token + "}", value)
            data.texts[slot] = text
        data.logo, data.logo_aspect = (self._logo(plug(ShotMaskNode.logo).asString())
                                       if data.logo_slots else (None, 1.0))
        return data

    _textures = {}  # image path -> (MTexture | None, width / height); kept: loading one costs

    @classmethod
    def _logo(cls, path):
        """The picture `path` as a texture and its shape; (None, 1.0) if it can't be read."""
        if not path:
            return None, 1.0
        try:
            stamp = (path, os.path.getmtime(path))
        except OSError:
            return None, 1.0
        if stamp not in cls._textures:
            manager = omr.MRenderer.getTextureManager()
            for old in list(cls._textures):  # another file, or the file changed: let the old one go
                texture = cls._textures.pop(old)[0]
                if texture is not None:
                    manager.releaseTexture(texture)
            texture = manager.acquireTexture(path)
            aspect = 1.0
            if texture is not None:
                description = texture.textureDescription()
                if description.fHeight:
                    aspect = float(description.fWidth) / float(description.fHeight)
            cls._textures[stamp] = (texture, aspect)
        return cls._textures[stamp]

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
        logo_height = bar * LOGO_PART
        logo_width = logo_height * data.logo_aspect
        logos = []  # (centre x, centre y) of every logo to draw
        for row, line, middle in (("top", top_line, y + height - bar / 2.0), ("bottom", bottom_line, y + bar / 2.0)):
            for column, at, alignment in columns:
                text = data.texts.get(row + column, "")
                if row + column in data.logo_slots and data.logo is not None:
                    aside = logo_width + data.padding
                    if column == "Left":
                        logos.append((at + logo_width / 2.0, middle))
                        at += aside
                    elif column == "Right":
                        logos.append((at - logo_width / 2.0, middle))
                        at -= aside
                    else:
                        logos.append((at, middle))
                        text = ""
                lines = [part.strip() for part in text.split(NEW_LINE)] if text else []
                while lines and not lines[-1]:
                    lines.pop()
                if not lines:
                    continue
                draw_manager.setColor(data.warn_color if row + column in data.warned else data.text_color)
                if len(lines) == 1:
                    draw_manager.setFontSize(data.font_size)
                    draw_manager.text2d(om.MPoint(at, line), lines[0], alignment)
                    continue
                # several lines: as big as the one-line text, unless they wouldn't fit the bar
                size = max(5, min(data.font_size, int(bar * LINES_PART / (len(lines) * LINE_PART))))
                step = size * LINE_PART
                draw_manager.setFontSize(size)
                first = middle + (len(lines) - 1) * step / 2.0  # the centre of the top line
                for index, part in enumerate(lines):
                    if part:
                        draw_manager.text2d(om.MPoint(at, first - index * step - size * 0.36), part, alignment)
        draw_manager.endDrawable()
        if logos:
            draw_manager.beginDrawable()
            draw_manager.setTexture(data.logo)
            draw_manager.setTextureSampler(omr.MSamplerState.kMinMagMipLinear, omr.MSamplerState.kTexClamp)
            draw_manager.setTextureMask(omr.MBlendState.kRGBAChannels)
            draw_manager.setColor(om.MColor((1.0, 1.0, 1.0, data.text_color.a)))  # as see-through as the text
            for centre_x, centre_y in logos:
                draw_manager.rect2d(om.MPoint(centre_x, centre_y), om.MVector(0.0, 1.0, 0.0),
                                    logo_width / 2.0, logo_height / 2.0, True)
            draw_manager.setTexture(None)
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
    manager = omr.MRenderer.getTextureManager()
    for texture, _aspect in ShotMaskDrawOverride._textures.values():
        if texture is not None and manager is not None:
            manager.releaseTexture(texture)
    ShotMaskDrawOverride._textures.clear()
