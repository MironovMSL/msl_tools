# ui/widgets/atoms/sliders/blend_slider.py
import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


def _square(position: float, limit: float) -> float:
    return math.copysign(position * position * limit, position)


def _square_root(weight: float, limit: float) -> float:
    part = max(-1.0, min(1.0, weight / limit)) if limit else 0.0
    return math.copysign(math.sqrt(abs(part)), part)


class BlendSlider(qt.QtWidgets.QWidget):
    """A slider that is pulled, not set: a knob in the middle of a track, dragged left or right
    and let go - it springs back to the middle. It sends a WEIGHT, -limit .. limit (0 = the
    middle); how the weight grows along the track while it is dragged is the owner's (`to_weight`
    / `to_position`, by default with the square of the distance: fine near the middle, fast at
    the ends).

    At rest the track is a thin strip under the knob (its marks there to click). With the knob held
    it grows to its full height (animated), the marks but the ends fade out and, once it is dragged,
    the number is written in it; it goes thin again once the knob is back in the middle.

    MARKS (`set_marks`: weights) are STEPS, not places on that scale: each side's marks stand at
    even distances from the middle up to where a full weight (1) lies, the smallest nearest the
    middle - so 1/8, 1/6, 1/4, 1/3 of a tween machine read as four even steps. A hovered one grows.
    A CLICK (press and let go without moving) sends a weight and shows nothing more - the change is
    seen in the scene: a mark's weight, the weight under the pointer elsewhere on the track, 0 on
    the knob. The knob shows a short text (`set_label`) and keeps its small size; the NUMBER while
    it is dragged - `format_weight(weight)`, the owner's - is written inside the track at the end
    AWAY from the knob (dragged right: on the left), never under the pointer.

    Signals:
        drag_started(str)     the press - the modifiers held then ("ctrl+shift"), for the owner to
                              pick what the drag does before anything moves
        dragged(float)        each move, the weight now (and once at a press on the knob: its weight there)
        drag_finished(float)  let go (also after a click: the weight clicked)
        cancelled()           Esc during the drag (the owner puts things back)
        menu_requested(QPoint) a right click, at this global position

    Colors are Qt properties set by ui/theme/widgets.qss (`BlendSlider[tone=...]` gives the fill):
    trackColor, trackTopColor, markColor, fillColor, knobColor, knobTopColor, knobTextColor,
    borderColor.
    """

    drag_started = qt.QtCore.Signal(str)
    dragged = qt.QtCore.Signal(float)
    drag_finished = qt.QtCore.Signal(float)
    cancelled = qt.QtCore.Signal()
    menu_requested = qt.QtCore.Signal(qt.QtCore.QPoint)

    trackColor = color_property("_track")
    trackTopColor = color_property("_track_top")
    markColor = color_property("_mark")
    fillColor = color_property("_fill")
    knobColor = color_property("_knob")
    knobTopColor = color_property("_knob_top")
    knobTextColor = color_property("_knob_text")
    borderColor = color_property("_border")

    HEIGHT = 24
    KNOB_WIDTH = 26
    CLICK_DISTANCE = 4      # pixels a press may move and still be a click
    MARK_REACH = 7          # pixels around a mark a click still snaps to it
    SPRING_MS = 180
    OPEN_MS = 140           # the track opening / closing
    CLOSE_DELAY_MS = 120    # after the knob is back in the middle, the track closes this much later
    THIN = 8                # the track's height at rest

    def __init__(self, parent=None, to_weight=None, to_position=None):
        super().__init__(parent)
        theme = ThemeRegistry.fallback()  # until QSS applies
        self._track = qt.QtGui.QColor(theme.surface)
        self._track_top = qt.QtGui.QColor(theme.surface)
        self._mark = qt.QtGui.QColor(theme.text_secondary)
        self._fill = qt.QtGui.QColor(theme.accent)
        self._knob = qt.QtGui.QColor(theme.surface)
        self._knob_top = qt.QtGui.QColor(theme.surface)
        self._knob_text = qt.QtGui.QColor(theme.text_primary)
        self._border = qt.QtGui.QColor(theme.border)
        self._to_weight = to_weight or _square
        self._to_position = to_position or _square_root
        self._limit = 1.0
        self._marks = (-1.0, -0.75, -0.5, -0.25, 0.25, 0.5, 0.75, 1.0)
        self._label = ""
        self.format_weight = lambda weight: f"{weight * 100:+.0f}"
        self._position = 0.0        # where the knob is, -1 .. 1 along the track
        self._press = None          # the press's x, or None
        self._dragging = False
        self._hovered = None        # (position, weight) of the mark under the pointer
        self._pressed_mark = None   # (position, weight) of the mark held down
        self._spring = qt.QtCore.QVariantAnimation(self)
        self._spring.setDuration(self.SPRING_MS)
        self._spring.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._spring.valueChanged.connect(self._sprung)
        # how far the track is open: 0 = a thin strip under the knob (at rest), 1 = its full height
        # (while the knob is held / dragged: the number is written in it then)
        self._open = 0.0
        self._opening = qt.QtCore.QVariantAnimation(self)
        self._opening.setDuration(self.OPEN_MS)
        self._opening.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._opening.valueChanged.connect(self._opened)
        self._closing = qt.QtCore.QTimer(self)
        self._closing.setSingleShot(True)
        self._closing.setInterval(self.CLOSE_DELAY_MS)
        self._closing.timeout.connect(lambda: self._open_to(0.0))
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

    # ------------------------------------------------------------------ what it shows

    def set_label(self, text: str) -> None:
        self._label = text or ""
        self.update()

    def set_marks(self, weights) -> None:
        marks = tuple(float(weight) for weight in weights if abs(float(weight)) > 1e-9)
        if marks == self._marks:
            return                   # the same (the owner shows its mode again on a press): keep the hover
        self._marks = marks
        self._hovered = None
        self._pressed_mark = None
        self.update()

    def set_limit(self, limit: float) -> None:
        """The weight at either end (2 = overshoot past the targets)."""
        self._limit = max(0.01, float(limit))
        self.update()

    def limit(self) -> float:
        return self._limit

    def is_dragging(self) -> bool:
        return self._press is not None

    def mark_positions(self) -> list:
        """[(position -1..1, weight)] of the marks: even steps on each side, up to where a full
        weight lies on the drag's scale (the end of the track without overshoot)."""
        reach = abs(self._to_position(1.0, self._limit)) or 1.0
        placed = []
        for sign in (-1.0, 1.0):
            side = sorted((weight for weight in self._marks if weight * sign > 0), key=abs)
            for step, weight in enumerate(side, start=1):
                placed.append((sign * reach * step / len(side), weight))
        return placed

    # ------------------------------------------------------------------ geometry

    def _half(self) -> float:
        return max(1.0, (self.width() - self.KNOB_WIDTH) / 2.0)

    def _centre(self) -> float:
        return self.width() / 2.0

    def _x_of(self, position: float) -> float:
        return self._centre() + position * self._half()

    def _position_at(self, x: float) -> float:
        return max(-1.0, min(1.0, (x - self._centre()) / self._half()))

    def _weight(self, position: float) -> float:
        return self._to_weight(position, self._limit)

    def _mark_at(self, x: float):
        if abs(x - self._centre()) <= self.KNOB_WIDTH / 2.0:
            return None
        near = [(abs(self._x_of(position) - x), position, weight) for position, weight in self.mark_positions()]
        if near:
            distance, position, weight = min(near)
            if distance <= self.MARK_REACH:
                return position, weight
        return None

    # ------------------------------------------------------------------ the mouse

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._spring.stop()
        self._press = event.position().x()
        self._dragging = False
        self._pressed_mark = self._mark_at(self._press)   # a mark pressed: it shows it, the knob doesn't
        self._closing.stop()
        if abs(self._press - self._centre()) <= self.KNOB_WIDTH / 2.0:
            self._open_to(1.0)       # the knob held: the track opens; a press on a mark doesn't
        modifiers = event.modifiers()
        names = [name for flag, name in ((qt.QtCore.Qt.KeyboardModifier.ControlModifier, "ctrl"),
                                         (qt.QtCore.Qt.KeyboardModifier.AltModifier, "alt"),
                                         (qt.QtCore.Qt.KeyboardModifier.ShiftModifier, "shift"))
                 if modifiers & flag]
        self.grabKeyboard()
        self.update()
        self.drag_started.emit("+".join(names))
        if self._pressed_mark is None and abs(self._press - self._centre()) <= self.KNOB_WIDTH / 2.0:
            # the knob held: what its place means is shown at once (a Tweener's half way), not only
            # when it is let go - the reference does the same
            self.dragged.emit(self._weight(self._position))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._press is None:
            hovered = self._mark_at(x)
            if hovered != self._hovered:
                self._hovered = hovered
                self.update()
            return super().mouseMoveEvent(event)
        if not self._dragging and abs(x - self._press) < self.CLICK_DISTANCE:
            return
        self._dragging = True
        self._pressed_mark = None        # dragged away from a mark: an ordinary drag of the knob
        self._open_to(1.0)
        self._hovered = None
        self._position = self._position_at(x)
        self.update()
        self.dragged.emit(self._weight(self._position))

    def mouseReleaseEvent(self, event) -> None:
        if self._press is None or event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        x = event.position().x()
        if self._dragging:
            weight = self._weight(self._position_at(x))
            self._release()
            self._spring_back()
        else:
            # a click sends its weight and shows nothing more: the change is seen in the scene
            mark = self._mark_at(x)
            if mark is not None:
                weight = mark[1]
            elif abs(x - self._centre()) <= self.KNOB_WIDTH / 2.0:
                weight = 0.0
            else:
                weight = self._weight(self._position_at(x))
            self._release()
            self._spring_back()
        self.drag_finished.emit(weight)

    def leaveEvent(self, event) -> None:
        if self._hovered is not None:
            self._hovered = None
            self.update()
        super().leaveEvent(event)

    def _open_to(self, value: float) -> None:
        if self._press is not None and value < 1.0:
            return
        if abs(self._open - value) < 1e-6 and self._opening.state() != qt.QtCore.QAbstractAnimation.State.Running:
            return
        self._opening.stop()
        self._opening.setStartValue(float(self._open))
        self._opening.setEndValue(float(value))
        self._opening.start()

    def _opened(self, value) -> None:
        self._open = float(value)
        self.update()

    def keyPressEvent(self, event) -> None:
        if self._press is not None and event.key() == qt.QtCore.Qt.Key.Key_Escape:
            self._release()
            self._spring_back()
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def _release(self) -> None:
        self._press = None
        self._dragging = False
        self._pressed_mark = None
        self.releaseKeyboard()

    def _spring_back(self) -> None:
        self._spring.stop()
        if abs(self._position) < 1e-6:          # already in the middle: nothing to spring, only close
            self._closing.start()
            self.update()
            return
        self._spring.setStartValue(float(self._position))
        self._spring.setEndValue(0.0)
        self._spring.start()
        self.update()

    def _sprung(self, value) -> None:
        self._position = float(value)
        if self._press is None and abs(self._position) < 1e-6:
            self._closing.start()     # back in the middle: the track goes thin again
        self.update()

    # ------------------------------------------------------------------ painting

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        whole = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        height = self.THIN + (whole.height() - self.THIN) * self._open
        rect = qt.QtCore.QRectF(whole.left(), whole.center().y() - height / 2.0, whole.width(), height)
        radius = rect.height() / 2.0
        groove = qt.QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        groove.setColorAt(0.0, self._track_top)
        groove.setColorAt(1.0, self._track)
        painter.setPen(qt.QtGui.QPen(self._border, 1.0))
        painter.setBrush(groove)
        painter.drawRoundedRect(rect, radius, radius)

        middle_y = rect.center().y()
        knob_x = self._x_of(self._position)
        if abs(knob_x - self._centre()) > 0.5:      # the stretch from the middle to the knob
            fill = qt.QtGui.QColor(self._fill)
            fill.setAlphaF(0.35)
            left, right = sorted((self._centre(), knob_x))
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            inset = min(3.0, rect.height() / 4.0)
            painter.drawRoundedRect(qt.QtCore.QRectF(left, rect.top() + inset, right - left,
                                                     rect.height() - 2 * inset), 3, 3)

        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        for position, weight in self.mark_positions():
            x = self._x_of(position)
            hovered = self._hovered is not None and abs(self._hovered[0] - position) < 1e-9
            pressed = self._pressed_mark is not None and abs(self._pressed_mark[0] - position) < 1e-9
            if abs(abs(weight) - 1.0) < 1e-6:          # a full weight: a square
                painter.setBrush(self._fill)
                size = 8.0 if pressed else 7.0 if hovered else 6.0
                painter.drawRoundedRect(qt.QtCore.QRectF(x - size / 2, middle_y - size / 2, size, size), 1.2, 1.2)
            else:
                # pressed, the marks fade out as the track grows (only the ends are kept), and come
                # back as it goes thin again
                fade = 1.0 - self._open
                if fade < 0.02:
                    continue
                color = qt.QtGui.QColor(self._fill if (hovered or pressed) else self._mark)
                color.setAlphaF(color.alphaF() * fade)
                painter.setBrush(color)
                size = 3.4 if pressed else 2.8 if hovered else 1.7
                painter.drawEllipse(qt.QtCore.QPointF(x, middle_y), size, size)

        # the number (while dragged) is written INSIDE the track at the end away from the
        # knob - the knob keeps the mode's letters and its small size. Not for a mark merely hovered:
        # on the way to the knob the pointer crosses marks, and numbers would flicker.
        number, side = None, 0.0
        if self._dragging:
            number, side = self.format_weight(self._weight(self._position)), self._position
        font = painter.font()
        font.setPointSizeF(max(6.5, font.pointSizeF() - 1.5))
        font.setBold(True)
        painter.setFont(font)
        if number and self._open > 0.6:
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(number) + 12.0
            inner = rect.adjusted(radius - 2, 3, -(radius - 2), -3)
            left = inner.left() if side > 0 else inner.right() - width
            plate = qt.QtCore.QRectF(left, inner.top(), width, inner.height())
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._track)
            painter.drawRoundedRect(plate, 4, 4)
            painter.setPen(self._fill)
            painter.drawText(plate, qt.QtCore.Qt.AlignmentFlag.AlignCenter, number)

        knob = qt.QtCore.QRectF(knob_x - self.KNOB_WIDTH / 2.0, whole.top() + 2, self.KNOB_WIDTH, whole.height() - 4)
        face = qt.QtGui.QLinearGradient(knob.topLeft(), knob.bottomLeft())
        face.setColorAt(0.0, self._knob_top)
        face.setColorAt(1.0, self._knob)
        lit = self._press is not None and self._pressed_mark is None   # a held mark lights itself
        painter.setPen(qt.QtGui.QPen(self._fill if lit else self._border, 1.0))
        painter.setBrush(face)
        painter.drawRoundedRect(knob, 5, 5)
        if self._label:
            painter.setPen(self._fill if lit else self._knob_text)
            painter.drawText(knob, qt.QtCore.Qt.AlignmentFlag.AlignCenter, self._label)
        painter.end()
