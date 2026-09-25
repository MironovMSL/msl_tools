# ui/widgets/compositions/draggable_list.py
import msl_tools.msl.ui.qt_bindings as qt


class _DragTargetIndicator(qt.QtWidgets.QLabel):
    """Private: the dashed drop-zone placeholder shown while dragging."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(25, 5, 25, 5)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #888; "
            "background-color: rgba(100, 100, 255, 40); text-align: center; }"
        )
        self.setText("Drop Here")


class DraggableList(qt.QtWidgets.QWidget):
    """Generic vertically-stacked list of widgets, reorderable by
    drag-and-drop and/or explicit up/down requests, with an animated
    reflow on every reorder.

    Storage-agnostic — knows nothing about what the items ARE or where
    their data lives. Each item is tracked by an opaque `item_id` string
    the caller assigns; this class only ever hands that id back out
    through its signals, never Maya Gate config or anything else.

    Ported from MSL_MayaGate's QCustomGroupBox.QDragWidget/
    DragTargetIndicator. Two real changes from the original:

    1. The original wrote directly to a global `json_config` singleton
       from inside this "generic" list (on remove/move), and reached
       three `.parent()` calls up to poke a specific enclosing widget's
       private methods. Both are gone — this class only emits signals;
       whoever owns an instance decides what to persist and how to
       react.
    2. start_drag() no longer sets a custom drag cursor pixmap — the
       original pointed at two paths hardcoded to msl.Mironov's own
       machine. Falls back to Qt's default drag cursor until real,
       portable cursor assets exist.

    An item widget opts into drag support by exposing a `drag_handle`
    attribute (any QWidget) — DraggableList installs its own event filter
    on that handle rather than the whole row, so only that handle starts
    a drag.

    Auto-scroll: when the list lives inside a scroll area (at any depth),
    holding a dragged row near the top/bottom edge of that scroll area's
    viewport scrolls it — faster the closer to the edge — and the drop
    indicator keeps following the cursor as the content moves under it.

    Signals:
        order_changed(list[str]) — new item_id order, after a drag-drop.
        item_removed(str) — item_id whose widget was just removed.
        item_moved_up(str) / item_moved_down(str) — item_id that was just
            moved one slot, via an explicit request (not drag-and-drop).
    """

    order_changed = qt.QtCore.Signal(list)
    item_removed = qt.QtCore.Signal(str)
    item_moved_up = qt.QtCore.Signal(str)
    item_moved_down = qt.QtCore.Signal(str)

    REORDER_ANIMATION_MS = 300
    DRAG_REFLOW_ANIMATION_MS = 300
    DRAG_START_DISTANCE_FALLBACK = 10

    AUTO_SCROLL_MARGIN = 36      # px from the viewport edge where auto-scroll kicks in
    AUTO_SCROLL_MAX_STEP = 16    # px per tick right at the edge
    AUTO_SCROLL_INTERVAL_MS = 16

    def __init__(self, draggable: bool = False, parent=None):
        super().__init__(parent)
        self._animations: list = []
        self._draggable = False
        self._dragging_widget = None
        self._drag_start_pos = None
        self._drag_target_indicator: _DragTargetIndicator | None = None
        self._drop_accepted = False

        self._auto_scroll_timer = qt.QtCore.QTimer(self)
        self._auto_scroll_timer.setInterval(self.AUTO_SCROLL_INTERVAL_MS)
        self._auto_scroll_timer.timeout.connect(self._on_auto_scroll_tick)

        self._build_layout()
        self.set_draggable(draggable)

    def _build_layout(self) -> None:
        self.main_layout = qt.QtWidgets.QVBoxLayout(self)
        self.main_layout.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

    def set_draggable(self, state: bool) -> None:
        self.setAcceptDrops(state)
        self._draggable = state
        if state and self._drag_target_indicator is None:
            self._drag_target_indicator = _DragTargetIndicator()
            self._drag_target_indicator.hide()

    # --- items -------------------------------------------------------

    def append_widget(self, item_id: str, widget: qt.QtWidgets.QWidget) -> None:
        """Adds `widget` to the end of the list under `item_id`. Connects
        any of remove_requested/move_up_requested/move_down_requested
        signals the widget happens to expose — none are required."""
        widget._dl_item_id = item_id  # noqa: SLF001 — this class's own bookkeeping, not the widget's

        if self._draggable and getattr(widget, "drag_handle", None) is not None:
            widget.drag_handle.installEventFilter(self)

        if hasattr(widget, "remove_requested"):
            widget.remove_requested.connect(lambda i=item_id: self._on_item_removed(i))
        if hasattr(widget, "move_up_requested"):
            widget.move_up_requested.connect(lambda i=item_id: self._on_item_moved(i, -1))
        if hasattr(widget, "move_down_requested"):
            widget.move_down_requested.connect(lambda i=item_id: self._on_item_moved(i, +1))

        self.main_layout.addWidget(widget)

    def clear(self) -> None:
        """Removes and deletes every item. Does not emit item_removed —
        this is a bulk reset (e.g. switching sections), not a per-item
        removal the caller needs to react to individually."""
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def current_order(self) -> list[str]:
        """item_ids in their current visual (top-to-bottom) order."""
        order = []
        for i in range(self.main_layout.count()):
            widget = self.main_layout.itemAt(i).widget()
            item_id = getattr(widget, "_dl_item_id", None)
            if item_id is not None:
                order.append(item_id)
        return order

    # --- explicit move / remove requests --------------------------------

    def _on_item_removed(self, item_id: str) -> None:
        for i in range(self.main_layout.count()):
            widget = self.main_layout.itemAt(i).widget()
            if getattr(widget, "_dl_item_id", None) == item_id:
                self.main_layout.removeWidget(widget)  # deleteLater() alone defers this — current_order() would still see it
                widget.deleteLater()
                break
        self.item_removed.emit(item_id)

    def _on_item_moved(self, item_id: str, direction: int) -> None:
        widget = None
        for i in range(self.main_layout.count()):
            candidate = self.main_layout.itemAt(i).widget()
            if getattr(candidate, "_dl_item_id", None) == item_id:
                widget = candidate
                break
        if widget is None:
            return

        self._move_widget_animated(widget, direction)
        (self.item_moved_up if direction < 0 else self.item_moved_down).emit(item_id)

    def _move_widget_animated(self, widget: qt.QtWidgets.QWidget, direction: int) -> None:
        layout = self.main_layout
        index = layout.indexOf(widget)
        new_index = index + direction

        if 0 <= new_index < layout.count():
            layout.removeWidget(widget)
            layout.insertWidget(new_index, widget)
            self._animate_reorder()

    def _animate_reorder(self,
                         duration_ms: int | None = None,
                         easing: "qt.QtCore.QEasingCurve.Type" = qt.QtCore.QEasingCurve.Type.OutBack) -> None:
        """Re-lays out the list and slides every item from where it is NOW to
        its new slot. "Where it is now" may be mid-animation — each call
        retargets from the current position, so rapid successive reorders
        (e.g. while dragging) stay smooth instead of snapping."""
        layout = self.main_layout
        self._stop_animations()

        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        widgets = [w for w in widgets if w is not None and w.isVisible()]
        old_positions = [w.pos() for w in widgets]
        layout.activate()
        new_positions = [w.pos() for w in widgets]

        for w, old_pos, new_pos in zip(widgets, old_positions, new_positions):
            if old_pos == new_pos:
                continue
            w.move(old_pos)
            anim = qt.QtCore.QPropertyAnimation(w, b"pos", self)
            anim.setDuration(duration_ms or self.REORDER_ANIMATION_MS)
            anim.setEasingCurve(easing)
            anim.setStartValue(old_pos)
            anim.setEndValue(new_pos)
            anim.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
            self._animations.append(anim)

    def _stop_animations(self) -> None:
        # Stopping (not just forgetting) matters: two animations driving the same
        # widget's pos would fight each other for the rest of their duration.
        for anim in self._animations:
            if qt.shiboken.isValid(anim):
                anim.stop()
        self._animations.clear()

    # --- drag start (from a row's drag handle) --------------------------

    def eventFilter(self, obj, event) -> bool:
        if self._draggable and obj is getattr(obj.parent(), "drag_handle", None):
            event_type = event.type()
            if event_type == qt.QtCore.QEvent.Type.Enter:
                obj.setCursor(qt.QtCore.Qt.CursorShape.OpenHandCursor)
                return True
            elif event_type == qt.QtCore.QEvent.Type.Leave:
                obj.unsetCursor()
                return True
            elif event_type == qt.QtCore.QEvent.Type.MouseButtonPress and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
                obj.setCursor(qt.QtCore.Qt.CursorShape.ClosedHandCursor)
                self._dragging_widget = obj.parentWidget()
                self._drag_start_pos = event.position().toPoint()
                return True
            elif event_type == qt.QtCore.QEvent.Type.MouseMove and self._drag_start_pos:
                distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
                if distance > qt.QtWidgets.QApplication.startDragDistance():
                    self._start_drag(obj)
                    self._dragging_widget = None
                    self._drag_start_pos = None
                return True
            elif event_type == qt.QtCore.QEvent.Type.MouseButtonRelease:
                obj.setCursor(qt.QtCore.Qt.CursorShape.OpenHandCursor)
                self._dragging_widget = None
                self._drag_start_pos = None
                return True

        return super().eventFilter(obj, event)

    def _start_drag(self, drag_handle: qt.QtWidgets.QWidget) -> None:
        """Runs a whole drag-and-drop gesture (QDrag.exec() blocks until drop/cancel).

        The dragged row is swapped for the drop indicator at the SAME index and
        size before the drag starts, so nothing shifts at pickup. While dragging,
        only the indicator changes index; the other rows slide around it
        (see dragMoveEvent). On cancel the row goes back where it started.
        """
        source = self._dragging_widget
        if not source:
            return

        drag = qt.QtGui.QDrag(source)
        drag.setMimeData(qt.QtCore.QMimeData())
        drag.setPixmap(source.grab())
        drag.setHotSpot(drag_handle.mapTo(source, self._drag_start_pos))

        start_index = self.main_layout.indexOf(source)
        indicator = self._drag_target_indicator
        indicator.setFixedHeight(source.height())
        self.main_layout.replaceWidget(source, indicator)
        source.hide()
        indicator.show()
        self._drop_accepted = False

        # No custom drag cursor here — see class docstring.
        drag.exec(qt.QtCore.Qt.DropAction.MoveAction)
        self._auto_scroll_timer.stop()

        if not self._drop_accepted:
            self.main_layout.removeWidget(indicator)
            indicator.hide()
            self.main_layout.insertWidget(start_index, source)
            source.show()
            self._animate_reorder(self.DRAG_REFLOW_ANIMATION_MS, qt.QtCore.QEasingCurve.Type.InOutCubic)

    # --- drop target -----------------------------------------------------

    def _is_own_drag(self, e) -> bool:
        # Only rows of THIS list can be dropped here — a row dragged out of a
        # sibling list (e.g. another variable group) is ignored.
        return self._dragging_widget is not None and e.source() is self._dragging_widget

    def dragEnterEvent(self, e) -> None:
        if self._is_own_drag(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e) -> None:
        if not self._is_own_drag(e):
            e.ignore()
            return

        self._move_indicator_to(e.position().toPoint().y())
        if self._auto_scroll_step() and not self._auto_scroll_timer.isActive():
            self._auto_scroll_timer.start()
        e.acceptProposedAction()

    def _move_indicator_to(self, y: int) -> None:
        indicator = self._drag_target_indicator
        target_index = self._find_drop_location(y)
        if target_index != self.main_layout.indexOf(indicator):
            self.main_layout.removeWidget(indicator)
            self.main_layout.insertWidget(target_index, indicator)
            self._animate_reorder(self.DRAG_REFLOW_ANIMATION_MS, qt.QtCore.QEasingCurve.Type.OutCubic)

    def dropEvent(self, e) -> None:
        if not self._is_own_drag(e):
            e.ignore()
            return

        self._auto_scroll_timer.stop()
        source = self._dragging_widget
        indicator = self._drag_target_indicator
        self._stop_animations()
        self.main_layout.replaceWidget(indicator, source)
        indicator.hide()
        source.show()
        self.main_layout.activate()
        self._drop_accepted = True

        e.acceptProposedAction()
        self.order_changed.emit(self.current_order())

    def _find_drop_location(self, y: int) -> int:
        """Layout index the indicator should occupy for a cursor at `y` (list coords).

        Uses each row's layout slot (item.geometry()), not its live pos(): rows
        are mid-animation while dragging, and hit-testing their moving positions
        would make the target flicker back and forth.
        """
        index = 0
        for n in range(self.main_layout.count()):
            item = self.main_layout.itemAt(n)
            widget = item.widget()
            if widget is None or widget is self._drag_target_indicator:
                continue
            if y > item.geometry().center().y():
                index += 1
        return index

    # --- auto-scroll while dragging ------------------------------------------

    def _enclosing_scroll_area(self) -> "qt.QtWidgets.QAbstractScrollArea | None":
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, qt.QtWidgets.QAbstractScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def _auto_scroll_step(self) -> int:
        """Signed px to scroll this tick for the cursor's position: negative
        near the viewport's top edge, positive near the bottom, 0 elsewhere
        (or when there's nothing left to scroll in that direction)."""
        area = self._enclosing_scroll_area()
        if area is None:
            return 0
        viewport = area.viewport()
        y = viewport.mapFromGlobal(qt.QtGui.QCursor.pos()).y()
        margin = self.AUTO_SCROLL_MARGIN
        bar = area.verticalScrollBar()

        if y < margin and bar.value() > bar.minimum():
            depth = margin - max(y, 0)
            return -max(1, round(self.AUTO_SCROLL_MAX_STEP * depth / margin))
        if y > viewport.height() - margin and bar.value() < bar.maximum():
            depth = y - (viewport.height() - margin)
            return max(1, round(self.AUTO_SCROLL_MAX_STEP * min(depth, margin) / margin))
        return 0

    def _on_auto_scroll_tick(self) -> None:
        step = self._auto_scroll_step() if self._dragging_widget is not None else 0
        if not step:
            self._auto_scroll_timer.stop()
            return
        bar = self._enclosing_scroll_area().verticalScrollBar()
        bar.setValue(bar.value() + step)
        # The content just moved under a (possibly still) cursor — no drag-move
        # event fires for that, so re-aim the indicator ourselves.
        self._move_indicator_to(self.mapFromGlobal(qt.QtGui.QCursor.pos()).y())


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()

        drag_list = DraggableList(draggable=False)
        for label in ("Row A", "Row B", "Row C"):
            row = qt.QtWidgets.QLabel(label)
            drag_list.append_widget(label, row)
        dialog.add_case("DraggableList (no drag handles, just the list mechanics)", drag_list)
        dialog.show()