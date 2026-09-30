# ui/widgets/atoms/editors/code_editor.py
import keyword
import re

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme, ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.atoms.scrollbars import SlimScrollBar


# Colored as constants, not keywords. Module level: the class body's rule list
# builds a generator, and a generator in a class body can't see class attributes.
_CONSTANTS = ("True", "False", "None")


class _PythonHighlighter(qt.QtGui.QSyntaxHighlighter):
    """Private: small regex-based Python highlighter. Good enough for short
    startup scripts; not a tokenizer (triple-quoted strings spanning lines
    are colored per line only)."""

    _RULES = [
        ("keyword", r"\b(?:" + "|".join(k for k in keyword.kwlist if k not in _CONSTANTS) + r")\b"),
        ("constant", r"\b(?:True|False|None)\b"),
        ("self", r"\b(?:self|cls)\b"),
        ("builtin", r"\b(?:print|len|range|open|str|int|float|bool|dict|list|set|tuple|isinstance|"
                    r"super|enumerate|zip|sorted|min|max|any|all|getattr|setattr|hasattr|type|object|"
                    r"Exception)\b"),
        ("number", r"\b\d+(?:\.\d+)?\b"),
        ("definition", r"(?<=\bdef\s)\w+|(?<=\bclass\s)\w+"),
        ("decorator", r"@[\w.]+"),
        ("string", r"[rbfuRBFU]{0,2}(\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^'\\]*(?:\\.[^'\\]*)*')"),
        ("comment", r"#[^\n]*"),
    ]

    def __init__(self, document, colors: dict[str, qt.QtGui.QColor]):
        super().__init__(document)
        self._patterns = [(name, re.compile(pattern)) for name, pattern in self._RULES]
        self._formats: dict[str, qt.QtGui.QTextCharFormat] = {}
        self.set_colors(colors)

    def set_colors(self, colors: dict[str, qt.QtGui.QColor]) -> None:
        """Colors per rule name (see _RULES). Color alone tells the kinds apart —
        no bold (it would make columns uneven); comments are italic."""
        self._formats = {}
        for name, color in colors.items():
            fmt = qt.QtGui.QTextCharFormat()
            fmt.setForeground(color)
            if name == "comment":
                fmt.setFontItalic(True)
            self._formats[name] = fmt
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        # Later rules win: strings and comments are applied last, so keywords
        # inside them don't stay highlighted.
        for name, pattern in self._patterns:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), self._formats[name])


class _LineNumberArea(qt.QtWidgets.QWidget):
    """Private: the gutter left of the text, painted by CodeEditor."""

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class CodeEditor(qt.QtWidgets.QPlainTextEdit):
    """Plain-text code editor for short Python scripts: monospace font,
    line numbers, current-line highlight, Python syntax colors, Tab/Shift+Tab
    (de)indent by 4 spaces, and auto-indent on Enter (one level deeper after
    a line ending in ':').

    Colors are Qt properties set by the window stylesheet (ui/theme/
    widgets.qss, from the palettes' --syntax-* tokens), which also styles
    the frame/background as `CodeEditor`: keywordColor, constantColor,
    selfColor, builtinColor, definitionColor, decoratorColor, numberColor,
    stringColor, commentColor; gutter: lineNumberColor,
    currentLineNumberColor, gutterDividerColor; currentLineColor.
    Until it applies (or outside a styled window) they hold the default
    theme's colors.

    Font: the first installed of FONT_FAMILIES (Consolas ships with
    Windows), else the system fixed font. The line-number gutter is ruled
    off from the text by a thin divider, with TEXT_MARGIN px before the code.
    """

    INDENT = "    "
    FONT_POINT_SIZE = 10
    FONT_FAMILIES = ("Cascadia Mono", "JetBrains Mono", "Consolas", "Menlo", "DejaVu Sans Mono")
    LINE_NUMBER_PADDING = 8
    TEXT_MARGIN = 6
    CURRENT_LINE_ALPHA = 22

    keywordColor = color_property("_keyword_color", "_on_syntax_colors_changed")
    definitionColor = color_property("_definition_color", "_on_syntax_colors_changed")
    numberColor = color_property("_number_color", "_on_syntax_colors_changed")
    stringColor = color_property("_string_color", "_on_syntax_colors_changed")
    commentColor = color_property("_comment_color", "_on_syntax_colors_changed")
    constantColor = color_property("_constant_color", "_on_syntax_colors_changed")
    selfColor = color_property("_self_color", "_on_syntax_colors_changed")
    builtinColor = color_property("_builtin_color", "_on_syntax_colors_changed")
    decoratorColor = color_property("_decorator_color", "_on_syntax_colors_changed")
    gutterDividerColor = color_property("_gutter_divider_color", "_on_gutter_colors_changed")
    lineNumberColor = color_property("_line_number_color", "_on_gutter_colors_changed")
    currentLineNumberColor = color_property("_current_line_number_color", "_on_gutter_colors_changed")
    currentLineColor = color_property("_current_line_color", "_highlight_current_line")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlighter = None  # property setters can run before it exists
        self._line_numbers = None
        self._seed_colors(ThemeRegistry.fallback())

        font = self._code_font()
        self.setFont(font)
        self.setLineWrapMode(qt.QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(qt.QtGui.QFontMetricsF(font).horizontalAdvance(" ") * len(self.INDENT))
        self.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical))  # widen on hover
        self.setHorizontalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Horizontal))

        self.document().setDocumentMargin(self.TEXT_MARGIN)  # room between the gutter divider and the code
        self._line_numbers = _LineNumberArea(self)
        self._highlighter = _PythonHighlighter(self.document(), self._syntax_colors())

        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_margins()
        self._highlight_current_line()

    # --- theming ---------------------------------------------------------------

    def _seed_colors(self, theme: Theme) -> None:
        """Defaults until QSS applies — same mapping as widgets.qss."""
        self._keyword_color = qt.QtGui.QColor(theme.accent)
        self._definition_color = qt.QtGui.QColor(theme.warning)
        self._number_color = qt.QtGui.QColor(theme.warning)
        self._string_color = qt.QtGui.QColor(theme.success)
        self._comment_color = qt.QtGui.QColor(theme.text_secondary)
        self._constant_color = qt.QtGui.QColor(theme.accent)
        self._self_color = qt.QtGui.QColor(theme.text_primary)
        self._builtin_color = qt.QtGui.QColor(theme.accent)
        self._decorator_color = qt.QtGui.QColor(theme.warning)
        self._gutter_divider_color = qt.QtGui.QColor(theme.border)
        self._line_number_color = qt.QtGui.QColor(theme.text_secondary)
        self._current_line_number_color = qt.QtGui.QColor(theme.text_primary)
        self._current_line_color = qt.QtGui.QColor(theme.text_primary)
        self._current_line_color.setAlpha(self.CURRENT_LINE_ALPHA)

    @classmethod
    def _code_font(cls) -> qt.QtGui.QFont:
        installed = set(qt.QtGui.QFontDatabase.families())
        family = next((name for name in cls.FONT_FAMILIES if name in installed), None)
        if family is None:
            font = qt.QtGui.QFontDatabase.systemFont(qt.QtGui.QFontDatabase.SystemFont.FixedFont)
        else:
            font = qt.QtGui.QFont(family)
        font.setStyleHint(qt.QtGui.QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(cls.FONT_POINT_SIZE)
        return font

    def _syntax_colors(self) -> dict[str, qt.QtGui.QColor]:
        return {
            "keyword": self._keyword_color, "constant": self._constant_color,
            "self": self._self_color, "builtin": self._builtin_color,
            "definition": self._definition_color, "decorator": self._decorator_color,
            "number": self._number_color, "string": self._string_color,
            "comment": self._comment_color,
        }

    def _on_syntax_colors_changed(self) -> None:
        if self._highlighter is not None:
            self._highlighter.set_colors(self._syntax_colors())

    def _on_gutter_colors_changed(self) -> None:
        if self._line_numbers is not None:
            self._line_numbers.update()


    # --- line numbers ------------------------------------------------------------

    def line_number_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return self.fontMetrics().horizontalAdvance("9") * digits + self.LINE_NUMBER_PADDING * 2

    def _update_margins(self, *_) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy) -> None:
        if dy:
            self._line_numbers.scroll(0, dy)
        else:
            self._line_numbers.update(0, rect.y(), self._line_numbers.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_numbers.setGeometry(
            qt.QtCore.QRect(contents.left(), contents.top(), self.line_number_width(), contents.height()))

    def paint_line_numbers(self, event) -> None:
        painter = qt.QtGui.QPainter(self._line_numbers)
        painter.setFont(self.font())
        current = self.textCursor().blockNumber()

        # Divider on the gutter's right edge, between the numbers and the code.
        x = self._line_numbers.width() - 0.5
        painter.setPen(qt.QtGui.QPen(self._gutter_divider_color, 1))
        painter.drawLine(qt.QtCore.QPointF(x, event.rect().top()), qt.QtCore.QPointF(x, event.rect().bottom() + 1))

        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        width = self._line_numbers.width() - self.LINE_NUMBER_PADDING
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                is_current = block.blockNumber() == current
                painter.setPen(self._current_line_number_color if is_current else self._line_number_color)
                painter.drawText(0, top, width, height, int(qt.QtCore.Qt.AlignmentFlag.AlignRight),
                                 str(block.blockNumber() + 1))
            top += round(self.blockBoundingRect(block).height())
            block = block.next()
        painter.end()

    def _highlight_current_line(self) -> None:
        if self._line_numbers is None:
            return  # a QSS property arrived before construction finished
        selection = qt.QtWidgets.QTextEdit.ExtraSelection()
        selection.format.setBackground(self._current_line_color)
        selection.format.setProperty(qt.QtGui.QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self._line_numbers.update()

    # --- editing -------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == qt.QtCore.Qt.Key.Key_Tab and not self.textCursor().hasSelection():
            self.textCursor().insertText(self.INDENT)
        elif key == qt.QtCore.Qt.Key.Key_Tab:
            self._shift_selected_lines(indent=True)
        elif key == qt.QtCore.Qt.Key.Key_Backtab:
            self._shift_selected_lines(indent=False)
        elif key in (qt.QtCore.Qt.Key.Key_Return, qt.QtCore.Qt.Key.Key_Enter):
            self._newline_with_indent()
        else:
            super().keyPressEvent(event)

    def _newline_with_indent(self) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()[:cursor.positionInBlock()]
        indent = line[:len(line) - len(line.lstrip())]
        if line.rstrip().endswith(":"):
            indent += self.INDENT
        cursor.insertText("\n" + indent)

    def _shift_selected_lines(self, indent: bool) -> None:
        cursor = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(max(cursor.selectionEnd() - 1, cursor.selectionStart())).blockNumber()

        cursor.beginEditBlock()
        for number in range(first, last + 1):
            block = doc.findBlockByNumber(number)
            line_cursor = qt.QtGui.QTextCursor(block)
            if indent:
                line_cursor.insertText(self.INDENT)
            else:
                text = block.text()
                remove = len(text) - len(text.lstrip(" "))
                remove = min(remove, len(self.INDENT))
                line_cursor.movePosition(qt.QtGui.QTextCursor.MoveOperation.Right,
                                         qt.QtGui.QTextCursor.MoveMode.KeepAnchor, remove)
                line_cursor.removeSelectedText()
        cursor.endEditBlock()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        editor = CodeEditor()
        editor.setPlainText(
            "# userSetup example\n"
            "import maya.utils\n\n"
            "def hello(name):\n"
            "    print(\"Hello, \" + name)  # greet\n\n"
            "maya.utils.executeDeferred(hello, 'Maya')\n"
        )
        editor.setMinimumSize(520, 260)
        dialog.add_case("CodeEditor", editor)
        dialog.show()
