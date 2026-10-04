# tools/maya/playblast/mask.py
"""The shot mask's Maya side: loads the plug-in, makes / removes / updates the one
`mslShotMask` node of the scene. No Qt.

The node is a helper of the SESSION, not part of the scene: it is marked "do not
write" (a saved scene never holds it, so nobody needs the plug-in to open that
scene), stays out of the outliner, and making or removing it leaves no trace in
the undo queue or in the scene's "modified" mark. What the mask shows lives in
the tool's settings; after a scene is opened the tool puts the mask back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from maya import cmds
import maya.api.OpenMaya as om

# In the Maya module of msl_tools (msl/maya_module). A Maya started from Maya Gate knows the
# module (MAYA_MODULE_PATH), finds the plug-in by NAME and trusts it; any other Maya is given
# the file's path — and asks its "untrusted plug-in" question first.
PLUGIN = Path(__file__).resolve().parents[3] / "maya_module" / "plug-ins" / "msl_shot_mask.py"
NODE_TYPE = "mslShotMask"
TRANSFORM = "mslShotMask"
SLOTS = ("topLeft", "topCenter", "topRight", "bottomLeft", "bottomCenter", "bottomRight")
# token -> what it stands for (shown in the "insert a token" menu)
TOKENS = {
    "scene": "the scene's name",
    "project": "the project folder's name",
    "camera": "the camera of the viewport",
    "focal_length": "the camera's focal length: 35 mm",
    "resolution": "the playblast's frame size: 1920x1080",
    "counter": "the frame, padded with zeros: 0042",
    "frame": "the frame as it is: 42",
    "timecode": "the frame as time: 00:00:01:18",
    "range": "the playback range: 1-96",
    "start": "the first frame of the playback range",
    "end": "its last frame",
    "frames": "how many frames the playback range has",
    "fps": "the scene's frames per second",
    "date": "today's date: 2026-10-03",
    "time": "the time now: 14:05",
    "user": "your login name",
    "note": "the note typed below: WIP, for review...",
    "logo": "the logo picture chosen below",
}
DEFAULT_TEXTS = {"topLeft": "{scene}", "topCenter": "", "topRight": "{date}",
                 "bottomLeft": "{camera}  {focal_length}", "bottomCenter": "{user}", "bottomRight": "{counter}"}


class MaskError(Exception):
    """The mask couldn't be shown; the message is written for the user."""


@dataclass
class MaskSettings:
    """What the mask shows.

    Attributes:
        texts: slot (one of SLOTS) -> its text, tokens allowed.
        camera: Draw only in this camera's viewport ("" = every perspective one).
        aspect: Width / height of the frame the mask frames (0 = the whole viewport).
        text_scale / bar_scale: 1 = the usual size.
        bar_opacity: 0 = no bars (text only) … 1 = solid.
        text_opacity: The same for the text (and the logo).
        font: The font's name (one of fonts()).
        letterbox: > 0 = the bars leave a picture of this width / height between them
            (2.39 = scope), whatever bar_scale says.
        top_bar / bottom_bar: Draw that bar.
        text_color / bar_color: (r, g, b), 0..1.
        counter_padding: Digits of {counter}.
        note / project: What {note} and {project} show.
        logo: The image file {logo} draws ("" = none).
        width / height: The playblast's frame size, for {resolution}.
        warn_range: Draw the slots that show the frame in `warn_color` while the
            current frame is outside range_start..range_end.
    """

    texts: dict = field(default_factory=lambda: dict(DEFAULT_TEXTS))
    camera: str = ""
    aspect: float = 0.0
    text_scale: float = 1.0
    bar_scale: float = 1.0
    bar_opacity: float = 1.0
    text_opacity: float = 1.0
    font: str = "Consolas"
    letterbox: float = 0.0
    top_bar: bool = True
    bottom_bar: bool = True
    text_color: tuple = (1.0, 1.0, 1.0)
    bar_color: tuple = (0.0, 0.0, 0.0)
    counter_padding: int = 4
    note: str = ""
    logo: str = ""
    project: str = ""
    width: int = 0
    height: int = 0
    warn_range: bool = False
    range_start: int = 0
    range_end: int = 0
    warn_color: tuple = (1.0, 0.33, 0.28)


class _Quiet:
    """Inside: nothing reaches the undo queue, and the scene's "modified" mark is put back."""

    def __enter__(self):
        self._modified = cmds.file(query=True, modified=True)
        self._undo_was_on = cmds.undoInfo(query=True, stateWithoutFlush=True)  # put back as it WAS
        cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *_exc):
        if self._undo_was_on:
            cmds.undoInfo(stateWithoutFlush=True)
        if not self._modified:
            cmds.file(modified=False)
        return False


def _load_plugin() -> None:
    if cmds.pluginInfo(PLUGIN.name, query=True, loaded=True):
        return
    try:
        try:
            cmds.loadPlugin(PLUGIN.name, quiet=True)   # on Maya's plug-in path: no question asked
        except RuntimeError:
            cmds.loadPlugin(str(PLUGIN), quiet=True)   # Maya asks whether to allow it
    except RuntimeError as error:
        raise MaskError(f"The shot mask’s plug-in couldn’t be loaded: {str(error).strip()}") from error


def token_values(camera: str, settings: MaskSettings) -> dict:
    """token -> what it reads right now, as the plug-in would fill it in (for a sketch of the
    mask outside the viewport). `camera`: the camera it is seen through."""
    import getpass
    import time
    from maya import mel
    frame = int(round(cmds.currentTime(query=True)))
    fps = float(mel.eval("currentTimeUnitToFPS"))
    start = int(cmds.playbackOptions(query=True, minTime=True))
    end = int(cmds.playbackOptions(query=True, maxTime=True))
    rate = max(1, int(round(fps)))
    seconds, part = divmod(max(0, frame), rate)
    focal = ""
    try:
        if camera and cmds.objExists(camera):
            focal = "%.0f mm" % cmds.camera(camera, query=True, focalLength=True)
    except RuntimeError:
        pass
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    return {"scene": Path(cmds.file(query=True, sceneName=True) or "").stem or "untitled",
            "project": settings.project, "camera": camera.split("|")[-1], "focal_length": focal,
            "resolution": f"{settings.width}x{settings.height}" if settings.width and settings.height else "",
            "frame": str(frame), "counter": ("-" if frame < 0 else "") + str(abs(frame)).zfill(settings.counter_padding),
            "timecode": "%02d:%02d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60, part),
            "start": str(start), "end": str(end), "range": f"{start}-{end}", "frames": str(end - start + 1),
            "fps": f"{fps:g}", "date": time.strftime("%Y-%m-%d"), "time": time.strftime("%H:%M"),
            "user": user, "note": settings.note}


def fonts() -> list[str]:
    """The fonts the viewport can draw text with, by name."""
    import maya.api.OpenMayaRender as omr
    try:
        return sorted(set(omr.MUIDrawManager.getFontList()), key=str.lower)
    except Exception:
        return ["Consolas"]


def node() -> str:
    """The mask node of the scene ("" = none)."""
    if not cmds.pluginInfo(PLUGIN.name, query=True, loaded=True):
        return ""
    found = cmds.ls(type=NODE_TYPE, long=True) or []
    return found[0] if found else ""


def is_shown() -> bool:
    return bool(node())


_state = {"settings": None, "callbacks": [], "put_back": False}

# The save callbacks' ids also live on maya.cmds — a module "Reload Code" doesn't replace. A copy
# of this module from before a reload left its callbacks registered, still putting back the OLD
# mask after every save (and more of them with every reload): they are taken off on import.
_CALLBACKS_KEPT_ON = "_msl_shot_mask_save_callbacks"


def _drop_callbacks_of_an_older_copy() -> None:
    for callback in getattr(cmds, _CALLBACKS_KEPT_ON, None) or []:
        try:
            om.MMessage.removeCallback(callback)
        except RuntimeError:  # already gone
            pass
    setattr(cmds, _CALLBACKS_KEPT_ON, [])


_drop_callbacks_of_an_older_copy()


def last_draw_error() -> str:
    """The traceback of the mask's last failed draw ("" = it draws). Maya swallows a draw's exception;
    the plug-in leaves it in an environment variable of this process."""
    import os
    return os.environ.get("MSL_SHOT_MASK_ERROR", "")


def _before_save(*_args) -> None:
    # A scene saved while the mask is up gets a `requires "msl_shot_mask.py"` line (the node itself
    # is never written): whoever opens it without the plug-in is warned. So the mask steps out
    # for the moment of the save.
    if node():
        _state["put_back"] = True
        _remove()


def _after_save(*_args) -> None:
    if _state["put_back"] and _state["settings"] is not None:
        _state["put_back"] = False
        try:
            show(_state["settings"])
        except MaskError:
            pass


def _watch_saves() -> None:
    if not _state["callbacks"]:
        _state["callbacks"] = [om.MSceneMessage.addCallback(om.MSceneMessage.kBeforeSave, _before_save),
                               om.MSceneMessage.addCallback(om.MSceneMessage.kAfterSave, _after_save)]
        setattr(cmds, _CALLBACKS_KEPT_ON, list(_state["callbacks"]))


def _unwatch_saves() -> None:
    for callback in _state["callbacks"]:
        om.MMessage.removeCallback(callback)
    _state["callbacks"] = []
    setattr(cmds, _CALLBACKS_KEPT_ON, [])


def show(settings: MaskSettings) -> str:
    """Puts the mask into the viewport (or updates the one that is there). Returns the node."""
    _load_plugin()
    _state["settings"] = settings
    _watch_saves()
    with _Quiet():
        shape = node()
        if not shape:
            selection = cmds.ls(selection=True, long=True) or []
            transform = cmds.createNode("transform", name=TRANSFORM, skipSelect=True)
            shape = cmds.createNode(NODE_TYPE, name=TRANSFORM + "Shape", parent=transform, skipSelect=True)
            shape = cmds.ls(shape, long=True)[0]
            cmds.setAttr(transform + ".hiddenInOutliner", True)
            for name in (transform, shape):  # never written into a saved scene
                picked = om.MSelectionList().add(name)
                om.MFnDependencyNode(picked.getDependNode(0)).setDoNotWrite(True)
            for attribute in ("tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"):
                cmds.setAttr(f"{transform}.{attribute}", lock=True, keyable=False, channelBox=False)
            if selection:
                cmds.select(selection, replace=True)
        _apply(shape, settings)
    cmds.refresh(force=False)
    return shape


def update(settings: MaskSettings) -> None:
    """New settings onto the mask, if it is shown."""
    shape = node()
    if shape:
        _state["settings"] = settings
        with _Quiet():
            _apply(shape, settings)
        cmds.refresh(force=False)


def hide() -> None:
    """Takes the mask out of the viewport."""
    _unwatch_saves()
    _state["put_back"] = False
    _remove()


def _remove() -> None:
    shape = node()
    if not shape:
        return
    with _Quiet():
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        cmds.lockNode(parents + [shape], lock=False)
        cmds.delete(parents or shape)
    cmds.refresh(force=False)


def _apply(shape: str, settings: MaskSettings) -> None:
    for slot in SLOTS:
        cmds.setAttr(f"{shape}.{slot}Text", settings.texts.get(slot, ""), type="string")
    cmds.setAttr(f"{shape}.camera", settings.camera.split("|")[-1], type="string")
    cmds.setAttr(f"{shape}.aspect", float(settings.aspect))
    cmds.setAttr(f"{shape}.textScale", float(settings.text_scale))
    cmds.setAttr(f"{shape}.barScale", float(settings.bar_scale))
    cmds.setAttr(f"{shape}.barOpacity", float(settings.bar_opacity))
    cmds.setAttr(f"{shape}.textOpacity", float(settings.text_opacity))
    cmds.setAttr(f"{shape}.letterbox", float(settings.letterbox))
    cmds.setAttr(f"{shape}.fontName", settings.font or "Consolas", type="string")
    cmds.setAttr(f"{shape}.topBar", bool(settings.top_bar))
    cmds.setAttr(f"{shape}.bottomBar", bool(settings.bottom_bar))
    cmds.setAttr(f"{shape}.counterPadding", int(settings.counter_padding))
    cmds.setAttr(f"{shape}.textColor", *settings.text_color, type="double3")
    cmds.setAttr(f"{shape}.barColor", *settings.bar_color, type="double3")
    cmds.setAttr(f"{shape}.warnColor", *settings.warn_color, type="double3")
    cmds.setAttr(f"{shape}.note", settings.note, type="string")
    cmds.setAttr(f"{shape}.logo", str(settings.logo).replace("\\", "/"), type="string")
    cmds.setAttr(f"{shape}.project", settings.project, type="string")
    cmds.setAttr(f"{shape}.frameWidth", int(settings.width))
    cmds.setAttr(f"{shape}.frameHeight", int(settings.height))
    cmds.setAttr(f"{shape}.warnRange", bool(settings.warn_range))
    cmds.setAttr(f"{shape}.rangeStart", int(settings.range_start))
    cmds.setAttr(f"{shape}.rangeEnd", int(settings.range_end))
