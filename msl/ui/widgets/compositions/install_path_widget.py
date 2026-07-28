# ui/widgets/compositions/install_path_widget.py

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.paths import BasePathWidget, PathMode


class InstallPathWidget(qt.QtWidgets.QWidget):
    """Composition of BasePathWidget with a checkbox that toggles between
    manual path entry and using the current package folder as the install path.

    Composed from BasePathWidget as a field, not by inheritance.

    Signals:
        path_changed(str): emitted whenever the effective install path changes.
        use_package_folder_toggled(bool): emitted when the checkbox state changes.
    """

    path_changed = qt.QtCore.Signal(str)
    use_package_folder_toggled = qt.QtCore.Signal(bool)

    def __init__(self, *, default_path: str, package_path: str, parent=None):
        super().__init__(parent)

        self._default_path = default_path
        self._package_path = package_path

        self._build_ui()
        self._connect_signals()
        self._apply_state(use_package_folder=False)

    def _build_ui(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.path_widget = BasePathWidget(
            label="install path",
            initial_path=self._default_path,
            mode=PathMode.DIRECTORY,
        )

        self.use_package_checkbox = qt.QtWidgets.QCheckBox("use package folder as install path")

        self.hint_label = qt.QtWidgets.QLabel()
        self.hint_label.setStyleSheet("color: gray; font-size: 11px;")

        layout.addWidget(self.path_widget)
        layout.addWidget(self.use_package_checkbox)
        layout.addWidget(self.hint_label)

    def _connect_signals(self) -> None:
        self.use_package_checkbox.toggled.connect(self._on_checkbox_toggled)
        self.path_widget.path_changed.connect(self._on_path_widget_changed)

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self._apply_state(use_package_folder=checked)
        self.use_package_folder_toggled.emit(checked)

    def _on_path_widget_changed(self, value: str) -> None:
        if not self.use_package_checkbox.isChecked():
            self._default_path = value
            self.path_changed.emit(value)

    def _apply_state(self, *, use_package_folder: bool) -> None:
        if use_package_folder:
            self.path_widget.set_path(self._package_path)
            self.path_widget.set_read_only(True)
            self.hint_label.setText("checked — path resolved from current package location")
        else:
            self.path_widget.set_path(self._default_path)
            self.path_widget.set_read_only(False)
            self.hint_label.setText("unchecked — using default install folder")

        self.path_changed.emit(self.path_widget.path())

    def effective_path(self) -> str:
        """Returns the currently active install path, regardless of checkbox state."""
        return self.path_widget.path()

    def is_using_package_folder(self) -> bool:
        """Returns True if the checkbox is checked (path resolved from package location)."""
        return self.use_package_checkbox.isChecked()