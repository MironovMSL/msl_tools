# tools/maya/playblast/panel_tables.py
"""The Playblast panel's fixed choices: names of sizes, ranges, formats, the shot mask's
looks and presets, the presets of a whole playblast. No Qt."""
from msl_tools.msl.core.fs.manager import FileSystemManager
from msl_tools.msl.tools.maya.playblast import mask


ACTIVE_VIEW = "Active view"
SIZE_RENDER, SIZE_CUSTOM = "Render settings", "Custom"
RANGE_CUSTOM = "Custom"
FORMAT_MP4, FORMAT_MOV, FORMAT_FRAMES = "MP4", "MOV", "Frames"
VIDEO_FORMATS = {FORMAT_MP4: ("mp4", ".mp4"), FORMAT_MOV: ("prores", ".mov")}  # shown -> (core/media format, suffix)
CODECS = {"H.264": "h264", "H.265": "h265"}   # MP4's picture codec (H.265: smaller, slower to play back)
# The viewport's background for the capture (put back afterwards): None = as the viewport is
BACKGROUNDS = {"Viewport": None, "Gray": (0.36, 0.36, 0.36), "Black": (0.0, 0.0, 0.0)}
# Room around the frame in the picture (camera overscan for the capture): composition notes see past the edge
OVERSCAN = {"Off": 1.0, "5 %": 1.05, "10 %": 1.1, "20 %": 1.2}
QUALITY = {"Best": "best", "High": "high", "Good": "good", "Small": "small"}  # the word shown -> core/media's
SHOW_VIEWPORT, SHOW_CUSTOM = "As in the viewport", "Custom"
MASK_TEXT = {"Small": 0.8, "Medium": 1.0, "Large": 1.3}       # the word shown -> the mask's text scale
MASK_BARS = {"Solid": 1.0, "75 %": 0.75, "50 %": 0.5, "None": 0.0}  # ... -> how solid its bars are
# The mask's looks that come with the tool (name -> what a click sets; the switch and the note stay).
MASK_PRESETS = {
    "Review": {"texts": dict(mask.DEFAULT_TEXTS), "text": "Medium", "bars": "Solid",
               "text_color": "#ffffff", "bar_color": "#000000"},
    "Client": {"texts": {"topLeft": "{logo}", "topCenter": "{note}", "topRight": "{date}", "bottomLeft": "{scene}",
                         "bottomCenter": "", "bottomRight": "{timecode}"},
               "text": "Medium", "bars": "75 %", "text_color": "#ffffff", "bar_color": "#000000"},
    "Frames": {"texts": {"topLeft": "", "topCenter": "", "topRight": "", "bottomLeft": "{range}",
                         "bottomCenter": "", "bottomRight": "{counter}"},
               "text": "Small", "bars": "None", "text_color": "#ffffff", "bar_color": "#000000"},
}
# Our own mark: what {logo} draws until another picture is chosen.
BRAND_LOGO = FileSystemManager.icons / "brand" / "watermark.png"
MASK_OPACITY = {"Solid": 1.0, "75 %": 0.75, "50 %": 0.5}             # ... -> how solid its text is
# ... -> the shape of the picture the bars leave between them (0 = the bars keep their own height)
MASK_LETTERBOX = {"Off": 0.0, "2.39:1": 2.39, "2.35:1": 2.35, "2:1": 2.0, "1.85:1": 1.85, "16:9": 16 / 9,
                  "4:3": 4 / 3, "1:1": 1.0}
MASK_DIGITS = ("2", "3", "4", "5", "6")
# every key of a mask's look with its default: a preset saved before a key existed means the default
MASK_LOOK_DEFAULTS = {"text": "Medium", "bars": "Solid", "text_color": "#ffffff", "bar_color": "#000000",
                      "top_bar": True, "bottom_bar": True, "font": "Consolas", "text_opacity": "Solid",
                      "letterbox": "Off", "digits": "4", "safe_action": False, "safe_title": False}
# A preset of the WHOLE playblast keeps these settings (not the camera, not custom frames: those
# belong to the scene) and, under "mask", the mask's look and whether it is shown.
PRESET_KEYS = ("size", "width", "height", "range", "show", "format", "quality", "sound", "ornaments", "smooth",
               "occlusion", "overwrite", "open", "copy", "folder", "name", "background", "overscan", "codec")
# The ones that come with the tool (name -> what a click sets; a key left out stays as it is).
PRESETS = {
    "Review": {"size": "HD 1080", "range": "Playback", "show": "As in the viewport", "format": "MP4",
               "quality": "High", "smooth": False, "occlusion": False,
               "mask": dict(MASK_PRESETS["Review"], shown=True)},
    "Client": {"size": "HD 1080", "range": "Playback", "show": "Geometry", "format": "MP4", "quality": "Best",
               "smooth": True, "occlusion": True, "mask": dict(MASK_PRESETS["Client"], shown=True)},
    "Quick": {"size": "HD 540", "range": "Playback", "show": "As in the viewport", "format": "MP4",
              "quality": "Small", "smooth": False, "occlusion": False, "mask": {"shown": False}},
}
MASK_PLACES = {"topLeft": "top left", "topCenter": "top centre", "topRight": "top right",
               "bottomLeft": "bottom left", "bottomCenter": "bottom centre", "bottomRight": "bottom right"}


def _plain(value):
    """A config node (or anything nested in one) as plain dicts and lists."""
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
