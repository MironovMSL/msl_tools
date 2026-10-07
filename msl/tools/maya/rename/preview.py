# tools/maya/rename/preview.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup
from msl_tools.msl.ui.widgets.atoms.scrollbars.slim_scroll_bar import SlimScrollBar

_ROLE = qt.QtCore.Qt.ItemDataRole.UserRole


class PreviewList(qt.QtWidgets.QTreeWidget):
    """"Before -> after" for every object the rename would touch, BEFORE anything is renamed.

    The new name is colored by what it means (rename.qss): fine, unchanged (dimmed), a clash
    (Maya would number it), a name Maya refuses, an object that can't be renamed. The reason is
    the row's tooltip. A double click on a new name edits it: that ONE object is renamed to what
    is typed (renamed). A right click: put this object's name into the name field, select only
    it, copy it.

    As tall as its rows (MIN_ROWS..MAX_ROWS), then it scrolls — the window stays compact.

    Signals:
        renamed(str, str) — a uuid and the name typed for it.
        use_name(str) — "Use in the name field" for that name.
        select_requested(str) — select only the object of that uuid.
    """

    renamed = qt.QtCore.Signal(str, str)
    use_name = qt.QtCore.Signal(str)
    select_requested = qt.QtCore.Signal(str)

    MIN_ROWS, MAX_ROWS = 3, 8
    MAX_SHOWN = 400  # more rows than this aren't listed (counted only)

    newColor = color_property("_new_color", "_recolor")
    sameColor = color_property("_same_color", "_recolor")
    oldColor = color_property("_old_color", "_recolor")
    clashColor = color_property("_clash_color", "_recolor")
    errorColor = color_property("_error_color", "_recolor")
    lockedColor = color_property("_locked_color", "_recolor")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()
        self._new_color = qt.QtGui.QColor(fallback.text_primary)
        self._same_color = self._old_color = self._locked_color = qt.QtGui.QColor(fallback.text_secondary)
        self._clash_color = qt.QtGui.QColor(fallback.warning)
        self._error_color = qt.QtGui.QColor(fallback.error)
        self._editing = False
        self.setObjectName("renamePreview")
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setIndentation(0)
        self.setSelectionMode(qt.QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(qt.QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical, self))
        self.setHorizontalScrollBarPolicy(qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(0, qt.QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, qt.QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.itemChanged.connect(self._on_item_changed)
        self._changes = []
        self._fit_height(0)

    # ------------------------------------------------------------------ filling

    def set_changes(self, changes: list) -> None:
        """Shows `changes` (rules.Change) — unless a name is being typed in the list right now."""
        if self._editing:
            return
        self._changes = list(changes)
        self.blockSignals(True)
        self.clear()
        for change in changes[:self.MAX_SHOWN]:
            item = qt.QtWidgets.QTreeWidgetItem([change.node.namespace + change.node.name, self._new_text(change)])
            item.setData(0, _ROLE, change.node.uuid)
            item.setData(1, _ROLE, change.state)
            tip = change.node.path
            if change.note:
                tip += "\n" + change.note
            item.setToolTip(0, tip)
            item.setToolTip(1, (change.note or "Double click to type a name for this one"))
            item.setFlags(item.flags() | qt.QtCore.Qt.ItemFlag.ItemIsEditable)
            self.addTopLevelItem(item)
        self.blockSignals(False)
        self._recolor()
        self._fit_height(min(len(changes), self.MAX_SHOWN))

    @staticmethod
    def _new_text(change) -> str:
        if change.state == "locked":
            return f"— {change.note}"
        if change.state == "same":
            return "unchanged"
        if change.state == "idle":
            return ""
        return change.new

    def _recolor(self) -> None:
        colors = {"": self._new_color, "warning": self._new_color, "same": self._same_color,
                  "clash": self._clash_color, "error": self._error_color, "locked": self._locked_color}
        self.blockSignals(True)
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            item.setForeground(0, self._old_color)
            item.setForeground(1, colors.get(item.data(1, _ROLE) or "", self._new_color))
            font = item.font(1)
            font.setItalic(item.data(1, _ROLE) in ("same", "locked"))
            item.setFont(1, font)
        self.blockSignals(False)

    def _fit_height(self, rows: int) -> None:
        row = self.sizeHintForRow(0) if self.topLevelItemCount() else self.fontMetrics().height() + 6
        shown = max(self.MIN_ROWS, min(self.MAX_ROWS, rows))
        self.setFixedHeight(row * shown + 2 * self.frameWidth() + 4)

    # ------------------------------------------------------------------ editing one name

    def _on_double_click(self, item, column) -> None:
        if item.data(1, _ROLE) == "locked":
            return
        self._editing = True
        self.blockSignals(True)
        change = self._change_of(item)
        item.setText(1, change.node.name if change is not None and change.state in ("same", "idle") else item.text(1))
        self.blockSignals(False)
        self.editItem(item, 1)

    def _on_item_changed(self, item, column) -> None:
        if column != 1 or not self._editing:
            return
        self._editing = False
        text = item.text(1).strip()
        change = self._change_of(item)
        if change is not None and text and text != change.node.name:
            self.renamed.emit(change.node.uuid, text)
        else:
            self.set_changes(self._changes)

    def closeEditor(self, editor, hint) -> None:
        super().closeEditor(editor, hint)
        if self._editing:  # Esc, or nothing changed
            self._editing = False
            qt.QtCore.QTimer.singleShot(0, lambda: self.set_changes(self._changes))

    def _change_of(self, item):
        uuid = item.data(0, _ROLE)
        return next((change for change in self._changes if change.node.uuid == uuid), None)

    # ------------------------------------------------------------------ menu

    def _on_menu(self, position) -> None:
        item = self.itemAt(position)
        change = self._change_of(item) if item is not None else None
        if change is None:
            return
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        name = change.node.name
        menu.addAction(f"Use “{name}” in the name field", lambda: self.use_name.emit(name))
        menu.addAction("Select only this one", lambda: self.select_requested.emit(change.node.uuid))
        menu.addAction("Copy the name", lambda: qt.QtWidgets.QApplication.clipboard().setText(name))
        if change.state not in ("same", "locked"):
            menu.addAction("Copy the new name", lambda: qt.QtWidgets.QApplication.clipboard().setText(change.new))
        menu.exec(self.viewport().mapToGlobal(position))
