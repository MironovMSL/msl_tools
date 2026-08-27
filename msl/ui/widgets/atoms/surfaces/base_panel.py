import msl_tools.msl.ui.qt_bindings as qt

class BasePanel(qt.QtWidgets.QWidget):
    """Rounded, filled container atom for grouping content into a visual
    'card'. Owns its own internal layout — callers add content via
    content_layout(), not by placing widgets in the parent's layout,
    so children actually sit inside the painted rounded rect."""

    def __init__(self, corner_radius: int = 8, parent=None):
        super().__init__(parent)
        self._corner_radius = corner_radius
        self._background_color = qt.QtGui.QColor("#2a2d34")
        self._border_color: qt.QtGui.QColor | None = None

        # self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding, qt.QtWidgets.QSizePolicy.Policy.Expanding)

        self._layout = qt.QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(5)

    def content_layout(self) -> qt.QtWidgets.QVBoxLayout:
        return self._layout

    def set_background_color(self, color) -> None:
        self._background_color = qt.QtGui.QColor(color)
        self.update()

    def set_border_color(self, color) -> None:
        self._border_color = qt.QtGui.QColor(color) if color else None
        self.update()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        path = qt.QtGui.QPainterPath()
        rect = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path.addRoundedRect(rect, self._corner_radius, self._corner_radius)

        painter.fillPath(path, self._background_color)
        if self._border_color is not None:
            pen = qt.QtGui.QPen(self._border_color)
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)