# ui/widgets/atoms/header/update_button.py
import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class UpdateButton(qt.QtWidgets.QAbstractButton):
    """Header button that says "an update is available": a download arrow
    dropping into a tray, in the accent color. Meant to be shown only while
    there IS an update — its animation is the announcement:

    - on show it pops in (scales up with a small overshoot);
    - at rest, once every CYCLE_MS, the arrow dips into the tray twice and a
      ring spreads out from the button and fades — enough to be noticed,
      idle for most of the cycle so it doesn't nag;
    - hover lays a soft tint under it; pressed, a stronger one.

    The animation runs only while the button is visible.

    Colors are Qt properties set by ui/theme/widgets.qss: iconColor,
    ringColor, hoverColor, pressedColor. Until the stylesheet applies they
    hold the default theme's accent.
    """

    SIZE = 26
    ICON_BOX = 16.0          # the icon is drawn on a 16-unit grid, centered
    STROKE = 1.6
    CYCLE_MS = 3200
    POP_IN_MS = 380
    DIP_PX = 2.4             # how far the arrow drops on its first dip
    RING_START, RING_END = 7.0, 13.5   # ring radius, px

    iconColor = color_property("_icon_color")
    ringColor = color_property("_ring_color")
    hoverColor = color_property("_hover_color")
    pressedColor = color_property("_pressed_color")

    def __init__(self, tooltip: str = "", parent=None):
        super().__init__(parent)
        accent = qt.QtGui.QColor(ThemeRegistry.fallback().accent)  # until QSS applies
        self._icon_color = qt.QtGui.QColor(accent)
        self._ring_color = qt.QtGui.QColor(accent)
        self._ring_color.setAlphaF(0.45)
        self._hover_color = qt.QtGui.QColor(accent)
        self._hover_color.setAlphaF(0.16)
        self._pressed_color = qt.QtGui.QColor(accent)
        self._pressed_color.setAlphaF(0.28)

        self._hovered = False
        self._cycle = 0.0   # 0..1 through the idle cycle
        self._scale = 1.0   # pop-in

        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip(tooltip)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

        self._cycle_animation = qt.QtCore.QVariantAnimation(self)
        self._cycle_animation.setStartValue(0.0)
        self._cycle_animation.setEndValue(1.0)
        self._cycle_animation.setDuration(self.CYCLE_MS)
        self._cycle_animation.setLoopCount(-1)
        self._cycle_animation.valueChanged.connect(self._on_cycle)

        self._pop_animation = qt.QtCore.QVariantAnimation(self)
        self._pop_animation.setStartValue(0.0)
        self._pop_animation.setEndValue(1.0)
        self._pop_animation.setDuration(self.POP_IN_MS)
        self._pop_animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutBack)
        self._pop_animation.valueChanged.connect(self._on_pop)

    # --- animation ---------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._pop_animation.start()
        self._cycle_animation.start()

    def hideEvent(self, event) -> None:
        self._pop_animation.stop()
        self._cycle_animation.stop()
        super().hideEvent(event)

    def _on_cycle(self, value) -> None:
        self._cycle = float(value)
        self.update()

    def _on_pop(self, value) -> None:
        self._scale = float(value)
        self.update()

    def _arrow_offset(self) -> float:
        """How far the arrow is dropped right now: two dips at the start of
        the cycle (a full one, then a small echo), then still."""
        p = self._cycle
        if p < 0.16:
            return math.sin(math.pi * p / 0.16) * self.DIP_PX
        if p < 0.26:
            return math.sin(math.pi * (p - 0.16) / 0.10) * self.DIP_PX * 0.45
        return 0.0

    def _ring(self) -> tuple[float, float]:
        """(radius, opacity 0..1) of the spreading ring; opacity 0 = none."""
        p = (self._cycle - 0.04) / 0.46
        if not 0.0 <= p <= 1.0:
            return 0.0, 0.0
        eased = 1.0 - (1.0 - p) ** 2
        return self.RING_START + (self.RING_END - self.RING_START) * eased, 1.0 - p

    # --- hover ---------------------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # --- painting ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        center = qt.QtCore.QRectF(self.rect()).center()
        painter.translate(center)
        painter.scale(self._scale, self._scale)

        if self.isDown() or self._hovered:
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._pressed_color if self.isDown() else self._hover_color)
            radius = self.SIZE / 2 - 1
            painter.drawEllipse(qt.QtCore.QPointF(0, 0), radius, radius)

        ring_radius, ring_opacity = self._ring()
        if ring_opacity > 0.0 and not self._hovered:
            ring = qt.QtGui.QColor(self._ring_color)
            ring.setAlphaF(ring.alphaF() * ring_opacity)
            painter.setPen(qt.QtGui.QPen(ring, 1.2))
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawEllipse(qt.QtCore.QPointF(0, 0), ring_radius, ring_radius)

        pen = qt.QtGui.QPen(self._icon_color, self.STROKE)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        half = self.ICON_BOX / 2

        def point(x: float, y: float) -> qt.QtCore.QPointF:
            return qt.QtCore.QPointF(x - half, y - half)

        # Tray: stays put.
        painter.drawPolyline([point(3, 10.6), point(3, 13.4), point(13, 13.4), point(13, 10.6)])
        # Arrow: shaft + head, dropping by the current offset.
        dy = self._arrow_offset()
        painter.drawLine(point(8, 2.4 + dy), point(8, 9.6 + dy))
        painter.drawPolyline([point(5.1, 6.9 + dy), point(8, 9.8 + dy), point(10.9, 6.9 + dy)])
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        button = UpdateButton("Update available: v0.2.0")
        button.clicked.connect(lambda: print("update clicked"))
        dialog.add_case("UpdateButton", button)
        dialog.show()
