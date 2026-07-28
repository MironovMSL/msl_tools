import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.version.manager import UpdateInfo, UpdateStatus


class VersionStatusWidget(qt.QtWidgets.QWidget):
    """Bottom status row: package version, installed version, and update status.

    Contains no comparison logic — only renders an UpdateInfo passed in via
    set_update_info(). The caller (e.g. an installer controller) is responsible
    for calling VersionManager.check_install_status() and forwarding the result.
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
        """Updates the display from an UpdateInfo. None means status was not checked yet."""

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