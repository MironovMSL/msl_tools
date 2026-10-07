# tools/maya/rename/word_fields.py
"""Line edits of the rename tool that complete the word being typed from the name library: the
name field (TemplateField, also takes {tokens}) and the plain ones (WordField: prefix, suffix,
find, replace)."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.ui.theme.qss import adopt_popup
from msl_tools.msl.ui.widgets.atoms.editors.token_line_edit import TokenLineEdit
from msl_tools.msl.ui.widgets.atoms.scrollbars.slim_scroll_bar import SlimScrollBar

_CATEGORY = qt.QtCore.Qt.ItemDataRole.UserRole + 7


class _WordDelegate(qt.QtWidgets.QStyledItemDelegate):
    """A row of the completion list: the word, and quietly on the right the category it is from."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        category = index.data(_CATEGORY)
        if not category:
            return
        painter.save()
        color = qt.QtGui.QColor(option.palette.color(qt.QtGui.QPalette.ColorRole.Text))
        color.setAlpha(110)
        painter.setPen(color)
        font = qt.QtGui.QFont(option.font)
        font.setPointSizeF(max(6.0, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.drawText(option.rect.adjusted(0, 0, -8, 0),
                         int(qt.QtCore.Qt.AlignmentFlag.AlignRight | qt.QtCore.Qt.AlignmentFlag.AlignVCenter), category)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        category = index.data(_CATEGORY) or ""
        return qt.QtCore.QSize(size.width() + option.fontMetrics.horizontalAdvance(category) + 24, size.height())


class _WordCompletion:
    """Completion of the word under the cursor — the part after the last "_" (or "}") — from a list
    of (word, category). From the first letter; words that START with what is typed come first,
    then those that only contain it ("der" -> shoulder). Tab or Enter takes the highlighted one,
    Esc closes the list. The owner hands the words in with set_words()."""

    MAX_SHOWN = 12

    def _setup_completion(self) -> None:
        self._all_words: list = []
        self._model = qt.QtGui.QStandardItemModel(self)
        self._completer = qt.QtWidgets.QCompleter(self._model, self)
        self._completer.setCompletionMode(qt.QtWidgets.QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setWidget(self)
        popup = self._completer.popup()
        # rename.qss: the look of our drop-down lists. NOT make_rounded_popup: a translucent list
        # view paints no ground at all (only its text showed — measured in Maya 2025)
        popup.setObjectName("wordCompleter")
        popup.setItemDelegate(_WordDelegate(popup))
        popup.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical, popup))
        self._completer.setMaxVisibleItems(self.MAX_SHOWN)
        self._completer.activated[qt.QtCore.QModelIndex].connect(self._take_index)
        self.textEdited.connect(self._on_edited)

    def set_words(self, words) -> None:
        """`words`: (word, category) pairs, or plain words."""
        self._all_words = [(entry, "") if isinstance(entry, str) else (entry[0], entry[1]) for entry in words]

    def _word_bounds(self) -> tuple[int, int]:
        text, cursor = self.text(), self.cursorPosition()
        start = max(text.rfind("_", 0, cursor), text.rfind("}", 0, cursor), text.rfind(":", 0, cursor)) + 1
        return start, cursor

    def _matches(self, typed: str) -> list:
        low = typed.lower()
        first = [pair for pair in self._all_words if pair[0].lower().startswith(low)]
        then = [pair for pair in self._all_words if low in pair[0].lower() and pair not in first]
        seen, result = set(), []
        for word, category in first + then:
            if word not in seen and word.lower() != low:
                seen.add(word)
                result.append((word, category))
        return result[:self.MAX_SHOWN]

    def _on_edited(self, _text) -> None:
        start, cursor = self._word_bounds()
        typed = self.text()[start:cursor]
        popup = self._completer.popup()
        matches = self._matches(typed) if typed else []
        if not matches:
            popup.hide()
            return
        self._model.clear()
        for word, category in matches:
            item = qt.QtGui.QStandardItem(word)
            item.setData(category, _CATEGORY)
            if category:
                item.setToolTip(category)
            self._model.appendRow(item)
        adopt_popup(popup, self)
        rect = self.cursorRect()
        rect.setWidth(max(180, popup.sizeHintForColumn(0) + 12))
        self._completer.complete(rect)
        popup.setCurrentIndex(self._model.index(0, 0))

    def _take_index(self, index) -> None:
        self._take(index.data())

    def _take(self, word: str) -> None:
        if not word:
            return
        start, cursor = self._word_bounds()
        text = self.text()
        self.setText(text[:start] + word + text[cursor:])
        self.setCursorPosition(start + len(word))
        self.textEdited.emit(self.text())

    def keyPressEvent(self, event) -> None:
        popup = self._completer.popup()
        if popup.isVisible() and event.key() in (qt.QtCore.Qt.Key.Key_Tab, qt.QtCore.Qt.Key.Key_Return,
                                                 qt.QtCore.Qt.Key.Key_Enter):
            index = popup.currentIndex()
            word = index.data() if index.isValid() else ""
            popup.hide()
            self._take(word)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, forward: bool) -> bool:
        return False if self._completer.popup().isVisible() else super().focusNextPrevChild(forward)


class TemplateField(_WordCompletion, TokenLineEdit):
    """The name field: a template with {tokens} (a right click lists them) + word completion."""

    def __init__(self, parent=None):
        super().__init__({token.strip("{}"): meaning for token, meaning in rules.TOKEN_HELP.items()}, parent)
        self._setup_completion()


class WordField(_WordCompletion, qt.QtWidgets.QLineEdit):
    """A plain field with word completion (prefix, suffix, find, replace).

    Signals:
        focused() — it got the keyboard focus.
    """

    focused = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_completion()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit()
