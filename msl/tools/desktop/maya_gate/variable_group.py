# tools/desktop/maya_gate/variable_group.py
from pathlib import Path
from typing import Callable, Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.compositions import BrowseMode, BulkActionBar, DraggableList, EnvVarRow
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog

# Maya Gate's own style rules (qproperty colors of its tool-specific widgets)
# live next to the tool, not in ui/theme/widgets.qss.
StylesheetBuilder.register_template(Path(__file__).with_name("maya_gate.qss"))

_QWIDGETSIZE_MAX = 16777215


class _FoldArrow(qt.QtWidgets.QLabel):
    """Private: chevron that rotates between ▸ (collapsed, 0°) and ▾ (expanded, 90°).

    A QLabel subclass on purpose: the global QSS `QLabel { color: ... }` rule
    matches it too, so its palette text color follows the theme for free.
    """

    SIZE = 14
    ROTATE_MS = 260

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._angle = 0.0
        self._animation: qt.QtCore.QPropertyAnimation | None = None

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, value: float) -> None:
        self._angle = value
        self.update()

    angle = qt.QtCore.Property(float, _get_angle, _set_angle)

    def set_expanded(self, expanded: bool, animate: bool) -> None:
        target = 90.0 if expanded else 0.0
        if self._animation is not None and qt.shiboken.isValid(self._animation):
            self._animation.stop()
        if not animate:
            self._set_angle(target)
            return
        animation = qt.QtCore.QPropertyAnimation(self, b"angle", self)
        animation.setDuration(self.ROTATE_MS)
        animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutBack)
        animation.setStartValue(self._angle)
        animation.setEndValue(target)
        animation.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._animation = animation

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._angle)

        pen = qt.QtGui.QPen(self.palette().color(self.foregroundRole()), 1.6)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        # A right-pointing chevron centered on the origin; rotation turns it down.
        painter.drawPolyline([qt.QtCore.QPointF(-2, -4), qt.QtCore.QPointF(2, 0), qt.QtCore.QPointF(-2, 4)])


class _ClipBody(qt.QtWidgets.QWidget):
    """Private: a window onto one child that is ALWAYS laid out at its full
    height — shrinking the body only clips the child, never squeezes it.

    A regular layout would hand the child less height as the body animates
    down, and the child's own layout would then pile its rows on top of
    each other — fighting the per-row fold animation for their positions.
    """

    def __init__(self, child: qt.QtWidgets.QWidget, parent=None):
        super().__init__(parent)
        self._child = child
        child.setParent(self)
        child.installEventFilter(self)

    def sizeHint(self) -> qt.QtCore.QSize:
        return self._child.sizeHint()

    def minimumSizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(0, 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_child()

    def eventFilter(self, watched, event) -> bool:
        # The child's content changed (rows added/removed) — re-fit it and let
        # our own parent layout know our size hint moved with it.
        if watched is self._child and event.type() == qt.QtCore.QEvent.Type.LayoutRequest:
            self._sync_child()
            self.updateGeometry()
        return super().eventFilter(watched, event)

    def _sync_child(self) -> None:
        self._child.setGeometry(0, 0, self.width(), self._child.sizeHint().height())


class _GroupHeader(qt.QtWidgets.QWidget):
    """Private: clickable header row — fold arrow, title, row count, and the
    bulk-action bar that fades in next to them while rows are selected.
    Clicks on the bar's own buttons are consumed by them, so they never
    toggle the fold."""

    HEIGHT = 24
    BULK_BAR_GAP = 16

    clicked = qt.QtCore.Signal()

    def __init__(self, left_inset: int = 4, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

        self._arrow = _FoldArrow()
        self._title_label = qt.QtWidgets.QLabel()
        self._count_label = qt.QtWidgets.QLabel()
        self._count_label.setEnabled(False)  # dimmed: secondary info
        self.bulk_bar = BulkActionBar()
        self.bulk_bar.setCursor(qt.QtCore.Qt.CursorShape.ArrowCursor)

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(left_inset, 0, 4, 0)
        layout.setSpacing(4)
        layout.addWidget(self._arrow)
        layout.addWidget(self._title_label)
        layout.addWidget(self._count_label)
        layout.addSpacing(self.BULK_BAR_GAP)
        layout.addWidget(self.bulk_bar)
        layout.addStretch()

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def set_count(self, count: int) -> None:
        self._count_label.setText(f"({count})")

    def set_collapsed(self, collapsed: bool, animate: bool = False) -> None:
        self._arrow.set_expanded(not collapsed, animate)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CollapsibleVariableGroup(qt.QtWidgets.QWidget):
    """One collapsible section of Maya Gate's "Variables" tab — a clickable
    header (fold arrow, "title · section", row count) over a drag-reorderable
    list of EnvVarRow for one config section (e.g. the "Dev" environment).

    Owns variable persistence: listens to DraggableList's generic signals
    and writes through the JsonConfig section it's given. Ported from
    MSL_MayaGate's QCustomGroupBox + QCustomScrollArea — the actual list
    mechanics moved out to DraggableList/EnvVarRow (ui/widgets/
    compositions/), which know nothing about config.

    Visible only while its section has variables (an empty group would be
    just a header with nothing to fold).

    Sizing: no scroll area of its own and no row cap — the box always
    grows to fit every row, and the page's single scroll area scrolls the
    whole editor. Nested scroll areas were dropped on purpose: the inner
    one captured the mouse wheel mid-page, and a drag couldn't reach rows
    hidden inside it. Long groups are handled by collapsing instead.

    Collapsed state is NOT persisted here: the box takes the initial state
    and emits collapsed_changed(bool); the owner decides where to store it.

    Selection & bulk actions: each row's hover-menu checkbox selects it;
    while anything is selected, the header shows a BulkActionBar
    ("N selected · ➜ · 🗑 · ×"). More bulk operations: add them in
    _build_bulk_actions() — the bar itself is operation-agnostic.
    Selection is per section and resets on section switch.

    "Copy to…" (➜) copies the selected variables, values included, into
    another section of the same config (one of `copy_targets`, e.g. from
    Dev to Stable); names that already exist there with a different value
    are replaced or skipped, as the user chooses. copy_items_to() is the
    non-interactive core.

    Signals:
        collapsed_changed(bool)
    """

    CONTENT_MARGIN = 4
    # Column LEFT of the frame for the rows' drag handles (Notion's
    # page-margin handles). The frame is painted from this x; owners that
    # want other content to line up with the frame indent it by this much.
    SELECTION_GUTTER = 22
    FRAME_RADIUS = 5
    NAME_COLUMN_MAX_WIDTH = 260    # longer names are clipped (full name in the tooltip)
    # Fold animation (see _run_fold_animation). Stagger shrinks for long lists
    # so the whole cascade never takes longer than MAX_TOTAL_STAGGER_MS + one row.
    ROW_ANIMATION_MS = 280
    ROW_STAGGER_MS = 40
    MAX_TOTAL_STAGGER_MS = 240
    ROW_SLIDE_PX = 50
    BODY_FOLD_MS = 500             # how long the empty body takes to fold shut / unfold open
    BODY_FOLD_AFTER_ROW = 0.4      # collapse: fold starts this far (0..1) into the last row's fade
    ROWS_AFTER_BODY_UNFOLD = 0.4   # expand: rows start dropping in this far (0..1) into the unfold

    # Easing curves — class-level so they can be tuned live (see the __main__
    # playground at the bottom of this file) or overridden per instance.
    ROW_EXPAND_EASING = qt.QtCore.QEasingCurve.Type.OutQuint
    ROW_COLLAPSE_EASING = qt.QtCore.QEasingCurve.Type.InQuint
    BODY_UNFOLD_EASING = qt.QtCore.QEasingCurve.Type.InOutQuint
    BODY_FOLD_EASING = qt.QtCore.QEasingCurve.Type.InOutQuint

    collapsed_changed = qt.QtCore.Signal(bool)

    frameColor = color_property("_frame_color")   # set by maya_gate.qss

    def __init__(self, title: str, section: str, config, collapsed: bool = False,
                 copy_targets: Sequence[str] = (),
                 browse_mode_for: Callable[[str], BrowseMode] | None = None, parent=None):
        """
        Args:
            title: Display title prefix (e.g. "Maya Variables"); shown as
                "<title> · <section>".
            section: Config section this group edits (e.g. "Dev").
            config: The JsonConfig (or ConfigNode) whose sections this group
                reads/writes — supplied by the owner, not looked up here.
            collapsed: Initial fold state.
            browse_mode_for: Variable name -> its row's BrowseMode (what
                browsing does: replace / append to a path list / nothing).
                None = every row replaces.
            copy_targets: Sections "Copy to…" offers (the current one is
                always left out). Empty = no copy action.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._title = title
        self._section = section
        self._config = config
        self._copy_targets = list(copy_targets)
        self._browse_mode_for = browse_mode_for or (lambda _name: BrowseMode.REPLACE)
        self._frame_color = qt.QtGui.QColor(ThemeRegistry.fallback().border)  # until QSS applies
        self._collapsed = collapsed
        self._selected: set[str] = set()
        self._fold_animation: qt.QtCore.QParallelAnimationGroup | None = None

        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Preferred, qt.QtWidgets.QSizePolicy.Policy.Fixed)

        self._build_widgets()
        self._build_layout()
        self._build_connections()
        self._apply_collapsed(animate=False)
        self.set_section(section)

    def _build_widgets(self) -> None:
        self._header = _GroupHeader(left_inset=self.SELECTION_GUTTER + self.CONTENT_MARGIN)
        self._build_bulk_actions()
        self.list = DraggableList(draggable=True)
        self.list.set_drop_indicator_inset(self.SELECTION_GUTTER + 2)  # keep "Drop Here" inside the frame

        # The list sits in a clipping body so collapsing can animate the
        # body's height while the list itself keeps its full size.
        self._body = _ClipBody(self.list)

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        margin = self.CONTENT_MARGIN
        # No left margin: rows start at x=0 so their drag handles land in the
        # gutter, outside the frame painted at x=SELECTION_GUTTER.
        layout.setContentsMargins(0, margin, margin, margin)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._body)
        # While the body animates, the box's own height catches up one layout
        # pass later; without this, that transient slack gets split around the
        # items and the header visibly drifts down during a collapse.
        layout.addStretch()

    def _build_bulk_actions(self) -> None:
        """Registers every bulk operation on the header's BulkActionBar —
        add new ones here (one add_action() + one handler each)."""
        bar = self._header.bulk_bar
        if self._copy_targets:
            self._copy_button = bar.add_action("➜", "Copy selected to another environment…")
            self._copy_button.set_icon(UiResources().iconManager.get_icon("arrow_right", sub_folder="actions"))
            self._copy_button.clicked.connect(self._show_copy_menu)
        delete_button = bar.add_action("\U0001f5d1", "Delete selected")
        delete_button.set_icon(UiResources().iconManager.get_icon("delete", sub_folder="actions"))
        delete_button.clicked.connect(self._delete_selected)
        bar.clear_requested.connect(self.clear_selection)

    def _build_connections(self) -> None:
        self._header.clicked.connect(self.toggle_collapsed)
        self.list.order_changed.connect(self._on_order_changed)
        self.list.item_removed.connect(self._on_item_removed)
        self.list.item_moved_up.connect(lambda item_id: self._on_item_moved(item_id, -1))
        self.list.item_moved_down.connect(lambda item_id: self._on_item_moved(item_id, +1))

    # --- public API --------------------------------------------------------

    def set_section(self, section: str) -> None:
        """Switches to a different config section, rebuilding all rows."""
        self._section = section
        variables = list(self._config[section].keys())

        self._selected.clear()
        self._header.bulk_bar.set_count(0)
        self.list.clear()
        self._update_title(section)
        for var_name in variables:
            self._append_row(var_name, self._config[section][var_name])
        self._update_state()

    def add_variable(self, var_name: str) -> None:
        """Adds a new, empty variable to this section. No-op if it
        already exists (matches the original's duplicate check). Expands
        the group if it was collapsed, so the new row is actually seen."""
        if var_name in self._config[self._section]:
            return
        self._config[self._section][var_name] = ""
        self._append_row(var_name, "")
        self._update_state()
        if self._collapsed:
            self.set_collapsed(False)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_collapsed(animate)
        self.collapsed_changed.emit(collapsed)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def selected_items(self) -> list[str]:
        """Selected variable names, in their current list order."""
        return [item_id for item_id in self.list.current_order() if item_id in self._selected]

    def clear_selection(self) -> None:
        for row in self._rows():
            row.set_selected(False)  # each emits selection_changed -> _on_row_selection_changed

    def paintEvent(self, event) -> None:
        """Draws the group frame starting at SELECTION_GUTTER, so the rows'
        drag-handle column visually sits outside it."""
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtGui.QPen(self._frame_color, 1))
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        frame = qt.QtCore.QRectF(self.rect()).adjusted(self.SELECTION_GUTTER + 0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(frame, self.FRAME_RADIUS, self.FRAME_RADIUS)
        painter.end()

    # --- rows / persistence --------------------------------------------------

    def _align_name_column(self) -> None:
        """Gives every row the same name-column width (the longest name,
        capped), so value fields start at one x instead of zig-zagging."""
        rows = self._rows()
        if not rows:
            return
        width = min(max(row.name_width_hint() for row in rows), self.NAME_COLUMN_MAX_WIDTH)
        for row in rows:
            row.set_name_width(width)

    def _rows(self) -> list:
        # From the layout, not findChildren(): rows removed with deleteLater()
        # are still children until the event loop gets to them.
        layout = self.list.main_layout
        widgets = (layout.itemAt(i).widget() for i in range(layout.count()))
        return [w for w in widgets if isinstance(w, EnvVarRow)]

    def _append_row(self, var_name: str, value: str) -> None:
        row = EnvVarRow(var_name, value, draggable=True,
                        selection_gutter=self.SELECTION_GUTTER,
                        browse_mode=self._browse_mode_for(var_name))
        row.value_changed.connect(self._on_value_changed)
        row.selection_changed.connect(self._on_row_selection_changed)
        self.list.append_widget(var_name, row)

    def _on_row_selection_changed(self, var_name: str, selected: bool) -> None:
        if selected:
            self._selected.add(var_name)
        else:
            self._selected.discard(var_name)
        self._header.bulk_bar.set_count(len(self._selected))

    def _delete_selected(self) -> None:
        for var_name in self.selected_items():
            self.list.remove_item(var_name)  # -> item_removed -> _on_item_removed (config + selection)

    # --- copy to another section ---------------------------------------------

    def copy_items_to(self, names: Sequence[str], target: str,
                      replace_existing: bool) -> tuple[list[str], list[str]]:
        """Copies variables `names` (with their values) from the current
        section into section `target` of the same config.

        A name already in `target` with the SAME value counts as copied (no
        change needed); with a DIFFERENT value it's overwritten only when
        `replace_existing` is True, otherwise left alone.

        Returns:
            (copied, skipped) name lists.
        """
        source = self._config[self._section]
        destination = self._config[target]
        copied, skipped = [], []
        for name in names:
            value = source[name]
            if name in destination and destination[name] != value and not replace_existing:
                skipped.append(name)
                continue
            destination[name] = value
            copied.append(name)
        return copied, skipped

    def copy_target_choices(self) -> list[str]:
        """Sections "Copy to…" offers right now (every target but the current one)."""
        return [target for target in self._copy_targets if target != self._section]

    def _show_copy_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))  # QSS border-radius shows
        for target in self.copy_target_choices():
            menu.addAction(target).triggered.connect(lambda _=False, t=target: self._copy_selected_to(t))
        menu.exec(self._copy_button.mapToGlobal(qt.QtCore.QPoint(0, self._copy_button.height())))

    def _ask_conflict_resolution(self, target: str, conflicts: list[str]) -> str | None:
        """Asks what to do with names already in `target` with a different
        value. Returns "replace", "skip", or None (cancel / window closed)."""
        choice = ConfirmDialog.ask(
            self, "Copy variables",
            f'{len(conflicts)} of the selected variables already exist in "{target}" '
            f"with a different value:",
            details=", ".join(conflicts),
            choices=[("replace", "Replace"), ("skip", "Skip existing"), ("cancel", "Cancel")])
        return choice if choice in ("replace", "skip") else None

    def _copy_selected_to(self, target: str) -> None:
        """Interactive copy: resolves conflicts with the user, then copies
        and reports."""
        names = self.selected_items()
        destination = self._config[target]
        source = self._config[self._section]
        conflicts = [name for name in names if name in destination and destination[name] != source[name]]

        replace = False
        if conflicts:
            choice = self._ask_conflict_resolution(target, conflicts)
            if choice is None:
                return
            replace = choice == "replace"

        copied, skipped = self.copy_items_to(names, target, replace_existing=replace)
        self.clear_selection()
        message = f"Copied {len(copied)} to {target}" + (f", skipped {len(skipped)}" if skipped else "")
        qt.QtWidgets.QToolTip.showText(qt.QtGui.QCursor.pos(), message, self)

    def _on_value_changed(self, var_name: str, value: str) -> None:
        self._config[self._section][var_name] = value

    def _on_order_changed(self, new_order: list) -> None:
        self._config[self._section].reorder_keys(new_order)

    def _on_item_removed(self, var_name: str) -> None:
        del self._config[self._section][var_name]
        self._selected.discard(var_name)
        self._header.bulk_bar.set_count(len(self._selected))
        self._update_state()

    def _on_item_moved(self, var_name: str, direction: int) -> None:
        if direction < 0:
            self._config[self._section].move_key_left(var_name)
        else:
            self._config[self._section].move_key_right(var_name)

    # --- presentation ----------------------------------------------------------

    def _update_title(self, section: str) -> None:
        self.setObjectName(f"CollapsibleVariableGroup_{section}")
        self._header.set_title(f"{self._title} \u00b7 {section}")

    def _update_state(self) -> None:
        self._align_name_column()
        count = len(list(self._config[self._section].keys()))
        self._header.set_count(count)
        if count == 0:
            self.hide()
        elif self.parentWidget() is not None:
            # show() on a still-parentless widget would pop it up as its own
            # window; not being explicitly hidden, it shows with its parent.
            self.show()

    # --- fold animation ---------------------------------------------------------
    #
    # Modeled on MayaVersionRow's show/hide: every row gets its own staggered
    # slide + fade instead of the body just being squashed.
    #   collapse: top row first, each is pulled up toward the header (InQuint —
    #             lingers, then leaves fast) while fading out; once the last
    #             row is on its way, the (by then empty) body folds shut.
    #             Shrinking earlier would clip rows that are still visible.
    #   expand:   the mirror image — the empty body unfolds to its full size
    #             first, and as it nears the end the rows drop in top row
    #             first, out of the header (OutQuint — fast in, soft landing,
    #             no overshoot) while fading in.
    # Curves/timings were picked by eye in the __main__ playground below.
    # Clicking again mid-animation reverses from wherever everything is NOW.

    def _apply_collapsed(self, animate: bool) -> None:
        animate = animate and self.isVisible()
        self._header.set_collapsed(self._collapsed, animate=animate)

        if self._fold_animation is not None and qt.shiboken.isValid(self._fold_animation):
            self._fold_animation.stop()  # stop() emits no finished(): rows keep their mid-flight state
        self._fold_animation = None

        rows = self._visible_rows()
        if not animate or not rows:
            self._finish_fold()
            return
        self._run_fold_animation(rows)

    def _visible_rows(self) -> list:
        return [row for row in self._rows() if not row.isHidden()]

    def _run_fold_animation(self, rows: list) -> None:
        collapsing = self._collapsed
        layout = self.list.main_layout
        layout.activate()
        slide = qt.QtCore.QPoint(0, self.ROW_SLIDE_PX)

        count = len(rows)
        stagger = min(self.ROW_STAGGER_MS, self.MAX_TOTAL_STAGGER_MS // max(count - 1, 1))

        full_height = self.list.sizeHint().height()
        if collapsing:
            rows_delay = 0
        else:
            # Unfold only what's still closed (a reversed collapse may be half-open
            # already), and hold the rows back until the body is mostly open.
            remaining = 1.0 - min(self._body.height() / max(full_height, 1), 1.0)
            unfold_ms = max(1, int(self.BODY_FOLD_MS * remaining))
            rows_delay = int(unfold_ms * self.ROWS_AFTER_BODY_UNFOLD)

        group = qt.QtCore.QParallelAnimationGroup(self)
        for k, row in enumerate(rows):
            rest_pos = layout.itemAt(layout.indexOf(row)).geometry().topLeft()
            hidden_pos = rest_pos - slide

            effect = row.graphicsEffect()
            if not isinstance(effect, qt.QtWidgets.QGraphicsOpacityEffect):
                # Fresh start (not reversing a running fold): expanding rows
                # begin invisible, tucked up under the header.
                effect = qt.QtWidgets.QGraphicsOpacityEffect(row)
                effect.setOpacity(1.0 if collapsing else 0.0)
                row.setGraphicsEffect(effect)
                if not collapsing:
                    row.move(hidden_pos)

            anim_pos = qt.QtCore.QPropertyAnimation(row, b"pos")
            anim_pos.setDuration(self.ROW_ANIMATION_MS)
            anim_pos.setEasingCurve(self.ROW_COLLAPSE_EASING if collapsing else self.ROW_EXPAND_EASING)
            anim_pos.setStartValue(row.pos())
            anim_pos.setEndValue(hidden_pos if collapsing else rest_pos)

            anim_opacity = qt.QtCore.QPropertyAnimation(effect, b"opacity")
            anim_opacity.setDuration(self.ROW_ANIMATION_MS)
            anim_opacity.setEasingCurve(qt.QtCore.QEasingCurve.Type.InOutQuad)
            anim_opacity.setStartValue(effect.opacity())
            anim_opacity.setEndValue(0.0 if collapsing else 1.0)

            row_parallel = qt.QtCore.QParallelAnimationGroup()
            row_parallel.addAnimation(anim_pos)
            row_parallel.addAnimation(anim_opacity)

            row_sequence = qt.QtCore.QSequentialAnimationGroup()
            row_sequence.addPause(rows_delay + k * stagger)
            row_sequence.addAnimation(row_parallel)
            group.addAnimation(row_sequence)

        body_height = qt.QtCore.QPropertyAnimation(self._body, b"maximumHeight")
        body_height.setEasingCurve(self.BODY_FOLD_EASING if collapsing else self.BODY_UNFOLD_EASING)
        body_height.setStartValue(self._body.height())
        if collapsing:
            # Wait until the last row is well into its fade, then fold the empty body.
            body_delay = stagger * (count - 1) + int(self.ROW_ANIMATION_MS * self.BODY_FOLD_AFTER_ROW)
            body_height.setDuration(self.BODY_FOLD_MS)
            body_height.setEndValue(0)
            body_sequence = qt.QtCore.QSequentialAnimationGroup()
            body_sequence.addPause(body_delay)
            body_sequence.addAnimation(body_height)
            group.addAnimation(body_sequence)
        else:
            body_height.setDuration(unfold_ms)
            body_height.setEndValue(full_height)
            group.addAnimation(body_height)

        group.finished.connect(self._finish_fold)
        group.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fold_animation = group

    def _finish_fold(self) -> None:
        """Settles the final state: body capped (collapsed) or uncapped
        (expanded, so rows added later still fit), rows back in their layout
        slots, and the temporary opacity effects removed — a graphics effect
        left on a row would re-render it (line edit included) offscreen forever."""
        self._fold_animation = None
        self._body.setMaximumHeight(0 if self._collapsed else _QWIDGETSIZE_MAX)
        for row in self._visible_rows():
            row.setGraphicsEffect(None)
        self.list.main_layout.invalidate()
        self.list.main_layout.activate()
        self.updateGeometry()


if __name__ == "__main__":
    # Fold-animation playground: pick curves/timings live, click "Toggle"
    # (or the group's header) to watch, "Print settings" to copy the result
    # back into the class constants.
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.core.resources import Resources
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    Easing = qt.QtCore.QEasingCurve
    ROW_IN_CURVES = ["OutBack", "OutElastic", "OutBounce", "OutQuint", "OutExpo", "OutCirc", "InOutBack", "Linear"]
    ROW_OUT_CURVES = ["InBack", "InQuint", "InExpo", "InCirc", "InOutBack", "InElastic", "InBounce", "Linear"]
    BODY_CURVES = ["InOutCubic", "OutCubic", "InOutQuint", "OutQuint", "OutBack", "OutElastic", "OutBounce",
                   "InOutBack", "Linear"]

    with QtApplicationContext():
        config = Resources().configsMayaMng.get_config("maya_gate_demo", defaults={})
        if not list(config["Playground"].keys()):
            for name in ("MAYA_APP_DIR", "MAYA_MODULE_PATH", "MAYA_SCRIPT_PATH",
                         "PYTHONPATH", "XBMLANGPATH", "TEMP"):
                config["Playground"][name] = f"H:/Demo/{name.lower()}"

        group = CollapsibleVariableGroup("Maya Variables", "Playground", config)

        def curve_combo(names, default):
            combo = qt.QtWidgets.QComboBox()
            combo.addItems(names)
            combo.setCurrentText(default)
            return combo

        def spin(value, maximum, step=10, decimals=None):
            box = qt.QtWidgets.QDoubleSpinBox() if decimals else qt.QtWidgets.QSpinBox()
            if decimals:
                box.setDecimals(decimals)
            box.setRange(0, maximum)
            box.setSingleStep(step)
            box.setValue(value)
            return box

        row_in = curve_combo(ROW_IN_CURVES, CollapsibleVariableGroup.ROW_EXPAND_EASING.name)
        row_out = curve_combo(ROW_OUT_CURVES, CollapsibleVariableGroup.ROW_COLLAPSE_EASING.name)
        body_unfold = curve_combo(BODY_CURVES, CollapsibleVariableGroup.BODY_UNFOLD_EASING.name)
        body_fold = curve_combo(BODY_CURVES, CollapsibleVariableGroup.BODY_FOLD_EASING.name)
        overshoot = spin(0.8, 5.0, step=0.25, decimals=2)
        row_ms = spin(group.ROW_ANIMATION_MS, 2000)
        stagger_ms = spin(group.ROW_STAGGER_MS, 300, step=5)
        slide_px = spin(group.ROW_SLIDE_PX, 80, step=2)
        body_ms = spin(group.BODY_FOLD_MS, 2000)
        rows_after = spin(group.ROWS_AFTER_BODY_UNFOLD, 1.0, step=0.1, decimals=2)
        fold_after = spin(group.BODY_FOLD_AFTER_ROW, 1.0, step=0.1, decimals=2)

        def curve(combo):
            easing = Easing(getattr(Easing.Type, combo.currentText()))
            easing.setOvershoot(overshoot.value())  # only Back curves use it
            return easing

        def apply_settings(*_):
            group.ROW_EXPAND_EASING = curve(row_in)
            group.ROW_COLLAPSE_EASING = curve(row_out)
            group.BODY_UNFOLD_EASING = curve(body_unfold)
            group.BODY_FOLD_EASING = curve(body_fold)
            group.ROW_ANIMATION_MS = row_ms.value()
            group.ROW_STAGGER_MS = stagger_ms.value()
            group.ROW_SLIDE_PX = slide_px.value()
            group.BODY_FOLD_MS = body_ms.value()
            group.ROWS_AFTER_BODY_UNFOLD = rows_after.value()
            group.BODY_FOLD_AFTER_ROW = fold_after.value()

        def print_settings():
            print(f"ROW_EXPAND_EASING = {row_in.currentText()}, ROW_COLLAPSE_EASING = {row_out.currentText()}, "
                  f"BODY_UNFOLD_EASING = {body_unfold.currentText()}, BODY_FOLD_EASING = {body_fold.currentText()}, "
                  f"overshoot = {overshoot.value()}, ROW_ANIMATION_MS = {row_ms.value()}, "
                  f"ROW_STAGGER_MS = {stagger_ms.value()}, ROW_SLIDE_PX = {slide_px.value()}, "
                  f"BODY_FOLD_MS = {body_ms.value()}, ROWS_AFTER_BODY_UNFOLD = {rows_after.value()}, "
                  f"BODY_FOLD_AFTER_ROW = {fold_after.value()}")

        tuner = qt.QtWidgets.QWidget()
        form = qt.QtWidgets.QFormLayout(tuner)
        for label, widget in [("Rows in (expand)", row_in), ("Rows out (collapse)", row_out),
                              ("Body unfold", body_unfold), ("Body fold", body_fold),
                              ("Back overshoot", overshoot), ("Row duration, ms", row_ms),
                              ("Row stagger, ms", stagger_ms), ("Row slide, px", slide_px),
                              ("Body duration, ms", body_ms), ("Rows start at unfold", rows_after),
                              ("Fold starts at last row", fold_after)]:
            form.addRow(label, widget)
            signal = getattr(widget, "currentTextChanged", None) or widget.valueChanged
            signal.connect(apply_settings)

        toggle_button = qt.QtWidgets.QPushButton("Toggle")
        toggle_button.clicked.connect(group.toggle_collapsed)
        print_button = qt.QtWidgets.QPushButton("Print settings")
        print_button.clicked.connect(print_settings)
        buttons = qt.QtWidgets.QHBoxLayout()
        buttons.addWidget(toggle_button)
        buttons.addWidget(print_button)
        form.addRow(buttons)
        apply_settings()

        dialog = ThemedWidgetPlaygroundDialog(title="fold animation playground")
        dialog.add_case("Animation settings", tuner)
        dialog.add_case("CollapsibleVariableGroup", group)
        dialog.resize(640, 720)
        dialog.show()
