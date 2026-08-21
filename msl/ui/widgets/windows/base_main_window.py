import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.windows.frameless_mixin import FramelessWindowMixin


class FramelessMainWindow(FramelessWindowMixin, qt.QtWidgets.QMainWindow):
    """Frameless QMainWindow with a custom title bar, drag/resize, and
    minimize/maximize/restore.

    Theme-aware: subscribes to UiResources.themeManager on construction and
    keeps its nav button icons/hover colors and window background in sync.
    The header's own background/text color are plain QSS, already covered by
    UiResources' global QApplication.setStyleSheet() on every theme change —
    this class only re-themes what QSS structurally cannot reach: the
    custom-painted window background and BaseNavButton's custom-painted
    icons/hover colors.

    A nested QMainWindow is used purely as an internal "body" — this lets
    setMenuBar()/addToolBar()/setStatusBar()/setCentralWidget() keep working
    exactly like on a normal QMainWindow, without reimplementing that layout
    machinery ourselves.

    Contains no DCC-specific logic — parenting to Maya (or any host) is done
    by the caller when instantiating.
    """

    ICON_SUB_FOLDER = "window"
    CLOSE_HOVER_ICON_COLOR = "#ffffff"
    HOVER_OVERLAY_ALPHA = 28

    def __init__(self, *, title: str = "", width: int = 960, height: int = 640,
                 icon: qt.QtGui.QIcon | None = None, subtitle: str | None = None,
                 show_close_button: bool = True, show_minimize_button: bool = True,
                 show_maximize_button: bool = True,
                 resources: UiResources | None = None, parent=None):
        super().__init__(parent)
        self._resources = resources or UiResources()

        self._init_frameless_state()
        self.resize(width, height)
        self._build_base_ui(title, icon, subtitle,
                             show_close_button, show_minimize_button, show_maximize_button)

        self._resources.themeManager.theme_changed.connect(self._on_theme_changed)
        self._apply_theme(self._resources.themeManager.current_theme)

    def _build_base_ui(self, title: str, icon: qt.QtGui.QIcon | None, subtitle: str | None,
                        show_close_button: bool, show_minimize_button: bool,
                        show_maximize_button: bool) -> None:
        shell = qt.QtWidgets.QWidget()
        shell_layout = qt.QtWidgets.QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self._build_frameless_chrome(
            shell_layout, title,
            icon=icon, subtitle=subtitle,
            show_close_button=show_close_button,
            show_minimize_button=show_minimize_button,
            show_maximize_button=show_maximize_button,
        )

        self._body = qt.QtWidgets.QMainWindow()
        self._body.setWindowFlags(qt.QtCore.Qt.WindowType.Widget)
        shell_layout.addWidget(self._body)

        # Bypass our own setCentralWidget() override below — this sets the
        # outer shell (header + body) as the real QMainWindow central widget.
        qt.QtWidgets.QMainWindow.setCentralWidget(self, shell)

    # --- Delegate the standard QMainWindow API to the inner body ---

    def setMenuBar(self, menu_bar: qt.QtWidgets.QMenuBar) -> None:
        self._body.setMenuBar(menu_bar)

    def menuBar(self) -> qt.QtWidgets.QMenuBar:
        return self._body.menuBar()

    def addToolBar(self, *args, **kwargs):
        return self._body.addToolBar(*args, **kwargs)

    def setStatusBar(self, status_bar: qt.QtWidgets.QStatusBar) -> None:
        self._body.setStatusBar(status_bar)

    def statusBar(self) -> qt.QtWidgets.QStatusBar:
        return self._body.statusBar()

    def setCentralWidget(self, widget: qt.QtWidgets.QWidget) -> None:
        self._body.setCentralWidget(widget)

    def centralWidget(self) -> qt.QtWidgets.QWidget:
        return self._body.centralWidget()

    # --- Theming ---

    def _on_theme_changed(self, theme: Theme) -> None:
        self._apply_theme(theme)

    def _apply_theme(self, theme: Theme) -> None:
        self.set_background_color(theme.surface)

        icon_manager = self._resources.iconManager
        color = theme.text_primary

        overlay = qt.QtGui.QColor(color)
        overlay.setAlpha(self.HOVER_OVERLAY_ALPHA)

        if self._minimize_button is not None:
            minimize_icon = icon_manager.get_icon("minimize", sub_folder=self.ICON_SUB_FOLDER, color=color)
            self._minimize_button.set_icon(minimize_icon)
            self._minimize_button.set_hover_color(overlay)

        if self._maximize_button is not None:
            maximize_icon = icon_manager.get_icon("maximize", sub_folder=self.ICON_SUB_FOLDER, color=color)
            restore_icon = icon_manager.get_icon("restore", sub_folder=self.ICON_SUB_FOLDER, color=color)
            self._maximize_button.set_icons(maximize_icon, restore_icon)
            self._maximize_button.set_hover_color(overlay)

        if self._close_button is not None:
            close_idle = icon_manager.get_icon("close", sub_folder=self.ICON_SUB_FOLDER, color=color)
            close_hover = icon_manager.get_icon("close", sub_folder=self.ICON_SUB_FOLDER, color=("#FFFFFF" if theme.name=="light" else "#000000"))
            self._close_button.set_icon(close_idle, hover_icon=close_hover)
            self._close_button.set_hover_color(overlay)  # no-op on CloseNavButton, by design


if __name__ == '__main__':
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext() as context:
        window = FramelessMainWindow(title="FramelessMainWindow", subtitle="theme demo")

        theme_checkbox = qt.QtWidgets.QCheckBox("dark theme")
        resources = window._resources
        theme_checkbox.setChecked(resources.themeManager.current_theme.name == "dark")
        theme_checkbox.toggled.connect(lambda checked: resources.themeManager.set_theme("dark" if checked else "light"))
        window.add_header_widget(theme_checkbox, side="right")

        menu_bar = qt.QtWidgets.QMenuBar()
        menu_bar.addMenu("File")
        menu_bar.addMenu("Edit")
        window.setMenuBar(menu_bar)

        window.setCentralWidget(qt.QtWidgets.QPushButton("body content"))
        window.setStatusBar(qt.QtWidgets.QStatusBar())
        window.show()