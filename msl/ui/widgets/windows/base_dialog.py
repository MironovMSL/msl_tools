import msl_tools.msl.ui.qt_bindings as qt


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
