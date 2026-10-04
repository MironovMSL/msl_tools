# tools/maya/playblast/capture.py
"""The Maya side of a playblast: what the scene is, and the capture itself —
frames into a folder, with the viewport put back the way it was. No Qt.

Runs inside Maya only (maya.cmds). Everything a capture changes — the
panel's camera, the selection, the current frame, the scene's
"modified" mark — is restored afterwards, also when it fails
or is cancelled, and none of it reaches the undo queue.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from maya import cmds, mel

ACTIVE_VIEW = ""   # CaptureSettings.camera: whatever the viewport looks through now
RESOLUTIONS = {"HD 1080": (1920, 1080), "HD 720": (1280, 720), "HD 540": (960, 540)}
RANGE_PLAYBACK, RANGE_ANIMATION, RANGE_RENDER = "Playback", "Animation", "Render"
RANGE_SELECTED = "Selected"   # the frames highlighted on the timeline (none: the playback range)

# What a viewport can show or hide, by kind: (group, [(modelEditor flag, what the user reads)]).
# Every flag was checked against Maya 2025 (queried and set on a model panel).
VISIBILITY_GROUPS = (
    ("Geometry", [("polymeshes", "Polygons"), ("nurbsSurfaces", "NURBS surfaces"),
                  ("subdivSurfaces", "Subdiv surfaces"), ("planes", "Planes")]),
    ("Curves and rig", [("nurbsCurves", "NURBS curves"), ("controllers", "Controllers"), ("cv", "NURBS CVs"),
                        ("hulls", "NURBS hulls"), ("joints", "Joints"), ("ikHandles", "IK handles"),
                        ("deformers", "Deformers"), ("locators", "Locators"), ("handles", "Handles"),
                        ("pivots", "Pivots")]),
    ("Scene", [("cameras", "Cameras"), ("lights", "Lights"), ("imagePlane", "Image planes"),
               ("textures", "Texture placements"), ("dimensions", "Dimensions"), ("strokes", "Strokes"),
               ("motionTrails", "Motion trails"), ("clipGhosts", "Clip ghosts"),
               ("greasePencils", "Grease pencil"), ("bluePencil", "Blue pencil"),
               ("pluginShapes", "Plug-in shapes"), ("hos", "Hold-outs")]),
    ("Dynamics", [("dynamics", "Dynamics"), ("fluids", "Fluids"), ("nParticles", "nParticles"),
                  ("nCloths", "nCloths"), ("nRigids", "nRigids"), ("hairSystems", "Hair systems"),
                  ("follicles", "Follicles"), ("particleInstancers", "Particle instancers"),
                  ("dynamicConstraints", "Dynamic constraints")]),
    ("Viewport", [("grid", "Grid"), ("manipulators", "Manipulators"),
                  ("selectionHiliteDisplay", "Selection highlighting")]),
)
VISIBILITY = tuple(flag for _group, entries in VISIBILITY_GROUPS for flag, _label in entries)
VISIBILITY_LABELS = {flag: label for _group, entries in VISIBILITY_GROUPS for flag, label in entries}
_GEOMETRY = ["polymeshes", "nurbsSurfaces", "subdivSurfaces"]
# name -> the kinds shown; everything else is hidden for the playblast
VISIBILITY_PRESETS = {
    "Geometry": _GEOMETRY,
    "Geometry + controls": _GEOMETRY + ["nurbsCurves", "controllers", "locators"],
    "Geometry + image planes": _GEOMETRY + ["imagePlane"],
    "Dynamics": _GEOMETRY + ["dynamics", "fluids", "nParticles", "nCloths", "hairSystems", "particleInstancers"],
}


class CaptureError(Exception):
    """A playblast couldn't be made; the message is written for the user."""


@dataclass
class CaptureSettings:
    """What to capture.

    Attributes:
        folder: Where the frames go (created; frames of the same name are replaced).
        name: The frames' name: `<name>.<number>.<format>`.
        start / end: The frame range, both included.
        width / height: The frames' size.
        camera: The camera to look through (ACTIVE_VIEW = as the viewport is).
        image_format: "png" or "jpg".
        ornaments: Keep the viewport's own overlays (HUD, axis) in the picture.
        visibility: The kinds of objects shown (flags of VISIBILITY), everything else
            hidden for the capture; None = as the viewport is.
        smooth: Anti-aliasing on for the capture (edges without stairs).
        occlusion: Ambient occlusion on for the capture (soft contact shadows).
        background: An even background (r, g, b in 0..1) instead of the viewport's own, for the
            capture; None = as the viewport is. (Maya's background is one setting for every
            viewport: it is put back afterwards.)
        overscan: Room around the frame (the camera's overscan, e.g. 1.1 = 10 %) for the capture;
            1.0 = none. The shot mask then marks the frame's edge inside the picture.
    """

    folder: Path
    name: str = "frame"
    start: int = 1
    end: int = 24
    width: int = 1920
    height: int = 1080
    camera: str = ACTIVE_VIEW
    image_format: str = "png"
    ornaments: bool = False
    visibility: tuple | None = None
    smooth: bool = False
    occlusion: bool = False
    background: tuple | None = None
    overscan: float = 1.0


@dataclass
class Capture:
    """What a capture made.

    Attributes:
        folder: The folder holding the frames.
        fps: The scene's frame rate.
        frames: How many frames were written.
        sound: The timeline's sound file ("" = none).
        sound_start: Seconds into that sound at which the first frame lies
            (negative: the sound begins that much AFTER the first frame).
        camera: The camera it was seen through.
    """

    folder: Path
    fps: float
    frames: int
    sound: str = ""
    sound_start: float = 0.0
    camera: str = ""


def frame_rate() -> float:
    """The scene's frames per second."""
    return float(mel.eval("currentTimeUnitToFPS"))


def scene_name() -> str:
    """The scene's name without folder and extension ("" for a scene never saved)."""
    return Path(cmds.file(query=True, sceneName=True) or "").stem


# what the user reads -> Maya's name of that time unit
FRAME_RATES = {"23.976": "23.976fps", "24": "film", "25": "pal", "29.97": "29.97fps", "30": "ntsc", "48": "show",
               "50": "palf", "59.94": "59.94fps", "60": "ntscf"}


def set_frame_rate(label: str) -> None:
    """Sets the scene's frame rate (a key of FRAME_RATES). The keys stay on their FRAME NUMBERS:
    the animation gets faster or slower, nothing is moved on the timeline."""
    cmds.currentUnit(time=FRAME_RATES[label], updateAnimation=False)


def scene_path() -> str:
    """The scene file ("" for a scene never saved)."""
    return cmds.file(query=True, sceneName=True) or ""


def scene_folder() -> str:
    """The folder of the scene file ("" for a scene never saved)."""
    path = cmds.file(query=True, sceneName=True) or ""
    return str(Path(path).parent.as_posix()) if path else ""


def project_folder() -> str:
    return cmds.workspace(query=True, rootDirectory=True) or ""


def cameras() -> list[str]:
    """The scene's cameras: the user's own first, then persp / top / front / side."""
    names = cmds.listCameras() or []
    own = [name for name in names if not cmds.camera(name, query=True, startupCamera=True)]
    return own + [name for name in names if name not in own]


def viewport_panel() -> str:
    """The viewport a playblast is taken from: the one with the focus, else the first one shown."""
    focused = cmds.getPanel(withFocus=True)
    if focused and cmds.getPanel(typeOf=focused) == "modelPanel":
        return focused
    for panel in cmds.getPanel(visiblePanels=True) or []:
        if cmds.getPanel(typeOf=panel) == "modelPanel":
            return panel
    raise CaptureError("No viewport is open — open one and try again.")


def visibility_state(panel: str = "") -> dict:
    """flag -> shown, for every kind of VISIBILITY, as `panel` (default: the active viewport) is now."""
    panel = panel or viewport_panel()
    return {flag: bool(cmds.modelEditor(panel, query=True, **{flag: True})) for flag in VISIBILITY}


def active_camera() -> str:
    """The camera the viewport looks through ("" without a viewport)."""
    try:
        camera = cmds.modelPanel(viewport_panel(), query=True, camera=True) or ""
    except CaptureError:
        return ""
    if camera and cmds.nodeType(camera) == "camera":  # a shape was returned: name its transform
        camera = (cmds.listRelatives(camera, parent=True) or [camera])[0]
    return camera


def frame_range(kind: str) -> tuple[int, int]:
    """The frames of a named range: the playback range, the whole animation range, or the render settings'."""
    if kind == RANGE_SELECTED:
        try:
            slider = mel.eval("$msl_playback_slider = $gPlayBackSlider")
            if cmds.timeControl(slider, query=True, rangeVisible=True):
                first, after = cmds.timeControl(slider, query=True, rangeArray=True)
                first = math.floor(first)
                return first, max(first, math.ceil(after) - 1)  # the end of a selection is exclusive
        except RuntimeError:
            pass
        kind = RANGE_PLAYBACK
    if kind == RANGE_ANIMATION:
        start, end = (cmds.playbackOptions(query=True, animationStartTime=True),
                      cmds.playbackOptions(query=True, animationEndTime=True))
    elif kind == RANGE_RENDER:
        start, end = cmds.getAttr("defaultRenderGlobals.startFrame"), cmds.getAttr("defaultRenderGlobals.endFrame")
    else:
        start, end = cmds.playbackOptions(query=True, minTime=True), cmds.playbackOptions(query=True, maxTime=True)
    return whole_frames(start, end)


def whole_frames(start: float, end: float) -> tuple[int, int]:
    """A range that may end on sub-frames (-0.5 .. 100.5) as the whole frames covering it
    (-1 .. 101): int() cut toward zero and lost a frame at each end of such a range."""
    return math.floor(start), math.ceil(end)


def render_resolution() -> tuple[int, int]:
    """The frame size of the scene's render settings."""
    return int(cmds.getAttr("defaultResolution.width")), int(cmds.getAttr("defaultResolution.height"))


def timeline_sound() -> tuple[str, float]:
    """(file, the frame it starts at) of the sound shown on the timeline; ("", 0) without one."""
    try:
        slider = mel.eval("$msl_playback_slider = $gPlayBackSlider")
        node = cmds.timeControl(slider, query=True, sound=True)
    except RuntimeError:
        return "", 0.0
    if not node:
        return "", 0.0
    return cmds.sound(node, query=True, file=True) or "", float(cmds.getAttr(f"{node}.offset"))


class CaptureSession:
    """A playblast taken ONE FRAME AT A TIME, so whoever drives it can show
    how far it is and stop it between frames:

        session = CaptureSession(settings)      # looks through the camera, clears the selection
        while session.step():                   # one frame each; False after the last one
            ...                                 # e.g. back to the event loop
        shot = session.finish()                 # everything put back -> Capture

    `abort()` instead of `finish()` gives up (everything is put back too).
    The viewport's camera, the selection, the current frame and the scene's
    "modified" mark and what it shows are restored whatever happens; nothing of it reaches the
    undo queue — and the undo queue is only switched off INSIDE a step, so
    what the user does between two frames stays undoable.
    """

    def __init__(self, settings: CaptureSettings):
        if settings.end < settings.start:
            raise CaptureError("The last frame must not be before the first one.")
        if settings.camera and not cmds.objExists(settings.camera):
            raise CaptureError(f"The camera “{settings.camera}” isn’t in the scene any more.")
        self.settings = settings
        self.total = settings.end - settings.start + 1
        self.done = 0
        self._panel = viewport_panel()
        self._folder = Path(settings.folder)
        self._folder.mkdir(parents=True, exist_ok=True)
        self._previous_camera = cmds.modelPanel(self._panel, query=True, camera=True)
        self._selection = cmds.ls(selection=True, long=True) or []
        self._time = cmds.currentTime(query=True)
        self._modified = cmds.file(query=True, modified=True)
        self._shown = visibility_state(self._panel) if settings.visibility is not None else None
        # Viewport 2.0's own switches (one node for every viewport): set for the capture, put back after
        wanted = {}
        if settings.smooth:
            wanted.update({"multiSampleEnable": True, "lineAAEnable": True})
        if settings.occlusion:
            wanted["ssaoEnable"] = True
        self._render = {}
        for attribute, value in wanted.items():
            plug = f"hardwareRenderingGlobals.{attribute}"
            try:
                self._render[plug] = cmds.getAttr(plug)
            except (RuntimeError, ValueError):
                continue
        # The background (a preference of Maya's, not of the scene) and the camera's overscan
        self._background = None
        if settings.background is not None:
            self._background = (bool(cmds.displayPref(query=True, displayGradient=True)),
                                tuple(cmds.displayRGBColor("background", query=True)))
        self._overscan = None
        if abs(settings.overscan - 1.0) > 1e-6:
            camera_shape = _camera_shape(settings.camera or self._previous_camera)
            if camera_shape:
                self._overscan = (camera_shape, cmds.getAttr(camera_shape + ".overscan"))
        self._open = True
        try:
            with _NoUndo():
                if self._background is not None:
                    cmds.displayPref(displayGradient=False)
                    cmds.displayRGBColor("background", *settings.background)
                if self._overscan is not None:
                    cmds.setAttr(self._overscan[0] + ".overscan", settings.overscan)
                for plug in self._render:
                    cmds.setAttr(plug, True)
                if settings.visibility is not None:
                    wanted = set(settings.visibility)
                    cmds.modelEditor(self._panel, edit=True, **{flag: flag in wanted for flag in VISIBILITY})
                if settings.camera:
                    cmds.lookThru(self._panel, settings.camera)
                cmds.select(clear=True)  # selection highlights and manipulators don't belong in the picture
        except Exception as error:
            # Half set up: whatever was changed goes back before the error is passed on.
            self._restore()
            raise CaptureError(f"Maya couldn’t prepare the playblast: {str(error).strip()}") from error

    def step(self) -> bool:
        """Draws the next frame. True while there are more to draw."""
        if not self._open or self.done >= self.total:
            return False
        settings, frame = self.settings, self.settings.start + self.done
        try:
            with _NoUndo():
                written = cmds.playblast(
                    format="image", compression=settings.image_format, quality=100,
                    filename=(self._folder / settings.name).as_posix(), startTime=frame, endTime=frame,
                    widthHeight=(settings.width // 2 * 2, settings.height // 2 * 2), percent=100, viewer=False,
                    offScreen=True, forceOverwrite=True, framePadding=4, showOrnaments=settings.ornaments,
                    clearCache=self.done == 0, editorPanelName=self._panel)
        except RuntimeError as error:
            self.abort()
            raise CaptureError(f"Maya couldn’t playblast: {str(error).strip()}") from error
        if not written:
            self.abort()
            raise CaptureError("The playblast was cancelled.")
        self.done += 1
        return self.done < self.total

    def finish(self) -> Capture:
        """Puts the viewport back and says what was made."""
        settings = self.settings
        camera = settings.camera or active_camera()
        self._restore()
        suffix = "." + settings.image_format
        frames = len([entry for entry in self._folder.iterdir() if entry.suffix.lower() == suffix])
        fps = frame_rate()
        sound, sound_frame = timeline_sound()
        return Capture(folder=self._folder, fps=fps, frames=frames, sound=sound,
                       sound_start=(settings.start - sound_frame) / fps if sound else 0.0, camera=camera)

    def abort(self) -> None:
        """Gives up: the viewport is put back (the frames drawn so far stay where they are)."""
        self._restore()

    def _restore(self) -> None:
        if not self._open:
            return
        self._open = False
        # Each step on its own: one that fails (the camera was deleted, another scene was opened
        # meanwhile) must not keep the others — the render switches above all — from going back.
        steps = []
        if self._previous_camera:
            steps.append(lambda: cmds.lookThru(self._panel, self._previous_camera))
        if self._selection:
            steps.append(lambda: cmds.select([name for name in self._selection if cmds.objExists(name)],
                                             replace=True))
        steps.append(lambda: cmds.currentTime(self._time, edit=True))
        if self._shown is not None:
            steps.append(lambda: cmds.modelEditor(self._panel, edit=True, **self._shown))
        for plug, value in self._render.items():
            steps.append(lambda plug=plug, value=value: cmds.setAttr(plug, value))
        if self._background is not None:
            gradient, color = self._background
            steps.append(lambda: cmds.displayRGBColor("background", *color))
            steps.append(lambda: cmds.displayPref(displayGradient=gradient))
        if self._overscan is not None:
            shape, value = self._overscan
            steps.append(lambda: cmds.setAttr(shape + ".overscan", value))
        with _NoUndo():
            for step in steps:
                try:
                    step()
                except Exception:
                    continue
            if not self._modified:
                try:
                    cmds.file(modified=False)  # looking through another camera marks the scene as changed
                except Exception:
                    pass


def _camera_shape(camera: str) -> str:
    """The camera shape of `camera` (a transform or a shape); "" if there is none."""
    if not camera or not cmds.objExists(camera):
        return ""
    if cmds.nodeType(camera) == "camera":
        return camera
    shapes = cmds.listRelatives(camera, shapes=True, type="camera", fullPath=True) or []
    return shapes[0] if shapes else ""


class _NoUndo:
    """Inside: what happens is no edit of the scene, and stays out of the undo queue."""

    def __enter__(self):
        # Put back as it WAS: switching it on regardless re-enabled undo for whoever had it off.
        self._was_on = cmds.undoInfo(query=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *_exc):
        if self._was_on:
            cmds.undoInfo(stateWithoutFlush=True)
        return False


def capture(settings: CaptureSettings) -> Capture:
    """Playblasts the range into `settings.folder` as numbered pictures and
    returns what was made — the whole range in one go (blocks until Maya has
    drawn every frame). A window uses CaptureSession instead."""
    session = CaptureSession(settings)
    while session.step():
        pass
    return session.finish()


def current_frame() -> int:
    """The frame the time slider is on."""
    return int(round(cmds.currentTime(query=True)))


def channel_box_attributes() -> list:
    """"node.attribute" for each attribute selected in the Channel Box, on the last selected node."""
    nodes = cmds.ls(selection=True) or []
    if not nodes:
        return []
    try:
        names = cmds.channelBox("mainChannelBox", query=True, selectedMainAttributes=True) or []
    except RuntimeError:
        return []
    return [f"{nodes[-1]}.{name}" for name in names]

