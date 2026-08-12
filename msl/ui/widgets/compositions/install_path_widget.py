# ui/widgets/compositions/install_path_widget.py

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme, ThemeRegistry
from msl_tools.msl.ui.widgets.atoms.paths import BasePathWidget, PathMode

class InstallPathWidget(qt.QtWidgets.QWidget):
    """Composition of BasePathWidget with a checkbox that toggles between
    manual path entry and using the current package folder as the install path.

    Composed from BasePathWidget as a field, not by inheritance.

    Signals:
        path_changed(str): emitted whenever the effective install path changes.
        use_package_folder_toggled(bool): emitted when the checkbox state changes.
    """

    use_package_folder_toggled = qt.QtCore.Signal(bool)
    path_changed               = qt.QtCore.Signal(str)

    def __init__(self, *, default_path: str, package_path: str, state_checkbox: bool,
                 theme: Theme | None = None, parent=None):
        """
        Args:
            default_path: Path used when the checkbox is unchecked.
            package_path: Path used when the checkbox is checked (current
                package location).
            state_checkbox: Initial checkbox state.
            theme: Theme to color the hint label and inner BasePathWidget
                with. Defaults to ThemeRegistry.fallback() (no file I/O) so
                this widget can be used standalone without wiring up UiResources.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._default_path = default_path
        self._package_path = package_path
        self._theme         = theme or ThemeRegistry.fallback()

        self._create_widgets(state_checkbox)
        self._create_layouts()
        self._create_connections()
        self._apply_state(use_package_folder=state_checkbox)

    def _create_widgets(self,state_checkbox) -> None:
        self.path_widget = BasePathWidget(label            = "install path",
                                          placeholder_text = "Select a default install folder",
                                          initial_path     = self._default_path,
                                          dialog_title     = "Select a Folder",
                                          theme            = self._theme)
        self.use_package_checkbox = qt.QtWidgets.QCheckBox("use package folder as install path")
        self.use_package_checkbox.setChecked(state_checkbox)
        self.hint_label = qt.QtWidgets.QLabel()
        self.hint_label.setStyleSheet(self._hint_style())

    def _hint_style(self) -> str:
        return f"color: {self._theme.text_secondary}; font-size: 11px;"

    def _create_layouts(self) -> None:
        self.main_laout = qt.QtWidgets.QVBoxLayout(self)
        self.main_laout.setContentsMargins(0, 0, 0, 0)
        self.main_laout.setSpacing(0)

        self.main_laout.addWidget(self.path_widget)
        self.main_laout.addWidget(self.use_package_checkbox)
        self.main_laout.addWidget(self.hint_label)

    def _create_connections(self) -> None:
        self.use_package_checkbox.toggled.connect(self._on_checkbox_toggled)
        self.path_widget.path_changed.connect(self._on_path_widget_changed)

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self.use_package_folder_toggled.emit(checked)
        self._apply_state(use_package_folder=checked)

    def _on_path_widget_changed(self, value: str) -> None:
        if not self.use_package_checkbox.isChecked():
            self._default_path = value

        self.path_changed.emit(value)

    def _apply_state(self, use_package_folder: bool) -> None:
        if use_package_folder:
            self.path_widget.set_path(self._package_path)
            self.path_widget.set_read_only(True)
            self.hint_label.setText("      checked — current package location")
        else:
            self.path_widget.set_path(self._default_path)
            self.path_widget.set_read_only(False)
            self.hint_label.setText("      unchecked — using default install folder")

    def effective_path(self) -> str:
        """Returns the currently active install path, regardless of checkbox state."""
        return self.path_widget.path()

    def is_using_package_folder(self) -> bool:
        """Returns True if the checkbox is checked (path resolved from package location)."""
        return self.use_package_checkbox.isChecked()

    def set_theme(self, theme: Theme) -> None:
        """Re-colors the hint label and forwards the theme to the inner
        BasePathWidget. The checkbox's look comes from Qt's native style,
        not a per-widget override, so it isn't touched here."""
        self._theme = theme
        self.hint_label.setStyleSheet(self._hint_style())
        self.path_widget.set_theme(theme)


if __name__ == "__main__":


    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.widget_playground_dialog import WidgetPlaygroundDialog

    default_path = r"C:\Users\s_mironov\Documents\maya\scripts"
    package_path = r"H:\ProjectsDev\MSL_Others"

    with QtApplicationContext():

        dialog = WidgetPlaygroundDialog()
        # dialog.setStyleSheet("background-color: rgb(0, 0, 0);")
        dialog.add_case("InstallPathWidget",
                        InstallPathWidget(default_path=default_path, package_path=package_path, state_checkbox=False))
        dialog.add_case("InstallPathWidget (dark)",
                        InstallPathWidget(default_path=default_path, package_path=package_path,
                                          state_checkbox=False, theme=ThemeRegistry.fallback("dark")))
        dialog.show()