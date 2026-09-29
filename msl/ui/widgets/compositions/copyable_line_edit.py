# ui/widgets/compositions/copyable_line_edit.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons import GlyphButton


class CopyableLineEdit(qt.QtWidgets.QLineEdit):
    """QLineEdit with a compact "copy" button that appears inside its right
    edge while hovered; clicking it puts the field's current text on the
    clipboard.

    The button's space is reserved permanently (a right text margin), so
    long text never reflows when the button shows up on hover.

    Signals:
        copied(str) — the text that was just copied.
    """

    # Same 20px as the other row buttons (16px icon); fits a 22px-high field.
    BUTTON_SIZE = qt.QtCore.QSize(20, 20)
    BUTTON_INSET = 1

    copied = qt.QtCore.Signal(str)

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._copy_button = GlyphButton("\u29c9", "Copy value", self.BUTTON_SIZE, parent=self)
        self._copy_button.set_icon(UiResources().iconManager.get_icon("copy", sub_folder="actions"))
        self._copy_button.hide()
        self._copy_button.clicked.connect(self._on_copy)
        self.setTextMargins(0, 0, self.BUTTON_SIZE.width() + self.BUTTON_INSET, 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        size = self._copy_button.size()
        self._copy_button.move(self.width() - size.width() - self.BUTTON_INSET,
                               (self.height() - size.height()) // 2)

    # Moving onto the child button doesn't send the line edit a Leave, so
    # these two cover the whole field including the button.
    def enterEvent(self, event) -> None:
        self._copy_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._copy_button.hide()
        super().leaveEvent(event)

    def _on_copy(self) -> None:
        qt.QtGui.QGuiApplication.clipboard().setText(self.text())
        qt.QtWidgets.QToolTip.showText(qt.QtGui.QCursor.pos(), "Copied!", self._copy_button)
        self.copied.emit(self.text())


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        field = CopyableLineEdit("H:/ProjectsDev/Maya/MSL_Scripts")
        field.copied.connect(lambda text: print("copied:", text))
        dialog.add_case("CopyableLineEdit (hover to reveal copy)", field)
        dialog.show()
