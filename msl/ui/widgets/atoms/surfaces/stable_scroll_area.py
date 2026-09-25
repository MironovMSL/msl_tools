# ui/widgets/atoms/surfaces/stable_scroll_area.py
import msl_tools.msl.ui.qt_bindings as qt


class StableScrollArea(qt.QtWidgets.QScrollArea):
    """Vertical scroll area whose content never shifts sideways when the
    scroll bar appears or disappears.

    A plain QScrollArea with ScrollBarAsNeeded narrows its viewport the
    moment the content outgrows it, so every row inside jumps left by the
    scroll bar's width. Here the scroll bar's column is ALWAYS reserved
    (ScrollBarAlwaysOn keeps QAbstractScrollArea's scroll-bar container
    laid out), while the bar itself is hidden whenever there's nothing to
    scroll — an empty gutter instead of a disabled-looking bar.

    Also transparent by default (no frame, no viewport/content fill), so
    it inherits whatever surface it sits on, and never scrolls sideways.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(qt.QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(qt.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.viewport().setAutoFillBackground(False)

        self.verticalScrollBar().rangeChanged.connect(self._on_range_changed)
        self._on_range_changed(0, self.verticalScrollBar().maximum())

    def setWidget(self, widget: qt.QtWidgets.QWidget) -> None:
        super().setWidget(widget)
        widget.setAutoFillBackground(False)  # QScrollArea.setWidget() forces it on

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        # Hides the bar only, never its container — the container is what
        # reserves the column, and it stays because the policy is AlwaysOn.
        self.verticalScrollBar().setVisible(maximum > 0)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()

        content = qt.QtWidgets.QWidget()
        content_layout = qt.QtWidgets.QVBoxLayout(content)
        for i in range(3):
            content_layout.addWidget(qt.QtWidgets.QLineEdit(f"Row {i}"))

        area = StableScrollArea()
        area.setWidget(content)
        area.setFixedHeight(90)

        add_button = qt.QtWidgets.QPushButton("Add row (scroll bar appears, rows don't move)")
        add_button.clicked.connect(lambda: content_layout.addWidget(qt.QtWidgets.QLineEdit("New row")))

        dialog.add_case("StableScrollArea", area)
        dialog.add_case("", add_button)
        dialog.show()
