# tools/maya/animation/space_menu.py
"""The SPACE SWITCHER's menu (Qt): what space_scene finds, as a menu at the pointer - a line per switch, and in it
"THIS FRAME" and "ALL KEYS" with the switch's values (the one it has now ticked); the rotate order has ALL KEYS only,
each order with its rating ("yxz · Best"). A pick switches with the control kept in place. The window's buttons and
the hotkeys both open it (`popup`)."""
from __future__ import annotations

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.animation import space_scene as ss
from msl_tools.msl.ui.theme.qss import make_rounded_popup


def _menu(parent) -> "qt.QtWidgets.QMenu":
    menu = make_rounded_popup(qt.QtWidgets.QMenu(parent))
    menu.setToolTipsVisible(True)
    return menu


def _submenu(menu, title: str) -> "qt.QtWidgets.QMenu":
    """A submenu kept by its parent menu (one made by addMenu(title) is deleted with its Python name)."""
    sub = _menu(menu)
    sub.setTitle(title)
    menu.addMenu(sub)
    kept = getattr(menu, "_kept", [])
    kept.append(sub)
    menu._kept = kept
    return sub


def _caption(menu, text: str) -> None:
    item = menu.addAction(text)
    item.setEnabled(False)


def build(parent, asset: bool, say) -> "qt.QtWidgets.QMenu":
    """The menu of the selection's switches (`asset`: of every control of its rig, no rotate orders); `say(do)`
    runs a pick and shows what it said."""
    menu = _menu(parent)
    if asset:
        name, switches = ss.asset_switches()
        _caption(menu, f"{name.upper() or 'NOTHING SELECTED'} · {len(switches)} switch{'es' if len(switches) != 1 else ''}")
    else:
        switches = ss.selection_switches()
        _caption(menu, "SELECTION" if switches else "NOTHING TO SWITCH ON THE SELECTION")
    for switch in switches:
        sub = _submenu(menu, switch.title)
        if switch.attribute == ss.ROTATE_ORDER:
            _caption(sub, "ALL KEYS")
            try:
                ratings = ss.rate(switch.node)
            except Exception:
                ratings = {}
            for index, order in enumerate(switch.names):
                rating = ratings.get(order, "")
                item = sub.addAction(f"{order}  ·  {rating}" if rating else order,
                                     lambda n=switch.node, i=index: say(lambda: ss.rotate_order(n, i)))
                item.setCheckable(True)
                item.setChecked(index == switch.current)
                item.setToolTip("The turn kept on every key of the control; the order itself is not keyed")
            continue
        for title, every in (("THIS FRAME", False), ("ALL KEYS", True)):
            if every:
                sub.addSeparator()
            _caption(sub, title)
            for index, value in enumerate(switch.names):
                item = sub.addAction(value, lambda n=switch.node, a=switch.attribute, i=index, e=every:
                                     say(lambda: ss.switch(n, a, i, e)))
                item.setCheckable(True)
                item.setChecked(index == switch.current)
                item.setToolTip("Kept in place on every key of the control, keyed there" if every else
                                "Kept in place on this frame (auto key: keyed)")
    return menu


def popup(asset: bool = False, say: bool = True) -> str:
    """For hotkeys: the menu at the pointer - over the Animation window when it is open (its look), else over Maya's
    own window with our stylesheet; what a pick did is said in the viewport."""
    from msl_tools.msl.tools.maya.animation import keys_scene
    from msl_tools.msl.ui.theme import StylesheetBuilder
    from msl_tools.msl.ui.ui_resources import UiResources
    from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery

    def say(do):
        try:
            keys_scene._done(do(), True)
        except Exception as error:
            keys_scene._done(str(error), True)

    menu = build(MayaWindowQuery.get_maya_main_window(), asset, say)
    menu.setStyleSheet(StylesheetBuilder.build(UiResources().themeManager.current_theme))
    menu.exec(qt.QtGui.QCursor.pos())
    return ""


def popup_asset(say: bool = True) -> str:
    return popup(True, say)
