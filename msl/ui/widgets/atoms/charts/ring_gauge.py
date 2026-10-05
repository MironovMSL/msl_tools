# ui/widgets/atoms/charts/ring_gauge.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class RingGauge(qt.QtWidgets.QWidget):
    """How far something is, as a ring that fills clockwise from the top, with a short value in its
    middle ("62%", "1/3") and a caption under it ("frames 248 / 400").

        gauge.set_value(0.62, "62%", "frames 248 / 400")

    The ring moves smoothly to a new value. Colors are Qt properties set from QSS (trackColor,
    fillColor, textColor, captionColor) — ui/theme/widgets.qss.
    """

    RING = 64
    WIDTH = 6
    ANIMATION_MS = 350

    trackColor = color_property("_track_color")
    fillColor = color_property("_fill_color")
    textColor = color_property("_text_color")
    captionColor = color_property("_caption_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._track_color = qt.QtGui.QColor(fallback.border)
        self._fill_color = qt.QtGui.QColor(fallback.accent)
        self._text_color = qt.QtGui.QColor(fallback.text_primary)
        self._caption_color = qt.QtGui.QColor(fallback.text_secondary)
        self._value = 0.0
        self._shown = 0.0
        self._text = ""
        self._caption = ""
        self._animation = qt.QtCore.QVariantAnimation(self)
        self._animation.setDuration(self.ANIMATION_MS)
        self._animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_frame)
        self.setFixedSize(self.RING + 56, self.RING + 22)

    def set_value(self, fraction: float, text: str, caption: str = "") -> None:
        fraction = min(max(float(fraction), 0.0), 1.0)
        self._text, self._caption = text, caption
        self.setToolTip(caption)
        if abs(fraction - self._value) > 1e-4:
            self._value = fraction
            self._animation.stop()
            self._animation.setStartValue(float(self._shown))
            self._animation.setEndValue(fraction)
            self._animation.start()
        self.update()

    def value(self) -> float:
        return self._value

    def _on_frame(self, value) -> None:
        self._shown = float(value)
        self.update()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        side = self.RING
        rect = qt.QtCore.QRectF((self.width() - side) / 2 + self.WIDTH / 2, self.WIDTH / 2,
                                side - self.WIDTH, side - self.WIDTH)
        pen = qt.QtGui.QPen(self._track_color, self.WIDTH)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        if self._shown > 0.001:
            pen.setColor(self._fill_color)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, int(-self._shown * 360 * 16))
        font = painter.font()
        font.setPixelSize(14)
        font.setWeight(qt.QtGui.QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(self._text_color)
        painter.drawText(rect, int(qt.QtCore.Qt.AlignmentFlag.AlignCenter), self._text)
        font.setPixelSize(11)
        font.setWeight(qt.QtGui.QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(self._caption_color)
        caption_rect = qt.QtCore.QRectF(0, side + 4, self.width(), self.height() - side - 4)
        metrics = qt.QtGui.QFontMetrics(font)
        painter.drawText(caption_rect, int(qt.QtCore.Qt.AlignmentFlag.AlignHCenter | qt.QtCore.Qt.AlignmentFlag.AlignTop),
                         metrics.elidedText(self._caption, qt.QtCore.Qt.TextElideMode.ElideRight, self.width()))
        painter.end()
