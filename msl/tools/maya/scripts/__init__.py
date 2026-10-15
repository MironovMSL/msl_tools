# tools/maya/scripts/__init__.py
"""MSL Scripts: one key = one thing done, no window — the actions a hotkey or the MSL menu's
"Scripts" calls. As opposed to the TOOLS (Playblast, Rename, Controls, Labels: windows), these
work on what is selected / under the pointer and say what they did in the viewport.

    reset_attributes.py   values back to their defaults: picked keys, picked channels, or the
                          selected objects (a transform's t / r / s, another node's keyable ones)
    camera_views.py       the viewport camera to an orthographic view of the side it faces, and back
    viewport.py           what a viewport shows: a kind on / off, geometry only (Shift: every viewport)
    rig.py                locators / joints on the selection (the Controls tool's own functions)

SCRIPTS is the one list of them: tools/maya/hotkeys.py makes each a runtime command of the Hotkey
Editor (Custom Scripts > MSL Scripts, NO key given — the user gives keys), the MSL menu lists them
under Scripts. A new script = its function here + one Script line. Actions that belong to a tool
(Controls' quick mirror, Labels' toggle, ...) are listed here too: the code stays with the tool.

Nothing here imports Maya: the list is read when the menu is built.
"""
from dataclasses import dataclass

_HERE = __name__                                 # msl_tools.msl.tools.maya.scripts
_TOOLS = _HERE.rsplit(".", 1)[0]                 # msl_tools.msl.tools.maya


@dataclass(frozen=True)
class Script:
    command: str      # the runtime command's name (the Hotkey Editor shows it)
    label: str        # the MSL menu's entry
    annotation: str   # what the Hotkey Editor and the menu's tooltip say it does
    call: str         # dotted path of the function it runs
    group: str        # where it stands in the menu

    def python(self) -> str:
        """The Python a runtime command runs."""
        module, function = self.call.rsplit(".", 1)
        return f"from {module} import {function}; {function}()"


SCRIPTS = (
    # camera
    Script("MSLOrthoView", "Ortho View", "The viewport camera (under the pointer) as an orthographic view of the side "
           "it faces - front, side, top...; again = back to the perspective it had",
           f"{_HERE}.camera_views.toggle_ortho", "Camera"),
    Script("MSLCameraBack", "Camera Back", "The viewport camera back: to the perspective it had before Ortho View, "
           "else Maya's home view", f"{_HERE}.camera_views.camera_back", "Camera"),
    # what the viewport shows (Shift: every viewport)
    Script("MSLToggleCurves", "Curves On / Off", "NURBS curves shown / hidden in the viewport under the pointer "
           "(Shift: every viewport)", f"{_HERE}.viewport.toggle_curves", "Viewport"),
    Script("MSLTogglePolygons", "Polygons On / Off", "Polygons shown / hidden in the viewport under the pointer "
           "(Shift: every viewport)", f"{_HERE}.viewport.toggle_polygons", "Viewport"),
    Script("MSLToggleJoints", "Joints On / Off", "Joints shown / hidden in the viewport under the pointer "
           "(Shift: every viewport)", f"{_HERE}.viewport.toggle_joints", "Viewport"),
    Script("MSLToggleLocators", "Locators On / Off", "Locators shown / hidden in the viewport under the pointer "
           "(Shift: every viewport)", f"{_HERE}.viewport.toggle_locators", "Viewport"),
    Script("MSLGeometryOnly", "Geometry Only", "Everything but the geometry hidden in the viewport under the "
           "pointer; again = back to exactly what it showed (Shift: every viewport)",
           f"{_HERE}.viewport.geometry_only", "Viewport"),
    # attributes
    Script("MSLResetAttributes", "Reset Attributes", "Values back to their defaults: the keys picked in the Graph "
           "Editor, else the channels picked in the Channel Box, else the selected objects' move / rotate / scale "
           "(a shape or another node: its keyable attributes). A default_<name> attribute on the node wins",
           f"{_HERE}.reset_attributes.run", "Attributes"),
    # rig
    Script("MSLLocatorsOnSelection", "Locators on Selection", "A locator on each selected object (at its pivot, "
           "turned like it) and on each selected vertex, edge, face", f"{_HERE}.rig.locators", "Rig"),
    Script("MSLLocatorInMiddle", "Locator in the Middle", "ONE locator in the middle of everything selected "
           "(an edge loop's center)", f"{_HERE}.rig.locator_in_middle", "Rig"),
    Script("MSLJointsOnSelection", "Joints on Selection", "A joint chain through the selection in the order picked",
           f"{_HERE}.rig.joints", "Rig"),
    # the Controls tool's quick actions
    Script("MSLControlsMirror", "Mirror Controls", "Controls: mirror the selected controls to the other side",
           f"{_TOOLS}.controls.quick.mirror", "Controls"),
    Script("MSLControlsZero", "Zero Controls", "Controls: zero the selected (groups or the offset matrix, as the "
           "window is set)", f"{_TOOLS}.controls.quick.zero", "Controls"),
    Script("MSLControlsSelect", "Select Controls", "Controls: select the controls under the selection (nothing "
           "selected: of the scene)", f"{_TOOLS}.controls.quick.select_controls", "Controls"),
    Script("MSLControlsPoseCopy", "Copy Pose", "Controls: copy the selected objects' pose",
           f"{_TOOLS}.controls.quick.copy_pose", "Controls"),
    Script("MSLControlsPosePaste", "Paste Pose", "Controls: paste the copied pose onto the selection",
           f"{_TOOLS}.controls.quick.paste_pose", "Controls"),
    Script("MSLControlsMatch", "Match", "Controls: match the selected objects to the last selected one",
           f"{_TOOLS}.controls.quick.match", "Controls"),
    Script("MSLControlsReset", "Reset Taken Channels", "Controls: the channels taken in the window, of the selected "
           "objects, back to rest", f"{_TOOLS}.controls.quick.reset", "Controls"),
    # showing
    Script("MSLShotMaskToggle", "Shot Mask On / Off", "Show or hide the MSL shot mask in the viewport",
           f"{_TOOLS}.playblast.toggle_mask", "Show"),
    Script("MSLLabelsToggle", "Labels On / Off", "Show or hide every set of MSL Labels in the scene",
           f"{_TOOLS}.labels.toggle", "Show"),
)
GROUPS = ("Camera", "Viewport", "Attributes", "Rig", "Controls", "Show")
