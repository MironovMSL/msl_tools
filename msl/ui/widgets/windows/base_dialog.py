import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.windows.frameless_mixin import FramelessWindowMixin


class BaseDialog(qt.QtWidgets.QDialog):
    """Base dialog for the widget library. Provides a content_layout for subclasses
    to extend and an optional bottom button row. Contains no DCC-specific logic —
    parenting to Maya (or any host) is done by the caller when instantiating."""

    def __init__(self, title: str = "", width: int = 480, height: int = 320,
                 show_close_button: bool = True, parent=None):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.resize(width, height)

        self._create_layouts()
        if show_close_button:
            self._build_button_row()

    def _create_layouts(self):
        self.main_layout = qt.QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(2)

        self.content_layout = qt.QtWidgets.QVBoxLayout()
        self.content_layout.setSpacing(2)

        self.main_layout.addLayout(self.content_layout)
        self.main_layout.addStretch()

    def _build_button_row(self) -> None:
        row = qt.QtWidgets.QHBoxLayout()
        row.addStretch()

        self.close_button = qt.QtWidgets.QPushButton("close")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)

        self.main_layout.addLayout(row)

    def add_widget(self, widget: qt.QtWidgets.QWidget) -> None:
        """Adds a widget to the content zone. Primary way for subclasses to populate the dialog."""
        self.content_layout.addWidget(widget)

    def add_separator(self) -> None:
        """Adds a horizontal separator line to the content zone."""
        line = qt.QtWidgets.QFrame()
        line.setFrameShape(qt.QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet("color: gray;")
        self.content_layout.addWidget(line)


class FramelessDialog(FramelessWindowMixin, qt.QtWidgets.QDialog):
    """Frameless dialog with a custom title bar instead of the native one —
    allows embedding widgets into the header (e.g. a theme switcher) alongside
    the centered title and close button. The header is draggable to move the
    window, and the window edges support interactive resizing, since the
    native title bar and frame are gone. Contains no DCC-specific logic —
    parenting to Maya (or any host) is done by the caller when instantiating.
    """

    def __init__(self, *, title: str = "", width: int = 480, height: int = 320,
                 show_close_button: bool = True, parent=None):
        super().__init__(parent)
        self._init_frameless_state()
        self.resize(width, height)
        self._build_base_ui(title, show_close_button)

    def _build_base_ui(self, title: str, show_close_button: bool) -> None:
        self._root_layout = qt.QtWidgets.QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._build_frameless_chrome(self._root_layout, title, show_close_button=show_close_button)

        self.content_layout = qt.QtWidgets.QVBoxLayout()
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(12)
        self._root_layout.addLayout(self.content_layout)

        self._root_layout.addStretch()

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
        window = FramelessDialog(title="BaseDialog")
        window.add_widget(qt.QtWidgets.QPushButton("test"))
        window.add_widget(qt.QtWidgets.QPushButton("test2"))
        window.add_separator()
        window.show()