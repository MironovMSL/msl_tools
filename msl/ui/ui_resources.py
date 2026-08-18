# ui/ui_resources.py — Qt-зависимый, отдельная точка входа
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.pattern.singleton import SingletonMeta
from msl_tools.msl.core.theme import Theme
from msl_tools.msl.ui.icon_manager import IconManager
from msl_tools.msl.ui.theme import ThemeManager, StylesheetBuilder


class UiResources(metaclass=SingletonMeta):
    """Qt-dependent composition root, sibling to core.Resources."""

    def __init__(self):
        self.core         = Resources()
        self.iconManager  = IconManager(self.core.fsManager.icons, logger=self.core.logs.get("IconManager", to_file=False))
        self.themeManager = ThemeManager(self.core.themeRegistry, initial_theme=self.core.coreConfig["theme"]["name"])

        self.create_connections()
        self._on_theme_changed(self.themeManager.current_theme)


    def create_connections(self):
        self.themeManager.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, theme: Theme) -> None:
        """Reacts to a theme switch: updates icon lookup, re-applies the
        global QSS baseline, and persists the choice for next launch."""
        self.iconManager.set_theme(theme.name)

        app = qt.QtWidgets.QApplication.instance()
        if app is not None:
            app.setStyleSheet(StylesheetBuilder.build(theme))
        else:

            pass

        self.core.coreConfig["theme"]["name"] = theme.name


if __name__ == '__main__':

    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.widget_playground_dialog import WidgetPlaygroundDialog
    from msl_tools.msl.ui.widgets.atoms.progress import BaseProgressBar, ProgressState
    from msl_tools.msl.ui.widgets.atoms.status import VersionStatusWidget
    from msl_tools.msl.core.version.manager import UpdateInfo, UpdateStatus
    from msl_tools.msl.ui.widgets.atoms.paths import BasePathWidget

    with QtApplicationContext() as context:
        uiCore = UiResources()

        dialog = WidgetPlaygroundDialog(parent=context.get_parent())
        dialog.setWindowTitle("Theme demo")

        # --- переключатель темы ---
        theme_checkbox = qt.QtWidgets.QCheckBox("dark theme")
        theme_checkbox.setChecked(uiCore.themeManager.current_theme.name == "dark")
        theme_checkbox.toggled.connect(
            lambda checked: uiCore.themeManager.set_theme("dark" if checked else "light")
        )
        dialog.add_widget(theme_checkbox)
        dialog.add_separator()

        # --- обычные виджеты: ничего не подписываем, красятся глобальным QSS ---
        dialog.add_case("QPushButton / QLineEdit (global QSS)", qt.QtWidgets.QPushButton("click me"))
        dialog.add_widget(qt.QtWidgets.QLineEdit("plain QLineEdit"))

        base_path_demo = BasePathWidget()
        dialog.add_case("BasePathWidget / QLineEdit (global QSS)", base_path_demo)
        # dialog.add_widget(qt.QtWidgets.QLineEdit("plain QLineEdit"))

        # --- state-виджеты: сами подписаны на theme_changed ---
        progress = BaseProgressBar(theme=uiCore.themeManager.current_theme)
        progress.set_progress(65)
        progress.set_state(ProgressState.SUCCESS)
        uiCore.themeManager.theme_changed.connect(progress.set_theme)
        dialog.add_case("BaseProgressBar (SUCCESS state)", progress)

        demo_info = UpdateInfo(status=UpdateStatus.UPDATE_AVAILABLE, current_version="0.0.1", latest_version="0.0.2")
        version_widget = VersionStatusWidget(package_version="0.0.1", info=demo_info,
                                             theme=uiCore.themeManager.current_theme)
        uiCore.themeManager.theme_changed.connect(version_widget.set_theme)
        dialog.add_case("VersionStatusWidget (UPDATE_AVAILABLE)", version_widget)

        dialog.show()