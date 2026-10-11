# tools/maya/controls/quick.py
"""The Controls tool's actions for HOTKEYS: what its busiest buttons do, without the window.

Each function works on what is selected now. While the Controls window is open the call is handed to
its panel - the same handler as the button, said in the window's header. With the window closed the
action runs here with the settings the window was left with (sides, side color, the zero mode and its
group names, the channels taken and World / Local of TRANSFORMS) and says what it did in the viewport.
Registered as Maya runtime commands in tools/maya/hotkeys.py.
"""
from maya import cmds

from msl_tools.msl.core.resources import Resources

ALL_CHANNELS = ("tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz")


def _panel():
    """The open Controls window's panel, else None."""
    try:
        import msl_tools.msl.ui.qt_bindings as qt
        from msl_tools.msl.tools.maya.controls.window import ControlsWindow
        from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery
        main = MayaWindowQuery.get_maya_main_window()
        window = main.findChild(qt.QtWidgets.QWidget, ControlsWindow.OBJECT_NAME) if main is not None else None
        if isinstance(window, ControlsWindow) and window.isVisible():
            return window.panel
    except (ImportError, RuntimeError):
        pass
    return None


def _say(text: str) -> None:
    try:
        cmds.inViewMessage(assistMessage=text, position="topCenter", fade=True, fadeStayTime=1400)
    except RuntimeError:
        pass


def _settings():
    return Resources().configsMayaMng.get_config("controls", defaults={"settings": {}})["settings"]


def _sides():
    from msl_tools.msl.tools.maya.rename import rules
    saved = Resources().configsMayaMng.get_config("rename")["settings"]
    return rules.Sides.from_settings(saved.get("sides"))


def _channels() -> dict:
    """{channel: +1 / -1} as the TRANSFORMS grid was left (scale left out when it was never set)."""
    stored = dict(_settings().get("transform_channels") or {})
    taken = {}
    for attr in ALL_CHANNELS:
        state = stored.get(attr, "off" if attr[0] == "s" else "on")
        if state != "off":
            taken[attr] = -1 if state == "inv" else 1
    return taken


def _world() -> bool:
    return _settings().get("transform_space", "World") != "Local"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


def mirror() -> None:
    """The selected controls mirrored to the other side (across X): a copy is made, or the other
    side's shape is updated when that control is there."""
    panel = _panel()
    if panel is not None:
        panel._mirror_to_other("X")
        return
    from msl_tools.msl.tools.maya.controls import scene
    controls = scene.controls_in_selection()
    if not controls:
        _say("Select controls (curves) first")
        return
    made, updated, _alone = scene.mirror_controls(controls, _sides(), "X", bool(_settings().get("side_color", True)))
    _say(f"Mirrored {len(made)} · {_plural(updated, 'shape')} updated" if made or updated else "Nothing to mirror")


def zero() -> None:
    """The selected objects zeroed the way the window is set to: groups above them, or the
    offsetParentMatrix (Zero = None counts as groups)."""
    matrix = str(_settings().get("offsets", "Groups")).lower() == "matrix"
    panel = _panel()
    if panel is not None:
        if matrix:
            panel._zero_matrix()
        else:
            panel._zero_groups()
        return
    from msl_tools.msl.tools.maya.controls import scene
    targets = scene.selected_transforms()
    if not targets:
        _say("Select the controls to zero first")
    elif matrix:
        scene.zero_with_matrix(targets)
        _say(f"Zeroed {len(targets)} in the matrix")
    else:
        names = str(_settings().get("offset_names", "offset")).replace(",", " ").split() or ["offset"]
        scene.zero_with_groups(targets, names)
        _say(f"Zeroed {len(targets)} with {', '.join(names)}")


def select_controls() -> None:
    """Every control under the selection - with nothing selected, every control of the scene."""
    from msl_tools.msl.tools.maya.controls import scene
    roots = scene.selected_transforms()
    panel = _panel()
    if panel is not None:
        panel._select_controls(bool(roots))
        return
    found = scene.all_controls(roots or None)
    if found:
        cmds.select(found, replace=True)
    _say(f"Selected {_plural(len(found), 'control')}" if found else "No controls (curves) there")


def copy_pose() -> None:
    """The selected objects' pose onto the clipboard (as text: it is pasted in another Maya too)."""
    panel = _panel()
    if panel is not None:
        panel._on_pose_copy()
        return
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.tools.maya.controls import scene, transforms
    nodes = scene.selected_transforms()
    if not nodes:
        _say("Select objects first")
        return
    qt.QtWidgets.QApplication.clipboard().setText(transforms.pose_text(transforms.pose_of(nodes)))
    _say(f"The pose of {_plural(len(nodes), 'object')} is copied")


def paste_pose() -> None:
    """The pose on the clipboard onto the selection: the channels taken in TRANSFORMS, World / Local
    as it was left there."""
    panel = _panel()
    if panel is not None:
        panel._on_pose_paste()
        return
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.tools.maya.controls import scene, transforms
    text = qt.QtWidgets.QApplication.clipboard().text()
    pose = transforms.pose_from_text(text) if text and transforms.POSE_MARK in text[:200] else None
    nodes, channels = scene.selected_transforms(), _channels()
    if not pose:
        _say("No pose on the clipboard - copy one first")
    elif not nodes:
        _say("Select objects first")
    elif not channels:
        _say("No channel is taken in TRANSFORMS")
    else:
        done, _left, how = transforms.apply_pose(nodes, pose, channels, _world())
        _say(f"{done} got the pose" if how and done else "The pose fits none of the selected")


def match() -> None:
    """The selected objects put where the LAST selected one is (the channels taken in TRANSFORMS)."""
    panel = _panel()
    if panel is not None:
        panel._on_match()
        return
    from msl_tools.msl.tools.maya.controls import scene, transforms
    nodes, channels = scene.selected_transforms(), _channels()
    if len(nodes) < 2:
        _say("Select the objects, then the one to match them to")
    elif not channels:
        _say("No channel is taken in TRANSFORMS")
    else:
        done = transforms.match(nodes, channels, _world())[0]
        _say(f"{done} matched to {nodes[-1].rpartition('|')[2]}" if done else "Already matched")


def reset() -> None:
    """The taken channels of the selected objects back to rest (0, scale 1)."""
    panel = _panel()
    if panel is not None:
        panel._on_reset_pick()
        return
    from msl_tools.msl.tools.maya.controls import scene, transforms
    nodes, channels = scene.selected_transforms(), _channels()
    if not nodes:
        _say("Select objects first")
    elif not channels:
        _say("No channel is taken in TRANSFORMS")
    else:
        done = transforms.reset(nodes, channels)[0]
        _say(f"{_plural(done, 'channel')} back to rest")
