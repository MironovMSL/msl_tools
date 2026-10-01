# ui/widgets/atoms/paths/base_path_widget.py

from enum import Enum, auto
import msl_tools.msl.ui.qt_bindings as qt
from pathlib import Path

from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton

class PathMode(Enum):
    """Determines which dialog type the browse button opens."""
    DIRECTORY = auto()
    FILE_OPEN = auto()
    FILE_SAVE = auto()


class BasePathWidget(qt.QtWidgets.QWidget):
    """Reusable path-selection widget: optional label + line edit + browse button.

    Styled by the window stylesheet: the label is QLabel#pathLabel
    (ui/theme/widgets.qss), the field uses the base.qss baseline, the browse
    button is an IconPushButton (`actions/browse`, tinted by QSS; "..." if
    the asset is missing) as high as the field.

    Signals:
        path_changed(str): emitted when the path changes (manual edit finished
            or a new path selected via dialog).
    """

    path_changed = qt.QtCore.Signal(str)

    BROWSE_BUTTON_SIZE = qt.QtCore.QSize(26, 22)  # 22 = the field's height (base.qss)

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
        """
        Args:
            label: Optional label text shown above the path field.
            initial_path: Path pre-filled in the field.
            placeholder_text: Placeholder shown when the field is empty.
            mode: Which QFileDialog variant the browse button opens.
            file_filter: File filter passed to the dialog (FILE_OPEN/FILE_SAVE only).
            dialog_title: Title of the browse dialog.
            read_only: Whether the field starts read-only.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._mode         = mode
        self._file_filter  = file_filter
        self._dialog_title = dialog_title

        self._create_widgets(initial_path, placeholder_text, read_only)
        self._create_layouts(label)
        self._create_connections()

    def _create_widgets(self, initial_path: str, placeholder_text: str, read_only: bool) -> None:
        self.path_field = qt.QtWidgets.QLineEdit(initial_path)
        self.path_field.setPlaceholderText(placeholder_text)
        self.path_field.setReadOnly(read_only)

        browsing_files = self._mode is not PathMode.DIRECTORY
        self.browse_button = IconPushButton(
            UiResources().iconManager.get_icon("browse", sub_folder="actions"),
            "Browse for a file" if browsing_files else "Browse for a folder", fallback_text="...")
        self.browse_button.setFixedSize(self.BROWSE_BUTTON_SIZE)
        self.browse_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def _create_layouts(self, label: str | None) -> None:
        self.main_layout = qt.QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.path_layout = qt.QtWidgets.QHBoxLayout()
        self.path_layout.setSpacing(4)
        self.path_layout.setContentsMargins(0, 0, 0, 0)

        self.path_layout.addWidget(self.path_field)
        self.path_layout.addWidget(self.browse_button)

        self.label_widget: qt.QtWidgets.QLabel | None = None
        if label:
            self._create_label(label)
        self.main_layout.addLayout(self.path_layout)

    def _create_connections(self) -> None:
        self.browse_button.clicked.connect(self._on_browse_clicked)
        self.path_field.editingFinished.connect(lambda: self.path_changed.emit(self.path_field.text()))

    def _create_label(self,label: str | None) -> None:
        self.label_widget = qt.QtWidgets.QLabel(label)
        self.label_widget.setObjectName("pathLabel")

        self.main_layout.addWidget(self.label_widget)

    def _on_browse_clicked(self) -> None:
        current = self.path_field.text()

        if self._mode is PathMode.DIRECTORY:
            selected = qt.QtWidgets.QFileDialog.getExistingDirectory(self, self._dialog_title, current)
        elif self._mode is PathMode.FILE_OPEN:
            selected, _ = qt.QtWidgets.QFileDialog.getOpenFileName(self, self._dialog_title, current, self._file_filter)
        else:
            selected, _ = qt.QtWidgets.QFileDialog.getSaveFileName(self, self._dialog_title, current, self._file_filter)

        if selected:
            self.set_path(str(Path(selected)))

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
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        dialog.add_case("directory picker DIRECTORY",
                        BasePathWidget(label="install path", placeholder_text=r"C:\\...\\maya\\scripts"))
        dialog.add_case("file picker with filter FILE_OPEN",
                        BasePathWidget(label= "FILE_OPEN", placeholder_text="path to config.json",mode=PathMode.FILE_OPEN, file_filter="JSON (*.json)"))
        dialog.add_case("file picker FILE SAVE",
                        BasePathWidget(placeholder_text="path to config.json",mode=PathMode.FILE_SAVE))
        dialog.add_case("read-only path DIRECTORY",
                        BasePathWidget(initial_path=r"H:\\ProjectsDev\\MSL_Others", read_only=True))
        dialog.show()