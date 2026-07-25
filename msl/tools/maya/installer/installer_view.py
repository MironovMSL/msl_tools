"""
View тула установки. Чистый UI без бизнес-логики.
"""
from PySide6 import QtWidgets

from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.windows.maya_window_meta import MayaWindowMeta

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

        self.version_info = self.CORE.versionManager.check_for_update()
        self.setWindowTitle(self.NAME)
        self.setWindowIcon(self.WINDOW_ICON)

        self.create_widgets()
        self.create_layouts()
        self.create_connections()

    def create_widgets(self):
        self.btn_install   = qt.QtWidgets.QPushButton("install")
        self.btn_uninstall = qt.QtWidgets.QPushButton("uninstall")
        self.btn_run = qt.QtWidgets.QPushButton("run")


        self.label_version = qt.QtWidgets.QLabel(f"Version:{self.version_info.current_version}")
        self.label_latest_version = qt.QtWidgets.QLabel(f"latest Version:{self.version_info.latest_version}")
        # self.label_status = qt.QtWidgets.QLabel("<status_placeholder>")
        self.label_status = qt.QtWidgets.QLabel("<status_placeholder>")

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
        target_path_layout.addWidget(self.label_installation_path)
        target_path_layout.addWidget(self.line_edit_installation_path)

        vr_layout = qt.QtWidgets.QHBoxLayout()
        vr_layout.addWidget(self.label_version)
        vr_layout.addWidget(self.label_latest_version)
        vr_layout.addWidget(self.label_status)

        main_layout = qt.QtWidgets.QVBoxLayout(self)
        main_layout.setAlignment(qt.QtCore.Qt.AlignTop)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        main_layout.addLayout(bt_layout)
        main_layout.addLayout(target_path_layout)
        main_layout.addLayout(vr_layout)

    def create_connections(self):
        self.btn_install.clicked.connect(self.click_install)
        self.btn_uninstall.clicked.connect(self.click_uninstall)

    def click_install(self):
        self.LOG.info("click install")
        print("click")

    def click_uninstall(self):
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


