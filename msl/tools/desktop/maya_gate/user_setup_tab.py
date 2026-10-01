# tools/desktop/maya_gate/user_setup_tab.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons import IconPushButton
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

    The status next to the title says where the script stands
    (QLabel#userSetupStatus[state=...], maya_gate.qss): "editing" while
    typing; after each save / load "saved", "off" (blank script — Maya
    starts without it) or "error" — a syntax error, with its line marked in
    the editor (the script is saved anyway; Maya's wrapper would only print
    the error at startup, far from here).
    """

    SAVE_DELAY_MS = 600

    def __init__(self, store: UserSetupStore, environment: str, parent=None):
        super().__init__(parent)
        self._store = store
        self._environment = environment
        self._loaded_environment: str | None = None
        self._dirty = False
        self._saved_text = ""  # what is on disk (or the default): the baseline for "edited"

        self._build_widgets()
        self._build_layout()
        self._build_connections()
        self._update_title()

    def _build_widgets(self) -> None:
        self._title_label = qt.QtWidgets.QLabel("userSetup")
        self._title_label.setObjectName("userSetupTitle")
        self._section_label = qt.QtWidgets.QLabel()
        self._section_label.setObjectName("userSetupSection")
        self._status_label = qt.QtWidgets.QLabel()
        self._status_label.setObjectName("userSetupStatus")

        icons = UiResources().iconManager
        self._insert_menu_button = IconPushButton(icons.get_icon("add", sub_folder="actions"))
        self._insert_menu_button.setText("Insert MSL menu")
        self._insert_menu_button.setToolTip(
            "Put back the code that loads the msl_tools main menu in Maya\n"
            "(also rewrites an old, longer version of it)")
        self._open_folder_button = IconPushButton(icons.get_icon("browse", sub_folder="actions"))
        self._open_folder_button.setText("Open folder")
        self._open_folder_button.setToolTip("Show the script file in the file explorer")

        self.editor = CodeEditor()
        self.editor.setPlaceholderText("# Python run at Maya startup, next to your own userSetup.py.\n"
                                       "# Leave empty to launch Maya without it.\n"
                                       "# \"Insert MSL menu\" puts the msl_tools menu code back.")

        self._hint_label = qt.QtWidgets.QLabel(
            "Runs at Maya startup together with your own userSetup.py. Empty = not injected. "
            "msl_tools is importable in Maya started from here.")
        self._hint_label.setToolTip(
            f"Maya Gate adds this folder to PYTHONPATH on every launch:\n{self._store.package_parent_dir()}")
        self._hint_label.setObjectName("userSetupHint")

        self._save_timer = qt.QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DELAY_MS)

    def _build_layout(self) -> None:
        header = qt.QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self._title_label)
        header.addWidget(self._section_label)
        header.addSpacing(6)
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
        self._saved_text = self.editor.toPlainText()
        self._store.write(self._loaded_environment, self._saved_text)
        self._dirty = False
        self._show_script_state(just_saved=True)

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
        self._saved_text = text
        self._loaded_environment = self._environment
        self._dirty = False
        self._show_script_state(just_saved=False)

    def _on_text_changed(self) -> None:
        # textChanged also fires when only the FORMATTING changes (a theme switch
        # re-highlights the code) — that is not an edit: nothing to save.
        if self.editor.toPlainText() == self._saved_text:
            if self._dirty:  # typed, then undone back to the saved text
                self._dirty = False
                self._save_timer.stop()
                self._show_script_state(just_saved=False)
            return
        self._dirty = True
        self._set_status("editing", "Editing\u2026")
        self._save_timer.start()

    def _update_title(self) -> None:
        self._section_label.setText(f"\u00b7 {self._environment}")

    # --- status ----------------------------------------------------------------

    def _set_status(self, state: str, text: str, tooltip: str = "") -> None:
        self._status_label.setText(text)
        self._status_label.setToolTip(tooltip)
        if self._status_label.property("state") != state:
            self._status_label.setProperty("state", state)
            repolish(self._status_label)

    def _show_script_state(self, just_saved: bool) -> None:
        """Status + error mark for the script as it now stands (after a save
        or a load): blank, broken, or fine."""
        text = self.editor.toPlainText()
        error = self._store.syntax_error(text) if text.strip() else None
        self.editor.set_error_line(error[0] if error else None)
        if not text.strip():
            self._set_status("off", "Empty \u2014 Maya starts without it")
        elif error:
            line, message = error
            self._set_status("error", f"Syntax error \u00b7 line {line}: {message}",
                             "The script is saved, but Maya will fail to run it.")
        else:
            self._set_status("saved", "Saved" if just_saved else "")

    def _insert_menu_snippet(self) -> None:
        """Makes sure the script has the menu snippet, once and in its current
        (short) form: rewrites an old long block in place, else appends it."""
        text = self.editor.toPlainText()
        upgraded = UserSetupStore.upgrade_menu_snippet(text)
        if UserSetupStore.MENU_SNIPPET not in upgraded:
            gap = "" if not upgraded or upgraded.endswith("\n\n") else ("\n" if upgraded.endswith("\n") else "\n\n")
            upgraded += gap + UserSetupStore.MENU_SNIPPET
        if upgraded == text:
            return
        # Through a cursor, not setPlainText(): stays one undoable step (Ctrl+Z).
        cursor = self.editor.textCursor()
        cursor.select(qt.QtGui.QTextCursor.SelectionType.Document)
        cursor.insertText(upgraded)
        self.editor.setTextCursor(cursor)

    def _open_folder(self) -> None:
        # Make sure there's something to show — even an empty script file.
        if self._dirty or not self._store.script_path(self._environment).is_file():
            self._dirty = True
            self.save()
        ProcessLauncher.open_file_explorer(self._store.script_path(self._environment))
