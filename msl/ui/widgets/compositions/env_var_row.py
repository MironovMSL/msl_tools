# ui/widgets/compositions/env_var_row.py
import msl_tools.msl.ui.qt_bindings as qt


class EnvVarRow(qt.QtWidgets.QWidget):
    """One row in a reorderable key/value list: name label, editable value,
    browse (...) button, hover-revealed row controls, and an optional drag
    handle for DraggableList.

    Storage-agnostic — never touches config. The original (MSL_MayaGate's
    VariablePathWgt) wrote straight to a global json_config singleton from
    on_value_changed(); that's gone, replaced by the value_changed signal.
    The owner decides what, if anything, to persist.

    Row controls (copy name, move up/down, delete) live INSIDE the row and
    appear while the mouse is anywhere over it (label, line edit, buttons).
    The original used shared floating top-level panels positioned next to
    the row — they were triggered only by the name label and were placed
    past the row's right edge, i.e. outside the host window. Hidden
    controls keep their space reserved (retainSizeWhenHidden), so the line
    edit never changes width on hover.

    Icons: plain characters ("⧉", "˄", "˅", "×") stand in for SVG icons —
    msl_tools' asset bundle doesn't have matching assets yet. Swap in
    IconManager-resolved icons once they exist.

    Signals:
        value_changed(str, str) — (item_id, new_value)
        remove_requested(str) / move_up_requested(str) / move_down_requested(str)
    """

    HEIGHT = 25
    LABEL_MIN_WIDTH = 150
    BUTTON_SIZE = qt.QtCore.QSize(22, 22)

    value_changed = qt.QtCore.Signal(str, str)
    remove_requested = qt.QtCore.Signal(str)
    move_up_requested = qt.QtCore.Signal(str)
    move_down_requested = qt.QtCore.Signal(str)

    def __init__(self, item_id: str, value: str, draggable: bool = False, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.value = value
        self.drag_handle: qt.QtWidgets.QPushButton | None = None

        self.setFixedHeight(self.HEIGHT)
        self._build_widgets(draggable)
        self._build_layout(draggable)
        self._build_connections()
        self._set_controls_visible(False)

    def _build_widgets(self, draggable: bool) -> None:
        self.name_label = qt.QtWidgets.QLabel(self.item_id)
        self.name_label.setMinimumWidth(self.LABEL_MIN_WIDTH)
        self.name_label.setTextInteractionFlags(qt.QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        self.copy_button = self._make_button("\u29c9", "Copy variable name")
        self.value_field = qt.QtWidgets.QLineEdit(self.value)
        self.browse_button = self._make_button("...", "Browse for a folder", flat=False)

        self.up_button = self._make_button("\u02c4", "Move up")
        self.down_button = self._make_button("\u02c5", "Move down")
        self.delete_button = self._make_button("\u00d7", "Remove variable")

        self._hover_controls = (self.copy_button, self.up_button, self.down_button, self.delete_button)
        for button in self._hover_controls:
            policy = button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            button.setSizePolicy(policy)

        if draggable:
            self.drag_handle = self._make_button("\u22ee\u22ee", "Drag to reorder")  # vertical-dots "grip"

    def _make_button(self, text: str, tooltip: str, flat: bool = True) -> qt.QtWidgets.QPushButton:
        button = qt.QtWidgets.QPushButton(text)
        button.setFixedSize(self.BUTTON_SIZE)
        button.setFlat(flat)
        button.setToolTip(tooltip)
        button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        return button

    def _build_layout(self, draggable: bool) -> None:
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)

        layout.addWidget(self.name_label)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.value_field, 1)
        layout.addWidget(self.browse_button)
        layout.addWidget(self.up_button)
        layout.addWidget(self.down_button)
        layout.addWidget(self.delete_button)
        if draggable:
            layout.addWidget(self.drag_handle)

    def _build_connections(self) -> None:
        self.value_field.textChanged.connect(self._on_value_changed)
        self.browse_button.clicked.connect(self._on_browse)
        self.copy_button.clicked.connect(self._on_copy)
        self.up_button.clicked.connect(lambda: self.move_up_requested.emit(self.item_id))
        self.down_button.clicked.connect(lambda: self.move_down_requested.emit(self.item_id))
        self.delete_button.clicked.connect(lambda: self.remove_requested.emit(self.item_id))

    def _on_value_changed(self, text: str) -> None:
        self.value = text
        self.value_changed.emit(self.item_id, text)

    def _on_browse(self) -> None:
        directory = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "Select a Folder", "")
        if directory:
            self.value_field.setText(directory)

    def _on_copy(self) -> None:
        qt.QtGui.QGuiApplication.clipboard().setText(self.item_id)
        qt.QtWidgets.QToolTip.showText(qt.QtGui.QCursor.pos(), "Copied!", self.copy_button)

    # --- hover-revealed controls -----------------------------------------
    # Enter/Leave on the row itself cover all of its children: Qt does not send
    # the row a Leave when the cursor moves onto its own line edit or buttons.

    def enterEvent(self, event) -> None:
        self._set_controls_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_controls_visible(False)
        super().leaveEvent(event)

    def _set_controls_visible(self, visible: bool) -> None:
        for button in self._hover_controls:
            button.setVisible(visible)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog
    from msl_tools.msl.ui.widgets.compositions.draggable_list import DraggableList

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()

        drag_list = DraggableList(draggable=True)
        for name, value in [("MAYA_APP_DIR", "H:/ProjectsDev/Maya/MSL_Prefs"),
                             ("PYTHONPATH", "H:/ProjectsDev/Maya/MSL_Scripts"),
                             ("TEMP", "H:/ProjectsDev/Temp")]:
            row = EnvVarRow(name, value, draggable=True)
            row.value_changed.connect(lambda i, v: print("changed:", i, "=", v))
            drag_list.append_widget(name, row)

        drag_list.order_changed.connect(lambda order: print("order:", order))
        drag_list.item_removed.connect(lambda i: print("removed:", i))

        dialog.add_case("EnvVarRow x3 in a DraggableList", drag_list)
        dialog.show()
