# ui/widgets/atoms/paths/base_path_widget.py

from enum import Enum, auto
import msl_tools.msl.ui.qt_bindings as qt


class PathMode(Enum):
    """Determines which dialog type the browse button opens."""
    DIRECTORY = auto()
    FILE_OPEN = auto()
    FILE_SAVE = auto()


class BasePathWidget(qt.QtWidgets.QWidget):
    """Reusable path-selection widget: optional label + line edit + browse button.
    Signals:
        path_changed(str): emitted when the path changes (manual edit finished
            or a new path selected via dialog).
    """

    path_changed = qt.QtCore.Signal(str)

    def __init__(self,
                 label:            str | None = None,
                 initial_path:     str        = "",
                 placeholder_text: str        = "",
                 mode:             PathMode   = PathMode.DIRECTORY,
                 file_filter:      str        = "All Files (*)",
                 dialog_title:     str        = "Select path",
                 read_only:        bool       = False,
                 parent                       = None
                 ):

        super().__init__(parent)

        self._mode = mode
        self._file_filter = file_filter
        self._dialog_title = dialog_title

        self._build_ui(label, initial_path, placeholder_text, read_only)
        self._connect_signals()

    def _build_ui(self, label: str | None, initial_path: str, placeholder_text: str, read_only: bool) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if label:
            label_widget = qt.QtWidgets.QLabel(label)
            label_widget.setStyleSheet("color: gray;")
            layout.addWidget(label_widget)

        row = qt.QtWidgets.QHBoxLayout()
        self.path_field = qt.QtWidgets.QLineEdit(initial_path)
        self.path_field.setPlaceholderText(placeholder_text)
        self.path_field.setReadOnly(read_only)

        self.browse_button = qt.QtWidgets.QPushButton("...")
        self.browse_button.setFixedWidth(36)

        row.addWidget(self.path_field)
        row.addWidget(self.browse_button)
        layout.addLayout(row)

    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self._on_browse_clicked)
        self.path_field.editingFinished.connect(
            lambda: self.path_changed.emit(self.path_field.text())
        )

    def _on_browse_clicked(self) -> None:
        current = self.path_field.text()

        if self._mode is PathMode.DIRECTORY:
            selected = qt.QtWidgets.QFileDialog.getExistingDirectory(self, self._dialog_title, current)
        elif self._mode is PathMode.FILE_OPEN:
            selected, _ = qt.QtWidgets.QFileDialog.getOpenFileName(self, self._dialog_title, current, self._file_filter)
        else:
            selected, _ = qt.QtWidgets.QFileDialog.getSaveFileName(self, self._dialog_title, current, self._file_filter)

        if selected:
            self.set_path(selected)

    def path(self) -> str:
        """Returns the current path as entered or selected."""
        return self.path_field.text()

    def set_path(self, value: str) -> None:
        """Programmatically sets the path and emits path_changed."""
        self.path_field.setText(value)
        self.path_changed.emit(value)

    def set_read_only(self, read_only: bool) -> None:
        """Toggles read-only state on the field and browse button, without recreating the widget."""
        self.path_field.setReadOnly(read_only)
        self.browse_button.setEnabled(not read_only)


if __name__ == "__main__":


    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.widget_playground_dialog import WidgetPlaygroundDialog

    with QtApplicationContext():

        dialog = WidgetPlaygroundDialog()
        dialog.add_case("directory picker",
                        BasePathWidget(label="install path", placeholder_text=r"C:\\...\\maya\\scripts"))
        dialog.add_case("file picker with filter",
                        BasePathWidget(placeholder_text="path to config.json",mode=PathMode.FILE_OPEN, file_filter="JSON (*.json)"))
        dialog.add_case("file save with filter",
                        BasePathWidget(placeholder_text="path to config.json",mode=PathMode.FILE_SAVE))
        dialog.add_case("read-only path",
                        BasePathWidget(initial_path=r"H:\\ProjectsDev\\MSL_Others", read_only=True))

        dialog.show()
