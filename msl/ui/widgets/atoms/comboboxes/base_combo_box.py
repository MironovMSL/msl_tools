# ui/widgets/atoms/comboboxes/base_combo_box.py
import msl_tools.msl.ui.qt_bindings as qt


class BaseComboBox(qt.QtWidgets.QComboBox):
    """Thin QComboBox atom: fixed item list, tracks its own current
    selection, and can ignore scroll-wheel input.

    No theming of its own — QComboBox is a plain control styled by the
    window's global stylesheet (StylesheetBuilder), the same way
    QPushButton/QLineEdit are. Only widgets with state-driven custom
    painting (BaseCheckbox, BaseToggle) carry their own set_theme().

    Wheel-disable exists because a combo box sitting in a scrollable
    page silently changes its value when the user scrolls past it —
    disabling the wheel here makes that opt-in per instance.
    """

    def __init__(self, items: list[str], current_item: str, enable_wheel: bool = True, parent=None):
        super().__init__(parent)
        self.items = items
        self.current_item = current_item

        self.addItems(self.items)
        self.setCurrentText(self.current_item)
        self.currentTextChanged.connect(self._on_current_text_changed)

        if not enable_wheel:
            self.wheelEvent = lambda event: event.ignore()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} items={self.items} current='{self.current_item}'>"

    def _on_current_text_changed(self, text: str) -> None:
        self.current_item = text


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        dialog.add_case("BaseComboBox", BaseComboBox(["2024", "2025", "2026"], "2025"))
        dialog.show()