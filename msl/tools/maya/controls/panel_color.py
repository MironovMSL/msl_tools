# tools/maya/controls/panel_color.py
"""The Controls panel's COLOR card: Maya's index palette, a color of your own (RGB) and the colors
you saved, where the color goes (the viewport and / or the Outliner; the shapes or the transform),
side colors, taking the color from an object, back to none, the curves' line width. Every click acts
on what is selected at once. Methods of ControlsPanel, kept apart by concern."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.controls import colors
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField, Swatches
from msl_tools.msl.tools.maya.rename.buttons import ToggleIconButton
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.color_swatch_button import ColorSwatchButton
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

COLOR_TARGETS = ("Shape", "Transform")
SAVED_MAX = 20


class _ColorMixin:

    def _color_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        card = self._color = FoldingCard("COLOR", icons.get_icon("color_pick", sub_folder="actions"))
        self._palette = Swatches(side=16, gap=2, columns=16)
        self._palette.setObjectName("controlsPalette")
        self._palette_colors = list(colors.INDEX_COLORS)
        self._show_palette()

        self._own = ColorSwatchButton(colors.to_hex(colors.SIDE_COLORS["left"]), "Your color — a click picks it "
                                      "and colors the selection with it")
        self._own.setObjectName("controlsOwnColor")
        self._saved = Swatches(side=16, gap=2, columns=10)
        self._saved.setObjectName("controlsSaved")
        self._save_color = self._tool_button("bookmark_add", "Save the color", "Keep your color among the saved "
                                                                              "ones (a right click on one removes it)")
        own = qt.QtWidgets.QHBoxLayout()
        own.setSpacing(4)
        own.addWidget(self._own)
        own.addWidget(self._save_color)
        own.addSpacing(4)
        own.addWidget(self._saved, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        own.addStretch(1)

        self._to_viewport = ToggleIconButton(icons.get_icon("eye", sub_folder="actions"), "In the viewport",
                                             "The drawing override: how the object is drawn")
        self._to_viewport.setObjectName("controlsToggle")
        self._to_outliner = ToggleIconButton(icons.get_icon("outliner", sub_folder="actions"), "In the Outliner",
                                             "The Outliner's color of the object (lifted to read like the viewport)")
        self._to_outliner.setObjectName("controlsToggle")
        self._color_on = SegmentedControl(list(COLOR_TARGETS), "Shape")
        self._color_on.setToolTip("Shape: the override on the curves (the transform stays clean, a joint or a "
                                  "group takes it itself) · Transform: on the object")
        self._by_side = self._tool_button("mirror_sides", "By side", "Each selected object in its side's color: "
                                                                     "left blue, right red, middle yellow")
        self._pick = self._tool_button("color_pick", "Take", "Take the color of the selected object as your color")
        self._reset_color = self._tool_button("clear", "No color", "Back to Maya's default color: no override, "
                                                                   "no Outliner color")
        self._line = DragNumberField(1.0, -1.0, 20.0, 0.5, width=40, decimals=1)
        self._line.setToolTip("The curves' line width (-1 = Maya's preference) — the selected controls at once; "
                              "drag with the middle mouse button, the wheel, Up / Down")
        where = qt.QtWidgets.QHBoxLayout()
        where.setSpacing(4)
        where.addWidget(self._to_viewport)
        where.addWidget(self._to_outliner)
        where.addWidget(self._color_on)
        where.addStretch(1)
        for button in (self._by_side, self._pick, self._reset_color):
            where.addWidget(button)
        where.addSpacing(6)
        where.addWidget(self._caption("Line"))
        where.addWidget(self._line)

        card.body_layout.addWidget(self._palette)
        card.body_layout.addLayout(own)
        card.body_layout.addLayout(where)
        return card

    def _connect_color(self) -> None:
        self._palette.clicked.connect(self._on_index)
        self._own.color_changed.connect(self._on_own_color)
        self._save_color.clicked.connect(self._on_save_color)
        self._saved.clicked.connect(self._on_saved_color)
        self._saved.menu_requested.connect(self._on_saved_menu)
        for toggle in (self._to_viewport, self._to_outliner):
            toggle.toggled.connect(self._save_color_settings)
        self._color_on.current_changed.connect(self._save_color_settings)
        self._by_side.clicked.connect(self._on_by_side)
        self._pick.clicked.connect(self._on_pick_color)
        self._reset_color.clicked.connect(self._on_reset_color)
        self._line.value_changed.connect(self._on_line_width)
        self._color.toggled.connect(lambda opened: self._save_folded("color", opened))

    def _apply_color_settings(self) -> None:
        s = self._settings
        self._to_viewport.setChecked(bool(s.get("color_viewport", True)))
        self._to_outliner.setChecked(bool(s.get("color_outliner", False)))
        target = s.get("color_on", "Shape")
        self._color_on.set_current(target if target in COLOR_TARGETS else "Shape", animate=False)
        own = s.get("own_color", "")
        if own:
            self._own.set_color(own)
        self._line.set_value(float(s.get("line_width", 1.0)))
        self._color.set_open(not dict(s.get("folded") or {}).get("color", False))
        self._show_saved()

    def _save_color_settings(self, *_args) -> None:
        if self._loading:
            return
        values = {"color_viewport": self._to_viewport.isChecked(), "color_outliner": self._to_outliner.isChecked(),
                  "color_on": self._color_on.current(), "own_color": self._own.hex(), "line_width": self._line.value()}
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value

    # ------------------------------------------------------------------ showing

    def refresh_palette(self) -> None:
        """Maya's index colors as THIS Maya has them (asked when the window shows)."""
        try:
            from msl_tools.msl.tools.maya.controls import scene
            self._palette_colors = scene.index_palette()
        except Exception:   # outside Maya: the default palette
            self._palette_colors = list(colors.INDEX_COLORS)
        self._show_palette()

    def _show_palette(self) -> None:
        self._palette.set_items([(str(index), None if index == 0 else rgb,
                                  "None — Maya's default color" if index == 0 else f"Index {index}")
                                 for index, rgb in enumerate(self._palette_colors)])

    def _saved_colors(self) -> list:
        return [text for text in (self._settings.get("saved_colors") or []) if isinstance(text, str)]

    def _show_saved(self) -> None:
        self._saved.set_items([(text, colors.from_hex(text), f"{text} — a click colors the selection · right "
                                                             f"click: remove") for text in self._saved_colors()])
        wanted = bool(self._saved_colors())
        if wanted == self._saved.isHidden():
            self._saved.setVisible(wanted)

    # ------------------------------------------------------------------ coloring

    def _where(self) -> dict:
        return {"viewport": self._to_viewport.isChecked(), "outliner": self._to_outliner.isChecked(),
                "on_shape": self._color_on.current() == "Shape"}

    def _targets(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if not targets:
            self._say("Select the objects to color first", "error")
        elif not (self._to_viewport.isChecked() or self._to_outliner.isChecked()):
            self._say("Switch on where the color goes: the viewport, the Outliner or both", "error")
            return []
        return targets

    def _on_index(self, key: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._targets()
        if targets:
            index = int(key)
            scene.color(targets, index=index, **self._where())
            self._palette.set_current(key)
            self._say(f"{len(targets)} in index {index}" if index else f"{len(targets)} back to the default color",
                      "done")

    def _apply_rgb(self, rgb, what: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._targets()
        if targets:
            scene.color(targets, rgb=rgb, **self._where())
            self._palette.set_current("")
            self._say(f"{len(targets)} in {what}", "done")

    def _on_own_color(self, text: str) -> None:
        self._save_color_settings()
        self._apply_rgb(colors.from_hex(text), text)

    def _on_saved_color(self, text: str) -> None:
        self._own.set_color(text)
        self._saved.set_current(text)
        self._save_color_settings()
        self._apply_rgb(colors.from_hex(text), text)

    def _on_save_color(self) -> None:
        text = self._own.hex()
        saved = self._saved_colors()
        if text in saved:
            self._say(f"{text} is saved already")
            return
        self._settings["saved_colors"] = (saved + [text])[-SAVED_MAX:]
        self._show_saved()
        self._say(f"Saved {text}", "done")

    def _on_saved_menu(self, text: str, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.addAction("Color the selection with it", lambda: self._on_saved_color(text))
        menu.addAction("Remove it", lambda: (self._settings.__setitem__(
            "saved_colors", [each for each in self._saved_colors() if each != text]), self._show_saved()))
        menu.exec(position)

    def _on_by_side(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._targets()
        if targets:
            counted = scene.color_by_side(targets, self._sides(), **self._where())
            self._say(" · ".join(f"{count} {side}" for side, count in counted.items()) + " — in their sides' colors",
                      "done")

    def _on_pick_color(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if not targets:
            self._say("Select the object whose color to take", "error")
            return
        rgb, index = scene.read_color(targets[0])
        if rgb is None:
            self._say(f"{targets[0].rpartition('|')[2]} has Maya's default color")
            return
        self._own.set_color(colors.to_hex(rgb))
        self._palette.set_current(str(index) if index else "")
        self._save_color_settings()
        self._say(f"Took {colors.to_hex(rgb)}" + (f" (index {index})" if index else "") + " — your color now", "done")

    def _on_reset_color(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if not targets:
            self._say("Select the objects first", "error")
            return
        scene.reset_color(targets)
        self._palette.set_current("")
        self._say(f"{len(targets)} back to Maya's default color · Ctrl+Z undoes it", "done")

    def _on_line_width(self, width: float) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        self._save_color_settings()
        controls = scene.controls_in_selection()
        if controls:
            count = scene.set_line_width(controls, width)
            self._say(f"Line width {width:g} on {count} curve{'s' if count != 1 else ''}", "done")
