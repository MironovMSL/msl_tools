"""
View тула установки. Чистый UI без бизнес-логики.
"""
from pathlib import Path

from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
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


class InstallerView(qt.QtWidgets.QDialog):
    """Installer window: lets the user pick an install path and install /
    uninstall the package. Contains no business logic itself — every action
    delegates to Resources().packageInstaller / versionManager and this view
    only wires widgets to those calls and reflects the results.
    """

    NAME = 'Installer'

    # Populated lazily by _ensure_core() on first instantiation, not at
    # class-body/import time. Resources()/UiResources() perform real I/O in
    # their constructors — importing this module must not trigger that.
    CORE: Resources | None = None
    UI_CORE: UiResources | None = None
    CONFIG = None
    LOG = None
    WINDOW_ICON = None

    @classmethod
    def _ensure_core(cls) -> None:
        """Initializes shared core/UI resources on first use.

        Resources and UiResources are singletons, so this performs real I/O
        only once per process no matter how many InstallerView instances are
        created afterwards.
        """
        if cls.CORE is not None:
            return
        cls.CORE = Resources()
        cls.UI_CORE = UiResources()
        cls.CONFIG = cls.CORE.configManager.get_config(cls.NAME, defaults=default_config)
        cls.LOG = cls.CORE.logManager.get(cls.NAME)
        cls.WINDOW_ICON = cls.UI_CORE.iconManager.get_icon(cls.NAME)

    def __init__(self, version: str, parent=None):
        super().__init__(parent=parent)
        self._ensure_core()

        self.installer_version = version
        self.msl_tool_version  = self.CORE.versionManager.core_raw_version

        pref_maya_path     = self.CORE.fsManager.mayaPaths.get_preferences_root() / "scripts"
        root_package_path  = self.CORE.fsManager.PARENT_DIR
        self.default_install_path = str(self.CONFIG["startup"]["default_install_path"] or pref_maya_path)
        self.package_install_path = str(self.CONFIG["startup"]["package_install_path"] or root_package_path)
        self.use_package_state    = self.CONFIG["startup"]["use_package_state"]

        self.width_window  = self.CONFIG["startup"]["width"]
        self.height_window = self.CONFIG["startup"]["height"]

        self.setWindowTitle(self.CONFIG["startup"]["name"] or self.NAME)
        self.setWindowIcon(self.WINDOW_ICON)
        self.resize(self.width_window, self.height_window)

        self._worker: CallableWorker | None = None

        self.install_info = self.CORE.versionManager.check_install_status(
            self.package_install_path if self.use_package_state else self.default_install_path
        )

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

        install_path_layout = qt.QtWidgets.QHBoxLayout()
        install_path_layout.addWidget(self.InstallPathWidget)

        version_status_layout = qt.QtWidgets.QHBoxLayout()
        version_status_layout.addWidget(self.VersionStatusWidget)

        progress_layout = qt.QtWidgets.QHBoxLayout()
        progress_layout.addWidget(self.BaseProgressBar)

        main_layout = qt.QtWidgets.QVBoxLayout(self)
        main_layout.setAlignment(qt.QtCore.Qt.AlignTop)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        main_layout.addLayout(button_layout)
        main_layout.addLayout(install_path_layout)
        main_layout.addLayout(version_status_layout)
        main_layout.addLayout(progress_layout)

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
        if self.use_package_state:
            # Running directly from the package folder — nothing to copy,
            # just refresh the displayed status.
            self._refresh_status(self.package_install_path)
            return

        target_path = self.default_install_path
        self._run_busy(
            target=lambda: self.CORE.packageInstaller.install_package(self.package_install_path, target_path),
            checked_path=target_path,
        )

    def on_click_uninstall(self):
        if self.use_package_state:
            self._refresh_status(self.package_install_path)
            return

        target_path = self.default_install_path
        self._run_busy(
            target=lambda: self.CORE.packageInstaller.uninstall_package(target_path),
            checked_path=target_path,
        )

    def _run_busy(self, target, checked_path: str) -> None:
        """Runs `target` on a background thread while the progress bar shows
        an indeterminate ("busy") state, then reflects the boolean result in
        the UI once the thread finishes.

        We deliberately don't fake a percentage: PackageInstaller doesn't
        report granular progress, and a number that doesn't track real work
        is misleading. Indeterminate mode communicates "working" honestly,
        and running on a QThread keeps the window responsive while it does.
        """
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
        """Captures an exception raised inside the worker's target callable,
        so _on_operation_finished can include it in the warning it logs.
        `failed` always fires before `finished_with_result`, so this value is
        ready by the time it's read."""
        self._last_error = error

    def _on_operation_finished(self, success: bool, checked_path: str) -> None:
        self.BaseProgressBar.set_indeterminate(False)
        self.BaseProgressBar.set_progress(self.BaseProgressBar.maximum())
        self.BaseProgressBar.set_state(ProgressState.SUCCESS if success else ProgressState.ERROR)

        self.btn_install.setEnabled(True)
        self.btn_uninstall.setEnabled(True)
        self._worker = None

        self._refresh_status(checked_path)

        # Path/state prefs are saved regardless of outcome so the user
        # doesn't lose what they typed; only warn on failure.
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