import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.base_dialog import BaseDialog


class WidgetPlaygroundDialog(BaseDialog):
    """Dialog for quickly visually testing library widgets in isolation.
    Not intended for production use — meant for development, to try out
    a new widget without building a full tool around it."""

    def __init__(self, parent=None):
        super().__init__(title="widget playground", width=400, height=300, parent=parent)

    def add_case(self, name: str, widget: qt.QtWidgets.QWidget) -> None:
        """Adds a widget with a name label above it, for context in the test window."""
        label = qt.QtWidgets.QLabel(name)
        label.setStyleSheet("color: rgb(0, 85, 127); font-size: 11px; font-weight: bold; text-decoration: underline;")

        self.add_widget(label)
        self.add_widget(widget)
        self.add_separator()



if __name__ == '__main__':

    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        window = WidgetPlaygroundDialog()
        btn    = qt.QtWidgets.QPushButton("btn")
        btn2   = qt.QtWidgets.QPushButton("btn2")

        window.add_case("Button1", btn)
        window.add_case("Button2", btn2)
        window.show()