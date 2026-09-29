# ui/widgets/atoms/status/version_status_widget.py

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.version.manager import UpdateInfo, UpdateStatus
from msl_tools.msl.ui.theme.qss import repolish


class VersionStatusWidget(qt.QtWidgets.QWidget):
    """Bottom status row: package version, installed version, and update status.

    Contains no comparison logic — only renders an UpdateInfo passed in via
    set_update_info(). The caller (e.g. an installer controller) is responsible
    for calling VersionManager.check_install_status() and forwarding the result.

    Styled entirely by the window stylesheet (ui/theme/widgets.qss): labels
    carry object names ("versionPrefix", "versionValue", "versionStatus"),
    and the status label a dynamic `status` property ("up_to_date",
    "update_available", "not_installed", "unknown"; empty before the first
    check) that the QSS picks the status color from.
    """

    _STATUS_TEXT = {
        UpdateStatus.UP_TO_DATE:       "up to date",
        UpdateStatus.UPDATE_AVAILABLE: "update available",
        UpdateStatus.NOT_INSTALLED:    "not installed",
        UpdateStatus.UNKNOWN:          "unknown",
    }

    def __init__(self,
                 package_version: str,
                 info: UpdateInfo | None = None,
                 parent=None):
        """
        Args:
            package_version: Version string of the package being installed
                (shown in the "Setup version" field).
            info: Initial UpdateInfo to render, or None to show placeholders.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._package_version = package_version
        self._last_info: UpdateInfo | None = info

        self._create_widgets()
        self._create_layouts()

        self.set_update_info(info)

    @staticmethod
    def _build_field(prefix_text: str) -> tuple[qt.QtWidgets.QWidget, qt.QtWidgets.QLabel, qt.QtWidgets.QLabel]:
        """Builds a small (prefix, value) label pair inside a horizontal
        container, so each part can be styled independently."""
        container = qt.QtWidgets.QWidget()
        layout = qt.QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        prefix_label = qt.QtWidgets.QLabel(prefix_text)
        prefix_label.setObjectName("versionPrefix")

        value_label = qt.QtWidgets.QLabel()
        value_label.setObjectName("versionValue")

        layout.addWidget(prefix_label)
        layout.addWidget(value_label)

        return container, prefix_label, value_label

    def _create_widgets(self) -> None:
        self.version_container, _, self.version_value_label = self._build_field("Setup version:")
        self.version_value_label.setText(self._package_version)

        self.installed_container, _, self.installed_value_label = self._build_field("Installed version:")
        self.status_container, self.status_prefix_label, self.status_value_label = self._build_field("Status:")
        self.status_value_label.setObjectName("versionStatus")

    def _create_layouts(self) -> None:
        self.main_layout = qt.QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.main_layout.addWidget(self.version_container)
        self.main_layout.addStretch()
        self.main_layout.addWidget(self.installed_container)
        self.main_layout.addStretch()
        self.main_layout.addWidget(self.status_container)

    def set_update_info(self, info: UpdateInfo | None) -> None:
        """Updates the display from an UpdateInfo. None means status was not checked yet."""
        self._last_info = info

        if info is None:
            self.installed_value_label.setText("—")
            self.status_value_label.setText("—")
            self._set_status_property("")
            return

        if info.status is UpdateStatus.NOT_INSTALLED:
            self.installed_value_label.setText("—")
        else:
            self.installed_value_label.setText(str(info.current_version))

        self.status_value_label.setText(self._STATUS_TEXT.get(info.status, "unknown"))
        self._set_status_property(info.status.name.lower())

    def _set_status_property(self, status: str) -> None:
        self.status_value_label.setProperty("status", status)
        repolish(self.status_value_label)



if __name__ == "__main__":

    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        dialog.add_case("not checked yet", VersionStatusWidget(package_version="0.0.2"))
        for status in UpdateStatus:
            info = UpdateInfo(status=status, current_version="0.0.1", latest_version="0.0.2")
            dialog.add_case(status.name, VersionStatusWidget(package_version="0.0.2", info=info))
        dialog.show()
