import msl_tools.msl.ui.qt_bindings as qt
from enum import Enum, auto
from msl_tools.msl.ui.widgets.compositions.window_header import WindowHeader
from msl_tools.msl.ui.widgets.windows.snap_layout_flyout import SnapLayoutFlyout


class _ResizeEdge(Enum):
    NONE         = auto()
    LEFT         = auto()
    RIGHT        = auto()
    TOP          = auto()
    BOTTOM       = auto()
    TOP_LEFT     = auto()
    TOP_RIGHT    = auto()
    BOTTOM_LEFT  = auto()
    BOTTOM_RIGHT = auto()


class FramelessWindowMixin:
    """Shared behavior for frameless top-level windows: draggable/resizable
    custom chrome with a WindowHeader that can host arbitrary widgets,
    minimize/maximize/restore with animated transitions, Windows
    11-style Snap Layouts, and interactive edge/corner resize.
    """

    _EDGE_MARGIN           = 6
    _OUTER_MARGIN          = 6
    _MIN_WIDTH             = 240
    _MIN_HEIGHT            = 160
    _DEFAULT_CORNER_RADIUS = 10
    _HIT_TEST_ALPHA        = 1
    _ANIMATION_DURATION_MS = 180
    _ANIMATION_EASING      = qt.QtCore.QEasingCurve.Type.OutCubic

    _CURSOR_BY_EDGE = {
        _ResizeEdge.LEFT        : qt.QtCore.Qt.CursorShape.SizeHorCursor,
        _ResizeEdge.RIGHT       : qt.QtCore.Qt.CursorShape.SizeHorCursor,
        _ResizeEdge.TOP         : qt.QtCore.Qt.CursorShape.SizeVerCursor,
        _ResizeEdge.BOTTOM      : qt.QtCore.Qt.CursorShape.SizeVerCursor,
        _ResizeEdge.TOP_LEFT    : qt.QtCore.Qt.CursorShape.SizeFDiagCursor,
        _ResizeEdge.BOTTOM_RIGHT: qt.QtCore.Qt.CursorShape.SizeFDiagCursor,
        _ResizeEdge.TOP_RIGHT   : qt.QtCore.Qt.CursorShape.SizeBDiagCursor,
        _ResizeEdge.BOTTOM_LEFT : qt.QtCore.Qt.CursorShape.SizeBDiagCursor,
    }

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_frameless_state(self,
                              corner_radius: int = _DEFAULT_CORNER_RADIUS,
                              outer_margin:  int = _OUTER_MARGIN) -> None:

        """Call once, first thing in __init__, before any mouse event can fire."""
        self.setWindowFlags(qt.QtCore.Qt.WindowType.FramelessWindowHint)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._drag_position:              qt.QtCore.QPoint | None = None
        self._arranged_drag_press_global: qt.QtCore.QPoint | None = None
        self._arranged_drag_press_local:  qt.QtCore.QPoint | None = None

        self._resize_edge = _ResizeEdge.NONE
        self._resize_start_geometry: qt.QtCore.QRect  | None = None
        self._resize_start_mouse:    qt.QtCore.QPoint | None = None

        self._minimize_button: qt.QtWidgets.QAbstractButton | None = None
        self._maximize_button: qt.QtWidgets.QAbstractButton | None = None
        self._close_button:    qt.QtWidgets.QAbstractButton | None = None

        self._is_pseudo_maximized = False
        self._normal_geometry:    qt.QtCore.QRect              | None = None
        self._maximize_animation: qt.QtCore.QPropertyAnimation | None = None

        self._corner_radius = corner_radius
        self._outer_margin_normal = outer_margin   # restored on un-maximize
        self._outer_margin = outer_margin
        self._root_layout: qt.QtWidgets.QLayout | None = None
        self._background_color = qt.QtGui.QColor("#b07878")

        self._is_snapped = False
        self._snap_flyout: SnapLayoutFlyout | None = None
        self._snap_flyout_timer = qt.QtCore.QTimer(self)
        self._snap_flyout_timer.setSingleShot(True)
        self._snap_flyout_timer.setInterval(500)  # matches native Win11 hover delay
        self._snap_flyout_timer.timeout.connect(self._show_snap_flyout)
        self._snap_flyout_colors: tuple | None = None

    # ------------------------------------------------------------------
    # Simple public accessors
    # ------------------------------------------------------------------

    def content_margins(self) -> tuple[int, int, int, int]:
        m = self._outer_margin
        return (m, m, m, m)

    def set_background_color(self, color) -> None:
        self._background_color = qt.QtGui.QColor(color)
        self.update()

    def isMaximized(self) -> bool:
        return self._is_pseudo_maximized

    # ------------------------------------------------------------------
    # Chrome construction
    # ------------------------------------------------------------------

    def _build_frameless_chrome(self, root_layout, title,
                                 icon=None, subtitle=None,
                                 show_close_button=True,
                                 show_minimize_button=False,
                                 show_maximize_button=False) -> None:

        self._root_layout = root_layout

        self.header = WindowHeader(title=title)
        self.header.set_corner_radius(self._corner_radius)

        if icon is not None:
            self.header.set_icon(icon)
        if subtitle is not None:
            self.header.set_subtitle(subtitle)

        if show_minimize_button and show_maximize_button:
            self._minimize_button, self._maximize_button, self._close_button = (
                self.header.add_window_controls(
                    minimize_slot=self.showMinimized,
                    maximize_slot=self._toggle_maximize_restore,
                    close_slot=self.close,
                )
            )
        elif show_minimize_button:
            self._minimize_button, self._close_button = (
                self.header.add_close_minimize_controls(
                    minimize_slot=self.showMinimized,
                    close_slot=self.close,
                )
            )
        elif show_close_button:
            self._close_button = self.header.add_close_only_controls(self.close)

        root_layout.addWidget(self.header)

        if self._maximize_button is not None:
            self._maximize_button.installEventFilter(self)

    def add_header_widget(self, widget, side: str = "left") -> None:
        if side == "left":
            self.header.add_leading_widget(widget)
        elif side == "right":
            self.header.add_trailing_widget(widget)
        else:
            raise ValueError(f"Unknown header side: {side!r}")

    def set_title(self, title: str) -> None:
        self.header.set_title(title)

    # ------------------------------------------------------------------
    # Corner radius / outer margin
    # ------------------------------------------------------------------

    def _set_corner_radius(self, radius: int) -> None:
        if radius == self._corner_radius:
            return
        self._corner_radius = radius
        self.header.set_corner_radius(radius)
        self.update()

    def _set_outer_margin(self, margin: int) -> None:
        if margin == self._outer_margin:
            return
        self._outer_margin = margin
        if self._root_layout is not None:
            self._root_layout.setContentsMargins(*self.content_margins())
        self.update()

    # ------------------------------------------------------------------
    # Maximize / restore / snap state machine
    # ------------------------------------------------------------------

    def _toggle_maximize_restore(self) -> None:
        if self._is_pseudo_maximized:
            self._animate_to_restored()
        else:
            self._animate_to_maximized()

    def _animate_to_maximized(self) -> None:
        self._capture_normal_geometry_if_needed()
        target_rect = self._maximized_target_geometry()

        self._is_pseudo_maximized = True
        self._is_snapped = False
        if self._maximize_button is not None:
            self._maximize_button.set_maximized(True)

        self._set_corner_radius(0)
        self._set_outer_margin(0)
        self._run_geometry_animation(self.geometry(), target_rect)

    def _animate_to_restored(self) -> None:
        target_rect = self._normal_geometry or self._default_restore_geometry()
        self._normal_geometry = None

        self._is_pseudo_maximized = False
        self._is_snapped = False
        if self._maximize_button is not None:
            self._maximize_button.set_maximized(False)

        def _on_finished() -> None:
            self._set_corner_radius(self._DEFAULT_CORNER_RADIUS)
            self._set_outer_margin(self._outer_margin_normal)

        self._run_geometry_animation(self.geometry(), target_rect, on_finished=_on_finished)

    def _capture_normal_geometry_if_needed(self) -> None:
        if self._normal_geometry is None and not self._is_pseudo_maximized and not self._is_snapped:
            self._normal_geometry = self.geometry()

    def _maximized_target_geometry(self) -> qt.QtCore.QRect:
        screen = self.screen() or qt.QtWidgets.QApplication.primaryScreen()
        return screen.availableGeometry()

    def _default_restore_geometry(self) -> qt.QtCore.QRect:
        """Fallback if _normal_geometry was never captured (e.g. window
        somehow starts out pseudo-maximized)."""
        return self.geometry()

    def _restore_from_arranged_drag(self, press_local: qt.QtCore.QPoint, global_pos: qt.QtCore.QPoint) -> None:
        """Tear a maximized OR zone-snapped window off the moment a header
        drag actually starts, re-anchoring it so the cursor stays over the
        same relative point on the header (matches native OS "tear off"
        behavior for both maximize and Snap). Stays instant (no easing
        animation) since the drag gesture itself already drives the motion
        frame by frame."""
        self._stop_maximize_animation()

        current_width = self.width()
        ratio_x = press_local.x() / current_width if current_width else 0.0

        self._is_pseudo_maximized = False
        self._is_snapped = False
        if self._maximize_button is not None:
            self._maximize_button.set_maximized(False)

        self._set_corner_radius(self._DEFAULT_CORNER_RADIUS)
        self._set_outer_margin(self._outer_margin_normal)

        target_size = self._normal_geometry.size() if self._normal_geometry is not None else self.size()
        self._normal_geometry = None
        restored_width, restored_height = target_size.width(), target_size.height()

        new_x = global_pos.x() - int(ratio_x * restored_width)
        new_y = global_pos.y() - press_local.y()
        self.setGeometry(new_x, new_y, restored_width, restored_height)

        self._drag_position = global_pos - self.frameGeometry().topLeft()

    # ------------------------------------------------------------------
    # Snap Layouts flyout
    # ------------------------------------------------------------------

    def _show_snap_flyout(self) -> None:
        if self._maximize_button is None:
            return
        if self._maximize_button.isDown():
            # Defensive: shouldn't normally reach here since MouseButtonPress
            # already cancels the timer in eventFilter, but never open the
            # flyout mid-press regardless of how we got here.
            return
        if self._snap_flyout is None:
            self._snap_flyout = SnapLayoutFlyout(parent=self)
            self._snap_flyout.zone_chosen.connect(self._snap_to_zone)
            if self._snap_flyout_colors is not None:
                self._snap_flyout.set_theme_colors(*self._snap_flyout_colors)
        self._snap_flyout.show_near(self._maximize_button)

    def _snap_to_zone(self, zone_fractions: tuple[float, float, float, float]) -> None:
        screen = self.screen() or qt.QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry()
        x_frac, y_frac, w_frac, h_frac = zone_fractions

        target_rect = qt.QtCore.QRect(
            available.x() + round(x_frac * available.width()),
            available.y() + round(y_frac * available.height()),
            round(w_frac * available.width()),
            round(h_frac * available.height()),
        )

        self._capture_normal_geometry_if_needed()

        self._is_pseudo_maximized = False
        self._is_snapped = True
        if self._maximize_button is not None:
            self._maximize_button.set_maximized(False)

        # Unlike full maximize, a zone-snapped window keeps its normal rounded
        # corners and outer margin — it's still a regular floating window,
        # just resized/repositioned to a screen zone, not a flush edge-to-edge
        # maximize.
        self._run_geometry_animation(self.geometry(), target_rect)

    def apply_snap_flyout_theme(self, background, border, zone_idle, zone_hover, zone_pressed,
                                 zone_border, zone_border_pressed=None) -> None:
        """Called by the host window's _apply_theme() so the flyout (if
        currently instantiated) picks up new colors immediately, and so
        colors computed before the flyout's first lazy creation aren't
        lost."""
        self._snap_flyout_colors = (background, border, zone_idle, zone_hover, zone_pressed,
                                     zone_border, zone_border_pressed)
        if self._snap_flyout is not None:
            self._snap_flyout.set_theme_colors(*self._snap_flyout_colors)

    # ------------------------------------------------------------------
    # Shared geometry animation engine (maximize / restore / snap all use this)
    # ------------------------------------------------------------------

    def _run_geometry_animation(self, start_rect, end_rect, on_finished=None) -> None:
        self._stop_maximize_animation()

        animation = qt.QtCore.QPropertyAnimation(self, b"geometry", self)
        animation.setDuration(self._ANIMATION_DURATION_MS)
        animation.setEasingCurve(self._ANIMATION_EASING)
        animation.setStartValue(start_rect)
        animation.setEndValue(end_rect)

        animation.finished.connect(self._clear_maximize_animation_ref)
        if on_finished is not None:
            animation.finished.connect(on_finished)

        self._maximize_animation = animation
        animation.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _clear_maximize_animation_ref(self) -> None:
        self._maximize_animation = None

    def _stop_maximize_animation(self) -> None:
        animation = self._maximize_animation
        self._maximize_animation = None
        if animation is not None and qt.shiboken.isValid(animation):
            animation.stop()

    # ------------------------------------------------------------------
    # Interactive edge/corner resize
    # ------------------------------------------------------------------

    def _resize_to_visible_size(self, width: int, height: int) -> None:
        self.resize(width + 2 * self._outer_margin, height + 2 * self._outer_margin)

    def _edge_at(self, pos: qt.QtCore.QPoint) -> _ResizeEdge:
        if self.isMaximized():
            return _ResizeEdge.NONE
        margin = self._outer_margin + self._EDGE_MARGIN   # <-- band now extends outward too
        rect = self.rect()
        on_left = pos.x() <= margin
        on_right = pos.x() >= rect.width() - margin
        on_top = pos.y() <= margin
        on_bottom = pos.y() >= rect.height() - margin
        if on_top and on_left: return _ResizeEdge.TOP_LEFT
        if on_top and on_right: return _ResizeEdge.TOP_RIGHT
        if on_bottom and on_left: return _ResizeEdge.BOTTOM_LEFT
        if on_bottom and on_right: return _ResizeEdge.BOTTOM_RIGHT
        if on_left: return _ResizeEdge.LEFT
        if on_right: return _ResizeEdge.RIGHT
        if on_top: return _ResizeEdge.TOP
        if on_bottom: return _ResizeEdge.BOTTOM
        return _ResizeEdge.NONE

    def _apply_resize(self, global_pos: qt.QtCore.QPoint) -> None:
        if self._resize_start_geometry is None or self._resize_start_mouse is None:
            return
        delta = global_pos - self._resize_start_mouse
        geometry = qt.QtCore.QRect(self._resize_start_geometry)

        if self._resize_edge in (_ResizeEdge.LEFT, _ResizeEdge.TOP_LEFT, _ResizeEdge.BOTTOM_LEFT):
            new_left = geometry.left() + delta.x()
            geometry.setLeft(min(new_left, geometry.right() - self._MIN_WIDTH))
        if self._resize_edge in (_ResizeEdge.RIGHT, _ResizeEdge.TOP_RIGHT, _ResizeEdge.BOTTOM_RIGHT):
            new_right = geometry.right() + delta.x()
            geometry.setRight(max(new_right, geometry.left() + self._MIN_WIDTH))
        if self._resize_edge in (_ResizeEdge.TOP, _ResizeEdge.TOP_LEFT, _ResizeEdge.TOP_RIGHT):
            new_top = geometry.top() + delta.y()
            geometry.setTop(min(new_top, geometry.bottom() - self._MIN_HEIGHT))
        if self._resize_edge in (_ResizeEdge.BOTTOM, _ResizeEdge.BOTTOM_LEFT, _ResizeEdge.BOTTOM_RIGHT):
            new_bottom = geometry.bottom() + delta.y()
            geometry.setBottom(max(new_bottom, geometry.top() + self._MIN_HEIGHT))

        self.setGeometry(geometry)

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:
        if watched is self._maximize_button:
            event_type = event.type()
            if event_type == qt.QtCore.QEvent.Type.Enter:
                self._snap_flyout_timer.start()
            elif event_type == qt.QtCore.QEvent.Type.Leave:
                self._snap_flyout_timer.stop()
            elif event_type == qt.QtCore.QEvent.Type.MouseButtonPress:
                # A click must always resolve as an immediate, uninterrupted
                # maximize/restore via the button's own press+release cycle.
                # Never let the flyout's timer fire mid-press — Qt.WindowType.Popup
                # implicitly grabs the pointer on show(), which would swallow
                # the button's mouseReleaseEvent and leave it stuck showing a
                # pressed/hover state forever (clicked never fires either).
                self._snap_flyout_timer.stop()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        if event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        edge = self._edge_at(pos)
        if edge is not _ResizeEdge.NONE:
            self._resize_edge = edge
            self._resize_start_geometry = self.geometry()
            self._resize_start_mouse = event.globalPosition().toPoint()
            event.accept()
            return
        if self.header.geometry().contains(pos):
            if self._maximize_button is not None and (self.isMaximized() or self._is_snapped):
                self._arranged_drag_press_global = event.globalPosition().toPoint()
                self._arranged_drag_press_local = pos
            else:
                self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        if self._resize_edge is not _ResizeEdge.NONE and event.buttons() & qt.QtCore.Qt.MouseButton.LeftButton:
            self._apply_resize(event.globalPosition().toPoint())
            event.accept()
            return

        if (self._maximize_button is not None
                and self._arranged_drag_press_global is not None
                and event.buttons() & qt.QtCore.Qt.MouseButton.LeftButton):

            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self._arranged_drag_press_global
            if delta.manhattanLength() >= qt.QtWidgets.QApplication.startDragDistance():
                self._restore_from_arranged_drag(self._arranged_drag_press_local, global_pos)
                self._arranged_drag_press_global = None
                self._arranged_drag_press_local = None
            event.accept()
            return

        if self._drag_position is not None and event.buttons() & qt.QtCore.Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
            return
        if not event.buttons():
            edge = self._edge_at(event.position().toPoint())
            self.setCursor(self._CURSOR_BY_EDGE.get(edge, qt.QtCore.Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        self._drag_position = None
        self._arranged_drag_press_global = None
        self._arranged_drag_press_local = None
        self._resize_edge = _ResizeEdge.NONE
        self._resize_start_geometry = None
        self._resize_start_mouse = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        if (event.button() == qt.QtCore.Qt.MouseButton.LeftButton
                and self._maximize_button is not None
                and self.header.geometry().contains(event.position().toPoint())):

            self._toggle_maximize_restore()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event: qt.QtGui.QPaintEvent) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), qt.QtGui.QColor(0, 0, 0, self._HIT_TEST_ALPHA))

        path = qt.QtGui.QPainterPath()
        inner_rect = qt.QtCore.QRectF(self.rect()).adjusted(self._outer_margin, self._outer_margin, -self._outer_margin, -self._outer_margin)
        path.addRoundedRect(inner_rect, self._corner_radius, self._corner_radius)
        painter.fillPath(path, self._background_color)