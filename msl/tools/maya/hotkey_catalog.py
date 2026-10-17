# tools/maya/hotkey_catalog.py
"""Every Maya command of msl_tools a key can be given to, as plain data - read by BOTH sides:
inside Maya (tools/maya/hotkeys.py makes each a runtime command, tools/maya/hotkey_set.py gives
them their keys) and in the hub (Maya Gate's Hotkeys tab lists them).

Imports neither Maya nor Qt (the hub reads it without Maya). The TOOLS' commands are listed here;
the MSL Scripts come from tools/maya/scripts (SCRIPTS, Maya-free too).
"""
from __future__ import annotations

from dataclasses import dataclass

from msl_tools.msl.tools.maya.scripts import GROUPS as SCRIPT_GROUPS
from msl_tools.msl.tools.maya.scripts import SCRIPTS

TOOLS_CATEGORY = "Custom Scripts.MSL Tools"
SCRIPTS_CATEGORY = "Custom Scripts.MSL Scripts"


@dataclass(frozen=True)
class Command:
    name: str         # the runtime command (what the Hotkey Editor lists)
    label: str        # how the hub names it
    annotation: str   # what it does (the Hotkey Editor's annotation, the hub's tooltip)
    python: str       # what it runs
    group: str        # the tool / group it belongs to (the hub's filter chips)
    icon: str         # an assets/icons/actions SVG
    category: str     # the Hotkey Editor's category
    toggle: bool = False   # on / off: run again on the key's RELEASE it puts things back ("hold to see")


def _tool(name: str, label: str, annotation: str, module: str, function: str, group: str, icon: str) -> Command:
    return Command(name, label, annotation, f"from msl_tools.msl.tools.maya.{module} import {function}; {function}()",
                   group, icon, TOOLS_CATEGORY)


def _slide(name: str, label: str, annotation: str, mode: str, weight: float, icon: str) -> Command:
    return Command(name, label, annotation, f"from msl_tools.msl.tools.maya.animation import nudge; "
                   f"nudge({mode!r}, {weight!r})", "Animation", icon, TOOLS_CATEGORY)


TOOL_COMMANDS = (
    _tool("MSLAnimation", "Animation window", "Open the MSL Animation window (the pose and curve sliders)",
          "animation", "launcher_entry_point", "Animation", "animation"),
    _slide("MSLAnimTweenHalf", "Tween 50%", "An inbetween half way between the keys around (the current frame, "
           "the timeline's range or the Graph Editor's keys)", "tween", 0.0, "animation"),
    _slide("MSLAnimNeighborsLeft", "Blend to key before 25%", "A quarter of the way toward the key before",
           "neighbors", -0.25, "chevron_left"),
    _slide("MSLAnimNeighborsRight", "Blend to key after 25%", "A quarter of the way toward the key after",
           "neighbors", 0.25, "chevron_right"),
    _slide("MSLAnimPull", "Pull 25%", "Soften: a quarter of the way to the straight line between the keys around",
           "pull_push", -0.25, "shrink"),
    _slide("MSLAnimPush", "Push 25%", "Exaggerate: a quarter more away from the straight line between the keys "
           "around", "pull_push", 0.25, "grow"),
    _tool("MSLPlayblast", "Playblast window", "Open the MSL Playblast window", "playblast", "launcher_entry_point",
          "Playblast", "clapper"),
    _tool("MSLPlayblastRepeat", "Playblast again", "Playblast again with the settings used last (opens the window "
          "if it is closed)", "playblast", "repeat_last", "Playblast", "repeat"),
    _tool("MSLRename", "Rename window", "Open the MSL Rename window", "rename", "launcher_entry_point", "Rename",
          "rename"),
    _tool("MSLRenameQuick", "Quick rename", "Rename at the mouse pointer: a small field, Enter renames the selection",
          "rename", "quick", "Rename", "text_frame"),
    _tool("MSLRenameRepeat", "Rename again", "Rename again: the last rename on what is selected now (opens the "
          "window if it is closed)", "rename", "repeat_last", "Rename", "repeat"),
    _tool("MSLControls", "Controls window", "Controls: the window of control shapes and tools", "controls",
          "launcher_entry_point", "Controls", "controls"),
    _tool("MSLLabels", "Labels window", "Open the MSL Labels window (attribute values in the viewport)", "labels",
          "launcher_entry_point", "Labels", "labels"),
    _tool("MSLPathsToVariables", "Paths to variables", "Paths to variables: the open scene's absolute paths become "
          "$WG_ANIM/... (asks first)", "scene_paths_tool", "paths_to_variables", "Scene", "scene"),
)

# MSL Scripts' icons (tools/maya/scripts keeps no icon of its own)
SCRIPT_ICONS = {
    "MSLOrthoView": "camera", "MSLCameraBack": "undo",
    "MSLToggleCurves": "smooth_curve", "MSLTogglePolygons": "viewport", "MSLToggleJoints": "joint_node",
    "MSLToggleLocators": "locator", "MSLGeometryOnly": "eye",
    "MSLResetAttributes": "zero_out",
    "MSLLocatorsOnSelection": "locator", "MSLLocatorInMiddle": "center", "MSLJointsOnSelection": "joint_chain",
    "MSLControlsMirror": "mirror_shape", "MSLControlsZero": "zero_out", "MSLControlsSelect": "select_all",
    "MSLControlsPoseCopy": "copy", "MSLControlsPosePaste": "paste", "MSLControlsMatch": "move",
    "MSLControlsReset": "restart",
    "MSLShotMaskToggle": "hud", "MSLLabelsToggle": "labels",
}

# on / off commands: run a second time they put back what the first did, so a key may run them again when it is let
# go ("hold to see" - Maya Gate's Hotkeys tab, tools/maya/hotkey_set.py: releaseName)
TOGGLES = {"MSLToggleCurves", "MSLTogglePolygons", "MSLToggleJoints", "MSLToggleLocators", "MSLGeometryOnly",
           "MSLOrthoView", "MSLShotMaskToggle", "MSLLabelsToggle"}

# the hub's groups, in its order: the tools first, then the scripts' groups (Controls once)
GROUPS = tuple(dict.fromkeys(["Animation", "Playblast", "Rename", "Controls", "Labels", "Scene"] + list(SCRIPT_GROUPS)))


def commands() -> tuple:
    """Every command, the tools' first, each once."""
    scripts = tuple(Command(script.command, script.label, script.annotation, script.python(), script.group,
                            SCRIPT_ICONS.get(script.command, "keyboard"), SCRIPTS_CATEGORY,
                            script.command in TOGGLES) for script in SCRIPTS)
    return TOOL_COMMANDS + scripts


def names() -> list:
    return [command.name for command in commands()]


def by_name() -> dict:
    return {command.name: command for command in commands()}
