# ui/widgets/atoms/charts/bar_strip.py
from typing import Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class BarStrip(qt.QtWidgets.QWidget):
    """A strip of thin vertical bars: how one number went over a handful of
    measurements, at a glance (oldest on the left). Each bar is in one of two
    tones — the accent or the muted one — and names itself in a tooltip.

        strip.set_bars([(52.0, False, "52.0 s without boost"), (28.0, True, "28.0 s with boost")])

    Bars are scaled from zero to the largest value, so heights compare
    honestly. The widget is as wide as its bars; no axes, no numbers — the
    numbers belong to the text next to it.

    Colors are Qt properties set by ui/theme/widgets.qss: accentColor,
    mutedColor.
    """

    BAR_WIDTH = 6
    GAP = 3
    HEIGHT = 30
    MIN_BAR = 2

    accentColor = color_property("_accent_color")
    mutedColor = color_property("_muted_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._accent_color = qt.QtGui.QColor(fallback.accent)
        self._muted_color = qt.QtGui.QColor(fallback.text_secondary)
        self._bars: list[tuple[float, bool, str]] = []
        self._hovered = -1
        self.setMouseTracking(True)
        self.setFixedSize(0, self.HEIGHT)

    def set_bars(self, bars: Sequence[tuple[float, bool, str]]) -> None:
        """`bars`: (value, accent tone?, tooltip) — left to right."""
        self._bars = [(max(float(value), 0.0), bool(accent), str(tip)) for value, accent, tip in bars]
        self._hovered = -1
        count = len(self._bars)
        self.setFixedSize(max(count * (self.BAR_WIDTH + self.GAP) - self.GAP, 0), self.HEIGHT)
        self.update()

    def bars(self) -> list[tuple[float, bool, str]]:
        return list(self._bars)

    def _bar_at(self, x: float) -> int:
        index = int(x // (self.BAR_WIDTH + self.GAP))
        return index if 0 <= index < len(self._bars) else -1

    def mouseMoveEvent(self, event) -> None:
        hovered = self._bar_at(event.position().x())
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = -1
        self.update()
        super().leaveEvent(event)

    def event(self, event) -> bool:
        if event.type() == qt.QtCore.QEvent.Type.ToolTip:
            index = self._bar_at(event.pos().x())
            if index >= 0:
                qt.QtWidgets.QToolTip.showText(event.globalPos(), self._bars[index][2], self)
            else:
                qt.QtWidgets.QToolTip.hideText()
            return True
        return super().event(event)

    def paintEvent(self, event) -> None:
        if not self._bars:
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        top = max(value for value, _accent, _tip in self._bars) or 1.0
        for index, (value, accent, _tip) in enumerate(self._bars):
            height = max(self.MIN_BAR, round(value / top * self.height()))
            color = qt.QtGui.QColor(self._accent_color if accent else self._muted_color)
            if self._hovered >= 0 and index != self._hovered:
                color.setAlphaF(color.alphaF() * 0.45)  # the bar under the pointer stands out
            painter.setBrush(color)
            rect = qt.QtCore.QRectF(index * (self.BAR_WIDTH + self.GAP), self.height() - height,
                                    self.BAR_WIDTH, height)
            painter.drawRoundedRect(rect, 1.5, 1.5)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        strip = BarStrip()
        strip.set_bars([(52, False, "52 s"), (48, False, "48 s"), (30, True, "30 s"), (28, True, "28 s"),
                        (51, False, "51 s"), (27.5, True, "27.5 s")])
        dialog.add_case("BarStrip", strip)
        dialog.show()
