# tools/maya/animation/panel.py
"""The Animation tool's panel: two sliders that are pulled, not set —
    POSE   where the keys go: Tweener, Blend to Neighbors / Default / Frame / Infinity / Undo
    CURVE  the shape of the keys: Pull | Push, Scale From ..., Smooth | Rough, Ease, Time Offset,
           Noise | Wave, Connect to Neighbors
— each with the mode it is on (a click on the name, or a right click on the slider, picks another;
held modifiers switch it for one drag: Shift = Blend to Neighbors / Smooth | Rough, ...), the frame
the "Frame" modes go to, and a line saying what the sliders act on now (Graph Editor keys, the
timeline's range, the current frame). A drag changes the curves live and ends as ONE undo step;
Esc during it puts everything back.

Settings: configsMayaMng "animation" (`settings`: pose, curve, overshoot, euler, frame).
"""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.animation import curves as cv
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField
from msl_tools.msl.tools.maya.rename.buttons import ToggleIconButton
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.sliders import BlendSlider
from msl_tools.msl.ui.widgets.compositions.option_menu import OptionMenu

StylesheetBuilder.register_template(Path(__file__).with_name("animation.qss"))

WATCH_MS = 500           # how often the line "what the sliders act on" is read while on screen
OVERSHOOT = 2.0          # the weight at a slider's end with overshoot on
FRAME_MODES = ("frame", "scale_frame")
MODE_WIDTH = 116          # the mode button; a longer name is cut short (the whole one in its tooltip)
KEYS_MS = 50             # how often the held keys are read while the pointer is over a slider


class _SliderRow(qt.QtWidgets.QWidget):
    """A slider of one family with the button that names (and picks) its mode."""

    picked = qt.QtCore.Signal(str)        # a mode was picked for this slider

    def __init__(self, family: str, parent=None):
        super().__init__(parent)
        self.family = family
        self.modes = cv.POSE_MODES if family == cv.POSE else cv.CURVE_MODES
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.button = qt.QtWidgets.QPushButton()
        self.button.setObjectName("animationMode")
        self.button.setProperty("tone", family)
        self.button.setFixedWidth(MODE_WIDTH)
        self.button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.slider = BlendSlider(to_weight=cv.weight_at, to_position=cv.position_of)
        self.slider.setProperty("tone", family)
        layout.addWidget(self.button)
        layout.addWidget(self.slider, 1)
        self.button.clicked.connect(lambda: self._menu(self.button.mapToGlobal(
            qt.QtCore.QPoint(0, self.button.height()))))
        self.slider.menu_requested.connect(self._menu)
        self.mode = self.modes[0]
        self._shown = self.mode
        # while the pointer is over the slider, the keys held now pick the mode it shows - so it
        # says what a press WOULD do before the click (the keyboard is read: the slider has no focus)
        self._keys = qt.QtCore.QTimer(self)
        self._keys.setInterval(KEYS_MS)
        self._keys.timeout.connect(self._follow_keys)
        self.slider.installEventFilter(self)

    def set_mode(self, key: str) -> None:
        self.mode = cv.BY_KEY.get(key) if key in cv.BY_KEY and cv.BY_KEY[key].family == self.family \
            else self.modes[0]
        self.show_mode(self.mode)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.slider:
            if event.type() == qt.QtCore.QEvent.Type.Enter:
                self._follow_keys()
                self._keys.start()
            elif event.type() == qt.QtCore.QEvent.Type.Leave:
                self._keys.stop()
                if not self.slider.is_dragging():
                    self.show_mode(self.mode)
        return super().eventFilter(watched, event)

    def held_mode(self) -> cv.Mode:
        """The mode a press would use now: the one the held keys switch to, else the picked one."""
        modifiers = qt.QtGui.QGuiApplication.queryKeyboardModifiers()
        names = "+".join(name for flag, name in ((qt.QtCore.Qt.KeyboardModifier.ControlModifier, "ctrl"),
                                                 (qt.QtCore.Qt.KeyboardModifier.AltModifier, "alt"),
                                                 (qt.QtCore.Qt.KeyboardModifier.ShiftModifier, "shift"))
                         if modifiers & flag)
        return cv.mode_for_modifiers(self.family, names) or self.mode

    def _follow_keys(self) -> None:
        if self.slider.is_dragging():
            return
        mode = self.held_mode()
        if mode is not self._shown:
            self.show_mode(mode)

    def show_mode(self, mode: cv.Mode) -> None:
        """What the row shows: the picked mode, or the one the held keys switch to (the button then
        says so in the slider's color)."""
        self._shown = mode
        held = mode is not self.mode
        if bool(self.button.property("held")) != held:
            self.button.setProperty("held", held)
            repolish(self.button)
        room = MODE_WIDTH - 30         # the padding, the colored edge and the arrow
        title = self.button.fontMetrics().elidedText(mode.title, qt.QtCore.Qt.TextElideMode.ElideRight, room)
        self.button.setText(f"{title}  ▾")
        self.button.setToolTip(f"{mode.title}\n{mode.tip}\nLeft: {mode.left} · right: {mode.right}")
        self.slider.set_label(mode.short)
        self.slider.set_marks(mode.marks)
        self.slider.setToolTip(f"{mode.title}\nDrag left: {mode.left}, right: {mode.right}. A click on a mark "
                               f"goes straight there. Hold a key while pressing for another mode; right click: "
                               f"every mode. Esc while dragging puts it back.")
        self.slider.format_weight = lambda weight, m=mode: cv.weight_text(m, weight)

    def _menu(self, position) -> None:
        """Every mode of this slider, each with a line saying what its two sides do and the key that
        switches to it for one drag; the full explanation in the row's tooltip."""
        menu = OptionMenu(self)
        menu.add_caption("POSE SLIDER · where the keys go" if self.family == cv.POSE
                         else "CURVE SLIDER · the shape of the keys")
        for mode in self.modes:
            chip = qt.QtWidgets.QLabel(mode.short)
            chip.setObjectName("animationModeChip")
            chip.setProperty("tone", self.family)
            chip.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
            title = mode.title + (f"   ·   hold {mode.modifier}" if mode.modifier else "")
            action = menu.add_option(title, f"← {mode.left}   ·   {mode.right} →", chip,
                                     checked=mode.key == self.mode.key)
            action.defaultWidget().setToolTip(f"{mode.title}\n{mode.tip}")
            action.triggered.connect(lambda _checked=False, key=mode.key: self.picked.emit(key))
        menu.exec(position)


class AnimationPanel(qt.QtWidgets.QWidget):
    """The tool (shown in an AnimationWindow).

    Signals:
        status_changed(str, str) — what the panel says (text, "" / "done" / "error"): the header.
    """

    status_changed = qt.QtCore.Signal(str, str)

    menuIconColor = color_property("_menu_icon", None)

    TOOL_NAME = "animation"

    def __init__(self, parent=None):
        super().__init__(parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        self._menu_icon = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)
        self._config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": {}})
        self._settings = self._config["settings"]
        self._drag = None
        self._drag_mode = None
        self._build()
        self._watch = qt.QtCore.QTimer(self)
        self._watch.setInterval(WATCH_MS)
        self._watch.timeout.connect(self._show_targets)

    # ------------------------------------------------------------------ settings

    def _get(self, key: str, default):
        value = (self._config.data.get("settings") or {}).get(key)   # plain data: no phantom keys
        return default if value is None else value

    def _set(self, key: str, value) -> None:
        self._settings[key] = value

    def _limit(self) -> float:
        return OVERSHOOT if self._overshoot.isChecked() else 1.0

    def _frame(self) -> float:
        return float(self._frame_field.value())

    # ------------------------------------------------------------------ building

    def _icon(self, name: str):
        return UiResources().iconManager.get_icon(name, sub_folder="actions")

    def _build(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        self._rows = {}
        for family in (cv.POSE, cv.CURVE):
            row = _SliderRow(family)
            row.set_mode(str(self._get(family, row.modes[0].key)))
            row.picked.connect(lambda key, r=row: self._pick(r, key))
            row.slider.drag_started.connect(lambda modifiers, r=row: self._start(r, modifiers))
            row.slider.dragged.connect(self._move)
            row.slider.drag_finished.connect(lambda weight, r=row: self._finish(r, weight))
            row.slider.cancelled.connect(lambda r=row: self._cancel(r))
            self._rows[family] = row
            layout.addWidget(row)

        frame_row = self._frame_row = qt.QtWidgets.QWidget()
        frame_layout = qt.QtWidgets.QHBoxLayout(frame_row)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(6)
        caption = qt.QtWidgets.QLabel("Frame to blend / scale to")
        caption.setObjectName("animationCaption")
        self._frame_field = DragNumberField(float(self._get("frame", 1.0)), -100000.0, 100000.0, 1.0, width=64,
                                            decimals=1)
        self._frame_field.setToolTip("The frame Blend to Frame and Scale From Frame use")
        self._frame_field.value_changed.connect(lambda value: self._set("frame", float(value)))
        take = qt.QtWidgets.QPushButton("Current frame")
        take.setObjectName("animationQuiet")
        take.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        take.setToolTip("Take the frame the timeline is on now")
        take.clicked.connect(self._take_frame)
        frame_layout.addWidget(caption)
        frame_layout.addWidget(self._frame_field)
        frame_layout.addWidget(take)
        frame_layout.addStretch(1)
        layout.addWidget(frame_row)

        self._targets = qt.QtWidgets.QLabel("")
        self._targets.setObjectName("animationTargets")
        self._targets.setWordWrap(True)
        self._targets.setToolTip("What the sliders act on now: keys picked in the Graph Editor (while it is on "
                                 "screen), else the selected objects' keys in the range highlighted on the "
                                 "timeline, else on the current frame (a key is added where a channel has none). "
                                 "Channels picked in the Channel Box narrow it.")
        layout.addWidget(self._targets)

        self._overshoot = ToggleIconButton(self._icon("expand"), "Overshoot",
                                           "The sliders' ends go to 200%: past the neighbors, the default, the "
                                           "frame.")
        self._overshoot.setObjectName("animationToggle")
        self._overshoot.setChecked(bool(self._get("overshoot", False)))
        self._overshoot.toggled.connect(self._overshoot_changed)
        self._euler = ToggleIconButton(self._icon("restart"), "Euler filter",
                                       "After a change of rotations, an Euler filter over the changed range - "
                                       "no flips from a tween across 180°.")
        self._euler.setObjectName("animationToggle")
        self._euler.setChecked(bool(self._get("euler", True)))
        self._euler.toggled.connect(lambda on: self._set("euler", bool(on)))
        self._overshoot_changed(self._overshoot.isChecked())
        self._show_frame_row()

    def header_widgets(self) -> list:
        """The window puts these in its header, before the theme toggle."""
        return [self._overshoot, self._euler]

    # ------------------------------------------------------------------ modes

    def _pick(self, row: _SliderRow, key: str) -> None:
        row.set_mode(key)
        self._set(row.family, key)
        self._show_frame_row()

    def _show_frame_row(self) -> None:
        self._frame_row.setVisible(any(row.mode.key in FRAME_MODES for row in self._rows.values()))

    def _overshoot_changed(self, on: bool) -> None:
        self._set("overshoot", bool(on))
        for row in self._rows.values():
            row.slider.set_limit(OVERSHOOT if on else 1.0)

    def _take_frame(self) -> None:
        try:
            from maya import cmds
            self._frame_field.set_value(float(cmds.currentTime(query=True)))
            self._set("frame", self._frame())
        except Exception:
            pass

    # ------------------------------------------------------------------ a drag

    def _start(self, row: _SliderRow, modifiers: str) -> None:
        mode = cv.mode_for_modifiers(row.family, modifiers) or row.mode
        self._drag_mode = mode
        row.show_mode(mode)
        frame = self._frame() if mode.key in FRAME_MODES else None
        try:
            from msl_tools.msl.tools.maya.animation import scene
            self._drag = scene.Drag(mode.key, frame)
        except Exception as error:   # outside Maya, or Maya refused
            self._drag = None
            self._say(f"{mode.title}: {error}", "error")
            return
        if not self._drag:
            self._drag = None
            self._say("Nothing to act on: select animated objects (or keys in the Graph Editor)", "error")

    def _move(self, weight: float) -> None:
        if self._drag is not None:
            try:
                self._drag.update(weight)
            except Exception as error:
                self._say(f"{self._drag_mode.title}: {error}", "error")

    def _finish(self, row: _SliderRow, weight: float) -> None:
        drag, self._drag = self._drag, None
        row.show_mode(row.mode)
        if drag is None:
            return
        try:
            text = drag.commit(weight, euler=self._euler.isChecked())
        except Exception as error:
            drag.cancel()
            self._say(f"{self._drag_mode.title}: {error}", "error")
            return
        self._say(text, "done")
        self._show_targets()

    def _cancel(self, row: _SliderRow) -> None:
        drag, self._drag = self._drag, None
        row.show_mode(row.mode)
        if drag is not None:
            drag.cancel()
            self._say("Put back as it was", "")

    # ------------------------------------------------------------------ what it acts on

    def _show_targets(self) -> None:
        if self._drag is not None:
            return
        try:
            from msl_tools.msl.tools.maya.animation import scene
            text = scene.describe()
        except Exception:
            text = ""
        if self._targets.text() != text:
            self._targets.setText(text)

    def _say(self, text: str, state: str = "") -> None:
        self.status_changed.emit(text, state)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._show_targets()
        self._watch.start()

    def hideEvent(self, event) -> None:
        self._watch.stop()
        if self._drag is not None:
            self._drag.cancel()
            self._drag = None
        super().hideEvent(event)
