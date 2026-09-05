# ui/widgets/atoms/checkboxes/base_checkbox.py
import shiboken6

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme, ThemeRegistry


class BaseCheckbox(qt.QtWidgets.QAbstractButton):
    """Self-painting checkbox atom: rounded box + animated fill + checkmark,
    label drawn alongside. Fully custom paint — no reliance on native
    QCheckBox styling, so it stays visually consistent across themes without
    depending on global QSS (see StylesheetBuilder's exclusion policy for
    state-driven widgets).

    Signals:
        toggled(bool) — inherited from QAbstractButton, fires on check state
        change (both user click and programmatic setChecked()).
    """

    BOX_SIZE      = 18
    BOX_SPACING   = 10
    CORNER_RADIUS = 5
    BORDER_WIDTH  = 1.5
    ANIM_DURATION = 280

    def __init__(self, text: str = "", theme: Theme | None = None, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Preferred,
                            qt.QtWidgets.QSizePolicy.Policy.Fixed)

        self._theme = theme or ThemeRegistry.fallback()
        self._hovered = False
        self._check_progress = 1.0 if self.isChecked() else 0.0

        self._animation: qt.QtCore.QPropertyAnimation | None = None

        self.toggled.connect(self._on_toggled)

    # --- animated property -------------------------------------------------

    def _get_check_progress(self) -> float:
        return self._check_progress

    def _set_check_progress(self, value: float) -> None:
        self._check_progress = value
        self.update()

    checkProgress = qt.QtCore.Property(float, _get_check_progress, _set_check_progress)

    def _on_toggled(self, checked: bool) -> None:
        self._animate_to(1.0 if checked else 0.0)

    def _animate_to(self, target: float) -> None:
        if self._animation is not None and shiboken6.isValid(self._animation):
            self._animation.stop()

        anim = qt.QtCore.QPropertyAnimation(self, b"checkProgress", self)
        anim.setDuration(self.ANIM_DURATION)
        anim.setStartValue(self._check_progress)
        anim.setEndValue(target)
        anim.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutBack)
        anim.setProperty("_owner_ref", self)

        self._animation = anim
        anim.finished.connect(self._clear_animation_ref)
        anim.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _clear_animation_ref(self) -> None:
        self._animation = None

    def set_checked_immediate(self, checked: bool) -> None:
        """Sets checked state without animating and without emitting
        toggled — used to sync initial state from theme/config at
        construction time (same convention as BaseToggle)."""
        if self._animation is not None and shiboken6.isValid(self._animation):
            self._animation.stop()
            self._animation = None

        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._check_progress = 1.0 if checked else 0.0
        self.update()

    # --- theming -------------------------------------------------------

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    # --- geometry --------------------------------------------------------

    def sizeHint(self) -> qt.QtCore.QSize:
        fm = qt.QtGui.QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(self.text()) if self.text() else 0
        width = self.BOX_SIZE + (self.BOX_SPACING + text_width if self.text() else 0)
        height = max(self.BOX_SIZE, fm.height()) + 4
        return qt.QtCore.QSize(width, height)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # --- paint -------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        inset = self.BORDER_WIDTH / 2
        box_rect = qt.QtCore.QRectF(
            inset, (self.height() - self.BOX_SIZE) / 2 + inset,
                   self.BOX_SIZE - self.BORDER_WIDTH, self.BOX_SIZE - self.BORDER_WIDTH)

        self._paint_box(painter, box_rect)
        self._paint_checkmark(painter, box_rect)

        if self.text():
            text_rect = qt.QtCore.QRectF(
                box_rect.right() + self.BOX_SPACING, 0,
                self.width() - box_rect.right() - self.BOX_SPACING, self.height())
            painter.setPen(qt.QtGui.QColor(self._theme.text_primary))
            painter.drawText(text_rect, int(qt.QtCore.Qt.AlignmentFlag.AlignVCenter), self.text())

        painter.end()

    def _paint_box(self, painter: qt.QtGui.QPainter, rect: qt.QtCore.QRectF) -> None:
        border_color = qt.QtGui.QColor(self._theme.accent if self._hovered else self._theme.border)

        path = qt.QtGui.QPainterPath()
        path.addRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

        base_color = qt.QtGui.QColor(self._theme.surface)
        painter.setPen(qt.QtGui.QPen(border_color, self.BORDER_WIDTH))
        painter.setBrush(base_color)
        painter.drawPath(path)

        if self._check_progress <= 0.0:
            return

        # Fill scales in from the center, same spirit as the reference —
        # clamp so OutBack overshoot doesn't paint outside the box.
        scale = min(max(self._check_progress, 0.0), 1.0)
        center = rect.center()
        fill_rect = qt.QtCore.QRectF(0, 0, rect.width() * scale, rect.height() * scale)
        fill_rect.moveCenter(center)

        fill_path = qt.QtGui.QPainterPath()
        fill_path.addRoundedRect(fill_rect, self.CORNER_RADIUS * scale, self.CORNER_RADIUS * scale)

        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(qt.QtGui.QColor(self._theme.accent))
        painter.drawPath(fill_path)

    def _paint_checkmark(self, painter: qt.QtGui.QPainter, rect: qt.QtCore.QRectF) -> None:
        if self._check_progress <= 0.0:
            return

        painter.save()
        painter.setOpacity(min(max(self._check_progress, 0.0), 1.0))

        s = rect.width()
        p1 = rect.topLeft() + qt.QtCore.QPointF(s * 0.28, s * 0.52)
        p2 = rect.topLeft() + qt.QtCore.QPointF(s * 0.44, s * 0.68)
        p3 = rect.topLeft() + qt.QtCore.QPointF(s * 0.74, s * 0.32)

        check_path = qt.QtGui.QPainterPath()
        check_path.moveTo(p1)
        check_path.lineTo(p2)
        check_path.lineTo(p3)

        # Icon color mirrors QPushButton:pressed convention already in
        # StylesheetBuilder (accent background -> theme.surface foreground).
        pen = qt.QtGui.QPen(qt.QtGui.QColor(self._theme.surface), 2.2,
                             qt.QtCore.Qt.PenStyle.SolidLine,
                             qt.QtCore.Qt.PenCapStyle.RoundCap,
                             qt.QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(check_path)
        painter.restore()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.widget_playground_dialog import WidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = WidgetPlaygroundDialog()
        dialog.add_case("BaseCheckbox (light)",
                         BaseCheckbox("use package folder as install path"))
        dialog.add_case("BaseCheckbox (dark)",
                         BaseCheckbox("use package folder as install path",
                                      theme=ThemeRegistry.fallback("dark")))
        dialog.show()