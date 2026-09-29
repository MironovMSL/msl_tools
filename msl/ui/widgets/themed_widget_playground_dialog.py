# ui/widgets/themed_widget_playground_dialog.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class ThemedWidgetPlaygroundDialog(FramelessDialog):
    """FramelessDialog-based widget playground with live theme switching,
    via the built-in header toggle — unlike WidgetPlaygroundDialog (two
    static side-by-side instances), add a widget once here and toggle the
    theme to watch it re-theme in place.

    Every added widget is styled by the window stylesheet like any
    FramelessDialog child — plain controls through base.qss, custom-painted
    widgets through their qproperty-* colors in widgets.qss — so the theme
    toggle re-themes them all with nothing to call per widget.

    Dev-only, same spirit as WidgetPlaygroundDialog — not for production.
    """

    def __init__(self, title: str = "themed widget playground", parent=None):
        super().__init__(title=title, width=420, height=360,
                          show_theme_toggle=True, parent=parent)

    def add_case(self, name: str, widget: qt.QtWidgets.QWidget) -> None:
        """Adds a widget with a name label above it."""
        label = qt.QtWidgets.QLabel(name)
        label.setStyleSheet("color: rgb(0, 85, 127); font-size: 11px; font-weight: bold; text-decoration: underline;")

        self.add_widget(label)
        self.add_widget(widget)
        self.add_separator()


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