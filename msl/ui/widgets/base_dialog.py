import msl_tools.msl.ui.qt_bindings as qt


class BaseDialog(qt.QtWidgets.QDialog):
    """Base dialog for the widget library. Provides a content_layout for subclasses
    to extend and an optional bottom button row. Contains no DCC-specific logic —
    parenting to Maya (or any host) is done by the caller when instantiating."""

    def __init__(self, title:str = "", width:int = 480, height:int = 320, parent = None):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.resize(width, height)

        self.create_layouts()

    def create_layouts(self):
        self.main_layout = qt.QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.setSpacing(2)

        self.content_layout = qt.QtWidgets.QVBoxLayout()
        self.content_layout.setSpacing(2)

        self.main_layout.addLayout(self.content_layout)
        self.main_layout.addStretch()

    def add_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        """Adds a widget to the content zone. Primary way for subclasses to populate the dialog."""
        self.content_layout.addWidget(widget)

    def add_separator(self) -> None:
        """Adds a horizontal separator line to the content zone."""
        line = qt.QtWidgets.QFrame()
        line.setFrameShape(qt.QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet("color: gray;")
        self.content_layout.addWidget(line)


if __name__ == '__main__':

    from msl_tools.msl.ui.app.application_context import QtApplicationContext


    with QtApplicationContext():
        window = BaseDialog(title="BaseDialog")
        window.add_widget(qt.QtWidgets.QPushButton("test"))
        window.add_widget(qt.QtWidgets.QPushButton("test2"))
        window.add_separator()
        window.show()