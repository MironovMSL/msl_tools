# ui/widgets/windows/text_dialog.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.scrollbars import SlimScrollBar
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class TextDialog(FramelessDialog):
    """A window that shows a block of plain text to read and copy — a
    report, a log — in a fixed-width font, with "Copy all".

    Read-only; the text can still be selected. Resizable (reports are wide).
    Colors: ui/theme/widgets.qss (QPlainTextEdit#textDialogView).

    Usage:
        TextDialog.show_for(self, "Launch report", text)
    """

    WIDTH = 760
    HEIGHT = 620
    FONT_FAMILIES = ("Cascadia Mono", "JetBrains Mono", "Consolas")
    FONT_POINT_SIZE = 9
    COPIED_MS = 1500

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(title=title, width=self.WIDTH, height=self.HEIGHT,
                         show_minimize_button=False, show_theme_toggle=False, parent=parent)
        self.view = qt.QtWidgets.QPlainTextEdit()
        self.view.setObjectName("textDialogView")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(qt.QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFont(self._fixed_font())
        self.view.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical))
        self.view.setHorizontalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Horizontal))
        self.view.setPlainText(text)

        self._copy_button = qt.QtWidgets.QPushButton("Copy all")
        self._copy_button.clicked.connect(self._on_copy)
        close_button = qt.QtWidgets.QPushButton("Close")
        close_button.setProperty("primary", True)
        close_button.clicked.connect(self.accept)

        buttons = qt.QtWidgets.QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch()
        buttons.addWidget(self._copy_button)
        buttons.addWidget(close_button)
        button_row = qt.QtWidgets.QWidget()
        button_row.setLayout(buttons)

        self.add_widget(self.view)
        self.add_widget(button_row)

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

    def _on_copy(self) -> None:
        qt.QtGui.QGuiApplication.clipboard().setText(self.view.toPlainText())
        self._copy_button.setText("Copied")
        qt.QtCore.QTimer.singleShot(self.COPIED_MS, lambda: self._copy_button.setText("Copy all"))

    @classmethod
    def show_for(cls, parent, title: str, text: str) -> None:
        """Opens the dialog modally over `parent`'s window (blurred behind it
        if it's a frameless window, like ConfirmDialog.ask())."""
        dialog = cls(title, text, parent=parent)
        window = parent.window() if parent is not None else None
        blur = getattr(window, "set_blurred", None)
        if blur is not None:
            blur(True)
        try:
            dialog.exec()
        finally:
            if blur is not None:
                blur(False)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        playground = ThemedWidgetPlaygroundDialog()
        button = qt.QtWidgets.QPushButton("Show a report…")
        sample = "\n".join(f"  line {number:3d}   some fixed-width text" for number in range(1, 80))
        button.clicked.connect(lambda: TextDialog.show_for(playground, "Report", sample))
        playground.add_case("TextDialog", button)
        playground.show()
