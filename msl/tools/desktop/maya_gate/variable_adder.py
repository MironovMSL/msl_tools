# tools/desktop/maya_gate/variable_adder.py
import msl_tools.msl.ui.qt_bindings as qt


class EnvVariableAdder(qt.QtWidgets.QWidget):
    """Row for adding a new environment variable to Maya Gate's config —
    either pick a known Maya variable (added to whichever environment is
    currently selected) or type a custom one (always added to the fixed
    "Additional" section, applied regardless of environment).

    That known-vs-custom split isn't just labeling — it's real routing:
    in the original (MSL_MayaGate's EnvVariableAdder +
    MayaLauncher.add_new_variable), which target section a new variable
    goes to depends on which button/field it came from. Kept as two
    separate signals here so that routing lives with the caller instead
    of being re-derived from a string tag.

    Storage-agnostic — never touches config itself. Icon-file buttons
    (add1.svg etc.) replaced with a plain "+" — no matching assets in
    msl_tools yet (same reasoning as EnvVarRow's hover panels).

    Signals:
        known_variable_added(str) — name picked from the known-variables
            dropdown; the caller adds it to the CURRENT environment.
        custom_variable_added(str) — freeform name typed by the user; the
            caller adds it to the "Additional" section.
    """

    KNOWN_VARIABLES = [
        "MAYA_PLUG_IN_PATH", "MAYA_MODULE_PATH", "MAYA_SCRIPT_PATH", "MAYA_SHELF_PATH",
        "XBMLANGPATH", "MAYA_APP_DIR", "MAYA_ENV_DIR", "MAYA_LOCATION", "PYTHONPATH", "TEMP",
        "MAYA_PROJECT", "MAYA_SHADER_PATH", "MAYA_ICON_PATH",
    ]

    HEIGHT = 25
    COMBO_WIDTH = 170
    LINE_EDIT_WIDTH = 170
    ADD_BUTTON_SIZE = qt.QtCore.QSize(25, 25)

    known_variable_added = qt.QtCore.Signal(str)
    custom_variable_added = qt.QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self._build_widgets()
        self._build_layout()
        self._build_connections()

    def _build_widgets(self) -> None:
        self.add_known_button = qt.QtWidgets.QPushButton("+")
        self.add_known_button.setFixedSize(self.ADD_BUTTON_SIZE)
        self.add_known_button.setFlat(True)

        self.known_combo = qt.QtWidgets.QComboBox()
        self.known_combo.addItems(self.KNOWN_VARIABLES)
        self.known_combo.setFixedWidth(self.COMBO_WIDTH)
        self.known_combo.setCurrentIndex(-1)
        self.known_combo.setEditable(True)
        self.known_combo.lineEdit().setPlaceholderText("Maya Variables")

        completer = qt.QtWidgets.QCompleter(self.KNOWN_VARIABLES, self.known_combo)
        completer.setCaseSensitivity(qt.QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(qt.QtCore.Qt.MatchFlag.MatchContains)
        self.known_combo.setCompleter(completer)

        self.custom_line_edit = qt.QtWidgets.QLineEdit()
        self.custom_line_edit.setPlaceholderText("New Variable")
        self.custom_line_edit.setFixedWidth(self.LINE_EDIT_WIDTH)

        self.add_custom_button = qt.QtWidgets.QPushButton("+")
        self.add_custom_button.setFixedSize(self.ADD_BUTTON_SIZE)
        self.add_custom_button.setFlat(True)

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self.add_known_button)
        layout.addWidget(self.known_combo)
        layout.addStretch()
        layout.addWidget(self.custom_line_edit)
        layout.addWidget(self.add_custom_button)

    def _build_connections(self) -> None:
        self.add_known_button.clicked.connect(self._on_add_known)
        self.known_combo.lineEdit().returnPressed.connect(self._on_add_known)
        self.add_custom_button.clicked.connect(self._on_add_custom)
        self.custom_line_edit.returnPressed.connect(self._on_add_custom)

    def _on_add_known(self) -> None:
        var = self.known_combo.currentText()
        if var and var in self.KNOWN_VARIABLES:
            self.known_variable_added.emit(var)

    def _on_add_custom(self) -> None:
        var = self.custom_line_edit.text()
        if var:
            self.custom_variable_added.emit(var)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        adder = EnvVariableAdder()
        adder.known_variable_added.connect(lambda v: print("known:", v))
        adder.custom_variable_added.connect(lambda v: print("custom:", v))
        dialog.add_case("EnvVariableAdder", adder)
        dialog.show()