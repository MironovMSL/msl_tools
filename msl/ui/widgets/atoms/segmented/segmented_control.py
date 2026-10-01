# ui/widgets/atoms/segmented/segmented_control.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class SegmentedControl(qt.QtWidgets.QWidget):
    """One-of-few picker drawn as a sunken track with equal segments; the
    chosen one sits on a raised "pill" that SLIDES to a newly picked segment
    (macOS / Figma style). For a handful of options that are switched often
    (Maya Gate's environments) — every option visible, one click away; a
    combo box stays the choice for long lists.

    Keyboard: Left / Right move the selection while focused (Tab focus).
    Focus is not drawn: a click focuses the control, and an accent border
    appearing on a mere click read as "something is wrong / selected".

    Colors are Qt properties set by ui/theme/widgets.qss: trackTopColor ->
    trackColor (sunken gradient), borderColor, pillTopColor -> pillColor
    (raised gradient), pillBorderColor, textColor, hoverTextColor,
    activeTextColor.

    Signals:
        current_changed(str) — the picked option (not on set_current()).
    """

    HEIGHT = 22
    TRACK_PADDING = 2
    SEGMENT_PADDING = 12
    RADIUS = 5
    ANIMATION_MS = 200

    current_changed = qt.QtCore.Signal(str)

    trackColor = color_property("_track_color")
    trackTopColor = color_property("_track_top_color")
    borderColor = color_property("_border_color")
    pillColor = color_property("_pill_color")
    pillTopColor = color_property("_pill_top_color")
    pillBorderColor = color_property("_pill_border_color")
    textColor = color_property("_text_color")
    hoverTextColor = color_property("_hover_text_color")
    activeTextColor = color_property("_active_text_color")

    def __init__(self, options: list[str], current: str, parent=None):
        super().__init__(parent)
        self._options = list(options)
        self._index = self._options.index(current) if current in self._options else 0
        self._hover_index = -1

        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._track_color = qt.QtGui.QColor(fallback.surface)
        self._track_top_color = qt.QtGui.QColor(fallback.surface)
        self._border_color = qt.QtGui.QColor(fallback.border)
        self._pill_color = qt.QtGui.QColor(fallback.surface)
        self._pill_top_color = qt.QtGui.QColor(fallback.surface)
        self._pill_border_color = qt.QtGui.QColor(fallback.border)
        self._text_color = qt.QtGui.QColor(fallback.text_secondary)
        self._hover_text_color = qt.QtGui.QColor(fallback.text_primary)
        self._active_text_color = qt.QtGui.QColor(fallback.text_primary)

        self._pill = qt.QtCore.QRectF()
        self._animation = qt.QtCore.QVariantAnimation(self)
        self._animation.setDuration(self.ANIMATION_MS)
        self._animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_pill_moved)

        self.setMouseTracking(True)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.StrongFocus)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Fixed, qt.QtWidgets.QSizePolicy.Policy.Fixed)

    # --- API --------------------------------------------------------------------

    def options(self) -> list[str]:
        return list(self._options)

    def current(self) -> str:
        return self._options[self._index] if self._options else ""

    def set_current(self, option: str, animate: bool = True) -> None:
        """Selects `option` without emitting current_changed."""
        if option in self._options:
            self._select(self._options.index(option), animate, emit=False)

    # --- geometry ---------------------------------------------------------------

    def _segment_width(self) -> int:
        metrics = self.fontMetrics()
        widest = max((metrics.horizontalAdvance(option) for option in self._options), default=0)
        return widest + 2 * self.SEGMENT_PADDING

    def sizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(len(self._options) * self._segment_width() + 2 * self.TRACK_PADDING, self.HEIGHT)

    def minimumSizeHint(self) -> qt.QtCore.QSize:
        return self.sizeHint()

    def _segment_rect(self, index: int) -> qt.QtCore.QRectF:
        width = self._segment_width()
        p = self.TRACK_PADDING
        return qt.QtCore.QRectF(p + index * width, p, width, self.height() - 2 * p)

    def _index_at(self, pos: qt.QtCore.QPointF) -> int:
        for index in range(len(self._options)):
            if self._segment_rect(index).contains(pos):
                return index
        return -1

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (qt.QtCore.QEvent.Type.FontChange, qt.QtCore.QEvent.Type.StyleChange):
            self.updateGeometry()
            self._snap()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._snap()

    # --- selection --------------------------------------------------------------

    def _select(self, index: int, animate: bool, emit: bool) -> None:
        if index < 0 or index == self._index and not self._pill.isEmpty():
            return
        self._index = index
        target = self._segment_rect(index)
        if animate and not self._pill.isEmpty() and self.isVisible():
            self._animation.stop()
            self._animation.setStartValue(qt.QtCore.QRectF(self._pill))
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._snap()
        if emit:
            self.current_changed.emit(self.current())

    def _snap(self) -> None:
        self._animation.stop()
        self._pill = self._segment_rect(self._index) if self._options else qt.QtCore.QRectF()
        self.update()

    def _on_pill_moved(self, rect) -> None:
        self._pill = qt.QtCore.QRectF(rect)
        self.update()

    # --- input ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._select(self._index_at(event.position()), animate=True, emit=True)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position())
        if index != self._hover_index:
            self._hover_index = index
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        step = {qt.QtCore.Qt.Key.Key_Left: -1, qt.QtCore.Qt.Key.Key_Right: 1}.get(event.key())
        if step is None:
            super().keyPressEvent(event)
            return
        index = self._index + step
        if 0 <= index < len(self._options):
            self._select(index, animate=True, emit=True)

    # --- painting ---------------------------------------------------------------

    @staticmethod
    def _vertical(rect: qt.QtCore.QRectF, top: qt.QtGui.QColor, bottom: qt.QtGui.QColor,
                  bottom_at: float = 1.0) -> qt.QtGui.QLinearGradient:
        gradient = qt.QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(bottom_at, bottom)
        return gradient

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        # Track: sunken like a field.
        track = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(qt.QtGui.QPen(self._border_color, 1))
        painter.setBrush(self._vertical(track, self._track_top_color, self._track_color, 0.45))
        painter.drawRoundedRect(track, self.RADIUS, self.RADIUS)

        # Pill: raised like a button, under the current option.
        if not self._pill.isEmpty():
            pill = self._pill.adjusted(0.5, 0.5, -0.5, -0.5)
            radius = self.RADIUS - self.TRACK_PADDING / 2
            painter.setPen(qt.QtGui.QPen(self._pill_border_color, 1))
            painter.setBrush(self._vertical(pill, self._pill_top_color, self._pill_color))
            painter.drawRoundedRect(pill, radius, radius)

        # Labels: active on the pill, hovered brighter, the rest dimmed.
        for index, option in enumerate(self._options):
            if index == self._index:
                color = self._active_text_color
            elif index == self._hover_index:
                color = self._hover_text_color
            else:
                color = self._text_color
            painter.setPen(color)
            painter.drawText(self._segment_rect(index), int(qt.QtCore.Qt.AlignmentFlag.AlignCenter), option)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        control = SegmentedControl(["<default>", "Stable", "Dev"], "Dev")
        control.current_changed.connect(lambda option: print("picked:", option))
        dialog.add_case("SegmentedControl", control)
        dialog.show()
