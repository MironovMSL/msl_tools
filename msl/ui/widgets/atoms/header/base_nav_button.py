import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tint_icon
from msl_tools.msl.ui.theme.qss import color_property


class BaseNavButton(qt.QtWidgets.QAbstractButton):
    """Window-control button of a frameless header (minimize / maximize /
    close): a flat cell whose background fades in on hover and whose icon
    brightens from ICON_IDLE_OPACITY to full.

    The icon is a one-color SHAPE (window/*.svg), tinted here. All colors are
    Qt properties set by ui/theme/widgets.qss — iconColor (rest),
    hoverIconColor (hovered; when it differs from iconColor the icon
    cross-fades into it, e.g. white on the close button's red), hoverColor,
    pressedColor — so theme switches and hot reload recolor it with no code.
    Until the stylesheet applies they hold the default theme's colors.
    """

    ICON_IDLE_OPACITY = 0.4
    ICON_SIZE         = 16

    FADE_IN_MS  = 120
    FADE_OUT_MS = 220

    iconColor = color_property("_icon_color")
    hoverIconColor = color_property("_hover_icon_color")
    hoverColor = color_property("_hover_color")
    pressedColor = color_property("_pressed_color")

    def __init__(self, width: int = 46, parent=None):
        super().__init__(parent)

        self.setFixedWidth(width)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Fixed, qt.QtWidgets.QSizePolicy.Policy.Expanding)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

        self._icon: qt.QtGui.QIcon | None = None
        self._tinted: dict[tuple, qt.QtGui.QPixmap] = {}

        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._icon_color = qt.QtGui.QColor(fallback.text_primary)
        self._hover_icon_color = qt.QtGui.QColor(fallback.text_primary)
        self._hover_color = qt.QtGui.QColor(fallback.text_primary)
        self._hover_color.setAlphaF(0.1)
        self._pressed_color = qt.QtGui.QColor(fallback.text_primary)
        self._pressed_color.setAlphaF(0.16)

        self._corner_radius   = 0
        self._round_top_left  = False
        self._round_top_right = False

        self._hover_progress  = 0.0
        self._animation       = qt.QtCore.QPropertyAnimation(self, b"hoverProgress", self)

    @qt.QtCore.Property(float)
    def hoverProgress(self) -> float:
        return self._hover_progress

    @hoverProgress.setter
    def hoverProgress(self, value: float) -> None:
        self._hover_progress = value
        self.update()

    def set_icon(self, icon: qt.QtGui.QIcon | None) -> None:
        """The icon SHAPE (a window/*.svg); its color comes from QSS."""
        self._icon = icon if icon is not None and not icon.isNull() else None
        self._tinted.clear()
        self.update()

    def set_corner_radius(self, radius: int, *, top_left: bool = False, top_right: bool = False) -> None:
        self._corner_radius = radius
        self._round_top_left = top_left
        self._round_top_right = top_right
        self.update()

    def _animate_to(self, value: float, duration: int) -> None:
        self._animation.stop()
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._hover_progress)
        self._animation.setEndValue(value)
        self._animation.start()

    def mousePressEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        super().mousePressEvent(event)
        self.update()

    def mouseReleaseEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self.update()

    def enterEvent(self, event: qt.QtCore.QEvent) -> None:
        self._animate_to(1.0, self.FADE_IN_MS)
        super().enterEvent(event)

    def leaveEvent(self, event: qt.QtCore.QEvent) -> None:
        self._animate_to(0.0, self.FADE_OUT_MS)
        super().leaveEvent(event)

    # --- Painting ---
    def _current_background_color(self) -> qt.QtGui.QColor:
        if self.isDown():
            return self._pressed_color

        color = qt.QtGui.QColor(self._hover_color)
        color.setAlpha(round(self._hover_color.alpha() * self._hover_progress))
        return color

    def paintEvent(self, event: qt.QtGui.QPaintEvent) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        rect     = qt.QtCore.QRectF(self.rect())
        bg_color = self._current_background_color()

        if self._corner_radius and (self._round_top_left or self._round_top_right):
            path = qt.QtGui.QPainterPath()
            path.moveTo(rect.left(), rect.bottom())
            path.lineTo(rect.left(), rect.top() + (self._corner_radius if self._round_top_left else 0))

            if self._round_top_left:
                path.quadTo(rect.left(), rect.top(), rect.left() + self._corner_radius, rect.top())

            path.lineTo(rect.right() - (self._corner_radius if self._round_top_right else 0), rect.top())

            if self._round_top_right:
                path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + self._corner_radius)

            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            painter.fillPath(path, bg_color)
        else:
            painter.fillRect(rect, bg_color)

        self._paint_icon(painter, rect)

    def _tinted_icon(self, color: qt.QtGui.QColor) -> qt.QtGui.QPixmap:
        ratio = self.devicePixelRatioF()
        key = (color.rgba(), ratio)
        if key not in self._tinted:
            self._tinted[key] = tint_icon(self._icon, self.ICON_SIZE, ratio, color)
        return self._tinted[key]

    def _paint_icon(self, painter: qt.QtGui.QPainter, rect: qt.QtCore.QRectF) -> None:
        if self._icon is None:
            return

        size = self.ICON_SIZE
        target = qt.QtCore.QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size)
        progress = self._hover_progress

        if self._hover_icon_color == self._icon_color:
            painter.setOpacity(self.ICON_IDLE_OPACITY + (1.0 - self.ICON_IDLE_OPACITY) * progress)
            painter.drawPixmap(target.toRect(), self._tinted_icon(self._icon_color))
        else:
            # Cross-fade the rest color into the hover color (the close button's white on red).
            painter.setOpacity(self.ICON_IDLE_OPACITY * (1.0 - progress))
            painter.drawPixmap(target.toRect(), self._tinted_icon(self._icon_color))
            painter.setOpacity(progress)
            painter.drawPixmap(target.toRect(), self._tinted_icon(self._hover_icon_color))

        painter.setOpacity(1.0)
