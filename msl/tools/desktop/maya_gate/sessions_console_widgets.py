# tools/desktop/maya_gate/sessions_console_widgets.py
"""The console's own small widgets: the code input with its history, the in-place
name field."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.editors import CodeEditor


class _ConsoleInput(CodeEditor):
    """Private: the console's input — a small Python editor. Ctrl+Enter
    sends it; Ctrl+Up / Ctrl+Down walk through what was sent before."""

    HEIGHT = 74
    HISTORY_KEPT = 50

    run_requested = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(self.HEIGHT)  # the least; the splitter above it gives it more
        self.setPlaceholderText("Python for the selected Maya \u2014 Ctrl+Enter runs it, Ctrl+Up / Down: earlier code")
        self._history: list[str] = []
        self._history_index = 0   # == len(history): the line being written, not an old one
        self._draft = ""

    def remember(self, code: str) -> None:
        """Adds `code` to the history (called once it was sent)."""
        if code and (not self._history or self._history[-1] != code):
            self._history.append(code)
            del self._history[:-self.HISTORY_KEPT]
        self._history_index = len(self._history)
        self._draft = ""

    def keyPressEvent(self, event) -> None:
        control = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        if control and key in (qt.QtCore.Qt.Key.Key_Return, qt.QtCore.Qt.Key.Key_Enter):
            self.run_requested.emit()
        elif control and key in (qt.QtCore.Qt.Key.Key_Up, qt.QtCore.Qt.Key.Key_Down) and self._history:
            self._walk_history(-1 if key == qt.QtCore.Qt.Key.Key_Up else 1)
        else:
            super().keyPressEvent(event)

    def _walk_history(self, step: int) -> None:
        if self._history_index == len(self._history):
            self._draft = self.toPlainText()  # what was being written comes back at the end
        self._history_index = max(0, min(len(self._history), self._history_index + step))
        at_end = self._history_index == len(self._history)
        self.setPlainText(self._draft if at_end else self._history[self._history_index])
        self.moveCursor(qt.QtGui.QTextCursor.MoveOperation.End)


class _NameField(qt.QtWidgets.QLineEdit):
    """Private: a one-line field that asks for a name in place — Enter takes
    it (returnPressed), Esc or clicking elsewhere gives up (cancelled)."""

    cancelled = qt.QtCore.Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == qt.QtCore.Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.cancelled.emit()
