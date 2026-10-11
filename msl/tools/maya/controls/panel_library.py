# tools/maya/controls/panel_library.py
"""The Controls panel's shape LIBRARY: the grid of thumbnails (`ShapeGrid`: stars, favorites dragged
into an order, one row or rows that wrap), the categories' drop-down (`CategoryBox`), favorites versus
the whole library, the search, the shape under the pointer, the grid's menu (create, replace, add,
favorites, code, your own shapes to and from a file), a double click. Methods of ControlsPanel, kept
apart by concern (moved out of panel.py as they were)."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.controls import shapes as shape_data
from msl_tools.msl.tools.maya.controls.preview import ShapeView, thumbnail
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from pathlib import Path
from msl_tools.msl.tools.maya.controls.panel_common import ALL, CELL, FAVORITE_ROWS, FIRST_FAVORITES, LIBRARY_ROWS, SHAPES_FILTER, STAR, THUMB


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

    # ---- one row that scrolls sideways (the favorites), or rows that wrap (the library)

    def set_single_row(self, on: bool) -> None:
        if bool(on) == self._single:
            return
        self._single = bool(on)
        self.setWrapping(not self._single)
        self.setVerticalScrollBarPolicy(qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff if self._single
                                        else qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.doItemsLayout()

    def _bar(self):
        return self.horizontalScrollBar() if self._single else self.verticalScrollBar()

    def wheelEvent(self, event) -> None:
        if self._single:
            # the wheel turns the row sideways, a tile at a time
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                bar = self.horizontalScrollBar()
                bar.setValue(bar.value() + (-CELL if delta > 0 else CELL))
                self.viewport().update()
            event.accept()
            return
        super().wheelEvent(event)

    def _paint_more(self, painter) -> None:
        """A small arrow at an end of the row while there are tiles beyond it."""
        bar = self.horizontalScrollBar()
        if not self._single or bar.maximum() <= 0:
            return
        pen = qt.QtGui.QPen(self._star_idle, 1.6)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        middle, right = self.viewport().height() / 2.0, self.viewport().width()
        if bar.value() > 0:
            painter.drawPolyline([qt.QtCore.QPointF(6, middle - 4), qt.QtCore.QPointF(2.5, middle),
                                  qt.QtCore.QPointF(6, middle + 4)])
        if bar.value() < bar.maximum():
            painter.drawPolyline([qt.QtCore.QPointF(right - 6, middle - 4), qt.QtCore.QPointF(right - 2.5, middle),
                                  qt.QtCore.QPointF(right - 6, middle + 4)])

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
                if self._single:        # near an end of the row: it turns under the held tile
                    bar = self.horizontalScrollBar()
                    if position.x() < 14:
                        bar.setValue(bar.value() - 10)
                    elif position.x() > self.viewport().width() - 14:
                        bar.setValue(bar.value() + 10)
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
        self._paint_more(painter)
        painter.end()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = ""
        self._favorites, self._stars_always = set(), False
        self._star_pressed = self._star_name = ""
        self._reorderable = self._dragging = self._drop_row_end = self._single = False
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
        self.setHorizontalScrollMode(qt.QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
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
        scrolled = self._bar().value() if same else 0
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
        self.doItemsLayout()
        if scrolled:
            self._bar().setValue(min(scrolled, self._bar().maximum()))
        elif self.currentItem() is not None:
            self.scrollToItem(self.currentItem())        # the picked shape is in sight

    def _retint(self) -> None:
        ratio = self.devicePixelRatioF()
        for index, shape in enumerate(self._shapes):
            item = self.item(index)
            if item is not None:
                item.setIcon(qt.QtGui.QIcon(thumbnail(shape.curves, THUMB, self._thumb, ratio)))

    def current_name(self) -> str:
        item = self.currentItem()
        return item.data(qt.QtCore.Qt.ItemDataRole.UserRole) if item is not None else ""


class _LibraryMixin:

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
        self._grid.set_single_row(not self._whole())
        self._grid.setFixedHeight(height)
        self._no_favorites.setFixedHeight(height)
        self._view.setFixedHeight(height + 6 + 22 + 6 + 24)      # the grid + Create + the line under it
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
        if self._settings.get("library", "favorites") != which:
            self._settings["library"] = which
        self._fit_library()
        self._show_heading()
        self._refresh_grid()         # (the window follows the card's height by itself)

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

    def _show_saved_shape(self) -> None:
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

    def _library_shape(self) -> "shape_data.Shape":
        return self.library.get(self._settings.get("shape", "circle")) or shape_data.BUILT_IN["circle"]

    def _copy_shape_code(self, name: str, for_maya: bool = True) -> None:
        shape = self.library.get(name)
        if shape is None:
            return
        if name == self._settings.get("shape") and self._edited is not None and not self._taken:
            shape = self._edited              # as it is in the editor now
        if for_maya:
            # facing the axis picked now, as Create would make it
            turned = shape_data.Shape(shape.name, shape_data.oriented(shape.curves, self._view.axis()), shape.category)
            qt.QtWidgets.QApplication.clipboard().setText(shape_data.as_maya_code(turned))
            self._say(f"“{shape.title()}” is on the clipboard as a script — paste it into the Script Editor "
                      "(Python) and run it", "done")
        else:
            qt.QtWidgets.QApplication.clipboard().setText(shape_data.as_code(shape))
            self._say(f"“{shape.title()}” is on the clipboard as a line for shapes.py", "done")

    def _restore_shape(self, name: str) -> None:
        if self.library.restore(name):
            if name == self._settings.get("shape"):
                self._drop_edited()
                if self._editor.isVisible():
                    shape = self._library_shape()
                    self._editor.open(shape.curves, shape.title())
            self._refresh_grid()
            self._say(f"“{name}” is the built-in shape again", "done")

    def _picked_shape(self) -> "shape_data.Shape | None":
        """The shape a control is made of: the library's picked one — as changed in the editor, if it was."""
        return self._edited if self._edited is not None else self._library_shape()

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
            self._menu_item(menu, "code", "Copy as a Maya script", lambda: self._copy_shape_code(name, True),
                            "A Python script on the clipboard: paste it into the Script Editor, run it — the "
                            "curve is made. Plain maya.cmds, it needs nothing of MSL Tools")
            self._menu_item(menu, "code", "Copy as a library line", lambda: self._copy_shape_code(name, False),
                            "The shape as a line of shapes.py — how a fix or a new shape gets into the "
                            "built-in library for everyone")
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
        self._show_saved_shape()
        self._refresh_grid()
        self._say(f"{len(added)} shape{'s' if len(added) != 1 else ''} added to Mine", "done")

    def _save_shape(self, name: str, curves: list) -> None:
        saved = self.library.add(name, curves)
        self._pick_saved(saved)
        self._add_favorites([saved])
        self._show_saved_shape()
        self._refresh_grid()
        self._say(f"Saved the shape “{saved}” — it is among your favorites (and under Mine)", "done")
