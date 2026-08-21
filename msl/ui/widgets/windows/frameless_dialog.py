import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.windows.frameless_mixin import FramelessWindowMixin


class FramelessDialog(FramelessWindowMixin, qt.QtWidgets.QDialog):

    ICON_SUB_FOLDER = "window"

    CLOSE_HOVER_ICON_COLOR_LIGHT = "#ffffff"
    CLOSE_HOVER_ICON_COLOR_DARK  = "#000000"


    def __init__(self,
                 title: str = "",
                 width: int = 480,
                 height: int = 320,
                 icon: qt.QtGui.QIcon | None = None,
                 subtitle: str | None = None,
                 show_close_button: bool = True,
                 resources: UiResources | None = None, parent=None):
        super().__init__(parent)

        self._resources = resources or UiResources()

        self._init_frameless_state(corner_radius=15)
        self.resize(width, height)
        self._build_base_ui(title, icon, subtitle, show_close_button)

        self._resources.themeManager.theme_changed.connect(self._on_theme_changed)
        self._apply_theme(self._resources.themeManager.current_theme)

    def _build_base_ui(self, title, icon, subtitle, show_close_button) -> None:
        self._root_layout = qt.QtWidgets.QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._build_frameless_chrome(self._root_layout,
                                     title,
                                     icon=icon,
                                     subtitle=subtitle,
                                     show_minimize_button=True,
                                     show_maximize_button=False,
                                     show_close_button=show_close_button)
        self.content_layout = qt.QtWidgets.QVBoxLayout()
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(12)
        self._root_layout.addLayout(self.content_layout)
        self._root_layout.addStretch()

    def add_widget(self, widget) -> None:
        self.content_layout.addWidget(widget)

    def add_separator(self) -> None:
        line = qt.QtWidgets.QFrame()
        line.setFrameShape(qt.QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet("color: gray;")
        self.content_layout.addWidget(line)

    def _on_theme_changed(self, theme: Theme) -> None:
        self._apply_theme(theme)

    def _apply_theme(self, theme: Theme) -> None:
        self.set_background_color(theme.surface)
        if self._close_button is None:
            return

        close_hover_icon_color = "#ffffff" if theme.name == "light" else "#000000"

        icon_manager = self._resources.iconManager
        color = theme.text_primary

        hover_alpha   = 15 if theme.name == "light" else 30
        pressed_alpha = 30 if theme.name == "light" else 15
        overlay = qt.QtGui.QColor(color)
        overlay.setAlpha(hover_alpha)
        pressed_overlay = qt.QtGui.QColor(color)
        pressed_overlay.setAlpha(pressed_alpha)

        if self._minimize_button is not None:
            minimize_icon = icon_manager.get_icon("minimize", sub_folder=self.ICON_SUB_FOLDER, color=color)
            self._minimize_button.set_icon(minimize_icon)
            self._minimize_button.set_hover_color(overlay)
            self._minimize_button.set_pressed_color(pressed_overlay)

        if self._maximize_button is not None:
            maximize_icon = icon_manager.get_icon("maximize", sub_folder=self.ICON_SUB_FOLDER, color=color)
            restore_icon = icon_manager.get_icon("restore", sub_folder=self.ICON_SUB_FOLDER, color=color)
            self._maximize_button.set_icons(maximize_icon, restore_icon)
            self._maximize_button.set_hover_color(overlay)
            self._maximize_button.set_pressed_color(pressed_overlay)

        if self._close_button is not None:
            close_idle = icon_manager.get_icon("close", sub_folder=self.ICON_SUB_FOLDER, color=color)
            close_hover = icon_manager.get_icon("close", sub_folder=self.ICON_SUB_FOLDER, color=close_hover_icon_color)
            self._close_button.set_icon(close_idle, hover_icon=close_hover)


if __name__ == '__main__':
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        window = FramelessDialog(title="BaseDialog", subtitle="theme demo")

        theme_checkbox = qt.QtWidgets.QCheckBox("dark theme")
        resources = window._resources
        theme_checkbox.setChecked(resources.themeManager.current_theme.name == "dark")
        theme_checkbox.toggled.connect(lambda checked: resources.themeManager.set_theme("dark" if checked else "light"))
        window.add_header_widget(theme_checkbox, side="right")

        window.add_widget(qt.QtWidgets.QPushButton("test"))
        window.add_widget(qt.QtWidgets.QPushButton("test2"))
        window.add_separator()
        window.show()