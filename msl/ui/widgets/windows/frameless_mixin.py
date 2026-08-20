from enum import Enum, auto

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.compositions.window_header import WindowHeader


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
    custom chrome with a WindowHeader that can host arbitrary widgets, plus
    minimize/maximize/restore.

    Mixed into a QDialog or QMainWindow subclass, e.g.:
        class FramelessDialog(FramelessWindowMixin, QtWidgets.QDialog): ...

    Consumers must call `_init_frameless_state()` first (before anything can
    receive mouse events), then `_build_frameless_chrome()` once their own
    root layout exists. Contains no DCC-specific logic.

    The window's own background (behind the header) is custom-painted via
    paintEvent — WA_TranslucentBackground means QSS can't paint the rounded
    shape, so set_background_color() must be called explicitly by the owning
    window's theme handler, same reasoning as WindowHeader.set_theme().
    """

    _EDGE_MARGIN = 6
    _MIN_WIDTH = 240
    _MIN_HEIGHT = 160
    _DEFAULT_CORNER_RADIUS = 10

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

    def _init_frameless_state(self, *, corner_radius: int = _DEFAULT_CORNER_RADIUS) -> None:
        """Call once, first thing in __init__, before any mouse event can fire."""
        self.setWindowFlags(qt.QtCore.Qt.WindowType.FramelessWindowHint)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._drag_position: qt.QtCore.QPoint | None = None
        self._resize_edge = _ResizeEdge.NONE
        self._resize_start_geometry: qt.QtCore.QRect | None = None
        self._resize_start_mouse: qt.QtCore.QPoint | None = None

        self._minimize_button: qt.QtWidgets.QAbstractButton | None = None
        self._maximize_button: qt.QtWidgets.QAbstractButton | None = None
        self._close_button: qt.QtWidgets.QAbstractButton | None = None

        self._corner_radius = corner_radius
        self._background_color = qt.QtGui.QColor("#b07878")  # placeholder until _apply_theme() calls set_background_color

    def set_background_color(self, color) -> None:
        self._background_color = qt.QtGui.QColor(color)
        self.update()

    def _build_frameless_chrome(self, root_layout, title,
                                 *, icon=None, subtitle=None,
                                 show_close_button=True,
                                 show_minimize_button=False,
                                 show_maximize_button=False) -> None:
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

    def add_header_widget(self, widget, *, side: str = "left") -> None:
        if side == "left":
            self.header.add_leading_widget(widget)
        elif side == "right":
            self.header.add_trailing_widget(widget)
        else:
            raise ValueError(f"Unknown header side: {side!r}")

    def set_title(self, title: str) -> None:
        self.header.set_title(title)

    def _toggle_maximize_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._set_corner_radius(self._DEFAULT_CORNER_RADIUS)
        else:
            self.showMaximized()
            self._set_corner_radius(0)
        if self._maximize_button is not None:
            self._maximize_button.set_maximized(self.isMaximized())

    def _set_corner_radius(self, radius: int) -> None:
        if radius == self._corner_radius:
            return
        self._corner_radius = radius
        self.header.set_corner_radius(radius)
        self.update()

    # --- Edge detection for interactive resize ---

    def _edge_at(self, pos: qt.QtCore.QPoint) -> _ResizeEdge:
        if self.isMaximized():
            return _ResizeEdge.NONE
        margin = self._EDGE_MARGIN
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
            if geometry.right() - new_left >= self._MIN_WIDTH:
                geometry.setLeft(new_left)
        if self._resize_edge in (_ResizeEdge.RIGHT, _ResizeEdge.TOP_RIGHT, _ResizeEdge.BOTTOM_RIGHT):
            new_right = geometry.right() + delta.x()
            if new_right - geometry.left() >= self._MIN_WIDTH:
                geometry.setRight(new_right)
        if self._resize_edge in (_ResizeEdge.TOP, _ResizeEdge.TOP_LEFT, _ResizeEdge.TOP_RIGHT):
            new_top = geometry.top() + delta.y()
            if geometry.bottom() - new_top >= self._MIN_HEIGHT:
                geometry.setTop(new_top)
        if self._resize_edge in (_ResizeEdge.BOTTOM, _ResizeEdge.BOTTOM_LEFT, _ResizeEdge.BOTTOM_RIGHT):
            new_bottom = geometry.bottom() + delta.y()
            if new_bottom - geometry.top() >= self._MIN_HEIGHT:
                geometry.setBottom(new_bottom)
        self.setGeometry(geometry)

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
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        if self._resize_edge is not _ResizeEdge.NONE and event.buttons() & qt.QtCore.Qt.MouseButton.LeftButton:
            self._apply_resize(event.globalPosition().toPoint())
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
        path = qt.QtGui.QPainterPath()
        path.addRoundedRect(qt.QtCore.QRectF(self.rect()), self._corner_radius, self._corner_radius)
        painter.fillPath(path, self._background_color)