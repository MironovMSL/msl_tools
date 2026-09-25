# ui/widgets/themed_widget_playground_dialog.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class ThemedWidgetPlaygroundDialog(FramelessDialog):
    """FramelessDialog-based widget playground with live theme switching,
    via the built-in header toggle — unlike WidgetPlaygroundDialog (two
    static side-by-side instances), add a widget once here and toggle the
    theme to watch it re-theme in place.

    Every added widget gets the global QSS baseline for free (same as any
    FramelessDialog child) — that alone covers plain controls like
    BaseComboBox. Widgets with their own custom-painted theming (anything
    exposing set_theme(), e.g. ApplicationButton) additionally get
    set_theme() called explicitly on every theme change, same as how
    FramelessDialog re-themes its own chrome buttons.

    Dev-only, same spirit as WidgetPlaygroundDialog — not for production.
    """

    def __init__(self, title: str = "themed widget playground", parent=None):
        # Must exist before super().__init__(): FramelessDialog.__init__()
        # calls self._apply_theme() synchronously at the end of its own
        # construction, and that call reaches our override below, which
        # reads this list.
        self._themed_cases: list[qt.QtWidgets.QWidget] = []
        super().__init__(title=title, width=420, height=360,
                          show_theme_toggle=True, parent=parent)

    def add_case(self, name: str, widget: qt.QtWidgets.QWidget) -> None:
        """Adds a widget with a name label above it. If the widget exposes
        set_theme(), it's tracked and re-themed on every toggle."""
        label = qt.QtWidgets.QLabel(name)
        label.setStyleSheet("color: rgb(0, 85, 127); font-size: 11px; font-weight: bold; text-decoration: underline;")

        self.add_widget(label)
        self.add_widget(widget)
        self.add_separator()

        if hasattr(widget, "set_theme"):
            self._themed_cases.append(widget)

    def _apply_theme(self, theme: Theme) -> None:
        super()._apply_theme(theme)
        for widget in self._themed_cases:
            widget.set_theme(theme)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.atoms.buttons import ApplicationButton
    from msl_tools.msl.ui.widgets.atoms.comboboxes import BaseComboBox
    from msl_tools.msl.tools.desktop.maya_gate.toolbar import MayaGateToolbar

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()

        dialog.add_case("ApplicationButton",
                         ApplicationButton("Maya 2025", r"C:\Windows\System32\notepad.exe"))
        dialog.add_case("BaseComboBox",
                         BaseComboBox(["2024", "2025", "2026"], "2025"))
        dialog.add_case("MayaGateToolbar",
                         MayaGateToolbar(["2024", "2025", "2026"], "2025",
                                          ["Dev", "Stable", "<default>"], "Dev"))

        dialog.show()