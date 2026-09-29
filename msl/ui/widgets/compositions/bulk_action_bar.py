# ui/widgets/compositions/bulk_action_bar.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons import GlyphButton


class BulkActionBar(qt.QtWidgets.QWidget):
    """Compact "N selected · [actions] · ×" strip for acting on a multi-row
    selection, Notion-style. Fades in when the count becomes non-zero and
    out when it drops back to zero.

    Extensible and storage-agnostic: it knows nothing about WHAT is
    selected. The owner adds each bulk operation with add_action() and
    connects the returned button's clicked signal; the bar only shows the
    count and hosts the buttons. The trailing "×" (clear selection) is
    built in, since every selection needs a way out.

    The count label (QLabel#bulkCount) is colored by the window stylesheet
    (ui/theme/widgets.qss).

    Signals:
        clear_requested() — the user asked to drop the whole selection.
    """

    FADE_MS = 150
    BUTTON_SIZE = qt.QtCore.QSize(20, 20)

    clear_requested = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._buttons: list[GlyphButton] = []
        self._fade: qt.QtCore.QPropertyAnimation | None = None

        self._count_label = qt.QtWidgets.QLabel()
        self._count_label.setObjectName("bulkCount")
        self._clear_button = GlyphButton("✕", "Clear selection", self.BUTTON_SIZE)
        self._clear_button.set_icon(UiResources().iconManager.get_icon("clear", sub_folder="actions"))
        self._clear_button.clicked.connect(self.clear_requested)

        self._layout = qt.QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._layout.addWidget(self._count_label)
        self._layout.addSpacing(4)
        self._layout.addWidget(self._clear_button)

        self._opacity = qt.QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self.hide()

    # --- public API --------------------------------------------------------

    def add_action(self, glyph: str, tooltip: str) -> GlyphButton:
        """Adds a bulk-operation button (before the built-in clear button)
        and returns it for the owner to connect."""
        button = GlyphButton(glyph, tooltip, self.BUTTON_SIZE)
        self._buttons.append(button)
        self._layout.insertWidget(self._layout.indexOf(self._clear_button) - 1, button)
        return button

    def set_count(self, count: int) -> None:
        was_visible = self._count > 0
        self._count = count
        if count > 0:
            self._count_label.setText(f"{count} selected")
        if (count > 0) != was_visible:
            self._fade_to(count > 0)

    def count(self) -> int:
        return self._count

    # --- internals -----------------------------------------------------------

    def _fade_to(self, visible: bool) -> None:
        if self._fade is not None and qt.shiboken.isValid(self._fade):
            self._fade.stop()
        if visible:
            self.show()
        animation = qt.QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        animation.setDuration(self.FADE_MS)
        animation.setStartValue(self._opacity.opacity())
        animation.setEndValue(1.0 if visible else 0.0)
        if not visible:
            animation.finished.connect(self.hide)
        animation.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade = animation


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        bar = BulkActionBar()
        bar.add_action("\U0001f5d1", "Delete selected").clicked.connect(lambda: print("delete"))
        bar.clear_requested.connect(lambda: bar.set_count(0))
        more = qt.QtWidgets.QPushButton("Select one more")
        more.clicked.connect(lambda: bar.set_count(bar.count() + 1))
        dialog.add_case("BulkActionBar", bar)
        dialog.add_case("", more)
        dialog.show()
