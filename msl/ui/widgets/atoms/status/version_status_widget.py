# ui/widgets/atoms/status/version_status_widget.py

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme, ThemeRegistry
from msl_tools.msl.core.version.manager import UpdateInfo, UpdateStatus


class VersionStatusWidget(qt.QtWidgets.QWidget):
    """Bottom status row: package version, installed version, and update status.

    Contains no comparison logic — only renders an UpdateInfo passed in via
    set_update_info(). The caller (e.g. an installer controller) is responsible
    for calling VersionManager.check_install_status() and forwarding the result.

    Colors come from a Theme instance rather than hardcoded hex values — call
    set_theme() to re-color every label (including the current status color)
    when the active theme changes.
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
                 theme: Theme | None = None,
                 parent=None):
        """
        Args:
            package_version: Version string of the package being installed
                (shown in the "Setup version" field).
            info: Initial UpdateInfo to render, or None to show placeholders.
            theme: Theme to color this widget with. Defaults to
                ThemeRegistry.fallback() (no file I/O) so this widget can be
                used standalone without wiring up UiResources.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._package_version = package_version
        self._theme = theme or ThemeRegistry.fallback()
        self._last_info: UpdateInfo | None = info

        # Populated by _build_field() as fields are created, so set_theme()
        # can re-style every label without needing per-field references
        # threaded through the constructor.
        self._prefix_labels: list[qt.QtWidgets.QLabel] = []
        self._value_labels: list[qt.QtWidgets.QLabel] = []

        self._create_widgets()
        self._create_layouts()

        self.set_update_info(info)

    def _status_color(self, status: UpdateStatus) -> str:
        """Maps an UpdateStatus to a semantic color from the current theme."""
        return {
            UpdateStatus.UP_TO_DATE:       self._theme.success,
            UpdateStatus.UPDATE_AVAILABLE: self._theme.warning,
            UpdateStatus.NOT_INSTALLED:    self._theme.text_secondary,
            UpdateStatus.UNKNOWN:          self._theme.error,
        }.get(status, self._theme.error)

    def _prefix_style(self) -> str:
        return f"color: {self._theme.text_secondary}; font-size: 12px;"

    def _value_style(self) -> str:
        return f"color: {self._theme.text_primary}; font-size: 13px; font-weight: 600;"

    def _status_style(self, color: str) -> str:
        return f"color: {color}; font-size: 13px; font-weight: 600;"

    def _build_field(self, prefix_text: str) -> tuple[qt.QtWidgets.QWidget, qt.QtWidgets.QLabel, qt.QtWidgets.QLabel]:
        """Builds a small (prefix, value) label pair inside a horizontal container,
        so each part can be styled independently. Registers both labels so
        set_theme() can find and re-style them later."""
        container = qt.QtWidgets.QWidget()
        laout = qt.QtWidgets.QHBoxLayout(container)
        laout.setContentsMargins(0, 0, 0, 0)
        laout.setSpacing(4)

        prefix_label = qt.QtWidgets.QLabel(prefix_text)
        prefix_label.setStyleSheet(self._prefix_style())
        self._prefix_labels.append(prefix_label)

        value_label = qt.QtWidgets.QLabel()
        value_label.setStyleSheet(self._value_style())
        self._value_labels.append(value_label)

        laout.addWidget(prefix_label)
        laout.addWidget(value_label)

        return container, prefix_label, value_label

    def _create_widgets(self) -> None:
        self.version_container, _, self.version_value_label = self._build_field("Setup version:")
        self.version_value_label.setText(self._package_version)

        self.installed_container, _, self.installed_value_label = self._build_field("Installed version:")
        self.status_container, self.status_prefix_label, self.status_value_label = self._build_field("Status:")

        # status_value_label gets a status-colored style, not the generic
        # value style — exclude it from the generic re-theming list so
        # set_theme() doesn't clobber it; set_update_info() owns its color.
        self._value_labels.remove(self.status_value_label)

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
        self._last_info = info

        if info is None:
            self.installed_value_label.setText("—")
            self.status_value_label.setText("—")
            self.status_value_label.setStyleSheet(self._value_style())
            return

        if info.status is UpdateStatus.NOT_INSTALLED:
            self.installed_value_label.setText("—")
        else:
            self.installed_value_label.setText(str(info.current_version))

        status_text  = self._STATUS_TEXT.get(info.status, "unknown")
        status_color = self._status_color(info.status)

        self.status_value_label.setText(status_text)
        self.status_value_label.setStyleSheet(self._status_style(status_color))

    def set_theme(self, theme: Theme) -> None:
        """Re-colors every label for a new Theme, preserving current text and
        the currently displayed update status."""
        self._theme = theme

        for label in self._prefix_labels:
            label.setStyleSheet(self._prefix_style())
        for label in self._value_labels:
            label.setStyleSheet(self._value_style())

        # Re-apply status color/text through the same path set_update_info()
        # uses, rather than duplicating that logic here.
        self.set_update_info(self._last_info)


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

        ver_wdg_dark = VersionStatusWidget(package_version="0.0.0", info=info,
                                            theme=ThemeRegistry.fallback("dark"))

        dialog = WidgetPlaygroundDialog()
        # dialog.setStyleSheet("background-color: rgb(0, 0, 0);")
        dialog.add_case("VersionStatusWidget", ver_wdg)
        dialog.add_case("VersionStatusWidget (dark)", ver_wdg_dark)
        dialog.show()