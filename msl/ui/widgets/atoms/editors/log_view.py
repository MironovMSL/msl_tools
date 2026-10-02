# ui/widgets/atoms/editors/log_view.py
import time

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.atoms.scrollbars import SlimScrollBar


class LogView(qt.QtWidgets.QPlainTextEdit):
    """A read-only, fixed-width view of log entries, each colored by its
    level: errors, warnings, plain messages, and dimmed detail (stack
    traces). Every entry is stamped with the time it was added.

        view.append_entry("error", "Cannot find procedure \"foo\".")
        view.set_entries(entries)      # [(level, text, time.time()), ...]

    Follows the newest entry while the view is scrolled to the bottom; once
    the reader scrolls up, it stays where they are. Keeps the last
    MAX_ENTRIES entries.

    Levels: "error", "warning", "info", "trace", and "input" (something the
    reader typed — shown with a ">>>" in the accent); anything else reads
    as "info". Colors are Qt properties set by ui/theme/widgets.qss
    (textColor, errorColor, warningColor, mutedColor, inputColor) — a theme
    switch re-renders the entries in the new colors.
    """

    MAX_ENTRIES = 2000
    FONT_FAMILIES = ("Cascadia Mono", "JetBrains Mono", "Consolas")
    FONT_POINT_SIZE = 9
    LEVEL_LABELS = {"error": "error", "warning": "warn ", "info": "     ", "trace": "     ", "input": ">>>  "}

    textColor = color_property("_text_color", "_rerender")
    errorColor = color_property("_error_color", "_rerender")
    warningColor = color_property("_warning_color", "_rerender")
    mutedColor = color_property("_muted_color", "_rerender")
    inputColor = color_property("_input_color", "_rerender")

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._text_color = qt.QtGui.QColor(fallback.text_primary)
        self._error_color = qt.QtGui.QColor(fallback.text_primary)
        self._warning_color = qt.QtGui.QColor(fallback.text_primary)
        self._muted_color = qt.QtGui.QColor(fallback.text_secondary)
        self._input_color = qt.QtGui.QColor(fallback.accent)
        self._entries: list[tuple[str, str, float]] = []

        self.setReadOnly(True)
        self.setLineWrapMode(qt.QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setPlaceholderText(placeholder)
        self.setFont(self._fixed_font())
        self.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical))
        self.setHorizontalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Horizontal))

    @classmethod
    def _fixed_font(cls) -> qt.QtGui.QFont:
        installed = set(qt.QtGui.QFontDatabase.families())
        family = next((name for name in cls.FONT_FAMILIES if name in installed), None)
        font = qt.QtGui.QFont(family) if family else \
            qt.QtGui.QFontDatabase.systemFont(qt.QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(qt.QtGui.QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(cls.FONT_POINT_SIZE)
        return font

    # --- entries -----------------------------------------------------------------

    def entries(self) -> list[tuple[str, str, float]]:
        return list(self._entries)

    def append_entry(self, level: str, text: str, when: float | None = None) -> None:
        self._entries.append((level, text, when if when is not None else time.time()))
        if len(self._entries) > self.MAX_ENTRIES:
            # Rarely: cut a batch at once rather than re-rendering on every new line.
            self._entries = self._entries[-(self.MAX_ENTRIES * 3 // 4):]
            self._rerender()
            return
        self._write(*self._entries[-1])

    def set_entries(self, entries) -> None:
        """Replaces what is shown with `entries`: (level, text, time) tuples."""
        self._entries = list(entries)[-self.MAX_ENTRIES:]
        self._rerender()

    def clear_entries(self) -> None:
        self._entries = []
        self.clear()

    def set_wrap(self, wrap: bool) -> None:
        """Long lines continue on the next line (True) or run off to the right
        behind a horizontal scroll bar (False, the start state)."""
        self.setLineWrapMode(qt.QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth if wrap
                             else qt.QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setWordWrapMode(qt.QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

    def plain_text(self) -> str:
        """Everything shown, as text (for the clipboard)."""
        return self.toPlainText()

    # --- rendering -----------------------------------------------------------------

    def _rerender(self) -> None:
        # Also reached from the color setters, which QSS may call during polish —
        # before __init__ has set everything up.
        if not hasattr(self, "_entries"):
            return
        self.clear()
        for entry in self._entries:
            self._write(*entry)

    def _write(self, level: str, text: str, when: float) -> None:
        bar = self.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 2  # the reader is at the bottom: keep them there

        stamp = time.strftime("%H:%M:%S", time.localtime(when))
        label = self.LEVEL_LABELS.get(level, self.LEVEL_LABELS["info"])
        lines = text.rstrip("\n").split("\n") or [""]
        indent = " " * (len(stamp) + 2 + len(label) + 2)

        cursor = self.textCursor()
        cursor.movePosition(qt.QtGui.QTextCursor.MoveOperation.End)
        if not self.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(stamp + "  ", self._format(self._muted_color))
        body = {"error": self._error_color, "warning": self._warning_color, "trace": self._muted_color,
                "input": self._input_color}.get(level, self._text_color)
        cursor.insertText(label + "  ", self._format(body))
        cursor.insertText(lines[0], self._format(body))
        for line in lines[1:]:
            cursor.insertBlock()
            cursor.insertText(indent + line, self._format(body))

        if follow:
            bar.setValue(bar.maximum())

    @staticmethod
    def _format(color: qt.QtGui.QColor) -> qt.QtGui.QTextCharFormat:
        text_format = qt.QtGui.QTextCharFormat()
        text_format.setForeground(color)
        return text_format


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        view = LogView("Nothing logged yet.")
        view.setMinimumSize(520, 180)
        view.append_entry("info", "scene opened")
        view.append_entry("warning", "line 1: mel warning")
        view.append_entry("error", "line 1: Cannot find procedure \"this\".")
        view.append_entry("trace", "Start of trace: (command window: line 1).\nthis (command window: line 1).")
        dialog.add_case("LogView", view)
        dialog.show()
