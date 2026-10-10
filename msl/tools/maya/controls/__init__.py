# tools/maya/controls/__init__.py
"""Controls: making rig controls and working on them — a window of ours inside Maya 2025+.

    shapes.py     control shapes as data: the built-in ones (drawn by code), the user's library,
                  the B-spline a preview draws (no Qt, no Maya)
    naming.py     a control's name from what it is made for (no Qt, no Maya; Rename's sides)
    scene.py      the Maya side: build, place, offsets (groups / offsetParentMatrix), shape edits
    preview.py    thumbnails and the turning preview, drawn by Qt from the points
    ghost.py      what Create would make, shown in Maya's viewport on the selected objects
    panel.py      ControlsPanel (cards that fold: CONTROL…), window.py ControlsWindow
    controls.qss

Nothing is imported here until the tool is opened: the menu refers to `launcher_entry_point`
by name only.
"""


def launcher_entry_point():
    """Opens the Controls window (the MSL menu's entry). Returns the window; its `panel` is the tool."""
    from msl_tools.msl.tools.maya.controls.window import ControlsWindow
    return ControlsWindow.open()
