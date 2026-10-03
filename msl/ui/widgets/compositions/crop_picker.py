# ui/widgets/compositions/crop_picker.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class CropPicker(qt.QtWidgets.QWidget):
    """A picture with a rectangle drawn on it by hand — what to keep. Drag a
    corner or an edge to resize the rectangle, drag inside it to move it;
    what lies outside is dimmed.

        picker = CropPicker()
        picker.set_picture(pixmap)
        picker.set_box(0.1, 0.1, 0.8, 0.8)     # x, y, width, height as parts of the picture, 0..1
        picker.box_changed.connect(...)        # while dragging
        picker.box()                           # -> (x, y, width, height)

    The picture is shown as large as it fits, centred. Colors are Qt
    properties set by ui/theme/widgets.qss: accentColor (the frame and its
    handles), dimColor (what is cut off), baseColor (while there is no
    picture), guideColor (the thirds inside the frame).

    Signals:
        box_changed(float, float, float, float) — x, y, width, height.
    """

    HEIGHT = 190
    GRIP = 9             # how near an edge the pointer takes hold of it, in pixels
    MIN_PART = 0.05      # the rectangle is never smaller than this part of the picture

    box_changed = qt.QtCore.Signal(float, float, float, float)

    accentColor = color_property("_accent_color")
    dimColor = color_property("_dim_color")
    baseColor = color_property("_base_color")
    guideColor = color_property("_guide_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._accent_color = qt.QtGui.QColor(fallback.accent)
        self._dim_color = qt.QtGui.QColor(fallback.surface)
        self._dim_color.setAlpha(170)
        self._base_color = qt.QtGui.QColor(fallback.border)
        self._guide_color = qt.QtGui.QColor(fallback.accent)
        self._guide_color.setAlpha(90)
        self._picture = qt.QtGui.QPixmap()
        self._box = [0.0, 0.0, 1.0, 1.0]
        self._drag = ""          # which edges are held: any of "l", "r", "t", "b" — or "move"
        self._grab = qt.QtCore.QPointF()
        self._start_box = list(self._box)
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(160)
        self.setMouseTracking(True)

    # --- content ----------------------------------------------------------------------------

    def set_picture(self, picture: "qt.QtGui.QPixmap | None") -> None:
        self._picture = picture if picture is not None else qt.QtGui.QPixmap()
        self.update()

    def box(self) -> tuple:
        return tuple(self._box)

    def set_box(self, x: float, y: float, width: float, height: float) -> None:
        """Sets the rectangle without emitting anything."""
        self._box = self._clamped(x, y, width, height)
        self.update()

    def _clamped(self, x: float, y: float, width: float, height: float) -> list:
        width = min(max(float(width), self.MIN_PART), 1.0)
        height = min(max(float(height), self.MIN_PART), 1.0)
        return [min(max(float(x), 0.0), 1.0 - width), min(max(float(y), 0.0), 1.0 - height), width, height]

    # --- geometry ---------------------------------------------------------------------------

    def _picture_rect(self) -> qt.QtCore.QRectF:
        """Where the picture is drawn: as large as it fits, centred."""
        area = qt.QtCore.QRectF(self.rect())
        if self._picture.isNull():
            return area
        scale = min(area.width() / self._picture.width(), area.height() / self._picture.height())
        width, height = self._picture.width() * scale, self._picture.height() * scale
        return qt.QtCore.QRectF((area.width() - width) / 2, (area.height() - height) / 2, width, height)

    def _box_rect(self) -> qt.QtCore.QRectF:
        picture = self._picture_rect()
        x, y, width, height = self._box
        return qt.QtCore.QRectF(picture.x() + x * picture.width(), picture.y() + y * picture.height(),
                                width * picture.width(), height * picture.height())

    def _part_at(self, point) -> str:
        rect = self._box_rect()
        outer = rect.adjusted(-self.GRIP, -self.GRIP, self.GRIP, self.GRIP)
        if not outer.contains(point):
            return ""
        edges = ("l" if abs(point.x() - rect.left()) <= self.GRIP else "r" if abs(point.x() - rect.right()) <= self.GRIP
                 else "")
        edges += "t" if abs(point.y() - rect.top()) <= self.GRIP else "b" if abs(point.y() - rect.bottom()) <= self.GRIP \
            else ""
        return edges or "move"

    # --- the mouse --------------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._drag = self._part_at(event.position())
        self._grab = event.position()
        self._start_box = list(self._box)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._drag:
            self._show_cursor(self._part_at(event.position()))
            return super().mouseMoveEvent(event)
        picture = self._picture_rect()
        dx = (event.position().x() - self._grab.x()) / max(picture.width(), 1.0)
        dy = (event.position().y() - self._grab.y()) / max(picture.height(), 1.0)
        x, y, width, height = self._start_box
        right, bottom = x + width, y + height
        if self._drag == "move":
            box = self._clamped(x + dx, y + dy, width, height)
        else:
            if "l" in self._drag:
                x = min(max(x + dx, 0.0), right - self.MIN_PART)
            if "r" in self._drag:
                right = max(min(right + dx, 1.0), x + self.MIN_PART)
            if "t" in self._drag:
                y = min(max(y + dy, 0.0), bottom - self.MIN_PART)
            if "b" in self._drag:
                bottom = max(min(bottom + dy, 1.0), y + self.MIN_PART)
            box = [x, y, right - x, bottom - y]
        if box != self._box:
            self._box = box
            self.update()
            self.box_changed.emit(*box)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = ""
        super().mouseReleaseEvent(event)

    def _show_cursor(self, part: str) -> None:
        shapes = qt.QtCore.Qt.CursorShape
        self.setCursor({"": shapes.ArrowCursor, "move": shapes.SizeAllCursor, "l": shapes.SizeHorCursor,
                        "r": shapes.SizeHorCursor, "t": shapes.SizeVerCursor, "b": shapes.SizeVerCursor,
                        "lt": shapes.SizeFDiagCursor, "rb": shapes.SizeFDiagCursor, "rt": shapes.SizeBDiagCursor,
                        "lb": shapes.SizeBDiagCursor}.get(part, shapes.ArrowCursor))

    # --- painting ---------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        picture = self._picture_rect()
        if self._picture.isNull():
            painter.fillRect(picture, self._base_color)
        else:
            painter.drawPixmap(picture, self._picture, qt.QtCore.QRectF(self._picture.rect()))
        box = self._box_rect()
        outside = qt.QtGui.QPainterPath()
        outside.addRect(picture)
        inside = qt.QtGui.QPainterPath()
        inside.addRect(box)
        painter.fillPath(outside.subtracted(inside), self._dim_color)

        painter.setPen(qt.QtGui.QPen(self._guide_color, 1))
        for part in (1 / 3, 2 / 3):  # the thirds: where a picture's weight likes to sit
            x, y = box.left() + box.width() * part, box.top() + box.height() * part
            painter.drawLine(qt.QtCore.QPointF(x, box.top()), qt.QtCore.QPointF(x, box.bottom()))
            painter.drawLine(qt.QtCore.QPointF(box.left(), y), qt.QtCore.QPointF(box.right(), y))
        painter.setPen(qt.QtGui.QPen(self._accent_color, 2))
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRect(box.adjusted(1, 1, -1, -1))
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._accent_color)
        for corner in (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight()):
            painter.drawRect(qt.QtCore.QRectF(corner.x() - 4, corner.y() - 4, 8, 8))
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        picker = CropPicker()
        picker.setMinimumWidth(480)
        pixmap = qt.QtGui.QPixmap(640, 360)
        pixmap.fill(qt.QtGui.QColor.fromHsv(200, 120, 180))
        picker.set_picture(pixmap)
        picker.set_box(0.2, 0.15, 0.5, 0.6)
        picker.box_changed.connect(lambda *box: print([round(value, 3) for value in box]))
        dialog.add_case("CropPicker", picker)
        dialog.show()
