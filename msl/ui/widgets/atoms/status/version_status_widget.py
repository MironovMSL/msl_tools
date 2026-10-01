# ui/widgets/atoms/status/version_status_widget.py

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.version.manager import UpdateInfo, UpdateStatus
from msl_tools.msl.ui.theme.qss import repolish


class VersionStatusWidget(qt.QtWidgets.QWidget):
    """One quiet line saying what is installed, and how that relates to the
    package being set up:

        Installed 0.1.1  ·  up to date
        Installed 0.1.0  ·  this setup installs 0.1.3
        Installed 0.1.3  ·  newer than this setup (0.1.1)
        Not installed  ·  this setup installs 0.1.3

    The setup's own version is only mentioned when it differs from the
    installed one. Contains no version comparison — it renders an UpdateInfo
    passed in via set_update_info(); the caller calls
    VersionManager.check_install_status() and forwards the result.

    Styled entirely by the window stylesheet (ui/theme/widgets.qss): the
    labels are QLabel#versionValue / #versionSeparator / #versionStatus, and
    the status label carries a dynamic `status` property ("up_to_date",
    "update_available", "newer", "not_installed", "unknown"; empty before
    the first check) that the QSS picks its color from. It is reference
    information, so "up to date" is NOT colored — the caller's own message
    is the place for a success accent.
    """

    SEPARATOR = "·"

    def __init__(self,
                 package_version: str,
                 info: UpdateInfo | None = None,
                 parent=None):
        """
        Args:
            package_version: Version of the package being installed (what
                this setup would put in place).
            info: Initial UpdateInfo to render, or None to show a placeholder.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._package_version = package_version
        self._last_info: UpdateInfo | None = info

        self._create_widgets()
        self._create_layouts()

        self.set_update_info(info)

    def _create_widgets(self) -> None:
        self.installed_value_label = qt.QtWidgets.QLabel()
        self.installed_value_label.setObjectName("versionValue")
        self.separator_label = qt.QtWidgets.QLabel(self.SEPARATOR)
        self.separator_label.setObjectName("versionSeparator")
        self.status_value_label = qt.QtWidgets.QLabel()
        self.status_value_label.setObjectName("versionStatus")

    def _create_layouts(self) -> None:
        self.main_layout = qt.QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(6)
        self.main_layout.addWidget(self.installed_value_label)
        self.main_layout.addWidget(self.separator_label)
        self.main_layout.addWidget(self.status_value_label)
        self.main_layout.addStretch()

    def set_update_info(self, info: UpdateInfo | None) -> None:
        """Updates the display from an UpdateInfo. None means status was not checked yet."""
        self._last_info = info
        package = self._package_version

        if info is None:
            self._show("—", "", "")
        elif info.status is UpdateStatus.NOT_INSTALLED:
            self._show("Not installed", f"this setup installs {package}", "not_installed")
        elif info.status is UpdateStatus.UPDATE_AVAILABLE:
            self._show(f"Installed {info.current_version}", f"this setup installs {package}", "update_available")
        elif info.status is UpdateStatus.UP_TO_DATE:
            if str(info.current_version) == str(package):
                self._show(f"Installed {info.current_version}", "up to date", "up_to_date")
            else:  # nothing newer to offer, yet not the same version: the installed one is ahead
                self._show(f"Installed {info.current_version}", f"newer than this setup ({package})", "newer")
        else:
            self._show("Installed version unknown", "", "unknown")

    def _show(self, value: str, status_text: str, status: str) -> None:
        self.installed_value_label.setText(value)
        self.status_value_label.setText(status_text)
        self.separator_label.setVisible(bool(status_text))
        self.status_value_label.setVisible(bool(status_text))
        for label in (self.installed_value_label, self.status_value_label):
            label.setProperty("status", status)
            repolish(label)


if __name__ == "__main__":

    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        dialog.add_case("not checked yet", VersionStatusWidget(package_version="0.0.2"))
        for status in UpdateStatus:
            info = UpdateInfo(status=status, current_version="0.0.1", latest_version="0.0.2")
            dialog.add_case(status.name, VersionStatusWidget(package_version="0.0.2", info=info))
        dialog.add_case("installed is newer than the setup", VersionStatusWidget(
            package_version="0.0.2", info=UpdateInfo(status=UpdateStatus.UP_TO_DATE, current_version="0.0.5")))
        dialog.show()
