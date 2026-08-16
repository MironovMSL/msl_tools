import msl_tools.msl.ui.qt_bindings as qt


class BaseNavButton(qt.QtWidgets.QAbstractButton):
    """Full-height chrome button for window headers (minimize/maximize/close and
    similar single-glyph controls). Meant to sit flush against the header edge
    with zero margin/spacing around it — width is fixed, height stretches to
    fill the header row.

    Hover background is animated via QPropertyAnimation on a Qt property
    (backgroundColor), not QSS :hover — Qt stylesheets don't support CSS-style
    transitions, so a plain :hover rule would snap instantly instead of fading.
    Fade-in is fast, fade-out is slow, matching common title-bar conventions
    (PyCharm, VSCode, Windows).

    Subclasses only need to set HOVER_COLOR and pass a glyph/icon; corner
    rounding is opt-in via set_corner_radius(), used only by whichever button
    ends up flush against a rounded window corner (normally close).
    """

    HOVER_COLOR = qt.QtGui.QColor(255, 255, 255, 25)
    IDLE_COLOR = qt.QtGui.QColor(0, 0, 0, 0)

    _ICON_SIZE = 16

    FADE_IN_MS = 120
    FADE_OUT_MS = 220

    def __init__(self, glyph: str = "", icon: qt.QtGui.QIcon | None = None,
                 width: int = 46, parent=None):
        super().__init__(parent)
        self.setFixedWidth(width)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Fixed,
                            qt.QtWidgets.QSizePolicy.Policy.Expanding)
        self.setCursor(qt.QtCore.Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

        self._glyph = glyph
        self._icon = icon
        self._bg_color = qt.QtGui.QColor(self.IDLE_COLOR)

        self._corner_radius = 0
        self._round_top_left = False
        self._round_top_right = False

        self._animation = qt.QtCore.QPropertyAnimation(self, b"backgroundColor", self)

    # --- Animated background color, exposed as a Qt property ---

    def _get_background_color(self) -> qt.QtGui.QColor:
        return self._bg_color

    def _set_background_color(self, color: qt.QtGui.QColor) -> None:
        self._bg_color = color
        self.update()

    backgroundColor = qt.QtCore.Property(qt.QtGui.QColor, _get_background_color, _set_background_color)

    def _animate_to(self, color: qt.QtGui.QColor, duration: int) -> None:
        self._animation.stop()
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._bg_color)
        self._animation.setEndValue(color)
        self._animation.start()

    def enterEvent(self, event: qt.QtCore.QEvent) -> None:
        self._animate_to(self.HOVER_COLOR, self.FADE_IN_MS)
        super().enterEvent(event)

    def leaveEvent(self, event: qt.QtCore.QEvent) -> None:
        self._animate_to(self.IDLE_COLOR, self.FADE_OUT_MS)
        super().leaveEvent(event)

    # --- Content: icon takes priority over glyph when set ---

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def set_icon(self, icon: qt.QtGui.QIcon | None) -> None:
        """Sets the icon to draw instead of the text glyph. Pass None to fall
        back to the glyph (e.g. before real icon assets are wired in)."""
        self._icon = icon
        self.update()

    # --- Corner rounding, set by whoever owns/positions this button ---

    def set_corner_radius(self, radius: int, *, top_left: bool = False, top_right: bool = False) -> None:
        """Rounds this button's own painted background on the given top
        corner(s), so it visually matches the window's corner radius when its
        hover fill would otherwise square off a rounded corner."""
        self._corner_radius = radius
        self._round_top_left = top_left
        self._round_top_right = top_right
        self.update()

    # --- Painting ---

    def paintEvent(self, event: qt.QtGui.QPaintEvent) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        rect = qt.QtCore.QRectF(self.rect())

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
            painter.fillPath(path, self._bg_color)
        else:
            painter.fillRect(rect, self._bg_color)

        if self._icon is not None:
            size = self._ICON_SIZE
            mode = (qt.QtGui.QIcon.Mode.Active if self.underMouse()
                    else qt.QtGui.QIcon.Mode.Normal)
            pixmap = self._icon.pixmap(qt.QtCore.QSize(size, size), mode)
            x = rect.center().x() - pixmap.width() / 2 / pixmap.devicePixelRatio()
            y = rect.center().y() - pixmap.height() / 2 / pixmap.devicePixelRatio()
            painter.drawPixmap(qt.QtCore.QPointF(x, y), pixmap)
        else:
            painter.setPen(qt.QtGui.QColor("white"))
            painter.setFont(self.font())
            painter.drawText(rect, qt.QtCore.Qt.AlignmentFlag.AlignCenter, self._glyph)