# tools/maya/scripts/rig.py
"""Locators and joints on the selection, for a key: the Controls tool's own functions
(controls/scene.py `locators_on_selection` / `joints_on_selection` — the same as its buttons, with
their defaults: each locator turned like its object, joints as a chain), said in the viewport."""
from maya import cmds


def locators() -> None:
    """A locator on each selected object and each selected vertex / edge / face."""
    from msl_tools.msl.tools.maya.controls import scene
    made, total = scene.locators_on_selection()
    _said(made, total, "locator")


def locator_in_middle() -> None:
    """ONE locator in the middle of everything selected."""
    from msl_tools.msl.tools.maya.controls import scene
    made, total = scene.locators_on_selection(center=True)
    _said(made, total, "locator")


def joints() -> None:
    """A joint chain through the selection, in the order picked."""
    from msl_tools.msl.tools.maya.controls import scene
    made, total = scene.joints_on_selection()
    _said(made, total, "joint")


def _said(made: list, total: int, word: str) -> None:
    if not made:
        text = f"Select objects or vertices / edges / faces for a {word} first"
    else:
        text = f"{len(made)} {word}{'s' if len(made) != 1 else ''} made"
        if total > len(made) and word == "locator" and len(made) > 1:
            text += f" - the first {len(made)} of {total}"
    print("MSL " + text)
    try:
        cmds.inViewMessage(assistMessage=text, position="topCenter", fade=True, fadeStayTime=1400)
    except RuntimeError:
        pass
