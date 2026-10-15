# ui/widgets/atoms/gradients/gradient_ramp.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import color_property


class GradientRamp(qt.QtWidgets.QWidget):
    """A color ramp to edit: a bar painted with the gradient its stops make, each stop a small
    handle under it. Click the bar = a new stop there (in the color the bar has there), drag a
    handle = move it, Delete / Backspace = remove the picked stop (one always stays), double click a
    handle = its color in the color dialog. `set_marker(position)` draws a line where a value lies
    now (None = no line); `set_steps(True)` paints the bar in steps — each stop's color holds until
    the next one — as the owner will use it.

    Positions are 0..1 across the bar; colors are the user's data (they are what is edited), only
    the frame, handles and marker take theme colors (qproperty borderColor / handleColor /
    pickedColor / markerColor).

    Signals:
        stops_changed(list) — [(position, QColor), ...] sorted, after any change.
        picked(int) — the index of the stop picked now (in that sorted list; -1 = none).
    """

    stops_changed = qt.QtCore.Signal(list)
    picked = qt.QtCore.Signal(int)

    BAR_HEIGHT = 14
    HANDLE = 9          # a handle's width; it hangs under the bar
    MARGIN = 6          # room at the ends, so the first / last handle is whole

    borderColor = color_property("_border", "update")
    handleColor = color_property("_handle", "update")
    pickedColor = color_property("_picked_color", "update")
    markerColor = color_property("_marker", "update")

    def __init__(self, stops=None, parent=None):
        super().__init__(parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        fallback = ThemeRegistry.fallback()
        self._border = qt.QtGui.QColor(fallback.text_secondary)
        self._handle = qt.QtGui.QColor(fallback.text_primary)
        self._picked_color = qt.QtGui.QColor(fallback.accent)
        self._marker = qt.QtGui.QColor(fallback.text_primary)
        self._stops = []
        self._picked = -1
        self._dragging = -1
        self._marker_at = None
        self._steps = False
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.ClickFocus)
        self.setMinimumHeight(self.BAR_HEIGHT + self.HANDLE + 6)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding, qt.QtWidgets.QSizePolicy.Policy.Fixed)
        self.set_stops(stops or [(0.0, qt.QtGui.QColor("#ffffff")), (1.0, qt.QtGui.QColor("#ffffff"))])

    # --- what it holds

    def stops(self) -> list:
        return [(position, qt.QtGui.QColor(color)) for position, color in self._stops]

    def set_stops(self, stops, emit: bool = False) -> None:
        self._stops = sorted(((min(1.0, max(0.0, float(position))), qt.QtGui.QColor(color))
                              for position, color in stops), key=lambda stop: stop[0])
        if not self._stops:
            self._stops = [(0.0, qt.QtGui.QColor("#ffffff"))]
        self._picked = min(self._picked, len(self._stops) - 1)
        self.update()
        if emit:
            self.stops_changed.emit(self.stops())

    def picked_index(self) -> int:
        return self._picked

    def set_picked_color(self, color) -> None:
        """Gives the picked stop `color` (nothing picked = nothing happens)."""
        if 0 <= self._picked < len(self._stops):
            self._stops[self._picked] = (self._stops[self._picked][0], qt.QtGui.QColor(color))
            self.update()
            self.stops_changed.emit(self.stops())

    def set_marker(self, position) -> None:
        self._marker_at = None if position is None else min(1.0, max(0.0, float(position)))
        self.update()

    def set_steps(self, steps: bool) -> None:
        self._steps = bool(steps)
        self.update()

    def color_at(self, position: float) -> "qt.QtGui.QColor":
        """The bar's color at `position` (as it is painted: blended, or in steps)."""
        stops = self._stops
        if position <= stops[0][0]:
            return qt.QtGui.QColor(stops[0][1])
        for (low, low_color), (high, high_color) in zip(stops, stops[1:]):
            if position < high:
                if self._steps or high <= low:
                    return qt.QtGui.QColor(low_color)
                part = (position - low) / (high - low)
                return qt.QtGui.QColor.fromRgbF(*(a + (b - a) * part for a, b in zip(low_color.getRgbF(),
                                                                                      high_color.getRgbF())))
        return qt.QtGui.QColor(stops[-1][1])

    # --- geometry

    def _bar(self) -> "qt.QtCore.QRectF":
        return qt.QtCore.QRectF(self.MARGIN, 1, self.width() - 2 * self.MARGIN, self.BAR_HEIGHT)

    def _x(self, position: float) -> float:
        bar = self._bar()
        return bar.left() + position * bar.width()

    def _position(self, x: float) -> float:
        bar = self._bar()
        return min(1.0, max(0.0, (x - bar.left()) / max(1.0, bar.width())))

    def _handle_at(self, point) -> int:
        """The stop whose handle (or the bar right above it) is under `point`; -1 = none."""
        best, best_distance = -1, self.HANDLE
        for index, (position, _color) in enumerate(self._stops):
            distance = abs(self._x(position) - point.x())
            if distance <= best_distance and point.y() >= self._bar().bottom() - 3:
                best, best_distance = index, distance
        return best

    # --- painting

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        bar = self._bar()
        if self._steps:
            for index, (position, color) in enumerate(self._stops):
                start = 0.0 if index == 0 else position
                end = self._stops[index + 1][0] if index + 1 < len(self._stops) else 1.0
                painter.fillRect(qt.QtCore.QRectF(self._x(start), bar.top(), self._x(end) - self._x(start),
                                                  bar.height()), color)
        else:
            gradient = qt.QtGui.QLinearGradient(bar.left(), 0, bar.right(), 0)
            for position, color in self._stops:
                gradient.setColorAt(position, color)
            painter.fillRect(bar, gradient)
        painter.setPen(qt.QtGui.QPen(self._border, 1))
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bar.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
        if self._marker_at is not None:
            x = self._x(self._marker_at)
            painter.setPen(qt.QtGui.QPen(self._marker, 2))
            painter.drawLine(qt.QtCore.QPointF(x, bar.top() - 1), qt.QtCore.QPointF(x, bar.bottom() + 1))
        for index, (position, color) in enumerate(self._stops):
            x = self._x(position)
            top = bar.bottom() + 1
            half = self.HANDLE / 2.0
            shape = qt.QtGui.QPolygonF([qt.QtCore.QPointF(x, top), qt.QtCore.QPointF(x + half, top + half),
                                        qt.QtCore.QPointF(x + half, top + self.HANDLE),
                                        qt.QtCore.QPointF(x - half, top + self.HANDLE),
                                        qt.QtCore.QPointF(x - half, top + half)])
            painter.setBrush(color)
            painter.setPen(qt.QtGui.QPen(self._picked_color if index == self._picked else self._handle,
                                         2 if index == self._picked else 1))
            painter.drawPolygon(shape)

    # --- the mouse and the keys

    def _pick(self, index: int) -> None:
        if index != self._picked:
            self._picked = index
            self.update()
            self.picked.emit(index)

    def mousePressEvent(self, event) -> None:
        if event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        point = event.position()
        index = self._handle_at(point)
        if index < 0 and self._bar().adjusted(-2, -2, 2, 2).contains(point):
            position = self._position(point.x())
            self._stops.append((position, self.color_at(position)))
            self._stops.sort(key=lambda stop: stop[0])
            index = next(at for at, stop in enumerate(self._stops) if stop[0] == position)
            self.stops_changed.emit(self.stops())
        self._dragging = index
        self._pick(index)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging < 0:
            return super().mouseMoveEvent(event)
        color = self._stops[self._dragging][1]
        self._stops[self._dragging] = (self._position(event.position().x()), color)
        moved = self._stops[self._dragging]
        self._stops.sort(key=lambda stop: stop[0])
        self._dragging = self._picked = self._stops.index(moved)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging >= 0:
            self._dragging = -1
            self.stops_changed.emit(self.stops())
            self.picked.emit(self._picked)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        index = self._handle_at(event.position())
        if index < 0:
            return super().mouseDoubleClickEvent(event)
        self._pick(index)
        color = qt.QtWidgets.QColorDialog.getColor(self._stops[index][1], self, "Color of this stop")
        if color.isValid():
            self.set_picked_color(color)

    def keyPressEvent(self, event) -> None:
        if (event.key() in (qt.QtCore.Qt.Key.Key_Delete, qt.QtCore.Qt.Key.Key_Backspace)
                and 0 <= self._picked < len(self._stops) and len(self._stops) > 1):
            del self._stops[self._picked]
            self._pick(min(self._picked, len(self._stops) - 1))
            self.update()
            self.stops_changed.emit(self.stops())
            return
        super().keyPressEvent(event)

    def sizeHint(self) -> "qt.QtCore.QSize":
        return qt.QtCore.QSize(200, self.BAR_HEIGHT + self.HANDLE + 6)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        ramp = GradientRamp([(0.0, qt.QtGui.QColor("#3388ff")), (0.5, qt.QtGui.QColor("#ffd23f")),
                             (1.0, qt.QtGui.QColor("#e2483f"))])
        ramp.set_marker(0.3)
        dialog.add_case("blended, a marker at 0.3", ramp)
        steps = GradientRamp([(0.0, qt.QtGui.QColor("#ffffff")), (0.6, qt.QtGui.QColor("#e2483f"))])
        steps.set_steps(True)
        dialog.add_case("in steps", steps)
        dialog.show()
