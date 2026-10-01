# tools/desktop/installer/installer_view.py
"""The setup window: pick a folder, install the desktop hub there, launch it."""
import sys
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.installer import runtime_bootstrap
from msl_tools.msl.core.installer.hub_installer import HubInstaller
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.paths.base_path_widget import BasePathWidget
from msl_tools.msl.ui.widgets.atoms.progress import BaseProgressBar, ProgressState
from msl_tools.msl.ui.widgets.atoms.status import VersionStatusWidget
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.workers import CallableWorker


class InstallerView(FramelessDialog):
    """Setup window of the desktop hub — runs on its own, no Maya involved
    (run_installer.py / setup_express_launcher.bat).

    The user picks the install folder; Install copies the package there
    (HubInstaller — it replaces a previous install's code and keeps its
    settings), optionally puts an "MSL Tools" shortcut on the desktop, and
    offers to launch the hub. Uninstall removes it again, asking what to do
    with the settings. Nothing is written into Maya's folders: Maya Gate
    injects its own userSetup at launch.

    No business logic here: HubInstaller does the work on a CallableWorker
    thread; the view shows the state (VersionStatusWidget: what is installed
    in the chosen folder vs. this package's version).
    """

    WIDTH = 460
    HEIGHT = 190

    def __init__(self, parent=None):
        self._core = Resources()
        self._ui = UiResources()
        self._log = self._core.logsDesktopHub.get("installer")
        self._installer = HubInstaller(self._core.fsManager.ROOT_DIR, logger=self._log)
        self._install_dir = str(self._installer.default_install_dir())
        self._worker: CallableWorker | None = None

        super().__init__(title="MSL Tools Setup", width=self.WIDTH, height=self.HEIGHT,
                         icon=self._ui.iconManager.get_icon("hub", sub_folder="brand"),
                         show_minimize_button=False, show_maximize_button=False,
                         fade_when_inactive=False, resources=self._ui, parent=parent)
        self._build_widgets()
        self._build_layout()
        self._build_connections()
        self._refresh()

    # --- construction ------------------------------------------------------------

    def _build_widgets(self) -> None:
        self._path = BasePathWidget(label="Install to", initial_path=self._install_dir)
        self._status = VersionStatusWidget(package_version=self._core.versionManager.core_raw_version,
                                           info=self._core.versionManager.check_install_status(self._install_dir))
        self._shortcut_checkbox = BaseCheckbox("Create a desktop shortcut")
        self._shortcut_checkbox.set_checked_immediate(True)

        self._message = qt.QtWidgets.QLabel()
        self._message.setObjectName("installerMessage")
        self._message.setWordWrap(True)
        self._progress = BaseProgressBar()

        self._install_button = qt.QtWidgets.QPushButton("Install")
        self._install_button.setProperty("primary", True)
        self._uninstall_button = qt.QtWidgets.QPushButton("Uninstall")
        self._launch_button = qt.QtWidgets.QPushButton("Launch MSL Tools")
        self._launch_button.hide()

    def _build_layout(self) -> None:
        buttons = qt.QtWidgets.QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(self._uninstall_button)
        buttons.addStretch()
        buttons.addWidget(self._launch_button)
        buttons.addWidget(self._install_button)

        layout = self.content_surface.content_layout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self._path)
        layout.addWidget(self._shortcut_checkbox)
        layout.addWidget(self._status)
        layout.addWidget(self._message)
        layout.addWidget(self._progress)
        layout.addStretch()
        layout.addLayout(buttons)

    def _build_connections(self) -> None:
        self._path.path_changed.connect(self._on_path_changed)
        self._install_button.clicked.connect(self._on_install)
        self._uninstall_button.clicked.connect(self._on_uninstall)
        self._launch_button.clicked.connect(self._on_launch)

    # --- state ---------------------------------------------------------------------

    def _on_path_changed(self, path: str) -> None:
        self._install_dir = str(Path(path)) if path.strip() else ""
        self._launch_button.hide()
        self._set_primary(self._install_button)
        self._refresh()

    def _refresh(self) -> None:
        """Buttons / status for whatever is (or isn't) in the chosen folder."""
        installed = self._installer.installed_version(self._install_dir) if self._install_dir else None
        is_source = bool(self._install_dir) and self._installer.is_source(self._install_dir)
        self._status.set_update_info(self._core.versionManager.check_install_status(self._install_dir or "."))
        self._install_button.setText("Reinstall" if installed else "Install")
        self._install_button.setEnabled(bool(self._install_dir) and not is_source)
        self._uninstall_button.setEnabled(installed is not None and not is_source)
        if is_source:
            self._set_message("This is the folder setup is running from — pick another one.", "warning")
        elif not self._install_dir:
            self._set_message("Pick a folder to install to.", "warning")
        elif self._message.property("state") == "warning":
            self._set_message("")

    def _set_message(self, text: str, state: str = "") -> None:
        self._message.setText(text)
        if self._message.property("state") != state:
            self._message.setProperty("state", state)  # colored by widgets.qss: QLabel#installerMessage[state]
            repolish(self._message)

    def _set_primary(self, button: qt.QtWidgets.QPushButton) -> None:
        """Makes `button` the accent one (the next sensible click)."""
        for candidate in (self._install_button, self._launch_button):
            candidate.setProperty("primary", candidate is button)
            repolish(candidate)

    # --- actions -------------------------------------------------------------------

    def _on_install(self) -> None:
        install_dir, shortcut = self._install_dir, self._shortcut_checkbox.isChecked()
        python = self._hub_python()

        def work() -> bool:
            if not self._installer.install(install_dir):
                return False
            if shortcut and not self._installer.create_shortcut(install_dir, python):
                self._log.warning("Installed, but the desktop shortcut could not be created.")
            return True

        self._run(work, done="Installed. You can launch MSL Tools now.", failed="Installation failed.",
                  on_success=self._after_install)

    def _on_uninstall(self) -> None:
        choice = ConfirmDialog.ask(
            self, "Uninstall MSL Tools", f'Remove MSL Tools from "{self._install_dir}"?',
            details="Your settings are the variables, userSetup scripts and window layout saved by the hub.",
            choices=[("keep", "Remove, keep my settings"), ("all", "Remove everything"), ("cancel", "Cancel")],
            kind="danger")
        if choice not in ("keep", "all"):
            return
        install_dir = self._install_dir

        def work() -> bool:
            self._installer.remove_shortcut()
            return self._installer.uninstall(install_dir, remove_user_data=(choice == "all"))

        self._run(work, done="Uninstalled.", failed="Could not remove everything (is MSL Tools still running?).")

    def _after_install(self) -> None:
        self._launch_button.show()
        self._set_primary(self._launch_button)

    def _on_launch(self) -> None:
        command = self._installer.launch_command(self._hub_python())
        if ProcessLauncher.launch_detached(command[0], arguments=command[1:], working_dir=self._install_dir):
            self.close()
        else:
            self._set_message("Could not start MSL Tools (see the log).", "error")

    @staticmethod
    def _hub_python() -> str:
        """Interpreter the installed hub runs with: the msl_tools environment
        if setup made one, else the Python running this window (a developer
        starting the installer from a checkout)."""
        runtime = runtime_bootstrap.python_executable(windowed=True)
        if runtime.is_file():
            return str(runtime)
        windowed = Path(sys.executable).with_name("pythonw.exe")
        return str(windowed if windowed.is_file() else sys.executable)

    # --- busy ----------------------------------------------------------------------

    def _run(self, work, done: str, failed: str, on_success=None) -> None:
        self._install_button.setEnabled(False)
        self._uninstall_button.setEnabled(False)
        self._path.setEnabled(False)
        self._launch_button.hide()
        self._set_message("Working…")
        self._progress.set_state(ProgressState.NORMAL)
        self._progress.set_indeterminate(True)

        self._pending = (done, failed, on_success)
        self._worker = CallableWorker(work, parent=self)
        self._worker.finished_with_result.connect(self._on_finished)  # a bound slot: delivered on the GUI thread
        self._worker.start()

    def _on_finished(self, success: bool) -> None:
        done, failed, on_success = self._pending
        self._worker = None
        self._progress.set_indeterminate(False)
        self._progress.set_progress(self._progress.maximum())
        self._progress.set_state(ProgressState.SUCCESS if success else ProgressState.ERROR)
        self._path.setEnabled(True)
        self._set_message(done if success else failed, "success" if success else "error")
        self._refresh()
        if success and on_success is not None:
            on_success()
