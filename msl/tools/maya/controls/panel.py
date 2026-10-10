# tools/maya/controls/panel.py
"""The Controls tool's panel: cards that fold — COLOR in panel_color.py —, CONTROL first — the shape library (search, a
category, a grid of thumbnails drawn from the shapes, a preview that turns), the shape tools
(turn, smaller / bigger, replace, save the selected curves as a shape) and how a new control is
made (name, size, facing axis, offsets, chain, side color)."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.controls import shapes as shape_data
from msl_tools.msl.tools.maya.controls import colors as color_data
from msl_tools.msl.tools.maya.controls.naming import DEFAULT_TEMPLATE, control_name
from msl_tools.msl.tools.maya.controls.panel_color import _ColorMixin
from msl_tools.msl.tools.maya.controls.preview import ShapeView, thumbnail
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField, Swatches, TurnButton
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.tools.maya.rename.buttons import QuickButton, ToggleIconButton
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces.stable_scroll_area import StableScrollArea
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

StylesheetBuilder.register_template(Path(__file__).with_name("controls.qss"))

ALL = "All"
OFFSET_MODES = ("None", "Groups", "Matrix")
DRIVES = ("None", "Shape", "Constrain", "Matrix")
SHAPES_FILTER = "MSL control shapes (*.json)"
THUMB = 38


class ShapeGrid(qt.QtWidgets.QListWidget):
    """The shapes as thumbnails in rows (QListWidget's icon mode), tinted by qproperty
    thumbColor; the name is the tooltip."""

    thumbColor = color_property("_thumb", "_retint")

    def __init__(self, parent=None):
        super().__init__(parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        self._thumb = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)
        self._shapes = []
        self.setObjectName("controlsGrid")
        self.setViewMode(qt.QtWidgets.QListView.ViewMode.IconMode)
        self.setResizeMode(qt.QtWidgets.QListView.ResizeMode.Adjust)
        self.setMovement(qt.QtWidgets.QListView.Movement.Static)
        self.setIconSize(qt.QtCore.QSize(THUMB, THUMB))
        self.setGridSize(qt.QtCore.QSize(THUMB + 8, THUMB + 8))
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setWrapping(True)
        self.setHorizontalScrollBarPolicy(qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(qt.QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)

    def set_shapes(self, shapes: list, current: str) -> None:
        self._shapes = list(shapes)
        self.blockSignals(True)
        self.clear()
        for shape in self._shapes:
            item = qt.QtWidgets.QListWidgetItem()
            item.setData(qt.QtCore.Qt.ItemDataRole.UserRole, shape.name)
            item.setToolTip(shape.title() + (" — yours" if shape.user else ""))
            item.setSizeHint(qt.QtCore.QSize(THUMB + 8, THUMB + 8))
            self.addItem(item)
            if shape.name == current:
                item.setSelected(True)
                self.setCurrentItem(item)
        self.blockSignals(False)
        self._retint()

    def _retint(self) -> None:
        ratio = self.devicePixelRatioF()
        for index, shape in enumerate(self._shapes):
            item = self.item(index)
            if item is not None:
                item.setIcon(qt.QtGui.QIcon(thumbnail(shape.curves, THUMB, self._thumb, ratio)))

    def current_name(self) -> str:
        item = self.currentItem()
        return item.data(qt.QtCore.Qt.ItemDataRole.UserRole) if item is not None else ""


class ControlsPanel(_ColorMixin, qt.QtWidgets.QWidget):
    """The tool (shown in a ControlsWindow). Settings and the user's shapes: configsMayaMng
    "controls" (`settings`, `shapes`).

    Signals:
        status_changed(str, str) — what the panel says (text, "" / "done" / "error"): the header.
    """

    status_changed = qt.QtCore.Signal(str, str)

    TOOL_NAME = "controls"
    DEFAULTS = {"shape": "circle", "category": ALL, "template": DEFAULT_TEMPLATE, "size": 1.0, "fit": True,
                "axis": "X", "offsets": "Groups", "offset_names": "offset", "chain": True, "side_color": True,
                "drive": "None", "own_color": "", "ghost": True,
                "folded": {"control": False}}

    def __init__(self, parent=None):
        super().__init__(parent)
        config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": dict(self.DEFAULTS)})
        self._config = config
        self._settings = config["settings"]
        self.library = shape_data.ShapeLibrary(config["shapes"])
        self._loading = True
        self._build()
        self._apply_settings()
        self._connect()
        self._loading = False
        self._refresh_grid()

    # ------------------------------------------------------------------ building

    def _build(self) -> None:
        icons = UiResources().iconManager
        # the search sits in the card's heading: the row under it is the categories' alone
        self._search = qt.QtWidgets.QLineEdit()
        self._search.setObjectName("controlsSearch")
        self._search.setPlaceholderText("Find a shape")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(120)
        card = self._control_card = FoldingCard("CONTROL", icons.get_icon("controls", sub_folder="actions"),
                                                extras=[self._search])
        self._categories = ChipBar(checkable=True)
        self._categories.setObjectName("controlsCategories")
        self._categories.set_chips([(name, name, "") for name in (ALL,) + shape_data.CATEGORIES])
        head = qt.QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self._categories, 1)

        self._grid = ShapeGrid()
        self._grid.setFixedHeight((THUMB + 8) * 3 + 6)
        self._view = ShapeView()
        self._view.setFixedSize(132, (THUMB + 8) * 3 + 6 - 28)
        # the picked shape and, under it, what makes it
        self._create = qt.QtWidgets.QPushButton("Create")
        self._create.setProperty("primary", True)
        self._create.setObjectName("controlsCreate")
        self._create.setFixedWidth(132)
        self._create.setToolTip("A control on every selected object (nothing selected: one at the origin) · "
                                "double click a shape does the same")
        picked = qt.QtWidgets.QVBoxLayout()
        picked.setSpacing(6)
        picked.addWidget(self._view)
        picked.addWidget(self._create)
        shelf = qt.QtWidgets.QHBoxLayout()
        shelf.setSpacing(6)
        shelf.addWidget(self._grid, 1)
        shelf.addLayout(picked)

        # how a new control is made — its size, "fit" and the axis it faces live in the preview
        self._template = qt.QtWidgets.QLineEdit()
        self._template.setObjectName("controlsTemplate")
        self._template.setPlaceholderText(DEFAULT_TEMPLATE)
        self._template.setToolTip("The new control's name: {name} = what it is made for (its side word and "
                                  "suffix taken off), {side} = lf / rt / mid from where it stands, {#} = 01, 02…")
        self._size = DragNumberField(1.0, 0.01, 1000.0, 0.1, width=40)
        self._size.setObjectName("controlsViewSize")
        self._size.setToolTip("Size of a new control — the wheel over the preview, drag with the middle mouse "
                              "button, Up / Down (Shift: ×10)")
        self._fit = ToggleIconButton(icons.get_icon("frame_fit", sub_folder="actions"), "Fit to what is selected",
                                     "The size times the target's own: a joint's radius, an object's bounding box")
        self._fit.setObjectName("controlsToggle")
        self._chain = ToggleIconButton(icons.get_icon("branch", sub_folder="actions"), "Chain",
                                       "Each control under the control of the joint above its own (FK)")
        self._chain.setObjectName("controlsToggle")
        self._side_color = ToggleIconButton(icons.get_icon("mirror_sides", sub_folder="actions"), "Side color",
                                            "Color by where it stands: left blue, right red, middle yellow · "
                                            "off: your color (the square beside it), or none")
        self._side_color.setObjectName("controlsToggle")
        # the color a new control gets — as the preview draws it; a click picks one of your own
        self._color_chip = Swatches(side=18, gap=0, columns=1)
        self._color_chip.setObjectName("controlsViewColor")
        self._color_chip.setFixedSize(self._color_chip.sizeHint())
        self._view.set_corner_widgets([self._size, self._fit], [self._side_color, self._color_chip])
        naming = qt.QtWidgets.QHBoxLayout()
        naming.setSpacing(4)
        naming.addWidget(self._caption("Name"))
        naming.addWidget(self._template, 1)
        naming.addWidget(self._chain)
        self._ghost = ToggleIconButton(icons.get_icon("eye", sub_folder="actions"), "Ghost in the viewport",
                                       "What Create would make, shown in Maya's viewport on the selected "
                                       "objects before anything is made: it follows the shape, size, axis and "
                                       "color here. Not part of your scene: it isn't saved and isn't in undo; "
                                       "a click on a ghost selects the object it stands for")
        self._ghost.setObjectName("controlsToggle")
        naming.addWidget(self._ghost)

        self._offsets = SegmentedControl(list(OFFSET_MODES), "Groups")
        self._offsets.setToolTip("Zero the NEW control: Groups = groups above it · Matrix = through its "
                                 "offsetParentMatrix, no group · None (controls that exist: the violet buttons "
                                 "of SELECTED)")
        self._offset_names = qt.QtWidgets.QLineEdit()
        self._offset_names.setObjectName("controlsOffsetNames")
        self._offset_names.setPlaceholderText("offset")
        self._offset_names.setToolTip("The groups above the control, top first, by their suffix: "
                                      "\"offset\" or \"grp, offset, driven\" for three — also what "
                                      "“Zero with groups” of SELECTED makes")
        # hidden on None / Matrix, its room kept: the row doesn't jump when the mode changes
        policy = self._offset_names.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self._offset_names.setSizePolicy(policy)
        making = qt.QtWidgets.QHBoxLayout()
        making.setSpacing(4)
        making.addWidget(self._caption("Zero"))
        making.addWidget(self._offsets)
        making.addWidget(self._offset_names, 1)

        # what the new control does to the object it is made for
        self._drive = SegmentedControl(list(DRIVES), "None")
        self._drive.setToolTip("What a new control does to the object it is made for:\n"
                               "None — it only stands there\n"
                               "Shape — no new object: the curve becomes the object's own shape (a joint you pick "
                               "by its curve)\n"
                               "Constrain — the object follows it through parent + scale constraints\n"
                               "Matrix — the object follows it through its offsetParentMatrix: no constraint node, "
                               "its channels read zero and stay free")
        driving = qt.QtWidgets.QHBoxLayout()
        driving.setSpacing(4)
        driving.addWidget(self._caption("Drive"))
        driving.addWidget(self._drive)
        driving.addStretch(1)

        card.body_layout.addLayout(head)
        card.body_layout.addLayout(shelf)
        card.body_layout.addLayout(naming)
        card.body_layout.addLayout(making)
        card.body_layout.addLayout(driving)

        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(10, 8, 4, 8)
        column.setSpacing(6)
        column.addWidget(self._selected_tools())
        column.addWidget(card)
        column.addWidget(self._color_card())
        column.addStretch(1)
        scroll = StableScrollArea()
        scroll.setObjectName("controlsScroll")
        scroll.setWidget(body)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def _selected_tools(self) -> FoldingCard:
        """SELECTED: everything that works on the controls selected in the scene, on top of the window
        — two rows of icon buttons in groups, each group in its own color (the `tone` property)."""
        icons = UiResources().iconManager
        card = self._selected_card = FoldingCard("SELECTED", icons.get_icon("select_all", sub_folder="actions"))

        def tool(icon, tone, text, tooltip, menu=False):
            button = self._tool_button(icon, text, tooltip)
            button.setProperty("tone", tone)
            if menu:
                button.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            return button

        # the shape itself (orange)
        self._turns = {}
        for axis in shape_data.AXES:
            self._turns[axis] = TurnButton(axis, f"Turn about {axis}\nThe selected controls' shapes 90° about "
                                                 f"their own {axis} (Shift: −90°)")
            self._turns[axis].setObjectName("controlsTool")
        self._shrink = tool("shrink", "orange", "Smaller", "The selected controls' shapes smaller (×0.8)")
        self._grow = tool("grow", "orange", "Bigger", "The selected controls' shapes bigger (×1.25)")
        self._cvs = tool("cvs", "orange", "Edit the shape", "The selected controls' CVs get selected: move, turn "
                         "and scale the SHAPE with Maya's own tools, the control's channels stay as they are · "
                         "again: back to the controls")
        # another shape (blue)
        self._replace = tool("replace", "blue", "Replace", "The selected controls get the picked shape — as big as "
                                                           "theirs, same color and line width")
        self._add_shape = tool("add", "blue", "Add the picked shape", "The picked shape BESIDE what the selected "
                                                                      "controls have")
        self._copy_shape = tool("copy", "blue", "Copy the shape", "Keep the selected control's shape to paste onto "
                                                                  "others")
        self._paste_shape = tool("paste", "blue", "Paste the shape", "The selected controls get the copied shape as "
                                 "it is — same size, same place about the pivot; each keeps its own color")
        self._combine = tool("merge", "blue", "Combine", "The selected curves become ONE control, the last "
                                                         "selected — staying where they are, colors kept")
        # the other side (teal)
        self._mirror = tool("mirror_shape", "teal", "Mirror", "A mirrored copy of each selected control on the "
                            "other side (lf_ ↔ rt_, _L ↔ _R): its zero groups too, under the other side's parent; "
                            "when that control is there already, its shape is made the mirror of this one\n"
                            "Right click: across Y / Z, or flip in place", menu=True)
        self._mirror_update = tool("mirror_update", "teal", "Shape to the other side", "Only the SHAPE: the other "
                                   "side's control (it is there already) gets the mirror of the selected one's "
                                   "shape — fix one side, carry it over; its color, place and groups stay. Either "
                                   "way, by what is selected\nRight click: across Y / Z", menu=True)
        # zero (violet)
        self._zero_groups_button = tool("zero_out", "violet", "Zero with groups", "Groups above each selected "
                                        "control where it stands (the suffixes of the Zero row below), its "
                                        "translate / rotate read 0")
        self._zero_matrix_button = tool("zero_matrix", "violet", "Zero into the matrix", "What the selected "
                                        "controls' channels say moves into their offsetParentMatrix: they read 0, "
                                        "no group")
        self._matrix_back_button = tool("matrix_out", "violet", "Out of the matrix", "The other way: what the "
                                        "offsetParentMatrix holds back into the channels, the matrix empty")
        # show and select (yellow)
        self._on_top_button = tool("on_top", "yellow", "Always on top", "The selected controls' curves drawn "
                                                                        "through the geometry — on / off")
        self._select_below = tool("branch", "yellow", "Controls under the selection", "Select every control "
                                                                                      "(curve) under what is selected")
        self._select_all = tool("select_all", "yellow", "Controls in the scene", "Select every control (curve) in "
                                                                               "the scene")
        # into the library (green)
        self._capture = tool("bookmark_add", "green", "Save as a shape", "Save the selected curves as a shape of "
                                                                         "yours (it goes under Mine)")

        rows = (((self._turns["X"], self._turns["Y"], self._turns["Z"], self._shrink, self._grow, self._cvs),
                 (self._replace, self._add_shape, self._copy_shape, self._paste_shape, self._combine),
                 (self._mirror, self._mirror_update)),
                ((self._zero_groups_button, self._zero_matrix_button, self._matrix_back_button),
                 (self._on_top_button, self._select_below, self._select_all),
                 (self._capture,)))
        for groups in rows:
            line = qt.QtWidgets.QHBoxLayout()
            line.setSpacing(3)
            for index, group in enumerate(groups):
                if index:
                    rule = qt.QtWidgets.QFrame()
                    rule.setObjectName("controlsRule")
                    rule.setFixedSize(1, 16)
                    line.addSpacing(2)
                    line.addWidget(rule)
                    line.addSpacing(2)
                for button in group:
                    line.addWidget(button)
            line.addStretch(1)
            card.body_layout.addLayout(line)
        return card

    def _tool_button(self, icon: str, text: str, tooltip: str) -> QuickButton:
        button = QuickButton(UiResources().iconManager.get_icon(icon, sub_folder="actions"), text,
                             f"{text}\n{tooltip}", icon_size=16)
        button.setObjectName("controlsTool")
        return button

    @staticmethod
    def _caption(text: str) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("controlsCaption")
        return label

    def _connect(self) -> None:
        self._search.textChanged.connect(lambda _text: self._refresh_grid())
        self._categories.clicked.connect(self._on_category)
        self._grid.itemSelectionChanged.connect(self._on_shape_picked)
        self._grid.itemDoubleClicked.connect(lambda _item: self.create())
        self._grid.customContextMenuRequested.connect(self._on_grid_menu)
        for axis, button in self._turns.items():
            button.clicked.connect(lambda _checked=False, axis=axis: self._turn(axis))
        self._shrink.clicked.connect(lambda: self._resize(0.8))
        self._grow.clicked.connect(lambda: self._resize(1.25))
        self._replace.clicked.connect(self._on_replace)
        self._capture.clicked.connect(self._on_capture)
        self._mirror.clicked.connect(lambda: self._mirror_to_other("X"))
        self._mirror.customContextMenuRequested.connect(self._on_mirror_menu)
        self._mirror_update.clicked.connect(lambda: self._mirror_shapes("X"))
        self._mirror_update.customContextMenuRequested.connect(self._on_mirror_update_menu)
        self._cvs.clicked.connect(self._on_cvs)
        self._copy_shape.clicked.connect(self._on_copy_shape)
        self._paste_shape.clicked.connect(self._on_paste_shape)
        self._add_shape.clicked.connect(self._on_add_shape)
        self._combine.clicked.connect(self._on_combine)
        self._zero_groups_button.clicked.connect(self._zero_groups)
        self._zero_matrix_button.clicked.connect(self._zero_matrix)
        self._matrix_back_button.clicked.connect(self._matrix_back)
        self._on_top_button.clicked.connect(self._on_top)
        self._select_below.clicked.connect(lambda: self._select_controls(True))
        self._select_all.clicked.connect(lambda: self._select_controls(False))
        self._drive.current_changed.connect(self._save)
        for axis, button in self._turns.items():
            self._watch_hover(button, f"turn_{axis}")
        for key, button in (("shrink", self._shrink), ("grow", self._grow), ("replace", self._replace),
                            ("add", self._add_shape), ("paste", self._paste_shape), ("mirror", self._mirror),
                            ("mirror_update", self._mirror_update), ("zero_groups", self._zero_groups_button),
                            ("zero_matrix", self._zero_matrix_button), ("matrix_back", self._matrix_back_button)):
            self._watch_hover(button, key)
        self._create.clicked.connect(self.create)
        for widget in (self._template, self._offset_names):
            widget.textEdited.connect(self._save)
        self._size.value_changed.connect(self._save)
        for toggle in (self._fit, self._chain, self._side_color, self._ghost):
            toggle.toggled.connect(self._save)
        self._view.axis_picked.connect(self._on_axis)
        self._color_chip.clicked.connect(lambda _key: self._pick_own_color())
        self._color_chip.menu_requested.connect(self._on_color_chip_menu)
        self._view.size_stepped.connect(self._size._nudge)
        self._selected_card.toggled.connect(lambda opened: self._save_folded("selected", opened))
        self._offsets.current_changed.connect(self._on_offsets)
        self._control_card.toggled.connect(lambda opened: self._save_folded("control", opened))
        self._control_card.toggled.connect(self._search.setVisible)
        self._connect_color()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_palette()
        self._watch_selection(True)
        self._refresh_live()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._refresh_live()

    def hideEvent(self, event) -> None:
        self._watch_selection(False)
        self._clear_ghost()
        super().hideEvent(event)

    # ------------------------------------------------------------------ the live preview

    _selection_callback = None
    WATCHED = ("SelectionChanged", "DragRelease", "Undo", "Redo", "timeChanged", "SceneSaved")   # what moves the ghost

    def _watch_selection(self, on: bool) -> None:
        """Maya tells the panel when the selection changes (or what is selected moved) — only while
        the panel is on screen."""
        try:
            import maya.api.OpenMaya as om
        except ImportError:
            return
        for callback in self._selection_callback or []:
            try:
                om.MMessage.removeCallback(callback)
            except RuntimeError:
                pass
        self._selection_callback = None
        if on:
            self._live_timer = getattr(self, "_live_timer", None) or qt.QtCore.QTimer(self)
            self._live_timer.setSingleShot(True)
            self._live_timer.setInterval(60)
            try:
                self._live_timer.timeout.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._live_timer.timeout.connect(self._refresh_live)
            known = set(om.MEventMessage.getEventNames())
            self._selection_callback = [om.MEventMessage.addEventCallback(name, self._on_selection)
                                        for name in self.WATCHED if name in known]

    def _on_selection(self, *_args) -> None:
        try:
            self._live_timer.start()
        except RuntimeError:      # the panel is gone, Maya still calls
            pass

    def _own_rgb(self):
        try:
            return color_data.from_hex(self._settings.get("own_color") or "")
        except ValueError:
            return None

    def _control_rgb(self, position=None):
        """The color a new control standing at `position` gets: its side's, your own, or None (Maya's)."""
        if self._side_color.isChecked():
            side = self._sides().of(position) if position is not None else "center"
            return color_data.SIDE_COLORS.get(side, color_data.SIDE_COLORS["center"])
        return self._own_rgb()

    def _refresh_live(self) -> None:
        """The preview imitates what Create would make of the selection NOW — or, while a button of
        SELECTED is hovered, what that button would do to the selected control."""
        if self._loading:
            return
        try:
            if self._hovered_action:
                self._show_action()
            else:
                self._draw_live()
        except Exception as error:      # a preview must never take the tool down — but it must say why
            self._report("The preview couldn't follow the selection", error)

    def _report(self, what: str, error: Exception) -> None:
        """A failure of the preview / the ghost: in the header (once per message) and, in full, in
        Maya's Script Editor."""
        import traceback
        text = f"{what} — {type(error).__name__}: {str(error).strip()}"
        if text != getattr(self, "_reported", ""):
            self._reported = text
            traceback.print_exc()
            self._say(text, "error")

    def _color_for(self, rgb):
        return qt.QtGui.QColor.fromRgbF(*rgb[:3]) if rgb is not None else "plain"

    def _draw_live(self) -> None:
        """Every selected object (a joint with its bones, a box) with the control it would get: at its
        real size, in its color, its zero groups as frames around it, chained controls joined by a
        line; the first one's name on top; the button says how many."""
        targets, looks = [], []
        try:
            from maya import cmds as _maya
            in_maya = True
        except ImportError:
            in_maya = False             # no Maya here: the shape alone
        if in_maya:
            try:
                from msl_tools.msl.tools.maya.controls import ghost, scene
                if ghost.redirect_selection():
                    return      # a picked ghost became its object: Maya tells of the new selection
                targets = scene.selected_transforms()
                looks = scene.targets_look(targets)
            except Exception as error:
                self._report("Couldn't read the selection", error)
        look = looks[0] if looks else None
        position = look["position"] if look else None
        rgb = self._control_rgb(position)
        by_side = self._side_color.isChecked()
        self._color_chip.set_items([("color", rgb, ("The color of its side — " if by_side else "Your color — "
                                                    if rgb is not None else "No color: Maya's default — ") +
                                     "click: pick your own · right click: more")])
        drive = self._drive.current()
        mode = self._offsets.current()
        fit = self._fit.isChecked()
        count = len(targets)
        if look and drive == "Shape":
            title, sub = look["name"], "gets the curve itself"
        else:
            title = control_name(self._template.text().strip(), look["name"] if look else "", position,
                                 self._sides(), 1)
            if count > 1:
                title += f"  +{count - 1}"
            parts = [" › ".join(self._offset_suffixes()) + " ›" if mode == "Groups" else
                     "matrix ›" if mode == "Matrix" else ""]
            if look and drive != "None":
                parts.append("→ " + drive.lower())
            sub = "  ".join(part for part in parts if part)
        self._view.set_title(title, sub)
        items = [{"look": each, "reach": self._size.value() * (each["fit"] if fit else 1.0),
                  "color": self._color_for(self._control_rgb(each["position"])), "matrix": each["matrix"],
                  "parent": each["parent"]} for each in looks] or [{"color": self._color_for(rgb)}]
        self._view.set_action(None, None)
        self._view.set_zero("none" if drive == "Shape" else mode.lower(), len(self._offset_suffixes()))
        self._view.set_scene(items, chain=self._chain.isChecked() and drive != "Shape")
        self._create.setText("Create" if not count else f"Shape onto {count}" if drive == "Shape"
                             else f"Create {count}")
        self._update_ghost(targets)

    # ---- the ghost: the same, in Maya's own viewport

    _made = frozenset()      # what the last Create made / shaped: no ghost on it while it stays selected

    def _update_ghost(self, targets: list) -> None:
        try:
            from maya import cmds as _maya      # no Maya here: no ghost
        except ImportError:
            return
        from msl_tools.msl.tools.maya.controls import ghost
        if self._made and not set(targets) <= self._made:
            self._made = frozenset()
        # a selected CONTROL is there to be worked on (SELECTED), not to get a control of its own
        from msl_tools.msl.tools.maya.controls import scene
        targets = [target for target in targets if not scene.curve_shapes(target)]
        if not (self._ghost.isChecked() and targets and self.isVisible()) or self._made:
            ghost.clear()
            return
        try:
            ghost.show(self._picked_shape(), targets, self._size.value(), self._view.axis(), self._fit.isChecked(),
                       self._control_rgb)
        except Exception as error:
            self._report("The ghost couldn't be drawn", error)
            ghost.clear()

    def _clear_ghost(self) -> None:
        try:
            from msl_tools.msl.tools.maya.controls import ghost
            ghost.clear()
        except (ImportError, RuntimeError):
            pass

    # ---- what a button of SELECTED would do, shown in the preview while it is hovered

    _hovered_action = ""

    def _watch_hover(self, button, key: str) -> None:
        button.hovered.connect(lambda on, key=key: self._on_action_hover(key, on))
        button.clicked.connect(self._after_action_click)

    def _on_action_hover(self, key: str, on: bool) -> None:
        if on or self._hovered_action == key:
            self._hovered_action = key if on else ""
            self._refresh_live()

    def _after_action_click(self, *_args) -> None:
        # the click changed the control: show the next click's effect once Maya has done its part
        qt.QtCore.QTimer.singleShot(0, self._refresh_live)

    def _show_action(self) -> None:
        key = self._hovered_action
        try:
            from msl_tools.msl.tools.maya.controls import scene
            holders = scene.selected_transforms() if key.startswith(("zero", "matrix")) else \
                scene.controls_in_selection()
            before = scene.read_curves(holders[0]) if holders else []
            rgb = scene.read_color(holders[0])[0] if holders else None
        except (ImportError, RuntimeError, ValueError):
            holders, before, rgb = [], [], None
        if not holders:
            self._draw_live()
            return
        reach = max([abs(value) for curve in before for point in curve.points for value in point] or [1.0]) or 1.0
        picked = shape_data.scaled(shape_data.oriented(self._picked_shape().curves, self._view.axis()), reach)
        back = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        after, zero, text = before, None, ""
        if key.startswith("turn_"):
            after = shape_data.turned(before, key[-1], -90.0 if back else 90.0)
            text = f"turn {'−' if back else ''}90° about {key[-1]}"
        elif key in ("shrink", "grow"):
            after = shape_data.scaled(before, 0.8 if key == "shrink" else 1.25)
            text = "×0.8" if key == "shrink" else "×1.25"
        elif key == "replace":
            after, text = picked, "gets " + self._picked_shape().title().lower()
        elif key == "add":
            after, text = before + picked, "plus " + self._picked_shape().title().lower()
        elif key == "paste" and ControlsPanel._copied_shape:
            after, text = list(ControlsPanel._copied_shape), "gets the copied shape"
        elif key in ("mirror", "mirror_update"):
            after = [shape_data.Curve([(-x, y, z) for x, y, z in curve.points], curve.degree, curve.closed)
                     for curve in before]
            text = "as the other side gets it"
        elif key == "zero_groups":
            names = self._offset_suffixes()
            zero, text = ("groups", len(names)), " › ".join(names) + " › above it"
        elif key == "zero_matrix":
            zero, text = ("matrix", 1), "zeroed in its matrix"
        elif key == "matrix_back":
            text = "back in its channels"
        else:
            self._draw_live()
            return
        if not before and zero is None:
            self._draw_live()
            return
        name = holders[0].rpartition("|")[2] + (f"  +{len(holders) - 1}" if len(holders) > 1 else "")
        self._view.set_title(name, text)
        self._view.set_action(before, after, self._color_for(rgb) if rgb is not None else None, zero)

    def _pick_own_color(self) -> None:
        start = qt.QtGui.QColor.fromRgbF(*(self._own_rgb() or self._control_rgb() or (1.0, 1.0, 1.0)))
        picked = qt.QtWidgets.QColorDialog.getColor(start, self, "The color of new controls")
        if picked.isValid():
            self._settings["own_color"] = picked.name()
            self._side_color.setChecked(False)
            self._save()

    def _set_color_mode(self, mode: str) -> None:
        if mode == "none":
            self._settings["own_color"] = ""
        self._side_color.setChecked(mode == "side")
        self._save()

    def _on_color_chip_menu(self, _key: str, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.addAction("Your color…", self._pick_own_color)
        menu.addAction("By side: left blue · right red · middle yellow", lambda: self._set_color_mode("side"))
        menu.addAction("No color — Maya's default", lambda: self._set_color_mode("none"))
        menu.exec(position)

    # ------------------------------------------------------------------ settings

    def _apply_settings(self) -> None:
        s = self._settings
        self._template.setText(s.get("template", DEFAULT_TEMPLATE))
        self._size.set_value(float(s.get("size", 1.0)))
        self._fit.setChecked(bool(s.get("fit", True)))
        axis = s.get("axis", "X")
        self._view.set_axis(axis if axis in shape_data.AXES else "X")
        mode = s.get("offsets", "Groups")
        self._offsets.set_current(mode if mode in OFFSET_MODES else "Groups", animate=False)
        self._offset_names.setText(s.get("offset_names", "offset"))
        drive = s.get("drive", "None")
        self._drive.set_current(drive if drive in DRIVES else "None", animate=False)
        self._chain.setChecked(bool(s.get("chain", True)))
        self._ghost.setChecked(bool(s.get("ghost", True)))
        self._side_color.setChecked(bool(s.get("side_color", True)))
        category = s.get("category", ALL)
        self._categories.set_current(category if category in (ALL,) + shape_data.CATEGORIES else ALL)
        self._control_card.set_open(not dict(s.get("folded") or {}).get("control", False))
        self._selected_card.set_open(not dict(s.get("folded") or {}).get("selected", False))
        if not self._control_card.is_open():
            self._search.hide()
        self._show_offset_names()
        self._apply_color_settings()

    def _save(self, *_args) -> None:
        if self._loading:
            return
        values = {"template": self._template.text().strip(), "size": self._size.value(),
                  "fit": self._fit.isChecked(), "axis": self._view.axis(), "offsets": self._offsets.current(),
                  "offset_names": self._offset_names.text().strip(), "chain": self._chain.isChecked(),
                  "side_color": self._side_color.isChecked(), "drive": self._drive.current(),
                  "ghost": self._ghost.isChecked()}
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value
        self._refresh_live()

    def _save_folded(self, key: str, opened: bool) -> None:
        folded = dict(self._settings.get("folded") or {})
        folded[key] = not opened
        self._settings["folded"] = folded

    # ------------------------------------------------------------------ the library

    def _shown_shapes(self) -> list:
        category = self._categories.current() or ALL
        needle = self._search.text().strip().lower()
        return [shape for shape in self.library.all().values()
                if (category == ALL or shape.category == category)
                and (not needle or needle in shape.name.lower())]

    def _refresh_grid(self) -> None:
        self._grid.set_shapes(self._shown_shapes(), self._settings.get("shape", "circle"))
        self._show_preview()

    def _on_category(self, name: str) -> None:
        self._settings["category"] = name
        self._refresh_grid()

    def _on_shape_picked(self) -> None:
        name = self._grid.current_name()
        if name:
            self._settings["shape"] = name
            self._show_preview()

    def _on_axis(self, _axis: str) -> None:
        self._save()
        self._show_preview()

    def _on_offsets(self, _mode: str) -> None:
        self._save()
        self._show_offset_names()

    def _show_offset_names(self) -> None:
        wanted = self._offsets.current() == "Groups"
        if wanted == self._offset_names.isHidden():
            self._offset_names.setVisible(wanted)

    def _picked_shape(self) -> "shape_data.Shape | None":
        return self.library.get(self._settings.get("shape", "circle")) or shape_data.BUILT_IN["circle"]

    def _show_preview(self) -> None:
        shape = self._picked_shape()
        axis = self._view.axis()
        self._view.set_curves(shape_data.oriented(shape.curves, axis), axis)
        self._refresh_live()

    def _on_grid_menu(self, position) -> None:
        item = self._grid.itemAt(position)
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        if item is not None:
            name = item.data(qt.QtCore.Qt.ItemDataRole.UserRole)
            shape = self.library.get(name)
            menu.addAction("Create it", self.create)
            menu.addAction("Put it on the selected controls", self._on_replace)
            menu.addAction("Add it to the selected controls", self._on_add_shape)
            if shape is not None and shape.user:
                menu.addAction("Remove this shape of yours", lambda: self._remove_shape(name))
            menu.addSeparator()
        mine = len(self.library.mine())
        menu.addAction(f"Your shapes into a file… ({mine})", self._on_export_shapes).setEnabled(mine > 0)
        menu.addAction("Shapes from a file…", self._on_import_shapes)
        menu.exec(self._grid.viewport().mapToGlobal(position))

    def _remove_shape(self, name: str) -> None:
        if self.library.remove(name):
            self._say(f"Removed the shape “{name}”", "done")
            self._refresh_grid()

    # ------------------------------------------------------------------ actions

    def _say(self, text: str, state: str = "") -> None:
        self.status_changed.emit(text, state)

    def _sides(self) -> rules.Sides:
        """The Rename tool's sides (one setting for both tools)."""
        saved = Resources().configsMayaMng.get_config("rename")["settings"]
        return rules.Sides.from_settings(saved.get("sides"))

    def create(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        shape = self._picked_shape()
        names = self._offset_suffixes()
        drive = {"constrain": "constraint"}.get(self._drive.current().lower(), self._drive.current().lower())
        targets = scene.selected_transforms()
        notes = []
        self._clear_ghost()
        try:
            made = scene.create(shape, targets, self._template.text().strip(), self._size.value(),
                                self._view.axis(), self._fit.isChecked(), self._offsets.current().lower(),
                                names, self._chain.isChecked(), self._side_color.isChecked(), self._sides(),
                                drive=drive, notes=notes, rgb=self._own_rgb())
        except RuntimeError as error:
            self._say(f"Maya refused: {error}".strip(), "error")
            return
        self._made = frozenset(made)
        short = [path.rpartition("|")[2] for path in made]
        listed = ", ".join(short[:3]) + ("…" if len(short) > 3 else "")
        if drive == "shape" and targets:
            self._say(f"“{shape.title()}” is now the shape of {len(made)}: {listed} · Ctrl+Z undoes it", "done")
            return
        text = f"Created {len(made)}: {listed}"
        if targets and drive in ("constraint", "matrix"):
            driven = len(made) - len(notes)
            text += f" · {driven} driven by {'constraints' if drive == 'constraint' else 'the matrix'}"
        if notes:
            text += f" · NOT driven — {notes[0]}" + (f" (+{len(notes) - 1})" if len(notes) > 1 else "")
        self._say(text + " · Ctrl+Z undoes it", "error" if notes and len(notes) == len(made) else "done")

    def _selected_controls(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        controls = scene.controls_in_selection()
        if not controls:
            self._say("Select controls (curves) first", "error")
        return controls

    def _turn(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            back = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
            scene.turn(controls, axis, -90.0 if back else 90.0)
            self._say(f"Turned {len(controls)} {'−' if back else ''}90° about {axis}", "done")

    def _resize(self, factor: float) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            scene.resize(controls, factor)
            self._say(f"{'Bigger' if factor > 1 else 'Smaller'}: {len(controls)}", "done")

    def _on_replace(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            shape = self._picked_shape()
            count = scene.replace(controls, shape, self._view.axis())
            self._say(f"{count} got the shape “{shape.title()}” · Ctrl+Z undoes it", "done")

    # ------------------------------------------------------------------ editing shapes

    _copied_shape: list = []     # the copied curves, kept by the CLASS: they outlive a closed window

    def _on_cvs(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        state = scene.toggle_cvs()
        if state == "cvs":
            self._say("The shapes' CVs are selected: move, turn, scale them — click again for the controls", "done")
        elif state == "objects":
            self._say("Back to the controls", "")
        else:
            self._say("Select controls (curves) first", "error")

    def _on_copy_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            ControlsPanel._copied_shape = scene.read_curves(controls[0])
            self._say(f"Copied the shape of {controls[0].rpartition('|')[2]} — select controls and paste", "done")

    def _on_paste_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        if not ControlsPanel._copied_shape:
            self._say("Nothing copied yet: select a control and copy its shape", "error")
            return
        controls = self._selected_controls()
        if controls:
            scene.set_curves(controls, ControlsPanel._copied_shape)
            self._say(f"Pasted the shape onto {len(controls)} · Ctrl+Z undoes it", "done")

    def _on_add_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            shape = self._picked_shape()
            scene.add_shape(controls, shape, self._view.axis())
            self._say(f"Added “{shape.title()}” to {len(controls)} · Ctrl+Z undoes it", "done")

    def _on_combine(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        if len(controls) < 2:
            self._say("Select two or more curves: they become one control, the LAST selected", "error")
            return
        keeper = scene.combine(controls)
        self._say(f"{len(controls)} curves are one control now: {keeper.rpartition('|')[2]} · Ctrl+Z undoes it", "done")

    def _on_top(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            state = scene.toggle_on_top(controls)
            if state is None:
                self._say("This Maya's curves have no “always on top”", "error")
            else:
                self._say(f"{len(controls)} drawn {'over everything' if state else 'as usual again'}", "done")

    def _select_controls(self, below: bool) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        from maya import cmds
        roots = scene.selected_transforms() if below else None
        if below and not roots:
            self._say("Select what to look under first", "error")
            return
        found = scene.all_controls(roots)
        if not found:
            self._say("No controls (curves) there", "")
            return
        cmds.select(found, replace=True)
        self._say(f"Selected {len(found)} control{'s' if len(found) != 1 else ''}", "done")

    def _on_export_shapes(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Your shapes into a file",
                                                                 "msl_control_shapes.json", SHAPES_FILTER)
        if not path:
            return
        try:
            count = self.library.export_file(path)
        except OSError as error:
            self._say(f"Couldn't write the file: {error}", "error")
            return
        self._say(f"{count} shape{'s' if count != 1 else ''} written to {Path(path).name}", "done")

    def _on_import_shapes(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(self, "Shapes from a file", "", SHAPES_FILTER)
        if not path:
            return
        try:
            added = self.library.import_file(path)
        except ValueError as error:
            self._say(str(error), "error")
            return
        if not added:
            self._say("Nothing new in that file: you have those shapes", "")
            return
        self._categories.set_current("Mine")
        self._settings["category"] = "Mine"
        self._settings["shape"] = added[0]
        self._refresh_grid()
        self._say(f"{len(added)} shape{'s' if len(added) != 1 else ''} added to Mine", "done")

    def _mirror_to_other(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        made, updated, alone = scene.mirror_controls(controls, self._sides(), axis, self._side_color.isChecked())
        if not made and not updated:
            self._say("Nothing to mirror: the names say no side (lf_ / rt_, _L / _R…)", "error")
            return
        parts = []
        if made:
            parts.append(f"Mirrored {len(made)}: " + ", ".join(path.rpartition("|")[2] for path in made[:2]) +
                         ("…" if len(made) > 2 else ""))
        if updated:
            parts.append(f"{updated} other-side shape{'s' if updated != 1 else ''} updated")
        if alone:
            parts.append(f"{len(alone)} say no side")
        self._say(" · ".join(parts) + " · Ctrl+Z undoes it", "done")

    def _mirror_shapes(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        updated, missing = scene.mirror_shapes_to_twins(controls, self._sides(), axis)
        if not updated:
            self._say("No other side to carry the shape to — Mirror makes one", "error")
            return
        text = f"{updated} shape{'s' if updated != 1 else ''} carried to the other side (across {axis})"
        if missing:
            text += f" · {len(missing)} without one: " + ", ".join(missing[:2])
        self._say(text + " · Ctrl+Z undoes it", "done")

    def _on_mirror_update_menu(self, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        for axis in shape_data.AXES:
            menu.addAction(f"The shape to the other side, across the world {axis}",
                           lambda axis=axis: self._mirror_shapes(axis))
        menu.exec(self._mirror_update.mapToGlobal(position))

    def _on_mirror_menu(self, position) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        for axis in shape_data.AXES:
            menu.addAction(f"Mirror across the world {axis}",
                           lambda axis=axis: self._mirror_to_other(axis))
        menu.addSeparator()
        for axis in shape_data.AXES:
            menu.addAction(f"Flip in place across its own {axis}", lambda axis=axis: self._flip(axis))
        menu.exec(self._mirror.mapToGlobal(position))

    def _flip(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            scene.flip(controls, axis)
            self._say(f"Flipped {len(controls)} across their own {axis} · Ctrl+Z undoes it", "done")

    def _zero_targets(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if not targets:
            self._say("Select the controls to zero first", "error")
        return targets

    def _zero_groups(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._zero_targets()
        if targets:
            names = self._offset_suffixes()
            scene.zero_with_groups(targets, names)
            self._say(f"Zeroed {len(targets)} with {', '.join(names)} above · Ctrl+Z undoes it", "done")

    def _zero_matrix(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._zero_targets()
        if targets:
            scene.zero_with_matrix(targets)
            self._say(f"Zeroed {len(targets)} through the offsetParentMatrix · Ctrl+Z undoes it", "done")

    def _matrix_back(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._zero_targets()
        if targets:
            held = [target for target in targets if scene.has_offset_matrix(target)]
            if not held:
                self._say("Their offsetParentMatrix holds nothing", "")
                return
            scene.matrix_to_channels(held)
            self._say(f"{len(held)} back in the channels, the offsetParentMatrix empty · Ctrl+Z undoes it", "done")

    def _offset_suffixes(self) -> list:
        return [part.strip() for part in self._offset_names.text().replace(",", " ").split() if part.strip()] \
            or ["offset"]

    def _on_capture(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        controls = self._selected_controls()
        if not controls:
            return
        curves = [curve for control in controls for curve in scene.read_curves(control)]
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        title = menu.addAction(f"Save {len(curves)} curve{'s' if len(curves) != 1 else ''} as a shape — its name:")
        title.setEnabled(False)
        _field_action(menu, controls[0].rpartition("|")[2], "Shape name", lambda name: self._save_shape(name, curves))
        menu.exec(self._capture.mapToGlobal(qt.QtCore.QPoint(0, self._capture.height())))

    def _save_shape(self, name: str, curves: list) -> None:
        saved = self.library.add(name, curves)
        self._settings["shape"] = saved
        self._categories.set_current("Mine")
        self._settings["category"] = "Mine"
        self._refresh_grid()
        self._say(f"Saved the shape “{saved}” — it is under Mine", "done")
