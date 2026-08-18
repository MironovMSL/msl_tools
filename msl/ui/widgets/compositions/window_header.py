import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.header.base_badge_label import BaseBadgeLabel
from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton
from msl_tools.msl.ui.widgets.atoms.header.close_nav_button import CloseNavButton
from msl_tools.msl.ui.widgets.atoms.header.minimize_nav_button import MinimizeNavButton
from msl_tools.msl.ui.widgets.atoms.header.maximize_nav_button import MaximizeNavButton


class WindowHeader(qt.QtWidgets.QWidget):
    """Title bar row for frameless windows.

    Layout, left to right:
        leading zone   — icon, title, badge, subtitle, any add_leading_widget() extras
        (stretch)
        trailing zone  — arbitrary widgets added via add_trailing_widget()
                          (e.g. a future theme toggle, search icon)
        nav zone       — window controls (close-only, or minimize/maximize/close),
                          flush against the right edge with zero margin/spacing

    Purely a layout/content component — dragging and resizing are handled by
    FramelessWindowMixin, which hosts this widget and reads its geometry for
    hit-testing. This widget has no opinion on theme; colors are placeholders
    until Theme wiring lands.
    """

    def __init__(self, title: str = "", height: int = 36, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)

        self._corner_radius = 0
        self._corner_button: BaseNavButton | None = None

        self._layout = qt.QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(8, 0, 0, 0)
        self._layout.setSpacing(6)

        # --- Leading zone ---

        self.leading_layout = qt.QtWidgets.QHBoxLayout()
        self.leading_layout.setSpacing(6)

        self._icon_label = qt.QtWidgets.QLabel()
        self._icon_label.setFixedSize(16, 16)
        self._icon_label.setScaledContents(True)
        self._icon_label.hide()
        self.leading_layout.addWidget(self._icon_label)

        self.title_label = qt.QtWidgets.QLabel(title)
        # self.title_label.setStyleSheet("color: white; font-weight: 600; font-size: 12px;")
        self.leading_layout.addWidget(self.title_label)

        self._badge_label = BaseBadgeLabel()
        self._badge_label.hide()
        self.leading_layout.addWidget(self._badge_label)

        self._subtitle_label = qt.QtWidgets.QLabel()
        self._subtitle_label.setStyleSheet("color: #8a8a8a; font-size: 12px;")
        self._subtitle_label.hide()
        self.leading_layout.addWidget(self._subtitle_label)

        # --- Trailing zone (regular widgets, normal spacing) ---

        self.trailing_layout = qt.QtWidgets.QHBoxLayout()
        self.trailing_layout.setSpacing(6)

        # --- Nav zone (window controls, flush to the edge, zero spacing) ---

        self._nav_layout = qt.QtWidgets.QHBoxLayout()
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(0)

        self._layout.addLayout(self.leading_layout)
        self._layout.addStretch()
        self._layout.addLayout(self.trailing_layout)
        self._layout.addLayout(self._nav_layout)

        self.set_corner_radius(0)

    # --- Leading zone content ---

    def set_icon(self, icon: qt.QtGui.QIcon) -> None:
        self._icon_label.setPixmap(icon.pixmap(16, 16))
        self._icon_label.show()

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_badge(self, text: str | None) -> None:
        if not text:
            self._badge_label.hide()
            return
        self._badge_label.setText(text)
        self._badge_label.show()

    def set_subtitle(self, text: str | None) -> None:
        if not text:
            self._subtitle_label.hide()
            return
        self._subtitle_label.setText(f"|  {text}")
        self._subtitle_label.show()

    # --- Extension points ---

    def add_leading_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        self.leading_layout.addWidget(widget)

    def add_trailing_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        self.trailing_layout.addWidget(widget)

    # --- Nav (window control) button sets ---

    def add_close_only_controls(self, close_slot) -> CloseNavButton:
        button = CloseNavButton()
        button.clicked.connect(close_slot)
        self._nav_layout.addWidget(button)
        self._set_corner_button(button)
        return button

    def add_window_controls(self, minimize_slot, maximize_slot, close_slot
                             ) -> tuple[MinimizeNavButton, MaximizeNavButton, CloseNavButton]:
        minimize_button = MinimizeNavButton()
        minimize_button.clicked.connect(minimize_slot)

        maximize_button = MaximizeNavButton()
        maximize_button.clicked.connect(maximize_slot)

        close_button = CloseNavButton()
        close_button.clicked.connect(close_slot)

        self._nav_layout.addWidget(minimize_button)
        self._nav_layout.addWidget(maximize_button)
        self._nav_layout.addWidget(close_button)
        self._set_corner_button(close_button)

        return minimize_button, maximize_button, close_button

    def _set_corner_button(self, button: BaseNavButton) -> None:
        """Tracks which nav button sits flush against the window's top-right
        corner, so it can be told to round itself when the header's corner
        radius changes (see set_corner_radius)."""
        self._corner_button = button
        button.set_corner_radius(self._corner_radius, top_right=True)

    # --- Chrome styling, driven by the owning window ---

    def set_corner_radius(self, radius: int) -> None:
        self._corner_radius = radius
        self.setStyleSheet(
            "WindowHeader {"
            "    background-color: #3f4652;"
            # "    background-color: #EDF1F5;"
            f"   border-top-left-radius: {radius}px;"
            f"   border-top-right-radius: {radius}px;"
            "}"
        )
        if self._corner_button is not None:
            self._corner_button.set_corner_radius(radius, top_right=True)


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
        # overlay.setAlpha(28)

        minimize_icon = ui_core.iconManager.get_icon("minimize", sub_folder="window", color=theme_color)
        maximize_icon = ui_core.iconManager.get_icon("maximize", sub_folder="window", color=theme_color)
        restore_icon  = ui_core.iconManager.get_icon("restore",  sub_folder="window", color=theme_color)
        close_idle    = ui_core.iconManager.get_icon("close",    sub_folder="window", color=theme_color)
        close_hover   = ui_core.iconManager.get_icon("close",    sub_folder="window", color="#0a0a0a")

        dialog = WidgetPlaygroundDialog()
        dialog.setWindowTitle("Header demo")

        header_close_only = WindowHeader(title="Close only")
        header_close_only.set_icon(icon)
        header_close_only.set_badge("TRIAL")
        header_close_only.set_subtitle("New BRC Queue")
        header_close_only.set_corner_radius(12)
        close_only_btn = header_close_only.add_close_only_controls(lambda: print("close"))
        close_only_btn.set_icon(close_idle, hover_icon=close_hover)
        dialog.add_case("WindowHeader — close only", header_close_only)

        header_full = WindowHeader(title="Full controls")
        header_full.set_icon(icon)
        header_full.set_corner_radius(12)

        toggle_button = qt.QtWidgets.QPushButton("😅")
        header_full.add_trailing_widget(toggle_button)

        min_btn, max_btn, close_btn = header_full.add_window_controls(
            minimize_slot=lambda: print("minimize"),
            maximize_slot=lambda: (print("maximize"), max_btn.set_maximized(not max_btn._is_maximized)),
            close_slot=lambda: print("close"),
        )
        min_btn.set_icon(minimize_icon)
        max_btn.set_icons(maximize_icon, restore_icon)
        close_btn.set_icon(close_idle, hover_icon=close_hover)

        min_btn.set_hover_color(overlay)
        max_btn.set_hover_color(overlay)
        close_btn.set_hover_color(overlay)  # no-op, ничего не изменит — специально

        dialog.add_case("WindowHeader — full controls", header_full)

        dialog.show()

