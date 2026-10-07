# tools/maya/rename/dialogs.py
"""The rename tool's two small settings windows: how a side is told (lf / rt / mid) and which
suffix each kind of object gets."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.tools.maya.rename.buttons import maya_type_icon
from msl_tools.msl.ui.widgets.atoms.scrollbars.slim_scroll_bar import SlimScrollBar
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class NumberField(qt.QtWidgets.QLineEdit):
    """A small whole-number field: Up / Down and the mouse wheel step it by one (Shift: ten)."""

    def __init__(self, value: int = 0, minimum: int = -99999, maximum: int = 99999, width: int = 44, parent=None):
        super().__init__(str(value), parent)
        self._minimum, self._maximum = minimum, maximum
        self.setValidator(qt.QtGui.QIntValidator(minimum, maximum, self))
        self.setFixedWidth(width)
        self.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)

    def value(self, fallback: int = 0) -> int:
        try:
            return max(self._minimum, min(self._maximum, int(self.text())))
        except ValueError:
            return fallback

    def set_value(self, value: int) -> None:
        self.setText(str(max(self._minimum, min(self._maximum, int(value)))))

    def _step(self, amount: int) -> None:
        self.set_value(self.value() + amount)
        self.textEdited.emit(self.text())

    def keyPressEvent(self, event) -> None:
        big = 10 if event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier else 1
        if event.key() == qt.QtCore.Qt.Key.Key_Up:
            self._step(big)
        elif event.key() == qt.QtCore.Qt.Key.Key_Down:
            self._step(-big)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if not self.hasFocus() and not self.underMouse():
            return super().wheelEvent(event)
        big = 10 if event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier else 1
        self._step(big if event.angleDelta().y() > 0 else -big)
        event.accept()


def _buttons(dialog, on_ok, on_reset) -> qt.QtWidgets.QHBoxLayout:
    row = qt.QtWidgets.QHBoxLayout()
    row.setSpacing(8)
    reset = qt.QtWidgets.QPushButton("Reset")
    reset.setFlat(True)
    reset.setToolTip("Back to the built-in values")
    reset.clicked.connect(on_reset)
    row.addWidget(reset)
    row.addStretch(1)
    cancel = qt.QtWidgets.QPushButton("Cancel")
    cancel.clicked.connect(dialog.reject)
    ok = qt.QtWidgets.QPushButton("OK")
    ok.setProperty("primary", True)
    ok.setDefault(True)
    ok.clicked.connect(on_ok)
    row.addWidget(cancel)
    row.addWidget(ok)
    return row


class SidesDialog(FramelessDialog):
    """How a side is told: along which axis, how close to 0 counts as the middle, and the three
    prefixes. `ask()` -> a settings dict (axis, tolerance, left, right, center) or None."""

    def __init__(self, values: dict, parent=None):
        super().__init__(title="Sides", width=300, height=250, show_minimize_button=False,
                         show_maximize_button=False, show_theme_toggle=False, parent=parent)
        self._result = None
        body = qt.QtWidgets.QWidget()
        form = qt.QtWidgets.QFormLayout(body)
        form.setContentsMargins(14, 10, 14, 12)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self._axis = SegmentedControl(list(rules.MIRROR_AXES), values.get("axis", "X"))
        self._axis.setToolTip("The mirror axis: + on it is the left side, − the right, around 0 the middle")
        self._tolerance = qt.QtWidgets.QLineEdit(f"{float(values.get('tolerance', 0.001)):g}")
        self._tolerance.setValidator(qt.QtGui.QDoubleValidator(0.0, 1000.0, 4, self._tolerance))
        self._tolerance.setToolTip("How far from 0 on the axis still counts as the middle (scene units)")
        self._fields = {}
        form.addRow("Axis", self._axis)
        form.addRow("Middle within", self._tolerance)
        for side, caption in ((rules.LEFT, "Left (+)"), (rules.RIGHT, "Right (−)"), (rules.CENTER, "Middle")):
            field = qt.QtWidgets.QLineEdit(values.get(side, rules.DEFAULT_SIDES[side]))
            field.setPlaceholderText("nothing")
            self._fields[side] = field
            form.addRow(caption, field)
        form.addRow(_buttons(self, self._on_ok, self._on_reset))
        self.add_widget(body)

    @classmethod
    def ask(cls, parent, values: dict):
        dialog = cls(values, parent=parent)
        try:
            dialog.exec()
            return dialog._result
        finally:
            dialog.deleteLater()

    def _on_reset(self) -> None:
        self._axis.set_current("X")
        self._tolerance.setText("0.001")
        for side, field in self._fields.items():
            field.setText(rules.DEFAULT_SIDES[side])

    def _on_ok(self) -> None:
        try:
            tolerance = abs(float(self._tolerance.text().replace(",", ".")))
        except ValueError:
            tolerance = 0.001
        self._result = {"axis": self._axis.current(), "tolerance": tolerance,
                        **{side: rules.sanitize(field.text()) if field.text().strip() else ""
                           for side, field in self._fields.items()}}
        self.accept()


class SuffixesDialog(FramelessDialog):
    """Which suffix each kind of object gets ("mesh" -> "geo"). The kinds in the selection come
    first. An empty field = that kind gets none. `ask()` -> {kind: suffix} or None."""

    def __init__(self, suffixes: dict, kinds_here=(), parent=None):
        super().__init__(title="Suffix by kind", width=320, height=460, show_minimize_button=False,
                         show_maximize_button=False, show_theme_toggle=False, parent=parent)
        self._result = None
        self._fields: dict[str, qt.QtWidgets.QLineEdit] = {}
        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(14, 10, 14, 12)
        column.setSpacing(8)
        self._list = qt.QtWidgets.QWidget()
        self._grid = qt.QtWidgets.QFormLayout(self._list)
        self._grid.setContentsMargins(0, 0, 6, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(6)
        self._grid.setLabelAlignment(qt.QtCore.Qt.AlignmentFlag.AlignLeft | qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        scroll = qt.QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(qt.QtWidgets.QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical, scroll))
        scroll.setWidget(self._list)
        scroll.viewport().setAutoFillBackground(False)
        self._list.setAutoFillBackground(False)
        column.addWidget(scroll, 1)
        add = qt.QtWidgets.QHBoxLayout()
        self._new_kind = qt.QtWidgets.QLineEdit()
        self._new_kind.setPlaceholderText("another kind (a node type), then Enter")
        self._new_kind.returnPressed.connect(self._on_add)
        add.addWidget(self._new_kind, 1)
        column.addLayout(add)
        column.addLayout(_buttons(self, self._on_ok, self._on_reset))
        self.add_widget(body)
        self._kinds_here = [kind for kind in kinds_here if kind]
        self._fill(suffixes)

    @classmethod
    def ask(cls, parent, suffixes: dict, kinds_here=()):
        dialog = cls(suffixes, kinds_here, parent=parent)
        try:
            dialog.exec()
            return dialog._result
        finally:
            dialog.deleteLater()

    def _fill(self, suffixes: dict) -> None:
        while self._grid.rowCount():
            self._grid.removeRow(0)
        self._fields = {}
        kinds = list(dict.fromkeys(self._kinds_here + list(suffixes)))
        for kind in kinds:
            self._add_row(kind, suffixes.get(kind, ""))

    ICON = 16

    def _add_row(self, kind: str, suffix: str) -> None:
        field = qt.QtWidgets.QLineEdit(suffix)
        field.setPlaceholderText("none")
        # Maya's icon of the kind, then its name: the icon is what one recognizes it by
        caption = qt.QtWidgets.QWidget()
        line = qt.QtWidgets.QHBoxLayout(caption)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        picture = qt.QtWidgets.QLabel()
        picture.setFixedSize(self.ICON, self.ICON)  # an empty slot keeps the names in one column
        icon = maya_type_icon(kind)
        if not icon.isNull():
            picture.setPixmap(icon.pixmap(self.ICON, self.ICON))
        name = qt.QtWidgets.QLabel(kind)
        if kind in self._kinds_here:
            name.setToolTip("in the selection now")
            font = name.font()
            font.setBold(True)
            name.setFont(font)
        line.addWidget(picture)
        line.addWidget(name)
        line.addStretch(1)
        self._fields[kind] = field
        self._grid.addRow(caption, field)

    def _on_add(self) -> None:
        kind = self._new_kind.text().strip()
        if kind and kind not in self._fields:
            self._add_row(kind, "")
            self._fields[kind].setFocus()
        self._new_kind.clear()

    def _on_reset(self) -> None:
        self._fill(dict(rules.DEFAULT_TYPE_SUFFIXES))

    def _on_ok(self) -> None:
        self._result = {kind: field.text().strip().strip("_") for kind, field in self._fields.items()}
        self.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (qt.QtCore.Qt.Key.Key_Return, qt.QtCore.Qt.Key.Key_Enter) and self._new_kind.hasFocus():
            return  # the field's own Enter adds a kind; it must not press OK
        super().keyPressEvent(event)
