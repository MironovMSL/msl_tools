# tools/maya/controls/widgets.py
"""Small widgets of the Controls tool."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import color_property


class DragNumberField(qt.QtWidgets.QLineEdit):
    """A number field that is also a slider: drag it left / right with the MIDDLE mouse button
    (Maya's own gesture for a channel), the wheel or Up / Down step it (Shift: ten times),
    a double click puts the starting value back.

    Signals:
        value_changed(float)
    """

    value_changed = qt.QtCore.Signal(float)

    def __init__(self, value: float, minimum: float, maximum: float, step: float, width: int = 52,
                 decimals: int = 2, parent=None):
        super().__init__(parent)
        self._minimum, self._maximum, self._step, self._decimals = minimum, maximum, step, decimals
        self._default = value
        self._value = value
        self._drag = None
        self.setFixedWidth(width)
        self.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        validator = qt.QtGui.QDoubleValidator(minimum, maximum, decimals, self)
        validator.setNotation(qt.QtGui.QDoubleValidator.Notation.StandardNotation)
        self.setValidator(validator)
        self._show()
        self.editingFinished.connect(self._take_text)

    def value(self) -> float:
        return self._value

    def set_value(self, value: float, emit: bool = False) -> None:
        value = round(max(self._minimum, min(self._maximum, float(value))), self._decimals)
        changed = value != self._value
        self._value = value
        self._show()
        if emit and changed:
            self.value_changed.emit(value)

    def _show(self) -> None:
        text = f"{self._value:.{self._decimals}f}".rstrip("0").rstrip(".")
        if self.text() != text:
            self.setText(text)

    def _take_text(self) -> None:
        try:
            self.set_value(float(self.text().replace(",", ".")), emit=True)
        except ValueError:
            self._show()

    def _nudge(self, steps: float) -> None:
        big = qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier
        self.set_value(self._value + steps * self._step * (10 if big else 1), emit=True)

    def keyPressEvent(self, event) -> None:
        if event.key() == qt.QtCore.Qt.Key.Key_Up:
            self._nudge(1)
        elif event.key() == qt.QtCore.Qt.Key.Key_Down:
            self._nudge(-1)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        self._nudge(1 if event.angleDelta().y() > 0 else -1)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.MiddleButton:
            self._drag = (event.position().x(), self._value)
            self.setCursor(qt.QtCore.Qt.CursorShape.SizeHorCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            start, value = self._drag
            self.set_value(value + (event.position().x() - start) / 4.0 * self._step, emit=True)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is not None and event.button() == qt.QtCore.Qt.MouseButton.MiddleButton:
            self._drag = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.set_value(self._default, emit=True)


class TurnButton(qt.QtWidgets.QPushButton):
    """"Turn about this axis": a turning arrow around the axis' letter, both in the axis' color
    (qproperty axisColor, set by the `axis` property in controls.qss); the frame is the button's QSS."""

    axisColor = color_property("_axis_color", "update")
    hovered = qt.QtCore.Signal(bool)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hovered.emit(False)

    def __init__(self, axis: str, tooltip: str = "", parent=None):
        super().__init__("", parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        self._axis_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)
        self._axis = axis
        self.setProperty("axis", axis)
        self.setToolTip(tooltip)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        import math
        super().paintEvent(event)
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        center = qt.QtCore.QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = min(self.width(), self.height()) / 2.0 - 3.5
        ring = qt.QtCore.QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        pen = qt.QtGui.QPen(self._axis_color, 1.4)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        start, span = 115.0, -300.0                     # clockwise, a gap at the top left
        painter.drawArc(ring, int(start * 16), int(span * 16))
        end = math.radians(start + span)
        tip = qt.QtCore.QPointF(center.x() + math.cos(end) * radius, center.y() - math.sin(end) * radius)
        heading = math.atan2(math.cos(end), math.sin(end))     # the way the arc runs at its end (screen)
        for side in (-0.6, 0.6):
            back = heading + math.pi + side
            painter.drawLine(tip, qt.QtCore.QPointF(tip.x() + math.cos(back) * 3.4, tip.y() + math.sin(back) * 3.4))
        font = painter.font()
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(ring, qt.QtCore.Qt.AlignmentFlag.AlignCenter, self._axis)
        painter.end()


class Swatches(qt.QtWidgets.QWidget):
    """Colors as small squares in rows: Maya's index palette, the user's saved colors. The colors
    are the scene's (data), only the ring under the pointer / around the current one comes from
    QSS (qproperty ringColor). A swatch whose color is None is "none": a diagonal line.

    Signals:
        clicked(str) — a swatch's key.
        menu_requested(str, QPoint) — a right click on one (global position).
        hovered(str) — the swatch under the pointer ("" = none).
    """

    clicked = qt.QtCore.Signal(str)
    menu_requested = qt.QtCore.Signal(str, qt.QtCore.QPoint)
    hovered = qt.QtCore.Signal(str)

    ringColor = color_property("_ring", "update")      # under the pointer, around the current one
    edgeColor = color_property("_edge", "update")      # a thin edge, so a dark swatch reads on the ground

    def __init__(self, side: int = 16, gap: int = 2, columns: int = 16, parent=None):
        super().__init__(parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        fallback = ThemeRegistry.fallback()
        self._ring = qt.QtGui.QColor(fallback.accent)
        self._edge = qt.QtGui.QColor(fallback.border)
        self._side, self._gap, self._columns = side, gap, columns
        self._items = []          # (key, QColor | None, tooltip)
        self._hover = -1
        self._current = ""
        self.setMouseTracking(True)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def set_items(self, items: list) -> None:
        """[(key, (r, g, b) 0..1 or None, tooltip)]"""
        self._items = [(key, qt.QtGui.QColor.fromRgbF(*rgb[:3]) if rgb is not None else None, tip)
                       for key, rgb, tip in items]
        self.updateGeometry()
        self.update()

    def set_current(self, key: str) -> None:
        if key != self._current:
            self._current = key
            self.update()

    def _rows(self) -> int:
        return max(1, (len(self._items) + self._columns - 1) // self._columns)

    def sizeHint(self) -> "qt.QtCore.QSize":
        columns = min(self._columns, max(1, len(self._items)))
        step = self._side + self._gap
        return qt.QtCore.QSize(columns * step - self._gap + 2, self._rows() * step - self._gap + 2)

    def minimumSizeHint(self) -> "qt.QtCore.QSize":
        return self.sizeHint()

    def _rect(self, index: int) -> "qt.QtCore.QRectF":
        step = self._side + self._gap
        return qt.QtCore.QRectF(1 + (index % self._columns) * step, 1 + (index // self._columns) * step,
                                self._side, self._side)

    def _at(self, point) -> int:
        for index in range(len(self._items)):
            if self._rect(index).contains(point):
                return index
        return -1

    def mouseMoveEvent(self, event) -> None:
        index = self._at(event.position())
        if index != self._hover:
            self._hover = index
            self.setToolTip(self._items[index][2] if index >= 0 else "")
            self.hovered.emit(self._items[index][0] if index >= 0 else "")
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hover != -1:
            self._hover = -1
            self.hovered.emit("")
            self.update()

    def mousePressEvent(self, event) -> None:
        index = self._at(event.position())
        if index < 0:
            return
        key = self._items[index][0]
        if event.button() == qt.QtCore.Qt.MouseButton.RightButton:
            self.menu_requested.emit(key, event.globalPosition().toPoint())
        elif event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(key)

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        for index, (key, color, _tip) in enumerate(self._items):
            rect = self._rect(index)
            painter.setPen(qt.QtGui.QPen(self._edge, 1))
            painter.setBrush(color if color is not None else qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            if color is None:      # "none": a line across
                painter.setPen(qt.QtGui.QPen(self._ring, 1.2))
                painter.drawLine(rect.bottomLeft() + qt.QtCore.QPointF(3, -3), rect.topRight() + qt.QtCore.QPointF(-3, 3))
            if index == self._hover or key == self._current:
                painter.setPen(qt.QtGui.QPen(self._ring, 2 if key == self._current else 1.5))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), 3.5, 3.5)
        painter.end()
