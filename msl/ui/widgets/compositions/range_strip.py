# ui/widgets/compositions/range_strip.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class RangeStrip(qt.QtWidgets.QWidget):
    """A strip of pictures laid side by side (the frames of a video, left to
    right) with a RANGE picked on it: two handles are dragged, what lies
    outside them is dimmed. For choosing a piece of something by eye.

        strip = RangeStrip()
        strip.set_pictures(pixmaps)      # any number; None = not there yet
        strip.set_range(0.25, 0.6)       # fractions of the whole, 0..1
        strip.range_changed.connect(...) # while dragging
        strip.range_released.connect(...)# when the mouse lets go

    Dragging a handle moves that end; dragging between the handles moves
    the whole range; a click outside moves the nearer handle there. The
    ends never cross (MIN_SPAN apart at least).

    Colors are Qt properties set by ui/theme/widgets.qss: accentColor (the
    range's frame and handles), dimColor (what is outside), baseColor
    (behind pictures that aren't there yet).

    Signals:
        range_changed(float, float) / range_released(float, float) — start, end.
    """

    HEIGHT = 46
    HANDLE = 7          # a handle's width
    MIN_SPAN = 0.005
    RADIUS = 4

    range_changed = qt.QtCore.Signal(float, float)
    range_released = qt.QtCore.Signal(float, float)

    accentColor = color_property("_accent_color")
    dimColor = color_property("_dim_color")
    baseColor = color_property("_base_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._accent_color = qt.QtGui.QColor(fallback.accent)
        self._dim_color = qt.QtGui.QColor(0, 0, 0, 150)
        self._base_color = qt.QtGui.QColor(fallback.border)
        self._pictures: list = []
        self._start, self._end = 0.0, 1.0
        self._drag = ""            # "start" / "end" / "move" while a button is down
        self._grab = 0.0           # where in the range a "move" drag took hold
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    # --- content ------------------------------------------------------------------

    def set_pictures(self, pictures: list) -> None:
        """The pictures, left to right (QPixmap, or None for one that isn't there yet)."""
        self._pictures = list(pictures)
        self.update()

    def range(self) -> tuple:
        return self._start, self._end

    def set_range(self, start: float, end: float) -> None:
        """Sets the range without emitting anything."""
        start, end = self._clamped(start, end)
        if (start, end) != (self._start, self._end):
            self._start, self._end = start, end
            self.update()

    def _clamped(self, start: float, end: float) -> tuple:
        start = min(max(float(start), 0.0), 1.0 - self.MIN_SPAN)
        end = min(max(float(end), start + self.MIN_SPAN), 1.0)
        return start, end

    # --- the mouse -------------------------------------------------------------------

    def _fraction(self, x: float) -> float:
        return min(max(x / max(self.width(), 1), 0.0), 1.0)

    def _part_at(self, x: float) -> str:
        left, right = self._start * self.width(), self._end * self.width()
        if abs(x - left) <= self.HANDLE + 2 and abs(x - left) <= abs(x - right):
            return "start"
        if abs(x - right) <= self.HANDLE + 2:
            return "end"
        return "move" if left < x < right else ""

    def mousePressEvent(self, event) -> None:
        if event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        x = event.position().x()
        part = self._part_at(x)
        if not part:  # outside the range: the nearer end jumps there
            part = "start" if x < self._start * self.width() else "end"
            self._drag = part
            self._move_to(x)
        self._drag = part
        self._grab = self._fraction(x) - self._start
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._drag:
            self._move_to(x)
        else:
            part = self._part_at(x)
            self.setCursor(qt.QtCore.Qt.CursorShape.SizeHorCursor if part in ("start", "end")
                           else qt.QtCore.Qt.CursorShape.OpenHandCursor if part == "move"
                           else qt.QtCore.Qt.CursorShape.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag:
            self._drag = ""
            self.range_released.emit(self._start, self._end)
        super().mouseReleaseEvent(event)

    def _move_to(self, x: float) -> None:
        at = self._fraction(x)
        if self._drag == "start":
            start, end = self._clamped(min(at, self._end - self.MIN_SPAN), self._end)
        elif self._drag == "end":
            start, end = self._clamped(self._start, max(at, self._start + self.MIN_SPAN))
        else:
            span = self._end - self._start
            start = min(max(at - self._grab, 0.0), 1.0 - span)
            end = start + span
        if (start, end) != (self._start, self._end):
            self._start, self._end = start, end
            self.update()
            self.range_changed.emit(start, end)

    # --- painting ----------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        rect = qt.QtCore.QRectF(self.rect())
        clip = qt.QtGui.QPainterPath()
        clip.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.setClipPath(clip)
        painter.fillRect(rect, self._base_color)

        count = len(self._pictures)
        if count:
            cell = rect.width() / count
            for index, picture in enumerate(self._pictures):
                if picture is None or picture.isNull():
                    continue
                target = qt.QtCore.QRectF(index * cell, 0, cell + 1, rect.height())
                # cover the cell: scale to fill, crop what sticks out
                scale = max(target.width() / picture.width(), target.height() / picture.height())
                width, height = target.width() / scale, target.height() / scale
                source = qt.QtCore.QRectF((picture.width() - width) / 2, (picture.height() - height) / 2, width, height)
                painter.drawPixmap(target, picture, source)

        left, right = self._start * rect.width(), self._end * rect.width()
        painter.fillRect(qt.QtCore.QRectF(0, 0, left, rect.height()), self._dim_color)
        painter.fillRect(qt.QtCore.QRectF(right, 0, rect.width() - right, rect.height()), self._dim_color)
        painter.setClipping(False)

        painter.setPen(qt.QtGui.QPen(self._accent_color, 2))
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(qt.QtCore.QRectF(left + 1, 1, max(right - left - 2, 1), rect.height() - 2), 3, 3)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._accent_color)
        for x in (left, right - self.HANDLE):
            x = min(max(x, 0), rect.width() - self.HANDLE)
            painter.drawRoundedRect(qt.QtCore.QRectF(x, 0, self.HANDLE, rect.height()), 3, 3)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        strip = RangeStrip()
        strip.setMinimumWidth(480)
        pictures = []
        for index in range(10):
            pixmap = qt.QtGui.QPixmap(160, 90)
            pixmap.fill(qt.QtGui.QColor.fromHsv(index * 30, 160, 200))
            pictures.append(pixmap)
        strip.set_pictures(pictures)
        strip.set_range(0.2, 0.7)
        strip.range_changed.connect(lambda a, b: print(f"{a:.3f} .. {b:.3f}"))
        dialog.add_case("RangeStrip", strip)
        dialog.show()
