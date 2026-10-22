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


def _key(name: str, label: str, annotation: str, call: str, args: tuple, icon: str, toggle: bool = False) -> Command:
    arguments = "".join(f", {a!r}" for a in args)
    return Command(name, label, annotation, f"from msl_tools.msl.tools.maya.animation import key_action; "
                   f"key_action({call!r}{arguments})", "Animation", icon, TOOLS_CATEGORY, toggle)


# the Animation window's KEYS row (keys_row.py); "N" = the window's frames number
KEY_COMMANDS = (
    _key("MSLAnimPreciseMinus", "Precise −", "The picked channels (Channel Box) / picked keys lowered by the precise "
         "step", "precise.precise", ("-STEP",), "minus"),
    _key("MSLAnimPrecisePlus", "Precise +", "The picked channels / picked keys raised by the precise step",
         "precise.precise", ("STEP",), "add"),
    _key("MSLAnimPreciseMinusFine", "Precise − fine", "Lowered by a tenth of the precise step", "precise.precise",
         ("-STEP", 0.1), "minus"),
    _key("MSLAnimPrecisePlusFine", "Precise + fine", "Raised by a tenth of the precise step", "precise.precise",
         ("STEP", 0.1), "add"),
    _key("MSLAnimPreciseMinusCoarse", "Precise − coarse", "Lowered by five precise steps", "precise.precise",
         ("-STEP", 5.0), "minus"),
    _key("MSLAnimPrecisePlusCoarse", "Precise + coarse", "Raised by five precise steps", "precise.precise",
         ("STEP", 5.0), "add"),
    _key("MSLAnimResetPose", "Reset pose", "Every keyable channel of the selected objects to its default (the "
         "preferred default pose where one is kept; autokey keys the animated ones)", "default_pose.reset", ("all",),
         "restart"),
    _key("MSLAnimResetTranslation", "Reset translation", "Move of the selected objects back to its default",
         "default_pose.reset", ("translate",), "move"),
    _key("MSLAnimResetRotation", "Reset rotation", "Rotate of the selected objects back to its default",
         "default_pose.reset", ("rotate",), "restart"),
    _key("MSLAnimResetScale", "Reset scale", "Scale of the selected objects back to its default",
         "default_pose.reset", ("scale",), "grow"),
    _key("MSLAnimResetTRS", "Reset translation, rotation, scale", "Move, rotate and scale back to their defaults",
         "default_pose.reset", ("trs",), "zero_out"),
    _key("MSLAnimSnapshotDefaultPose", "Snapshot preferred default pose", "The selected objects' pose kept as "
         "their default (by name without the namespace)", "default_pose.snapshot", (), "bookmark_add"),
    _key("MSLAnimNudgeLeft", "Nudge keys left", "The keys in play N frames left (picked / range / current frame)",
         "nudge", ("-N",), "key_nudge_left"),
    _key("MSLAnimNudgeRight", "Nudge keys right", "The keys in play N frames right", "nudge", ("N",),
         "key_nudge_right"),
    _key("MSLAnimNudgeAllLeft", "Nudge all keys left", "Every key of the selected objects N frames left",
         "nudge", ("-N", "all"), "key_nudge_left"),
    _key("MSLAnimNudgeAllRight", "Nudge all keys right", "Every key of the selected objects N frames right",
         "nudge", ("N", "all"), "key_nudge_right"),
    _key("MSLAnimNudgeSceneLeft", "Nudge the scene left", "Every key in the scene N frames left", "nudge",
         ("-N", "scene"), "key_nudge_left"),
    _key("MSLAnimNudgeSceneRight", "Nudge the scene right", "Every key in the scene N frames right", "nudge",
         ("N", "scene"), "key_nudge_right"),
    _key("MSLAnimSlideLeft", "Slide the motion left", "The keys stay, the motion moves N frames left under them",
         "time_offset", ("N",), "key_nudge_left"),
    _key("MSLAnimSlideRight", "Slide the motion right", "The keys stay, the motion moves N frames right under them",
         "time_offset", ("-N",), "key_nudge_right"),
    _key("MSLAnimInsertInbetween", "Insert inbetween", "N empty frames after the current frame (picked keys, the "
         "range's keys)", "inbetween", ("N",), "keys_insert"),
    _key("MSLAnimRemoveInbetween", "Remove inbetween", "N frames taken out after the current frame", "inbetween",
         ("-N",), "keys_remove"),
    _key("MSLAnimInsertInbetweenScene", "Insert inbetween · scene", "N empty frames after the current frame, every "
         "curve of the scene", "inbetween", ("N", True), "keys_insert"),
    _key("MSLAnimRemoveInbetweenScene", "Remove inbetween · scene", "N frames taken out after the current frame, "
         "every curve of the scene", "inbetween", ("-N", True), "keys_remove"),
    _key("MSLAnimSpaceKeys", "Space keys N apart", "The picked keys (the range's) laid out N frames apart",
         "set_spacing", ("N",), "keys_space"),
    _key("MSLAnimSpaceOnes", "Space keys on ones", "The picked keys (the range's) one frame apart", "set_spacing",
         (1,), "keys_space"),
    _key("MSLAnimSpaceTwos", "Space keys on twos", "The picked keys (the range's) two frames apart", "set_spacing",
         (2,), "keys_space"),
    _key("MSLAnimSpaceThrees", "Space keys on threes", "The picked keys (the range's) three frames apart",
         "set_spacing", (3,), "keys_space"),
    _key("MSLAnimSpaceFours", "Space keys on fours", "The picked keys (the range's) four frames apart",
         "set_spacing", (4,), "keys_space"),
    _key("MSLAnimShareKeyTimes", "Share key times", "Every curve of the selection keyed wherever any of them is",
         "share_times", (), "keys_share"),
    _key("MSLAnimShareKeyTimesLast", "Share key times from the last selected", "The others keyed wherever the "
         "last selected object is", "share_times", (True,), "keys_share"),
    _key("MSLAnimCopyKeyTimes", "Copy key times", "Keep the key times in play to paste them", "copy_times", (),
         "copy"),
    _key("MSLAnimCopyColorKeyTimes", "Copy color key times", "Keep the times of the keys of the current key's "
         "color", "copy_times", (True,), "copy"),
    _key("MSLAnimPasteTintKeyTimes", "Paste tint key times", "The selection's keys on the copied times take the "
         "copied color", "paste_tint", (), "keyframe"),
    _key("MSLAnimPasteKeyTimes", "Paste key times · merge", "Keys at the copied times", "paste_times", ("merge",),
         "paste"),
    _key("MSLAnimPasteKeyTimesReplace", "Paste key times · replace", "Keys at the copied times, other keys in "
         "their span removed", "paste_times", ("replace",), "paste"),
    _key("MSLAnimPasteKeyTimesInsert", "Paste key times · at the current frame", "Replace, the first copied time "
         "on the current frame", "paste_times", ("insert",), "paste"),
    _key("MSLAnimBakeOnes", "Bake on ones", "A key on every frame", "bake", (1,), "keys_bake"),
    _key("MSLAnimBakeTwos", "Bake on twos", "A key every 2 frames", "bake", (2,), "keys_bake"),
    _key("MSLAnimBakeThrees", "Bake on threes", "A key every 3 frames", "bake", (3,), "keys_bake"),
    _key("MSLAnimBakeFours", "Bake on fours", "A key every 4 frames", "bake", (4,), "keys_bake"),
    _key("MSLAnimBakeEvery", "Bake every N frames", "A key every N frames", "bake", ("N",), "keys_bake"),
    _key("MSLAnimBakeFromLast", "Bake from the last selected", "The others' keys on the last selected's key "
         "times, constraints baked", "bake_from_last", (), "keys_share"),
    _key("MSLAnimBakeInfinity", "Bake infinity", "A cycling curve's infinity made real keys", "bake_infinity", (),
         "infinity"),
    _key("MSLAnimSmartSnap", "Smart snap keys", "Keys between frames to whole frames, the pose kept",
         "smart_snap", (), "snap_grid"),
    _key("MSLAnimRemoveRedundant", "Remove redundant keys", "Keys that don't change the curve", "remove_redundant",
         (), "sweep"),
    _key("MSLAnimRemoveStatic", "Remove static curves", "Curves that hold one value", "remove_static", (), "minus"),
    _key("MSLAnimCrop", "Crop to the range", "Keys outside the highlighted range go", "crop", (), "crop"),
    _key("MSLAnimReverse", "Reverse animation", "The animation backwards in the range", "reverse", (), "reverse"),
    _key("MSLAnimClear", "Clear animation", "Every curve of the selected objects deleted", "clear", (), "clear"),
    _key("MSLAnimTintRed", "Tint keys red", "The keys in play: plain keys (poses)", "tint", ("red",), "keyframe"),
    _key("MSLAnimTintYellow", "Tint keys yellow", "The keys in play: breakdowns", "tint", ("yellow",), "keyframe"),
    _key("MSLAnimTintGreen", "Tint keys green", "The keys in play: baked keys (Maya's breakdown)", "tint",
         ("green",), "keyframe"),
    _key("MSLAnimTintSceneRed", "Every key in the scene red", "All the key colors in the scene cleared",
         "tint_scene_red", (), "keyframe"),
    _key("MSLAnimRemoveRedKeys", "Remove red keys", "Every red key of the selection", "remove_color", ("red",),
         "clear"),
    _key("MSLAnimRemoveYellowKeys", "Remove yellow keys", "Every yellow key of the selection", "remove_color",
         ("yellow",), "clear"),
    _key("MSLAnimRemoveGreenKeys", "Remove green keys", "Every green key of the selection", "remove_color",
         ("green",), "clear"),
    _key("MSLAnimPlayKeys", "Play keys", "Playback from key to key (again: stop)", "play", ("keys",), "play"),
    _key("MSLAnimPlayColorKeys", "Play color keys", "Playback over the keys of the current key's color", "play",
         ("color",), "play"),
    _key("MSLAnimPlayTwos", "Play on twos", "Playback every second frame (again: stop)", "play", (2,), "play"),
    _key("MSLAnimPlayThrees", "Play on threes", "Playback every third frame", "play", (3,), "play"),
    _key("MSLAnimPlayFours", "Play on fours", "Playback every fourth frame", "play", (4,), "play"),
    _key("MSLAnimTangentCycle", "Cycle match tangent", "Each curve's last key takes the first key's tangent",
         "tangents_scene.cycle", (), "tangent_cycle"),
    _key("MSLAnimCopyAnimation", "Copy animation", "The selection's keys (the highlighted span, else the animation "
         "range) to the clipboard and a file - another Maya pastes them too", "transfer_scene.copy_animation", (),
         "copy"),
    _key("MSLAnimPasteInsert", "Paste insert animation", "The copied animation from the current frame, the target "
         "cleared over that span", "transfer_scene.paste_insert", (), "paste"),
    _key("MSLAnimPasteReplace", "Paste replace animation", "The target's animation replaced by the copied one",
         "transfer_scene.paste_replace", (), "paste"),
    _key("MSLAnimCopyPose", "Copy pose", "The selection's Channel Box values on this frame to the clipboard and a "
         "file", "transfer_scene.copy_pose", (), "copy"),
    _key("MSLAnimPastePose", "Paste pose", "The copied pose onto the selection (keyed where auto key would)",
         "transfer_scene.paste_pose", (), "paste"),
    _key("MSLAnimMirrorPose", "Mirror pose", "The selected controls' pose onto their opposites (both sides "
         "selected swap; a highlighted span: its keys)", "mirror_scene.mirror_pose", (), "mirror_sides"),
    _key("MSLAnimMirrorToRight", "Mirror to right", "The right side takes the left side's pose",
         "mirror_scene.mirror_to_right", (), "mirror_to_right"),
    _key("MSLAnimMirrorToLeft", "Mirror to left", "The left side takes the right side's pose",
         "mirror_scene.mirror_to_left", (), "mirror_to_left"),
    _key("MSLAnimMirrorAllKeys", "Mirror all keys", "The whole animation onto the opposites",
         "mirror_scene.mirror_all_keys", (), "mirror_keys"),
    _key("MSLAnimSelectOpposite", "Select opposite", "The opposites of the selected controls selected instead",
         "mirror_scene.select_opposite", (), "select_all"),
    _key("MSLAnimSnapshotMirror", "Snapshot mirror settings", "The signs of the selected controls' channels kept "
         "as their axes are now (the rig in its default pose)", "mirror_scene.snapshot", (), "mirror_snapshot"),
    _key("MSLAnimAlignObjects", "Align objects", "The selected objects onto the last selected (a highlighted "
         "span: keyed on its key frames)", "align_scene.align", (), "align_objects"),
    _key("MSLAnimAlignAllKeys", "Align objects all keys", "The selected objects onto the last selected on every "
         "key frame of either", "align_scene.align_all_keys", (), "align_keys"),
    *(_key(f"MSLAnimAlign{name}{suffix}", f"Align objects {name.lower()}{title}", f"Only the {name.lower()} "
           f"of the selected objects onto the last selected{tip}", f"align_scene.{call}", (part,),
           "align_keys" if suffix else "align_objects")
      for part, name in (("translate", "Position"), ("rotate", "Orientation"), ("scale", "Scale"))
      for suffix, title, tip, call in (("", "", "", "align"),
                                       ("AllKeys", " all keys", " on every key frame of either", "align_all_keys"))),
    _key("MSLAnimTangentCycleFirst", "Cycle match tangent · first key", "Each curve's first key takes the last "
         "key's tangent", "tangents_scene.cycle", (True,), "tangent_cycle"),
    *(_key(f"MSLAnimTangent{name.title().replace('_', '')}", f"{title} tangent", tip, "tangents_scene.tangent",
           (name,), f"tangent_{name}")
      for name, title, tip in (
          ("best_guess", "Best guess", "Maya's own tangents picked by the keys (clamped on ends and extremes, auto "
                                       "between) on the keys in play"),
          ("polished", "Polished", "Smooth tangents without overshoot on the keys in play"),
          ("flow", "Flow", "Smooth tangents carrying the momentum through the keys in play"),
          ("bounce", "Bounce", "Sharp tangents pointing at the neighbor keys"),
          ("auto", "Auto", "Maya's auto tangents on the keys in play"),
          ("spline", "Spline", "Maya's spline tangents on the keys in play"),
          ("clamped", "Clamped", "Maya's clamped tangents on the keys in play"),
          ("linear", "Linear", "Maya's linear tangents on the keys in play"),
          ("flat", "Flat", "Maya's flat tangents on the keys in play"),
          ("step", "Step", "Maya's stepped out tangents on the keys in play"),
          ("plateau", "Plateau", "Maya's plateau tangents on the keys in play"))),
)

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
    *KEY_COMMANDS,
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
