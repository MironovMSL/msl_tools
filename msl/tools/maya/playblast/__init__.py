# tools/maya/playblast/__init__.py
"""Playblast: what the viewport shows as a video (or frames), made by our own
ffmpeg chain — a window of ours inside Maya 2025+.

    naming.py    folder and file name with {tokens} (no Qt, no Maya)
    capture.py   the Maya side: cameras, ranges, sizes, the timeline's sound, the capture itself (no Qt)
    panel.py     PlayblastPanel, the tool's widget
    window.py    PlayblastWindow, our frameless window around the panel
    playblast.qss

Nothing is imported here until the tool is opened: the menu refers to
`launcher_entry_point` by name only.
"""

CONTROL_NAME = "mslPlayblastPanel"
CONTROL_LABEL = "MSL Playblast"
RESTORE_SCRIPT = "from msl_tools.msl.tools.maya.playblast import restore; restore()"


def launcher_entry_point():
    """Opens the playblast window (the MSL menu's entry). Returns the window; its `panel` is the tool."""
    from msl_tools.msl.tools.maya.playblast.window import PlayblastWindow
    return PlayblastWindow.open()


def repeat_last():
    """Playblasts again with the settings used last — for a hotkey (tools/maya/hotkeys.py). The
    window is opened if it is closed: it is where the progress shows and where Cancel is."""
    window = launcher_entry_point()
    window.panel.start()
    return window


def toggle_mask() -> bool:
    """Shows the shot mask if it is hidden and hides it if it is shown — for a hotkey. With the
    window closed the mask of the saved settings is used. Returns True if it is shown now."""
    from msl_tools.msl.tools.maya.playblast.window import PlayblastWindow
    window = PlayblastWindow.find()
    if window is None:
        window = launcher_entry_point()
    window.panel.toggle_mask()
    from msl_tools.msl.tools.maya.playblast import mask
    return mask.is_shown()


def _panel():
    from msl_tools.msl.tools.maya.playblast.panel import PlayblastPanel
    return PlayblastPanel()


def open_docked():
    """The same tool as a Maya PANEL that docks among Maya's own (ui/windows/maya_dock.py).
    Kept for later — the menu opens the window. Returns the panel."""
    from msl_tools.msl.ui.windows.maya_dock import MayaDock
    return MayaDock.show(CONTROL_NAME, CONTROL_LABEL, _panel, restore_script=RESTORE_SCRIPT, width=380, height=560)


def restore():
    """Run by Maya (a panel's uiScript) when it rebuilds a layout that holds the docked panel.
    A layout saved while the tool WAS a panel still names it: unless the docked form was opened
    in this session, that left-over panel is removed instead of filled."""
    from msl_tools.msl.ui.windows.maya_dock import MayaDock
    if MayaDock.wanted(CONTROL_NAME):
        return MayaDock.fill(CONTROL_NAME, _panel)
    from maya import cmds
    cmds.evalDeferred(lambda: cmds.workspaceControl(CONTROL_NAME, exists=True) and cmds.deleteUI(CONTROL_NAME))
    return None
