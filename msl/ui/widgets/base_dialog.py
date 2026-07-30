import msl_tools.msl.ui.qt_bindings as qt


class BaseDialog(qt.QtWidgets.QDialog):
    """Base dialog for the widget library. Provides a content_layout for subclasses
    to extend and an optional bottom button row. Contains no DCC-specific logic —
    parenting to Maya (or any host) is done by the caller when instantiating."""

    def __init__(self, title:str = "", width:int = 480, height:int = 320, show_close_button: bool = True, parent = None):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.resize(width, height)

        self._create_layouts()
        if show_close_button:
            self._build_button_row()

    def _create_layouts(self):
        self.main_layout = qt.QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(2)

        self.content_layout = qt.QtWidgets.QVBoxLayout()
        self.content_layout.setSpacing(2)

        self.main_layout.addLayout(self.content_layout)
        self.main_layout.addStretch()


    def _build_button_row(self) -> None:
        row = qt.QtWidgets.QHBoxLayout()
        row.addStretch()

        self.close_button = qt.QtWidgets.QPushButton("close")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)

        self.main_layout.addLayout(row)

    def add_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        """Adds a widget to the content zone. Primary way for subclasses to populate the dialog."""
        self.content_layout.addWidget(widget)

    def add_separator(self) -> None:
        """Adds a horizontal separator line to the content zone."""
        line = qt.QtWidgets.QFrame()
        line.setFrameShape(qt.QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet("color: gray;")
        self.content_layout.addWidget(line)


# ui/widgets/base_dialog.py
# ui/widgets/base_dialog.py

from enum import Enum, auto




class _ResizeEdge(Enum):
    NONE = auto()
    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()
    TOP_LEFT = auto()
    TOP_RIGHT = auto()
    BOTTOM_LEFT = auto()
    BOTTOM_RIGHT = auto()


class BaseDialog2(qt.QtWidgets.QDialog):
    """Base dialog for the widget library. Frameless, with a custom title bar
    instead of the native one — allows embedding widgets into the header
    (e.g. a theme switcher) alongside the centered title and close button.
    The header is draggable to move the window, and the window edges support
    interactive resizing, since the native title bar and frame are gone.
    Contains no DCC-specific logic — parenting to Maya (or any host) is done
    by the caller when instantiating.
    """

    _EDGE_MARGIN = 6
    _MIN_WIDTH = 240
    _MIN_HEIGHT = 160

    _CURSOR_BY_EDGE = {
        _ResizeEdge.LEFT: qt.QtCore.Qt.CursorShape.SizeHorCursor,
        _ResizeEdge.RIGHT: qt.QtCore.Qt.CursorShape.SizeHorCursor,
        _ResizeEdge.TOP: qt.QtCore.Qt.CursorShape.SizeVerCursor,
        _ResizeEdge.BOTTOM: qt.QtCore.Qt.CursorShape.SizeVerCursor,
        _ResizeEdge.TOP_LEFT: qt.QtCore.Qt.CursorShape.SizeFDiagCursor,
        _ResizeEdge.BOTTOM_RIGHT: qt.QtCore.Qt.CursorShape.SizeFDiagCursor,
        _ResizeEdge.TOP_RIGHT: qt.QtCore.Qt.CursorShape.SizeBDiagCursor,
        _ResizeEdge.BOTTOM_LEFT: qt.QtCore.Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self,
                 *,
                 title: str = "",
                 width: int = 480,
                 height: int = 320,
                 show_close_button: bool = True,
                 parent=None):

        super().__init__(parent)

        self.setWindowFlags(qt.QtCore.Qt.WindowType.FramelessWindowHint)
        self.setMouseTracking(True)
        self.resize(width, height)

        self._drag_position: qt.QtCore.QPoint | None = None
        self._resize_edge = _ResizeEdge.NONE
        self._resize_start_geometry: qt.QtCore.QRect | None = None
        self._resize_start_mouse: qt.QtCore.QPoint | None = None

        self._build_base_ui(title, show_close_button)

    def _build_base_ui(self, title: str, show_close_button: bool) -> None:
        self._root_layout = qt.QtWidgets.QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._build_header(title, show_close_button)

        self.content_layout = qt.QtWidgets.QVBoxLayout()
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(12)
        self._root_layout.addLayout(self.content_layout)

        self._root_layout.addStretch()

    def _build_header(self, title: str, show_close_button: bool) -> None:
        self.header_widget = qt.QtWidgets.QWidget()
        self.header_widget.setFixedHeight(36)
        self.header_widget.setStyleSheet("background-color: #2b2b2b;")
        self.header_widget.setMouseTracking(True)

        header_layout = qt.QtWidgets.QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(8, 0, 8, 0)
        header_layout.setSpacing(6)

        self.header_left_layout = qt.QtWidgets.QHBoxLayout()
        self.header_left_layout.setSpacing(6)

        self.title_label = qt.QtWidgets.QLabel(title)
        self.title_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("color: white; font-weight: 500;")

        self.header_right_layout = qt.QtWidgets.QHBoxLayout()
        self.header_right_layout.setSpacing(6)

        if show_close_button:
            self.close_button = qt.QtWidgets.QPushButton("×")
            self.close_button.setFixedSize(24, 24)
            self.close_button.setStyleSheet("color: white; border: none; font-size: 16px;")
            self.close_button.clicked.connect(self.close)
            self.header_right_layout.addWidget(self.close_button)

        header_layout.addLayout(self.header_left_layout)
        header_layout.addStretch()
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addLayout(self.header_right_layout)

        self._root_layout.addWidget(self.header_widget)

    def add_header_widget(self, widget: qt.QtWidgets.QWidget, *, side: str = "left") -> None:
        """Adds a widget to the header. side is 'left' (before the title) or
        'right' (after the title, before the close button)."""
        if side == "left":
            self.header_left_layout.addWidget(widget)
        elif side == "right":
            self.header_right_layout.insertWidget(0, widget)
        else:
            raise ValueError(f"Unknown header side: {side!r}")

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def add_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        """Adds a widget to the content zone. Primary way for subclasses to populate the dialog."""
        self.content_layout.addWidget(widget)

    def add_separator(self) -> None:
        """Adds a horizontal separator line to the content zone."""
        line = qt.QtWidgets.QFrame()
        line.setFrameShape(qt.QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet("color: gray;")
        self.content_layout.addWidget(line)

    # --- Edge detection for interactive resize ---

    def _edge_at(self, pos: qt.QtCore.QPoint) -> _ResizeEdge:
        margin = self._EDGE_MARGIN
        rect = self.rect()

        on_left = pos.x() <= margin
        on_right = pos.x() >= rect.width() - margin
        on_top = pos.y() <= margin
        on_bottom = pos.y() >= rect.height() - margin

        if on_top and on_left:
            return _ResizeEdge.TOP_LEFT
        if on_top and on_right:
            return _ResizeEdge.TOP_RIGHT
        if on_bottom and on_left:
            return _ResizeEdge.BOTTOM_LEFT
        if on_bottom and on_right:
            return _ResizeEdge.BOTTOM_RIGHT
        if on_left:
            return _ResizeEdge.LEFT
        if on_right:
            return _ResizeEdge.RIGHT
        if on_top:
            return _ResizeEdge.TOP
        if on_bottom:
            return _ResizeEdge.BOTTOM
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

    # --- Mouse events: resize takes priority over header drag ---

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

        if self.header_widget.geometry().contains(pos):
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

        # No button held — just update the cursor shape when hovering an edge
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


if __name__ == '__main__':

    from msl_tools.msl.ui.app.application_context import QtApplicationContext


    with QtApplicationContext():
        window = BaseDialog(title="BaseDialog")
        window.add_widget(qt.QtWidgets.QPushButton("test"))
        window.add_widget(qt.QtWidgets.QPushButton("test2"))
        window.add_separator()
        window.show()