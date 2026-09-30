# ui/widgets/atoms/apps/application_button.py
import math
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import color_property, repolish


class ApplicationButton(qt.QtWidgets.QWidget):
    """Atom: one clickable application entry — the target executable's own
    OS icon above a bold name label, with a small hover "shake" and a
    click "pulse" for feedback.

    The icon comes from QFileIconProvider (the file's real OS icon), not
    from IconManager — this isn't a themed bundled asset, it's whatever
    icon the target executable itself carries. That's the point: different
    Maya versions show their own distinct icon without us maintaining one.

    Ported from MSL_MayaGate's ApplicationButtonWdg: shake-on-hover and
    pulse-on-click kept as-is, adapted to the qt_bindings shim.

    The whole tile (icon + name) is the target: hovering it shakes the icon
    and lays a soft card under the tile (qproperty hoverColor /
    hoverBorderColor, ui/theme/widgets.qss); a click anywhere on it launches.
    After a click the tile is BUSY for BUSY_MS — name reads "Starting…" in
    the accent, the icon greys out, further clicks are ignored — so a
    double click can't start the application twice. The name label is
    `QLabel#appName` (busy="true" while busy), styled in widgets.qss.

    Exposes graphicsEffect() as a QGraphicsOpacityEffect on purpose — a
    parent composition (e.g. a row of these buttons) animates this
    button's opacity externally via graphicsEffect().setOpacity(), for
    show/hide transitions it orchestrates itself. This atom doesn't drive
    its own opacity.

    Signals:
        clicked(str) — emits application_path when the button is pressed.
    """

    BUTTON_SIZE = qt.QtCore.QSize(48, 48)
    SHAKE_INTERVAL_MS = 30
    SHAKE_AMPLITUDE_X = 2
    SHAKE_AMPLITUDE_Y = 1.5
    PULSE_DURATION_MS = 160
    PULSE_SHRINK_RATIO = 0.9
    BUSY_MS = 5000
    BUSY_TEXT = "Starting\u2026"
    CARD_RADIUS = 8

    clicked = qt.QtCore.Signal(str)

    hoverColor = color_property("_hover_color")
    hoverBorderColor = color_property("_hover_border_color")

    def __init__(self, name: str, application_path: str | Path, parent=None):
        """
        Args:
            name: Display name shown under the icon (e.g. "Maya 2025").
            application_path: Path to the executable this button launches.
                Also what `clicked` emits and what the OS icon is read from.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.name = name
        self.application_path = str(application_path)

        self._shake_phase = 0.0
        self._original_pos: qt.QtCore.QPoint | None = None
        self._hovered = False
        self._busy = False
        self._hover_color = qt.QtGui.QColor(0, 0, 0, 0)          # until QSS applies
        self._hover_border_color = qt.QtGui.QColor(0, 0, 0, 0)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

        self._build_widgets()
        self._build_layout()
        self._build_animations()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}>"

    # --- construction ----------------------------------------------------

    def _build_widgets(self) -> None:
        self._label = qt.QtWidgets.QLabel(self.name)
        self._label.setObjectName("appName")

        self._button = qt.QtWidgets.QToolButton()
        self._button.setFixedSize(self.BUTTON_SIZE)
        self._button.setIcon(self._resolve_icon())
        self._button.setIconSize(self.BUTTON_SIZE)
        self._button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._button.clicked.connect(self._on_clicked)

        # Parent composition animates this via graphicsEffect() — see
        # class docstring. Opacity starts at 1.0; we never touch it
        # ourselves past construction.
        self._opacity_effect = qt.QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(0)
        layout.addWidget(self._button, alignment=qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label, alignment=qt.QtCore.Qt.AlignmentFlag.AlignCenter)

    def _build_animations(self) -> None:
        self._shake_timer = qt.QtCore.QTimer(self)
        self._shake_timer.setInterval(self.SHAKE_INTERVAL_MS)
        self._shake_timer.timeout.connect(self._shake_step)

        self._pulse = qt.QtCore.QVariantAnimation(self)
        self._pulse.setDuration(self.PULSE_DURATION_MS)
        self._pulse.setKeyValues([
            (0.0, self.BUTTON_SIZE),
            (0.5, self.BUTTON_SIZE * self.PULSE_SHRINK_RATIO),
            (1.0, self.BUTTON_SIZE),
        ])
        self._pulse.valueChanged.connect(self._apply_button_size)

    def _resolve_icon(self) -> qt.QtGui.QIcon:
        """Real OS icon of the target executable, scaled to BUTTON_SIZE."""
        file_info = qt.QtCore.QFileInfo(self.application_path)
        provider = qt.QtWidgets.QFileIconProvider()
        icon = provider.icon(file_info)
        pixmap = icon.pixmap(self.BUTTON_SIZE)
        return qt.QtGui.QIcon(pixmap)

    # --- theming -----------------------------------------------------------


    # --- hover shake ---------------------------------------------------

    # The whole tile hovers: Enter/Leave on it cover the icon and the label too.
    def enterEvent(self, event) -> None:
        self._hovered = True
        if not self._busy:
            self._start_shake()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._stop_shake()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        # Accept the press so the matching release comes back to the tile
        # (the name label ignores presses; unaccepted, they'd go to the row).
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # Clicks on the tile around the icon (e.g. the name) launch too.
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._on_clicked()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        if self._hovered:
            painter = qt.QtGui.QPainter(self)
            painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
            painter.setPen(qt.QtGui.QPen(self._hover_border_color, 1))
            painter.setBrush(self._hover_color)
            rect = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.drawRoundedRect(rect, self.CARD_RADIUS, self.CARD_RADIUS)
            painter.end()
        super().paintEvent(event)

    def _start_shake(self) -> None:
        self._original_pos = self._button.pos()
        self._shake_timer.start()

    def _stop_shake(self) -> None:
        self._shake_timer.stop()
        if self._original_pos is not None:
            self._button.move(self._original_pos)

    def _shake_step(self) -> None:
        if self._original_pos is None:
            self._original_pos = self._button.pos()
        self._shake_phase += 0.2
        dx = math.sin(self._shake_phase * 2) * self.SHAKE_AMPLITUDE_X
        dy = math.cos(self._shake_phase * 3) * self.SHAKE_AMPLITUDE_Y
        self._button.move(self._original_pos + qt.QtCore.QPoint(int(dx), int(dy)))

    # --- click pulse -----------------------------------------------------

    def _apply_button_size(self, size: qt.QtCore.QSize) -> None:
        size = qt.QtCore.QSize(int(size.width()), int(size.height()))
        self._button.setFixedSize(size)
        self._button.setIconSize(size)

    def _on_clicked(self) -> None:
        if self._busy:
            return  # already starting: a double click must not launch twice
        self._stop_shake()
        self._pulse.stop()
        self._pulse.start()
        self._set_busy(True)
        qt.QtCore.QTimer.singleShot(self.BUSY_MS, lambda: self._set_busy(False))
        self.clicked.emit(self.application_path)

    # --- busy state ----------------------------------------------------------

    def is_busy(self) -> bool:
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._label.setText(self.BUSY_TEXT if busy else self.name)
        self._label.setProperty("busy", busy)
        repolish(self._label)
        self._button.setEnabled(not busy)  # greys the icon and blocks its clicks
        self.setCursor(qt.QtCore.Qt.CursorShape.BusyCursor if busy else qt.QtCore.Qt.CursorShape.PointingHandCursor)
        if not busy and self._hovered:
            self._start_shake()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        dialog.add_case("ApplicationButton",
                         ApplicationButton("Maya 2025", r"C:\Windows\System32\notepad.exe"))
        dialog.show()