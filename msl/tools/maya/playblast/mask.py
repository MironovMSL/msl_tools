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
    "camera": "the camera of the viewport",
    "counter": "the frame, padded with zeros: 0042",
    "frame": "the frame as it is: 42",
    "focal_length": "the camera's focal length: 35 mm",
    "fps": "the scene's frames per second",
    "date": "today's date: 2026-10-03",
    "user": "your login name",
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
        top_bar / bottom_bar: Draw that bar.
        text_color / bar_color: (r, g, b), 0..1.
        counter_padding: Digits of {counter}.
    """

    texts: dict = field(default_factory=lambda: dict(DEFAULT_TEXTS))
    camera: str = ""
    aspect: float = 0.0
    text_scale: float = 1.0
    bar_scale: float = 1.0
    bar_opacity: float = 1.0
    top_bar: bool = True
    bottom_bar: bool = True
    text_color: tuple = (1.0, 1.0, 1.0)
    bar_color: tuple = (0.0, 0.0, 0.0)
    counter_padding: int = 4


class _Quiet:
    """Inside: nothing reaches the undo queue, and the scene's "modified" mark is put back."""

    def __enter__(self):
        self._modified = cmds.file(query=True, modified=True)
        cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *_exc):
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


def node() -> str:
    """The mask node of the scene ("" = none)."""
    if not cmds.pluginInfo(PLUGIN.name, query=True, loaded=True):
        return ""
    found = cmds.ls(type=NODE_TYPE, long=True) or []
    return found[0] if found else ""


def is_shown() -> bool:
    return bool(node())


_state = {"settings": None, "callbacks": [], "put_back": False}


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


def _unwatch_saves() -> None:
    for callback in _state["callbacks"]:
        om.MMessage.removeCallback(callback)
    _state["callbacks"] = []


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
    cmds.setAttr(f"{shape}.topBar", bool(settings.top_bar))
    cmds.setAttr(f"{shape}.bottomBar", bool(settings.bottom_bar))
    cmds.setAttr(f"{shape}.counterPadding", int(settings.counter_padding))
    cmds.setAttr(f"{shape}.textColor", *settings.text_color, type="double3")
    cmds.setAttr(f"{shape}.barColor", *settings.bar_color, type="double3")
