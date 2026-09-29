# tools/desktop/maya_gate/user_setup_tab.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.widgets.atoms.editors import CodeEditor
from msl_tools.msl.tools.desktop.maya_gate.user_setup import UserSetupStore


class UserSetupTab(qt.QtWidgets.QWidget):
    """Maya Gate's "userSetup" tab: a code editor for the current
    environment's startup script, which Maya runs next to the user's own
    userSetup.py when launched from Maya Gate (see UserSetupStore).

    One script per environment — switching the environment in the toolbar
    saves the current script and loads that environment's one.

    Saving is automatic (debounced while typing, flushed on environment
    switch and on hide). No file I/O at construction: the first read
    happens when the tab is first shown.
    """

    SAVE_DELAY_MS = 600

    def __init__(self, store: UserSetupStore, environment: str, parent=None):
        super().__init__(parent)
        self._store = store
        self._environment = environment
        self._loaded_environment: str | None = None
        self._dirty = False

        self._build_widgets()
        self._build_layout()
        self._build_connections()
        self._update_title()

    def _build_widgets(self) -> None:
        self._title_label = qt.QtWidgets.QLabel()
        self._status_label = qt.QtWidgets.QLabel()
        self._status_label.setEnabled(False)  # dimmed: secondary info

        self._insert_menu_button = qt.QtWidgets.QPushButton("Insert MSL menu")
        self._insert_menu_button.setToolTip("Append code that loads the msl_tools main menu in Maya")
        self._open_folder_button = qt.QtWidgets.QPushButton("Open folder")
        self._open_folder_button.setToolTip("Show the script file in the file explorer")

        self.editor = CodeEditor()
        self.editor.setPlaceholderText("# Python run at Maya startup, next to your own userSetup.py.\n"
                                       "# Leave empty to launch Maya without it.")

        self._hint_label = qt.QtWidgets.QLabel(
            "Runs at Maya startup together with your own userSetup.py. Empty = not injected.")
        self._hint_label.setEnabled(False)

        self._save_timer = qt.QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DELAY_MS)

    def _build_layout(self) -> None:
        header = qt.QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self._title_label)
        header.addWidget(self._status_label)
        header.addStretch()
        header.addWidget(self._insert_menu_button)
        header.addWidget(self._open_folder_button)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(5)
        layout.addLayout(header)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self._hint_label)

    def _build_connections(self) -> None:
        self.editor.textChanged.connect(self._on_text_changed)
        self._save_timer.timeout.connect(self.save)
        self._insert_menu_button.clicked.connect(self._insert_menu_snippet)
        self._open_folder_button.clicked.connect(self._open_folder)

    # --- public API ------------------------------------------------------------

    def set_environment(self, environment: str) -> None:
        """Saves the current script, then shows `environment`'s one."""
        self.save()
        self._environment = environment
        self._update_title()
        if self.isVisible():
            self._load()

    def save(self) -> None:
        """Writes pending edits now (no-op when nothing changed)."""
        self._save_timer.stop()
        if not self._dirty or self._loaded_environment is None:
            return
        self._store.write(self._loaded_environment, self.editor.toPlainText())
        self._dirty = False
        self._status_label.setText("Saved")

    # --- internals -------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._loaded_environment != self._environment:
            self._load()

    def hideEvent(self, event) -> None:
        self.save()
        super().hideEvent(event)

    def _load(self) -> None:
        text = self._store.read(self._environment)
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._loaded_environment = self._environment
        self._dirty = False
        self._status_label.setText("")

    def _on_text_changed(self) -> None:
        self._dirty = True
        self._status_label.setText("Editing…")
        self._save_timer.start()

    def _update_title(self) -> None:
        self._title_label.setText(f"userSetup · {self._environment}")

    def _insert_menu_snippet(self) -> None:
        snippet = UserSetupStore.msl_menu_snippet()
        if snippet in self.editor.toPlainText():
            return
        cursor = self.editor.textCursor()
        cursor.movePosition(qt.QtGui.QTextCursor.MoveOperation.End)
        prefix = "" if not self.editor.toPlainText() or self.editor.toPlainText().endswith("\n\n") else (
            "\n" if self.editor.toPlainText().endswith("\n") else "\n\n")
        cursor.insertText(prefix + snippet)
        self.editor.setTextCursor(cursor)

    def _open_folder(self) -> None:
        # Make sure there's something to show — even an empty script file.
        if self._dirty or not self._store.script_path(self._environment).is_file():
            self._dirty = True
            self.save()
        ProcessLauncher.open_file_explorer(self._store.script_path(self._environment))
