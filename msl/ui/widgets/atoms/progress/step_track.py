# ui/widgets/atoms/progress/step_track.py
import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property

WAITING, RUNNING, ERROR, DONE = "waiting", "running", "error", "done"


def _round_pen(color: qt.QtGui.QColor, width: float) -> qt.QtGui.QPen:
    """A pen with round ends (PySide6's QPen takes no `cap=` keyword: it raised inside
    paintEvent with the painter active, and that took the process down)."""
    pen = qt.QtGui.QPen(color, width)
    pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
    return pen


class StepTrack(qt.QtWidgets.QWidget):
    """The stages of one piece of work in a row: ① Read — ② Open — ③ Render — ④ Video.

        track.set_steps(["Read", "Open", "Render", "Video"])
        track.set_stage(2, "running")     # 1 and 2 done (ticked), 3 at work, 4 to come
        track.set_stage(4, "done")        # all four ticked

    A step before the current one is done: a filled circle with a tick. The current one is
    "running" (a ring that breathes, its number in the accent), "error" (filled in the error
    color with "!") or "waiting" (nothing at work: the track stands there). A line joins the
    circles; its filled part GLIDES to the current step. The labels sit under the circles.

    It only shows what it is told; the owner decides what the stages mean.
    Colors are Qt properties set by ui/theme/widgets.qss: activeColor, markColor, quietColor,
    errorColor, textColor, quietTextColor.
    """

    DOT = 18          # circle diameter
    LABEL_GAP = 4
    GLIDE_MS = 420
    FRAME_MS = 33

    activeColor = color_property("_active_color")
    markColor = color_property("_mark_color")
    quietColor = color_property("_quiet_color")
    errorColor = color_property("_error_color")
    textColor = color_property("_text_color")
    quietTextColor = color_property("_quiet_text_color")

    def __init__(self, steps=(), parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._active_color = qt.QtGui.QColor(fallback.accent)
        self._mark_color = qt.QtGui.QColor("#ffffff")
        self._quiet_color = qt.QtGui.QColor(fallback.text_secondary)
        self._error_color = qt.QtGui.QColor(fallback.error)
        self._text_color = qt.QtGui.QColor(fallback.text_primary)
        self._quiet_text_color = qt.QtGui.QColor(fallback.text_secondary)
        self._steps: list[str] = []
        self._index = 0
        self._state = WAITING
        self._fill = 0.0      # where the filled line ends, in steps (0 = the first circle)
        self._glide = qt.QtCore.QVariantAnimation(self)
        self._glide.setDuration(self.GLIDE_MS)
        self._glide.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._glide.valueChanged.connect(self._on_glide)
        self._clock = qt.QtCore.QElapsedTimer()
        self._clock.start()
        self._pulse = qt.QtCore.QTimer(self)
        self._pulse.setInterval(self.FRAME_MS)
        self._pulse.timeout.connect(self.update)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding, qt.QtWidgets.QSizePolicy.Policy.Fixed)
        self.set_steps(steps)

    # --- what it shows ----------------------------------------------------------------

    def set_steps(self, steps) -> None:
        steps = [str(step) for step in steps]
        if steps == self._steps:
            return
        self._steps = steps
        self._index = min(self._index, len(steps))
        self._fill = float(min(self._index, max(len(steps) - 1, 0)))
        self.updateGeometry()
        self.update()

    def steps(self) -> list[str]:
        return list(self._steps)

    def stage(self) -> tuple[int, str]:
        return self._index, self._state

    def set_stage(self, index: int, state: str = RUNNING, animate: bool = True) -> None:
        """Step `index` (0-based) is where the work is, in `state`; every step before it is
        done. `index` == the number of steps (with "done") = all of them are done."""
        index = max(0, min(int(index), len(self._steps)))
        state = state if state in (WAITING, RUNNING, ERROR, DONE) else WAITING
        if (index, state) == (self._index, self._state):
            return
        self._index, self._state = index, state
        target = float(min(index, max(len(self._steps) - 1, 0)))
        self._glide.stop()
        if animate and self.isVisible() and target != self._fill:
            self._glide.setStartValue(self._fill)
            self._glide.setEndValue(target)
            self._glide.start()
        else:
            self._fill = target
        self._sync_pulse()
        self.update()

    def _on_glide(self, value) -> None:
        self._fill = float(value)
        self.update()

    def _sync_pulse(self) -> None:
        running = self._state == RUNNING and self._index < len(self._steps) and self.isVisible()
        if running and not self._pulse.isActive():
            self._pulse.start()
        elif not running:
            self._pulse.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_pulse()

    def hideEvent(self, event) -> None:
        self._pulse.stop()
        super().hideEvent(event)

    def step_state(self, index: int) -> str:
        """What step `index` shows now: done, the current state, or waiting (to come)."""
        if index < self._index or (self._state == DONE and index < len(self._steps)):
            return DONE
        if index == self._index:
            return self._state
        return WAITING

    # --- size and painting --------------------------------------------------------------

    def sizeHint(self) -> qt.QtCore.QSize:
        metrics = qt.QtGui.QFontMetrics(self.font())
        widest = max((metrics.horizontalAdvance(step) for step in self._steps), default=0)
        width = max(len(self._steps) * (widest + 16), 120)
        return qt.QtCore.QSize(width, self.DOT + self.LABEL_GAP + metrics.height() + 2)

    def minimumSizeHint(self) -> qt.QtCore.QSize:
        metrics = qt.QtGui.QFontMetrics(self.font())
        return qt.QtCore.QSize(len(self._steps) * (self.DOT + 12),
                               self.DOT + self.LABEL_GAP + metrics.height() + 2)

    def centers(self) -> list[float]:
        """The x of each circle: evenly over the width, the outer ones half a cell in."""
        count = len(self._steps)
        if not count:
            return []
        cell = self.width() / count
        return [cell * (i + 0.5) for i in range(count)]

    def paintEvent(self, event) -> None:
        if not self._steps:
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        centers = self.centers()
        radius = self.DOT / 2.0
        y = radius + 1.0

        # the line BETWEEN the circles: quiet, filled up to where the work is (gliding)
        quiet = qt.QtGui.QColor(self._quiet_color)
        quiet.setAlphaF(quiet.alphaF() * 0.35)
        for index in range(len(centers) - 1):
            x0, x1 = centers[index] + radius + 3.0, centers[index + 1] - radius - 3.0
            if x1 <= x0:
                continue
            painter.setPen(_round_pen(quiet, 2.0))
            painter.drawLine(qt.QtCore.QPointF(x0, y), qt.QtCore.QPointF(x1, y))
            share = max(0.0, min(self._fill - index, 1.0))
            if share > 0:
                painter.setPen(_round_pen(self._active_color, 2.0))
                painter.drawLine(qt.QtCore.QPointF(x0, y), qt.QtCore.QPointF(x0 + (x1 - x0) * share, y))

        number_font = qt.QtGui.QFont(self.font())
        if number_font.pointSizeF() > 0:
            number_font.setPointSizeF(max(number_font.pointSizeF() - 1.5, 6.0))
        number_font.setWeight(qt.QtGui.QFont.Weight.DemiBold)
        label_font = qt.QtGui.QFont(self.font())
        current_label = qt.QtGui.QFont(label_font)
        current_label.setWeight(qt.QtGui.QFont.Weight.DemiBold)
        metrics = qt.QtGui.QFontMetrics(label_font)
        seconds = self._clock.elapsed() / 1000.0

        for index, (x, label) in enumerate(zip(centers, self._steps)):
            state = self.step_state(index)
            circle = qt.QtCore.QRectF(x - radius, y - radius, self.DOT, self.DOT)
            if state == DONE:
                painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(self._active_color)
                painter.drawEllipse(circle)
                self._tick(painter, circle)
            elif state == ERROR:
                painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(self._error_color)
                painter.drawEllipse(circle)
                painter.setPen(self._mark_color)
                painter.setFont(number_font)
                painter.drawText(circle, int(qt.QtCore.Qt.AlignmentFlag.AlignCenter), "!")
            else:
                running = state == RUNNING
                if running:   # a soft halo that breathes
                    breath = 0.5 - 0.5 * math.cos(2 * math.pi * seconds / 1.4)
                    halo = qt.QtGui.QColor(self._active_color)
                    halo.setAlphaF(halo.alphaF() * (0.10 + 0.22 * breath))
                    painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
                    painter.setBrush(halo)
                    grow = 2.0 + 2.5 * breath
                    painter.drawEllipse(circle.adjusted(-grow, -grow, grow, grow))
                ring = qt.QtGui.QColor(self._active_color if running else self._quiet_color)
                if not running:
                    ring.setAlphaF(ring.alphaF() * 0.7)
                painter.setPen(qt.QtGui.QPen(ring, 2.0 if running else 1.5))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(circle.adjusted(1, 1, -1, -1))
                painter.setPen(ring)
                painter.setFont(number_font)
                painter.drawText(circle, int(qt.QtCore.Qt.AlignmentFlag.AlignCenter), str(index + 1))

            current = index == self._index and state in (RUNNING, ERROR, WAITING) and self._state != DONE
            painter.setFont(current_label if current else label_font)
            color = self._error_color if state == ERROR else (self._text_color if current or state == DONE
                                                              else self._quiet_text_color)
            painter.setPen(color)
            cell = self.width() / len(self._steps)
            text_rect = qt.QtCore.QRectF(x - cell / 2, self.DOT + self.LABEL_GAP, cell, metrics.height() + 2)
            text = metrics.elidedText(label, qt.QtCore.Qt.TextElideMode.ElideRight, int(cell) - 4)
            painter.drawText(text_rect, int(qt.QtCore.Qt.AlignmentFlag.AlignHCenter | qt.QtCore.Qt.AlignmentFlag.AlignTop),
                             text)
        painter.end()

    def _tick(self, painter: qt.QtGui.QPainter, circle: qt.QtCore.QRectF) -> None:
        pen = qt.QtGui.QPen(self._mark_color, 1.8)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        c, s = circle.center(), circle.width() / 18.0
        path = qt.QtGui.QPainterPath(qt.QtCore.QPointF(c.x() - 4.0 * s, c.y() + 0.2 * s))
        path.lineTo(c.x() - 1.2 * s, c.y() + 3.0 * s)
        path.lineTo(c.x() + 4.2 * s, c.y() - 3.2 * s)
        painter.drawPath(path)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        for index, state in ((0, RUNNING), (2, RUNNING), (2, ERROR), (4, DONE)):
            track = StepTrack(["Read", "Open", "Render", "Video"])
            track.set_stage(index, state, animate=False)
            dialog.add_case(f"StepTrack {index} {state}", track)
        dialog.show()
