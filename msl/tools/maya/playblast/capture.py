# tools/maya/playblast/capture.py
"""The Maya side of a playblast: what the scene is, and the capture itself —
frames into a folder, with the viewport put back the way it was. No Qt.

Runs inside Maya only (maya.cmds). Everything a capture changes — the
panel's camera, the selection, the current frame, the scene's
"modified" mark — is restored afterwards, also when it fails
or is cancelled, and none of it reaches the undo queue.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from maya import cmds, mel

ACTIVE_VIEW = ""   # CaptureSettings.camera: whatever the viewport looks through now
RESOLUTIONS = {"HD 1080": (1920, 1080), "HD 720": (1280, 720), "HD 540": (960, 540)}
RANGE_PLAYBACK, RANGE_ANIMATION, RANGE_RENDER = "Playback", "Animation", "Render"

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
    if kind == RANGE_ANIMATION:
        start, end = (cmds.playbackOptions(query=True, animationStartTime=True),
                      cmds.playbackOptions(query=True, animationEndTime=True))
    elif kind == RANGE_RENDER:
        start, end = cmds.getAttr("defaultRenderGlobals.startFrame"), cmds.getAttr("defaultRenderGlobals.endFrame")
    else:
        start, end = cmds.playbackOptions(query=True, minTime=True), cmds.playbackOptions(query=True, maxTime=True)
    return int(start), int(end)


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
        self._open = True
        with _NoUndo():
            if settings.visibility is not None:
                wanted = set(settings.visibility)
                cmds.modelEditor(self._panel, edit=True, **{flag: flag in wanted for flag in VISIBILITY})
            if settings.camera:
                cmds.lookThru(self._panel, settings.camera)
            cmds.select(clear=True)  # selection highlights and manipulators don't belong in the picture

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
        with _NoUndo():
            try:
                if self._previous_camera:
                    cmds.lookThru(self._panel, self._previous_camera)
                if self._selection:
                    cmds.select([name for name in self._selection if cmds.objExists(name)], replace=True)
                cmds.currentTime(self._time, edit=True)
                if self._shown is not None:
                    cmds.modelEditor(self._panel, edit=True, **self._shown)
            finally:
                if not self._modified:
                    cmds.file(modified=False)  # looking through another camera marks the scene as changed


class _NoUndo:
    """Inside: what happens is no edit of the scene, and stays out of the undo queue."""

    def __enter__(self):
        cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *_exc):
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
