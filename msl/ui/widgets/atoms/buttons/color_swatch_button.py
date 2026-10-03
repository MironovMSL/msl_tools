# ui/widgets/atoms/buttons/color_swatch_button.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class ColorSwatchButton(qt.QtWidgets.QAbstractButton):
    """A small button that IS a color: it shows the color it holds, and a
    click opens the color dialog to pick another.

        swatch = ColorSwatchButton("#ffffff", "The text's color")
        swatch.color_changed.connect(...)      # the user picked another one
        swatch.hex()                           # "#ffffff"

    The color shown is the user's DATA, not a theme color — only the frame
    around it comes from QSS (qproperty borderColor / hoverBorderColor).
    `set_color()` changes it without the signal.

    Signals:
        color_changed(str) — "#rrggbb", after the user picked a color.
    """

    color_changed = qt.QtCore.Signal(str)

    borderColor = color_property("_border_color")
    hoverBorderColor = color_property("_hover_border_color")

    def __init__(self, color: str = "#ffffff", tooltip: str = "", parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()
        self._border_color = qt.QtGui.QColor(fallback.border)       # until QSS applies
        self._hover_border_color = qt.QtGui.QColor(fallback.accent)
        self._color = qt.QtGui.QColor(color)
        self._title = tooltip
        self.setToolTip(tooltip)
        self.setFixedSize(24, 22)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self._pick)

    def hex(self) -> str:
        return self._color.name()

    def rgb(self) -> tuple:
        """(r, g, b), each 0..1."""
        return self._color.redF(), self._color.greenF(), self._color.blueF()

    def set_color(self, color: str) -> None:
        picked = qt.QtGui.QColor(color)
        if picked.isValid() and picked != self._color:
            self._color = picked
            self.update()

    def _pick(self) -> None:
        picked = qt.QtWidgets.QColorDialog.getColor(self._color, self.window(), self._title or "Pick a color")
        if picked.isValid() and picked != self._color:
            self._color = picked
            self.update()
            self.color_changed.emit(self.hex())

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        border = self._hover_border_color if self.underMouse() and self.isEnabled() else self._border_color
        painter.setPen(qt.QtGui.QPen(border, 1))
        painter.setBrush(self._color)
        painter.setOpacity(1.0 if self.isEnabled() else 0.45)
        painter.drawRoundedRect(rect, 4, 4)
