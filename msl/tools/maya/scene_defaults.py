# tools/maya/scene_defaults.py
"""Inside Maya: the frame rate (and the rest of the Scene tab) a Maya Gate environment works at.

The launch says it (MSL_GATE_SCENE_FPS = "30", MSL_GATE_SCENE_CHECK = "1"); `start()`, run by
hub_link.start() once Maya is up, then
  - writes the rate into Maya's own preferences for new scenes (optionVars workingUnitTime /
    workingUnitTimeDefault - what File > New and Maya's next start read), so they stay this
    environment's;
  - gives it to the empty scene Maya started with, and to every new scene (kAfterNew);
  - with the check on, after a scene is opened (kAfterOpen) says when the scene - or a .ma
    reference it holds - is at another rate: a warning in the Script Editor (which reaches the
    hub's log) and a message in the viewport. An existing scene is NEVER changed: changing its
    rate moves its keys - that stays the user's decision.

The rest of the tab (core/link/scene_settings.py, MSL_GATE_SCENE_RANGE / _UNITS / _UP / _SPEED /
_TANGENTS / _AUTO_KEY), each only when set: the linear unit and playback range of new scenes go
into Maya's preferences too (File > New reads them) and onto the untouched start scene and every
new one; the up axis, playback speed, the tangents of new keys and auto key are set once at the
start (they outlast File > New on their own).

Runs in Maya 2023+ (PySide2 / 6), so Python 3.9-valid; never raises - a failure here must not
spoil Maya's start.
"""
from __future__ import annotations

import os
import re

from msl_tools.msl.core.link import scene_rate
from msl_tools.msl.core.link import scene_settings
from msl_tools.msl.core.link import variables

_CALLBACKS = "_msl_scene_defaults_callbacks"   # kept on maya.cmds: they outlive this module's reload


def wanted_unit() -> str:
    """The time unit this launch's environment works at ("" = Maya's own is left alone)."""
    return scene_rate.unit_for(os.environ.get(variables.SCENE_FPS, ""))


def checks() -> bool:
    return os.environ.get(variables.SCENE_CHECK, "") == "1"


def wanted() -> dict:
    """The rest of the tab's settings this launch carries ({key: "" or the value})."""
    return scene_settings.from_environment(os.environ)


def start() -> bool:
    """Puts the rate and the other settings in place and listens for new / opened scenes. Safe to
    call again (the callbacks of an earlier call are removed first). True if anything is set."""
    try:
        import maya.cmds as cmds
        _remove_callbacks(cmds)
        unit, settings = wanted_unit(), wanted()
        if not unit and not any(settings.values()):
            return False
        if unit:
            for name in ("workingUnitTime", "workingUnitTimeDefault"):
                cmds.optionVar(stringValue=(name, unit))
        _write_preferences(cmds, settings)
        _set_session(cmds, settings)
        apply_to_new_scene(unit, settings)
        import maya.api.OpenMaya as om
        ids = []
        if unit or settings["units"] or settings["range"]:
            ids.append(om.MSceneMessage.addCallback(om.MSceneMessage.kAfterNew, _after_new))
        if unit and checks():
            ids.append(om.MSceneMessage.addCallback(om.MSceneMessage.kAfterOpen, _after_open))
        setattr(cmds, _CALLBACKS, ids)
        return True
    except Exception:
        return False


def _write_preferences(cmds, settings: dict) -> None:
    """What File > New reads from Maya's preferences: the linear unit, the playback range."""
    if settings["units"]:
        for name in ("workingUnitLinear", "workingUnitLinearDefault"):
            cmds.optionVar(stringValue=(name, settings["units"]))
    span = scene_settings.parse_range(settings["range"])
    if span:
        start, end = span
        for name, value in (("playbackMin", start), ("playbackMax", end), ("playbackMinRange", start),
                            ("playbackMaxRange", end), ("playbackMinDefault", start), ("playbackMaxDefault", end),
                            ("playbackMinRangeDefault", start), ("playbackMaxRangeDefault", end)):
            cmds.optionVar(floatValue=(name, float(value)))


def _set_session(cmds, settings: dict) -> None:
    """What is set once and outlasts File > New: up axis, playback speed, key tangents, auto key.
    Each on its own - one that fails doesn't keep the others from being set."""
    def attempt(action):
        try:
            action()
        except Exception:
            pass

    modified = cmds.file(query=True, modified=True)
    if settings["up"] and cmds.upAxis(query=True, axis=True) != settings["up"]:
        attempt(lambda: cmds.upAxis(axis=settings["up"]))
    if settings["speed"]:
        attempt(lambda: cmds.playbackOptions(playbackSpeed=scene_settings.SPEEDS[settings["speed"]][1]))
    if settings["tangents"]:
        _shown, in_tangent, out_tangent = scene_settings.TANGENTS[settings["tangents"]]
        attempt(lambda: cmds.keyTangent(g=True, inTangentType=in_tangent, outTangentType=out_tangent))
    if settings["autokey"]:
        attempt(lambda: cmds.autoKeyframe(state=settings["autokey"] == "on"))
    if not modified:
        attempt(lambda: cmds.file(modified=False))   # the untouched start scene stays untouched


def stop() -> None:
    try:
        import maya.cmds as cmds
        _remove_callbacks(cmds)
    except Exception:
        pass


def _remove_callbacks(cmds) -> None:
    import maya.api.OpenMaya as om
    for callback in getattr(cmds, _CALLBACKS, None) or []:
        try:
            om.MMessage.removeCallback(callback)
        except Exception:
            pass
    setattr(cmds, _CALLBACKS, [])


def apply_to_new_scene(unit: str, settings: dict | None = None) -> bool:
    """Gives `unit` (and the linear unit / playback range of `settings`) to the scene that is open
    IF it is an untouched new one (no file, no changes) - a scene with work in it is never changed.
    Its "modified" mark stays as it was."""
    import maya.cmds as cmds
    if cmds.file(query=True, sceneName=True) or cmds.file(query=True, modified=True):
        return False
    settings = settings or {}
    if unit and cmds.currentUnit(query=True, time=True) != unit:
        cmds.currentUnit(time=unit, updateAnimation=False)
    if settings.get("units") and cmds.currentUnit(query=True, linear=True) != settings["units"]:
        cmds.currentUnit(linear=settings["units"])
    span = scene_settings.parse_range(settings.get("range", ""))
    if span:
        cmds.playbackOptions(minTime=span[0], maxTime=span[1], animationStartTime=span[0], animationEndTime=span[1])
    cmds.file(modified=False)
    return True


def _after_new(*_args) -> None:
    try:
        apply_to_new_scene(wanted_unit(), wanted())
    except Exception:
        pass


def mismatches(unit: str) -> list:
    """What in the open scene is not at `unit`: ["the scene: 24 fps", "reference shot_cam.ma: 24 fps"]."""
    import maya.cmds as cmds
    found = []
    scene = cmds.currentUnit(query=True, time=True)
    if scene != unit:
        found.append("the scene: %s" % scene_rate.describe(scene))
    for reference in cmds.file(query=True, reference=True) or []:
        path = re.sub(r"\{\d+\}$", "", reference)   # a second copy of a file is "<path>{1}"
        referenced = scene_rate.file_unit(path)
        if referenced and referenced != unit:
            found.append("reference %s: %s" % (os.path.basename(path), scene_rate.describe(referenced)))
    return found


def _after_open(*_args) -> None:
    try:
        unit = wanted_unit()
        if not unit:
            return
        found = mismatches(unit)
        if not found:
            return
        import maya.cmds as cmds
        if cmds.about(batch=True):
            _report(unit, found)
        else:
            # Said at Maya's next idle moment, not inside the open: a scene opened by code the hub
            # sent (the console, an assistant) opens while the hub's log stream is paused, and the
            # warning would never reach it.
            cmds.evalDeferred(lambda: _report(unit, found))
    except Exception:
        pass


def _report(unit: str, found: list) -> None:
    try:
        import maya.cmds as cmds
        environment = os.environ.get(variables.ENVIRONMENT, "") or "this environment"
        head = "MSL: %s works at %s, but" % (environment, scene_rate.describe(unit))
        for line in found:
            cmds.warning("%s %s (nothing was changed)" % (head, line))
        if not cmds.about(batch=True):
            cmds.inViewMessage(
                assistMessage="<hl>Frame rate</hl>: %s works at %s - %s" % (
                    environment, scene_rate.describe(unit), "; ".join(found)),
                position="topCenter", fade=True, fadeStayTime=6000)
    except Exception:
        pass
