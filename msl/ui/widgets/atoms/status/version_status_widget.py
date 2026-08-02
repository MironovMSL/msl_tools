# ui/widgets/atoms/status/version_status_widget.py

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.version.manager import UpdateInfo, UpdateStatus


class VersionStatusWidget(qt.QtWidgets.QWidget):
    """Bottom status row: package version, installed version, and update status.

    Contains no comparison logic — only renders an UpdateInfo passed in via
    set_update_info(). The caller (e.g. an installer controller) is responsible
    for calling VersionManager.check_install_status() and forwarding the result.
    """

    _PREFIX_STYLE        = "color: #878787; font-size: 12px;"
    _VALUE_STYLE         = "color: #0a0a0a; font-size: 13px; font-weight: 600;"

    _STATUS_TEXT = {
        UpdateStatus.UP_TO_DATE:       "up to date",
        UpdateStatus.UPDATE_AVAILABLE: "update available",
        UpdateStatus.NOT_INSTALLED:    "not installed",
        UpdateStatus.UNKNOWN:          "unknown",
    }

    _STATUS_COLOR = {
        UpdateStatus.UP_TO_DATE:       "#4caf50",
        UpdateStatus.UPDATE_AVAILABLE: "#ff9800",
        UpdateStatus.NOT_INSTALLED:    "#878787",
        UpdateStatus.UNKNOWN:          "#f44336",
    }

    def __init__(self, package_version: str, info: UpdateInfo | None = None, parent=None):
        super().__init__(parent)

        self._package_version = package_version

        self._create_widgets()
        self._create_layouts()

        self.set_update_info(info)

    def _build_field(self, prefix_text: str) -> tuple[qt.QtWidgets.QWidget, qt.QtWidgets.QLabel, qt.QtWidgets.QLabel]:
        """Builds a small (prefix, value) label pair inside a horizontal container,
        so each part can be styled independently."""
        container = qt.QtWidgets.QWidget()
        laout = qt.QtWidgets.QHBoxLayout(container)
        laout.setContentsMargins(0, 0, 0, 0)
        laout.setSpacing(4)

        prefix_label = qt.QtWidgets.QLabel(prefix_text)
        prefix_label.setStyleSheet(self._PREFIX_STYLE)

        value_label = qt.QtWidgets.QLabel()
        value_label.setStyleSheet(self._VALUE_STYLE)

        laout.addWidget(prefix_label)
        laout.addWidget(value_label)

        return container, prefix_label, value_label

    def _create_widgets(self) -> None:
        self.version_container, _, self.version_value_label = self._build_field("Setup version:")
        self.version_value_label.setText(self._package_version)

        self.installed_container, _, self.installed_value_label = self._build_field("Installed version:")
        self.status_container, self.status_prefix_label, self.status_value_label = self._build_field("Status:")

    def _create_layouts(self) -> None:
        self.main_laout = qt.QtWidgets.QHBoxLayout(self)
        self.main_laout.setContentsMargins(0, 0, 0, 0)
        self.main_laout.setSpacing(0)

        self.main_laout.addWidget(self.version_container)
        self.main_laout.addStretch()
        self.main_laout.addWidget(self.installed_container)
        self.main_laout.addStretch()
        self.main_laout.addWidget(self.status_container)

    def set_update_info(self, info: UpdateInfo | None) -> None:
        """Updates the display from an UpdateInfo. None means status was not checked yet."""

        if info is None:
            self.installed_value_label.setText("—")
            self.status_value_label.setText("—")
            self.status_value_label.setStyleSheet(self._VALUE_STYLE)
            return

        if info.status is UpdateStatus.NOT_INSTALLED:
            self.installed_value_label.setText("—")
        else:
            self.installed_value_label.setText(str(info.current_version))

        status_text  = self._STATUS_TEXT.get(info.status, "unknown")
        status_color = self._STATUS_COLOR.get(info.status, "red")

        self.status_value_label.setText(status_text)
        self.status_value_label.setStyleSheet(f"color: {status_color}; font-size: 13px; font-weight: 600;")


if __name__ == "__main__":

    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.widget_playground_dialog import WidgetPlaygroundDialog

    current_version = "0.0.1"
    status = UpdateStatus.UP_TO_DATE
    # status = UpdateStatus.UPDATE_AVAILABLE
    # status = UpdateStatus.NOT_INSTALLED
    # status = UpdateStatus.UNKNOWN
    latest_version = "0.0.0"

    info = UpdateInfo(status=status, current_version=current_version, latest_version=latest_version)

    with QtApplicationContext():
        ver_wdg = VersionStatusWidget(package_version="0.0.0", info=info)

        dialog = WidgetPlaygroundDialog()
        dialog.add_case("VersionStatusWidget", ver_wdg)
        dialog.show()