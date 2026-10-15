# tools/maya/scripts/viewport.py
"""What a viewport shows, for a key — the user's old MSLtoggle Joints, made one for every kind.

`toggle(flag)`: one kind of object (a modelEditor flag: "joints", "nurbsCurves", ...) shown <-> hidden
    in the viewport under the pointer (else the one with the focus). With SHIFT held: in every
    viewport, all set as the one under the pointer goes (so they end alike).
`geometry_only()`: everything but the geometry hidden; again = back to exactly what each viewport
    showed before (not "everything on"). Shift: every viewport. The viewport's own helpers (grid,
    manipulators, selection highlighting) and plug-in shapes (the MSL shot mask, Labels) are left
    as they are.

The kinds and their names are Playblast's (playblast/capture.py VISIBILITY_GROUPS). What a viewport
shows is a view setting: nothing reaches the undo queue. Said in the viewport ("Joints: hidden").
"""
from maya import cmds

from msl_tools.msl.tools.maya.playblast.capture import VISIBILITY_GROUPS, VISIBILITY_LABELS

GEOMETRY = ("polymeshes", "nurbsSurfaces", "subdivSurfaces")
LEFT_ALONE = ("grid", "manipulators", "selectionHiliteDisplay", "pluginShapes")
OBJECT_KINDS = tuple(flag for _group, entries in VISIBILITY_GROUPS for flag, _label in entries
                     if flag not in LEFT_ALONE)
_before = {}      # model panel -> {flag: shown} before geometry_only()


def _shift() -> bool:
    try:
        return bool(cmds.getModifiers() & 1)
    except RuntimeError:
        return False


def _panel() -> str:
    """The model panel under the pointer, else the focused one; "" = none."""
    for panel in (cmds.getPanel(underPointer=True), cmds.getPanel(withFocus=True)):
        if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
            return panel
    return ""


def _panels(everywhere: bool, first: str) -> list:
    if not everywhere:
        return [first] if first else []
    panels = [panel for panel in cmds.getPanel(type="modelPanel") or []
              if cmds.modelEditor(panel, query=True, exists=True)]
    return ([first] if first in panels else []) + [panel for panel in panels if panel != first]


def toggle(flag: str) -> None:
    """One kind shown <-> hidden (see the module)."""
    everywhere = _shift()
    first = _panel()
    panels = _panels(everywhere, first)
    if not panels:
        _say("Put the pointer over a viewport")
        return
    shown = not cmds.modelEditor(panels[0], query=True, **{flag: True})
    for panel in panels:
        cmds.modelEditor(panel, edit=True, **{flag: shown})
    where = " in every viewport" if everywhere else ""
    _say(f"{VISIBILITY_LABELS.get(flag, flag)}: {'shown' if shown else 'hidden'}{where}")


def geometry_only() -> None:
    """Only the geometry shown <-> back to what was shown (see the module)."""
    everywhere = _shift()
    first = _panel()
    panels = _panels(everywhere, first)
    if not panels:
        _say("Put the pointer over a viewport")
        return
    if any(panel in _before for panel in panels):        # in "only geometry" now: back
        for panel in panels:
            state = _before.pop(panel, None)
            if state:
                cmds.modelEditor(panel, edit=True, **state)
        _say("Back to what the viewport showed" + (" (every viewport)" if everywhere else ""))
        return
    for panel in panels:
        _before[panel] = {flag: cmds.modelEditor(panel, query=True, **{flag: True}) for flag in OBJECT_KINDS}
        cmds.modelEditor(panel, edit=True, **{flag: flag in GEOMETRY for flag in OBJECT_KINDS})
    _say("Only geometry" + (" in every viewport" if everywhere else "") + " - again to get the rest back")


# for the hotkeys (a runtime command calls a function without arguments)
def toggle_curves() -> None:
    toggle("nurbsCurves")


def toggle_polygons() -> None:
    toggle("polymeshes")


def toggle_joints() -> None:
    toggle("joints")


def toggle_locators() -> None:
    toggle("locators")


def _say(text: str) -> None:
    print("MSL " + text)
    try:
        cmds.inViewMessage(assistMessage=text, position="topCenter", fade=True, fadeStayTime=1000)
    except RuntimeError:
        pass
