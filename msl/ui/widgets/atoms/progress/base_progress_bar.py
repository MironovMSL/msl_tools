# ui/widgets/atoms/progress/base_progress_bar.py

from enum import Enum, auto

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import repolish


class ProgressState(Enum):
    """Semantic state of a progress bar, independent of the underlying percentage value."""
    NORMAL  = auto()
    SUCCESS = auto()
    ERROR   = auto()


class BaseProgressBar(qt.QtWidgets.QProgressBar):
    """Base progress bar atom. Other files in this subfolder inherit from this class only.

    Wraps QProgressBar with:
      - a semantic ProgressState (NORMAL / SUCCESS / ERROR), exposed as the
        dynamic property `state` ("normal" / "success" / "error"); the window
        stylesheet (ui/theme/widgets.qss) picks the chunk color per state:
            BaseProgressBar[state="error"]::chunk { background-color: var(--error); }
      - a convenience indeterminate ("busy") mode toggle, using Qt's native
        min == max == 0 trick (no manual animation/timer needed)
      - optional percentage text visibility

    Contains no domain logic (install/download/task progress) — the caller drives
    it entirely via set_progress() / set_state() / set_indeterminate().
    """

    def __init__(self,
                 minimum: int = 0,
                 maximum: int = 100,
                 show_percentage: bool = False,
                 parent=None):
        """
        Args:
            minimum: Minimum progress value.
            maximum: Maximum progress value.
            show_percentage: Whether the numeric percentage is drawn on the bar.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._state = ProgressState.NORMAL
        self._cached_range = (minimum, maximum)

        self.setFixedHeight(5)
        self.setMinimum(minimum)
        self.setMaximum(maximum)
        self.setTextVisible(show_percentage)
        self.setValue(minimum)

        self.setProperty("state", self._state.name.lower())

    def set_progress(self, value: int) -> None:
        """Sets the current progress value, clamped to [minimum, maximum]."""
        clamped = max(self.minimum(), min(self.maximum(), value))
        self.setValue(clamped)

    def set_indeterminate(self, enabled: bool) -> None:
        """Toggles busy/indeterminate mode. Caches the previous range so it can
        be restored when switching back to determinate mode."""
        if enabled:
            self._cached_range = (self.minimum(), self.maximum())
            self.setRange(0, 0)
        else:
            self.setRange(*self._cached_range)

    def set_state(self, state: ProgressState) -> None:
        """Updates the semantic state (color) without touching the numeric value."""
        self._state = state
        self.setProperty("state", state.name.lower())  # "normal" / "success" / "error"
        repolish(self)


    def set_percentage_visible(self, visible: bool) -> None:
        """Toggles whether the percentage text is shown."""
        self.setTextVisible(visible)

    def reset_progress(self) -> None:
        """Resets value to minimum and state back to NORMAL."""
        self.set_state(ProgressState.NORMAL)
        self.setValue(self.minimum())


if __name__ == "__main__":

    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        bar_normal = BaseProgressBar()
        bar_normal.set_progress(42)

        bar_success = BaseProgressBar()
        bar_success.set_progress(100)
        bar_success.set_state(ProgressState.SUCCESS)

        bar_error = BaseProgressBar()
        bar_error.set_progress(30)
        bar_error.set_state(ProgressState.ERROR)

        bar_busy = BaseProgressBar(show_percentage=False)
        bar_busy.set_indeterminate(True)

        dialog = ThemedWidgetPlaygroundDialog()
        dialog.add_case("Normal", bar_normal)
        dialog.add_case("Success", bar_success)
        dialog.add_case("Error", bar_error)
        dialog.add_case("Indeterminate", bar_busy)
        dialog.show()