# ui/widgets/windows/confirm_dialog.py
from typing import Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class ToneBadge(qt.QtWidgets.QWidget):
    """A round badge with a glyph ("?", "!", "×") in the dialog's tone color —
    a tinted disc and the glyph on it. `toneColor` is a Qt property set by
    widgets.qss per the dialog's kind (ConfirmDialog[kind=...])."""

    SIZE = 30
    GLYPHS = {"question": "?", "warning": "!", "danger": "\u00d7"}
    GLYPH_SCALE = {"danger": 0.8}  # "×" sits small in its em box; the rest use 0.55

    toneColor = color_property("_tone_color")

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._glyph = self.GLYPHS.get(kind, "?")
        self._glyph_scale = self.GLYPH_SCALE.get(kind, 0.55)
        self._tone_color = qt.QtGui.QColor(ThemeRegistry.fallback().accent)  # until QSS applies
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        disc = qt.QtGui.QColor(self._tone_color)
        disc.setAlphaF(0.16)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(disc)
        painter.drawEllipse(qt.QtCore.QRectF(self.rect()))
        font = qt.QtGui.QFont(self.font())
        font.setBold(True)
        font.setPixelSize(round(self.SIZE * self._glyph_scale))
        # Centered by the glyph's INK, not its text box: drawText(AlignCenter)
        # centers the line box, which leaves "×" (and "!") visibly off-center.
        path = qt.QtGui.QPainterPath()
        path.addText(0, 0, font, self._glyph)
        ink = path.boundingRect()
        path.translate(self.width() / 2 - ink.center().x(), self.height() / 2 - ink.center().y())
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._tone_color)
        painter.drawPath(path)
        painter.end()


class ConfirmDialog(FramelessDialog):
    """Small modal question window in the app's own look — rounded
    frameless chrome, themed like every other window — used instead of
    QMessageBox (whose native frame can't be rounded or themed).

    Layout: a tone badge (ToneBadge) left of the message, optional secondary
    details under it (e.g. a list of names), and a row of choice buttons.
    The first choice is the primary one (QPushButton[primary="true"],
    base.qss) and is triggered by Enter; Esc / × mean "no choice".

    `kind` sets the tone: "question" (accent, default), "warning" (the
    action overwrites something), "danger" (irreversible — the primary
    button turns red, QPushButton[danger="true"]). Colors: widgets.qss.
    In a "danger" dialog Enter triggers the LAST choice instead (by
    convention the cancel one), so a stray Enter never destroys anything —
    the destructive button has to be clicked (or tabbed to).

    While the dialog is open, a frameless parent window is blurred behind
    it (FramelessWindowMixin.set_blurred), keeping the eye on the question.

    Usage:
        choice = ConfirmDialog.ask(self, "Copy variables",
                                   "2 variables already exist in Stable.",
                                   details="A, B",
                                   choices=[("replace", "Replace"),
                                            ("skip", "Skip existing"),
                                            ("cancel", "Cancel")],
                                   kind="warning")
        # -> "replace" / "skip" / "cancel", or None if closed
    """

    WIDTH = 420
    BUTTON_SPACING = 6
    KINDS = ("question", "warning", "danger")

    def __init__(self, title: str, message: str, details: str | None = None,
                 choices: Sequence[tuple[str, str]] = (("ok", "OK"),), kind: str = "question",
                 parent=None):
        """
        Args:
            title: Window title (chrome header).
            message: Main question text (word-wrapped).
            details: Optional secondary text under it, dimmed.
            choices: (key, label) pairs, left to right; the first is primary.
            kind: "question", "warning" or "danger" (see the class docstring).
            parent: Widget the dialog is modal to (centered over its window).
        """
        self._kind = kind if kind in self.KINDS else "question"
        super().__init__(title=title, width=self.WIDTH, height=10,
                         show_minimize_button=False, show_maximize_button=False,
                         show_theme_toggle=False, parent=parent)
        self.setProperty("kind", self._kind)  # widgets.qss: badge tone per kind
        self._choice: str | None = None
        self._build(message, details, choices)

    def _build(self, message: str, details: str | None, choices: Sequence[tuple[str, str]]) -> None:
        badge = ToneBadge(self._kind)

        message_label = qt.QtWidgets.QLabel(message)
        message_label.setObjectName("confirmMessage")
        message_label.setWordWrap(True)

        text = qt.QtWidgets.QWidget()
        text_layout = qt.QtWidgets.QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(message_label)
        if details:
            details_label = qt.QtWidgets.QLabel(details)
            details_label.setObjectName("confirmDetails")
            details_label.setWordWrap(True)
            details_label.setTextInteractionFlags(qt.QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            text_layout.addWidget(details_label)

        body = qt.QtWidgets.QWidget()
        body_layout = qt.QtWidgets.QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        body_layout.addWidget(badge, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        body_layout.addWidget(text, 1)
        self.add_widget(body)

        buttons = qt.QtWidgets.QWidget()
        buttons_layout = qt.QtWidgets.QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 14, 0, 0)
        buttons_layout.setSpacing(self.BUTTON_SPACING)
        buttons_layout.addStretch()
        choice_buttons: list[qt.QtWidgets.QPushButton] = []
        for index, (key, label) in enumerate(choices):
            button = qt.QtWidgets.QPushButton(label)
            button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            if index == 0:
                button.setProperty("primary", True)  # accent button (base.qss)
                button.setProperty("danger", self._kind == "danger")  # red instead
            button.clicked.connect(lambda _=False, k=key: self._choose(k))
            buttons_layout.addWidget(button)
            choice_buttons.append(button)
        self.add_widget(buttons)

        # Enter: the primary choice — except in a "danger" dialog, where it is the
        # last (cancel) one. Focus goes there too: a QDialog's Enter follows the
        # focused button, and the first button would otherwise take the focus.
        enter_button = choice_buttons[-1] if self._kind == "danger" else choice_buttons[0]
        enter_button.setDefault(True)
        enter_button.setFocus()

        self.content_surface.content_layout().setContentsMargins(16, 14, 16, 14)
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
            choices: Sequence[tuple[str, str]] = (("ok", "OK"),), kind: str = "question") -> str | None:
        """Shows the dialog modally and returns the chosen key (None if closed)."""
        dialog = cls(title, message, details, choices, kind, parent)
        window = parent.window() if parent is not None else None
        blur = getattr(window, "set_blurred", None)
        if blur is not None:
            blur(True)
        try:
            dialog.exec()
        finally:
            if blur is not None:
                blur(False)
        return dialog.choice()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        playground = ThemedWidgetPlaygroundDialog()
        for kind in ConfirmDialog.KINDS:
            button = qt.QtWidgets.QPushButton(f"Ask ({kind})…")
            button.clicked.connect(lambda _=False, k=kind: print("choice:", ConfirmDialog.ask(
                playground, "Copy variables",
                '2 of the selected variables already exist in "Stable" with a different value:',
                details="MAYA_SCRIPT_PATH, PYTHONPATH",
                choices=[("replace", "Replace"), ("skip", "Skip existing"), ("cancel", "Cancel")], kind=k)))
            playground.add_case(f"ConfirmDialog ({kind})", button)
        playground.show()
