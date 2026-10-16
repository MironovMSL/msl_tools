# ui/widgets/atoms/progress/spinner.py
import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class Spinner(qt.QtWidgets.QWidget):
    """"Working on it" without a number: an arc that turns round a faint ring and keeps
    growing and shrinking as it goes, so it never looks stuck.

        spinner = Spinner(16)
        spinner.show()      # it turns only while it is visible: hidden = nothing runs

    For a wait of unknown length (reading a file, a list from the internet, a Maya that is
    starting); when the share done is known, a progress bar or a RingGauge says more.

    Colors are Qt properties set by ui/theme/widgets.qss: arcColor, trackColor.
    """

    FRAME_MS = 16
    TURN_S = 1.1        # one round of the arc's head
    BREATH_S = 1.6      # one grow-and-shrink of its length
    SPAN_MIN, SPAN_MAX = 30.0, 260.0   # degrees

    arcColor = color_property("_arc_color")
    trackColor = color_property("_track_color")

    def __init__(self, size: int = 16, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._arc_color = qt.QtGui.QColor(fallback.accent)
        self._track_color = qt.QtGui.QColor(fallback.text_secondary)
        self._track_color.setAlphaF(0.2)
        self._clock = qt.QtCore.QElapsedTimer()
        self._timer = qt.QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self.update)
        self.setFixedSize(size, size)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def showEvent(self, event) -> None:
        if not self._clock.isValid():
            self._clock.start()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def angles(self, seconds: float) -> tuple[float, float]:
        """(start, span) in degrees at `seconds` since it began: the head turns at an even
        pace, the length breathes between SPAN_MIN and SPAN_MAX (eased, so it slows at both
        ends). Qt's angles: counter-clockwise, so the head goes clockwise with a minus."""
        head = -(seconds / self.TURN_S) * 360.0
        breath = 0.5 - 0.5 * math.cos(2 * math.pi * seconds / self.BREATH_S)
        span = self.SPAN_MIN + (self.SPAN_MAX - self.SPAN_MIN) * breath
        return head % 360.0, span

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        width = max(side / 8.0, 1.5)
        rect = qt.QtCore.QRectF(width / 2, width / 2, side - width, side - width)
        rect.moveCenter(qt.QtCore.QPointF(self.width() / 2, self.height() / 2))
        pen = qt.QtGui.QPen(self._track_color, width)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        start, span = self.angles(self._clock.elapsed() / 1000.0 if self._clock.isValid() else 0.0)
        pen = qt.QtGui.QPen(self._arc_color, width)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # the HEAD is at `start`; the arc trails `span` degrees behind it (counter-clockwise)
        painter.drawArc(rect, int(start * 16), int(span * 16))
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        row = qt.QtWidgets.QWidget()
        layout = qt.QtWidgets.QHBoxLayout(row)
        for size in (12, 16, 24, 40):
            layout.addWidget(Spinner(size))
        layout.addStretch(1)
        dialog.add_case("Spinner", row)
        dialog.show()
