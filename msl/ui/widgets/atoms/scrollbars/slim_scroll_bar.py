# ui/widgets/atoms/scrollbars/slim_scroll_bar.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class SlimScrollBar(qt.QtWidgets.QScrollBar):
    """Scroll bar whose handle is a thin rounded bar that smoothly widens
    while the mouse is over the bar (THIN_PX -> WIDE_PX) and narrows again
    when it leaves — QSS can't animate, so the handle is painted here.

    Everything else stays QSS-driven: the bar's size, the handle's position
    and length (the style's slider rect — no arrow buttons, per base.qss
    `QScrollBar` rules, which match this subclass too), and the colors,
    which are Qt properties set by ui/theme/widgets.qss:
    handleColor (rest), handleHoverColor (mouse over the handle),
    handlePressedColor (while dragging).

    Drop-in: `area.setVerticalScrollBar(SlimScrollBar(Qt.Vertical))`.
    Stays wide while a drag holds the mouse, even outside the bar.
    """

    THIN_PX = 4
    WIDE_PX = 6
    ANIMATION_MS = 140

    handleColor = color_property("_handle_color")
    handleHoverColor = color_property("_handle_hover_color")
    handlePressedColor = color_property("_handle_pressed_color")

    def __init__(self, orientation: qt.QtCore.Qt.Orientation = qt.QtCore.Qt.Orientation.Vertical, parent=None):
        super().__init__(orientation, parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._handle_color = qt.QtGui.QColor(fallback.text_primary)
        self._handle_color.setAlphaF(0.22)
        self._handle_hover_color = qt.QtGui.QColor(fallback.text_primary)
        self._handle_hover_color.setAlphaF(0.38)
        self._handle_pressed_color = qt.QtGui.QColor(fallback.accent)
        self._handle_pressed_color.setAlphaF(0.75)

        self._over_bar = False
        self._over_handle = False
        self._width_progress = 0.0  # 0 = THIN_PX, 1 = WIDE_PX
        self._animation = qt.QtCore.QVariantAnimation(self)
        self._animation.setDuration(self.ANIMATION_MS)
        self._animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_width_progress)

        self.setMouseTracking(True)
        self.sliderReleased.connect(self._sync_width)

    # --- hover / drag state ---------------------------------------------------

    def enterEvent(self, event) -> None:
        self._over_bar = True
        self._sync_width()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._over_bar = False
        self._over_handle = False
        self._sync_width()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        over_handle = self._slider_rect().contains(event.position().toPoint())
        if over_handle != self._over_handle:
            self._over_handle = over_handle
            self.update()
        super().mouseMoveEvent(event)

    def _sync_width(self) -> None:
        """Animates toward wide while hovered or dragged, else toward thin."""
        target = 1.0 if (self._over_bar or self.isSliderDown()) else 0.0
        end = self._animation.endValue()
        if self._animation.state() == qt.QtCore.QAbstractAnimation.State.Running and end == target:
            return
        if self._width_progress == target:
            return
        self._animation.stop()
        self._animation.setStartValue(self._width_progress)
        self._animation.setEndValue(target)
        self._animation.start()

    def _on_width_progress(self, value) -> None:
        self._width_progress = float(value)
        self.update()

    # --- painting -------------------------------------------------------------

    def _slider_rect(self) -> qt.QtCore.QRect:
        option = qt.QtWidgets.QStyleOptionSlider()
        self.initStyleOption(option)
        return self.style().subControlRect(qt.QtWidgets.QStyle.ComplexControl.CC_ScrollBar, option,
                                           qt.QtWidgets.QStyle.SubControl.SC_ScrollBarSlider, self)

    def paintEvent(self, event) -> None:
        slider = self._slider_rect()
        if slider.isEmpty() or self.maximum() <= self.minimum():
            return
        thickness = self.THIN_PX + (self.WIDE_PX - self.THIN_PX) * self._width_progress
        if self.orientation() == qt.QtCore.Qt.Orientation.Vertical:
            handle = qt.QtCore.QRectF(self.width() / 2 - thickness / 2, slider.top(), thickness, slider.height())
        else:
            handle = qt.QtCore.QRectF(slider.left(), self.height() / 2 - thickness / 2, slider.width(), thickness)

        if self.isSliderDown():
            color = self._handle_pressed_color
        elif self._over_handle:
            color = self._handle_hover_color
        else:
            color = self._handle_color

        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(handle, thickness / 2, thickness / 2)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        text = qt.QtWidgets.QPlainTextEdit("\n".join(f"line {i}" for i in range(80)))
        text.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical))
        text.setFixedHeight(160)
        dialog.add_case("SlimScrollBar (hover the bar)", text)
        dialog.show()
