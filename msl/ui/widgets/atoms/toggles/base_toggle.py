"""Qt-dependent base for checkable, animated-progress toggle atoms."""

import msl_tools.msl.ui.qt_bindings as qt


class BaseToggle(qt.QtWidgets.QAbstractButton):
    """Base for checkable toggle atoms whose visual state is driven by a
    single animated 0..1 'progress' Qt property (progress=0 at unchecked,
    progress=1 at checked). Subclasses only need to implement paintEvent()
    using self.get_progress(); this base handles checkable wiring, the
    property animation, and toggled -> animate-to-target.
    """

    _ANIMATION_DURATION_MS = 500
    _ANIMATION_EASING = qt.QtCore.QEasingCurve.Type.OutBack

    _HOVER_ANIMATION_DURATION_MS = 300
    _HOVER_ANIMATION_EASING = qt.QtCore.QEasingCurve.Type.OutCubic

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)


        self._progress       = 0.0
        self._hover_progress = 0.0
        self.toggled.connect(self._on_toggled)

        self._animation = qt.QtCore.QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(self._ANIMATION_DURATION_MS)
        self._animation.setEasingCurve(self._ANIMATION_EASING)

        self._hover_animation = qt.QtCore.QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setDuration(self._HOVER_ANIMATION_DURATION_MS)
        self._hover_animation.setEasingCurve(self._HOVER_ANIMATION_EASING)

    @qt.QtCore.Property(float)
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, value: float) -> None:
        self._progress = value
        self.update()

    @qt.QtCore.Property(float)
    def hoverProgress(self) -> float:
        return self._hover_progress

    @hoverProgress.setter
    def hoverProgress(self, value: float) -> None:
        self._hover_progress = value
        self.update()

    def enterEvent(self, event) -> None:
        self._animate_hover_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_hover_to(0.0)
        super().leaveEvent(event)

    def _animate_hover_to(self, target: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def _on_toggled(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def set_checked_immediate(self, checked: bool) -> None:
        """Sync both the checked flag and its visual progress instantly, with
        no animation and no toggled signal. For initializing the widget to
        reflect an already-known external state (e.g. current theme when the
        window is first built) — animating from a stale progress=0 in that
        case would show a spurious animation playing on startup for no user
        interaction."""
        if self._animation.state() == qt.QtCore.QAbstractAnimation.State.Running:
            self._animation.stop()
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self.progress= (1.0 if checked else 0.0)

    @staticmethod
    def lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    @classmethod
    def lerp_color(cls, c1: qt.QtGui.QColor, c2: qt.QtGui.QColor, t: float) -> qt.QtGui.QColor:
        t = max(0.0, min(1.0, t))
        return qt.QtGui.QColor(
            round(cls.lerp(c1.red(), c2.red(), t)),
            round(cls.lerp(c1.green(), c2.green(), t)),
            round(cls.lerp(c1.blue(), c2.blue(), t)),
            round(cls.lerp(c1.alpha(), c2.alpha(), t)))
