"""
View тула установки. Чистый UI без бизнес-логики.
"""
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.compositions.install_path_widget import InstallPathWidget
from msl_tools.msl.ui.widgets.atoms.status import VersionStatusWidget

import msl_tools.msl.ui.qt_bindings as qt

default_config = {
    "startup": {
        "name"  : None,
        "version": None,
        "width" : 400,
        "height": 150,
        "default_install_path": None,
        "package_install_path": None,
        "use_package_path": False,
    }
}

class InstallerView(qt.QtWidgets.QDialog):

    NAME        = 'Installer'
    CORE        = Resources()
    UI_CORE     = UiResources()

    CONFIG      = CORE.configManager.get_config(NAME, defaults=default_config)
    LOG         = CORE.logManager.get(NAME)
    WINDOW_ICON = UI_CORE.iconManager.get_icon(NAME)

    def __init__(self, version: str, parent=None):
        super().__init__(parent=parent)

        self.installer_version    =  version
        self.msl_tool_version     =  self.CORE.versionManager.core_raw_version

        pref_maya_path            =  self.CORE.fsManager.mayaPaths.get_preferences_root() / "scripts"
        root_package_path         =  self.CORE.fsManager.PARENT_DIR
        self.default_install_path = str((self.CONFIG["startup"]["default_install_path"] or pref_maya_path))
        self.package_install_path = str((self.CONFIG["startup"]["package_install_path"] or root_package_path))
        self.use_package_path     =  self.CONFIG["startup"]["use_package_path"]

        self.width_window         = self.CONFIG["startup"]["width"]
        self.height_window        = self.CONFIG["startup"]["height"]

        self.setWindowTitle(self.NAME)
        self.setWindowIcon(self.WINDOW_ICON)

        self.resize(self.width_window, self.height_window)

        if self.use_package_path:
            self.install_info  = self.CORE.versionManager.check_install_status(self.package_install_path)
        else:
            self.install_info  = self.CORE.versionManager.check_install_status(self.default_install_path)

        self.create_widgets()
        self.create_layouts()
        self.create_connections()

    def create_widgets(self):
        self.btn_install   = qt.QtWidgets.QPushButton("install")
        self.btn_uninstall = qt.QtWidgets.QPushButton("uninstall")
        self.btn_run = qt.QtWidgets.QPushButton("run")

        self.InstallPathWidget = InstallPathWidget(default_path=self.default_install_path,
                                                   package_path=self.package_install_path,
                                                   state_checkbox=self.use_package_path)

        self.VersionStatusWidget = VersionStatusWidget(package_version=self.msl_tool_version,
                                                       info=self.install_info)



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
        vr_layout.addWidget(self.VersionStatusWidget)


        main_layout = qt.QtWidgets.QVBoxLayout(self)
        main_layout.setAlignment(qt.QtCore.Qt.AlignTop)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        main_layout.addLayout(bt_layout)
        main_layout.addLayout(target_path_layout)
        main_layout.addLayout(vr_layout)


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
        window = InstallerView("0.0.1",parent=content.get_parent())
        window.show()


