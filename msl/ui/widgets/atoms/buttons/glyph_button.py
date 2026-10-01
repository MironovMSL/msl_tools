# ui/widgets/atoms/buttons/glyph_button.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme, ThemeRegistry
from msl_tools.msl.ui.icon_manager import tint_icon
from msl_tools.msl.ui.theme.qss import color_property


class GlyphButton(qt.QtWidgets.QAbstractButton):
    """Small borderless icon button for dense rows and toolbars: draws one
    glyph (or an icon) centered, with a soft rounded highlight on hover/press.

    Custom-painted on purpose: the global QSS baseline gives every
    QPushButton `padding: 4px 10px`, which leaves no room for a glyph in a
    ~20px button — such buttons render as empty boxes. This atom ignores
    that baseline entirely.

    Colors are Qt properties set by the window stylesheet (ui/theme/
    widgets.qss): glyphColor, activeGlyphColor (hovered/pressed),
    highlightColor, pressedHighlightColor. Until it applies (or outside a styled window) they hold the default
    theme's colors.

    Content is either a Unicode glyph ("⧉", "⋮⋮", ...) or an icon via
    set_icon(). Icons are treated as ONE-COLOR shapes and painted in the
    current glyph color (see _tinted_icon), so they follow the QSS colors
    exactly like glyphs do; use monochrome SVGs (e.g. from
    UiResources().iconManager.get_icon(name, sub_folder="actions")).
    """

    DEFAULT_SIZE = qt.QtCore.QSize(20, 20)
    CORNER_RADIUS = 4
    GLYPH_SCALE = 0.62   # glyph pixel size relative to the button's shorter side
    ICON_SCALE = 0.8     # icon size relative to the button's shorter side
    DISABLED_ALPHA = 90

    glyphColor = color_property("_glyph_color")
    activeGlyphColor = color_property("_active_glyph_color")
    highlightColor = color_property("_highlight_color")
    pressedHighlightColor = color_property("_pressed_highlight_color")

    def __init__(self, glyph: str = "", tooltip: str = "",
                 size: qt.QtCore.QSize | None = None, parent=None):
        super().__init__(parent)
        self._glyph = glyph
        self._icon: qt.QtGui.QIcon | None = None
        self._regular_icon: qt.QtGui.QIcon | None = None   # what a flash goes back to
        self._flashing = False
        self._flash_timer = qt.QtCore.QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)
        self._hovered = False
        self._seed_colors(ThemeRegistry.fallback())

        self.setFixedSize(size or self.DEFAULT_SIZE)
        self.setToolTip(tooltip)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

    def _seed_colors(self, theme: Theme) -> None:
        """Defaults until QSS applies — same mapping as widgets.qss."""
        self._glyph_color = qt.QtGui.QColor(theme.text_secondary)
        self._active_glyph_color = qt.QtGui.QColor(theme.text_primary)
        self._highlight_color = qt.QtGui.QColor(theme.text_primary)
        self._highlight_color.setAlpha(28)
        self._pressed_highlight_color = qt.QtGui.QColor(theme.text_primary)
        self._pressed_highlight_color.setAlpha(55)

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def set_icon(self, icon: "qt.QtGui.QIcon | None") -> None:
        """Draws `icon` instead of the glyph (None goes back to the glyph)."""
        self._regular_icon = icon
        if not self._flashing:
            self._icon = icon
            self.update()

    def flash_icon(self, icon: "qt.QtGui.QIcon | None", duration_ms: int = 1200) -> None:
        """Shows `icon` for a moment, then the regular one again — quick
        feedback for an action with no other visible result ("copied": a
        check mark). No-op without an icon."""
        if icon is None or icon.isNull():
            return
        self._flashing = True
        self._icon = icon
        self.update()
        self._flash_timer.start(duration_ms)

    def _end_flash(self) -> None:
        self._flashing = False
        self._icon = self._regular_icon
        self.update()


    def sizeHint(self) -> qt.QtCore.QSize:
        return self.size()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def _tinted_icon(self, side: int, color: qt.QtGui.QColor) -> qt.QtGui.QPixmap:
        """The icon as a one-color shape in `color` (see icon_manager.tint_icon),
        so it follows the same QSS colors as a text glyph — theme, hover,
        disabled — with no per-theme files or recoloring calls."""
        return tint_icon(self._icon, side, self.devicePixelRatioF(), color)

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = qt.QtCore.QRectF(self.rect())

        active = self.isEnabled() and (self._hovered or self.isDown())
        if active:
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._pressed_highlight_color if self.isDown() else self._highlight_color)
            painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

        side = min(self.width(), self.height())
        color = qt.QtGui.QColor(self._active_glyph_color if active else self._glyph_color)
        if not self.isEnabled():
            color.setAlpha(self.DISABLED_ALPHA)

        if self._icon is not None:
            icon_side = int(side * self.ICON_SCALE)
            icon_rect = qt.QtCore.QRect(0, 0, icon_side, icon_side)
            icon_rect.moveCenter(self.rect().center())
            painter.drawPixmap(icon_rect.topLeft(), self._tinted_icon(icon_side, color))
        elif self._glyph:
            font = qt.QtGui.QFont(self.font())
            font.setPixelSize(max(8, int(side * self.GLYPH_SCALE)))
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(rect, int(qt.QtCore.Qt.AlignmentFlag.AlignCenter), self._glyph)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        for glyph, tip in [("⧉", "Copy"), ("⋮⋮", "Drag"), ("˄", "Up"),
                           ("˅", "Down"), ("…", "Browse"), ("\U0001f5d1", "Delete")]:
            button = GlyphButton(glyph, tip)
            button.clicked.connect(lambda _=False, t=tip: print("clicked:", t))
            dialog.add_case(tip, button)
        dialog.show()
