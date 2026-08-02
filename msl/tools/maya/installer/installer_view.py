"""
View тула установки. Чистый UI без бизнес-логики.
"""

from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.compositions.install_path_widget import InstallPathWidget
from msl_tools.msl.ui.widgets.atoms.status import VersionStatusWidget

import msl_tools.msl.ui.qt_bindings as qt


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

        self.version_info  = self.CORE.versionManager.check_install_status(self.path_maya)
        self.version_setup = self.CORE.versionManager.core_raw_version

        self.setWindowTitle(self.NAME)
        self.setWindowIcon(self.WINDOW_ICON)

        self.create_widgets()
        self.create_layouts()
        self.create_connections()

    def create_widgets(self):
        self.btn_install   = qt.QtWidgets.QPushButton("install")
        self.btn_uninstall = qt.QtWidgets.QPushButton("uninstall")
        self.btn_run = qt.QtWidgets.QPushButton("run")

        self.InstallPathWidget = InstallPathWidget(default_path=self.path_maya, package_path=self.path_current)
        self.VersionStatusWidget = VersionStatusWidget(package_version=self.version_setup)


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
        print(self.version_info)
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


