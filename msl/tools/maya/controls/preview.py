# tools/maya/controls/preview.py
"""Control shapes drawn by Qt from their points — no Maya, no playblast: the library's thumbnails
(`thumbnail()`) and the preview that turns under the mouse (`ShapeView`). An orthographic view
from above and to the side, so flat shapes read as what they are and 3D ones have depth."""
import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
from msl_tools.msl.tools.maya.controls.shapes import polyline, scaled
from msl_tools.msl.ui.theme.qss import color_property

THUMB_YAW, THUMB_PITCH = 24.0, 62.0     # degrees: the thumbnails' fixed view
REACH = 1.75                            # what the view must hold: a unit cube's corner is at ~1.73


def _projected(point, yaw: float, pitch: float):
    """(screen x, screen y up, depth toward the viewer) of a point seen from yaw / pitch."""
    x, y, z = point
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    x, z = x * cy - z * sy, x * sy + z * cy
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    y, z = y * cp - z * sp, y * sp + z * cp
    return x, y, z


def draw_curves(painter, rect, curves, color, yaw: float, pitch: float, width: float = 1.5,
                reach: "float | None" = REACH) -> None:
    """Paints `curves` (shapes.Curve) into `rect`: centred on the origin, `reach` units to its edge —
    or, `reach` None, fitted: the picture of the shape as big as the rect allows (thumbnails)."""
    lines = [[_projected(point, yaw, pitch) for point in polyline(curve, 6)] for curve in curves]
    if reach is None:
        xs = [x for line in lines for x, _y, _z in line] or [0.0]
        ys = [y for line in lines for _x, y, _z in line] or [0.0]
        width_used, height_used = max(xs) - min(xs) or 1e-6, max(ys) - min(ys) or 1e-6
        scale = min(rect.width() / width_used, rect.height() / height_used)
        center = qt.QtCore.QPointF(rect.center().x() - (max(xs) + min(xs)) / 2 * scale,
                                   rect.center().y() + (max(ys) + min(ys)) / 2 * scale)
    else:
        scale = min(rect.width(), rect.height()) / 2 / reach
        center = rect.center()
    pen = qt.QtGui.QPen(color, width)
    pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
    for line in lines:
        painter.drawPolyline(qt.QtGui.QPolygonF([qt.QtCore.QPointF(center.x() + x * scale, center.y() - y * scale)
                                                 for x, y, _depth in line]))


def thumbnail(curves, side: int, color, ratio: float = 1.0) -> "qt.QtGui.QPixmap":
    """A transparent square picture of the shape, `side` px (device ratio `ratio`)."""
    pixmap = qt.QtGui.QPixmap(int(side * ratio), int(side * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(qt.QtCore.Qt.GlobalColor.transparent)
    painter = qt.QtGui.QPainter(pixmap)
    painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
    margin = max(3.0, side * 0.1)
    # a flat shape is seen straight from above (a letter, a heart read as what they are), a 3D one from aside
    flat = all(abs(point[1]) < 1e-4 for curve in curves for point in curve.points)
    yaw, pitch = (0.0, 90.0) if flat else (THUMB_YAW, THUMB_PITCH)
    draw_curves(painter, qt.QtCore.QRectF(margin, margin, side - 2 * margin, side - 2 * margin), curves, color,
                yaw, pitch, 1.4, reach=None)
    painter.end()
    return pixmap


class ShapeView(qt.QtWidgets.QWidget):
    """The picked shape, big: drag to turn it, double click to look from the start again. A ground
    grid, the three axes (the one the shape faces drawn longer) and the shape in the line color.
    Colors: qproperty groundColor / gridColor / lineColor / xColor / yColor / zColor (controls.qss)."""

    groundColor = color_property("_ground", "update")
    gridColor = color_property("_grid", "update")
    lineColor = color_property("_line", "update")
    xColor = color_property("_x", "update")
    yColor = color_property("_y", "update")
    zColor = color_property("_z", "update")
    titleColor = color_property("_title_color", "update")
    zeroColor = color_property("_zero_color", "update")      # the frames that stand for zero groups
    driveColor = color_property("_drive_color", "update")    # the note that says the control will drive

    axis_picked = qt.QtCore.Signal(str)      # a click on an axis chip: the shape faces it now
    size_stepped = qt.QtCore.Signal(int)     # the wheel over the view: +1 / -1

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()
        self._ground = qt.QtGui.QColor(fallback.surface)
        self._grid = qt.QtGui.QColor(fallback.border)
        self._line = qt.QtGui.QColor(fallback.accent)
        self._x = qt.QtGui.QColor(fallback.error)
        self._y = qt.QtGui.QColor(fallback.success)
        self._z = qt.QtGui.QColor(fallback.accent)
        self._title_color = qt.QtGui.QColor(fallback.text_secondary)
        self._curves = []
        self._axis = "Y"
        self._title = ""
        self._subtitle = ""
        self._corner = ([], [])
        self._zero_color = qt.QtGui.QColor(fallback.accent)
        self._drive_color = qt.QtGui.QColor(fallback.accent)
        self._notes = []             # [(icon, text, "zero" / "drive" / "")]: what will be done, top left
        self._items = []             # what Create would make: one per target (see set_scene)
        self._chain = False
        self._zero = ("none", 0)     # how new controls are zeroed: ("groups", how many) / ("matrix", 1)
        self._action = None          # a shape tool's before / after, shown while its button is hovered
        self._yaw, self._pitch = THUMB_YAW, 28.0
        self._drag = None
        self.setMinimumSize(110, 110)
        self.setMouseTracking(True)
        self.setCursor(qt.QtCore.Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to turn it · double click: the first view")

    def set_curves(self, curves, axis: str = "Y") -> None:
        self._curves, self._axis = list(curves), axis
        self.update()

    # ---- what the view holds besides the picture: the facing axis, the shape's name, two corner widgets

    def axis(self) -> str:
        return self._axis

    def set_axis(self, axis: str) -> None:
        self._axis = axis
        self.update()

    def set_title(self, text: str, subtitle: str = "") -> None:
        """What the picture is of, top left: a line, and a quieter one under it."""
        self._title, self._subtitle = text, subtitle
        self.update()

    def set_notes(self, notes: list) -> None:
        """Lines top left, each a small icon in its tone and a few words: [(QIcon, text, "zero" /
        "drive" / "")] — how the new control is zeroed, what it will drive. Shown instead of the
        title while there are any (the title is a hovered tool's)."""
        self._notes = list(notes)
        self.update()

    def set_scene(self, items: list, chain: bool = False) -> None:
        """What Create would make, one item per object it is made for:
        {"look": scene.target_look or None, "reach": the control's size in scene units,
         "color": QColor / "plain" (no color of its own) / None (the preview's own),
         "matrix": 16 numbers placing it in the FIRST object's axes (None = there), "parent": the index of
         the item its control goes under, or -1, "becomes": True when the object itself becomes the control
         (the curve goes onto it): it is then drawn in the control's color}. `chain` draws a line from each control to its parent's."""
        self._items, self._chain = list(items), bool(chain)
        self.update()

    def set_zero(self, mode: str, count: int = 1) -> None:
        """How a new control is zeroed, drawn around it: "groups" = `count` nested frames, "matrix" =
        the corners of one (brackets), "none"."""
        self._zero = (mode, max(1, int(count)))
        self.update()

    def set_action(self, before, after, color=None, zero=None) -> None:
        """A shape tool's effect on a control that exists: its curves now (drawn faint) and after the
        click, in the control's color; `zero` as set_zero's pair. before None = back to the scene."""
        self._action = None if before is None else {"before": list(before), "after": list(after or []),
                                                    "color": color, "zero": zero}
        self.update()

    def set_corner_widgets(self, left, right) -> None:
        """Small widgets of the owner's shown in the bottom corners: a list for the left, one for the right."""
        self._corner = (list(left), list(right))
        for widget in self._corner[0] + self._corner[1]:
            widget.setParent(self)
            widget.installEventFilter(self)     # the stylesheet resizes them after they were placed
        self._place_corners()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (qt.QtCore.QEvent.Type.Resize, qt.QtCore.QEvent.Type.Show) and \
                watched in self._corner[0] + self._corner[1]:
            self._place_corners()
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place_corners()

    def _place_corners(self) -> None:
        """One row along the bottom: whatever their heights, their MIDDLES are on one line."""
        left, right = self._corner
        tallest = max([widget.height() for widget in left + right] or [0])
        middle = self.height() - 5 - tallest / 2.0

        def put(widget, x: int) -> None:
            spot = qt.QtCore.QPoint(x, int(round(middle - widget.height() / 2.0)))
            if widget.pos() != spot:
                widget.move(spot)

        x = 5
        for widget in left:
            put(widget, x)
            x += widget.width() + 3
        x = self.width() - 5
        for widget in reversed(right):
            x -= widget.width()
            put(widget, x)
            x -= 3

    @staticmethod
    def _target_extent(look, reach: float) -> float:
        """How far the target reaches from its pivot — never so far that the control gets lost."""
        if not look:
            return 0.0
        limit = reach * 2.6
        if look.get("kind") == "joint":
            bones = [sum(value * value for value in bone) ** 0.5 for bone in look.get("bones", [])]
            return min(max([look.get("radius", 0.0)] + bones), limit)
        box = look.get("box")
        return min(max(abs(value) for value in box), limit) if box else 0.0

    @staticmethod
    def _placed(matrix, p):
        """A point of an item in the first item's axes (a row vector times the 4x4)."""
        if not matrix:
            return p
        x, y, z = p
        m = matrix
        return (x * m[0] + y * m[4] + z * m[8] + m[12], x * m[1] + y * m[5] + z * m[9] + m[13],
                x * m[2] + y * m[6] + z * m[10] + m[14])

    def _color_of(self, wanted) -> "qt.QtGui.QColor":
        return self._title_color if isinstance(wanted, str) else (wanted or self._line)

    def _paint_target(self, painter, place, look, radius_px: float, own=None) -> None:
        """The object a control is made for, quiet and grey — or, `own` (a color): the object that
        BECOMES the control (the curve goes onto it), drawn in the control's color, as one with it."""
        color = qt.QtGui.QColor(own if own is not None else self._title_color)
        color.setAlpha(255 if own is not None else 190)
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        if look.get("kind") == "joint":
            painter.setPen(qt.QtGui.QPen(color, 1.8 if own is not None else 1.2))
            origin = place((0.0, 0.0, 0.0))
            painter.drawEllipse(origin, radius_px, radius_px)
            for bone in look.get("bones", []):
                end = place(bone)
                painter.drawLine(origin, end)
                painter.drawEllipse(end, radius_px * 0.6, radius_px * 0.6)
            return
        if look.get("kind") == "part":
            # a point of a surface: a dot, and the way the surface faces there (the picked axis)
            origin = place((0.0, 0.0, 0.0))
            painter.setPen(qt.QtGui.QPen(color, 1.2))
            painter.setBrush(color)
            painter.drawEllipse(origin, 2.5, 2.5)
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            return
        box = look.get("box")
        if not box:
            return
        pen = qt.QtGui.QPen(color, 1.0)
        pen.setStyle(qt.QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        x0, y0, z0, x1, y1, z1 = box
        corners = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        for a in range(8):
            for b in range(a + 1, 8):
                if sum(1 for i in range(3) if corners[a][i] != corners[b][i]) == 1:
                    painter.drawLine(place(corners[a]), place(corners[b]))

    def _faced(self, x: float, z: float):
        """A point of the plane a flat shape lies in (it faces the picked axis)."""
        return {"X": (0.0, -x, z), "Z": (x, -z, 0.0)}.get(self._axis, (x, 0.0, z))

    def _paint_zero(self, painter, place, reach: float, zero) -> None:
        """Zero groups as frames nested around the control, one per group; the matrix as brackets."""
        mode, count = zero
        if mode not in ("groups", "matrix"):
            return
        color = qt.QtGui.QColor(self._zero_color)
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        for index in range(min(count, 4) if mode == "groups" else 1):
            half = reach * (1.2 + 0.17 * index)
            corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
            color.setAlpha(230 - 45 * index)
            pen = qt.QtGui.QPen(color, 1.1)
            if mode == "groups":
                pen.setStyle(qt.QtCore.Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawPolygon(qt.QtGui.QPolygonF([place(self._faced(x, z)) for x, z in corners]))
                continue
            painter.setPen(pen)
            arm = half * 0.4
            for x, z in corners:
                sx, sz = (1 if x < 0 else -1), (1 if z < 0 else -1)
                painter.drawPolyline(qt.QtGui.QPolygonF([place(self._faced(x + sx * arm, z)), place(self._faced(x, z)),
                                                         place(self._faced(x, z + sz * arm))]))

    @staticmethod
    def _paint_curves(painter, place, curves, color, width: float, dashed: bool = False) -> None:
        pen = qt.QtGui.QPen(color, width)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
        if dashed:
            pen.setStyle(qt.QtCore.Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        for curve in curves:
            painter.drawPolyline(qt.QtGui.QPolygonF([place(p) for p in polyline(curve, 6)]))

    def _paint_action(self, painter, point) -> None:
        """A control that exists: as it is (faint, dotted) and as the hovered tool would leave it."""
        action = self._action
        reach = max([abs(value) for curve in action["before"] + action["after"] for p in curve.points
                     for value in p] or [1.0]) or 1.0
        zero = action.get("zero")
        room = reach * ((1.25 + 0.17 * min(zero[1], 4)) if zero and zero[0] in ("groups", "matrix") else 1.2)

        def place(p):
            return point(tuple(value / room for value in p))

        faint = qt.QtGui.QColor(self._title_color)
        faint.setAlpha(150)
        color = self._color_of(action.get("color"))
        if action["after"] != action["before"]:
            self._paint_curves(painter, place, action["before"], faint, 1.2, dashed=True)
        if zero:
            self._paint_zero(painter, place, reach, zero)
        self._paint_curves(painter, place, action["after"], color, 1.8)

    def _paint_scene(self, painter, point, scale: float) -> None:
        """Every object a control would be made for, each with its control: at its size, in its color,
        its zero frames around it, a line to the control it goes under."""
        items = self._items or [{}]
        placed = any(item.get("look") for item in items)
        reaches = [max(1e-6, float(item.get("reach", 1.0))) if placed else 1.0 for item in items]
        spots = [self._placed(item.get("matrix"), (0.0, 0.0, 0.0)) for item in items]
        low = [min(spot[i] for spot in spots) for i in range(3)]
        high = [max(spot[i] for spot in spots) for i in range(3)]
        middle = [(a + b) / 2.0 for a, b in zip(low, high)]
        mode, count = self._zero
        frames = 1.2 + 0.17 * min(count, 4) if mode == "groups" else 1.25 if mode == "matrix" else 1.0
        extent = 1e-6
        for item, reach, spot in zip(items, reaches, spots):
            away = sum((a - b) ** 2 for a, b in zip(spot, middle)) ** 0.5
            extent = max(extent, away + max(reach * frames, self._target_extent(item.get("look"), reach)))
        many = len(items) > 1
        if many:
            extent /= 1.45      # a row of controls is flat: it may fill more of the view than one 3D shape

        def place_from(matrix):
            return lambda p: point(tuple((value - centre) / extent
                                         for value, centre in zip(self._placed(matrix, p), middle)))

        for item, reach in zip(items, reaches):
            look = item.get("look")
            if look:
                radius = max(2.5, min(look.get("radius", 0.5) / extent * scale, 14.0))
                self._paint_target(painter, place_from(item.get("matrix")), look, radius,
                                   self._color_of(item.get("color")) if item.get("becomes") else None)
        if self._chain and many:
            for item, spot in zip(items, spots):
                parent = item.get("parent", -1)
                if 0 <= parent < len(items):
                    pen = qt.QtGui.QPen(self._color_of(item.get("color")), 1.3)
                    pen.setStyle(qt.QtCore.Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    to_view = place_from(None)
                    painter.drawLine(to_view(spot), to_view(spots[parent]))
        for index, (item, reach) in enumerate(zip(items, reaches)):
            place = place_from(item.get("matrix"))
            if index < 6:
                self._paint_zero(painter, place, reach, self._zero)
            self._paint_curves(painter, place, scaled(self._curves, reach), self._color_of(item.get("color")),
                               1.4 if many else 1.8)
        return point(tuple(-centre / extent for centre in middle))      # where the first object stands

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_corners()

    def _axis_rect(self, index: int) -> "qt.QtCore.QRectF":
        return qt.QtCore.QRectF(self.width() - 23, 5 + index * 19, 18, 16)

    def _axis_at(self, point) -> str:
        for index, axis in enumerate("XYZ"):
            if self._axis_rect(index).contains(point):
                return axis
        return ""

    def wheelEvent(self, event) -> None:
        self.size_stepped.emit(1 if event.angleDelta().y() > 0 else -1)
        event.accept()

    def mousePressEvent(self, event) -> None:
        axis = self._axis_at(event.position())
        if axis:
            if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and axis != self._axis:
                self._axis = axis
                self.axis_picked.emit(axis)
                self.update()
            return
        self._drag = (event.position(), self._yaw, self._pitch)
        self.setCursor(qt.QtCore.Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            over = self._axis_at(event.position())
            self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor if over
                           else qt.QtCore.Qt.CursorShape.OpenHandCursor)
            self.setToolTip(f"The shape faces {over} (a joint's X usually runs along the bone)" if over
                            else "Drag to turn it · the wheel: its size · double click: the first view")
            return
        start, yaw, pitch = self._drag
        delta = event.position() - start
        self._yaw = yaw - delta.x() * 0.6   # drag left -> the shape turns left, like a viewport
        self._pitch = max(-89.0, min(89.0, pitch + delta.y() * 0.6))
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        self.setCursor(qt.QtCore.Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:
        self._yaw, self._pitch = THUMB_YAW, 28.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(qt.QtGui.QPen(self._grid, 1))
        painter.setBrush(self._ground)
        painter.drawRoundedRect(rect, 6, 6)
        inner = rect.adjusted(6, 6, -6, -6)
        scale = min(inner.width(), inner.height()) / 2 / REACH
        center = inner.center()

        def point(p):
            x, y, _ = _projected(p, self._yaw, self._pitch)
            return qt.QtCore.QPointF(center.x() + x * scale, center.y() - y * scale)

        grid = qt.QtGui.QColor(self._grid)
        grid.setAlpha(110)
        painter.setPen(qt.QtGui.QPen(grid, 0.8))
        for step in range(-2, 3):
            value = step * 0.5
            painter.drawLine(point((value, 0, -1)), point((value, 0, 1)))
            painter.drawLine(point((-1, 0, value)), point((1, 0, value)))
        painter.save()
        painter.setClipRect(inner)
        if self._action:
            self._paint_action(painter, point)
            origin = center
        else:
            origin = self._paint_scene(painter, point, scale)
        painter.restore()
        # the axes of the (first) object, the one the shape faces drawn longer
        zero = point((0.0, 0.0, 0.0))
        for axis, color, end in (("X", self._x, (1, 0, 0)), ("Y", self._y, (0, 1, 0)), ("Z", self._z, (0, 0, 1))):
            long = axis == self._axis
            tip = point(tuple(value * (0.75 if long else 0.4) for value in end)) - zero
            painter.setPen(qt.QtGui.QPen(color, 1.5 if long else 1.0))
            painter.drawLine(origin, origin + tip)
        # the axis the shape faces: three chips in the corner, the picked one filled
        font = painter.font()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        for index, (axis, color) in enumerate((("X", self._x), ("Y", self._y), ("Z", self._z))):
            chip = self._axis_rect(index).adjusted(0.5, 0.5, -0.5, -0.5)
            picked = axis == self._axis
            fill = qt.QtGui.QColor(color if picked else self._ground)
            fill.setAlpha(70 if picked else 200)
            edge = qt.QtGui.QColor(color if picked else self._grid)
            painter.setPen(qt.QtGui.QPen(edge, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(chip, 4, 4)
            letter = qt.QtGui.QColor(color)
            letter.setAlpha(255 if picked else 150)
            painter.setPen(letter)
            painter.drawText(chip, qt.QtCore.Qt.AlignmentFlag.AlignCenter, axis)
        font.setBold(False)
        painter.setFont(font)
        notes = [] if self._action else self._notes
        for row, (icon, text, tone) in enumerate(notes):
            from msl_tools.msl.ui.icon_manager import tint_icon
            color = {"zero": self._zero_color, "drive": self._drive_color}.get(tone, self._title_color)
            top = 5 + row * 15
            left = 7
            if icon is not None and not icon.isNull():
                painter.drawPixmap(qt.QtCore.QPointF(left, top), tint_icon(icon, 12, self.devicePixelRatioF(), color))
                left += 16
            painter.setPen(self._title_color)
            room = qt.QtCore.QRectF(left, top - 1, self.width() - 29 - left, 14)
            painter.drawText(room, qt.QtCore.Qt.AlignmentFlag.AlignLeft | qt.QtCore.Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(text, qt.QtCore.Qt.TextElideMode.ElideRight,
                                                              int(room.width())))
        for row, (text, alpha) in enumerate(((self._title, 255), (self._subtitle, 150))):
            if not text or notes:
                continue
            color = qt.QtGui.QColor(self._title_color)
            color.setAlpha(alpha)
            painter.setPen(color)
            room = qt.QtCore.QRectF(7, 4 + row * 13, self.width() - 36, 14)
            painter.drawText(room, qt.QtCore.Qt.AlignmentFlag.AlignLeft | qt.QtCore.Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(text, qt.QtCore.Qt.TextElideMode.ElideRight,
                                                              int(room.width())))
        painter.end()
