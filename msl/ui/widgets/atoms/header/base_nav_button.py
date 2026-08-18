import msl_tools.msl.ui.qt_bindings as qt


class BaseNavButton(qt.QtWidgets.QAbstractButton):
    """Full-height chrome button for window headers (minimize/maximize/close and
    similar single-glyph controls).

    A single animated scalar, hoverProgress (0.0 idle -> 1.0 hovered), drives
    everything: background fill alpha and icon appearance. This keeps the
    background fade and the icon fade in exact sync and avoids having two
    independent animation timelines.

    Background fade interpolates ONLY the alpha of HOVER_COLOR (RGB stays
    fixed) — interpolating RGB from a fully transparent black toward the
    hover color produces a muddy in-between shade (e.g. red hover would pass
    through a dark brownish tone before "arriving" at red), which reads as a
    visual jump rather than a smooth fade. Holding RGB fixed and only ramping
    alpha gives a clean fade from invisible to fully saturated.

    Icon has two modes, chosen by whether a hover icon was supplied:
      - No hover icon (minimize/maximize/restore): the single icon is drawn
        with opacity interpolated between ICON_IDLE_OPACITY and 1.0 — it just
        gets "less pale" on hover, same color throughout.
      - Hover icon supplied (close): idle and hover icons are cross-faded —
        used when the hover background changes color enough (e.g. red) that
        the icon needs an actual color swap, not just more opacity, to stay
        readable. The idle icon's opacity is scaled by ICON_IDLE_OPACITY too,
        so it starts pale and fades out while the hover icon fades in.
    """

    DEFAULT_HOVER_COLOR = qt.QtGui.QColor(255, 255, 255, 25)
    DEFAULT_PRESSED_COLOR = qt.QtGui.QColor(255, 255, 255, 15)

    ICON_IDLE_OPACITY = 0.30
    ICON_SIZE = 16

    FADE_IN_MS = 120
    FADE_OUT_MS = 220

    def __init__(self, width: int = 46, parent=None):
        super().__init__(parent)
        self.setFixedWidth(width)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Fixed,
                            qt.QtWidgets.QSizePolicy.Policy.Expanding)
        self.setCursor(qt.QtCore.Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

        self._icon: qt.QtGui.QIcon | None = None
        self._hover_icon: qt.QtGui.QIcon | None = None

        self._hover_color = qt.QtGui.QColor(self.DEFAULT_HOVER_COLOR)
        self._pressed_color = qt.QtGui.QColor(self.DEFAULT_PRESSED_COLOR)

        self._corner_radius = 0
        self._round_top_left = False
        self._round_top_right = False

        self._hover_progress = 0.0
        self._animation = qt.QtCore.QPropertyAnimation(self, b"hoverProgress", self)

    # --- Animated scalar driving background + icon appearance ---

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float) -> None:
        self._hover_progress = value
        self.update()

    hoverProgress = qt.QtCore.Property(float, _get_hover_progress, _set_hover_progress)

    # --- Colors, theme-driven ---
    def set_hover_color(self, color: qt.QtGui.QColor) -> None:
        self._hover_color = qt.QtGui.QColor(color)
        self.update()

    def set_pressed_color(self, color: qt.QtGui.QColor) -> None:
        self._pressed_color = qt.QtGui.QColor(color)
        self.update()

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

    def _animate_to(self, value: float, duration: int) -> None:
        self._animation.stop()
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._hover_progress)
        self._animation.setEndValue(value)
        self._animation.start()


    def set_hover_color(self, color: qt.QtGui.QColor) -> None:
        """Sets the hover background color. Intended to be called by the
        owning window whenever the theme changes, so contrast is correct on
        both light and dark backgrounds — a fixed white overlay disappears
        on a light header, a fixed dark overlay disappears on a dark one."""
        self._hover_color = qt.QtGui.QColor(color)
        self.update()
    # --- Icon content ---

    def set_icon(self, icon: qt.QtGui.QIcon, hover_icon: qt.QtGui.QIcon | None = None) -> None:
        """icon: idle-state icon (typically theme-colored, e.g. text_primary).
        hover_icon: optional, only needed when the hover background changes
        color enough that the icon needs a different color to stay readable
        (e.g. close's white-on-red). If omitted, hover is a pure opacity
        increase on the same icon."""
        self._icon = icon
        self._hover_icon = hover_icon
        self.update()

    # --- Corner rounding, set by whoever owns/positions this button ---

    def set_corner_radius(self, radius: int, *, top_left: bool = False, top_right: bool = False) -> None:
        self._corner_radius = radius
        self._round_top_left = top_left
        self._round_top_right = top_right
        self.update()

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

        rect = qt.QtCore.QRectF(self.rect())
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
            idle_opacity = self.ICON_IDLE_OPACITY * (1.0 - self._hover_progress)
            painter.setOpacity(idle_opacity)
            self._icon.paint(painter, target.toRect())

            painter.setOpacity(self._hover_progress)
            self._hover_icon.paint(painter, target.toRect())

        painter.setOpacity(1.0)