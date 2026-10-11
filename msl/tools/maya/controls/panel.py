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
from msl_tools.msl.tools.maya.controls.editor import ShapeEditor, axis_step_button
from msl_tools.msl.tools.maya.controls.naming import DEFAULT_TEMPLATE, control_name
from msl_tools.msl.tools.maya.controls.panel_attributes import _AttributesMixin
from msl_tools.msl.tools.maya.controls.panel_color import _ColorMixin
from msl_tools.msl.tools.maya.controls.panel_common import (ALL, OFFSET_MODES, DRIVES, SHAPES_FILTER, EDITOR_HEIGHT, THUMB,
                                                      CELL, FAVORITE_ROWS, LIBRARY_ROWS, STAR, FIRST_FAVORITES)
from msl_tools.msl.tools.maya.controls.panel_editor import _EditorMixin
from msl_tools.msl.tools.maya.controls.panel_library import CategoryBox, ShapeGrid, _LibraryMixin
from msl_tools.msl.tools.maya.controls.panel_selected import _SelectedMixin
from msl_tools.msl.tools.maya.controls.panel_transforms import _TransformsMixin
from msl_tools.msl.tools.maya.controls.preview import ShapeView, thumbnail
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField, HierarchyStrip, Swatches, TurnButton
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.tools.maya.rename.buttons import QuickButton, ToggleIconButton
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces.stable_scroll_area import StableScrollArea
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

StylesheetBuilder.register_template(Path(__file__).with_name("controls.qss"))



class ControlsPanel(_ColorMixin, _AttributesMixin, _TransformsMixin, _SelectedMixin, _LibraryMixin, _EditorMixin,
                    qt.QtWidgets.QWidget):
    """The tool (shown in a ControlsWindow). Settings and the user's shapes: configsMayaMng
    "controls" (`settings`, `shapes`).

    Signals:
        status_changed(str, str) — what the panel says (text, "" / "done" / "error"): the header.
    """

    status_changed = qt.QtCore.Signal(str, str)

    menuIconColor = color_property("_menu_icon", None)     # a menu's icons that belong to no colored button

    TOOL_NAME = "controls"
    DEFAULTS = {"shape": "circle", "category": ALL, "template": DEFAULT_TEMPLATE, "size": 1.0, "fit": True,
                "axis": "X", "offsets": "Groups", "offset_names": "offset", "chain": True, "side_color": True,
                "drive": "None", "own_color": "", "ghost": True, "middle": False,
                "shape_step": 0.1, "shape_angle": 90.0, "shape_factor": 1.25, "hide_joint": True, "as_joint": False,
                "favorites": list(FIRST_FAVORITES), "library": "favorites",
                "shown": {"channels": False, "attributes": False},
                "folded": {"control": False}}

    def __init__(self, parent=None):
        super().__init__(parent)
        config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": dict(self.DEFAULTS)})
        self._config = config
        self._settings = config["settings"]
        self.library = shape_data.ShapeLibrary(config["shapes"])
        self._loading = True
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        self._menu_icon = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)
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
        self._search.setFixedWidth(104)
        self._search.setToolTip("Looks through the WHOLE library, whichever of the two is shown")
        # the library: only your favorites (two rows), or all of it (in place, by category)
        self._categories = CategoryBox((ALL,) + shape_data.CATEGORIES)
        self._categories.setObjectName("controlsCategories")
        self._categories.setFixedWidth(82)
        self._categories.setToolTip("Which part of the library is shown")
        self._favorites_only = ToggleIconButton(icons.get_icon("star", sub_folder="actions"), "Only your favorites",
                                                "The shapes you use — a short list instead of the whole library. "
                                                "The star in a tile's corner adds a shape or takes it out; "
                                                "drag a tile to put them in your order")
        self._whole_library = ToggleIconButton(icons.get_icon("grid", sub_folder="actions"), "The whole library",
                                               "Every shape, by category — to find one and star it")
        for button in (self._favorites_only, self._whole_library):
            button.setObjectName("controlsToggle")
        card = self._control_card = FoldingCard("CONTROL", icons.get_icon("controls", sub_folder="actions"),
                                                extras=[self._categories, self._favorites_only,
                                                        self._whole_library, self._search])
        self._heading_extras = (self._categories, self._favorites_only, self._whole_library, self._search)

        self._grid = ShapeGrid()
        self._view = ShapeView()
        self._view.setFixedWidth(132)
        # what makes the picked shape: under the library, as wide as it — the preview keeps its height
        self._create = qt.QtWidgets.QPushButton("Create")
        self._create.setProperty("primary", True)
        self._create.setObjectName("controlsCreate")
        self._no_favorites = qt.QtWidgets.QLabel("No favorites yet — open the whole library (the grid button "
                                                 "above) and click the star in a shape's corner")
        self._no_favorites.setObjectName("controlsCaption")
        self._no_favorites.setWordWrap(True)
        self._no_favorites.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._no_favorites.hide()
        self._create.setToolTip("A control on every selected object (nothing selected: one at the origin) · "
                                "double click a shape does the same — or, with only controls (curves) "
                                "selected, gives them that shape")
        picked = qt.QtWidgets.QVBoxLayout()
        picked.setSpacing(6)
        picked.addWidget(self._grid)
        picked.addWidget(self._no_favorites)
        picked.addWidget(self._create)
        # top first, like the Outliner: the zero groups, the control, an arrow to what it drives —
        # under Create, so the preview beside them keeps its height while the library is one row
        self._strip = HierarchyStrip()
        self._strip.setObjectName("controlsStrip")
        picked.addWidget(self._strip)
        shelf = qt.QtWidgets.QHBoxLayout()
        shelf.setSpacing(6)
        shelf.addLayout(picked, 1)
        shelf.addWidget(self._view)
        # the preview grows into an editor of the shape's points, in the library's room
        self._expand = self._tool_button("expand", "Edit the shape", "The preview grows into an editor: drag the "
                                         "shape's points, move it away from the pivot, turn and scale it, add and "
                                         "remove points — then create it, put it on a control or save it as yours."
                                         + chr(10) + "With a curve selected in the scene, THAT curve opens in it")
        self._expand.setParent(self._view)
        self._expand.move(5, 5)
        # "the joint itself is the control": the curve becomes the joint's own shape (Drive = Shape)
        self._bone = ToggleIconButton(icons.get_icon("joint_shape", sub_folder="actions"), "The joint is the control",
                                      "No new object: the curve becomes the shape of the selected joint (or object) "
                                      "itself — you pick and animate the joint by its curve. The same as Drive = "
                                      "Shape; Zero, Chain and the name don't apply")
        self._bone.setObjectName("controlsToggle")
        self._bone.setParent(self._view)
        self._bone.move(32, 5)
        # an eye for the joint's own bone: open = it is drawn, closed = only the curve is seen
        self._eye_icons = {True: icons.get_icon("eye", sub_folder="actions"),
                           False: icons.get_icon("eye_off", sub_folder="actions")}
        self._hide_joint = ToggleIconButton(self._eye_icons[True], "The joint's bone is seen",
                                            "The eye open: a joint that is a control draws its bone under the curve "
                                            "· closed: only the curve is seen (Draw Style: None).\nIt shows how the "
                                            "SELECTED joint controls are drawn now, and a click changes them at "
                                            "once; with none selected it is how the next ones are made")
        self._hide_joint.setObjectName("controlsToggle")
        self._hide_joint.setParent(self._view)
        self._hide_joint.move(59, 5)
        self._editor = ShapeEditor()
        self._editor.setFixedHeight(EDITOR_HEIGHT)
        self._editor.hide()

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
        self._color_chip = Swatches(side=22, gap=0, columns=1)
        self._color_chip.setObjectName("controlsViewColor")
        self._color_chip.setFixedSize(self._color_chip.sizeHint())
        self._view.set_corner_widgets([self._size, self._fit], [self._side_color, self._color_chip])
        naming = qt.QtWidgets.QHBoxLayout()
        naming.setSpacing(4)
        naming.addWidget(self._caption("Name"))
        naming.addWidget(self._template, 1)
        naming.addWidget(self._chain)
        self._middle = ToggleIconButton(icons.get_icon("center", sub_folder="actions"), "One in the middle",
                                        "ONE control in the middle of everything selected, instead of one on "
                                        "each: select an edge loop and get a ring around the limb — it faces "
                                        "across the loop and reaches just past it (with Fit)")
        self._middle.setObjectName("controlsToggle")
        naming.addWidget(self._middle)
        self._as_joint = ToggleIconButton(icons.get_icon("joint_node", sub_folder="actions"), "Controls are joints",
                                          "Each new control is a JOINT node (its bone not drawn, only the curve) "
                                          "instead of a plain transform — for rigs built of joints all through")
        self._as_joint.setObjectName("controlsToggle")
        naming.addWidget(self._as_joint)
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

        card.body_layout.addLayout(shelf)
        card.body_layout.addWidget(self._editor)
        # top first, like the Outliner: the zero groups, the control, an arrow to what it drives
        card.body_layout.addLayout(naming)
        card.body_layout.addLayout(making)
        card.body_layout.addLayout(driving)

        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(10, 8, 4, 8)
        column.setSpacing(6)
        self._column = column
        # the cards, by key, in the order they are made in (the user drags them into his own:
        # settings.card_order)
        self._cards = {"selected": self._selected_tools(), "control": card, "color": self._color_card(),
                       "channels": self._channels_card(), "attributes": self._attributes_card(),
                       "transforms": self._transforms_card()}
        for each in self._cards.values():
            column.addWidget(each)
            each.drag_moved.connect(self._on_card_dragged)
            each.drag_released.connect(self._on_card_dropped)
        column.addStretch(1)
        self._card_line = qt.QtWidgets.QFrame(body)        # where a dragged card would land
        self._card_line.setObjectName("controlsAttrDrop")
        self._card_line.hide()
        self._card_drop = -1
        scroll = StableScrollArea()
        scroll.setObjectName("controlsScroll")
        scroll.setWidget(body)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    # ---- the cards in the user's own order: a card is dragged by its heading

    def _shown_cards(self) -> list:
        """The cards on screen, top to bottom."""
        cards = [self._column.itemAt(index).widget() for index in range(self._column.count())]
        return [card for card in cards if card is not None and card in self._cards.values() and not card.isHidden()]

    def _card_order(self) -> list:
        """Every card's key, top to bottom (the hidden ones too: they keep their place)."""
        keys = {card: key for key, card in self._cards.items()}
        cards = [self._column.itemAt(index).widget() for index in range(self._column.count())]
        return [keys[card] for card in cards if card in keys]

    def _apply_card_order(self) -> None:
        wanted = [key for key in (self._settings.get("card_order") or []) if key in self._cards]
        wanted += [key for key in self._cards if key not in wanted]
        if wanted == self._card_order():
            return
        for key in wanted:
            self._column.removeWidget(self._cards[key])
        for index, key in enumerate(wanted):
            self._column.insertWidget(index, self._cards[key])

    def _on_card_dragged(self, card, position) -> None:
        shown = self._shown_cards()
        body = self._card_line.parentWidget()
        y = body.mapFromGlobal(position).y()
        index = len(shown)
        for place, each in enumerate(shown):
            if y < each.geometry().center().y():
                index = place
                break
        self._card_drop = index
        at = (shown[index].geometry().top() - 4) if index < len(shown) else (shown[-1].geometry().bottom() + 2)
        self._card_line.setGeometry(card.geometry().left() + 6, max(0, at), card.width() - 12, 2)
        self._card_line.show()
        self._card_line.raise_()

    def _on_card_dropped(self, card) -> None:
        index, self._card_drop = self._card_drop, -1
        self._card_line.hide()
        shown = self._shown_cards()
        if index < 0 or card not in shown:
            return
        source = shown.index(card)
        if index in (source, source + 1):
            return
        before = shown[index] if index < len(shown) else None      # the card it lands in front of
        self._column.removeWidget(card)
        if before is None:
            last = self._column.indexOf(shown[-1] if shown[-1] is not card else shown[-2])
            self._column.insertWidget(last + 1, card)
        else:
            self._column.insertWidget(self._column.indexOf(before), card)
        self._settings["card_order"] = self._card_order()
        self._say("The cards are in your order — drag a card by its heading", "done")

    def content_height_change(self) -> int:
        """How much taller (+) or shorter (-) the panel wants to be to show everything without
        scrolling and without empty room under it — the window follows it."""
        scroll = self.findChild(StableScrollArea, "controlsScroll")
        if scroll is None or scroll.widget() is None:
            return 0
        return scroll.widget().sizeHint().height() - scroll.viewport().height()


    # ---- menus: a caption says what the lines under it are, every line has an icon in its button's color

    def _menu(self) -> "qt.QtWidgets.QMenu":
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setToolTipsVisible(True)
        return menu

    @staticmethod
    def _menu_caption(menu, text: str) -> None:
        """A line that only names the group under it (it can't be picked)."""
        menu.addAction(text).setEnabled(False)

    def _menu_item(self, menu, icon: str, text: str, slot, tip: str = "", color=None, hint: str = ""):
        """A line of a menu: `icon` (actions/) tinted `color` — a button's own `iconColor`, so a menu
        looks like its button —, `hint` at the right edge (what a plain click does: "click")."""
        from msl_tools.msl.ui.icon_manager import tinted_menu_icon
        picture = tinted_menu_icon(UiResources().iconManager.get_icon(icon, sub_folder="actions"),
                                   color or self._menu_icon, self.devicePixelRatioF())
        action = menu.addAction(picture, text + (f"\t{hint}" if hint else ""), slot)
        if tip:
            action.setToolTip(tip)
        return action

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
        self._grid.itemDoubleClicked.connect(lambda _item: self._on_shape_double_click())
        self._grid.customContextMenuRequested.connect(self._on_grid_menu)
        self._grid.hovered.connect(self._on_shape_hover)
        self._grid.star_clicked.connect(self._toggle_favorite)
        self._grid.order_changed.connect(self._on_favorites_order)
        self._favorites_only.clicked.connect(lambda: self._set_library("favorites"))
        self._whole_library.clicked.connect(lambda: self._set_library("all"))
        self._expand.clicked.connect(lambda: self._set_editing(True))
        self._bone.toggled.connect(self._on_bone)
        self._editor.closed.connect(lambda: self._set_editing(False))
        self._editor.edited.connect(self._on_shape_edited)
        self._editor.reset_requested.connect(self._reset_edited)
        self._editor.save_requested.connect(self._on_save_edited)
        self._editor.create_requested.connect(self.create)
        self._editor.apply_requested.connect(self._on_replace)
        self._editor.take_requested.connect(self._take_shape)
        for axis, button in self._turns.items():
            button.clicked.connect(lambda _checked=False, axis=axis: self._turn(axis))
        self._shrink.clicked.connect(lambda: self._resize(1.0 / self._shape_factor.value()))
        self._grow.clicked.connect(lambda: self._resize(self._shape_factor.value()))
        for (index, sign), button in self._shifts.items():
            button.clicked.connect(lambda _checked=False, index=index, sign=sign: self._shift_shape(index, sign))
        for field in (self._shape_step, self._shape_angle, self._shape_factor):
            field.value_changed.connect(self._save)
        self._replace.clicked.connect(self._on_replace)
        self._fit_button.clicked.connect(self._fit_selected)
        self._select_same.clicked.connect(lambda: self._select_same_shape(False))
        self._select_same.customContextMenuRequested.connect(
            lambda position: self._same_shape_menu().exec(self._select_same.mapToGlobal(position)))
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
        self._strip_shape.clicked.connect(self._on_strip_shape)
        self._zero_groups_button.clicked.connect(self._zero_groups)
        self._zero_matrix_button.clicked.connect(self._zero_matrix)
        self._matrix_back_button.clicked.connect(self._matrix_back)
        self._on_top_button.clicked.connect(self._on_top)
        self._drive_constraint.clicked.connect(lambda: self._drive_selected("constraint"))
        self._drive_matrix.clicked.connect(lambda: self._drive_selected("matrix"))
        self._drive_off.clicked.connect(self._undrive_selected)
        self._locators.clicked.connect(lambda: self._make_locators(False))
        self._locators.customContextMenuRequested.connect(self._on_locators_menu)
        self._joints.clicked.connect(lambda: self._make_joints(True))
        self._joints.customContextMenuRequested.connect(self._on_joints_menu)
        self._select_below.clicked.connect(lambda: self._select_controls(True))
        self._select_all.clicked.connect(lambda: self._select_controls(False))
        self._drive.current_changed.connect(self._save)
        for axis, button in self._turns.items():
            self._watch_hover(button, f"turn_{axis}")
        for (index, sign), button in self._shifts.items():
            self._watch_hover(button, f"shift_{index}{'+' if sign > 0 else '-'}")
        for key, button in (("shrink", self._shrink), ("grow", self._grow), ("replace", self._replace),
                            ("add", self._add_shape), ("paste", self._paste_shape), ("mirror", self._mirror),
                            ("mirror_update", self._mirror_update), ("zero_groups", self._zero_groups_button),
                            ("zero_matrix", self._zero_matrix_button), ("matrix_back", self._matrix_back_button)):
            self._watch_hover(button, key)
        self._create.clicked.connect(self.create)
        for widget in (self._template, self._offset_names):
            widget.textEdited.connect(self._save)
        self._size.value_changed.connect(self._save)
        self._hide_joint.toggled.connect(self._show_eye)
        self._hide_joint.toggled.connect(self._on_hide_joint)
        for toggle in (self._fit, self._chain, self._side_color, self._ghost, self._middle, self._as_joint):
            toggle.toggled.connect(self._save)
        self._view.axis_picked.connect(self._on_axis)
        self._strip.clicked.connect(self._on_strip)
        self._color_chip.clicked.connect(lambda _key: self._pick_own_color())
        self._color_chip.menu_requested.connect(self._on_color_chip_menu)
        self._view.size_stepped.connect(self._size._nudge)
        self._selected_card.toggled.connect(lambda opened: self._save_folded("selected", opened))
        self._offsets.current_changed.connect(self._on_offsets)
        self._control_card.toggled.connect(lambda opened: self._save_folded("control", opened))
        self._control_card.toggled.connect(lambda _opened: self._show_heading())
        self._connect_color()
        self._connect_attributes()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._highlight_back()           # (left off by a look that never ended)
        self.refresh_palette()
        self.refresh_scene_colors()
        self._watch_selection(True)
        self._refresh_live()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._refresh_live()
        self.refresh_scene_colors()

    def hideEvent(self, event) -> None:
        self._end_try()                  # a color being tried on is never left on the objects
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
        if self._loading or self._trying:       # (a color being tried on: the selection is aside for it)
            return
        try:
            if self._hovered_action:
                self._show_action()
            else:
                self._draw_live()
        except Exception as error:      # a preview must never take the tool down — but it must say why
            self._report("The preview couldn't follow the selection", error)
        try:
            self._show_line_width()
            self._show_color_places()
            self._refresh_transform_values()
            self._refresh_attributes()      # CHANNELS / ATTRIBUTES, while they are on screen
        except Exception as error:
            self._report("The channels couldn't follow the selection", error)

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

    def _draw_live(self, with_ghost: bool = True) -> None:
        """Every selected object (a joint with its bones, a box) with the control it would get: at its
        real size, in its color, its zero groups as frames around it, chained controls joined by a
        line; the first one's name on top; the button says how many. `entries` = what Create works
        on (scene.selection_targets): objects, and the selected PARTS of objects — vertices, edges,
        faces — or the one in the middle of them all; `targets` = the objects among them."""
        entries, targets, looks = [], [], []
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
                entries = scene.selection_targets(self._view.axis(), self._middle.isChecked())
                targets = [entry for entry in entries if isinstance(entry, str)]
                looks = scene.targets_look(entries[:1], axis=self._view.axis())
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
        count = len(entries)
        in_middle = count == 1 and not targets and bool(entries) and not isinstance(entries[0].item, str)
        name = look["name"] if (look and drive == "Shape") else control_name(
            self._template.text().strip(), look["name"] if look else "", position, self._sides(), 1)
        self._view.set_title("", "")
        self._view.set_notes([])
        self._view.set_zero("none")
        self._create.setToolTip((f"Makes {name}" + (f" and {count - 1} more" if count > 1 else "") + "\n"
                                 if count or drive != "Shape" else "") +
                                "A control on every selected object (nothing selected: one at the origin) · "
                                "double click a shape does the same — or, with only controls (curves) "
                                "selected, gives them that shape")
        existing = None             # the first selected object is a control that exists
        if entries and in_maya and isinstance(entries[0], str):
            try:
                if scene.curve_shapes(targets[0]):
                    own = scene.read_color(targets[0])[0]
                    existing = (scene.read_curves(targets[0]), own, scene.links_of(targets[0]))
            except Exception as error:
                self._report("Couldn't read the selected control", error)
        if existing:
            # what IS: its own shape in its own color, and the line says what it is tied into
            curves, own, info = existing
            after = curves
            if self._hover_shape:
                # the shape under the pointer in the library, as Replace would put it on this control
                reach = max([abs(value) for curve in curves for point in curve.points for value in point] or [1.0])
                after = shape_data.scaled(shape_data.oriented(self._previewed_shape().curves, self._view.axis()),
                                          reach or 1.0)
            self._view.set_action(curves, after, self._color_for(own) if own is not None else None)
            self._strip.set_items(self._strip_existing(targets[0], info, count))
        else:
            # what WILL BE made of the selection
            becomes = drive == "Shape"         # the object itself becomes the control: one color with its curve
            items = [{"look": each, "reach": self._size.value() * (each["fit"] if fit else 1.0),
                      "color": self._color_for(self._control_rgb(each["position"])), "matrix": each["matrix"],
                      "parent": each["parent"], "becomes": becomes and each.get("kind") != "part"} for each in looks]
            if not items and becomes:
                # nothing selected yet: a bone to show what this mode makes — a joint that wears the curve
                items = [{"look": {"kind": "joint", "radius": 0.22, "bones": [(1.5, 0.0, 0.0)]}, "reach": 1.0,
                          "color": self._color_for(rgb), "becomes": True}]
            items = items or [{"color": self._color_for(rgb)}]
            self._view.set_action(None, None)
            self._view.set_scene(items)
            self._strip.set_items(self._strip_planned(look, count, name, mode, drive))
        self._refresh_states(targets)
        self._read_joint_controls(targets)
        self._create.setText("Create" if not count else f"Shape onto {len(targets)}" if drive == "Shape" and targets
                             else "Create 1 · middle" if in_middle else f"Create {count}")
        self._editor.set_create_text(self._create.text())
        if with_ghost:
            self._update_ghost(entries)

    # ---- the line under the library: zero groups › control ⇢ what it drives

    def _strip_planned(self, look, count: int, name: str, mode: str, drive: str) -> list:
        """What Create WOULD make, top first. Its blocks are the settings: a click changes them."""
        icons = UiResources().iconManager
        more = f"  +{count - 1}" if count > 1 else ""
        target = {"key": "", "text": (look["name"] + more) if look else "what you select",
                  "tone": "target" if look else "muted", "tip": "The object the control is made for"}
        if drive == "Shape":
            return [{"key": "drive", "icon": icons.get_icon("cvs", sub_folder="actions"), "text": "the curve",
                     "tone": "drive", "link": "into", "tip": "No new object: the curve becomes a shape of the "
                                                             "object itself — click to change"}, target]
        items = [{"key": "zero", "tone": "zero" if mode != "None" else "muted",
                  "icon": icons.get_icon({"Groups": "zero_out", "Matrix": "zero_matrix"}.get(mode, "clear"),
                                         sub_folder="actions"),
                  "text": {"Matrix": "matrix", "None": "no zero"}.get(mode, ""),
                  "link": "gap" if mode == "Groups" else "into",
                  "tip": "How a new control is zeroed — click to change"}]
        if mode == "Groups":
            for index, suffix in enumerate(self._offset_suffixes()):
                items.append({"key": f"group:{index}", "text": suffix, "tone": "zero", "link": "into",
                              "tip": f"A group above the control: <control>_{suffix} — click to rename it"})
        items.append({"key": "control", "text": name + more, "tone": "control",
                      "tip": "The new control — click to change how it is named",
                      "link": {"Constrain": "constraint", "Matrix": "matrix"}.get(drive, "none"),
                      "link_key": "drive",
                      "link_tip": {"Constrain": "It will drive the object through constraints",
                                   "Matrix": "It will drive the object through its offsetParentMatrix"}
                      .get(drive, "It will NOT drive the object") + " — click to change"})
        items.append(target)
        return items

    def _strip_existing(self, control: str, info: dict, count: int) -> list:
        """What a control that exists IS tied into. A click on a block selects that object."""
        icons = UiResources().iconManager
        short = control.rpartition("|")[2]
        items = []
        for group in info["groups"]:
            name = group.rpartition("|")[2]
            items.append({"key": "node:" + group, "tone": "zero", "link": "into", "tip": f"{name} — click to select it",
                          "text": name[len(short) + 1:] if name.startswith(short + "_") else name})
        if info["matrix_zero"]:
            items.append({"key": "", "tone": "zero", "text": "matrix", "link": "into",
                          "icon": icons.get_icon("zero_matrix", sub_folder="actions"),
                          "tip": "Zeroed in its offsetParentMatrix"})
        driven = info["driven"]
        items.append({"key": "node:" + control, "text": short + (f"  +{count - 1}" if count > 1 else ""),
                      "tone": "control", "tip": "The selected control",
                      "link": driven[0][1] if driven else "",
                      "link_tip": "Drives it through " + ("constraints" if driven and driven[0][1] == "constraint"
                                                          else "its offsetParentMatrix")})
        if driven:
            items.append({"key": "node:" + driven[0][0], "tone": "target", "tip": "The object it drives — click to "
                          "select it", "text": driven[0][0].rpartition("|")[2] +
                          (f"  +{len(driven) - 1}" if len(driven) > 1 else "")})
        elif not info["groups"] and not info["matrix_zero"]:
            items.append({"key": "", "tone": "muted", "text": "not zeroed · drives nothing"})
        return items

    def _on_strip(self, key: str, where) -> None:
        if key.startswith("node:"):
            try:
                from maya import cmds
                cmds.select(key[5:], replace=True)
            except (ImportError, RuntimeError, ValueError):
                pass
        elif key == "control":
            self._template.setFocus()
            self._template.selectAll()
        elif key.startswith("group:"):
            import re
            if self._offsets.current() != "Groups":
                self._offsets.set_current("Groups")
                self._on_offsets("Groups")
            words = list(re.finditer(r"[^,\s]+", self._offset_names.text()))
            index = int(key[6:])
            self._offset_names.setFocus()
            if index < len(words):
                self._offset_names.setSelection(words[index].start(), len(words[index].group()))
            else:
                self._offset_names.selectAll()
        elif key in ("zero", "drive"):
            self._setting_menu(key).exec(where)

    def _setting_menu(self, key: str) -> "qt.QtWidgets.QMenu":
        """Zero ("zero") or Drive ("drive") of a new control as a menu; the one that is set is marked."""
        control = self._offsets if key == "zero" else self._drive
        lines = (("None", "clear", "No zero", "The control keeps its own values"),
                 ("Groups", "zero_out", "Groups above it", "One group per suffix of the Zero row"),
                 ("Matrix", "zero_matrix", "In its matrix", "Its offsetParentMatrix holds the place: no group")) \
            if key == "zero" else \
                (("None", "clear", "Doesn't drive", "The control only stands there"),
                 ("Shape", "cvs", "The curve onto the object", "No new object: the object gets the curve as its shape"),
                 ("Constrain", "drive_constraint", "Constraints", "Parent + scale constraints"),
                 ("Matrix", "drive_matrix", "Matrix", "The object's offsetParentMatrix: no constraint node"))
        tone = (self._zero_groups_button if key == "zero" else self._drive_constraint).iconColor
        menu = self._menu()
        self._menu_caption(menu, "Zero of a new control" if key == "zero" else "What a new control does to its object")
        for option, icon, text, tip in lines:
            self._menu_item(menu, icon, text, lambda option=option: self._pick_setting(control, option), tip, tone,
                            hint="✓" if control.current() == option else "")
        return menu

    # ---- the bone on the preview: Drive = Shape, as a picture

    _drive_before = "None"       # what Drive was before the bone was switched on: switching it off goes back
    _worn = ()                   # the selected joints that wear a curve (joint controls): the eye is theirs

    def _read_joint_controls(self, targets: list) -> None:
        """The eye shows how the selected joint controls are drawn NOW (read from the scene on every
        change of the selection) — not what the setting says."""
        try:
            from msl_tools.msl.tools.maya.controls import scene
            self._worn = tuple(scene.joint_controls(targets))
            hidden = scene.bones_hidden(list(self._worn)) if self._worn else bool(self._settings.get("hide_joint", True))
        except ImportError:
            self._worn, hidden = (), bool(self._settings.get("hide_joint", True))
        if self._hide_joint.isChecked() == hidden:       # the eye is OPEN (checked) while the bone is seen
            self._syncing_bone = True
            try:
                self._hide_joint.setChecked(not hidden)
            finally:
                self._syncing_bone = False
        self._sync_bone()

    def _show_eye(self, *_args) -> None:
        """Open while the bone is seen, closed while it is not."""
        self._hide_joint.set_source_icon(self._eye_icons[self._hide_joint.isChecked()])

    def _on_hide_joint(self, seen: bool) -> None:
        if self._syncing_bone or self._loading:
            return
        if not self._worn:
            self._save()                # nothing to change in the scene: it is how the next ones are made
            return
        from msl_tools.msl.tools.maya.controls import scene
        count = scene.set_bones_hidden(list(self._worn), not seen)
        self._say(f"{count} joint control{'s' if count != 1 else ''}: " +
                  ("the bone is seen too" if seen else "only the curve is seen") + " · Ctrl+Z undoes it", "done")

    def _on_bone(self, on: bool) -> None:
        if self._syncing_bone or self._loading:
            return
        if on:
            if self._drive.current() != "Shape":
                self._drive_before = self._drive.current()
            self._pick_setting(self._drive, "Shape")
        elif self._drive.current() == "Shape":
            self._pick_setting(self._drive, self._drive_before if self._drive_before != "Shape" else "None")

    _syncing_bone = False

    def _sync_bone(self) -> None:
        """The bone follows Drive, whoever changed it."""
        wanted = self._drive.current() == "Shape"
        shown = wanted or bool(self._worn)              # the eye: with the bone, or for selected joint controls
        if self._hide_joint.isHidden() == shown:
            self._hide_joint.setVisible(shown)
        if self._bone.isChecked() != wanted:
            self._syncing_bone = True
            try:
                self._bone.setChecked(wanted)
            finally:
                self._syncing_bone = False

    def _pick_setting(self, control, option: str) -> None:
        control.set_current(option)
        if control is self._offsets:
            self._on_offsets(option)
        else:
            self._save()

    # ---- the ghost: the same, in Maya's own viewport

    _made = frozenset()      # what the last Create made / shaped: no ghost on it while it stays selected

    def _update_ghost(self, entries: list) -> None:
        try:
            from maya import cmds as _maya      # no Maya here: no ghost
        except ImportError:
            return
        from msl_tools.msl.tools.maya.controls import ghost
        targets = [entry for entry in entries if isinstance(entry, str)]
        if self._made and (len(targets) != len(entries) or not set(targets) <= self._made):
            self._made = frozenset()
        from msl_tools.msl.tools.maya.controls import scene
        # a selected CONTROL doesn't get a ghost of a new one: it gets the marks of what it is tied into
        links = [target for target in targets if scene.curve_shapes(target)]
        fresh = [] if self._made else [entry for entry in entries if not (isinstance(entry, str) and entry in links)]
        if not (self._ghost.isChecked() and self.isVisible() and (fresh or links)):
            ghost.clear()
            return
        try:
            drive = {"constrain": "constraint"}.get(self._drive.current().lower(), self._drive.current().lower())
            zero = ("none", 0) if drive == "shape" else (self._offsets.current().lower(), len(self._offset_suffixes()))
            ghost.show(self._picked_shape(), fresh, self._size.value(), self._view.axis(), self._fit.isChecked(),
                       self._control_rgb, zero=zero, drive=drive, links=links)
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

    def _color_menu(self) -> "qt.QtWidgets.QMenu":
        by_side, own = self._side_color.isChecked(), self._own_rgb() is not None
        menu = self._menu()
        self._menu_caption(menu, "Color of a new control")
        self._menu_item(menu, "mirror_sides", "By its side", lambda: self._set_color_mode("side"),
                        "Left blue, right red, middle yellow", hint="✓" if by_side else "")
        self._menu_item(menu, "color_pick", "Your color…", self._pick_own_color,
                        "Pick one color for every new control", hint="✓" if own and not by_side else "")
        self._menu_item(menu, "clear", "No color", lambda: self._set_color_mode("none"),
                        "Maya's default color: no override", hint="✓" if not own and not by_side else "")
        return menu

    def _on_color_chip_menu(self, _key: str, position) -> None:
        self._color_menu().exec(position)

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
        self._bone.setChecked(drive == "Shape")
        self._hide_joint.setChecked(not bool(s.get("hide_joint", True)))
        self._show_eye()
        self._as_joint.setChecked(bool(s.get("as_joint", False)))
        self._hide_joint.setVisible(drive == "Shape")
        self._chain.setChecked(bool(s.get("chain", True)))
        self._ghost.setChecked(bool(s.get("ghost", True)))
        self._shape_step.set_value(float(s.get("shape_step", 0.1)))
        self._shape_angle.set_value(float(s.get("shape_angle", 90.0)))
        self._shape_factor.set_value(float(s.get("shape_factor", 1.25)))
        self._middle.setChecked(bool(s.get("middle", False)))
        self._side_color.setChecked(bool(s.get("side_color", True)))
        category = s.get("category", ALL)
        self._categories.set_current(category if category in (ALL,) + shape_data.CATEGORIES else ALL)
        self._control_card.set_open(not dict(s.get("folded") or {}).get("control", False))
        self._selected_card.set_open(not dict(s.get("folded") or {}).get("selected", False))
        self._fit_library()
        self._show_heading()
        self._show_offset_names()
        self._apply_color_settings()
        self._apply_attribute_settings()
        self._apply_transform_settings()
        self._apply_card_order()

    def _save(self, *_args) -> None:
        if self._loading:
            return
        values = {"template": self._template.text().strip(), "size": self._size.value(),
                  "fit": self._fit.isChecked(), "axis": self._view.axis(), "offsets": self._offsets.current(),
                  "offset_names": self._offset_names.text().strip(), "chain": self._chain.isChecked(),
                  "side_color": self._side_color.isChecked(), "drive": self._drive.current(),
                  "ghost": self._ghost.isChecked(), "middle": self._middle.isChecked(),
                  "hide_joint": (not self._hide_joint.isChecked()) if not self._worn else
                  bool(self._settings.get("hide_joint", True)), "as_joint": self._as_joint.isChecked(),
                  "shape_step": self._shape_step.value(), "shape_angle": self._shape_angle.value(),
                  "shape_factor": self._shape_factor.value()}
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value
        self._sync_bone()
        self._refresh_live()

    def _save_folded(self, key: str, opened: bool) -> None:
        folded = dict(self._settings.get("folded") or {})
        folded[key] = not opened
        self._settings["folded"] = folded

    # ------------------------------------------------------------------ the library

















    # ---- the shape under the pointer in the library, looked at before it is picked




    # ---- the editor: the preview grown into the library's room








        # (the window gives the editor its room and takes it back by itself: it follows the content)








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


    def _show_preview(self) -> None:
        shape = self._previewed_shape()
        axis = self._view.axis()
        self._view.set_curves(shape_data.oriented(shape.curves, axis), axis)
        self._refresh_live()




    # ------------------------------------------------------------------ actions

    def _say(self, text: str, state: str = "") -> None:
        self.status_changed.emit(text, state)
        if not self._loading:       # something was done: the buttons' marks may be out of date
            qt.QtCore.QTimer.singleShot(0, self._refresh_states)


    def _sides(self) -> rules.Sides:
        """The Rename tool's sides (one setting for both tools)."""
        saved = Resources().configsMayaMng.get_config("rename")["settings"]
        return rules.Sides.from_settings(saved.get("sides"))

    def create(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        shape = self._picked_shape()
        names = self._offset_suffixes()
        drive = {"constrain": "constraint"}.get(self._drive.current().lower(), self._drive.current().lower())
        entries = scene.selection_targets(self._view.axis(), self._middle.isChecked())
        targets = [entry for entry in entries if isinstance(entry, str)]
        parts = len(entries) - len(targets)
        if drive == "shape" and parts and not targets:
            self._say("The curve can't become the shape of a vertex, an edge or a face — pick another Drive", "error")
            return
        notes = []
        self._clear_ghost()
        try:
            made = scene.create(shape, entries, self._template.text().strip(), self._size.value(),
                                self._view.axis(), self._fit.isChecked(), self._offsets.current().lower(),
                                names, self._chain.isChecked(), self._side_color.isChecked(), self._sides(),
                                drive=drive, notes=notes, rgb=self._own_rgb(),
                                as_joint=self._as_joint.isChecked(),
                                hide_joint=bool(self._settings.get("hide_joint", True)))
        except RuntimeError as error:
            self._say(f"Maya refused: {error}".strip(), "error")
            return
        self._made = frozenset(made)
        if self._middle.isChecked():
            # for this one Create: left on, it kept making ONE control of several objects, unnoticed
            self._middle.setChecked(False)
        short = [path.rpartition("|")[2] for path in made]
        listed = ", ".join(short[:3]) + ("…" if len(short) > 3 else "")
        if drive == "shape" and targets:
            self._say(f"“{shape.title()}” is now the shape of {len(made)}: {listed} · Ctrl+Z undoes it", "done")
            return
        text = f"Created {len(made)}: {listed}"
        if targets and drive in ("constraint", "matrix"):
            driven = len(targets) - len(notes)
            text += f" · {driven} driven by {'constraints' if drive == 'constraint' else 'the matrix'}"
        if notes:
            text += f" · NOT driven — {notes[0]}" + (f" (+{len(notes) - 1})" if len(notes) > 1 else "")
        if parts and drive in ("constraint", "matrix"):
            text += " · a vertex, an edge or a face can't be driven: those only stand there"
        self._say(text + " · Ctrl+Z undoes it", "error" if notes and len(notes) == len(made) else "done")








    # ------------------------------------------------------------------ editing shapes




































    def _offset_suffixes(self) -> list:
        return [part.strip() for part in self._offset_names.text().replace(",", " ").split() if part.strip()] \
            or ["offset"]


