# tools/maya/labels/sketch.py
"""ViewportSketch: the picture a playblast would show, small — a 16:9 frame with every HUD column
of the layout drawn where it will stand, its header and lines, the picked one framed in the accent.
A column is dragged to where it should be (it keeps its corner: the drag changes how far in from
it). Letters are drawn at least READABLE pixels high, so the sketch says what the columns hold;
their places are to scale. 3D columns stand at objects in the scene, so they are only named along
the bottom."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.labels import layout as lay
from msl_tools.msl.ui.theme.qss import color_property

ASPECT = 16.0 / 9.0
REFERENCE = 1080.0   # the frame stands for a picture this high (a Manual column's pixels are screen pixels)
CAPITALS = 0.65      # the capitals' height as a part of the font size (measured, Maya 2026)
READABLE = 8.0       # the sketch draws no letters smaller than this: it is a sketch, not to scale —
                     # true to scale, 14 px labels in a 1080 picture are 3 px here and say nothing
MOST = 190           # the sketch is at most this high (16:9 of a wide window would be taller)


class ViewportSketch(qt.QtWidgets.QWidget):
    """Signals:
        picked(int) — a column was clicked (its index).
        moved(int, int, int) — a column was dragged: its index, new x, new y (pixels, as stored).
    """

    picked = qt.QtCore.Signal(int)
    moved = qt.QtCore.Signal(int, int, int)

    frameColor = color_property("_frame", "update")
    groundColor = color_property("_ground", "update")
    textColor = color_property("_text", "update")
    quietColor = color_property("_quiet", "update")
    pickedColor = color_property("_picked_color", "update")

    def __init__(self, parent=None):
        super().__init__(parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        fallback = ThemeRegistry.fallback()
        self._frame = qt.QtGui.QColor(fallback.text_secondary)
        self._ground = qt.QtGui.QColor(fallback.surface)
        self._text = qt.QtGui.QColor(fallback.text_primary)
        self._quiet = qt.QtGui.QColor(fallback.text_secondary)
        self._picked_color = qt.QtGui.QColor(fallback.accent)
        self._columns: list[lay.Column] = []
        self._values: dict = {}        # (column index, line index) -> the value's text now
        self._current = -1
        self._boxes: dict = {}         # column index -> its QRectF as painted
        self._drag = None              # (index, press point, start x, start y)
        self.setMinimumHeight(120)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding, qt.QtWidgets.QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def set_columns(self, columns, current: int, values=None) -> None:
        self._columns = list(columns)
        self._current = current
        self._values = dict(values or {})
        self.update()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return min(MOST, int(round(width / ASPECT)))

    def sizeHint(self) -> "qt.QtCore.QSize":
        return qt.QtCore.QSize(360, int(360 / ASPECT))

    # --- where a column stands in the sketch

    def _frame_rect(self) -> "qt.QtCore.QRectF":
        width = float(self.width()) - 2
        height = width / ASPECT
        if height > self.height() - 2:
            height = float(self.height()) - 2
            width = height * ASPECT
        return qt.QtCore.QRectF((self.width() - width) / 2.0, (self.height() - height) / 2.0, width, height)

    def _scale(self, frame) -> float:
        """Sketch pixels per picture pixel."""
        return frame.height() / REFERENCE

    @staticmethod
    def _reference(column: lay.Column) -> float:
        return float(column.reference_height) if column.scale_mode == lay.AUTO else REFERENCE

    def _lines_of(self, index: int, column: lay.Column) -> list:
        lines = []
        shown = [line for line in column.lines if line.show]
        width = max([len(line.label or line.attribute.split(".")[-1]) for line in shown] or [0])
        for line_index, line in enumerate(column.lines):
            if not line.show:
                continue
            label = line.label or line.attribute.split(".")[-1]
            value = self._values.get((index, line_index), "-")
            color = qt.QtGui.QColor.fromRgbF(*line.color)
            if line.color_keys:
                color = qt.QtGui.QColor.fromRgbF(*line.color_keys[-1][1])
            lines.append((label.ljust(width) + "  " + value, color))
        return lines

    def _box(self, index: int, column: lay.Column, frame, metrics_for) -> "qt.QtCore.QRectF":
        """The column's rectangle in the sketch."""
        picture = frame.height() / self._reference(column)       # sketch px per column px (Auto)
        size = max(READABLE, column.size * column.scale * picture)
        step = size * 1.2 + column.spacing * column.scale * picture
        lines = self._lines_of(index, column)
        height = len(lines) * step
        texts = [text for text, _color in lines]
        width = max([metrics_for(size).horizontalAdvance(text) for text in texts] or [0])
        if column.header:
            header_size = size * column.header_scale
            height += header_size * 1.2 + (step - size * 1.2)
            width = max(width, metrics_for(header_size).horizontalAdvance(column.header))
        width, height = max(width, 12.0), max(height, size * 1.2)
        x = column.x * picture
        y = column.y * picture
        left = frame.left() + x if column.corner in (lay.TOP_LEFT, lay.BOTTOM_LEFT) else frame.right() - x - width
        # the capitals' top lies y under the frame's top (a top corner) / the box's bottom y above its bottom
        top = (frame.top() + y - size * (1.0 - CAPITALS) * 0.5 if column.corner in (lay.TOP_LEFT, lay.TOP_RIGHT)
               else frame.bottom() - y - height)
        return qt.QtCore.QRectF(left, top, width, height)

    def _font(self, column: lay.Column, size: float) -> "qt.QtGui.QFont":
        font = qt.QtGui.QFont(column.font or "Consolas")
        font.setPixelSize(max(4, int(round(size))))
        return font

    # --- painting

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        frame = self._frame_rect()
        painter.setPen(qt.QtGui.QPen(self._frame, 1))
        painter.setBrush(self._ground)
        painter.drawRoundedRect(frame, 4, 4)
        self._boxes = {}
        spaced = []
        for index, column in enumerate(self._columns):
            if column.mode != lay.HUD:
                spaced.append((index, column))
                continue
            box = self._box(index, column, frame,
                            lambda size, column=column: qt.QtGui.QFontMetricsF(self._font(column, size)))
            self._boxes[index] = box
            self._paint_column(painter, index, column, box, frame)
        if spaced:   # 3D columns: named along the bottom
            font = self.font()
            font.setPixelSize(10)
            painter.setFont(font)
            text = "In the scene:  " + "  ·  ".join(
                f"{column.name} at {column.anchor or '?'}" for _index, column in spaced)
            painter.setPen(self._quiet)
            painter.drawText(frame.adjusted(6, 0, -6, -4), qt.QtCore.Qt.AlignmentFlag.AlignBottom
                             | qt.QtCore.Qt.AlignmentFlag.AlignLeft, text)

    def _paint_column(self, painter, index, column, box, frame) -> None:
        picture = frame.height() / self._reference(column)
        size = max(READABLE, column.size * column.scale * picture)
        step = size * 1.2 + column.spacing * column.scale * picture
        right = column.corner in (lay.TOP_RIGHT, lay.BOTTOM_RIGHT)
        align = qt.QtCore.Qt.AlignmentFlag.AlignRight if right else qt.QtCore.Qt.AlignmentFlag.AlignLeft
        top = box.top()
        if column.header:
            header_size = size * column.header_scale
            painter.setFont(self._font(column, header_size))
            painter.setPen(qt.QtGui.QColor.fromRgbF(*column.header_color))
            painter.drawText(qt.QtCore.QRectF(box.left(), top, box.width(), header_size * 1.2), align, column.header)
            top += header_size * 1.2 + (step - size * 1.2)
        painter.setFont(self._font(column, size))
        for text, color in self._lines_of(index, column):
            painter.setPen(color)
            painter.drawText(qt.QtCore.QRectF(box.left(), top, box.width(), size * 1.2), align, text)
            top += step
        if index == self._current:
            painter.setPen(qt.QtGui.QPen(self._picked_color, 1.5))
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-3, -2, 3, 2), 3, 3)

    # --- the mouse

    def _column_at(self, point) -> int:
        for index in sorted(self._boxes, key=lambda each: each != self._current):
            if self._boxes[index].adjusted(-4, -4, 4, 4).contains(point):
                return index
        return -1

    def mousePressEvent(self, event) -> None:
        if event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        index = self._column_at(event.position())
        if index < 0:
            return
        column = self._columns[index]
        self._drag = (index, event.position(), column.x, column.y)
        if index != self._current:
            self._current = index
            self.update()
            self.picked.emit(index)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            over = self._column_at(event.position()) >= 0
            self.setCursor(qt.QtCore.Qt.CursorShape.SizeAllCursor if over else qt.QtCore.Qt.CursorShape.ArrowCursor)
            return
        index, start, x, y = self._drag
        column = self._columns[index]
        picture = self._frame_rect().height() / self._reference(column)
        dx = (event.position().x() - start.x()) / picture
        dy = (event.position().y() - start.y()) / picture
        # in from the corner: moving right is "more" from a left corner, "less" from a right one
        column.x = int(round(max(0.0, x + (dx if column.corner in (lay.TOP_LEFT, lay.BOTTOM_LEFT) else -dx))))
        column.y = int(round(max(0.0, y + (dy if column.corner in (lay.TOP_LEFT, lay.TOP_RIGHT) else -dy))))
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is not None:
            index = self._drag[0]
            self._drag = None
            column = self._columns[index]
            self.moved.emit(index, column.x, column.y)
        super().mouseReleaseEvent(event)


class CornerPicker(qt.QtWidgets.QWidget):
    """Which corner of the screen: four small cells in a 2 x 2 frame, the picked one filled. A click
    on a cell picks it.

    Signals:
        picked(str) — layout.TOP_LEFT / TOP_RIGHT / BOTTOM_LEFT / BOTTOM_RIGHT.
    """

    picked = qt.QtCore.Signal(str)

    cellColor = color_property("_cell", "update")
    pickedColor = color_property("_picked_color", "update")
    hoverColor = color_property("_hover", "update")

    def __init__(self, parent=None):
        super().__init__(parent)
        from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
        fallback = ThemeRegistry.fallback()
        self._cell = qt.QtGui.QColor(fallback.text_secondary)
        self._picked_color = qt.QtGui.QColor(fallback.accent)
        self._hover = qt.QtGui.QColor(fallback.text_primary)
        self._current = lay.TOP_LEFT
        self._over = ""
        self.setFixedSize(34, 22)
        self.setMouseTracking(True)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def current(self) -> str:
        return self._current

    def set_current(self, corner: str) -> None:
        if corner in lay.CORNERS and corner != self._current:
            self._current = corner
            self.update()

    def _cells(self) -> dict:
        width, height = (self.width() - 5) / 2.0, (self.height() - 5) / 2.0
        return {lay.TOP_LEFT: qt.QtCore.QRectF(1.5, 1.5, width, height),
                lay.TOP_RIGHT: qt.QtCore.QRectF(3.5 + width, 1.5, width, height),
                lay.BOTTOM_LEFT: qt.QtCore.QRectF(1.5, 3.5 + height, width, height),
                lay.BOTTOM_RIGHT: qt.QtCore.QRectF(3.5 + width, 3.5 + height, width, height)}

    def _at(self, point) -> str:
        return next((corner for corner, cell in self._cells().items() if cell.contains(point)), "")

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        for corner, cell in self._cells().items():
            if corner == self._current:
                painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(self._picked_color)
            else:
                painter.setPen(qt.QtGui.QPen(self._hover if corner == self._over else self._cell, 1))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(cell.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)

    def mouseMoveEvent(self, event) -> None:
        over = self._at(event.position())
        if over != self._over:
            self._over = over
            self.update()

    def leaveEvent(self, event) -> None:
        self._over = ""
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        corner = self._at(event.position())
        if corner and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.set_current(corner)
            self.picked.emit(corner)
