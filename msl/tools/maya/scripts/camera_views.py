# tools/maya/scripts/camera_views.py
"""Ortho View and Camera Back — the user's old View Snap / Reset Camera, rewritten.

`toggle_ortho()`: the camera of the viewport under the pointer (else the one with the focus)
    - perspective -> an ORTHOGRAPHIC view of the side it faces most: it is turned to look straight
      along the nearest world axis, with "up" the nearest world axis across it (built from those two
      directions — rounding each Euler angle to 90 degrees on its own went wrong for a camera tilted
      near 90 degrees and for rotate orders other than xyz), looking at the same point as before,
      as wide as that point was far, and moved back so nothing in front of the old view is cut off;
    - orthographic (one this script made) -> back to the perspective it had, carried along by how
      far the ortho view was panned meanwhile; an ortho camera of no record (the scene was reopened):
      a perspective of the same width in front of where it looks.
`camera_back()`: the perspective from before Ortho View, as it was (no panning carried); with none
    remembered, Maya's home view of that camera (`viewSet -home`).

Camera moves are view changes, not edits: they stay out of the undo queue (and the undo state is put
back as it WAS) and the scene's "modified" mark is put back. A camera with keys, locks or something
driving its move / rotate (a shot camera) is left alone — the message says why; Maya's own top /
front / side cameras too (they are orthographic by nature).

The perspective each camera had is remembered for the Maya session (by the camera's UUID).
"""
from maya import cmds
import maya.api.OpenMaya as om

AXES = {"+X": om.MVector(1, 0, 0), "-X": om.MVector(-1, 0, 0), "+Y": om.MVector(0, 1, 0),
        "-Y": om.MVector(0, -1, 0), "+Z": om.MVector(0, 0, 1), "-Z": om.MVector(0, 0, -1)}
SIDES = {"-Z": "front", "+Z": "back", "-X": "right side", "+X": "left side", "-Y": "top", "+Y": "bottom"}  # by where it LOOKS
STARTUP = ("top", "front", "side", "bottom", "back", "left")
BACK_OFF = 1000.0      # an ortho camera stands at least this far (scene units) from what it looks at
_remembered = {}       # camera UUID -> {"matrix": [16], "coi": float, "ortho": [16]}


# --- what it works on --------------------------------------------------------------------------

def viewport_panel() -> str:
    """The model panel under the pointer, else the one with the focus; "" = none."""
    for panel in (cmds.getPanel(underPointer=True), cmds.getPanel(withFocus=True)):
        if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
            return panel
    return ""


def panel_camera(panel: str) -> str:
    """The camera TRANSFORM a model panel looks through."""
    camera = cmds.modelPanel(panel, query=True, camera=True)
    if camera and cmds.nodeType(camera) == "camera":
        camera = cmds.listRelatives(camera, parent=True, fullPath=True)[0]
    return camera


def _shape(camera: str) -> str:
    shapes = cmds.listRelatives(camera, shapes=True, type="camera", fullPath=True) or []
    return shapes[0] if shapes else camera


def why_not(camera: str) -> str:
    """Why this camera mustn't be moved ("" = it may)."""
    short = camera.rsplit("|", 1)[-1]
    if short in STARTUP and cmds.camera(camera, query=True, startupCamera=True):
        return f"{short} is one of Maya's own orthographic cameras"
    for attribute in ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ"):
        plug = f"{camera}.{attribute}"
        if cmds.getAttr(plug, lock=True):
            return f"{short}'s {attribute} is locked"
        if cmds.listConnections(plug, source=True, destination=False):
            return f"{short}'s {attribute} is keyed or driven (a shot camera is left alone)"
    return ""


# --- the math (no Maya scene involved) ------------------------------------------------------------

def nearest_axis(vector, avoid=None) -> str:
    """The name of the world axis ("+X" ...) closest to `vector`; `avoid` = an axis it must be
    across (its own and the opposite one are skipped)."""
    best, best_dot = "", -2.0
    for name, axis in AXES.items():
        if avoid is not None and name[1] == avoid[1]:
            continue
        dot = vector.normal() * axis
        if dot > best_dot:
            best, best_dot = name, dot
    return best


def ortho_matrix(matrix, center_of_interest: float):
    """For a camera's world matrix and center of interest: (its ortho world matrix, the point it
    looks at, the width, the side's name). Maya's camera looks along its -Z, up = +Y."""
    m = om.MMatrix(matrix)
    position = om.MVector(m[12], m[13], m[14])
    forward = -om.MVector(m[8], m[9], m[10]).normal()
    up = om.MVector(m[4], m[5], m[6]).normal()
    look = nearest_axis(forward)
    upward = nearest_axis(up, avoid=look)
    z_axis = -AXES[look]
    y_axis = AXES[upward]
    x_axis = y_axis ^ z_axis
    target = position + forward * center_of_interest
    distance = max(center_of_interest, BACK_OFF)
    eye = target + z_axis * distance
    built = om.MMatrix([x_axis.x, x_axis.y, x_axis.z, 0, y_axis.x, y_axis.y, y_axis.z, 0,
                        z_axis.x, z_axis.y, z_axis.z, 0, eye.x, eye.y, eye.z, 1])
    return built, target, abs(center_of_interest), SIDES[look]


def carried(perspective, ortho_then, ortho_now):
    """The perspective matrix moved by how far the ortho camera was panned (its move across the
    view; moving along the view means nothing in an ortho view)."""
    then = om.MMatrix(ortho_then)
    now = om.MMatrix(ortho_now)
    look = om.MVector(then[8], then[9], then[10]).normal()
    shift = om.MVector(now[12] - then[12], now[13] - then[13], now[14] - then[14])
    shift -= look * (shift * look)
    result = om.MMatrix(perspective)
    result[12] += shift.x
    result[13] += shift.y
    result[14] += shift.z
    return result


# --- the scene --------------------------------------------------------------------------------------

class _ViewChange:
    """Inside: no undo queue (put back as it WAS), the scene's modified mark kept."""

    def __enter__(self):
        self._undo = cmds.undoInfo(query=True, stateWithoutFlush=True)
        self._modified = cmds.file(query=True, modified=True)
        cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *_exc):
        cmds.undoInfo(stateWithoutFlush=self._undo)
        if not self._modified:
            cmds.file(modified=False)
        return False


def _uuid(camera: str) -> str:
    return (cmds.ls(camera, uuid=True) or [camera])[0]


def _world(camera: str) -> list:
    return cmds.xform(camera, query=True, worldSpace=True, matrix=True)


def to_ortho(camera: str) -> str:
    """The perspective `camera` as an ortho view of the side it faces. Returns the side's name."""
    shape = _shape(camera)
    coi = cmds.getAttr(shape + ".centerOfInterest")
    matrix, _target, width, side = ortho_matrix(_world(camera), coi)
    with _ViewChange():
        _remembered[_uuid(camera)] = {"matrix": _world(camera), "coi": coi, "ortho": list(matrix)}
        cmds.xform(camera, worldSpace=True, matrix=list(matrix))
        cmds.setAttr(shape + ".centerOfInterest", max(coi, BACK_OFF))
        cmds.camera(camera, edit=True, orthographic=True, orthographicWidth=max(width, 0.001))
    return side


def to_perspective(camera: str, carry_pan: bool = True) -> bool:
    """The ortho `camera` back to perspective. True = to the one remembered."""
    shape = _shape(camera)
    record = _remembered.get(_uuid(camera))
    with _ViewChange():
        cmds.camera(camera, edit=True, orthographic=False)
        if record is not None:
            matrix = carried(record["matrix"], record["ortho"], _world(camera)) if carry_pan else \
                om.MMatrix(record["matrix"])
            cmds.xform(camera, worldSpace=True, matrix=list(matrix))
            cmds.setAttr(shape + ".centerOfInterest", record["coi"])
            _remembered.pop(_uuid(camera), None)
            return True
        # none remembered: as far in front of the point it looks at as the view was wide
        width = cmds.camera(camera, query=True, orthographicWidth=True)
        coi = cmds.getAttr(shape + ".centerOfInterest")
        m = om.MMatrix(_world(camera))
        forward = -om.MVector(m[8], m[9], m[10]).normal()
        move = forward * (coi - width)
        cmds.move(move.x, move.y, move.z, camera, relative=True, worldSpace=True)
        cmds.setAttr(shape + ".centerOfInterest", width)
    return False


def toggle_ortho() -> None:
    """Ortho View (see the module): the viewport's camera to ortho and back."""
    panel = viewport_panel()
    if not panel:
        _say("Ortho View: put the pointer over a viewport")
        return
    camera = panel_camera(panel)
    reason = why_not(camera)
    if reason:
        _say(f"Ortho View: {reason}")
        return
    short = camera.rsplit("|", 1)[-1]
    if cmds.camera(camera, query=True, orthographic=True):
        back = to_perspective(camera)
        _say(f"{short}: perspective again" + ("" if back else " (none remembered - in front of where it looked)"))
    else:
        _say(f"{short}: {to_ortho(camera)} view, orthographic - again for perspective")


def camera_back() -> None:
    """Camera Back (see the module)."""
    panel = viewport_panel()
    if not panel:
        _say("Camera Back: put the pointer over a viewport")
        return
    camera = panel_camera(panel)
    short = camera.rsplit("|", 1)[-1]
    if _uuid(camera) in _remembered and not why_not(camera):
        if not cmds.camera(camera, query=True, orthographic=True):
            _remembered.pop(_uuid(camera), None)       # back in perspective by hand since: nothing to undo
        else:
            to_perspective(camera, carry_pan=False)
            _say(f"{short}: back to the perspective it had")
            return
    with _ViewChange():
        cmds.viewSet(camera, home=True)
    _say(f"{short}: home view")


def _say(text: str) -> None:
    print("MSL " + text)
    try:
        cmds.inViewMessage(assistMessage=text, position="topCenter", fade=True, fadeStayTime=1400)
    except RuntimeError:
        pass
