# tools/maya/rename/preview.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
from msl_tools.msl.tools.maya.rename.buttons import maya_type_icon
from msl_tools.msl.tools.maya.rename.rules import name_parts
from msl_tools.msl.ui.icon_manager import tint_icon
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.scrollbars.slim_scroll_bar import SlimScrollBar

_ROLE = qt.QtCore.Qt.ItemDataRole.UserRole
_LOCKED = qt.QtCore.Qt.ItemDataRole.UserRole + 1
_PARTS = qt.QtCore.Qt.ItemDataRole.UserRole + 2     # the new name as [(text, changed)]
_DEPTH = qt.QtCore.Qt.ItemDataRole.UserRole + 3     # how deep under other listed rows (the tree)
_KIDS = qt.QtCore.Qt.ItemDataRole.UserRole + 4      # it has listed rows under it
_PARENT = qt.QtCore.Qt.ItemDataRole.UserRole + 5    # the uuid of the listed row it is under
_NS = qt.QtCore.Qt.ItemDataRole.UserRole + 6        # its namespace ("ns:"), drawn faint before the name
INDENT = 12        # px per level of the tree
ARROW = 12         # px of the fold arrow in front of a row (in the tree)
DOT, DOT_GAP = 6, 9    # the problem dots after a name
# what a problem dot means, in the order they are drawn (the colors: qproperty, rename.qss)
DOT_KINDS = ("same", "bad", "convention", "shape")
_ROW_MIME = "application/x-msl-rename-row"
FRAME_DELAY_MS = 250   # a click on a row frames its object this much later (unless a double click came)
_CHANGING = ("", "warning", "clash")                # states whose new name is drawn with its changes


class _NewNameDelegate(qt.QtWidgets.QStyledItemDelegate):
    """Draws a new name with what CHANGES in it in the accent (bold), the rest as the row's color."""

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner

    def paint(self, painter, option, index) -> None:
        parts = index.data(_PARTS)
        if not parts:
            return super().paint(painter, option, index)
        view = qt.QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(view, index)
        view.text = ""
        widget = view.widget
        style = widget.style() if widget is not None else qt.QtWidgets.QApplication.style()
        style.drawControl(qt.QtWidgets.QStyle.ControlElement.CE_ItemViewItem, view, painter, widget)
        rect = style.subElementRect(qt.QtWidgets.QStyle.SubElement.SE_ItemViewItemText, view, widget)
        base = index.data(qt.QtCore.Qt.ItemDataRole.ForegroundRole)
        base = base.color() if isinstance(base, qt.QtGui.QBrush) else qt.QtGui.QColor(self._owner._new_color)
        painter.save()
        painter.setClipRect(rect)
        x = rect.left() + 2
        for text, changed in parts:
            font = qt.QtGui.QFont(view.font)
            font.setBold(changed)
            painter.setFont(font)
            painter.setPen(self._owner._changed_color if changed else base)
            width = qt.QtGui.QFontMetrics(font).horizontalAdvance(text)
            painter.drawText(qt.QtCore.QRect(x, rect.top(), width + 2, rect.height()),
                             int(qt.QtCore.Qt.AlignmentFlag.AlignVCenter | qt.QtCore.Qt.AlignmentFlag.AlignLeft), text)
            x += width
        painter.restore()


class _NameDelegate(qt.QtWidgets.QStyledItemDelegate):
    """The first column: the tree's indent and fold arrow, the tick, Maya's icon of the kind with
    a dot of the side it stands on, the namespace faint before the name, and the problem dots
    after it (their places are kept for clicks: PreviewList._dot_hits)."""

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner

    def _shifted(self, option, index):
        shifted = qt.QtWidgets.QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(self._owner.indent_of(index), 0, 0, 0)
        return shifted

    def editorEvent(self, event, model, option, index) -> bool:
        return super().editorEvent(event, model, self._shifted(option, index), index)

    def paint(self, painter, option, index) -> None:
        owner = self._owner
        view = qt.QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(view, index)
        text = view.text
        view.text = ""
        widget = view.widget
        style = widget.style() if widget is not None else qt.QtWidgets.QApplication.style()
        shifted = self._shifted(view, index)
        indent = shifted.rect.left() - view.rect.left()
        if indent > 0:   # the row's ground under the indent (the rest comes with the item itself)
            painter.save()
            painter.setClipRect(qt.QtCore.QRect(view.rect.left(), view.rect.top(), indent, view.rect.height()))
            style.drawPrimitive(qt.QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem, view, painter, widget)
            painter.restore()
        style.drawControl(qt.QtWidgets.QStyle.ControlElement.CE_ItemViewItem, shifted, painter, widget)
        uuid = index.data(_ROLE) or ""
        painter.save()
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        # the fold arrow
        if owner.tree_shown() and index.data(_KIDS):
            x = option.rect.left() + (index.data(_DEPTH) or 0) * INDENT + 3
            y = option.rect.center().y()
            pen = qt.QtGui.QPen(owner._old_color, 1.6)
            pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            if uuid in owner._folded:
                points = [qt.QtCore.QPointF(x + 1.5, y - 3.5), qt.QtCore.QPointF(x + 5, y), qt.QtCore.QPointF(x + 1.5, y + 3.5)]
            else:
                points = [qt.QtCore.QPointF(x - 0.5, y - 1.5), qt.QtCore.QPointF(x + 3, y + 2), qt.QtCore.QPointF(x + 6.5, y - 1.5)]
            painter.drawPolyline(qt.QtGui.QPolygonF(points))
        # the side it stands on: a dot on the icon's corner
        side = owner._row_sides.get(uuid)
        if side:
            icon_rect = style.subElementRect(qt.QtWidgets.QStyle.SubElement.SE_ItemViewItemDecoration, shifted, widget)
            color = {"left": owner._left_color, "right": owner._right_color}.get(side, owner._mid_color)
            painter.setPen(qt.QtGui.QPen(owner._ground_color, 1.2))
            painter.setBrush(color)
            painter.drawEllipse(qt.QtCore.QPointF(icon_rect.right() - 0.5, icon_rect.bottom() - 0.5), 3, 3)
        # the namespace (faint), the name, then the dots
        rect = style.subElementRect(qt.QtWidgets.QStyle.SubElement.SE_ItemViewItemText, shifted, widget)
        namespace = index.data(_NS) or ""
        name = text[len(namespace):] if namespace and text.startswith(namespace) else text
        issues = owner._row_issues.get(uuid, [])
        room = rect.width() - 4 - (len(issues) * DOT_GAP + 6 if issues else 0)
        metrics = qt.QtGui.QFontMetrics(view.font)
        painter.setFont(view.font)
        x = rect.left() + 2
        if namespace:
            faint = qt.QtGui.QColor(owner._old_color)
            faint.setAlpha(120)
            painter.setPen(faint)
            shown = metrics.elidedText(namespace, qt.QtCore.Qt.TextElideMode.ElideMiddle, max(0, room // 2))
            painter.drawText(qt.QtCore.QRect(x, rect.top(), metrics.horizontalAdvance(shown) + 2, rect.height()),
                             int(qt.QtCore.Qt.AlignmentFlag.AlignVCenter | qt.QtCore.Qt.AlignmentFlag.AlignLeft), shown)
            x += metrics.horizontalAdvance(shown)
            room -= metrics.horizontalAdvance(shown)
        base = index.data(qt.QtCore.Qt.ItemDataRole.ForegroundRole)
        painter.setPen(base.color() if isinstance(base, qt.QtGui.QBrush) else owner._old_color)
        shown = metrics.elidedText(name, qt.QtCore.Qt.TextElideMode.ElideRight, max(0, room))
        width = metrics.horizontalAdvance(shown)
        painter.drawText(qt.QtCore.QRect(x, rect.top(), width + 2, rect.height()),
                         int(qt.QtCore.Qt.AlignmentFlag.AlignVCenter | qt.QtCore.Qt.AlignmentFlag.AlignLeft), shown)
        hits = []
        x += width + 7
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        for kind, _why in issues:
            painter.setBrush(owner.dot_color(kind))
            center = qt.QtCore.QPointF(x + DOT / 2, rect.center().y() + 0.5)
            painter.drawEllipse(center, DOT / 2, DOT / 2)
            hits.append((qt.QtCore.QRect(int(x) - 2, rect.top(), DOT_GAP + 1, rect.height()), kind))
            x += DOT_GAP
        owner._dot_hits[uuid] = hits
        painter.restore()


class _RowActions(qt.QtWidgets.QFrame):
    """The small buttons that appear at the end of the hovered row's name: copy it, put it into
    the name field, show the object in the scene. A pill of the list's own ground, so it covers
    the end of a long name (rename.qss: QFrame#renameRowActions)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("renameRowActions")
        icons = UiResources().iconManager
        line = qt.QtWidgets.QHBoxLayout(self)
        line.setContentsMargins(2, 0, 2, 0)
        line.setSpacing(0)
        self.buttons = {}
        for key, icon, tip in (("edit", "edit", "Type a name for this one (F2 / double click)"),
                               ("mirror", "mirror_sides", "Rename this one to the other side's name (lf_ ↔ rt_)"),
                               ("branch", "branch", "Select it and everything under it"),
                               ("copy", "copy", "Copy the name"),
                               ("field", "text_frame", "Put the name into the name field")):
            button = GlyphButton("", tip, size=qt.QtCore.QSize(20, 18))
            button.setObjectName("renameRowAction")
            button.set_icon(icons.get_icon(icon, sub_folder="actions"))
            line.addWidget(button)
            self.buttons[key] = button
        self.hide()


class PreviewList(qt.QtWidgets.QTreeWidget):
    """"Before -> after" for every object the rename would touch, BEFORE anything is renamed.

    A row: a tick (unticked = left out of renames), Maya's icon of its kind, the name it has, the
    name it will get — what CHANGES in it in the accent —, a warning / error mark for a clash or a
    name Maya refuses (the reason in the tooltip), and the lock at the right edge (a click locks
    or unlocks). Under the pointer a row shows three buttons at the end of its name: copy it, into
    the name field, show it in the scene. A row can be DRAGGED to another place: the numbers and
    letters follow the list's order then. A double click on a new name renames that one object.

    As tall as its rows (MIN_ROWS..MAX_ROWS) unless the user dragged its height; the scroll bar's
    column is always kept, so nothing jumps sideways when the list starts to scroll.

    Signals:
        renamed(str, str) — a uuid and the name typed for it.
        use_name(str) — put that name into the name field.
        select_requested(str) — select only the object of that uuid.
        show_requested(str) — select it and frame it in the viewport.
        lock_requested(str, bool) — lock (True) / unlock that object.
        included_changed(str, bool) — a row's tick.
        include_all() — every row ticked again.
        order_changed(list) — the uuids in the order the user dragged them into.
        order_reset() — back to the order they came in.
    """

    renamed = qt.QtCore.Signal(str, str)
    use_name = qt.QtCore.Signal(str)
    select_requested = qt.QtCore.Signal(str)
    show_requested = qt.QtCore.Signal(str)
    rows_picked = qt.QtCore.Signal(list)
    frame_requested = qt.QtCore.Signal(str)
    lock_requested = qt.QtCore.Signal(str, bool)
    included_changed = qt.QtCore.Signal(str, bool)
    include_all = qt.QtCore.Signal()
    order_changed = qt.QtCore.Signal(list)
    order_reset = qt.QtCore.Signal()
    mirror_requested = qt.QtCore.Signal(str)        # rename that one to the other side's name
    branch_requested = qt.QtCore.Signal(str)        # select it and everything under it
    fix_requested = qt.QtCore.Signal(str, qt.QtCore.QPoint)   # a problem dot clicked: the row's fixes
    paste_requested = qt.QtCore.Signal()            # names from the clipboard, one per row
    paste_hovered = qt.QtCore.Signal(bool)          # ...the menu item is under the pointer

    LOCK_COLUMN = 2
    MIN_ROWS, MAX_ROWS = 3, 8
    MAX_SHOWN = 400  # more rows than this aren't listed (counted only)

    newColor = color_property("_new_color", "_recolor")
    sameColor = color_property("_same_color", "_recolor")
    oldColor = color_property("_old_color", "_recolor")
    clashColor = color_property("_clash_color", "_recolor")
    errorColor = color_property("_error_color", "_recolor")
    lockedColor = color_property("_locked_color", "_recolor")
    changedColor = color_property("_changed_color", "_repaint")   # what changes in a new name
    dropColor = color_property("_drop_color", "_repaint")         # where a dragged row lands
    leftColor = color_property("_left_color", "_repaint")         # the side dot: Maya's left (blue)
    rightColor = color_property("_right_color", "_repaint")       # ...right (red)
    midColor = color_property("_mid_color", "_repaint")           # ...the middle (yellow)
    groundColor = color_property("_ground_color", "_repaint")     # the ring around a side dot
    sameDotColor = color_property("_same_dot", "_repaint")        # problem dots, as the strip's buttons
    badDotColor = color_property("_bad_dot", "_repaint")
    conventionDotColor = color_property("_convention_dot", "_repaint")
    shapeDotColor = color_property("_shape_dot", "_repaint")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()
        self._new_color = qt.QtGui.QColor(fallback.text_primary)
        self._same_color = self._old_color = self._locked_color = qt.QtGui.QColor(fallback.text_secondary)
        self._clash_color = qt.QtGui.QColor(fallback.warning)
        self._error_color = qt.QtGui.QColor(fallback.error)
        self._changed_color = self._drop_color = qt.QtGui.QColor(fallback.accent)
        self._left_color = self._convention_dot = qt.QtGui.QColor(fallback.accent)
        self._right_color = self._bad_dot = qt.QtGui.QColor(fallback.error)
        self._same_dot = self._mid_color = qt.QtGui.QColor(fallback.warning)
        self._shape_dot = qt.QtGui.QColor(fallback.text_secondary)
        self._ground_color = qt.QtGui.QColor(fallback.surface)
        self._tree = False             # rows drawn as a tree (indent + fold arrows)
        self._folded: set = set()      # uuids whose rows under them are hidden
        self._row_sides: dict = {}     # uuid -> "left" / "right"
        self._row_issues: dict = {}    # uuid -> [(kind, why)]
        self._dot_hits: dict = {}      # uuid -> [(rect, kind)] where its dots were drawn
        self._editing = False
        self._ordered = False          # the user dragged the rows into an order of their own
        icons = UiResources().iconManager
        self._lock_shape = icons.get_icon("lock", sub_folder="actions")
        self._warning_shape = icons.get_icon("warning", sub_folder="actions")
        self._error_shape = icons.get_icon("error", sub_folder="actions")
        self.setObjectName("renamePreview")
        self.setIconSize(qt.QtCore.QSize(14, 14))
        self.setColumnCount(3)  # [x] icon  old name · new name · lock
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setIndentation(0)
        self.setSelectionMode(qt.QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(qt.QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.ClickFocus)  # the keys: up / down, F2, space
        self.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical, self))
        self.setHorizontalScrollBarPolicy(qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # the bar's column is always there (SlimScrollBar draws nothing while nothing scrolls), so the
        # columns don't jump sideways when the list starts to scroll
        self.setVerticalScrollBarPolicy(qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.header().setStretchLastSection(False)  # the lock column keeps its 24 px at the right
        self.header().setSectionResizeMode(0, qt.QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, qt.QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(self.LOCK_COLUMN, qt.QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.header().resizeSection(self.LOCK_COLUMN, 24)
        self.setItemDelegateForColumn(0, _NameDelegate(self))
        self.setItemDelegateForColumn(1, _NewNameDelegate(self))
        self.itemClicked.connect(self._on_clicked)
        self.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.itemChanged.connect(self._on_item_changed)
        # hover buttons and dragging rows
        self._actions = _RowActions(self.viewport())
        self._hover_uuid = ""
        self._actions.buttons["copy"].clicked.connect(self._on_copy)
        self._actions.buttons["field"].clicked.connect(lambda: self._emit_for_hover(self.use_name, name=True))
        self._actions.buttons["mirror"].clicked.connect(lambda: self._emit_for_hover(self.mirror_requested))
        self._actions.buttons["branch"].clicked.connect(lambda: self._emit_for_hover(self.branch_requested))
        self._actions.buttons["edit"].clicked.connect(self._edit_hovered)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self._press = None
        self._drop_y = None
        # a click selects the row's object at once and frames it a moment later — unless it was the
        # first half of a double click (that edits the new name)
        self._frame_timer = qt.QtCore.QTimer(self)
        self._frame_timer.setSingleShot(True)
        # shorter than the system's double-click time (~0.5 s) on purpose — the user's call: the camera
        # follows a click sooner; a slow double click frames as well, and still edits
        self._frame_timer.setInterval(min(FRAME_DELAY_MS, qt.QtWidgets.QApplication.doubleClickInterval()))
        self._frame_timer.timeout.connect(self._emit_frame)
        self._frame_uuid = ""
        self._tick_clicked = False
        self._after_double = False
        self._changes = []
        self._user_height = None
        self._fit_height(0)

    # ------------------------------------------------------------------ filling

    def set_changes(self, changes: list, ordered: bool = False, tree: bool = False) -> None:
        """Shows `changes` (rules.Change) — unless a name is being typed in the list right now.
        `ordered`: the rows are in an order the user dragged them into (the menu offers it back).

        The same rows as before (the same objects in the same order) are UPDATED IN PLACE, never
        rebuilt: a click picks a row and the others turn "not picked", and rebuilding the items
        between the two clicks of a double click lost it — Qt compares the second press with the
        first one's index, which clear() invalidates (met with the real mouse)."""
        if self._editing:
            return
        signature = (ordered, tree, tuple((change.node.uuid, change.node.path, change.node.namespace, change.node.name,
                                           change.node.kind, change.node.locked, change.new, change.state, change.note)
                                          for change in changes))
        self._changes = list(changes)
        self._ordered = ordered
        self._tree = bool(tree)
        self._shape_tree(changes)
        if signature == getattr(self, "_signature", None) and self.topLevelItemCount():
            return
        self._signature = signature
        shown = changes[:self.MAX_SHOWN]
        current = [self.topLevelItem(index).data(0, _ROLE) for index in range(self.topLevelItemCount())]
        self.blockSignals(True)
        if current == [change.node.uuid for change in shown]:
            for index, change in enumerate(shown):
                self._fill(self.topLevelItem(index), change)
        else:
            self.clear()
            for change in shown:
                item = qt.QtWidgets.QTreeWidgetItem(["", "", ""])
                self._fill(item, change)
                self.addTopLevelItem(item)
        self.blockSignals(False)
        self._recolor()
        self._apply_picked()
        self._apply_fold()
        self._place_actions(self._hover_uuid)

    def _shape_tree(self, changes) -> None:
        """Depth, parent and "has rows under it" of each row, from the long names: a row is under
        the nearest listed row its path starts with (the list in the Outliner's order)."""
        self._depth, self._parent, self._kids = {}, {}, set()
        by_path = {}
        for change in changes:
            path = change.node.path
            parent, cut = "", path
            while "|" in cut and self._tree:
                cut = cut.rpartition("|")[0]
                if cut in by_path:
                    parent = by_path[cut]
                    break
            self._parent[change.node.uuid] = parent
            self._depth[change.node.uuid] = self._depth.get(parent, -1) + 1 if parent else 0
            if parent:
                self._kids.add(parent)
            by_path[path] = change.node.uuid

    def tree_shown(self) -> bool:
        return self._tree and bool(getattr(self, "_kids", None))

    def indent_of(self, index) -> int:
        """How far the first column's content moves right (the tree's depth + the arrow's room)."""
        if not self.tree_shown():
            return 0
        return (index.data(_DEPTH) or 0) * INDENT + ARROW

    def dot_color(self, kind: str) -> "qt.QtGui.QColor":
        return {"same": self._same_dot, "bad": self._bad_dot, "convention": self._convention_dot,
                "shape": self._shape_dot}.get(kind, self._shape_dot)

    def set_marks(self, sides: dict, issues: dict) -> None:
        """The side each object stands on ({uuid: "left" / "right" / "center"}) and its problems
        ({uuid: [(kind, why)]}, kinds DOT_KINDS): a dot on the icon, dots after the name."""
        if sides == self._row_sides and issues == self._row_issues:
            return
        self._row_sides, self._row_issues = dict(sides), dict(issues)
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            self._tip(item, self._change_of(item))
        self.viewport().update()

    def _apply_fold(self) -> None:
        """Rows under a folded row are hidden (they are still renamed: folding only hides)."""
        hidden: dict = {}
        shown = 0
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            uuid = item.data(0, _ROLE)
            parent = self._parent.get(uuid, "") if self._tree else ""
            hide = bool(parent) and (parent in self._folded or hidden.get(parent, False))
            hidden[uuid] = hide
            if item.isHidden() != hide:
                item.setHidden(hide)
            shown += not hide
        self._fit_height(min(shown, self.MAX_SHOWN))

    def _toggle_fold(self, uuid: str) -> None:
        if uuid in self._folded:
            self._folded.discard(uuid)
        else:
            self._folded.add(uuid)
        self._apply_fold()
        self.viewport().update()

    def _tip(self, item, change) -> None:
        if change is None:
            return
        tip = change.node.path
        if change.note:
            tip += "\n" + change.note
        side = self._row_sides.get(change.node.uuid)
        if side:
            tip += ("\nStands in the middle (the dot on its icon)" if side == "center" else
                    f"\nStands on the {side} (the dot on its icon)")
        for kind, why in self._row_issues.get(change.node.uuid, []):
            tip += f"\n● {why}"
        if self._row_issues.get(change.node.uuid):
            tip += "\nA click on a dot: put it right"
        item.setToolTip(0, tip + "\nClick: pick it (select + frame) · Ctrl / Shift+click: several · drag: the order "
                                "of the numbers\nKeys: ↑ ↓ pick · F2 type a name · space tick · ← → fold")

    def _fill(self, item, change) -> None:
        item.setText(0, change.node.namespace + change.node.name)
        item.setData(0, _NS, change.node.namespace)
        item.setData(0, _DEPTH, self._depth.get(change.node.uuid, 0))
        item.setData(0, _KIDS, change.node.uuid in self._kids)
        item.setText(1, self._new_text(change))
        item.setData(0, _ROLE, change.node.uuid)
        item.setIcon(0, maya_type_icon(change.node.kind))  # what it is, as in the Outliner
        item.setData(1, _ROLE, change.state)
        item.setData(1, _LOCKED, bool(change.node.locked))
        item.setData(1, _PARTS, name_parts(change.node.name, change.new)
                     if change.state in _CHANGING and change.new != change.node.name else None)
        self._tip(item, change)
        item.setToolTip(1, (change.note or "Double click to type a name for this one"))
        item.setFlags(item.flags() | qt.QtCore.Qt.ItemFlag.ItemIsEditable | qt.QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, qt.QtCore.Qt.CheckState.Unchecked if change.state == "skipped" and change.note == "left out"
                           else qt.QtCore.Qt.CheckState.Checked)
        item.setToolTip(self.LOCK_COLUMN, "Locked — it can't be renamed, deleted or re-parented. Click to unlock"
                        if change.node.locked == "locked node" else
                        ("From a reference: its file decides" if change.node.locked else "Click to lock it"))

    # ------------------------------------------------------------------ picking rows

    def set_picked(self, uuids) -> None:
        """The rows picked (by the owner, the one who decides): highlighted in the list."""
        self._picked = [uuid for uuid in uuids]
        self._apply_picked()

    def _apply_picked(self) -> None:
        picked = set(getattr(self, "_picked", []))
        self.blockSignals(True)
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            selected = item.data(0, _ROLE) in picked
            if item.isSelected() != selected:
                item.setSelected(selected)
        self.blockSignals(False)

    def _pick(self, uuid: str) -> None:
        """A click on a row: plain = only it, Ctrl = add / take away, Shift = the rows from the one
        clicked last to this one (as in the Outliner)."""
        modifiers = qt.QtWidgets.QApplication.keyboardModifiers()
        picked = list(getattr(self, "_picked", []))
        rows = [change.node.uuid for change in self._changes]
        anchor = getattr(self, "_anchor", "")
        if modifiers & qt.QtCore.Qt.KeyboardModifier.ShiftModifier and anchor in rows and uuid in rows:
            first, last = sorted((rows.index(anchor), rows.index(uuid)))
            span = rows[first:last + 1]
            picked = (picked + [each for each in span if each not in picked]
                      if modifiers & qt.QtCore.Qt.KeyboardModifier.ControlModifier else span)
        elif modifiers & qt.QtCore.Qt.KeyboardModifier.ControlModifier:
            picked = [each for each in picked if each != uuid] if uuid in picked else picked + [uuid]
            self._anchor = uuid
        else:
            picked = [uuid]
            self._anchor = uuid
        self.set_picked(picked)
        self._pending_pick = picked
        qt.QtCore.QTimer.singleShot(0, self._emit_picked)  # (the owner re-plans: not inside the click)

    def _emit_picked(self) -> None:
        picked, self._pending_pick = getattr(self, "_pending_pick", None), None
        if picked is not None:
            self.rows_picked.emit(picked)

    @staticmethod
    def _new_text(change) -> str:
        if change.state == "locked":
            return change.note  # beside the lock
        if change.state == "same":
            return "unchanged"
        if change.state == "idle":
            return ""
        if change.state == "skipped":
            return change.note or "left out"   # "left out" (unticked) / "not picked"
        if change.state == "nonconform":
            return f"✗ {change.note}"
        return change.new

    def _tinted(self, shape, color) -> "qt.QtGui.QIcon":
        if shape is None or shape.isNull():
            return qt.QtGui.QIcon()
        return qt.QtGui.QIcon(tint_icon(shape, 14, self.devicePixelRatioF(), color))

    def _recolor(self) -> None:
        colors = {"": self._new_color, "warning": self._new_color, "same": self._same_color,
                  "clash": self._clash_color, "error": self._error_color, "locked": self._locked_color,
                  "nonconform": self._clash_color, "skipped": self._same_color}
        faint = qt.QtGui.QColor(self._locked_color)
        faint.setAlpha(55)
        lock, unlocked = self._tinted(self._lock_shape, self._new_color), self._tinted(self._lock_shape, faint)
        marks = {"clash": self._tinted(self._warning_shape, self._clash_color),
                 "error": self._tinted(self._error_shape, self._error_color)}
        self.blockSignals(True)
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            state = item.data(1, _ROLE) or ""
            item.setIcon(self.LOCK_COLUMN, lock if item.data(1, _LOCKED) else unlocked)  # a click toggles it
            item.setIcon(1, marks.get(state, qt.QtGui.QIcon()))  # a clash / a refused name: a mark
            item.setForeground(0, self._old_color)
            item.setForeground(1, colors.get(state, self._new_color))
            font = item.font(1)
            font.setItalic(state in ("same", "locked", "skipped"))
            item.setFont(1, font)
        self.blockSignals(False)

    def _repaint(self) -> None:
        self.viewport().update()

    def _row_height(self) -> int:
        return self.sizeHintForRow(0) if self.topLevelItemCount() else self.fontMetrics().height() + 6

    def _fit_height(self, rows: int) -> None:
        self._rows = rows
        least = max(self._row_height() * self.MIN_ROWS + 2 * self.frameWidth() + 4, getattr(self, "_floor", 0))
        if self._user_height:
            self.setFixedHeight(max(least, self._user_height))  # the height the user dragged it to
            return
        shown = max(self.MIN_ROWS, min(self.MAX_ROWS, rows))
        self.setFixedHeight(max(least, self._row_height() * shown + 2 * self.frameWidth() + 4))

    def set_floor(self, height: int) -> None:
        """The least height whatever the rows (the panel: as tall as the strip of buttons beside it)."""
        self._floor = int(height or 0)
        self._fit_height(getattr(self, "_rows", 0))

    def set_user_height(self, height: "int | None") -> None:
        """A height the user picked by dragging the grip under the list (None = as tall as its rows)."""
        self._user_height = int(height) if height else None
        self._fit_height(getattr(self, "_rows", 0))

    # ------------------------------------------------------------------ the hovered row's buttons

    def _item_of(self, uuid: str):
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item.data(0, _ROLE) == uuid:
                return item
        return None

    def _place_actions(self, uuid: str) -> None:
        item = self._item_of(uuid) if uuid and not self._editing and self._drop_y is None else None
        if item is None:
            self._actions.hide()
            return
        rect = self.visualItemRect(item)
        right = self.header().sectionPosition(1)   # the end of the name column
        self._actions.adjustSize()
        size = self._actions.sizeHint()
        self._actions.setGeometry(right - size.width() - 2, rect.top() + (rect.height() - size.height()) // 2,
                                  size.width(), size.height())
        self._actions.show()
        self._actions.raise_()

    def _hover(self, uuid: str) -> None:
        if uuid != self._hover_uuid:
            self._hover_uuid = uuid
            self._place_actions(uuid)

    def _hovered_change(self):
        return next((change for change in self._changes if change.node.uuid == self._hover_uuid), None)

    def _on_copy(self) -> None:
        change = self._hovered_change()
        if change is not None:
            qt.QtWidgets.QApplication.clipboard().setText(change.node.name)
            self._actions.buttons["copy"].flash_icon(UiResources().iconManager.get_icon("check", sub_folder="actions"))

    def _emit_for_hover(self, signal, name: bool = False) -> None:
        change = self._hovered_change()
        if change is not None:
            self._pending_hover = (signal, change.node.name if name else change.node.uuid)
            qt.QtCore.QTimer.singleShot(0, self._emit_hover)  # (it may rebuild the list: not inside the click)

    def _emit_hover(self) -> None:
        pending, self._pending_hover = getattr(self, "_pending_hover", None), None
        if pending is not None:
            pending[0].emit(pending[1])

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport():
            kind = event.type()
            if kind == qt.QtCore.QEvent.Type.MouseMove:
                point = event.position().toPoint()
                item = self.itemAt(point)
                self._hover(item.data(0, _ROLE) if item is not None else "")
                self._maybe_start_drag(event)
            elif kind == qt.QtCore.QEvent.Type.Leave:
                if not self._actions.geometry().contains(self.viewport().mapFromGlobal(qt.QtGui.QCursor.pos())):
                    self._hover("")
            elif kind in (qt.QtCore.QEvent.Type.MouseButtonPress, qt.QtCore.QEvent.Type.MouseButtonDblClick) \
                    and event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self._hit_extra(event):
                return True   # the fold arrow / a problem dot: not a pick
            elif kind == qt.QtCore.QEvent.Type.MouseButtonPress and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
                item = self.itemAt(event.position().toPoint())
                self._press = (event.position().toPoint(), item.data(0, _ROLE)) if item is not None else None
                if item is None and getattr(self, "_picked", []):
                    self.set_picked([])
                    self._pending_pick = []
                    qt.QtCore.QTimer.singleShot(0, self._emit_picked)
            elif kind == qt.QtCore.QEvent.Type.MouseButtonRelease:
                self._press = None
        return super().eventFilter(watched, event)

    def _hit_extra(self, event) -> bool:
        """A press on a row's fold arrow folds it; on a problem dot asks for its fixes."""
        point = event.position().toPoint()
        item = self.itemAt(point)
        if item is None or self.header().logicalIndexAt(point.x()) != 0:
            return False
        uuid = item.data(0, _ROLE)
        if self.tree_shown() and item.data(0, _KIDS):
            left = self.visualItemRect(item).left() + (item.data(0, _DEPTH) or 0) * INDENT
            if left - 2 <= point.x() <= left + ARROW:
                if event.type() == qt.QtCore.QEvent.Type.MouseButtonPress:
                    self._toggle_fold(uuid)
                return True
        for rect, kind in self._dot_hits.get(uuid, []):
            if rect.contains(point):
                if event.type() == qt.QtCore.QEvent.Type.MouseButtonPress:
                    self._pending_fix = (uuid, self.viewport().mapToGlobal(point))
                    qt.QtCore.QTimer.singleShot(0, self._emit_fix)
                return True
        return False

    def _emit_fix(self) -> None:
        pending, self._pending_fix = getattr(self, "_pending_fix", None), None
        if pending is not None:
            self.fix_requested.emit(*pending)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover("")

    # ------------------------------------------------------------------ the keys

    def _visible_uuids(self) -> list:
        return [self.topLevelItem(index).data(0, _ROLE) for index in range(self.topLevelItemCount())
                if not self.topLevelItem(index).isHidden()]

    def keyPressEvent(self, event) -> None:
        key = event.key()
        keys = qt.QtCore.Qt.Key
        rows = self._visible_uuids()
        current = getattr(self, "_anchor", "")
        if key in (keys.Key_Up, keys.Key_Down) and rows:
            if current in rows:
                at = rows.index(current) + (1 if key == keys.Key_Down else -1)
                at = max(0, min(len(rows) - 1, at))
            else:
                at = 0 if key == keys.Key_Down else len(rows) - 1
            uuid = rows[at]
            self._pick(uuid)
            item = self._item_of(uuid)
            if item is not None:
                self.scrollToItem(item)
            self._frame_uuid = uuid
            self._frame_timer.start()
            return
        if key in (keys.Key_Left, keys.Key_Right) and self.tree_shown() and current in self._kids:
            if (key == keys.Key_Left) != (current in self._folded):
                self._toggle_fold(current)
            return
        if key in (keys.Key_F2, keys.Key_Return, keys.Key_Enter) and current:
            item = self._item_of(current)
            if item is not None:
                self._edit(item)
            return
        if key == keys.Key_Space:
            picked = [uuid for uuid in getattr(self, "_picked", []) if uuid in rows] or ([current] if current else [])
            changes = [change for change in self._changes if change.node.uuid in picked]
            if changes:
                tick = any(change.state == "skipped" and change.note == "left out" for change in changes)
                self._pending_includes = [(change.node.uuid, tick) for change in changes]
                qt.QtCore.QTimer.singleShot(0, self._emit_includes)
            return
        if key == keys.Key_Escape and getattr(self, "_picked", []):
            self.set_picked([])
            self.rows_picked.emit([])
            return
        if event.matches(qt.QtGui.QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
            return
        super().keyPressEvent(event)

    def _emit_includes(self) -> None:
        pending, self._pending_includes = getattr(self, "_pending_includes", None), None
        for uuid, ticked in pending or []:
            self.included_changed.emit(uuid, ticked)

    # ------------------------------------------------------------------ dragging rows into an order

    def _maybe_start_drag(self, event) -> None:
        if self._press is None or not (event.buttons() & qt.QtCore.Qt.MouseButton.LeftButton):
            return
        start, uuid = self._press
        if (event.position().toPoint() - start).manhattanLength() < qt.QtWidgets.QApplication.startDragDistance() * 2:
            return
        self._press = None
        item = self._item_of(uuid)
        if item is None or self.header().logicalIndexAt(start.x()) != 0:
            return  # a row is dragged by its name (the new-name column edits, the lock clicks)
        self._actions.hide()
        drag = qt.QtGui.QDrag(self)
        data = qt.QtCore.QMimeData()
        data.setData(_ROW_MIME, uuid.encode("utf-8"))
        drag.setMimeData(data)
        rect = self.visualItemRect(item)
        drag.setPixmap(self.viewport().grab(qt.QtCore.QRect(0, rect.top(), self.header().sectionPosition(1), rect.height())))
        drag.exec(qt.QtCore.Qt.DropAction.MoveAction)
        self._drop_y = None
        self.viewport().update()

    def _drop_index(self, y: int) -> int:
        """Before which row a drop at `y` lands (the count = after the last)."""
        for index in range(self.topLevelItemCount()):
            rect = self.visualItemRect(self.topLevelItem(index))
            if y < rect.center().y():
                return index
        return self.topLevelItemCount()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_ROW_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_ROW_MIME):
            return super().dragMoveEvent(event)
        index = self._drop_index(event.position().toPoint().y())
        if index < self.topLevelItemCount():
            self._drop_y = self.visualItemRect(self.topLevelItem(index)).top()
        else:
            last = self.topLevelItem(self.topLevelItemCount() - 1)
            self._drop_y = self.visualItemRect(last).bottom() if last is not None else 0
        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drop_y = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_ROW_MIME):
            return super().dropEvent(event)
        uuid = bytes(event.mimeData().data(_ROW_MIME)).decode("utf-8")
        order = [change.node.uuid for change in self._changes]
        index = self._drop_index(event.position().toPoint().y())
        self._drop_y = None
        event.acceptProposedAction()
        if uuid not in order:
            return
        moved_from = order.index(uuid)
        order.remove(uuid)
        order.insert(index - 1 if index > moved_from else index, uuid)
        self._pending_order = order
        qt.QtCore.QTimer.singleShot(0, self._emit_order)  # (the list is rebuilt: not inside the drop)

    def _emit_order(self) -> None:
        order, self._pending_order = getattr(self, "_pending_order", None), None
        if order is not None:
            self.order_changed.emit(order)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_y is None:
            return
        painter = qt.QtGui.QPainter(self.viewport())
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        pen = qt.QtGui.QPen(self._drop_color, 2)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        y = max(1, self._drop_y)
        painter.drawLine(qt.QtCore.QPointF(4, y), qt.QtCore.QPointF(self.viewport().width() - 4, y))
        painter.end()

    # ------------------------------------------------------------------ editing one name

    def _edit_hovered(self) -> None:
        item = self._item_of(self._hover_uuid)
        if item is not None:
            self._edit(item)

    def _edit(self, item) -> None:
        """Types a name for one row (F2, Enter, the pencil): as a double click, minus its click."""
        self._on_double_click(item, 1)
        self._after_double = False

    def _on_double_click(self, item, column) -> None:
        self._frame_timer.stop()     # it was a double click: edit, don't frame
        self._after_double = True    # (its release emits one more click)
        if item.data(1, _ROLE) == "locked":
            return
        self._editing = True
        self._actions.hide()
        self.blockSignals(True)
        change = self._change_of(item)
        item.setData(1, _PARTS, None)  # the editor shows plain text
        item.setText(1, change.node.name if change is not None and change.state in ("same", "idle", "skipped",
                                                                                     "nonconform") else item.text(1))
        self.blockSignals(False)
        self.editItem(item, 1)

    def _emit_included(self) -> None:
        pending, self._pending_include = getattr(self, "_pending_include", None), None
        if pending is not None:
            self.included_changed.emit(*pending)

    def _on_clicked(self, item, column) -> None:
        if column != self.LOCK_COLUMN:
            ticked, self._tick_clicked = self._tick_clicked, False
            after_double, self._after_double = self._after_double, False
            if ticked or after_double:
                return  # the click was on the tick / the end of a double click
            uuid = item.data(0, _ROLE)
            if uuid:
                self._pick(uuid)
                self._frame_uuid = uuid
                self._frame_timer.start()
            return
        change = self._change_of(item)
        if change is None or (change.node.locked and change.node.locked != "locked node"):
            return  # referenced / read-only: not ours to lock or unlock
        self._pending_lock = (change.node.uuid, not bool(change.node.locked))
        qt.QtCore.QTimer.singleShot(0, self._emit_lock)  # (the list is rebuilt: not inside the click)

    def _emit_frame(self) -> None:
        if self._frame_uuid and not self._editing:
            self.frame_requested.emit(self._frame_uuid)
        self._frame_uuid = ""

    def _emit_lock(self) -> None:
        pending, self._pending_lock = getattr(self, "_pending_lock", None), None
        if pending is not None:
            self.lock_requested.emit(*pending)

    def _on_item_changed(self, item, column) -> None:
        if column == 0:
            self._tick_clicked = True   # the click that follows is the tick's, not a "select it"
            change = self._change_of(item)
            if change is not None:
                # told on the NEXT turn of the event loop: the owner rebuilds the list, and deleting
                # the item while Qt is still inside its setData took Maya down
                self._pending_include = (change.node.uuid, item.checkState(0) == qt.QtCore.Qt.CheckState.Checked)
                qt.QtCore.QTimer.singleShot(0, self._emit_included)
            return
        if column != 1 or not self._editing:
            return
        self._editing = False
        text = item.text(1).strip()
        change = self._change_of(item)
        if change is not None and text and text != change.node.name:
            self._pending_rename = (change.node.uuid, text)
            qt.QtCore.QTimer.singleShot(0, self._emit_renamed)
        else:
            qt.QtCore.QTimer.singleShot(0, self._show_again)

    def _emit_renamed(self) -> None:
        pending, self._pending_rename = getattr(self, "_pending_rename", None), None
        if pending is not None:
            self.renamed.emit(*pending)

    def _show_again(self) -> None:
        self._signature = None   # the editor changed an item's text: draw them all again
        self.set_changes(self._changes, self._ordered)

    def closeEditor(self, editor, hint) -> None:
        super().closeEditor(editor, hint)
        if self._editing:  # Esc, or nothing changed
            self._editing = False
            qt.QtCore.QTimer.singleShot(0, self._show_again)

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
        menu.addAction("Show it in the scene", lambda: self.show_requested.emit(change.node.uuid))
        menu.addAction("Select only this one", lambda: self.select_requested.emit(change.node.uuid))
        menu.addAction("Copy the name", lambda: qt.QtWidgets.QApplication.clipboard().setText(name))
        if change.state in _CHANGING:
            menu.addAction("Copy the new name", lambda: qt.QtWidgets.QApplication.clipboard().setText(change.new))
        lines = paste_lines(qt.QtWidgets.QApplication.clipboard().text())
        paste = menu.addAction(f"Paste names — {len(lines)} from the clipboard, one per row (Ctrl+V)"
                               if lines else "Paste names — copy a column of names first")
        paste.setEnabled(bool(lines))
        paste.triggered.connect(self.paste_requested.emit)
        paste.hovered.connect(lambda: self.paste_hovered.emit(True))
        menu.aboutToHide.connect(lambda: self.paste_hovered.emit(False))
        if self.tree_shown():
            menu.addAction("Fold every branch", lambda: (self._folded.update(self._kids), self._apply_fold(),
                                                         self.viewport().update()))
            menu.addAction("Unfold every branch", lambda: (self._folded.clear(), self._apply_fold(),
                                                           self.viewport().update()))
        if any(each.state == "skipped" for each in self._changes):
            menu.addAction("Include every one again", self.include_all.emit)
        if self._ordered:
            menu.addAction("Back to the order they came in", self.order_reset.emit)
        if getattr(self, "_picked", []):
            menu.addAction("Pick none — the whole list again", lambda: (self.set_picked([]), self.rows_picked.emit([])))
        menu.addSeparator()
        if change.state == "locked" and change.note == "locked node":
            menu.addAction("Unlock it", lambda: self.lock_requested.emit(change.node.uuid, False))
        elif change.state != "locked":
            menu.addAction("Lock it — no rename, delete or re-parent",
                           lambda: self.lock_requested.emit(change.node.uuid, True))
        menu.exec(self.viewport().mapToGlobal(position))


def paste_lines(text: str) -> list:
    """Names from copied text: one per line (a table's column), else separated by commas / tabs."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) == 1:
        for separator in ("\t", ",", ";"):
            if separator in lines[0]:
                return [part.strip() for part in lines[0].split(separator) if part.strip()]
    return lines


class HeightGrip(qt.QtWidgets.QWidget):
    """A thin handle under the list: drag it to make the list taller or shorter; a double click
    gives the list its own height back (as tall as its rows). Its mark's color: qproperty gripColor
    (rename.qss).

    Signals:
        dragged(int) — how far down (px) from where the drag started.
        released() — the drag is over.
        reset() — double click.
    """

    dragged = qt.QtCore.Signal(int)
    released = qt.QtCore.Signal()
    reset = qt.QtCore.Signal()

    gripColor = color_property("_grip_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grip_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_secondary)
        self._start = None
        self.setFixedHeight(9)
        self.setCursor(qt.QtCore.Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag to make the list taller or shorter · double click: as tall as its rows")

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        pen = qt.QtGui.QPen(self._grip_color, 2)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        middle = self.width() / 2
        for y in (self.height() / 2 - 1.5, self.height() / 2 + 1.5):
            painter.drawLine(qt.QtCore.QPointF(middle - 14, y), qt.QtCore.QPointF(middle + 14, y))
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._start = event.globalPosition().y()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None:
            self.dragged.emit(int(event.globalPosition().y() - self._start))

    def mouseReleaseEvent(self, event) -> None:
        if self._start is not None:
            self._start = None
            self.released.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        self.reset.emit()
