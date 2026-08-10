"""
View тула установки. Чистый UI без бизнес-логики.
"""
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.compositions.install_path_widget import InstallPathWidget
from msl_tools.msl.ui.widgets.atoms.status import VersionStatusWidget
from msl_tools.msl.ui.widgets.atoms.progress import BaseProgressBar, ProgressState


from pathlib import Path


import msl_tools.msl.ui.qt_bindings as qt


default_config = {
    "startup": {
        "name"  : 'Installer',
        "version": None,
        "width" : 400,
        "height": 150,
        "default_install_path": None,
        "package_install_path": None,
        "use_package_state": False,
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
        self.use_package_state     =  self.CONFIG["startup"]["use_package_state"]

        self.width_window         = self.CONFIG["startup"]["width"]
        self.height_window        = self.CONFIG["startup"]["height"]

        self.setWindowTitle((self.CONFIG["startup"]["name"] or self.NAME))
        self.setWindowIcon(self.WINDOW_ICON)

        self.resize(self.width_window, self.height_window)

        if self.use_package_state:
            self.install_info  = self.CORE.versionManager.check_install_status(self.package_install_path)
        else:
            self.install_info  = self.CORE.versionManager.check_install_status(self.default_install_path)

        self.create_widgets()
        self.create_layouts()
        self.create_connections()

    def create_widgets(self):
        self.btn_install   = qt.QtWidgets.QPushButton("install")
        self.btn_uninstall = qt.QtWidgets.QPushButton("uninstall")

        self.InstallPathWidget = InstallPathWidget(default_path=self.default_install_path,
                                                   package_path=self.package_install_path,
                                                   state_checkbox=self.use_package_state)

        self.VersionStatusWidget = VersionStatusWidget(package_version=self.msl_tool_version,
                                                       info=self.install_info)

        self.BaseProgressBar = BaseProgressBar()

    def create_layouts(self):

        button_layout = qt.QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.btn_install)
        button_layout.addWidget(self.btn_uninstall)

        InstallPathWidget_layout = qt.QtWidgets.QHBoxLayout()
        InstallPathWidget_layout.addWidget(self.InstallPathWidget)

        VersionStatusWidget_layout = qt.QtWidgets.QHBoxLayout()
        VersionStatusWidget_layout.addWidget(self.VersionStatusWidget)

        BaseProgressBar_layout = qt.QtWidgets.QHBoxLayout()
        BaseProgressBar_layout.addWidget(self.BaseProgressBar)

        main_layout = qt.QtWidgets.QVBoxLayout(self)
        main_layout.setAlignment(qt.QtCore.Qt.AlignTop)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        main_layout.addLayout(button_layout)
        main_layout.addLayout(InstallPathWidget_layout)
        main_layout.addLayout(VersionStatusWidget_layout)
        main_layout.addLayout(BaseProgressBar_layout)

    def create_connections(self):
        self.btn_install.clicked.connect(self.on_click_install)
        self.btn_uninstall.clicked.connect(self.on_click_uninstall)

        self.InstallPathWidget.use_package_folder_toggled.connect(self.set_use_package_state)
        self.InstallPathWidget.path_changed.connect(self.on_path_edited)

    def set_use_package_state(self, checked: bool):
        self.use_package_state = checked

    def on_path_edited(self, path: str) -> None:
        p = str(Path(path))
        if not self.use_package_state:
            self.default_install_path = p

        self.install_info = self.CORE.versionManager.check_install_status(p)
        self.VersionStatusWidget.set_update_info(self.install_info)

    def on_click_install(self):
        self.BaseProgressBar.set_state(ProgressState.NORMAL)
        self.BaseProgressBar.set_progress(20)
        check_path = None

        if not self.use_package_state:
            self.CORE.packageInstaller.install_package(self.package_install_path, self.default_install_path)
            check_path = self.default_install_path
        else:
            check_path = self.package_install_path


        import time

        for i in range(21, 101):

            self.BaseProgressBar.set_progress(i)
            time.sleep(0.005)
        else:
            self.BaseProgressBar.set_state(ProgressState.SUCCESS)

        self.install_info = self.CORE.versionManager.check_install_status(check_path)
        self.VersionStatusWidget.set_update_info(self.install_info)


        self.CONFIG["startup"]["default_install_path"] = self.default_install_path
        self.CONFIG["startup"]["package_install_path"] = self.package_install_path
        self.CONFIG["startup"]["use_package_state"]    = self.use_package_state
        self.CONFIG["startup"]["version"]              = self.installer_version



    def on_click_uninstall(self):
        check_path = None
        self.BaseProgressBar.set_state(ProgressState.NORMAL)
        self.BaseProgressBar.set_progress(20)

        if not self.use_package_state:
            self.CORE.packageInstaller.uninstall_package(self.default_install_path)
            check_path = self.default_install_path

        else:
            check_path = self.package_install_path

        import time

        for i in range(21, 101):

            self.BaseProgressBar.set_progress(i)
            time.sleep(0.005)
        else:
            self.BaseProgressBar.set_state(ProgressState.SUCCESS)

        self.install_info = self.CORE.versionManager.check_install_status(check_path)
        self.VersionStatusWidget.set_update_info(self.install_info)







if __name__ == '__main__':

    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


    with QtApplicationContext() as content:
        # InstallerView.show_window(parent=content.get_parent())
        # MayaWindowQuery.close_ui_elements([window])
        window = InstallerView("0.0.1",parent=content.get_parent())
        window.show()


