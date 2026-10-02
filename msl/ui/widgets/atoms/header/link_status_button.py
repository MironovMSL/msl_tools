# ui/widgets/atoms/header/link_status_button.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class LinkStatusButton(qt.QtWidgets.QAbstractButton):
    """Header indicator of a live connection service: a status dot and the
    number of connected peers, clickable.

        off        a hollow ring, dimmed     the service isn't running
        on         a filled dot              running (the number next to it: who is connected)
        attention  a filled dot, alert tone  something needs a look (it pulses once a few seconds)

    It only shows what it is told (set_state()); the owner decides what the
    states mean, sets the tooltip and handles the click. In the hub: the
    hub <-> Maya link (run_hub.py) — listening or not, how many Mayas are
    connected, and whether one of them reported an error not looked at yet.

    Colors are Qt properties set by ui/theme/widgets.qss: onColor, offColor,
    attentionColor, textColor, hoverColor, pressedColor.
    """

    HEIGHT = 26
    DOT = 8.0
    PADDING = 8
    GAP = 5
    PULSE_MS = 2600

    OFF, ON, ATTENTION = "off", "on", "attention"

    onColor = color_property("_on_color")
    offColor = color_property("_off_color")
    attentionColor = color_property("_attention_color")
    textColor = color_property("_text_color")
    hoverColor = color_property("_hover_color")
    pressedColor = color_property("_pressed_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._on_color = qt.QtGui.QColor(fallback.success)
        self._off_color = qt.QtGui.QColor(fallback.text_secondary)
        self._attention_color = qt.QtGui.QColor(fallback.error)
        self._text_color = qt.QtGui.QColor(fallback.text_secondary)
        self._hover_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._pressed_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._state = self.OFF
        self._count = 0
        self._hovered = False
        self._pulse = 0.0  # 0..1 through one pulse cycle (attention only)

        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._pulse_animation = qt.QtCore.QVariantAnimation(self)
        self._pulse_animation.setStartValue(0.0)
        self._pulse_animation.setEndValue(1.0)
        self._pulse_animation.setDuration(self.PULSE_MS)
        self._pulse_animation.setLoopCount(-1)
        self._pulse_animation.valueChanged.connect(self._on_pulse)
        self._resize()

    # --- state -------------------------------------------------------------------

    def set_state(self, state: str, count: int = 0) -> None:
        """`state`: OFF / ON / ATTENTION; `count`: the number shown next to
        the dot (hidden when 0)."""
        if (state, count) == (self._state, self._count):
            return
        self._state, self._count = state, max(int(count), 0)
        self._resize()
        self._sync_pulse()
        self.update()

    def state(self) -> str:
        return self._state

    def _text(self) -> str:
        return str(self._count) if self._count else ""

    def _resize(self) -> None:
        text_width = self.fontMetrics().horizontalAdvance(self._text()) if self._count else 0
        width = self.PADDING * 2 + int(self.DOT) + (self.GAP + text_width if text_width else 0)
        self.setFixedSize(width, self.HEIGHT)

    def _sync_pulse(self) -> None:
        wanted = self._state == self.ATTENTION and self.isVisible()
        running = self._pulse_animation.state() == qt.QtCore.QAbstractAnimation.State.Running
        if wanted and not running:
            self._pulse_animation.start()
        elif not wanted and running:
            self._pulse_animation.stop()
            self._pulse = 0.0

    def _on_pulse(self, value) -> None:
        self._pulse = float(value)
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_pulse()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._sync_pulse()

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
        rect = qt.QtCore.QRectF(self.rect())

        if self.isDown() or self._hovered:
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._pressed_color if self.isDown() else self._hover_color)
            painter.drawRoundedRect(rect.adjusted(0, 2, 0, -2), 5, 5)

        center = qt.QtCore.QPointF(self.PADDING + self.DOT / 2, rect.center().y())
        radius = self.DOT / 2
        color = {self.ON: self._on_color, self.ATTENTION: self._attention_color}.get(self._state, self._off_color)
        if self._state == self.OFF:
            painter.setPen(qt.QtGui.QPen(color, 1.4))
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius - 0.7, radius - 0.7)
        else:
            if self._state == self.ATTENTION and self._pulse < 0.45:
                # A ring spreads from the dot and fades, in the first part of each cycle.
                progress = self._pulse / 0.45
                ring = qt.QtGui.QColor(color)
                ring.setAlphaF(0.55 * (1.0 - progress))
                painter.setPen(qt.QtGui.QPen(ring, 1.4))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
                spread = radius + 1.0 + 5.0 * progress
                painter.drawEllipse(center, spread, spread)
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(center, radius, radius)

        if self._count:
            painter.setPen(self._text_color)
            text_rect = rect.adjusted(self.PADDING + self.DOT + self.GAP, 0, -self.PADDING + 2, 0)
            painter.drawText(text_rect, int(qt.QtCore.Qt.AlignmentFlag.AlignVCenter | qt.QtCore.Qt.AlignmentFlag.AlignLeft),
                             self._text())
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        for label, state, count in (("off", LinkStatusButton.OFF, 0), ("on, nobody", LinkStatusButton.ON, 0),
                                    ("on, 2 connected", LinkStatusButton.ON, 2),
                                    ("attention", LinkStatusButton.ATTENTION, 3)):
            button = LinkStatusButton()
            button.set_state(state, count)
            dialog.add_case(label, button)
        dialog.show()
