"""
View installation tool. Clean UI without business logic.
"""
from pathlib import Path

from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.widgets.compositions.install_path_widget import InstallPathWidget
from msl_tools.msl.ui.widgets.atoms.status import VersionStatusWidget
from msl_tools.msl.ui.widgets.atoms.progress import BaseProgressBar, ProgressState
from msl_tools.msl.ui.workers import CallableWorker

import msl_tools.msl.ui.qt_bindings as qt


default_config = {
    "startup": {
        "name": 'Installer',
        "version": None,
        "width": 400,
        "height": 150,
        "default_install_path": None,
        "package_install_path": None,
        "use_package_state": False,
    }
}


class InstallerView(FramelessDialog):
    """Installer window: lets the user pick an install path and install /
    uninstall the package. Contains no business logic itself — every action
    delegates to Resources().packageInstaller / versionManager and this view
    only wires widgets to those calls and reflects the results.
    """

    NAME = 'Installer'

    def __init__(self, version: str, parent=None):
        self.CORE    = Resources()
        self.UI_CORE = UiResources()
        self.CONFIG  = self.CORE.configsMayaMng.get_config(self.NAME, defaults=default_config)
        self.LOG     = self.CORE.logsMaya.get(self.NAME)

        self.installer_version = version
        self.msl_tool_version  = self.CORE.versionManager.core_raw_version

        pref_maya_path    = self.CORE.fsManager.mayaPaths.get_preferences_root() / "scripts"
        root_package_path = self.CORE.fsManager.PARENT_DIR
        self.default_install_path = str(self.CONFIG["startup"]["default_install_path"] or pref_maya_path)
        self.package_install_path = str(self.CONFIG["startup"]["package_install_path"] or root_package_path)
        self.use_package_state    =     self.CONFIG["startup"]["use_package_state"]

        window_title = self.CONFIG["startup"]["name"] or self.NAME
        window_icon  = self.UI_CORE.iconManager.get_icon(self.NAME)

        super().__init__(
            title    = window_title,
            width    = self.CONFIG["startup"]["width"],
            height   = self.CONFIG["startup"]["height"],
            icon     = window_icon,
            resources= self.UI_CORE,
            show_minimize_button = False,
            show_maximize_button = False,
            show_close_button    = True,
            show_theme_toggle    = True,
            parent   = parent,
        )

        self._worker: CallableWorker | None = None

        self.install_info = self.CORE.versionManager.check_install_status(
            self.package_install_path if self.use_package_state else self.default_install_path)

        self.create_widgets()
        self.create_layouts()
        self.create_connections()
        self._apply_installer_theme(self.UI_CORE.themeManager.current_theme)

    def create_widgets(self):
        self.btn_install   = qt.QtWidgets.QPushButton("install")
        self.btn_uninstall = qt.QtWidgets.QPushButton("uninstall")

        current_theme = self.UI_CORE.themeManager.current_theme

        self.InstallPathWidget = InstallPathWidget(default_path=self.default_install_path,
                                                   package_path=self.package_install_path,
                                                   state_checkbox=self.use_package_state,
                                                   theme=current_theme)

        self.VersionStatusWidget = VersionStatusWidget(package_version=self.msl_tool_version,
                                                       info=self.install_info,
                                                       theme=current_theme)

        self.BaseProgressBar = BaseProgressBar(theme=current_theme)

    def create_layouts(self):
        button_layout = qt.QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.btn_install)
        button_layout.addWidget(self.btn_uninstall)

        install_path_layout = qt.QtWidgets.QHBoxLayout()
        install_path_layout.addWidget(self.InstallPathWidget)

        version_status_layout = qt.QtWidgets.QHBoxLayout()
        version_status_layout.addWidget(self.VersionStatusWidget)

        progress_layout = qt.QtWidgets.QHBoxLayout()
        progress_layout.addWidget(self.BaseProgressBar)

        # Content now lives inside FramelessDialog's rounded content
        # surface instead of directly on `self`.
        content_layout = self.content_surface.content_layout()
        content_layout.setAlignment(qt.QtCore.Qt.AlignTop)
        content_layout.setSpacing(5)

        content_layout.addLayout(button_layout)
        content_layout.addLayout(install_path_layout)
        content_layout.addLayout(version_status_layout)
        content_layout.addLayout(progress_layout)

    def create_connections(self):
        self.btn_install.clicked.connect(self.on_click_install)
        self.btn_uninstall.clicked.connect(self.on_click_uninstall)

        self.InstallPathWidget.use_package_folder_toggled.connect(self.set_use_package_state)
        self.InstallPathWidget.path_changed.connect(self.on_path_edited)

        # Deliberately NOT named _on_theme_changed — that name is owned by
        # FramelessDialog and connecting to it here would shadow the base
        # class's chrome theming (see class docstring notes above).
        self.UI_CORE.themeManager.theme_changed.connect(self._apply_installer_theme)

    def _apply_installer_theme(self, theme) -> None:
        """Forwards a theme switch to every themed child widget owned by
        this view. FramelessDialog's own theme_changed handler (chrome,
        buttons, snap flyout) runs independently via its own connection."""
        self.InstallPathWidget.set_theme(theme)
        self.VersionStatusWidget.set_theme(theme)
        self.BaseProgressBar.set_theme(theme)

    def set_use_package_state(self, checked: bool):
        self.use_package_state = checked

    def on_path_edited(self, path: str) -> None:
        p = str(Path(path))
        if not self.use_package_state:
            self.default_install_path = p

        self.install_info = self.CORE.versionManager.check_install_status(p)
        self.VersionStatusWidget.set_update_info(self.install_info)

    def on_click_install(self):
        if self.use_package_state:
            self._refresh_status(self.package_install_path)
            return

        target_path = self.default_install_path
        self._run_busy(
            target=lambda: self.CORE.packageInstaller.install_package(self.package_install_path, target_path),
            checked_path=target_path)

    def on_click_uninstall(self):
        if self.use_package_state:
            self._refresh_status(self.package_install_path)
            return

        target_path = self.default_install_path
        self._run_busy(
            target=lambda: self.CORE.packageInstaller.uninstall_package(target_path),
            checked_path=target_path)

    def _run_busy(self, target, checked_path: str) -> None:
        self.btn_install.setEnabled(False)
        self.btn_uninstall.setEnabled(False)

        self.BaseProgressBar.set_state(ProgressState.NORMAL)
        self.BaseProgressBar.set_indeterminate(True)

        self._last_error = None
        self._worker = CallableWorker(target, parent=self)
        self._worker.failed.connect(self._store_worker_error)
        self._worker.finished_with_result.connect(
            lambda success: self._on_operation_finished(success, checked_path)
        )
        self._worker.start()

    def _store_worker_error(self, error: Exception | None) -> None:
        self._last_error = error

    def _on_operation_finished(self, success: bool, checked_path: str) -> None:
        self.BaseProgressBar.set_indeterminate(False)
        self.BaseProgressBar.set_progress(self.BaseProgressBar.maximum())
        self.BaseProgressBar.set_state(ProgressState.SUCCESS if success else ProgressState.ERROR)

        self.btn_install.setEnabled(True)
        self.btn_uninstall.setEnabled(True)
        self._worker = None

        self._refresh_status(checked_path)

        self.CONFIG["startup"]["default_install_path"] = self.default_install_path
        self.CONFIG["startup"]["package_install_path"] = self.package_install_path
        self.CONFIG["startup"]["use_package_state"]    = self.use_package_state
        self.CONFIG["startup"]["version"]               = self.installer_version

        if not success:
            if self._last_error is not None:
                self.LOG.warning(f'Operation failed for "{checked_path}". Issue: {self._last_error}')
            else:
                self.LOG.warning(f'Operation failed for "{checked_path}". See PackageInstaller warnings for details.')

    def _refresh_status(self, checked_path: str) -> None:
        self.install_info = self.CORE.versionManager.check_install_status(checked_path)
        self.VersionStatusWidget.set_update_info(self.install_info)


if __name__ == '__main__':
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext() as content:
        window = InstallerView("0.0.1", parent=content.get_parent())
        window.show()