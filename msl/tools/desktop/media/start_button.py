# tools/desktop/media/start_button.py
"""The Media page's start button: the action's icon beside its text, and a thin bar along
its bottom with the batch's progress while jobs run."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton


class StartButton(IconPushButton):
    """The button that starts the picked action: its icon beside its text,
    and — while jobs run — a thin bar along its bottom edge showing how far
    the whole batch is. Colors: qproperty iconColor (IconPushButton),
    progressColor / progressTrackColor (media.qss)."""

    BAR_HEIGHT = 3

    progressColor = color_property("_progress_color")
    progressTrackColor = color_property("_progress_track_color")

    def __init__(self, parent=None):
        super().__init__(None, parent=parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._progress_color = qt.QtGui.QColor(fallback.surface)
        self._progress_track_color = qt.QtGui.QColor(fallback.surface)
        self._progress_track_color.setAlpha(70)
        self._progress: float | None = None

    def set_progress(self, fraction: float | None) -> None:
        """0..1 while jobs run, None when nothing does."""
        if fraction != self._progress:
            self._progress = fraction
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._progress is None:
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        track = qt.QtCore.QRectF(6, self.height() - self.BAR_HEIGHT - 3, self.width() - 12, self.BAR_HEIGHT)
        painter.setBrush(self._progress_track_color)
        painter.drawRoundedRect(track, self.BAR_HEIGHT / 2, self.BAR_HEIGHT / 2)
        done = qt.QtCore.QRectF(track)
        done.setWidth(track.width() * min(max(self._progress, 0.0), 1.0))
        painter.setBrush(self._progress_color)
        painter.drawRoundedRect(done, self.BAR_HEIGHT / 2, self.BAR_HEIGHT / 2)
        painter.end()
