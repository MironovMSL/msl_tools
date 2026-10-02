# ui/widgets/atoms/buttons/motion_icon_button.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.atoms.icons.motion_icons import DEFAULT_DURATION, DURATIONS, MOTION_ICONS, paint_motion_icon


class MotionIconButton(qt.QtWidgets.QPushButton):
    """A button whose icon MOVES: one of the motion icons (atoms/icons/
    motion_icons.py — scissors that snip, a loop that turns, ...), played
    once when the pointer comes over the button and when play() is called
    (e.g. when it is picked). The animation says what the button does.

        button = MotionIconButton("scissors", "Trim")
        button.play()

    The frame, hover and pressed looks are a QPushButton's, from QSS; the
    icon is painted over them in the `iconColor` Qt property
    (`MotionIconButton { qproperty-iconColor: var(--text-secondary); }`),
    so it follows the theme like every other icon. Disabled = dimmed, and
    it doesn't play.
    """

    DISABLED_OPACITY = 0.4

    iconColor = color_property("_icon_color")

    def __init__(self, icon_name: str, tooltip: str = "", icon_size: int = 20, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = int(icon_size)
        self._icon_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)  # until QSS applies
        self._phase = 0.0
        self._animation = qt.QtCore.QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(DURATIONS.get(icon_name, DEFAULT_DURATION))
        self._animation.valueChanged.connect(self._on_phase)
        self._animation.finished.connect(lambda: self._on_phase(0.0))
        self.setToolTip(tooltip)

    @staticmethod
    def has_icon(name: str) -> bool:
        """Is there a motion icon called `name`."""
        return name in MOTION_ICONS

    def play(self) -> None:
        """Plays the icon's animation once (from the start, if it is already playing)."""
        if not self.isEnabled():
            return
        self._animation.stop()
        self._animation.start()

    def is_playing(self) -> bool:
        return self._animation.state() == qt.QtCore.QAbstractAnimation.State.Running

    def _on_phase(self, value) -> None:
        self._phase = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        if not self.is_playing():
            self.play()
        super().enterEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # the frame / hover / pressed look from QSS
        painter = qt.QtGui.QPainter(self)
        if not self.isEnabled():
            painter.setOpacity(self.DISABLED_OPACITY)
        side = self._icon_size
        rect = qt.QtCore.QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        paint_motion_icon(self._icon_name, painter, rect, self._icon_color, self._phase)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        for name in MOTION_ICONS:
            button = MotionIconButton(name, name, icon_size=28)
            button.setFixedSize(52, 44)
            button.clicked.connect(button.play)
            dialog.add_case(name + " (hover or click)", button)
        dialog.show()
