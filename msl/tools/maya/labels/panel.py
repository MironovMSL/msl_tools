# tools/maya/labels/panel.py
"""The Labels tool's panel: cards that fold —
    VIEWPORT  a sketch of the picture with the HUD columns where they will stand (drag them there)
    COLUMNS   the columns as chips (+ a new one, mirror, duplicate, remove), and the picked column's
              look and place: header, size, gap, font, HUD corner + offset or the 3D object
    LINES     the picked column's lines: color, label, attribute, its value now, shown or not;
              + from the Channel Box, + an empty line, remove, up / down
    LINE      the picked line: a static color + opacity, or a gradient by the value (a ramp over a
              range, smooth or in steps, opacity from - to), digits
— and under them the namespace the layout is built for, Manual / Auto size and the button that
builds it into the scene. Once built, every edit updates the scene at once (outside the undo queue:
`scene.build(undo=False)`); the button then reads "Update in scene" and does it as one undo step.

The layout being edited is kept in configsMayaMng "labels" (`settings.layout`), saved layouts in
`layouts` (the header's bookmark menu, which also reads a layout back from the scene and writes /
reads layout files).
"""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField
from msl_tools.msl.tools.maya.labels import layout as lay
from msl_tools.msl.tools.maya.labels.sketch import CornerPicker, ViewportSketch
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.tools.maya.rename.buttons import QuickButton, ToggleIconButton
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.color_swatch_button import ColorSwatchButton
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.gradients.gradient_ramp import GradientRamp
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces.stable_scroll_area import StableScrollArea
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

StylesheetBuilder.register_template(Path(__file__).with_name("labels.qss"))

NO_NAMESPACE = "No namespace"
LIVE_MS = 250        # an edit reaches the scene this long after the last one
VALUES_MS = 300      # how often the lines' values are read while the window is on screen
FONTS = ("Consolas", "Cascadia Mono", "Courier New", "Lucida Console", "Arial", "Segoe UI")


def _hex(color) -> str:
    return qt.QtGui.QColor.fromRgbF(*color).name()


def _rgb(text: str) -> tuple:
    color = qt.QtGui.QColor(text)
    return (round(color.redF(), 4), round(color.greenF(), 4), round(color.blueF(), 4))


def _starting_layout() -> lay.Layout:
    return lay.Layout(name="labels", columns=[lay.Column(name="labels", header="LABELS")])


class LabelsPanel(qt.QtWidgets.QWidget):
    """The tool (shown in a LabelsWindow).

    Signals:
        status_changed(str, str) — what the panel says (text, "" / "done" / "error"): the header.
    """

    status_changed = qt.QtCore.Signal(str, str)

    menuIconColor = color_property("_menu_icon", None)

    TOOL_NAME = "labels"

    def __init__(self, parent=None):
        super().__init__(parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        self._menu_icon = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)
        self._config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": {}})
        self._settings = self._config["settings"]
        stored = (self._config.data.get("settings") or {}).get("layout")   # plain data, not a ConfigNode
        self._layout = lay.from_dict(stored) if stored else _starting_layout()
        if not self._layout.columns:
            self._layout.columns.append(lay.Column())
        self._column_index = 0
        self._line_index = 0
        self._loading = True
        self._build()
        self._connect()
        self._loading = False
        self._live = qt.QtCore.QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(LIVE_MS)
        self._live.timeout.connect(self._update_scene)
        self._values_timer = qt.QtCore.QTimer(self)
        self._values_timer.setInterval(VALUES_MS)
        self._values_timer.timeout.connect(self._show_values)
        self._show_all()

    # ------------------------------------------------------------------ the layout being edited

    def _column(self) -> lay.Column:
        self._column_index = max(0, min(self._column_index, len(self._layout.columns) - 1))
        return self._layout.columns[self._column_index]

    def _line(self) -> "lay.Line | None":
        lines = self._column().lines
        if not lines:
            return None
        self._line_index = max(0, min(self._line_index, len(lines) - 1))
        return lines[self._line_index]

    def _namespace(self) -> str:
        text = self._namespaces.currentText()
        return "" if text == NO_NAMESPACE else text

    def _changed(self, live: bool = True) -> None:
        """Something was edited: kept, shown, and — when the layout is built — sent to the scene."""
        if self._loading:
            return
        self._layout.namespace = self._namespace()
        self._settings["layout"] = lay.to_dict(self._layout)
        self._show_all()
        if live and self._built():
            self._live.start()

    def _built(self) -> str:
        try:
            from msl_tools.msl.tools.maya.labels import scene
            return scene.find(self._layout.name, self._namespace()) or ""
        except Exception:      # outside Maya (an offscreen test) there is no scene
            return ""

    # ------------------------------------------------------------------ building the widgets

    def _icon(self, name: str):
        return UiResources().iconManager.get_icon(name, sub_folder="actions")

    def _tool(self, icon: str, text: str, tip: str, tone: str = "") -> QuickButton:
        button = QuickButton(self._icon(icon), text, f"{text}\n{tip}" if tip else text, icon_size=15)
        button.setObjectName("labelsTool")
        if tone:
            button.setProperty("tone", tone)
        return button

    @staticmethod
    def _caption(text: str, width: int = 0) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("labelsCaption")
        if width:
            label.setFixedWidth(width)
        return label

    @staticmethod
    def _row(*widgets, stretch_at: int = -1) -> qt.QtWidgets.QHBoxLayout:
        row = qt.QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for index, widget in enumerate(widgets):
            if widget is None:
                row.addStretch(1)
            elif isinstance(widget, qt.QtWidgets.QLayout):
                row.addLayout(widget, 1 if index == stretch_at else 0)
            else:
                row.addWidget(widget, 1 if index == stretch_at else 0)
        return row

    def _build(self) -> None:
        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(8, 6, 8, 8)
        column.setSpacing(8)
        folded = self._settings.get("folded") or {}

        # VIEWPORT
        self._mode = SegmentedControl(["3D", "HUD"], "HUD")
        self._mode.setToolTip("3D: the column stands at an object in the scene and follows it\n"
                              "HUD: it stays on the screen, in a corner")
        self._sketch = ViewportSketch()
        self._viewport_card = FoldingCard("VIEWPORT", self._icon("viewport"), extras=[self._mode])
        # COLUMNS
        self._chips = ChipBar(add_text="+ column", name_placeholder="Column name, then Enter", checkable=True,
                              custom_menu=True)
        self._mirror = self._tool("mirror_sides", "Mirror", "A copy of the picked column for the other side: "
                                  "lf_ <-> rt_ in its attributes, name and object; a HUD column goes to the "
                                  "other corner", "teal")
        self._duplicate = self._tool("copy", "Duplicate", "A copy of the picked column")
        self._remove_column = self._tool("delete", "Remove", "Takes the picked column out of the layout")
        self._columns_card = FoldingCard("COLUMNS", self._icon("layout"),
                                         extras=[self._mirror, self._duplicate, self._remove_column])
        self._header = qt.QtWidgets.QLineEdit()
        self._header.setPlaceholderText("Header (empty = none)")
        self._header_color = ColorSwatchButton("#ffd166", "The header's color")
        self._size = DragNumberField(14, 4, 96, 1, width=44, decimals=0)
        self._size.setToolTip("The letters' size in pixels")
        self._spacing = DragNumberField(4, 0, 96, 1, width=40, decimals=0)
        self._spacing.setToolTip("Room between the lines, in pixels")
        self._font = BaseComboBox(list(FONTS), FONTS[0], enable_wheel=False)
        self._font.setEditable(True)
        self._font.setToolTip("The font Maya draws the text in — a fixed-width one keeps the values in a column")
        self._corner = CornerPicker()
        self._corner.setToolTip("The screen's corner the column stands in")
        self._x = DragNumberField(40, 0, 4000, 1, width=46, decimals=0)
        self._x.setToolTip("Pixels in from the corner, sideways")
        self._y = DragNumberField(40, 0, 4000, 1, width=46, decimals=0)
        self._y.setToolTip("Pixels in from the corner, up or down")
        self._anchor = qt.QtWidgets.QLineEdit()
        self._anchor.setPlaceholderText("The object it stands at")
        self._pick_anchor = self._tool("color_pick", "Selected", "The selected object (its namespace taken off)")
        self._distance = DragNumberField(0, 0, 100000, 1, width=50, decimals=1)
        self._distance.setToolTip("Smaller with the camera's distance: the distance at which it has its size\n"
                                  "0 = as big wherever it stands")
        self._hud_row = qt.QtWidgets.QWidget()
        self._hud_row.setLayout(self._row(self._caption("Corner", 52), self._corner, self._caption("X"), self._x,
                                          self._caption("Y"), self._y, None))
        self._space_row = qt.QtWidgets.QWidget()
        self._space_row.setLayout(self._row(self._caption("At", 52), self._anchor, self._pick_anchor,
                                            self._caption("Far"), self._distance, stretch_at=1))
        # LINES
        self._lines = qt.QtWidgets.QTreeWidget()
        self._lines.setObjectName("labelsLines")
        self._lines.setColumnCount(4)
        self._lines.setHeaderLabels(["", "Label", "Attribute", "Now"])
        self._lines.setRootIsDecorated(False)
        self._lines.setUniformRowHeights(True)
        self._lines.setEditTriggers(qt.QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                                    | qt.QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        header = self._lines.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, qt.QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 26)
        header.setSectionResizeMode(1, qt.QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, qt.QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, qt.QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, 64)
        self._from_box = self._tool("channels", "From the Channel Box",
                                    "A line for every channel picked in the Channel Box, on each selected object")
        self._add_line = self._tool("add", "Add a line", "An empty line: type its attribute (double click)")
        self._remove_line = self._tool("delete", "Remove the line", "Takes the picked line out")
        self._up = self._tool("chevron_up", "Up", "Moves the picked line up")
        self._down = self._tool("chevron_down", "Down", "Moves the picked line down")
        self._lines_card = FoldingCard("LINES", self._icon("text_frame"),
                                       extras=[self._from_box, self._add_line, self._up, self._down,
                                               self._remove_line])
        # LINE
        self._color_mode = SegmentedControl(["Static", "Gradient"], "Static")
        self._color_mode.setToolTip("Static: one color\nGradient: the color follows the value")
        self._line_card = FoldingCard("LINE", self._icon("brush"), extras=[self._color_mode])
        self._line_color = ColorSwatchButton("#ffffff", "The line's color")
        self._opacity = DragNumberField(1.0, 0.0, 1.0, 0.05, width=48, decimals=2)
        self._opacity.setToolTip("0 = invisible, 1 = solid")
        self._decimals = BaseComboBox(["auto", "0", "1", "2", "3"], "auto", enable_wheel=False)
        self._decimals.setToolTip("Digits after the point (auto = at most two)")
        self._ramp = GradientRamp()
        self._ramp.setToolTip("Click the bar: a new color there · drag a handle · Delete: remove the picked one "
                              "· double click a handle: its color")
        self._range_low = DragNumberField(0, -1e6, 1e6, 0.1, width=56, decimals=3)
        self._range_high = DragNumberField(1, -1e6, 1e6, 0.1, width=56, decimals=3)
        self._range_low.setToolTip("The value at the ramp's left end")
        self._range_high.setToolTip("The value at the ramp's right end")
        self._blend = SegmentedControl(["Smooth", "Steps"], "Smooth")
        self._blend.setToolTip("Smooth: blended between the colors\nSteps: each color holds from its place on")
        self._fade = ToggleIconButton(self._icon("eye"), "Opacity by the value",
                                      "From the left end's opacity to the right end's")
        self._fade.setObjectName("labelsToggle")
        self._fade_low = DragNumberField(0.2, 0.0, 1.0, 0.05, width=44, decimals=2)
        self._fade_high = DragNumberField(1.0, 0.0, 1.0, 0.05, width=44, decimals=2)
        self._static_row = qt.QtWidgets.QWidget()
        self._static_row.setLayout(self._row(self._caption("Color", 52), self._line_color,
                                             self._caption("Opacity"), self._opacity, None))
        self._gradient_box = qt.QtWidgets.QWidget()
        gradient = qt.QtWidgets.QVBoxLayout(self._gradient_box)
        gradient.setContentsMargins(0, 0, 0, 0)
        gradient.setSpacing(4)
        gradient.addWidget(self._ramp)
        gradient.addLayout(self._row(self._range_low, None, self._blend, None, self._range_high))
        gradient.addLayout(self._row(self._fade, self._caption("from"), self._fade_low, self._caption("to"),
                                     self._fade_high, None))
        # the build row
        self._namespaces = BaseComboBox([NO_NAMESPACE], NO_NAMESPACE, enable_wheel=False)
        self._namespaces.setToolTip("The rig the layout is built for: its attributes and objects are "
                                    "looked for in this namespace")
        self._scale_mode = SegmentedControl(["Manual", "Auto"], "Manual")
        self._scale_mode.setToolTip("Manual: as big as Maya's own interface - for working\n"
                                    "Auto: a part of the picture - every playblast and every machine the same")
        self._build_button = qt.QtWidgets.QPushButton("Build in scene")
        self._build_button.setObjectName("labelsBuild")
        self._build_button.setProperty("primary", True)

        for card, key in ((self._viewport_card, "viewport"), (self._columns_card, "columns"),
                          (self._lines_card, "lines"), (self._line_card, "line")):
            card.set_open(not folded.get(key, False))
            card.toggled.connect(lambda opened, key=key: self._save_folded(key, opened))
        self._fill_card(self._viewport_card, [self._sketch])
        self._fill_card(self._columns_card, [self._chips,
                                             self._row(self._caption("Header", 52), self._header, self._header_color,
                                                       stretch_at=1),
                                             self._row(self._caption("Size", 52), self._size,
                                                       self._caption("Gap"), self._spacing,
                                                       self._caption("Font"), self._font, stretch_at=5),
                                             self._hud_row, self._space_row])
        self._fill_card(self._lines_card, [self._lines])
        self._fill_card(self._line_card, [self._static_row, self._gradient_box,
                                          self._row(self._caption("Digits", 52), self._decimals, None)])
        for card in (self._viewport_card, self._columns_card, self._lines_card, self._line_card):
            column.addWidget(card)
        column.addLayout(self._row(self._caption("Namespace"), self._namespaces, self._caption("Size"),
                                   self._scale_mode, stretch_at=1))
        column.addWidget(self._build_button)
        column.addStretch(1)
        scroll = StableScrollArea()
        scroll.setObjectName("labelsScroll")
        scroll.setWidget(body)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    @staticmethod
    def _fill_card(card: FoldingCard, parts: list) -> None:
        box = card.body_layout
        for part in parts:
            if isinstance(part, qt.QtWidgets.QLayout):
                box.addLayout(part)
            else:
                box.addWidget(part)

    def header_widgets(self) -> list:
        """The window puts these into its header: the layouts' menu."""
        self._layouts_button = QuickButton(self._icon("bookmark"), "Layouts",
                                           "Layouts\nSaved layouts, read one back from the scene, files",
                                           icon_size=15)
        self._layouts_button.setObjectName("labelsHeaderButton")
        self._layouts_button.clicked.connect(self._open_layouts_menu)
        return [self._layouts_button]

    def content_height_change(self) -> int:
        scroll = self.findChild(StableScrollArea, "labelsScroll")
        if scroll is None or scroll.widget() is None:
            return 0
        return scroll.widget().sizeHint().height() - scroll.viewport().height()

    # ------------------------------------------------------------------ wiring

    def _connect(self) -> None:
        self._sketch.picked.connect(self._pick_column)
        self._sketch.moved.connect(lambda _index, _x, _y: self._changed())
        self._mode.current_changed.connect(lambda text: self._set_column(mode=lay.SPACE if text == "3D" else lay.HUD))
        self._chips.clicked.connect(lambda key: self._pick_column(int(key)))
        self._chips.add_requested.connect(self._add_column)
        self._chips.menu_requested.connect(self._column_menu)
        self._mirror.clicked.connect(self._mirror_column)
        self._duplicate.clicked.connect(self._duplicate_column)
        self._remove_column.clicked.connect(self._delete_column)
        self._header.editingFinished.connect(lambda: self._set_column(header=self._header.text()))
        self._header_color.color_changed.connect(lambda text: self._set_column(header_color=_rgb(text)))
        self._size.value_changed.connect(lambda value: self._set_column(size=int(value)))
        self._spacing.value_changed.connect(lambda value: self._set_column(spacing=int(value)))
        self._font.currentTextChanged.connect(lambda text: self._set_column(font=text.strip() or "Consolas"))
        self._corner.picked.connect(lambda corner: self._set_column(corner=corner))
        self._x.value_changed.connect(lambda value: self._set_column(x=int(value)))
        self._y.value_changed.connect(lambda value: self._set_column(y=int(value)))
        self._anchor.editingFinished.connect(lambda: self._set_column(anchor=self._anchor.text().strip()))
        self._pick_anchor.clicked.connect(self._use_selected_anchor)
        self._distance.value_changed.connect(lambda value: self._set_column(distance_scale=value))
        self._lines.currentItemChanged.connect(self._on_line_picked)
        self._lines.itemChanged.connect(self._on_line_edited)
        self._from_box.clicked.connect(self._lines_from_channel_box)
        self._add_line.clicked.connect(self._add_empty_line)
        self._remove_line.clicked.connect(self._delete_line)
        self._up.clicked.connect(lambda: self._move_line(-1))
        self._down.clicked.connect(lambda: self._move_line(1))
        self._color_mode.current_changed.connect(self._on_color_mode)
        self._line_color.color_changed.connect(lambda text: self._set_line(color=_rgb(text)))
        self._opacity.value_changed.connect(lambda value: self._set_line(opacity=value))
        self._decimals.currentTextChanged.connect(
            lambda text: self._set_line(decimals=-1 if text == "auto" else int(text)))
        self._ramp.stops_changed.connect(self._on_ramp)
        self._range_low.value_changed.connect(lambda _value: self._on_range())
        self._range_high.value_changed.connect(lambda _value: self._on_range())
        self._blend.current_changed.connect(
            lambda text: self._set_line(blend=lay.STEPS if text == "Steps" else lay.SMOOTH))
        self._fade.toggled.connect(lambda _on: self._on_fade())
        self._fade_low.value_changed.connect(lambda _value: self._on_fade())
        self._fade_high.value_changed.connect(lambda _value: self._on_fade())
        self._namespaces.currentTextChanged.connect(lambda _text: self._changed(live=False))
        self._scale_mode.current_changed.connect(self._on_scale_mode)
        self._build_button.clicked.connect(self.build_in_scene)

    def _save_folded(self, key: str, opened: bool) -> None:
        folded = dict(self._settings.get("folded") or {})
        folded[key] = not opened
        self._settings["folded"] = folded

    def _say(self, text: str, state: str = "") -> None:
        self.status_changed.emit(text, state)

    # ------------------------------------------------------------------ showing the layout

    def _show_all(self) -> None:
        """Every widget shows the layout as it is (no signals go out meanwhile)."""
        self._loading, was = True, self._loading
        try:
            column = self._column()
            self._chips.set_chips([(str(index), each.name, f"{len(each.lines)} line(s)")
                                   for index, each in enumerate(self._layout.columns)])
            self._chips.set_current(str(self._column_index))
            self._mode.set_current("3D" if column.mode == lay.SPACE else "HUD", animate=False)
            self._header.setText(column.header)
            self._header_color.set_color(_hex(column.header_color))
            self._size.set_value(column.size)
            self._spacing.set_value(column.spacing)
            if self._font.currentText() != column.font:
                self._font.setCurrentText(column.font)
            self._corner.set_current(column.corner)
            self._x.set_value(column.x)
            self._y.set_value(column.y)
            self._anchor.setText(column.anchor)
            self._distance.set_value(column.distance_scale)
            if column.mode == lay.SPACE:
                self._hud_row.hide()
                self._space_row.show()
            else:
                self._space_row.hide()
                self._hud_row.show()
            self._scale_mode.set_current("Auto" if column.scale_mode == lay.AUTO else "Manual", animate=False)
            self._show_lines()
            self._show_line()
            self._sketch.set_columns(self._layout.columns, self._column_index, self._sketch_values())
            built = bool(self._built())
            self._build_button.setText("Update in scene" if built else "Build in scene")
            self._columns_card.set_summary(f"{len(self._layout.columns)} column(s)")
            self._lines_card.set_summary(f"{len(column.lines)} line(s) · {column.name}")
        finally:
            self._loading = was

    def _show_lines(self) -> None:
        column = self._column()
        self._lines.blockSignals(True)
        try:
            self._lines.clear()
            for line in column.lines:
                item = qt.QtWidgets.QTreeWidgetItem(["", line.label, line.attribute, ""])
                item.setFlags(item.flags() | qt.QtCore.Qt.ItemFlag.ItemIsEditable
                              | qt.QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, qt.QtCore.Qt.CheckState.Checked if line.show
                                   else qt.QtCore.Qt.CheckState.Unchecked)
                if not line.color_keys:   # a gradient's color depends on the value: the "Now" column shows it
                    item.setForeground(1, qt.QtGui.QBrush(qt.QtGui.QColor.fromRgbF(*line.color)))
                item.setToolTip(0, "Shown — untick to hide the line (it keeps its attribute)")
                item.setToolTip(2, "Double click to type: node.attribute, without the rig's namespace")
                self._lines.addTopLevelItem(item)
            if column.lines:
                self._lines.setCurrentItem(self._lines.topLevelItem(self._line_index))
        finally:
            self._lines.blockSignals(False)
        self._lines.setFixedHeight(min(8, max(3, len(column.lines))) * 22 + 28)

    def _show_line(self) -> None:
        line = self._line()
        enabled = line is not None
        for widget in (self._color_mode, self._static_row, self._gradient_box, self._decimals):
            widget.setEnabled(enabled)
        if line is None:
            self._line_card.set_summary("no line picked")
            return
        gradient = bool(line.color_keys)
        self._color_mode.set_current("Gradient" if gradient else "Static", animate=False)
        if gradient:
            self._static_row.hide()
            self._gradient_box.show()
        else:
            self._gradient_box.hide()
            self._static_row.show()
        self._line_color.set_color(_hex(line.color))
        self._opacity.set_value(line.opacity)
        self._decimals.setCurrentText("auto" if line.decimals < 0 else str(line.decimals))
        if gradient:
            low, high = line.color_keys[0][0], line.color_keys[-1][0]
            if high <= low:
                high = low + 1.0
            self._range_low.set_value(low)
            self._range_high.set_value(high)
            self._ramp.set_stops([((value - low) / (high - low), qt.QtGui.QColor.fromRgbF(*color))
                                  for value, color in line.color_keys])
            self._ramp.set_steps(line.blend == lay.STEPS)
            self._blend.set_current("Steps" if line.blend == lay.STEPS else "Smooth", animate=False)
            self._fade.setChecked(len(line.opacity_keys) >= 2)
            if len(line.opacity_keys) >= 2:
                self._fade_low.set_value(line.opacity_keys[0][1])
                self._fade_high.set_value(line.opacity_keys[-1][1])
        self._line_card.set_summary(f"{line.label or line.attribute or 'empty'} · "
                                    f"{'gradient' if gradient else 'static'}")

    def _sketch_values(self) -> dict:
        values = getattr(self, "_values", None) or {}
        return {key: text for key, text in values.items()}

    # ------------------------------------------------------------------ editing columns

    def _pick_column(self, index: int) -> None:
        self._column_index = index
        self._line_index = 0
        self._show_all()

    def _set_column(self, **changes) -> None:
        if self._loading:
            return
        column = self._column()
        for name, value in changes.items():
            setattr(column, name, value)
        self._changed()

    def _add_column(self, name: str) -> None:
        name = name.strip() or "labels"
        taken = {column.name for column in self._layout.columns}
        base, number = name, 2
        while name in taken:
            name, number = f"{base}{number}", number + 1
        self._layout.columns.append(lay.Column(name=name, header=name.upper()))
        self._column_index = len(self._layout.columns) - 1
        self._changed()

    def _mirror_column(self) -> None:
        column = self._column()
        other = lay.mirror_column(column, rules.mirror)
        if other.name == column.name:
            self._say(f"“{column.name}” says no side (lf_ / rt_, _L / _R…): nothing to mirror", "error")
            return
        existing = self._layout.column(other.name)
        if existing is not None:
            self._layout.columns[self._layout.columns.index(existing)] = other
        else:
            self._layout.columns.append(other)
        self._column_index = self._layout.columns.index(other)
        self._changed()
        self._say(f"Mirrored into “{other.name}”", "done")

    def _duplicate_column(self) -> None:
        import copy
        other = copy.deepcopy(self._column())
        taken = {column.name for column in self._layout.columns}
        number = 2
        while f"{other.name}{number}" in taken:
            number += 1
        other.name = f"{other.name}{number}"
        self._layout.columns.insert(self._column_index + 1, other)
        self._column_index += 1
        self._changed()

    def _delete_column(self) -> None:
        if len(self._layout.columns) <= 1:
            self._say("The last column stays — a layout needs one", "error")
            return
        del self._layout.columns[self._column_index]
        self._column_index = max(0, self._column_index - 1)
        self._changed()

    def _column_menu(self, key: str, position) -> None:
        self._pick_column(int(key))
        menu = self._menu()
        menu.addAction("Rename…", self._rename_column)
        menu.addAction("Mirror to the other side", self._mirror_column)
        menu.addAction("Duplicate", self._duplicate_column)
        menu.addSeparator()
        menu.addAction("Remove", self._delete_column)
        menu.exec(position)

    def _rename_column(self) -> None:
        name, ok = qt.QtWidgets.QInputDialog.getText(self, "Rename the column", "Name", text=self._column().name)
        if ok and name.strip():
            self._set_column(name=name.strip())

    def _use_selected_anchor(self) -> None:
        from msl_tools.msl.tools.maya.labels import scene
        node = scene.selected_object()
        if not node:
            self._say("Select the object the column should stand at", "error")
            return
        self._set_column(anchor=lay.without_namespace(node, self._namespace()), mode=lay.SPACE)
        self._say(f"The column stands at {node}", "done")

    def _on_scale_mode(self, text: str) -> None:
        if self._loading:
            return
        mode = lay.AUTO if text == "Auto" else lay.MANUAL
        for column in self._layout.columns:     # one rule for the whole layout: it reads as one picture
            column.scale_mode = mode
        self._changed()

    # ------------------------------------------------------------------ editing lines

    def _on_line_picked(self, current, _previous) -> None:
        if self._loading or current is None:
            return
        self._line_index = self._lines.indexOfTopLevelItem(current)
        self._loading = True
        try:
            self._show_line()
        finally:
            self._loading = False

    def _on_line_edited(self, item, column: int) -> None:
        if self._loading:
            return
        index = self._lines.indexOfTopLevelItem(item)
        lines = self._column().lines
        if not 0 <= index < len(lines):
            return
        line = lines[index]
        if column == 0:
            line.show = item.checkState(0) == qt.QtCore.Qt.CheckState.Checked
        elif column == 1:
            line.label = item.text(1).strip()
        elif column == 2:
            line.attribute = lay.without_namespace(item.text(2).strip(), self._namespace())
        self._line_index = index
        qt.QtCore.QTimer.singleShot(0, self._changed)   # not while Qt is still inside the item's edit

    def _lines_from_channel_box(self) -> None:
        from msl_tools.msl.tools.maya.labels import scene
        paths = scene.selected_channels()
        if not paths:
            self._say("Pick channels in the Channel Box (with their objects selected) first", "error")
            return
        namespace = self._namespace()
        have = {line.attribute for line in self._column().lines}
        added = 0
        for path in paths:
            attribute = lay.without_namespace(path, namespace)
            if attribute in have:
                continue
            line = lay.Line(attribute=attribute)
            self._column().lines.append(line)
            have.add(attribute)
            added += 1
        self._line_index = len(self._column().lines) - 1
        self._changed()
        self._say(f"{added} line(s) added" if added else "Those channels are in the column already", "done")

    def _add_empty_line(self) -> None:
        self._column().lines.append(lay.Line())
        self._line_index = len(self._column().lines) - 1
        self._changed()
        item = self._lines.topLevelItem(self._line_index)
        if item is not None:
            self._lines.editItem(item, 2)

    def _delete_line(self) -> None:
        lines = self._column().lines
        if lines and 0 <= self._line_index < len(lines):
            del lines[self._line_index]
            self._line_index = max(0, self._line_index - 1)
            self._changed()

    def _move_line(self, step: int) -> None:
        lines = self._column().lines
        target = self._line_index + step
        if lines and 0 <= target < len(lines):
            lines[self._line_index], lines[target] = lines[target], lines[self._line_index]
            self._line_index = target
            self._changed()

    def _set_line(self, **changes) -> None:
        if self._loading:
            return
        line = self._line()
        if line is None:
            return
        for name, value in changes.items():
            setattr(line, name, value)
        self._changed()

    def _guess_range(self, line: lay.Line) -> tuple:
        try:
            from msl_tools.msl.tools.maya.labels import scene
            found = scene.value_range(lay.with_namespace(line.attribute, self._namespace()))
        except Exception:
            found = None
        return found or (0.0, 1.0)

    def _on_color_mode(self, text: str) -> None:
        if self._loading:
            return
        line = self._line()
        if line is None:
            return
        if text == "Gradient" and not line.color_keys:
            low, high = self._guess_range(line)
            line.color_keys = [(low, (0.2, 0.55, 1.0)), (high, (0.3, 0.9, 0.35))]
        elif text == "Static":
            line.color_keys = []
            line.opacity_keys = []
        self._changed()

    def _keys_from_ramp(self, stops) -> list:
        low, high = self._range_low.value(), self._range_high.value()
        if high <= low:
            high = low + 1.0
        return [(round(low + position * (high - low), 6), (round(color.redF(), 4), round(color.greenF(), 4),
                                                           round(color.blueF(), 4)))
                for position, color in stops]

    def _on_ramp(self, stops) -> None:
        if self._loading or self._line() is None:
            return
        self._line().color_keys = self._keys_from_ramp(stops)
        self._on_fade(changed=False)
        self._changed()

    def _on_range(self) -> None:
        if self._loading or self._line() is None:
            return
        self._line().color_keys = self._keys_from_ramp(self._ramp.stops())
        self._on_fade(changed=False)
        self._changed()

    def _on_fade(self, changed: bool = True) -> None:
        if self._loading or self._line() is None:
            return
        line = self._line()
        if self._fade.isChecked() and line.color_keys:
            low, high = line.color_keys[0][0], line.color_keys[-1][0]
            line.opacity_keys = [(low, self._fade_low.value()), (high, self._fade_high.value())]
        else:
            line.opacity_keys = []
        if changed:
            self._changed()

    # ------------------------------------------------------------------ values now

    def _show_values(self) -> None:
        """Reads every line's value (the picked column's in the list, all of them for the sketch)."""
        try:
            from msl_tools.msl.tools.maya.labels import scene
        except Exception:
            return
        namespace = self._namespace()
        values = {}
        try:
            for column_index, column in enumerate(self._layout.columns):
                for line_index, line in enumerate(column.lines):
                    path = lay.with_namespace(line.attribute, namespace)
                    values[(column_index, line_index)] = scene.value_text(path, line.decimals)
        except Exception:
            return
        if values == getattr(self, "_values", None):
            return
        self._values = values
        self._lines.blockSignals(True)
        try:
            for line_index in range(self._lines.topLevelItemCount()):
                item = self._lines.topLevelItem(line_index)
                item.setText(3, values.get((self._column_index, line_index), "-"))
        finally:
            self._lines.blockSignals(False)
        line = self._line()
        if line is not None and line.color_keys:
            number = scene.value_number(lay.with_namespace(line.attribute, namespace))
            low, high = self._range_low.value(), self._range_high.value()
            self._ramp.set_marker(None if number is None or high <= low else (number - low) / (high - low))
        self._sketch.set_columns(self._layout.columns, self._column_index, values)

    # ------------------------------------------------------------------ the scene

    def _refresh_namespaces(self) -> None:
        try:
            from msl_tools.msl.tools.maya.labels import scene
            names = scene.namespaces()
        except Exception:
            names = []
        wanted = self._layout.namespace or NO_NAMESPACE
        self._loading, was = True, self._loading
        try:
            self._namespaces.clear()
            self._namespaces.addItem(NO_NAMESPACE)
            self._namespaces.addItems(names)
            if wanted != NO_NAMESPACE and wanted not in names:
                self._namespaces.addItem(wanted)
            self._namespaces.setCurrentText(wanted)
        finally:
            self._loading = was

    def build_in_scene(self) -> None:
        """Builds the layout into the scene for the namespace picked (one undo step)."""
        problems = lay.problems(self._layout)
        if any("at no object" in problem for problem in problems):
            self._say(next(problem for problem in problems if "at no object" in problem), "error")
            return
        from msl_tools.msl.tools.maya.labels import scene
        try:
            result = scene.build(self._layout, self._namespace())
        except Exception as error:   # the plug-in can't be loaded, ...
            self._say(str(error), "error")
            return
        self._show_all()
        if result.missing:
            self._say(f"Built — not found: {', '.join(result.missing[:3])}"
                      + (f" and {len(result.missing) - 3} more" if len(result.missing) > 3 else ""), "error")
        else:
            self._say(f"Built: {result.group.rsplit('|', 1)[-1]} — edits now show in the viewport at once", "done")

    def _update_scene(self) -> None:
        """The live update: the built layout follows the edit, outside the undo queue."""
        if not self._built():
            return
        try:
            from msl_tools.msl.tools.maya.labels import scene
            scene.build(self._layout, self._namespace(), undo=False)
        except Exception as error:
            self._say(f"The scene couldn't follow: {error}", "error")

    # ------------------------------------------------------------------ layouts

    def _menu(self) -> "qt.QtWidgets.QMenu":
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setToolTipsVisible(True)
        return menu

    def _submenu(self, menu, title: str) -> "qt.QtWidgets.QMenu":
        """A submenu kept by its menu (one made by menu.addMenu(title) was deleted too early, Maya 2026)."""
        sub = make_rounded_popup(qt.QtWidgets.QMenu(title, menu))
        menu.addMenu(sub)
        kept = getattr(menu, "_kept_submenus", None)
        if kept is None:
            kept = menu._kept_submenus = []
        kept.append(sub)
        return sub

    def _saved(self) -> dict:
        """The saved layouts as plain data: name -> layout dict."""
        return dict(self._config.data.get("layouts") or {})

    def layouts_menu(self) -> "qt.QtWidgets.QMenu":
        """The header button's menu (returned, so a test can look at it)."""
        menu = self._menu()
        saved = self._saved()
        menu.addAction("SAVED LAYOUTS").setEnabled(False)
        if not saved:
            menu.addAction("none yet").setEnabled(False)
        for name in sorted(saved, key=str.lower):
            menu.addAction(name, lambda name=name: self._load_saved(name))
        menu.addAction("Save this layout as…", self._save_as)
        if saved:
            remove = self._submenu(menu, "Remove a saved layout")
            for name in sorted(saved, key=str.lower):
                remove.addAction(name, lambda name=name: self._remove_saved(name))
        menu.addSeparator()
        menu.addAction("IN THE SCENE").setEnabled(False)
        rigs = []
        try:
            from msl_tools.msl.tools.maya.labels import scene
            rigs = scene.rigs()
        except Exception:
            pass
        if rigs:
            read = self._submenu(menu, "Read a layout back from the scene")
            for group in rigs:
                read.addAction(group.rsplit("|", 1)[-1], lambda group=group: self._read_back(group))
        built = self._built()
        action = menu.addAction("Remove this layout from the scene", self._remove_from_scene)
        action.setEnabled(bool(built))
        menu.addSeparator()
        menu.addAction("FILES").setEnabled(False)
        menu.addAction("Write to a file…", self._write_file)
        menu.addAction("Read from a file…", self._read_file)
        menu.addSeparator()
        menu.addAction("Start a new layout", self._new_layout)
        return menu

    def _open_layouts_menu(self) -> None:
        button = self._layouts_button
        self.layouts_menu().exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height())))

    def _take(self, layout: lay.Layout, said: str) -> None:
        self._layout = layout
        if not self._layout.columns:
            self._layout.columns.append(lay.Column())
        self._column_index = self._line_index = 0
        self._refresh_namespaces()
        self._settings["layout"] = lay.to_dict(self._layout)
        self._show_all()
        self._say(said, "done")

    def _load_saved(self, name: str) -> None:
        data = self._saved().get(name)
        if data:
            self._take(lay.from_dict(data), f"Layout “{name}” — build it to see it")

    def _save_as(self) -> None:
        name, ok = qt.QtWidgets.QInputDialog.getText(self, "Save the layout", "Name", text=self._layout.name)
        if not ok or not name.strip():
            return
        self._layout.name = name.strip()
        saved = self._saved()
        saved[self._layout.name] = lay.to_dict(self._layout)
        self._config["layouts"] = saved
        self._changed(live=False)
        self._say(f"Saved as “{self._layout.name}”", "done")

    def _remove_saved(self, name: str) -> None:
        saved = self._saved()
        saved.pop(name, None)
        self._config["layouts"] = saved
        self._say(f"“{name}” removed from the saved layouts", "done")

    def _read_back(self, group: str) -> None:
        from msl_tools.msl.tools.maya.labels import scene
        try:
            self._take(scene.capture(group), f"Read back from {group.rsplit('|', 1)[-1]}")
        except Exception as error:
            self._say(str(error), "error")

    def _remove_from_scene(self) -> None:
        group = self._built()
        if group:
            from msl_tools.msl.tools.maya.labels import scene
            scene.remove(group)
            self._show_all()
            self._say("Taken out of the scene (Ctrl+Z puts it back); the layout stays here", "done")

    def _write_file(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Write the layout", self._layout.name + ".json",
                                                                 "Labels layout (*.json)")
        if path:
            lay.save(path, self._layout)
            self._say(f"Written: {Path(path).name}", "done")

    def _read_file(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(self, "Read a layout", "", "Labels layout (*.json)")
        if path:
            try:
                self._take(lay.load(path), f"Read: {Path(path).name}")
            except ValueError as error:
                self._say(str(error), "error")

    def _new_layout(self) -> None:
        self._take(_starting_layout(), "A new layout")

    # ------------------------------------------------------------------ on screen

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_namespaces()
        self._show_all()
        self._values_timer.start()
        self._show_values()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._values_timer.stop()
        if self._live.isActive():       # an edit still on its way reaches the scene
            self._live.stop()
            self._update_scene()
