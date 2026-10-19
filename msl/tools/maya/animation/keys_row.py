# tools/maya/animation/keys_row.py
"""The Animation tool's KEYS row: keys and timing in one line under the sliders —

    ◀ [N] ▶   nudge by N frames (right click: all keys of the selection, the whole scene, time offset)
    then six GROUP buttons, each showing the action used last: a click repeats it, the corner, a right
    click or holding it opens the group (a pick runs it and becomes the button) —
        inbetweens · key times · bake · clean up · color keys · play

What each action does and acts on: keys_scene.py (one undo step each). The row only says what happened
(`said(text, state)` -> the window's header) and keeps its choices in the panel's settings
(`frames`, `keys_last`).
"""
from __future__ import annotations

from dataclasses import dataclass

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
from msl_tools.msl.tools.maya.animation import keys as ky
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField
from msl_tools.msl.tools.maya.rename.buttons import GroupButton, QuickButton
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources

N = "N"     # stands for the frames field's number in an action's arguments


@dataclass(frozen=True)
class Action:
    key: str
    title: str
    tip: str
    icon: str
    call: str           # keys_scene's function
    args: tuple = ()


GROUPS = (
    ("inbetween", "Inbetweens", "teal", (
        Action("insert", "Insert inbetween", "N empty frames after the current frame - or after each picked key, or "
               "after every key in the highlighted range", "keys_insert", "inbetween", (N,)),
        Action("remove", "Remove inbetween", "N frames taken out after the current frame (the picked keys, the "
               "range's keys) - never past the key before", "keys_remove", "inbetween", ("-N",)),
        Action("insert_scene", "Insert inbetween · scene", "N empty frames after the current frame, on every curve "
               "of the scene", "keys_insert", "inbetween", (N, True)),
        Action("remove_scene", "Remove inbetween · scene", "N frames taken out after the current frame, on every "
               "curve of the scene", "keys_remove", "inbetween", ("-N", True)),
        Action("space", "Space the keys N apart", "The picked keys (or the range's) laid out N frames apart from the "
               "first one - the keys after them stay", "keys_space", "set_spacing", (N,)),
    )),
    ("times", "Key times", "blue", (
        Action("share", "Share key times", "Every curve of the selected objects gets a key wherever any of them has "
               "one - the shape kept", "keys_share", "share_times", ()),
        Action("share_last", "Share from the last selected", "The others get a key wherever the object selected "
               "LAST has one", "keys_share", "share_times", (True,)),
        Action("copy", "Copy key times", "Keep the key times in play (picked, the range's, else the selection's) "
               "to paste them", "copy", "copy_times", ()),
        Action("paste_merge", "Paste key times · merge", "Keys at the copied times, the selection's own stay",
               "paste", "paste_times", (ky.MERGE,)),
        Action("paste_replace", "Paste key times · replace", "Keys at the copied times; keys inside their span on "
               "other frames go", "paste", "paste_times", (ky.REPLACE,)),
        Action("paste_insert", "Paste key times · at the current frame", "Replace, with the first copied time on "
               "the current frame", "paste", "paste_times", (ky.INSERT,)),
    )),
    ("bake", "Bake", "violet", (
        Action("ones", "Bake on ones", "A key on every frame (picked span / range / the animation range)",
               "keys_bake", "bake", (1,)),
        Action("twos", "Bake on twos", "A key every 2 frames, the keys between go", "keys_bake", "bake", (2,)),
        Action("threes", "Bake on threes", "A key every 3 frames", "keys_bake", "bake", (3,)),
        Action("fours", "Bake on fours", "A key every 4 frames", "keys_bake", "bake", (4,)),
        Action("every", "Bake every N frames", "A key every N frames (the number field)", "keys_bake", "bake",
               (N,)),
        Action("infinity", "Bake infinity", "A cycling curve's infinity made real keys in the highlighted range "
               "(else the playback range), then constant", "infinity", "bake_infinity", ()),
    )),
    ("clean", "Clean up", "orange", (
        Action("snap", "Smart snap", "Keys between frames to the nearest whole frame, holding the pose there",
               "snap_grid", "smart_snap", ()),
        Action("redundant", "Remove redundant keys", "Keys that don't change the curve", "sweep",
               "remove_redundant", ()),
        Action("static", "Remove static curves", "Curves that hold one value all along (the value stays)",
               "minus", "remove_static", ()),
        Action("crop", "Crop to the range", "Keys outside the highlighted range (or the picked keys' span) go, "
               "the motion inside kept", "crop", "crop", ()),
        Action("reverse", "Reverse", "The animation backwards inside the picked span / the range / the playback "
               "range", "reverse", "reverse", ()),
        Action("clear", "Clear animation", "Every curve of the selected objects deleted (the pose stays)",
               "clear", "clear", ()),
    )),
    ("color", "Color keys", "red", (
        Action("red", "Tint red", "Plain keys - the poses (Maya's own key flags, nothing added)", "keyframe",
               "tint", (ky.RED,)),
        Action("yellow", "Tint yellow", "Breakdowns, inbetweens (Maya's special tick)", "keyframe", "tint",
               (ky.YELLOW,)),
        Action("green", "Tint green", "Baked keys (Maya's breakdown key: it keeps its place between its "
               "neighbors when they move)", "keyframe", "tint", (ky.GREEN,)),
        Action("remove_red", "Remove red keys", "Every red key of the selection", "clear", "remove_color",
               (ky.RED,)),
        Action("remove_yellow", "Remove yellow keys", "Every yellow key of the selection", "clear",
               "remove_color", (ky.YELLOW,)),
        Action("remove_green", "Remove green keys", "Every green key of the selection", "clear", "remove_color",
               (ky.GREEN,)),
    )),
    ("play", "Play", "green", (
        Action("keys", "Play keys", "Playback from key to key, each pose held until the next (again: stop)",
               "play", "play", ("keys",)),
        Action("color_keys", "Play color keys", "Only the keys of the color the current frame's key has",
               "play", "play", ("color",)),
        Action("twos", "Play on twos", "Every second frame, held for two", "play", "play", (2,)),
        Action("threes", "Play on threes", "Every third frame", "play", "play", (3,)),
        Action("fours", "Play on fours", "Every fourth frame", "play", "play", (4,)),
    )),
)

REFUSED = ("Nothing", "Not ", "Copy key times first", "Pick ", "Highlight", "Select ", "Bake every", "No cycling",
           "No key on that side", "No key of that color")
TONE_OF_COLOR = {ky.RED: "red", ky.YELLOW: "yellow", ky.GREEN: "green"}


def run(call: str, args: tuple, frames: float, say: bool = False) -> str:
    """One keys_scene function with N filled in."""
    from msl_tools.msl.tools.maya.animation import keys_scene
    values = [frames if a == N else -frames if a == "-N" else a for a in args]
    return getattr(keys_scene, call)(*values, say=say)


class KeysRow(qt.QtWidgets.QWidget):
    """The KEYS row. Signals: said(text, state) - what an action did ("done" / "error")."""

    said = qt.QtCore.Signal(str, str)

    # the color keys' own colors in the group's menu (QSS: animation.qss)
    redColor = color_property("_red", None)
    yellowColor = color_property("_yellow", None)
    greenColor = color_property("_green", None)

    def __init__(self, get, put, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()
        self._red = qt.QtGui.QColor(fallback.tokens.get("error", "#d9534f"))
        self._yellow = qt.QtGui.QColor(fallback.tokens.get("yellow", "#e0b84a"))
        self._green = qt.QtGui.QColor(fallback.tokens.get("success", "#4caf50"))
        self._get, self._put = get, put
        icons = UiResources().iconManager
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self._left = self._nudge_button(icons, -1)
        self.frames = DragNumberField(float(get("frames", 1.0)), 0.1, 1000.0, 1.0, width=36, decimals=1)
        self.frames.setObjectName("animationFrames")
        self.frames.setToolTip("Frames\nHow many frames a nudge, an inbetween, the spacing and \"bake every N\" use. "
                               "Wheel / Up / Down step it, a middle-drag scrubs it.")
        self.frames.value_changed.connect(lambda value: self._put("frames", float(value)))
        self._right = self._nudge_button(icons, 1)
        for widget in (self._left, self.frames, self._right):
            layout.addWidget(widget)
        layout.addSpacing(6)
        self._groups = {}
        for group, title, tone, actions in GROUPS:
            button = GroupButton(tone, icon_size=16)
            button.setObjectName("animationGroup")
            button.setFixedSize(30, 24)
            button.run_requested.connect(lambda g=group: self._run(g, self._last(g)))
            button.menu_requested.connect(lambda g=group: self._menu(g))
            self._groups[group] = button
            layout.addWidget(button)
            self._show_group(group)
        layout.addStretch(1)

    # ------------------------------------------------------------------ nudge

    def _nudge_button(self, icons, direction: int) -> QuickButton:
        side = "left" if direction < 0 else "right"
        button = QuickButton(icons.get_icon(f"key_nudge_{side}", sub_folder="actions"), "◀" if direction < 0 else "▶",
                             f"Nudge {side}\nThe keys in play N frames {side}: the picked keys, the range's, or the "
                             f"current frame's (the time follows; on an empty frame the nearest key comes to it). "
                             f"Right click: all keys of the selection, the whole scene, or slide the motion under "
                             f"the keys.", icon_size=16)
        button.setObjectName("animationNudge")
        button.setFixedSize(24, 24)
        button.clicked.connect(lambda: self._nudge(direction, ""))
        button.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(lambda _pos, b=button: self._nudge_menu(b, direction))
        return button

    def _nudge(self, direction: int, reach: str) -> None:
        frames = self.frames.value() * direction
        if reach == "offset":
            self._say(lambda: run("time_offset", (-frames,), 0))
        else:
            self._say(lambda: run("nudge", (frames, reach), 0))

    def _nudge_menu(self, button, direction: int) -> None:
        from msl_tools.msl.ui.icon_manager import tinted_menu_icon
        side = "left" if direction < 0 else "right"
        icons = UiResources().iconManager
        menu = self._new_menu()
        for reach, title, tip, icon in (
                ("", f"Nudge {side}", "The keys in play", f"key_nudge_{side}"),
                ("all", f"All keys {side}", "Every key of the selected objects (the time follows)", "keys_share"),
                ("scene", f"Scene {side}", "Every key in the scene", "scene"),
                ("offset", f"Slide the motion {side}", "The keys stay where they are; the motion moves under them "
                 "by N frames", "timeline")):
            picture = tinted_menu_icon(icons.get_icon(icon, sub_folder="actions"), button._icon_color,
                                       self.devicePixelRatioF(), side=18)
            action = menu.addAction(picture, title, lambda r=reach: self._nudge(direction, r))
            action.setToolTip(tip)
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height() + 2)))

    # ------------------------------------------------------------------ the groups

    def _actions(self, group: str) -> tuple:
        return next(actions for g, _t, _tone, actions in GROUPS if g == group)

    def _last(self, group: str) -> Action:
        actions = self._actions(group)
        chosen = (self._get("keys_last", {}) or {}).get(group)
        return next((a for a in actions if a.key == chosen), actions[0])

    def _show_group(self, group: str) -> None:
        action = self._last(group)
        button = self._groups[group]
        button.set_source_icon(UiResources().iconManager.get_icon(action.icon, sub_folder="actions"))
        title = next(t for g, t, _tone, _a in GROUPS if g == group)
        button.setToolTip(f"{action.title}\n{action.tip}\n{title}: right click (or the corner) for the others.")
        if group == "color":
            tone = TONE_OF_COLOR.get(action.args[0], "red")
            if button.property("tone") != tone:
                button.setProperty("tone", tone)
                repolish(button)

    def _menu(self, group: str) -> None:
        from msl_tools.msl.ui.icon_manager import tinted_menu_icon
        button = self._groups[group]
        button.setDown(False)
        last = self._last(group)
        icons = UiResources().iconManager
        menu = self._new_menu()
        for action in self._actions(group):
            color = button._icon_color
            if group == "color":
                color = self._color_of(action)
            icon = tinted_menu_icon(icons.get_icon(action.icon, sub_folder="actions"), color, self.devicePixelRatioF(),
                                    side=18)
            item = menu.addAction(icon, action.title + ("\tlast" if action is last else ""),
                                  lambda a=action: self._pick(group, a))
            item.setToolTip(action.tip)
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height() + 2)))

    def _color_of(self, action: Action) -> "qt.QtGui.QColor":
        return {ky.RED: self._red, ky.YELLOW: self._yellow, ky.GREEN: self._green}[action.args[0]]

    def _pick(self, group: str, action: Action) -> None:
        last = dict(self._get("keys_last", {}) or {})
        last[group] = action.key
        self._put("keys_last", last)
        self._show_group(group)
        self._run(group, action)

    def _run(self, group: str, action: Action) -> None:
        self._say(lambda: run(action.call, action.args, self.frames.value()))

    # ------------------------------------------------------------------ helpers

    def _new_menu(self) -> "qt.QtWidgets.QMenu":
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setToolTipsVisible(True)
        return menu

    def _say(self, do) -> None:
        try:
            text = do()
        except Exception as error:     # outside Maya, or Maya refused
            self.said.emit(str(error), "error")
            return
        if text.startswith(REFUSED):
            state = "error"
        elif text.startswith(("No ", "Every key is", "Playback stopped")):
            state = ""
        else:
            state = "done"
        self.said.emit(text, state)
