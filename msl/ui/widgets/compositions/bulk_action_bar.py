# ui/widgets/compositions/bulk_action_bar.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons import GlyphButton


class BulkActionBar(qt.QtWidgets.QWidget):
    """Compact strip for acting on a multi-row selection, Notion-style:

        ( 2 of 4 selected | select-all  [actions]  | × )

    drawn as one accent-tinted pill so it reads as a separate "selection
    mode" inside whatever header hosts it. Fades in when the count becomes
    non-zero and out when it drops back to zero.

    Extensible and storage-agnostic: it knows nothing about WHAT is
    selected. The owner adds each bulk operation with add_action() and
    connects the returned button's clicked signal; the bar shows the count
    and hosts the buttons. Built in, since every selection needs them:
    "select all" (hidden once everything is selected, or when the owner
    gives no total) and the trailing "×" (clear selection).

    Styling (ui/theme/widgets.qss): the pill = qproperty pillColor /
    pillBorderColor; the count label = QLabel#bulkCount; dividers =
    QWidget#bulkDivider; a destructive action (add_action(danger=True))
    is a GlyphButton[danger="true"] — red on hover.

    Signals:
        clear_requested() — the user asked to drop the whole selection.
        select_all_requested() — the user asked to select every row.
    """

    FADE_MS = 150
    HEIGHT = 22
    BUTTON_SIZE = qt.QtCore.QSize(20, 20)

    clear_requested = qt.QtCore.Signal()
    select_all_requested = qt.QtCore.Signal()

    pillColor = color_property("_pill_color")
    pillBorderColor = color_property("_pill_border_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._total: int | None = None
        self._buttons: list[GlyphButton] = []
        self._fade: qt.QtCore.QPropertyAnimation | None = None
        self._pill_color = qt.QtGui.QColor(0, 0, 0, 0)         # until QSS applies
        self._pill_border_color = qt.QtGui.QColor(0, 0, 0, 0)
        self.setFixedHeight(self.HEIGHT)

        icons = UiResources().iconManager
        self._count_label = qt.QtWidgets.QLabel()
        self._count_label.setObjectName("bulkCount")
        self._select_all_button = GlyphButton("\u2713", "Select all", self.BUTTON_SIZE)
        self._select_all_button.set_icon(icons.get_icon("select_all", sub_folder="actions"))
        self._select_all_button.clicked.connect(self.select_all_requested)
        self._clear_button = GlyphButton("\u2715", "Clear selection", self.BUTTON_SIZE)
        self._clear_button.set_icon(icons.get_icon("clear", sub_folder="actions"))
        self._clear_button.clicked.connect(self.clear_requested)
        self._clear_divider = self._divider()

        self._layout = qt.QtWidgets.QHBoxLayout(self)
        # Right margin: the last button's (square-ish) hover highlight must stay
        # inside the pill's round end — at 2px its corners poked out of it.
        self._layout.setContentsMargins(9, 1, 6, 1)
        self._layout.setSpacing(2)
        self._layout.addWidget(self._count_label)
        self._layout.addSpacing(4)
        self._layout.addWidget(self._divider())
        self._layout.addWidget(self._select_all_button)
        self._layout.addWidget(self._clear_divider)
        self._layout.addWidget(self._clear_button)

        self._opacity = qt.QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self.hide()

    @staticmethod
    def _divider() -> qt.QtWidgets.QWidget:
        divider = qt.QtWidgets.QWidget()
        divider.setObjectName("bulkDivider")
        divider.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        divider.setFixedSize(1, 12)
        return divider

    # --- public API --------------------------------------------------------

    def add_action(self, glyph: str, tooltip: str, danger: bool = False) -> GlyphButton:
        """Adds a bulk-operation button (before the clear button's divider)
        and returns it for the owner to connect. `danger` marks a
        destructive operation: the button turns red on hover."""
        button = GlyphButton(glyph, tooltip, self.BUTTON_SIZE)
        if danger:
            button.setProperty("danger", True)  # widgets.qss: GlyphButton[danger="true"]
        self._buttons.append(button)
        self._layout.insertWidget(self._layout.indexOf(self._clear_divider), button)
        return button

    def set_count(self, count: int, total: int | None = None) -> None:
        """`count` rows selected, out of `total` if the owner knows it (then
        the label reads "2 of 4 selected" and "select all" hides once
        everything is selected)."""
        was_visible = self._count > 0
        self._count = count
        self._total = total
        if count > 0:
            self._count_label.setText(f"{count} selected" if total is None else f"{count} of {total} selected")
        self._select_all_button.setVisible(total is not None and count < total)
        if (count > 0) != was_visible:
            self._fade_to(count > 0)

    def count(self) -> int:
        return self._count

    # --- internals -----------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtGui.QPen(self._pill_border_color, 1))
        painter.setBrush(self._pill_color)
        rect = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.end()

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
        TOTAL = 4
        bar = BulkActionBar()
        bar.add_action("\U0001f5d1", "Delete selected", danger=True).clicked.connect(lambda: print("delete"))
        bar.clear_requested.connect(lambda: bar.set_count(0, TOTAL))
        bar.select_all_requested.connect(lambda: bar.set_count(TOTAL, TOTAL))
        more = qt.QtWidgets.QPushButton("Select one more")
        more.clicked.connect(lambda: bar.set_count(min(bar.count() + 1, TOTAL), TOTAL))
        dialog.add_case("BulkActionBar", bar)
        dialog.add_case("", more)
        dialog.show()
