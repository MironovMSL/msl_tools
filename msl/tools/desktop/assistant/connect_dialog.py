# tools/desktop/assistant/connect_dialog.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import assistant_setup as setup
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog


class ConnectAssistantDialog(FramelessDialog):
    """How to give a coding assistant the msl-maya tools - for an INSTALLED copy, which
    has no `.mcp.json` of its own (core/link/assistant_setup.py makes the texts).

    Three ways, most common first: the one line for Claude Code (every project on this
    computer), `.mcp.json` written into one chosen folder, and the JSON block other
    assistants' MCP settings take. Each has its own Copy; nothing is run from here.
    Looks: ui/theme/widgets.qss (ConnectAssistantDialog ...).
    """

    WIDTH = 640
    COPIED_MS = 1500

    def __init__(self, parent=None):
        super().__init__(title="Connect a coding assistant", width=self.WIDTH, height=10,
                         show_minimize_button=False, show_maximize_button=False,
                         show_theme_toggle=False, parent=parent)
        self._entry = setup.server_entry()

        self._command = qt.QtWidgets.QLineEdit(setup.claude_command(self._entry))
        self._command.setObjectName("connectCode")
        self._command.setReadOnly(True)
        self._command.setFont(TextDialog._fixed_font())
        self._command.setCursorPosition(0)

        self._folder_status = qt.QtWidgets.QLabel()
        self._folder_status.setObjectName("connectStatus")
        self._folder_status.setWordWrap(True)
        self._folder_status.hide()

        self._json = qt.QtWidgets.QPlainTextEdit(setup.config_text(self._entry))
        self._json.setObjectName("connectJson")
        self._json.setReadOnly(True)
        self._json.setFont(TextDialog._fixed_font())
        self._json.setLineWrapMode(qt.QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self._json.setFixedHeight(self._json.fontMetrics().lineSpacing() * 10 + 16)

        write_button = qt.QtWidgets.QPushButton("Write .mcp.json into a folder…")
        write_button.clicked.connect(self._on_write)
        close_button = qt.QtWidgets.QPushButton("Close")
        close_button.setProperty("primary", True)
        close_button.clicked.connect(self.accept)

        self.add_widget(self._section(
            "Claude Code — every project on this computer",
            "Run this once in a terminal (PowerShell or cmd). A Claude Code session started "
            "after it has the tools: the Mayas connected to MSL Tools, their logs, their viewports "
            "and — when you allow it at the robot’s head — Python in them.",
            self._row(self._command, self._copy_button(lambda: self._command.text()))))
        self.add_widget(self._section(
            "Claude Code — one project only",
            "Puts the server into that folder’s .mcp.json (other servers in it stay); "
            "Claude Code started in that folder asks once whether to use it.",
            self._row(write_button, None), self._folder_status))
        self.add_widget(self._section(
            "Other assistants",
            "Most take MCP servers as JSON like this, in their own settings file.",
            self._json, self._row(None, self._copy_button(lambda: self._json.toPlainText()))))
        self.add_widget(self._row(None, close_button))

    # --- building -------------------------------------------------------------------

    @staticmethod
    def _section(title: str, hint: str, *widgets) -> qt.QtWidgets.QWidget:
        box = qt.QtWidgets.QWidget()
        layout = qt.QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(5)
        caption = qt.QtWidgets.QLabel(title)
        caption.setObjectName("connectCaption")
        note = qt.QtWidgets.QLabel(hint)
        note.setObjectName("connectHint")
        note.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(note)
        for widget in widgets:
            layout.addWidget(widget)
        return box

    @staticmethod
    def _row(first, last) -> qt.QtWidgets.QWidget:
        row = qt.QtWidgets.QWidget()
        layout = qt.QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if first is not None:
            layout.addWidget(first, 1 if isinstance(first, qt.QtWidgets.QLineEdit) else 0)
        layout.addStretch(0 if isinstance(first, qt.QtWidgets.QLineEdit) else 1)
        if last is not None:
            layout.addWidget(last)
        return row

    def _copy_button(self, text) -> qt.QtWidgets.QPushButton:
        button = qt.QtWidgets.QPushButton("Copy")

        def copy() -> None:
            qt.QtGui.QGuiApplication.clipboard().setText(text())
            button.setText("Copied")
            qt.QtCore.QTimer.singleShot(self.COPIED_MS, lambda: button.setText("Copy"))

        button.clicked.connect(copy)
        return button

    # --- one project ------------------------------------------------------------------

    def _on_write(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The project folder Claude Code works in")
        if folder:
            self.write_into(folder)

    def write_into(self, folder: str) -> bool:
        """Writes the server into `folder`'s .mcp.json and says how it went (False = it didn't)."""
        try:
            path = setup.write_project_config(folder, self._entry)
        except OSError as error:
            self._say("Not written: %s" % error, "error")
            return False
        self._say("Written: %s" % path, "done")
        return True

    def _say(self, text: str, state: str) -> None:
        self._folder_status.setText(text)
        self._folder_status.setProperty("state", state)
        repolish(self._folder_status)
        self._folder_status.show()

    @classmethod
    def show_for(cls, parent) -> None:
        """Opens the dialog modally over `parent`'s window (blurred behind it, like ConfirmDialog.ask())."""
        dialog = cls(parent=parent)
        window = parent.window() if parent is not None else None
        blur = getattr(window, "set_blurred", None)
        if blur is not None:
            blur(True)
        try:
            dialog.exec()
        finally:
            if blur is not None:
                blur(False)
