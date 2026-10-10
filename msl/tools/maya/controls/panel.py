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
from msl_tools.msl.tools.maya.controls.panel_color import _ColorMixin
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

ALL = "All"
OFFSET_MODES = ("None", "Groups", "Matrix")
DRIVES = ("None", "Shape", "Constrain", "Matrix")
SHAPES_FILTER = "MSL control shapes (*.json)"
EDITOR_HEIGHT = 456
THUMB = 38
CELL = THUMB + 8
FAVORITE_ROWS, LIBRARY_ROWS = 2, 3         # how tall the grid is: your shapes / the whole library
STAR = 13                                  # the star in a tile's corner (and the spot that takes its click)
# the shapes a fresh install starts with as favorites — the ones every rig uses
FIRST_FAVORITES = ("circle", "square", "cube", "sphere", "diamond", "arrow", "double_arrow", "four_arrows",
                   "pin", "locator", "cross", "root")


class CategoryBox(BaseComboBox):
    """The library's categories as one drop-down in the card's heading (they were a row of chips)."""

    clicked = qt.QtCore.Signal(str)

    def __init__(self, names, parent=None):
        super().__init__(list(names), names[0], enable_wheel=False, parent=parent)
        self.activated.connect(lambda _index: self.clicked.emit(self.currentText()))

    def current(self) -> str:
        return self.currentText()

    def set_current(self, name: str) -> None:
        self.setCurrentText(name)


class ShapeGrid(qt.QtWidgets.QListWidget):
    """The shapes as thumbnails in rows (QListWidget's icon mode), tinted by qproperty
    thumbColor; the name is the tooltip."""

    thumbColor = color_property("_thumb", "_retint")
    starColor = color_property("_star", "_repaint_stars")            # a favorite's star
    starIdleColor = color_property("_star_idle", "_repaint_stars")   # the hollow star of the hovered tile

    def _repaint_stars(self) -> None:
        self.viewport().update()

    hovered = qt.QtCore.Signal(str)      # the shape under the pointer ("" = none)
    star_clicked = qt.QtCore.Signal(str) # the star in a tile's corner was clicked

    # ---- the order of the tiles by dragging one (the favorites: `set_reorderable`). Done by hand —
    #      an icon-mode list's own drag moves tiles freely, not in order.

    dropColor = color_property("_drop", "_repaint_stars")      # the line where a dragged tile would land
    order_changed = qt.QtCore.Signal(list)                     # the names in their new order

    def set_reorderable(self, on: bool) -> None:
        self._reorderable = bool(on)
        if not on:
            self._end_drag()

    def _end_drag(self) -> None:
        if self._dragging:
            self.viewport().unsetCursor()
        self._drag_name, self._dragging, self._drop_index = "", False, -1
        self.viewport().update()

    def _drop_index_at(self, position) -> tuple:
        """(before which tile a drop at `position` lands — count = after the last —, whether that is
        the END of the pointer's row: the line then stands after the row's last tile)."""
        if not self.count():
            return 0, False
        first, last = self.visualItemRect(self.item(0)), self.visualItemRect(self.item(self.count() - 1))
        y = max(first.top(), min(last.bottom(), position.y()))
        in_row = -1
        for row in range(self.count()):
            rect = self.visualItemRect(self.item(row))
            if rect.top() <= y <= rect.bottom():
                if position.x() < rect.center().x():
                    return row, False
                in_row = row
        return in_row + 1, in_row + 1 < self.count()

    def _drop_line(self):
        """The drop line's two ends, or None."""
        if not self._dragging or self._drop_index < 0 or not self.count():
            return None
        if self._drop_index < self.count():
            rect = self.visualItemRect(self.item(self._drop_index))
            x = rect.left()
            # the first tile of a row, while the pointer is still on the row above: the line stands
            # at the END of that row
            if self._drop_index and self._drop_row_end:
                rect = self.visualItemRect(self.item(self._drop_index - 1))
                x = rect.right()
        else:
            rect = self.visualItemRect(self.item(self.count() - 1))
            x = rect.right()
        return qt.QtCore.QPointF(x + 0.5, rect.top() + 4), qt.QtCore.QPointF(x + 0.5, rect.bottom() - 4)

    def mouseMoveEvent(self, event) -> None:
        position = event.position().toPoint()
        if self._drag_name and event.buttons() & qt.QtCore.Qt.MouseButton.LeftButton:
            # a press on a tile is held: no super() — the list would pick every tile it passes
            if not self._dragging and (position - self._drag_from).manhattanLength() >= \
                    qt.QtWidgets.QApplication.startDragDistance():
                self._dragging = True
                self.viewport().setCursor(qt.QtCore.Qt.CursorShape.ClosedHandCursor)
                if self._hovered:
                    self._hovered = ""
                    self.hovered.emit("")
            if self._dragging:
                self._drop_index, self._drop_row_end = self._drop_index_at(position)
                self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)
        item = self.itemAt(position)
        name = item.data(qt.QtCore.Qt.ItemDataRole.UserRole) if item is not None else ""
        if name != self._hovered:
            self._hovered = name
            self.viewport().update()
            self.hovered.emit(name)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._hovered:
            self._hovered = ""
            self.viewport().update()
            self.hovered.emit("")

    # ---- the star in a tile's corner: a favorite's is always drawn (while the whole library shows),
    #      the tile under the pointer shows one to click

    def set_favorites(self, names, always: bool) -> None:
        """`names`: the favorite shapes; `always`: draw their stars all the time (the whole library is
        shown) — else only on the tile under the pointer (every tile shown is a favorite)."""
        self._favorites, self._stars_always = set(names), always
        self.viewport().update()

    def _star_rect(self, item) -> "qt.QtCore.QRect":
        rect = self.visualItemRect(item)
        return qt.QtCore.QRect(rect.right() - STAR - 1, rect.top() + 2, STAR, STAR)

    def star_at(self, position) -> str:
        """The shape whose star is at `position` (viewport), or ""."""
        item = self.itemAt(position)
        if item is not None and self._star_rect(item).adjusted(-2, -2, 2, 2).contains(position):
            return item.data(qt.QtCore.Qt.ItemDataRole.UserRole)
        return ""

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.star_at(event.position().toPoint()):
            self._star_pressed = self.star_at(event.position().toPoint())
            event.accept()          # the star's own click: the tile is not picked
            return
        self._star_pressed = ""
        super().mousePressEvent(event)
        item = self.itemAt(event.position().toPoint())
        if self._reorderable and event.button() == qt.QtCore.Qt.MouseButton.LeftButton and item is not None \
                and self.count() > 1:
            self._drag_name = item.data(qt.QtCore.Qt.ItemDataRole.UserRole)
            self._drag_from = event.position().toPoint()

    def _emit_order(self) -> None:
        names, self._new_order = self._new_order, []
        if names:
            self.order_changed.emit(names)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            names = [self.item(row).data(qt.QtCore.Qt.ItemDataRole.UserRole) for row in range(self.count())]
            source, target = names.index(self._drag_name), self._drop_index
            self._end_drag()
            if target not in (source, source + 1) and target >= 0:
                name = names.pop(source)
                names.insert(target - 1 if target > source else target, name)
                self._new_order = names          # sent on the next turn: the owner rebuilds the list
                qt.QtCore.QTimer.singleShot(0, self._emit_order)
            event.accept()
            return
        self._drag_name = ""
        pressed, self._star_pressed = self._star_pressed, ""
        if pressed:
            if self.star_at(event.position().toPoint()) == pressed:
                # on the next turn of the event loop: the owner rebuilds the list, and that must not
                # happen inside the click
                self._star_name = pressed
                qt.QtCore.QTimer.singleShot(0, self._emit_star)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.star_at(event.position().toPoint()):
            event.accept()          # a fast second click on the star is no "create"
            return
        super().mouseDoubleClickEvent(event)

    def _emit_star(self) -> None:
        name, self._star_name = self._star_name, ""
        if name:
            self.star_clicked.emit(name)

    @staticmethod
    def _star_path(rect) -> "qt.QtGui.QPainterPath":
        import math
        path = qt.QtGui.QPainterPath()
        cx, cy, outer = rect.center().x() + 0.5, rect.center().y() + 0.5, rect.width() / 2.0
        for index in range(10):
            radius = outer if index % 2 == 0 else outer * 0.45
            angle = -math.pi / 2 + index * math.pi / 5
            point = qt.QtCore.QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle))
            path.lineTo(point) if index else path.moveTo(point)
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = qt.QtGui.QPainter(self.viewport())
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        for index in range(self.count()):
            item = self.item(index)
            name = item.data(qt.QtCore.Qt.ItemDataRole.UserRole)
            favorite, under = name in self._favorites, name == self._hovered
            if not ((favorite and self._stars_always) or under):
                continue
            path = self._star_path(self._star_rect(item))
            if favorite:
                painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(self._star)
            else:
                painter.setPen(qt.QtGui.QPen(self._star_idle, 1.2))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        line = self._drop_line()
        if line is not None:
            pen = qt.QtGui.QPen(self._drop, 2.0)
            pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(*line)
        painter.end()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = ""
        self._favorites, self._stars_always = set(), False
        self._star_pressed = self._star_name = ""
        self._reorderable = self._dragging = self._drop_row_end = False
        self._drag_name, self._drop_index, self._new_order = "", -1, []
        self._drag_from = qt.QtCore.QPoint()
        self.setMouseTracking(True)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        self._thumb = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)
        self._star = qt.QtGui.QColor(ThemeRegistry.fallback().accent)
        self._star_idle = qt.QtGui.QColor(ThemeRegistry.fallback().text_secondary)
        self._drop = qt.QtGui.QColor(ThemeRegistry.fallback().accent)
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

    def _tip(self, shape) -> str:
        return (shape.title() + (" — yours" if shape.user else " — corrected by you" if shape.changed else "") +
                ("\n★ a favorite — the star in its corner takes it out" if shape.name in self._favorites
                 else "\nThe star in its corner adds it to your favorites"))

    def set_shapes(self, shapes: list, current: str) -> None:
        if self.count() == len(shapes) and [shape.name for shape in shapes] == [shape.name for shape in self._shapes]:
            # the same tiles (a star was clicked): nothing is rebuilt, so the list stays where it is
            # scrolled to — a rebuild jumped back to the top
            self._shapes = list(shapes)
            for index, shape in enumerate(self._shapes):
                self.item(index).setToolTip(self._tip(shape))
                if shape.name == current and self.currentItem() is not self.item(index):
                    self.blockSignals(True)
                    self.setCurrentItem(self.item(index))
                    self.blockSignals(False)
            self._retint()
            self.viewport().update()
            return
        # the same shapes in another order (a star clicked in a search: favorites go first) keep the
        # place too; another set of shapes starts at its top
        same = {shape.name for shape in shapes} == {shape.name for shape in self._shapes}
        scrolled = self.verticalScrollBar().value() if same else 0
        self._shapes = list(shapes)
        self.blockSignals(True)
        self.clear()
        for shape in self._shapes:
            item = qt.QtWidgets.QListWidgetItem()
            item.setData(qt.QtCore.Qt.ItemDataRole.UserRole, shape.name)
            item.setToolTip(self._tip(shape))
            item.setSizeHint(qt.QtCore.QSize(THUMB + 8, THUMB + 8))
            self.addItem(item)
            if shape.name == current:
                item.setSelected(True)
                self.setCurrentItem(item)
        self.blockSignals(False)
        self._retint()
        if scrolled:
            self.doItemsLayout()
            self.verticalScrollBar().setValue(min(scrolled, self.verticalScrollBar().maximum()))

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

    menuIconColor = color_property("_menu_icon", None)     # a menu's icons that belong to no colored button

    TOOL_NAME = "controls"
    DEFAULTS = {"shape": "circle", "category": ALL, "template": DEFAULT_TEMPLATE, "size": 1.0, "fit": True,
                "axis": "X", "offsets": "Groups", "offset_names": "offset", "chain": True, "side_color": True,
                "drive": "None", "own_color": "", "ghost": True, "middle": False,
                "shape_step": 0.1, "shape_angle": 90.0, "shape_factor": 1.25, "hide_joint": True, "as_joint": False,
                "favorites": list(FIRST_FAVORITES), "library": "favorites",
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
        self._strip = HierarchyStrip()
        self._strip.setObjectName("controlsStrip")
        card.body_layout.addWidget(self._strip)
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
            self._turns[axis] = TurnButton(axis, f"Turn about {axis}\nThe selected controls' shapes about their "
                                                 f"own {axis}, by the angle beside it (Shift: the other way)")
            self._turns[axis].setObjectName("controlsTool")
        self._shrink = tool("shrink", "orange", "Smaller", "The selected controls' shapes smaller: divided by "
                                                           "the number beside it")
        self._grow = tool("grow", "orange", "Bigger", "The selected controls' shapes bigger: times the number "
                                                      "beside it")
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
        self._strip_shape = tool("shape_off", "blue", "Take the curve off", "The selected objects lose their curve — "
                                 "a joint that was made a control (the bone on the preview) is a plain joint "
                                 "again, drawn as a bone")
        # the other side (teal)
        self._mirror = tool("mirror_shape", "teal", "Mirror", "A mirrored copy of each selected control on the "
                            "other side (lf_ ↔ rt_, _L ↔ _R; a name without a side gets one: arm_ctrl → rt_arm_ctrl): its zero groups too, under the other side's parent; "
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
        # drive: tie a control that exists to its object, or let go (pink)
        self._drive_constraint = tool("drive_constraint", "pink", "Drive with constraints", "The object follows "
                                      "its control through parent + scale constraints, staying where it is\n"
                                      "Select CONTROLS — each finds its object by its name (lf_arm_ctrl → "
                                      "lf_arm_jnt) — or a control and its object(s): pairs by the order picked, "
                                      "or one control for all")
        self._drive_matrix = tool("drive_matrix", "pink", "Drive with the matrix", "The object follows its control "
                                  "through its offsetParentMatrix: no constraint node, its channels read zero\n"
                                  "Select controls (objects found by name), or a control and its object(s)")
        self._drive_off = tool("drive_off", "pink", "Let go", "Untie, from either end: a selected OBJECT is freed "
                               "of the control that drives it; a selected CONTROL lets go of what it drives. "
                               "The objects stay where they stand")
        # show and select (yellow)
        self._on_top_button = tool("on_top", "yellow", "Always on top", "The selected controls' curves drawn "
                                                                        "through the geometry — on / off")
        self._select_below = tool("branch", "yellow", "Controls under the selection", "Select every control "
                                                                                      "(curve) under what is selected")
        self._select_all = tool("select_all", "yellow", "Controls in the scene", "Select every control (curve) in "
                                                                               "the scene")
        # helpers of the rigging itself (plain)
        self._locators = tool("locator", "", "Locators on the selection", "A locator on each selected object — "
                              "at its pivot, turned like it — and on each selected vertex, CV, edge or face (its "
                              "middle)\nRight click: along the surface's normal · ONE locator in the "
                              "middle of everything selected (the center of an edge loop)", menu=True)
        self._joints = tool("joint_chain", "", "Joints on the selection", "A chain of joints through what is "
                            "selected, in the order picked — locators set out for a skeleton, or vertices: "
                            "each joint under the one before, its X down the bone, named after what it stands "
                            "on (lf_arm_loc → lf_arm_jnt)\nRight click: separate joints, not a chain", menu=True)
        # into the library (green)
        self._capture = tool("bookmark_add", "green", "Save as a shape", "Save the selected curves as a shape of "
                                                                         "yours (it goes under Mine)")

        # (the turn and bigger / smaller buttons stand in the rows below, beside their numbers)
        rows = (((self._cvs,),
                 (self._replace, self._add_shape, self._copy_shape, self._paste_shape, self._combine, self._strip_shape),
                 (self._mirror, self._mirror_update),
                 (self._zero_groups_button, self._zero_matrix_button, self._matrix_back_button)),
                ((self._drive_constraint, self._drive_matrix, self._drive_off),
                 (self._on_top_button, self._select_below, self._select_all),
                 (self._locators, self._joints),
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

        # the shape of a control that exists, by exact steps: off its pivot along an axis; how much a
        # turn turns and a "bigger" grows
        self._shape_step = DragNumberField(0.1, 0.001, 1000.0, 0.05, width=44, decimals=3)
        self._shape_step.setToolTip("The step of the six buttons beside it — drag with the middle mouse button, the wheel")
        self._shape_angle = DragNumberField(90.0, 1.0, 180.0, 5.0, width=38, decimals=1)
        self._shape_angle.setToolTip("The angle, in degrees: the three buttons beside it turn the shape by it "
                                     "about X, Y or Z (Shift + click: the other way)")
        self._shape_factor = DragNumberField(1.25, 1.01, 10.0, 0.05, width=40, decimals=2)
        self._shape_factor.setToolTip("The factor: the two buttons beside it make the shape that much smaller / bigger")
        steps = qt.QtWidgets.QHBoxLayout()
        steps.setSpacing(3)
        steps.addWidget(self._caption("Move"))
        steps.addWidget(self._shape_step)
        self._shifts = {}
        for index, axis in enumerate(shape_data.AXES):
            for sign, mark in ((-1, "−"), (1, "+")):
                made = axis_step_button(axis, mark, f"The selected controls' shapes one step along their own "
                                                    f"{mark}{axis}: off the pivot, the control itself stays "
                                                    "(Shift: five steps)")
                self._shifts[(index, sign)] = made
                steps.addWidget(made)
        steps.addStretch(1)
        card.body_layout.addLayout(steps)
        # each number with the buttons that use it right beside it
        turning = qt.QtWidgets.QHBoxLayout()
        turning.setSpacing(3)
        turning.addWidget(self._caption("Turn"))
        turning.addWidget(self._shape_angle)
        for axis in shape_data.AXES:
            turning.addWidget(self._turns[axis])
        turning.addSpacing(14)
        turning.addWidget(self._caption("Scale"))
        turning.addWidget(self._shape_factor)
        turning.addWidget(self._shrink)
        turning.addWidget(self._grow)
        turning.addStretch(1)
        card.body_layout.addLayout(turning)
        return card

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
            angle = self._shape_angle.value()
            after = shape_data.turned(before, key[-1], -angle if back else angle)
            text = f"turn {'−' if back else ''}{angle:g}° about {key[-1]}"
        elif key.startswith("shift_"):
            axis, sign = int(key[6]), (1 if key.endswith("+") else -1)
            step = sign * self._shape_step.value() * (5 if back else 1)
            after = [shape_data.Curve([tuple(value + (step if index == axis else 0.0) for index, value in enumerate(point))
                                       for point in curve.points], curve.degree, curve.closed) for curve in before]
            text = f"{step:+g} along {shape_data.AXES[axis]}"
        elif key in ("shrink", "grow"):
            factor = self._shape_factor.value() if key == "grow" else 1.0 / self._shape_factor.value()
            after = shape_data.scaled(before, factor)
            text = f"×{factor:.3g}"
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
        self._view.set_notes([])
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

    def _favorites(self) -> list:
        """Your favorite shapes that still exist, in your order."""
        shapes = self.library.all()
        stored = self._settings.get("favorites", None)
        if not isinstance(stored, (list, tuple)):
            # settings from before favorites existed: the usual ones + every shape of the user's own
            stored = list(FIRST_FAVORITES) + list(self.library.mine())
        return [name for name in stored if name in shapes]

    def _whole(self) -> bool:
        return self._settings.get("library", "favorites") == "all"

    def _shown_shapes(self) -> list:
        needle = self._search.text().strip().lower()
        shapes = self.library.all()
        if needle:
            # a search looks through everything, whichever is shown: favorites first
            favorites = self._favorites()
            found = [shape for shape in shapes.values() if needle in shape.name.lower()]
            return sorted(found, key=lambda shape: shape.name not in favorites)
        if not self._whole():
            return [shapes[name] for name in self._favorites()]
        category = self._categories.current() or ALL
        return [shape for shape in shapes.values() if category == ALL or shape.category == category]

    def _refresh_grid(self) -> None:
        searching = bool(self._search.text().strip())
        self._grid.set_favorites(self._favorites(), always=self._whole() or searching)
        self._grid.set_reorderable(not self._whole() and not searching)      # your list: drag a tile
        shown = self._shown_shapes()
        self._grid.set_shapes(shown, self._settings.get("shape", "circle"))
        empty = not shown and not searching and not self._whole() and not self._editor.isVisible()
        self._grid.setVisible(not empty and not self._editor.isVisible())
        self._no_favorites.setVisible(empty)
        self._show_preview()

    def _rows(self) -> int:
        return LIBRARY_ROWS if self._whole() else FAVORITE_ROWS

    def _fit_library(self) -> None:
        """The grid as tall as its rows (two of favorites, three of the library), the preview beside
        it as tall as the grid + Create; the two buttons say which is shown."""
        height = CELL * self._rows() + 6
        self._grid.setFixedHeight(height)
        self._no_favorites.setFixedHeight(height)
        self._view.setFixedHeight(height + 6 + 22)
        self._library_syncing = True
        try:
            self._favorites_only.setChecked(not self._whole())
            self._whole_library.setChecked(self._whole())
        finally:
            self._library_syncing = False

    _library_syncing = False

    def _show_heading(self) -> None:
        opened = self._control_card.is_open()
        for widget in self._heading_extras:
            widget.setVisible(opened and (widget is not self._categories or self._whole()))

    def _set_library(self, which: str) -> None:
        """Your favorites, or the whole library in their place — the window gives it its row."""
        if self._library_syncing:
            return
        before = self._rows()
        if self._settings.get("library", "favorites") != which:
            self._settings["library"] = which
        self._fit_library()
        self._show_heading()
        self._refresh_grid()
        grown = CELL * (self._rows() - before)
        window = self.window()
        if grown and not self._editor.isVisible() and window is not None and window is not self \
                and not window.isMaximized():
            window.resize(window.width(), max(window.minimumHeight(), window.height() + grown))

    def _toggle_favorite(self, name: str) -> None:
        favorites = self._favorites()
        if name in favorites:
            favorites.remove(name)
            self._say(f"“{name}” is out of your favorites — it stays in the library", "")
        else:
            favorites.append(name)
            self._say(f"“{name}” is a favorite now", "done")
        self._settings["favorites"] = favorites
        self._refresh_grid()

    def _add_favorites(self, names) -> None:
        favorites = self._favorites()
        self._settings["favorites"] = favorites + [name for name in names if name not in favorites]

    def _on_favorites_order(self, names: list) -> None:
        """A tile was dragged to another place among the favorites."""
        if not self._whole() and not self._search.text().strip():
            self._settings["favorites"] = list(names)
            self._refresh_grid()

    def _move_favorite(self, name: str, steps: int) -> None:
        favorites = self._favorites()
        if name in favorites:
            index = favorites.index(name)
            favorites.insert(max(0, min(len(favorites) - 1, index + steps)), favorites.pop(index))
            self._settings["favorites"] = favorites
            self._refresh_grid()

    def _show_saved(self) -> None:
        """A shape just saved / brought in is shown: with the library open, under Mine."""
        if self._whole():
            self._categories.set_current("Mine")
            self._settings["category"] = "Mine"

    def _on_category(self, name: str) -> None:
        self._settings["category"] = name
        self._refresh_grid()

    def _on_shape_picked(self) -> None:
        name = self._grid.current_name()
        if name:
            self._settings["shape"] = name
            self._drop_edited()             # another shape: the hand-made changes of the last one go
            if self._editor.isVisible():
                shape = self._library_shape()
                self._editor.open(shape.curves, shape.title())
            self._show_preview()

    # ---- the shape under the pointer in the library, looked at before it is picked

    _hover_shape = ""

    def _on_shape_hover(self, name: str) -> None:
        if name == self._hover_shape or self._loading:
            return
        self._hover_shape = name
        shape = self._previewed_shape()
        self._view.set_curves(shape_data.oriented(shape.curves, self._view.axis()), self._view.axis())
        try:
            if self._hovered_action:
                self._show_action()
            else:
                self._draw_live(with_ghost=False)       # the ghost in Maya stays the PICKED shape's
        except Exception as error:
            self._report("The preview couldn't show that shape", error)

    def _previewed_shape(self) -> "shape_data.Shape":
        """What the small preview shows: the shape under the pointer in the library, else the picked one."""
        return (self.library.get(self._hover_shape) if self._hover_shape else None) or self._picked_shape()

    # ---- the editor: the preview grown into the library's room

    _edited = None          # the picked shape as changed by hand; Create, the ghost and Replace use it
    _taken = ""             # the control the working copy was TAKEN from ("" = it began as a library shape)

    def _pick_saved(self, name: str) -> None:
        """A shape just saved / brought in becomes THE picked shape. The editor's working copy of the
        shape picked before goes with it — else Create kept making that old copy while the library
        showed the new shape as picked (it did: a curve saved from the scene, then Create made a pin)."""
        self._settings["shape"] = name
        self._drop_edited()
        if self._editor.isVisible():
            shape = self._library_shape()
            self._editor.open(shape.curves, shape.title())

    def _drop_edited(self) -> None:
        self._edited, self._taken = None, ""
        self._editor.set_apply_text("Onto the selected controls")

    @staticmethod
    def _unturned(curves: list, axis: str) -> list:
        """Curves as they are on a control, turned back to how the library keeps a shape (facing +Y):
        turned to `axis` again — what Create does — they are exactly what they were."""
        if axis == "X":
            back = lambda q: (q[1], q[0], -q[2])       # the turn to X is its own inverse
        elif axis == "Z":
            back = lambda q: (q[0], q[2], -q[1])
        else:
            return curves
        return [shape_data.Curve([back(point) for point in curve.points], curve.degree, curve.closed) for curve in curves]

    @staticmethod
    def _curve_selected() -> bool:
        try:
            from msl_tools.msl.tools.maya.controls import scene
            return bool(scene.controls_in_selection())
        except (ImportError, RuntimeError, ValueError):
            return False

    def _take_shape(self) -> None:
        """The selected control's shape into the editor, as it is in the scene: to be changed and put
        back exactly, made again elsewhere, or saved as a shape of yours."""
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        name = controls[0].rpartition("|")[2]
        curves = self._unturned(scene.read_curves(controls[0]), self._view.axis())
        self._edited = shape_data.Shape(name.rpartition(":")[2], curves, "Mine", True)
        self._taken = name
        self._editor.open(curves, f"{name} · from the scene")
        self._editor.set_apply_text("Back onto the selected controls")
        self._show_preview()
        self._say(f"The curve {name} is in the editor — change it, put it back, or Save… it as a shape of yours "
                  "(Reset: the library's shape)", "done")

    def _library_shape(self) -> "shape_data.Shape":
        return self.library.get(self._settings.get("shape", "circle")) or shape_data.BUILT_IN["circle"]

    def _set_editing(self, on: bool) -> None:
        if on == self._editor.isVisible():
            return
        shelf_height = self._view.height()
        for widget in (self._grid, self._view, self._create):
            widget.setVisible(not on)
        self._no_favorites.hide()
        self._editor.setVisible(on)
        if not on:
            self._refresh_grid()
        if on:
            shape = self._picked_shape()
            self._editor.open(shape.curves, shape.title() + (" · edited" if self._edited is not None else ""))
            self._editor.set_create_text(self._create.text())
            # a curve is selected in the scene: THAT is what one opens the editor for — it comes in as
            # it is, to be changed, put back or saved as a shape (Reset: the library's shape instead)
            if not self._taken and self._curve_selected():
                self._take_shape()
        # the window gives the editor its room, and takes it back
        window = self.window()
        grown = EDITOR_HEIGHT - shelf_height
        if window is not None and window is not self and not window.isMaximized():
            window.resize(window.width(), max(window.minimumHeight(), window.height() + (grown if on else -grown)))

    def _on_shape_edited(self) -> None:
        if self._taken:
            self._edited = shape_data.Shape(self._edited.name, self._editor.curves(), "Mine", True)
            self._editor.set_title(f"{self._taken} · from the scene · edited")
        else:
            source = self._library_shape()
            self._edited = shape_data.Shape(source.name, self._editor.curves(), source.category, True)
            self._editor.set_title(source.title() + " · edited")
        self._show_preview()

    def _reset_edited(self) -> None:
        self._drop_edited()
        source = self._library_shape()
        self._editor.open(source.curves, source.title())
        self._show_preview()
        self._say(f"“{source.title()}” is as the library has it again", "")

    def _on_save_edited(self) -> None:
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        source = self._edited if self._taken else self._library_shape()
        button = self._editor.save_button()
        menu = self._menu()
        if not self._taken:
            # a fix of the shape itself: it stays what and where it is in the library
            self._menu_caption(menu, "The library's shape")
            self._menu_item(menu, "save", f"Update “{source.title()}”", self._update_shape,
                            "The library keeps the shape as it is in the editor now, in its place — "
                            + ("your shape is saved over" if source.user else
                               "a correction of the built-in shape; the library's right-click menu can "
                               "bring the built-in one back"))
            menu.addSeparator()
        self._menu_caption(menu, "A new shape of yours — its name:")
        _field_action(menu, source.name, "Shape name", self._save_edited)
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height())))

    def _update_shape(self) -> None:
        """The picked library shape becomes what is in the editor (not a new shape under Mine)."""
        name = self._settings.get("shape", "circle")
        if self._taken or not self.library.update(name, self._editor.curves()):
            self._say("Nothing to update — pick a shape of the library first", "error")
            return
        self._drop_edited()
        self._refresh_grid()
        shape = self._library_shape()
        self._editor.open(shape.curves, shape.title())
        self._say(f"The library's “{shape.title()}” is updated" +
                  ("" if shape.user else " — right click it in the library to bring the built-in one back"), "done")

    def _restore_shape(self, name: str) -> None:
        if self.library.restore(name):
            if name == self._settings.get("shape"):
                self._drop_edited()
                if self._editor.isVisible():
                    shape = self._library_shape()
                    self._editor.open(shape.curves, shape.title())
            self._refresh_grid()
            self._say(f"“{name}” is the built-in shape again", "done")

    def _save_edited(self, name: str) -> None:
        saved = self.library.add(name, self._editor.curves())
        self._drop_edited()
        self._settings["shape"] = saved
        self._add_favorites([saved])
        self._show_saved()
        self._refresh_grid()
        shape = self._library_shape()
        self._editor.open(shape.curves, shape.title())
        self._say(f"Saved the shape “{saved}” — it is among your favorites (and under Mine)", "done")

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
        """The shape a control is made of: the library's picked one — as changed in the editor, if it was."""
        return self._edited if self._edited is not None else self._library_shape()

    def _show_preview(self) -> None:
        shape = self._previewed_shape()
        axis = self._view.axis()
        self._view.set_curves(shape_data.oriented(shape.curves, axis), axis)
        self._refresh_live()

    def _grid_menu(self, name: str = "") -> "qt.QtWidgets.QMenu":
        """The library's menu: for the shape under the pointer (`name`), then your own shapes' file."""
        menu = self._menu()
        shape = self.library.get(name) if name else None
        if shape is not None:
            self._menu_caption(menu, shape.title())
            replaces = self._only_controls_selected()      # what a double click does NOW
            self._menu_item(menu, "controls", "Create", self.create, "A control of this shape on the selection",
                            hint="" if replaces else "double click")
            self._menu_item(menu, "replace", "Replace the selected controls' shape", self._on_replace,
                            "As big as theirs, same color", self._replace.iconColor,
                            hint="double click" if replaces else "")
            self._menu_item(menu, "add", "Add to the selected controls", self._on_add_shape,
                            "Beside the shape they have", self._replace.iconColor)
            favorites = self._favorites()
            if name in favorites:
                self._menu_item(menu, "star", "Take out of favorites", lambda: self._toggle_favorite(name),
                                "It stays in the library", hint="the star")
                if not self._whole() and not self._search.text().strip() and len(favorites) > 1:
                    self._menu_item(menu, "chevron_left", "Move earlier", lambda: self._move_favorite(name, -1))
                    self._menu_item(menu, "chevron_right", "Move later", lambda: self._move_favorite(name, 1))
                    self._menu_item(menu, "chevron_up", "Move to the front",
                                    lambda: self._move_favorite(name, -len(favorites)))
            else:
                self._menu_item(menu, "star", "Add to favorites", lambda: self._toggle_favorite(name),
                                "Your short list: what the library shows by default", hint="the star")
            if shape.user:
                self._menu_item(menu, "delete", "Remove from your shapes", lambda: self._remove_shape(name))
            if shape.changed:
                self._menu_item(menu, "undo", "Back to the built-in shape", lambda: self._restore_shape(name),
                                "You updated this shape — this drops your correction")
            menu.addSeparator()
        mine = len(self.library.mine())
        self._menu_caption(menu, f"Your shapes · {mine}")
        self._menu_item(menu, "save", "Into a file…", self._on_export_shapes,
                        "To hand your shapes to someone else").setEnabled(mine > 0)
        self._menu_item(menu, "file_add", "From a file…", self._on_import_shapes, "Add someone's shapes to yours")
        return menu

    def _on_grid_menu(self, position) -> None:
        item = self._grid.itemAt(position)
        name = item.data(qt.QtCore.Qt.ItemDataRole.UserRole) if item is not None else ""
        self._grid_menu(name).exec(self._grid.viewport().mapToGlobal(position))

    def _remove_shape(self, name: str) -> None:
        if self.library.remove(name):
            self._say(f"Removed the shape “{name}”", "done")
            self._refresh_grid()

    # ------------------------------------------------------------------ actions

    def _say(self, text: str, state: str = "") -> None:
        self.status_changed.emit(text, state)
        if not self._loading:       # something was done: the buttons' marks may be out of date
            qt.QtCore.QTimer.singleShot(0, self._refresh_states)

    def _refresh_states(self, selected: "list | None" = None) -> None:
        """The SELECTED buttons show what is ALREADY true of the selection: tied by constraints / the
        matrix, zeroed with groups / in the matrix, drawn on top — the button of it is lit (`on`)."""
        found = {}
        try:
            from msl_tools.msl.tools.maya.controls import scene
            found = scene.states(scene.selected_transforms() if selected is None else selected)
        except ImportError:
            pass
        except Exception as error:
            self._report("Couldn't read what the selection is tied to", error)
        total = 0 if selected is None else len(selected)
        for key, button, what in (("constraint", self._drive_constraint, "tied by constraints"),
                                  ("matrix", self._drive_matrix, "tied through the matrix"),
                                  ("zero_groups", self._zero_groups_button, "zeroed with groups"),
                                  ("zero_matrix", self._zero_matrix_button, "zeroed in the matrix"),
                                  ("on_top", self._on_top_button, "drawn on top")):
            count = int(found.get(key, 0))
            if bool(button.property("on")) != bool(count):
                button.setProperty("on", bool(count))
                repolish(button)
            base = button.toolTip().split("\n● ")[0]
            button.setToolTip(base + (f"\n● {count} of the selected {'is' if count == 1 else 'are'} {what}"
                                      if count else ""))
        tied = bool(found.get("constraint") or found.get("matrix"))
        if bool(self._drive_off.property("on")) != tied:
            self._drive_off.setProperty("on", tied)
            repolish(self._drive_off)

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

    @staticmethod
    def _only_controls_selected() -> bool:
        """Something is selected and every selected object is a control (has curve shapes)."""
        try:
            from msl_tools.msl.tools.maya.controls import scene
            selected = scene.selected_transforms()
            return bool(selected) and all(scene.curve_shapes(item) for item in selected)
        except (ImportError, RuntimeError, ValueError):
            return False

    def _on_shape_double_click(self) -> None:
        """A double click on a library shape: the selected controls get that shape (Replace) when ONLY
        controls are selected; on anything else — or nothing — a control is made, as Create does."""
        if self._only_controls_selected():
            self._on_replace()
        else:
            self.create()

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
            angle = self._shape_angle.value()
            scene.turn(controls, axis, -angle if back else angle)
            self._say(f"Turned {len(controls)} {'−' if back else ''}{angle:g}° about {axis}", "done")

    def _shift_shape(self, axis: int, sign: int) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            shift = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
            offset = [0.0, 0.0, 0.0]
            offset[axis] = sign * self._shape_step.value() * (5 if shift else 1)
            scene.shift(controls, offset)
            self._say(f"The shape of {len(controls)} moved {offset[axis]:+g} along {shape_data.AXES[axis]} · "
                      "Ctrl+Z undoes it", "done")

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
            if self._taken and self._edited is not None:
                # a shape TAKEN from the scene goes back as it is: same size, same place about the pivot
                # (Replace would size a library shape to the control — this one has its own size)
                count = scene.set_curves(controls, shape_data.oriented(shape.curves, self._view.axis()))
                self._say(f"{count} got the edited shape back, exactly · Ctrl+Z undoes it", "done")
                return
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

    def _on_strip_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            stripped = scene.strip_shapes(controls)
            self._say(f"The curve is off {len(stripped)}: " + ", ".join(stripped[:3]) + ("…" if len(stripped) > 3 else "")
                      + " · Ctrl+Z undoes it", "done")
            self._refresh_live()        # they are no controls any more: the preview, the line, the eye

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
        self._pick_saved(added[0])
        self._add_favorites(added)
        self._show_saved()
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

    def _mirror_update_menu(self) -> "qt.QtWidgets.QMenu":
        tone = self._mirror_update.iconColor
        menu = self._menu()
        self._menu_caption(menu, "Only the shape, to the control on the other side")
        for axis in shape_data.AXES:
            self._menu_item(menu, "mirror_update", f"Across {axis}", lambda axis=axis: self._mirror_shapes(axis),
                            f"The mirror plane stands across the world's {axis}", tone, hint="click" if axis == "X" else "")
        return menu

    def _on_mirror_update_menu(self, position) -> None:
        self._mirror_update_menu().exec(self._mirror_update.mapToGlobal(position))

    def _mirror_menu(self) -> "qt.QtWidgets.QMenu":
        tone = self._mirror.iconColor
        menu = self._menu()
        self._menu_caption(menu, "A mirrored copy on the other side")
        for axis in shape_data.AXES:
            self._menu_item(menu, "mirror_shape", f"Across {axis}", lambda axis=axis: self._mirror_to_other(axis),
                            f"The mirror plane stands across the world's {axis}: the copy, its zero groups, its name",
                            tone, hint="click" if axis == "X" else "")
        menu.addSeparator()
        self._menu_caption(menu, "Flip this shape, where it is")
        for axis in shape_data.AXES:
            self._menu_item(menu, "mirror_sides", f"Along its own {axis}", lambda axis=axis: self._flip(axis),
                            "No copy: the shape is turned inside out along that axis of the control", tone)
        return menu

    def _on_mirror_menu(self, position) -> None:
        self._mirror_menu().exec(self._mirror.mapToGlobal(position))

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

    def _drive_selected(self, mode: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        pairs, problems = scene.pair_up(scene.selected_transforms())
        if not pairs:
            self._say("Nothing to tie — " + (problems[0] if problems else "select controls"), "error")
            return
        notes = []
        done = scene.drive_pairs(pairs, mode, notes)
        how = "constraints" if mode == "constraint" else "the matrix"
        text = f"{done} now follow{'s' if done == 1 else ''} {'its control' if done == 1 else 'their controls'} " \
               f"through {how}"
        for each in (notes + problems)[:1]:
            text += f" · NOT tied — {each}" + (f" (+{len(notes + problems) - 1})" if len(notes + problems) > 1 else "")
        self._say(text + (" · Ctrl+Z undoes it" if done else ""), "done" if done else "error")

    def _make_locators(self, center: bool, along_normal: bool = False) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        try:
            made, total = scene.locators_on_selection(center=center, along_normal=along_normal,
                                                      axis=self._view.axis())
        except RuntimeError as error:
            self._say(f"Maya refused: {error}".strip(), "error")
            return
        if not made:
            self._say("Select objects, vertices, edges or faces first", "error")
            return
        short = [path.rpartition("|")[2] for path in made]
        if center:
            text = f"One locator in the middle of {total} selected: {short[0]}"
        else:
            text = f"{len(made)} locator{'s' if len(made) != 1 else ''}: " + ", ".join(short[:3]) + \
                ("…" if len(short) > 3 else "")
            if total > len(made):
                text += f" · the first {len(made)} of {total} (right click: one in the middle)"
        if along_normal:
            text += f" · {self._view.axis()} along the normal"
        self._say(text + " · Ctrl+Z undoes it", "done")

    def _locators_menu(self) -> "qt.QtWidgets.QMenu":
        axis = self._view.axis()
        menu = self._menu()
        self._menu_caption(menu, "A locator on each selected thing")
        self._menu_item(menu, "locator", "On each", lambda: self._make_locators(False),
                        "An object: at its pivot, turned like it · a vertex, edge, face: where it is", hint="click")
        self._menu_item(menu, "locator", f"On each, {axis} along the normal", lambda: self._make_locators(False, True),
                        "Vertices, edges, faces of a mesh: the locator faces away from the surface "
                        "(the axis is the preview's)")
        menu.addSeparator()
        self._menu_caption(menu, "One locator for all of it")
        self._menu_item(menu, "center", "In the middle", lambda: self._make_locators(True),
                        "The center of an edge loop, of several objects")
        self._menu_item(menu, "center", f"In the middle, {axis} across the loop", lambda: self._make_locators(True, True),
                        "Turned along the limb the loop goes around")
        return menu

    def _on_locators_menu(self, position) -> None:
        self._locators_menu().exec(self._locators.mapToGlobal(position))

    def _make_joints(self, chain: bool) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        try:
            made, total = scene.joints_on_selection(chain=chain)
        except RuntimeError as error:
            self._say(f"Maya refused: {error}".strip(), "error")
            return
        if not made:
            self._say("Select locators (or other objects, vertices) in the order of the chain first", "error")
            return
        short = [path.rpartition("|")[2] for path in made]
        text = (f"A chain of {len(made)} joints: " if chain and len(made) > 1 else
                f"{len(made)} joint{'s' if len(made) != 1 else ''}: ") + ", ".join(short[:3]) + \
            ("…" if len(short) > 3 else "")
        if total > len(made):
            text += f" · the first {len(made)} of {total}"
        self._say(text + " · Ctrl+Z undoes it", "done")

    def _joints_menu(self) -> "qt.QtWidgets.QMenu":
        menu = self._menu()
        self._menu_caption(menu, "Joints where the selection is")
        self._menu_item(menu, "joint_chain", "A chain, in the order picked", lambda: self._make_joints(True),
                        "Each joint under the one before, X down the bone", hint="click")
        self._menu_item(menu, "joints_separate", "Separate joints", lambda: self._make_joints(False),
                        "Not connected, each turned like its object")
        return menu

    def _on_joints_menu(self, position) -> None:
        self._joints_menu().exec(self._joints.mapToGlobal(position))

    def _undrive_selected(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        selected = scene.selected_transforms()
        if not selected:
            self._say("Select the object to free, or the control that should let go", "error")
            return
        freed = scene.undrive(selected)
        if not freed:
            self._say("Nothing selected is tied to a control", "")
            return
        self._say(f"Let go of {len(freed)}: " + ", ".join(freed[:3]) + ("…" if len(freed) > 3 else "") +
                  " · Ctrl+Z undoes it", "done")

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
        self._pick_saved(saved)
        self._add_favorites([saved])
        self._show_saved()
        self._refresh_grid()
        self._say(f"Saved the shape “{saved}” — it is among your favorites (and under Mine)", "done")
