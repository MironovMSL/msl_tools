# ui/widgets/atoms/comboboxes/base_combo_box.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.atoms.scrollbars import SlimScrollBar


class BaseComboBox(qt.QtWidgets.QComboBox):
    """Thin QComboBox atom: fixed item list, tracks its own current
    selection, and can ignore scroll-wheel input.

    Styled by the window's global stylesheet like any QComboBox (field,
    gradient, arrow separator: ui/theme/base.qss) — except the arrow, which
    it paints itself so it can animate: when the list opens the chevron
    turns to point up and takes the "open" color, and turns back when the
    list closes (QSS can't animate). Its colors are Qt properties set by
    ui/theme/widgets.qss: arrowColor (rest), arrowHoverColor (mouse over the
    combo), arrowOpenColor (list open). widgets.qss also hides the QSS arrow
    image for BaseComboBox; its size/position still come from base.qss's
    `QComboBox::down-arrow` (the SC_ComboBoxArrow rect).

    Wheel-disable exists because a combo box sitting in a scrollable
    page silently changes its value when the user scrolls past it —
    disabling the wheel here makes that opt-in per instance.

    The drop-down list scrolls with a SlimScrollBar, like the rest of the UI,
    and draws its rows with a QStyledItemDelegate so base.qss's
    `QComboBox QAbstractItemView::item` rules (padding, hover) apply.
    """

    ARROW_ANIMATION_MS = 180
    ARROW_STROKE = 1.5  # chevron line width, px

    arrowColor = color_property("_arrow_color")
    arrowHoverColor = color_property("_arrow_hover_color")
    arrowOpenColor = color_property("_arrow_open_color")

    def __init__(self, items: list[str], current_item: str, enable_wheel: bool = True, parent=None):
        super().__init__(parent)
        self.items = items
        self.current_item = current_item

        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._arrow_color = qt.QtGui.QColor(fallback.text_secondary)
        self._arrow_hover_color = qt.QtGui.QColor(fallback.text_primary)
        self._arrow_open_color = qt.QtGui.QColor(fallback.accent)
        self._open_progress = 0.0  # 0 = closed (pointing down), 1 = open (pointing up)
        self._arrow_animation = qt.QtCore.QVariantAnimation(self)
        self._arrow_animation.setDuration(self.ARROW_ANIMATION_MS)
        self._arrow_animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._arrow_animation.valueChanged.connect(self._on_open_progress)

        self.setItemDelegate(qt.QtWidgets.QStyledItemDelegate(self))
        self.view().setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical))
        self.addItems(self.items)
        self.setCurrentText(self.current_item)
        self.currentTextChanged.connect(self._on_current_text_changed)

        if not enable_wheel:
            self.wheelEvent = lambda event: event.ignore()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} items={self.items} current='{self.current_item}'>"

    def _on_current_text_changed(self, text: str) -> None:
        self.current_item = text

    # --- animated arrow -------------------------------------------------------

    def showPopup(self) -> None:
        super().showPopup()
        self._animate_arrow(1.0)

    def hidePopup(self) -> None:
        super().hidePopup()
        self._animate_arrow(0.0)

    def _animate_arrow(self, target: float) -> None:
        if self._open_progress == target:
            return
        self._arrow_animation.stop()
        self._arrow_animation.setStartValue(self._open_progress)
        self._arrow_animation.setEndValue(target)
        self._arrow_animation.start()

    def _on_open_progress(self, value) -> None:
        self._open_progress = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()  # rest -> hover arrow color

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # field, text, separator; the QSS arrow image is hidden
        option = qt.QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = qt.QtCore.QRectF(self.style().subControlRect(
            qt.QtWidgets.QStyle.ComplexControl.CC_ComboBox, option,
            qt.QtWidgets.QStyle.SubControl.SC_ComboBoxArrow, self))
        if rect.isEmpty():
            return

        rest = self._arrow_hover_color if self.underMouse() else self._arrow_color
        color = self._blend(rest, self._arrow_open_color, self._open_progress)
        if not self.isEnabled():
            color.setAlphaF(color.alphaF() * 0.5)

        # The chevron of actions/chevron_down.svg (24-unit grid: 6,9 -> 12,15 -> 18,9),
        # drawn as a path so it stays crisp while it turns.
        side = min(rect.width(), rect.height())
        scale = side / 24.0
        path = qt.QtGui.QPainterPath(qt.QtCore.QPointF(-6 * scale, -3 * scale))
        path.lineTo(0, 3 * scale)
        path.lineTo(6 * scale, -3 * scale)

        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.translate(rect.center())
        painter.rotate(180.0 * self._open_progress)
        pen = qt.QtGui.QPen(color, self.ARROW_STROKE)
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()

    @staticmethod
    def _blend(a: qt.QtGui.QColor, b: qt.QtGui.QColor, t: float) -> qt.QtGui.QColor:
        return qt.QtGui.QColor.fromRgbF(*(ca + (cb - ca) * t for ca, cb in zip(a.getRgbF(), b.getRgbF())))


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        dialog.add_case("BaseComboBox", BaseComboBox(["2024", "2025", "2026"], "2025"))
        dialog.show()
