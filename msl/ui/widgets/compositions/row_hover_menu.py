# ui/widgets/compositions/row_hover_menu.py
import msl_tools.msl.ui.qt_bindings as qt


class RowHoverMenu(qt.QtWidgets.QWidget):
    """Notion-style hover gutter at the START of a row: a strip of small
    controls (selection checkbox, drag handle, ...) that
    appears while the row is hovered.

    Extensible and content-agnostic: the owner adds whatever widgets it
    needs with add_widget(); this class only decides what is visible.
    A widget is visible while the menu is revealed (row hovered), or at any
    time while it is pinned — e.g. a checkbox stays visible once checked,
    like Notion keeps a selected row's checkbox on screen.

    Hidden widgets keep their space (retainSizeWhenHidden), so the rest of
    the row never shifts when the menu shows or hides.
    """

    SPACING = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._revealed = False
        self._pinned: set = set()
        self._widgets: list = []

        self._layout = qt.QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(self.SPACING)

    def add_widget(self, widget: qt.QtWidgets.QWidget) -> qt.QtWidgets.QWidget:
        """Appends `widget` to the menu (left to right) and returns it.

        The widget never takes keyboard focus: menu widgets hide when the
        pointer leaves the row, and a HIDDEN focused widget hands focus to the
        next one in the chain — the row's line edit, which then selects all of
        its text (clicking the checkbox off and moving away did exactly that).
        """
        widget.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        policy = widget.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        widget.setSizePolicy(policy)
        self._widgets.append(widget)
        self._layout.addWidget(widget, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._sync(widget)
        return widget

    def add_spacing(self, pixels: int) -> None:
        """Fixed gap between menu widgets (e.g. to step over a frame line)."""
        self._layout.addSpacing(pixels)

    def set_revealed(self, revealed: bool) -> None:
        """Shows (row hovered) or hides every non-pinned widget."""
        self._revealed = revealed
        for widget in self._widgets:
            self._sync(widget)

    def set_pinned(self, widget: qt.QtWidgets.QWidget, pinned: bool) -> None:
        """Keeps `widget` visible even while the menu isn't revealed."""
        if pinned:
            self._pinned.add(widget)
        else:
            self._pinned.discard(widget)
        self._sync(widget)

    def _sync(self, widget: qt.QtWidgets.QWidget) -> None:
        widget.setVisible(self._revealed or widget in self._pinned)
