# ui/widgets/compositions/chip_bar.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.widgets.atoms.layouts import FlowLayout


class _NameField(qt.QtWidgets.QLineEdit):
    """Private: a one-line field that asks for a name in place — Enter takes
    it (returnPressed), Esc or clicking elsewhere gives up (cancelled)."""

    cancelled = qt.QtCore.Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == qt.QtCore.Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.cancelled.emit()


class ChipBar(qt.QtWidgets.QWidget):
    """A row of small pill buttons ("chips") that wraps to the next line when
    it runs out of width. Two uses:

    - a picker (checkable=True): one chip is the current one — for a
      handful to a dozen options that don't fit a SegmentedControl;
    - a shelf of saved things (presets, snippets): a click uses one; with
      `add_text` an "+ …" link at the end asks for a name IN PLACE (Enter
      takes it, Esc gives up — no dialog) and add_requested follows; a
      right click on a removable chip offers "Remove".

        bar = ChipBar(add_text="+ Save preset", name_placeholder="Preset name, then Enter")
        bar.set_chips([("web", "For the web", "720p, small"), ...], removable={"web"})

    The bar only shows and reports; what a chip means is the owner's.
    Looks: ui/theme/widgets.qss (`ChipBar QPushButton#chip`, `#chipAdd`).

    Signals:
        clicked(str) — a chip's key.
        add_requested(str) — the name typed after the "+ …" link.
        remove_requested(str) — "Remove" was picked for that chip's key.
    """

    clicked = qt.QtCore.Signal(str)
    add_requested = qt.QtCore.Signal(str)
    remove_requested = qt.QtCore.Signal(str)

    def __init__(self, add_text: str = "", name_placeholder: str = "", checkable: bool = False, parent=None):
        super().__init__(parent)
        self._checkable = checkable
        self._chips: dict[str, qt.QtWidgets.QPushButton] = {}
        self._removable: set[str] = set()
        self._current = ""
        self._layout = FlowLayout(self, spacing=6)

        self._add_button = qt.QtWidgets.QPushButton(add_text, self)
        self._add_button.setObjectName("chipAdd")
        self._add_button.setFlat(True)
        self._add_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._add_button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._name_field = _NameField(self)
        self._name_field.setPlaceholderText(name_placeholder)
        self._name_field.setFixedWidth(190)
        self._layout.addWidget(self._add_button)
        self._layout.addWidget(self._name_field)
        self._name_field.hide()
        if not add_text:
            self._add_button.hide()
        self._add_button.clicked.connect(self.ask_name)
        self._name_field.returnPressed.connect(self._on_named)
        self._name_field.cancelled.connect(self._name_field.hide)

    # --- chips ------------------------------------------------------------------------

    def set_chips(self, chips: list, removable=()) -> None:
        """`chips`: (key, text, tooltip) tuples, shown in that order; `removable`: keys with a "Remove" menu."""
        for chip in self._chips.values():
            self._layout.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        self._chips = {}
        self._removable = set(removable)
        for widget in (self._add_button, self._name_field):
            self._layout.removeWidget(widget)
        for key, text, tooltip in chips:
            chip = qt.QtWidgets.QPushButton(text, self)
            chip.setObjectName("chip")
            chip.setToolTip(tooltip)
            chip.setCheckable(self._checkable)
            chip.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            chip.clicked.connect(lambda _checked=False, key=key: self._on_chip(key))
            if key in self._removable:
                chip.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
                chip.customContextMenuRequested.connect(
                    lambda position, key=key, chip=chip: self._on_chip_menu(key, chip.mapToGlobal(position)))
            self._chips[key] = chip
            self._layout.addWidget(chip)
            chip.show()
        for widget in (self._add_button, self._name_field):
            self._layout.addWidget(widget)
        if self._checkable:
            if self._current not in self._chips:
                self._current = next(iter(self._chips), "")
            self._sync_checked()
        self._layout.invalidate()

    def keys(self) -> list[str]:
        return list(self._chips)

    def current(self) -> str:
        """The picked chip's key (a checkable bar; "" when it has no chips)."""
        return self._current

    def set_current(self, key: str) -> None:
        """Picks a chip without emitting clicked."""
        if key in self._chips:
            self._current = key
            self._sync_checked()

    def _sync_checked(self) -> None:
        for key, chip in self._chips.items():
            chip.setChecked(key == self._current)

    def _on_chip(self, key: str) -> None:
        if self._checkable:
            self._current = key
            self._sync_checked()
        self.clicked.emit(key)

    def _on_chip_menu(self, key: str, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.addAction("Remove").triggered.connect(lambda: self.remove_requested.emit(key))
        self._menu = menu  # for tests; the menu deletes itself on close
        menu.popup(position)

    # --- adding one ---------------------------------------------------------------------

    def ask_name(self, suggestion: str = "") -> None:
        """Shows the name field (what the "+ …" link does)."""
        self._name_field.setText(suggestion if isinstance(suggestion, str) else "")
        self._name_field.show()
        self._layout.invalidate()
        self._name_field.setFocus()
        self._name_field.selectAll()

    def _on_named(self) -> None:
        name = self._name_field.text().strip()
        self._name_field.hide()
        if name:
            self.add_requested.emit(name)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        picker = ChipBar(checkable=True)
        picker.set_chips([(name, name, "") for name in ("Make smaller", "Trim", "Stamp", "Sound", "GIF", "Adjust")])
        shelf = ChipBar(add_text="+ Save preset", name_placeholder="Preset name, then Enter")
        shelf.set_chips([("a", "Messenger · 10 MB", ""), ("b", "Preview 720p", "")], removable={"a", "b"})
        dialog.add_case("ChipBar (picker)", picker)
        dialog.add_case("ChipBar (shelf)", shelf)
        dialog.show()
