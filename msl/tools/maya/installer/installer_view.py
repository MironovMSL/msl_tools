"""
View тула установки. Чистый UI без бизнес-логики.
"""
from PySide6 import QtWidgets

from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.windows.maya_window_meta import MayaWindowMeta

import msl_tools.msl.ui.qt_bindings as qt

# ui/widgets/version_status_widget.py

from msl_tools.msl.core.version.manager import UpdateInfo, UpdateStatus


class VersionStatusWidget(qt.QtWidgets.QWidget):
    """Нижняя строка инсталлятора: версия пакета, установленная версия, статус.

    Не содержит логики сравнения версий — только отображение готового UpdateInfo.
    Обновляется через set_update_info(), вызываемый контроллером после
    VersionManager.check_install_status().
    """

    _STATUS_TEXT = {
        UpdateStatus.UP_TO_DATE: "up to date",
        UpdateStatus.UPDATE_AVAILABLE: "update available",
        UpdateStatus.NOT_INSTALLED: "not installed",
        UpdateStatus.UNKNOWN: "unknown",
    }

    _STATUS_COLOR = {
        UpdateStatus.UP_TO_DATE: "green",
        UpdateStatus.UPDATE_AVAILABLE: "orange",
        UpdateStatus.NOT_INSTALLED: "gray",
        UpdateStatus.UNKNOWN: "red",
    }

    def __init__(self, *, package_version: str, parent=None):
        super().__init__(parent)

        self._package_version = package_version

        self._build_ui()
        self.set_update_info(None)

    def _build_ui(self) -> None:
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        self.version_label = qt.QtWidgets.QLabel(f"version: {self._package_version}")
        self.installed_label = qt.QtWidgets.QLabel("installed version: —")
        self.status_label = qt.QtWidgets.QLabel("status: —")

        for label in (self.version_label, self.installed_label, self.status_label):
            label.setStyleSheet("color: gray; font-size: 12px;")

        layout.addWidget(self.version_label)
        layout.addStretch()
        layout.addWidget(self.installed_label)
        layout.addStretch()
        layout.addWidget(self.status_label)

    def set_update_info(self, info: UpdateInfo | None) -> None:
        """Обновляет отображение на основе UpdateInfo. None — состояние ещё не проверялось."""

        if info is None:
            self.installed_label.setText("installed version: —")
            self.status_label.setText("status: —")
            self.status_label.setStyleSheet("color: gray; font-size: 12px;")
            return

        if info.status is UpdateStatus.NOT_INSTALLED:
            self.installed_label.setText("installed version: —")
        else:
            self.installed_label.setText(f"installed version: {info.current_version}")

        status_text = self._STATUS_TEXT.get(info.status, "unknown")
        status_color = self._STATUS_COLOR.get(info.status, "red")

        self.status_label.setText(f"status: {status_text}")
        self.status_label.setStyleSheet(f"color: {status_color}; font-size: 12px;")

# ui/widgets/install_path_widget.py
class InstallPathWidget(qt.QtWidgets.QWidget):
    """Виджет выбора install path с переключением между ручным вводом
    и путём текущей папки пакета.

    Сигналы:
        path_changed(str): эмитится при любом изменении effective install path
        use_package_folder_toggled(bool): эмитится при переключении чекбокса
    """

    path_changed = qt.QtCore.Signal(str)
    use_package_folder_toggled = qt.QtCore.Signal(bool)

    def __init__(self, *, maya_path: str, package_path: str, parent=None):
        super().__init__(parent)

        self._maya_path = maya_path
        self._package_path = package_path

        self._build_ui()
        self._connect_signals()
        self._update_state(use_package_folder=False)

    def _build_ui(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = qt.QtWidgets.QLabel("install path")
        label.setStyleSheet("color: gray;")

        path_row = qt.QtWidgets.QHBoxLayout()
        self.path_field = qt.QtWidgets.QLineEdit(self._maya_path)
        self.browse_button = qt.QtWidgets.QPushButton("...")
        self.browse_button.setFixedWidth(36)
        path_row.addWidget(self.path_field)
        path_row.addWidget(self.browse_button)

        self.use_package_checkbox = qt.QtWidgets.QCheckBox("use package folder as install path")

        self.hint_label = qt.QtWidgets.QLabel()
        self.hint_label.setStyleSheet("color: gray; font-size: 11px;")

        layout.addWidget(label)
        layout.addLayout(path_row)
        layout.addWidget(self.use_package_checkbox)
        layout.addWidget(self.hint_label)

    def _connect_signals(self) -> None:
        self.use_package_checkbox.toggled.connect(self._on_checkbox_toggled)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        self.path_field.editingFinished.connect(self._on_path_edited)

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self._update_state(use_package_folder=checked)
        self.use_package_folder_toggled.emit(checked)

    def _update_state(self, *, use_package_folder: bool) -> None:
        if use_package_folder:
            self.path_field.setText(self._package_path)
            self.path_field.setReadOnly(True)
            self.browse_button.setEnabled(False)
            self.hint_label.setText("   checked — path resolved from current package location")
        else:
            self.path_field.setText(self._maya_path)
            self.path_field.setReadOnly(False)
            self.browse_button.setEnabled(True)
            self.hint_label.setText("   unchecked — using default Maya scripts folder")

        self.path_changed.emit(self.path_field.text())

    def _on_browse_clicked(self) -> None:
        selected_dir = qt.QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select install path", self.path_field.text()
        )
        if selected_dir:
            self._maya_path = selected_dir
            self.path_field.setText(selected_dir)
            self.path_changed.emit(selected_dir)

    def _on_path_edited(self) -> None:
        if not self.use_package_checkbox.isChecked():
            self._maya_path = self.path_field.text()
            self.path_changed.emit(self._maya_path)

    def effective_path(self) -> str:
        return self.path_field.text()

    def is_using_package_folder(self) -> bool:
        return self.use_package_checkbox.isChecked()

class InstallerView(qt.QtWidgets.QDialog): # "singleton" "unique" "multi"

    NAME   = 'Installer'

    CORE        = Resources()

    CONFIG      = CORE.configManager.get_config(NAME, ".ini")
    LOG         = CORE.logManager.get(NAME)

    UI_CORE     = UiResources()
    WINDOW_ICON = UI_CORE.iconManager.get_icon(NAME)

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.path_maya = r"C:\Users\s_mironov\Documents\maya\scripts"
        self.path_current = r"H:\ProjectsDev\MSL_Others"

        self.version_info = self.CORE.versionManager.check_install_status(self.path_maya)
        print(self.version_info)
        # self.version_setup = self.CORE.versionManager.local_reader.get_version(self.CORE.versionManager.core_module_path)
        self.version_setup = "0.0.2"

        self.setWindowTitle(self.NAME)
        self.setWindowIcon(self.WINDOW_ICON)

        self.create_widgets()
        self.create_layouts()
        self.create_connections()

    def create_widgets(self):
        self.btn_install   = qt.QtWidgets.QPushButton("install")
        self.btn_uninstall = qt.QtWidgets.QPushButton("uninstall")
        self.btn_run = qt.QtWidgets.QPushButton("run")

        self.InstallPathWidget = InstallPathWidget(maya_path=self.path_maya, package_path=self.path_current)
        self.VersionStatusWidget = VersionStatusWidget(package_version=self.version_setup)


        self.label_version = qt.QtWidgets.QLabel(f"Version:{self.version_setup}")
        self.label_latest_version = qt.QtWidgets.QLabel(f"latest Version: ???")
        # self.label_status = qt.QtWidgets.QLabel("<status_placeholder>")
        self.label_status = qt.QtWidgets.QLabel("<status_placeholder>")

        # self.update_version = qt.QtWidgets.QLabel(f"{self.version_info}")

        # Text-field path
        self.label_installation_path = qt.QtWidgets.QLabel("Installation Path:")
        self.line_edit_installation_path = qt.QtWidgets.QLineEdit()
        self.line_edit_installation_path.setPlaceholderText("<installation_target_path_placeholder>")
        self.line_edit_installation_path.setReadOnly(True)



    def create_layouts(self):


        bt_layout = qt.QtWidgets.QHBoxLayout()

        bt_layout.addWidget(self.btn_install)
        bt_layout.addWidget(self.btn_uninstall)
        bt_layout.addWidget(self.btn_run)

        # Install Path
        target_path_layout = qt.QtWidgets.QHBoxLayout()
        target_path_layout.addWidget(self.InstallPathWidget)

        vr_layout = qt.QtWidgets.QHBoxLayout()
        # vr_layout.addWidget(self.label_version)
        # vr_layout.addWidget(self.label_latest_version)
        # vr_layout.addWidget(self.label_status)
        vr_layout.addWidget(self.VersionStatusWidget)

        # update_layout = qt.QtWidgets.QHBoxLayout()
        # update_layout.addWidget(self.update_version)

        main_layout = qt.QtWidgets.QVBoxLayout(self)
        main_layout.setAlignment(qt.QtCore.Qt.AlignTop)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        main_layout.addLayout(bt_layout)
        main_layout.addLayout(target_path_layout)
        main_layout.addLayout(vr_layout)
        # main_layout.addLayout(update_layout)


    def create_connections(self):
        self.btn_install.clicked.connect(self.on_click_install)
        self.btn_uninstall.clicked.connect(self.on_click_uninstall)

        self.InstallPathWidget.path_changed.connect(self._on_path_edited)

    def _on_path_edited(self, path: str) -> None:
        print(path)
        self.path_maya = path
        self.version_info = self.CORE.versionManager.check_install_status(self.path_maya)
        # self.VersionStatusWidget.set_update_info(UpdateInfo(status=UpdateStatus.UP_TO_DATE, current_version="unknown"))
        self.VersionStatusWidget.set_update_info(self.version_info)

        # UpdateStatus.UP_TO_DATE: "up to date",
        # UpdateStatus.UPDATE_AVAILABLE: "update available",
        # UpdateStatus.NOT_INSTALLED: "not installed",
        # UpdateStatus.UNKNOWN: "unknown",

    def on_click_install(self):
        self.LOG.info("click install")
        print("click")

    def on_click_uninstall(self):
        self.LOG.info("click uninstall")
        print("click")







if __name__ == '__main__':

    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


    with QtApplicationContext() as content:
        # InstallerView.show_window(parent=content.get_parent())
        # MayaWindowQuery.close_ui_elements([window])
        window = InstallerView(parent=content.get_parent())
        window.show()


