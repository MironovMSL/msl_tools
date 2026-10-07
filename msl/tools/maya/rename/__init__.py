# tools/maya/rename/__init__.py
"""Rename: quick naming of Maya objects — a window of ours inside Maya 2025+.

    rules.py       what a rename does to names: the template and its tokens, case, parts,
                   sides, kinds, checks (no Qt, no Maya)
    library.py     the words names are built of: categories, favorites, names used last (no Qt)
    operations.py  what a click would do, as a value (no Qt)
    scene.py       the Maya side: which objects, what they are, the rename as one undo step
    panel.py       RenamePanel (+ panel_words / panel_find / panel_objects), window.py RenameWindow
    rename.qss

Nothing is imported here until the tool is opened: the menu refers to `launcher_entry_point`
by name only.
"""


def launcher_entry_point():
    """Opens the rename window (the MSL menu's entry). Returns the window; its `panel` is the tool."""
    from msl_tools.msl.tools.maya.rename.window import RenameWindow
    return RenameWindow.open()


def repeat_last():
    """The last rename again on what is selected now — for a hotkey. Opens the window if it is
    closed: the list and the outcome show there."""
    window = launcher_entry_point()
    window.panel.repeat_last()
    return window
