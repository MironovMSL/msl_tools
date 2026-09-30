# ui/widgets/windows/confirm_dialog.py
from typing import Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class ConfirmDialog(FramelessDialog):
    """Small modal question window in the app's own look — rounded
    frameless chrome, themed like every other window — used instead of
    QMessageBox (whose native frame can't be rounded or themed).

    Layout: a message, optional secondary details (e.g. a list of names),
    and a row of choice buttons. The first choice is the primary one:
    accent-colored (QPushButton#confirmPrimary in ui/theme/widgets.qss) and
    triggered by Enter. Closing the window (×, Esc) means "no choice".

    Usage:
        choice = ConfirmDialog.ask(self, "Copy variables",
                                   "2 variables already exist in Stable.",
                                   details="A, B",
                                   choices=[("replace", "Replace"),
                                            ("skip", "Skip existing"),
                                            ("cancel", "Cancel")])
        # -> "replace" / "skip" / "cancel", or None if closed
    """

    WIDTH = 420
    BUTTON_SPACING = 6

    def __init__(self, title: str, message: str, details: str | None = None,
                 choices: Sequence[tuple[str, str]] = (("ok", "OK"),), parent=None):
        """
        Args:
            title: Window title (chrome header).
            message: Main question text (word-wrapped).
            details: Optional secondary text under it, dimmed.
            choices: (key, label) pairs, left to right; the first is primary.
            parent: Widget the dialog is modal to (centered over its window).
        """
        super().__init__(title=title, width=self.WIDTH, height=10,
                         show_minimize_button=False, show_maximize_button=False,
                         show_theme_toggle=False, parent=parent)
        self._choice: str | None = None
        self._build(message, details, choices)

    def _build(self, message: str, details: str | None, choices: Sequence[tuple[str, str]]) -> None:
        message_label = qt.QtWidgets.QLabel(message)
        message_label.setObjectName("confirmMessage")
        message_label.setWordWrap(True)
        self.add_widget(message_label)

        if details:
            details_label = qt.QtWidgets.QLabel(details)
            details_label.setObjectName("confirmDetails")
            details_label.setWordWrap(True)
            details_label.setTextInteractionFlags(qt.QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            self.add_widget(details_label)

        buttons = qt.QtWidgets.QWidget()
        buttons_layout = qt.QtWidgets.QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 12, 0, 0)
        buttons_layout.setSpacing(self.BUTTON_SPACING)
        buttons_layout.addStretch()
        for index, (key, label) in enumerate(choices):
            button = qt.QtWidgets.QPushButton(label)
            button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            if index == 0:
                button.setProperty("primary", True)  # accent button (base.qss)
                button.setDefault(True)  # Enter
            button.clicked.connect(lambda _=False, k=key: self._choose(k))
            buttons_layout.addWidget(button)
        self.add_widget(buttons)

        self.content_surface.content_layout().setContentsMargins(14, 12, 14, 12)
        self.content_surface.content_layout().setSpacing(6)
        self.adjustSize()

    def _choose(self, key: str) -> None:
        self._choice = key
        self.accept()

    def choice(self) -> str | None:
        """Key of the clicked choice, or None if the window was closed."""
        return self._choice

    @classmethod
    def ask(cls, parent, title: str, message: str, details: str | None = None,
            choices: Sequence[tuple[str, str]] = (("ok", "OK"),)) -> str | None:
        """Shows the dialog modally and returns the chosen key (None if closed)."""
        dialog = cls(title, message, details, choices, parent)
        dialog.exec()
        return dialog.choice()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        playground = ThemedWidgetPlaygroundDialog()
        button = qt.QtWidgets.QPushButton("Ask…")
        button.clicked.connect(lambda: print("choice:", ConfirmDialog.ask(
            playground, "Copy variables",
            '2 of the selected variables already exist in "Stable" with a different value:',
            details="MAYA_SCRIPT_PATH, PYTHONPATH",
            choices=[("replace", "Replace"), ("skip", "Skip existing"), ("cancel", "Cancel")])))
        playground.add_case("ConfirmDialog", button)
        playground.show()
