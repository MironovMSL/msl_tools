import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme
from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton
from msl_tools.msl.ui.widgets.atoms.header.close_nav_button import CloseNavButton
from msl_tools.msl.ui.widgets.atoms.header.minimize_nav_button import MinimizeNavButton
from msl_tools.msl.ui.widgets.atoms.header.maximize_nav_button import MaximizeNavButton


class WindowHeader(qt.QtWidgets.QWidget):
    """Title bar row for frameless windows. ... (docstring unchanged)"""

    def __init__(self, title: str = "", height: int = 36, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)

        self.corner_radius = 0
        self.corner_button: BaseNavButton | None = None
        self._chrome_background: str | None = None
        self._border_color: str | None = None  # new

        self._apply_stylesheet()

        self.create_widgets(title)
        self.create_layouts()

    def create_widgets(self, title: str = ""):
        self.icon_label = qt.QtWidgets.QLabel()
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setScaledContents(True)
        self.icon_label.hide()

        self.title_label = qt.QtWidgets.QLabel(title)
        self.title_label.setStyleSheet("font-weight: 600; font-size: 12px;")  # color -> global QSS (QLabel -> text_primary)

        self.subtitle_label = qt.QtWidgets.QLabel()
        self.subtitle_label.setObjectName("headerSubtitle")  # targeted by StylesheetBuilder for text_secondary
        self.subtitle_label.setStyleSheet("font-size: 12px;")
        self.subtitle_label.hide()

    def create_layouts(self):
        self.leading_layout = qt.QtWidgets.QHBoxLayout()
        self.leading_layout.setSpacing(6)
        self.leading_layout.addWidget(self.icon_label)
        self.leading_layout.addWidget(self.title_label)
        self.leading_layout.addWidget(self.subtitle_label)

        self.trailing_layout = qt.QtWidgets.QHBoxLayout()
        self.trailing_layout.setSpacing(6)

        self.nav_layout = qt.QtWidgets.QHBoxLayout()
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(0)

        self.main_layout = qt.QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(8, 0, 0, 0)
        self.main_layout.setSpacing(6)

        self.main_layout.addLayout(self.leading_layout)
        self.main_layout.addStretch()
        self.main_layout.addLayout(self.trailing_layout)
        self.main_layout.addLayout(self.nav_layout)

    # --- Leading zone content ---

    def set_icon(self, icon: qt.QtGui.QIcon) -> None:
        self.icon_label.setPixmap(icon.pixmap(16, 16))
        self.icon_label.show()

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_subtitle(self, text: str | None) -> None:
        if not text:
            self.subtitle_label.hide()
            return
        self.subtitle_label.setText(f"|  {text}")
        self.subtitle_label.show()

    # --- Extension points ---

    def add_leading_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        self.leading_layout.addWidget(widget)

    def add_trailing_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        self.trailing_layout.addWidget(widget)

    # --- Nav (window control) button sets ---

    def add_close_only_controls(self, close_slot) -> CloseNavButton:

        close_button = CloseNavButton()
        close_button.clicked.connect(close_slot)
        self.nav_layout.addWidget(close_button)
        self.set_corner_button(close_button)
        return close_button

    def add_close_minimize_controls(self, minimize_slot, close_slot) -> tuple[MinimizeNavButton, CloseNavButton]:
        minimize_button = MinimizeNavButton()
        minimize_button.clicked.connect(minimize_slot)
        close_button = CloseNavButton()
        close_button.clicked.connect(close_slot)
        self.nav_layout.addWidget(minimize_button)
        self.nav_layout.addWidget(close_button)
        self.set_corner_button(close_button)
        return minimize_button, close_button

    def add_window_controls(self, minimize_slot, maximize_slot, close_slot) -> tuple[MinimizeNavButton, MaximizeNavButton, CloseNavButton]:
        minimize_button = MinimizeNavButton()
        minimize_button.clicked.connect(minimize_slot)
        maximize_button = MaximizeNavButton()
        maximize_button.clicked.connect(maximize_slot)
        close_button = CloseNavButton()
        close_button.clicked.connect(close_slot)
        self.nav_layout.addWidget(minimize_button)
        self.nav_layout.addWidget(maximize_button)
        self.nav_layout.addWidget(close_button)
        self.set_corner_button(close_button)
        return minimize_button, maximize_button, close_button

    def set_corner_button(self, button: BaseNavButton) -> None:
        self.corner_button = button
        button.set_corner_radius(self.corner_radius, top_right=True)

    # --- Chrome styling ---

    def set_corner_radius(self, radius: int) -> None:
        self.corner_radius = radius
        self._apply_stylesheet()
        if self.corner_button is not None:
            self.corner_button.set_corner_radius(radius, top_right=True)

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            "WindowHeader {"
            f"   border-top-left-radius: {self.corner_radius}px;"
            f"   border-top-right-radius: {self.corner_radius}px;"
            "}"
        )


if __name__ == '__main__':
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.widget_playground_dialog import WidgetPlaygroundDialog
    from msl_tools.msl.ui.ui_resources import UiResources

    with QtApplicationContext() as context:
        ui_core = UiResources()
        icon = ui_core.iconManager.get_icon("Installer")

        # theme_color = "#0a0a0a"
        theme_color = "#ffffff"

        # overlay = qt.QtGui.QColor(qt.QtGui.QColor(0, 0, 0, 30))
        overlay = qt.QtGui.QColor(qt.QtGui.QColor(255, 255, 255, 25))


        minimize_icon = ui_core.iconManager.get_icon("minimize", sub_folder="window", color=theme_color)
        maximize_icon = ui_core.iconManager.get_icon("maximize", sub_folder="window", color=theme_color)
        restore_icon  = ui_core.iconManager.get_icon("restore",  sub_folder="window", color=theme_color)
        close_idle    = ui_core.iconManager.get_icon("close",    sub_folder="window", color=theme_color)
        close_hover   = ui_core.iconManager.get_icon("close",    sub_folder="window", color="#0a0a0a")

        dialog = WidgetPlaygroundDialog()
        dialog.setWindowTitle("Header demo")

        header_close_only = WindowHeader(title="Close only")
        header_close_only.set_icon(icon)
        header_close_only.set_subtitle("New BRC Queue")
        header_close_only.set_corner_radius(12)
        close_only_btn = header_close_only.add_close_only_controls(lambda: print("close"))
        close_only_btn.set_icon(close_idle, hover_icon=close_hover)
        dialog.add_case("WindowHeader — close only", header_close_only)

        header_close_minimize = WindowHeader(title="Close and minimize")
        header_close_minimize.set_icon(icon)
        header_close_minimize.set_corner_radius(12)
        minimize_btn2, close_btn2 = header_close_minimize.add_close_minimize_controls(minimize_slot=lambda: print("minimize"),
                                                                                      close_slot=lambda: print("close"))
        close_btn2.set_icon(close_idle, hover_icon=close_hover)
        minimize_btn2.set_icon(minimize_icon)
        dialog.add_case("WindowHeader — close minimize", header_close_minimize)

        header_full = WindowHeader(title="Full controls")
        header_full.set_icon(icon)
        header_full.set_corner_radius(12)

        toggle_button = qt.QtWidgets.QPushButton("😅")
        header_full.add_trailing_widget(toggle_button)

        min_btn, max_btn, close_btn = header_full.add_window_controls(
            minimize_slot=lambda: print("minimize"),
            maximize_slot=lambda: (print("maximize"), max_btn.set_maximized(not max_btn._is_maximized)),
            close_slot=lambda: print("close"))

        min_btn.set_icon(minimize_icon)
        max_btn.set_icons(maximize_icon, restore_icon)
        close_btn.set_icon(close_idle, hover_icon=close_hover)

        min_btn.set_hover_color(overlay)
        max_btn.set_hover_color(overlay)
        close_btn.set_hover_color(overlay)  # no-op, ничего не изменит — специально

        dialog.add_case("WindowHeader — full controls", header_full)

        dialog.show()

