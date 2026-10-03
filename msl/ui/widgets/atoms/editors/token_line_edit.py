# ui/widgets/atoms/editors/token_line_edit.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import make_rounded_popup


class TokenLineEdit(qt.QtWidgets.QLineEdit):
    """A line edit whose text may hold {tokens}: a RIGHT CLICK lists them, and
    the one picked goes in where the click was (replacing the selection, if
    the click was inside it). Under the tokens the menu keeps Cut / Copy /
    Paste.

        field = TokenLineEdit({"scene": "the scene's name", "date": "today's date"})
        field.token_inserted.connect(...)   # textEdited doesn't fire for an insert made by code

    `tokens`: name -> what it stands for (the menu item's tooltip). `insert_token()`
    puts one in at the cursor — for a button beside the field.

    Signals:
        token_inserted(str) — the token that went in, braces included.
        focused() — the field got the keyboard focus (so an owner with several
            fields knows which one a shared button means).
    """

    token_inserted = qt.QtCore.Signal(str)
    focused = qt.QtCore.Signal()

    def __init__(self, tokens: dict, parent=None):
        super().__init__(parent)
        self._tokens = dict(tokens)

    def insert_token(self, token: str) -> None:
        """Puts `token` ("{scene}") in at the cursor, replacing a selection."""
        self.insert(token)
        self.setFocus()
        self.token_inserted.emit(token)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit()

    def contextMenuEvent(self, event) -> None:
        position = self.cursorPositionAt(event.pos())
        start, length = self.selectionStart(), len(self.selectedText())
        if not (start >= 0 and start <= position <= start + length):
            self.setCursorPosition(position)  # the token goes where the click was
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setToolTipsVisible(True)
        for token, meaning in self._tokens.items():
            action = menu.addAction("{" + token + "}")
            action.setToolTip(meaning)
            action.triggered.connect(lambda _checked=False, text="{" + token + "}": self.insert_token(text))
        menu.addSeparator()
        cut = menu.addAction("Cut")
        cut.setEnabled(self.hasSelectedText() and not self.isReadOnly())
        cut.triggered.connect(self.cut)
        copy = menu.addAction("Copy")
        copy.setEnabled(self.hasSelectedText())
        copy.triggered.connect(self.copy)
        paste = menu.addAction("Paste")
        paste.setEnabled(not self.isReadOnly() and bool(qt.QtWidgets.QApplication.clipboard().text()))
        paste.triggered.connect(self.paste)
        menu.exec(event.globalPos())
