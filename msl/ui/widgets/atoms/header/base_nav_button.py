import msl_tools.msl.ui.qt_bindings as qt


class BaseNavButton(qt.QtWidgets.QAbstractButton):

    DEFAULT_HOVER_COLOR   = qt.QtGui.QColor(255, 255, 255, 25)
    DEFAULT_PRESSED_COLOR = qt.QtGui.QColor(255, 255, 255, 15)

    ICON_IDLE_OPACITY = 0.40
    ICON_SIZE         = 16

    FADE_IN_MS  = 120
    FADE_OUT_MS = 220

    def __init__(self, width: int = 46, parent=None):
        super().__init__(parent)

        self.setFixedWidth(width)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Fixed, qt.QtWidgets.QSizePolicy.Policy.Expanding)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

        self._icon:       qt.QtGui.QIcon | None = None
        self._hover_icon: qt.QtGui.QIcon | None = None

        self._hover_color   = qt.QtGui.QColor(self.DEFAULT_HOVER_COLOR)
        self._pressed_color = qt.QtGui.QColor(self.DEFAULT_PRESSED_COLOR)

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

    def set_icon(self, icon: qt.QtGui.QIcon, hover_icon: qt.QtGui.QIcon | None = None) -> None:
        self._icon = icon
        self._hover_icon = hover_icon
        self.update()

    def set_hover_color(self, color: qt.QtGui.QColor) -> None:
        self._hover_color = qt.QtGui.QColor(color)
        self.update()

    def set_pressed_color(self, color: qt.QtGui.QColor) -> None:
        self._pressed_color = qt.QtGui.QColor(color)
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

    def _paint_icon(self, painter: qt.QtGui.QPainter, rect: qt.QtCore.QRectF) -> None:
        if self._icon is None:
            return

        size = self.ICON_SIZE
        x = rect.center().x() - size / 2
        y = rect.center().y() - size / 2
        target = qt.QtCore.QRectF(x, y, size, size)

        if self._hover_icon is None:
            painter.setOpacity(self.ICON_IDLE_OPACITY + (1.0 - self.ICON_IDLE_OPACITY) * self._hover_progress)
            self._icon.paint(painter, target.toRect())
        else:
            painter.setOpacity(self.ICON_IDLE_OPACITY * (1.0 - self._hover_progress))
            self._icon.paint(painter, target.toRect())

            painter.setOpacity(self._hover_progress)
            self._hover_icon.paint(painter, target.toRect())

        painter.setOpacity(1.0)