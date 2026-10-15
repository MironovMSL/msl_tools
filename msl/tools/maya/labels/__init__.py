# tools/maya/labels/__init__.py
"""Labels: attribute values shown live in Maya's viewport — a tool of ours inside Maya 2025+.

    layout.py   what a set of labels IS: a layout of columns of lines, as plain data that goes to
                and from JSON; namespaces, mirroring, checks (no Qt, no Maya)
    scene.py    the Maya side: a layout built into the scene as mslLabels nodes (one undo step),
                read back from the scene, removed
    sketch.py   ViewportSketch: the picture, small, with the HUD columns where they stand (drag them)
    panel.py    LabelsPanel (cards: VIEWPORT, COLUMNS, LINES, LINE), window.py LabelsWindow
    labels.qss

Nothing is imported here until the tool is opened: the menu refers to `launcher_entry_point`
by name only. The nodes are drawn by the plug-in maya_module/plug-ins/msl_labels.py.
"""


def launcher_entry_point():
    """Opens the Labels window (the MSL menu's entry). Returns the window; its `panel` is the tool."""
    from msl_tools.msl.tools.maya.labels.window import LabelsWindow
    return LabelsWindow.open()


def toggle():
    """Shows or hides every set of labels built in the scene (one undo step) — for a hotkey: all
    of them hidden when any is shown, else all shown."""
    from maya import cmds
    from msl_tools.msl.tools.maya.labels import scene
    groups = scene.rigs()
    if not groups:
        cmds.inViewMessage(amg="MSL Labels: none in this scene", pos="topCenter", fade=True)
        return
    shown = any(cmds.getAttr(group + ".visibility") for group in groups)
    cmds.undoInfo(openChunk=True, chunkName=scene.UNDO_NAME)
    try:
        for group in groups:
            if not cmds.getAttr(group + ".visibility", lock=True):
                cmds.setAttr(group + ".visibility", not shown)
    finally:
        cmds.undoInfo(closeChunk=True)
