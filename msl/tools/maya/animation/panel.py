# tools/maya/animation/panel.py
"""The Animation tool's panel: two sliders that are pulled, not set —
    POSE   where the keys go: Tweener, Blend to Neighbors / Default / Frame / Infinity / Undo
    CURVE  the shape of the keys: Pull | Push, Scale From ..., Smooth | Rough, Ease, Time Offset,
           Noise | Wave, Connect to Neighbors
— each with the mode it is on (a click on the name, or a right click on the slider, picks another;
held modifiers switch it for one drag: Shift = Blend to Neighbors / Smooth | Rough, ...), the frames
the "Frame" modes go to (grey squares at the slider's ends: hover = the frame, click = the current
frame, wheel = +-1, right click = type it), and a line saying what the sliders act on now (Graph Editor keys, the
timeline's range, the current frame). A drag changes the curves live and ends as ONE undo step;
Esc during it puts everything back.

Under them the tool groups (keys_row.py), flat: precise, nudge, default pose, baking, clean up, color keys, play.

Settings: configsMayaMng "animation" (`settings`: pose, curve, overshoot, euler, frame_left, frame_right, world,
frames, precise, bake / share options, slider settings).
"""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.animation import curves as cv
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField
from msl_tools.msl.tools.maya.rename.buttons import ToggleIconButton
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.sliders import BlendSlider
from msl_tools.msl.ui.widgets.compositions.option_menu import OptionMenu

StylesheetBuilder.register_template(Path(__file__).with_name("animation.qss"))

WATCH_MS = 500           # how often the line "what the sliders act on" is read while on screen
OVERSHOOT = 2.0          # the weight at a slider's end with overshoot on
FRAME_MODES = ("frame", "scale_frame")
FRAME_SIDES = {"frame": ("left", "right"), "scale_frame": ("left",)}   # the slots each frame mode uses
WORLD_MODES = ("tween", "neighbors", "frame", "infinity")   # the pose modes that can work in world space (world.py)
WORLD_WIDTH = 24
MODE_WIDTH = 116          # the mode button; a longer name is cut short (the whole one in its tooltip)
KEYS_MS = 50             # how often the held keys are read while the pointer is over a slider
NUMBER_WIDTH = 40        # the slider's number box


class _SliderRow(qt.QtWidgets.QWidget):
    """A slider of one family with the button that names (and picks) its mode."""

    picked = qt.QtCore.Signal(str)        # a mode was picked for this slider
    typed = qt.QtCore.Signal(float)       # a weight typed into the number box (1 = 100 %)

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
        # the pose slider can blend where objects ARE in the world (world.py), not their channels
        self.world = None
        if family == cv.POSE:
            self.world = ToggleIconButton(UiResources().iconManager.get_icon("world", sub_folder="actions"),
                                          "World space", "Tweener, Blend to Neighbors, Frame and Infinity work on "
                                          "where the selected objects are in the WORLD - the hierarchy ignored: a "
                                          "control under a moving parent goes where it was, and its own channels "
                                          "are worked out from that.")
            self.world.setObjectName("animationToggle")
            self.world.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            self.world.setFixedWidth(WORLD_WIDTH)
            policy = self.world.sizePolicy()
            policy.setRetainSizeWhenHidden(True)      # a mode without it doesn't move the slider
            self.world.setSizePolicy(policy)
            layout.addWidget(self.world)
        else:
            room = qt.QtWidgets.QWidget()              # the same room, so both sliders start alike
            room.setFixedWidth(WORLD_WIDTH)
            layout.addWidget(room)
        layout.addWidget(self.slider, 1)
        # the number box (setting "Show slider input box"): a percent typed + Enter = the mode at that weight
        self.number = qt.QtWidgets.QLineEdit()
        self.number.setObjectName("animationNumber")
        self.number.setFixedWidth(NUMBER_WIDTH)
        self.number.setPlaceholderText("%")
        self.number.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self.number.setValidator(qt.QtGui.QDoubleValidator(-1000.0, 1000.0, 2, self.number))
        self.number.setToolTip("A number for the slider\nType a percent (-100 .. 100; to 200 with overshoot) and press "
                               "Enter: the slider's mode at exactly that weight, one undo step.")
        self.number.returnPressed.connect(self._take_number)
        # click focus only: a window that opens or comes to the front must not hand it the keyboard
        self.number.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.ClickFocus)
        self.number.installEventFilter(self)
        layout.addWidget(self.number)
        self.button.clicked.connect(lambda: self._menu(self.button.mapToGlobal(
            qt.QtCore.QPoint(0, self.button.height()))))
        self.slider.menu_requested.connect(self._menu)
        self.mode = self.modes[0]
        self._shown = self.mode
        self.frames = {"left": 1.0, "right": 10.0}   # the panel's; shown in the slots of the frame modes
        # while the pointer is over the slider, the keys held now pick the mode it shows - so it
        # says what a press WOULD do before the click (the keyboard is read: the slider has no focus)
        self._keys = qt.QtCore.QTimer(self)
        self._keys.setInterval(KEYS_MS)
        self._keys.timeout.connect(self._follow_keys)
        self.slider.installEventFilter(self)

    def _take_number(self) -> None:
        text = self.number.text().replace(",", ".")
        self.number.clearFocus()              # done with it: the keyboard goes back (Maya's hotkeys work again)
        try:
            value = float(text)
        except ValueError:
            return
        self.typed.emit(value / 100.0)

    def set_mode(self, key: str) -> None:
        self.mode = cv.BY_KEY.get(key) if key in cv.BY_KEY and cv.BY_KEY[key].family == self.family \
            else self.modes[0]
        self.show_mode(self.mode)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.number and event.type() == qt.QtCore.QEvent.Type.KeyPress and                 event.key() == qt.QtCore.Qt.Key.Key_Escape:
            self.number.clear()
            self.number.clearFocus()
            return True
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
        if self.world is not None:
            self.world.setVisible(mode.key in WORLD_MODES)
        self.slider.set_marks(mode.marks)
        self.slider.setToolTip(f"{mode.title}\nDrag left: {mode.left}, right: {mode.right}. A click on a mark "
                               f"goes straight there. Hold a key while pressing for another mode; right click: "
                               f"every mode. Esc while dragging puts it back.")
        self.slider.format_weight = lambda weight, m=mode: cv.weight_text(m, weight)
        self.show_frames()

    def show_frames(self) -> None:
        """The slots at the slider's ends: the frames of the mode shown, if it uses any."""
        sides = FRAME_SIDES.get(self._shown.key, ())
        texts = {side: (f"{self.frames[side]:g}" if side in sides else None) for side in ("left", "right")}
        self.slider.set_slots(texts["left"], texts["right"])

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

    # ------------------------------------------------------------------ building

    def _icon(self, name: str):
        return UiResources().iconManager.get_icon(name, sub_folder="actions")

    def _build(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        self._rows = {}
        left = float(self._get("frame_left", self._get("frame", 1.0)))
        self._frames = {"left": left, "right": float(self._get("frame_right", left + 10.0))}
        for family in (cv.POSE, cv.CURVE):
            row = _SliderRow(family)
            row.frames = self._frames
            row.set_mode(str(self._get(family, row.modes[0].key)))
            row.slider.slot_clicked.connect(self._take_frame)
            row.slider.slot_stepped.connect(lambda side, steps: self._set_frame(side, self._frames[side] + steps))
            row.slider.slot_menu_requested.connect(lambda side, position, r=row: self._frame_menu(r, side, position))
            row.picked.connect(lambda key, r=row: self._pick(r, key))
            row.typed.connect(lambda weight, r=row: self._typed(r, weight))
            row.slider.drag_started.connect(lambda modifiers, r=row: self._start(r, modifiers))
            row.slider.dragged.connect(self._move)
            row.slider.drag_finished.connect(lambda weight, r=row: self._finish(r, weight))
            row.slider.cancelled.connect(lambda r=row: self._cancel(r))
            self._rows[family] = row
            layout.addWidget(row)

        # the tool groups: precise, nudge, default pose, baking, clean up, color keys, play (keys_row.py)
        from msl_tools.msl.tools.maya.animation.keys_row import KeysRow
        self._keys_row = KeysRow(self._get, self._set)
        self._keys_row.said.connect(self._said)
        layout.addWidget(self._keys_row)

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
        # overshoot belongs to the sliders: at the end of the pose row, beside the number box (the curve row keeps
        # the same room, so both sliders end alike)
        self._overshoot.setFixedWidth(WORLD_WIDTH)
        self._overshoot.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._rows[cv.POSE].layout().addWidget(self._overshoot)
        room = qt.QtWidgets.QWidget()
        room.setFixedWidth(WORLD_WIDTH)
        self._rows[cv.CURVE].layout().addWidget(room)
        world = self._rows[cv.POSE].world
        world.setChecked(bool(self._get("world", False)))
        world.toggled.connect(lambda on: self._set("world", bool(on)))

        from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
        self._settings_button = GlyphButton("", "Slider settings\nThe mouse wheel on the sliders, its direction, the "
                                                "number box, overshoot", qt.QtCore.QSize(24, 22))
        self._settings_button.setObjectName("animationGear")
        self._settings_button.set_icon(self._icon("sliders"))
        self._settings_button.clicked.connect(lambda: self._settings_menu().exec(
            self._settings_button.mapToGlobal(qt.QtCore.QPoint(0, self._settings_button.height()))))
        self._apply_slider_settings()

    def header_widgets(self) -> list:
        """The window puts these in its header, before the theme toggle."""
        return [self._euler, self._settings_button]

    # ------------------------------------------------------------------ slider settings (the reference's preferences)

    SLIDER_SETTINGS = (   # key, title, what it does, the default (the reference's)
        ("wheel", "Mouse wheel on the sliders", "Over a slider the wheel pulls its knob: the first notch starts at the "
         "middle (a Tweener's 50 %), each next notch a step further; moving off the slider ends it - one undo step",
         True),
        ("wheel_flip", "Flip the wheel's direction", "Wheel up moves the knob right instead of left", False),
        ("input_box", "Show the sliders' number box", "A box beside each slider: type a percent, Enter applies the "
         "mode at exactly that weight", True),
    )

    def _slider_setting(self, key: str) -> bool:
        default = next(d for k, _t, _n, d in self.SLIDER_SETTINGS if k == key)
        return bool(self._get(key, default))

    def _apply_slider_settings(self) -> None:
        for row in self._rows.values():
            row.slider.set_wheel(self._slider_setting("wheel"), self._slider_setting("wheel_flip"))
            row.number.setVisible(self._slider_setting("input_box"))

    def _settings_menu(self) -> "qt.QtWidgets.QMenu":
        menu = qt.QtWidgets.QMenu(self)
        make_rounded_popup(menu)
        menu.setToolTipsVisible(True)
        caption = menu.addAction("SLIDERS")
        caption.setEnabled(False)
        for key, title, note, _default in self.SLIDER_SETTINGS:
            item = menu.addAction(title)
            item.setCheckable(True)
            item.setChecked(self._slider_setting(key))
            item.setToolTip(note)
            if key == "wheel_flip":
                item.setEnabled(self._slider_setting("wheel"))
            item.toggled.connect(lambda on, k=key: (self._set(k, bool(on)), self._apply_slider_settings()))
        overshoot = menu.addAction("Overshoot (the ends go to 200 %)")
        overshoot.setCheckable(True)
        overshoot.setChecked(self._overshoot.isChecked())
        overshoot.toggled.connect(self._overshoot.setChecked)
        return menu

    def _typed(self, row: _SliderRow, weight: float) -> None:
        """A number typed for a slider: its mode at exactly that weight, as a drag that ends there (one undo)."""
        weight = max(-self._limit(), min(self._limit(), weight))
        self._start(row, "")
        if self._drag is None:
            return
        self._move(weight)
        self._finish(row, weight)

    # ------------------------------------------------------------------ modes

    def _pick(self, row: _SliderRow, key: str) -> None:
        row.set_mode(key)
        self._set(row.family, key)

    def _overshoot_changed(self, on: bool) -> None:
        self._set("overshoot", bool(on))
        for row in self._rows.values():
            row.slider.set_limit(OVERSHOOT if on else 1.0)

    # ------------------------------------------------------------------ the frames (the slots)

    def _set_frame(self, side: str, frame: float) -> None:
        self._frames[side] = round(float(frame), 3)
        self._set(f"frame_{side}", self._frames[side])
        for row in self._rows.values():
            row.show_frames()
        self._say(f"{side.capitalize()} frame: {self._frames[side]:g}", "")

    def _take_frame(self, side: str) -> None:
        """A click on a slot: the frame the timeline is on now."""
        try:
            from maya import cmds
            self._set_frame(side, float(cmds.currentTime(query=True)))
        except Exception:
            pass

    def _frame_menu(self, row: _SliderRow, side: str, position) -> None:
        """A right click on a slot: type the frame, or take the current one."""
        menu = qt.QtWidgets.QMenu(self)
        make_rounded_popup(menu)
        caption = menu.addAction(f"{side.upper()} FRAME")
        caption.setEnabled(False)
        field = DragNumberField(self._frames[side], -100000.0, 100000.0, 1.0, width=90, decimals=1)
        field.value_changed.connect(lambda value: self._set_frame(side, value))
        holder = qt.QtWidgets.QWidget()
        holder_layout = qt.QtWidgets.QHBoxLayout(holder)
        holder_layout.setContentsMargins(10, 2, 10, 2)
        holder_layout.addWidget(field)
        action = qt.QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        try:
            from maya import cmds
            now = float(cmds.currentTime(query=True))
            menu.addAction(f"Current frame ({now:g})").triggered.connect(lambda: self._set_frame(side, now))
        except Exception:
            pass
        field.returnPressed.connect(menu.close)
        qt.QtCore.QTimer.singleShot(0, lambda: (field.setFocus(), field.selectAll()))
        menu.exec(position)

    # ------------------------------------------------------------------ a drag

    def _start(self, row: _SliderRow, modifiers: str) -> None:
        mode = cv.mode_for_modifiers(row.family, modifiers) or row.mode
        self._drag_mode = mode
        row.show_mode(mode)
        sides = FRAME_SIDES.get(mode.key, ())
        frame = self._frames["left"] if "left" in sides else None
        frame_right = self._frames["right"] if "right" in sides else None
        try:
            from msl_tools.msl.tools.maya.animation import scene
            world = row.world is not None and row.world.isChecked() and mode.key in WORLD_MODES
            if world:
                from msl_tools.msl.tools.maya.animation import world as world_space
                self._drag = world_space.WorldDrag(mode.key, frame, frame_right)
            else:
                self._drag = scene.make_drag(mode.key, frame, frame_right)
        except Exception as error:   # outside Maya, or Maya refused
            self._drag = None
            self._say(f"{mode.title}: {error}", "error")
            return
        if not self._drag:
            self._drag = None
            self._say("Nothing to act on: select animated objects (or keys in the Graph Editor)", "error")
        elif mode.key == "buffer" and not self._drag.buffered:
            self._drag.cancel()
            self._drag = None
            self._say("No buffer curve: take one in the Graph Editor - Curves > Buffer Curve Snapshot", "error")

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

    def _said(self, text: str, state: str) -> None:
        self._say(text, state)
        self._show_targets()

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
