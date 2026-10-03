# tools/maya/playblast/visibility_dialog.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.playblast import capture
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class VisibilityDialog(FramelessDialog):
    """Picks what a playblast SHOWS: the kinds of objects a viewport can show
    or hide (capture.VISIBILITY), a check box each, grouped by what they are.

        keys, name, removed = VisibilityDialog.ask(parent, shown=[...], preset="Geometry", removable=False)

    `ask()` returns None when cancelled, else (the kinds to show, the name to
    save them under — "" = don't save, just use them —, True if "Remove this
    preset" was pressed instead).

    Quick ways in: "All", "None", and "As the viewport is now" (the kinds the
    active viewport shows at this moment — set the viewport up the way the
    playblast should look, then take it over).
    """

    COLUMNS = 3

    def __init__(self, shown, preset: str = "", removable: bool = False, parent=None):
        super().__init__(title="What the playblast shows", width=560, height=520, show_minimize_button=False,
                         show_maximize_button=False, show_theme_toggle=False, parent=parent)
        self._result = None
        self._boxes: dict[str, BaseCheckbox] = {}
        shown = set(shown)
        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(14, 10, 14, 12)
        column.setSpacing(10)

        quick = qt.QtWidgets.QHBoxLayout()
        quick.setSpacing(6)
        for text, slot in (("All", lambda: self._set_all(True)), ("None", lambda: self._set_all(False)),
                           ("As the viewport is now", self._from_viewport)):
            button = qt.QtWidgets.QPushButton(text)
            button.clicked.connect(slot)
            quick.addWidget(button)
        quick.addStretch(1)
        column.addLayout(quick)

        for group, entries in capture.VISIBILITY_GROUPS:
            heading = qt.QtWidgets.QLabel(group.upper())
            heading.setObjectName("visibilityGroup")
            column.addWidget(heading)
            grid = qt.QtWidgets.QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(6)
            for index, (key, label) in enumerate(entries):
                box = BaseCheckbox(label)
                box.set_checked_immediate(key in shown)
                self._boxes[key] = box
                grid.addWidget(box, index // self.COLUMNS, index % self.COLUMNS)
            for index in range(self.COLUMNS):
                grid.setColumnStretch(index, 1)
            column.addLayout(grid)
        column.addStretch(1)

        self._name = qt.QtWidgets.QLineEdit(preset)
        self._name.setPlaceholderText("a name saves it as a preset — empty: just use it")
        save = qt.QtWidgets.QHBoxLayout()
        save.setSpacing(8)
        caption = qt.QtWidgets.QLabel("Preset")
        caption.setObjectName("visibilityCaption")
        save.addWidget(caption)
        save.addWidget(self._name, 1)
        column.addLayout(save)

        buttons = qt.QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        remove = qt.QtWidgets.QPushButton("Remove this preset")
        remove.setFlat(True)
        remove.clicked.connect(self._on_remove)
        if not removable:
            remove.hide()
        buttons.addWidget(remove)
        buttons.addStretch(1)
        cancel = qt.QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        use = qt.QtWidgets.QPushButton("Use")
        use.setProperty("primary", True)
        use.setDefault(True)
        use.clicked.connect(self._on_use)
        buttons.addWidget(cancel)
        buttons.addWidget(use)
        column.addLayout(buttons)
        self.add_widget(body)

    @classmethod
    def ask(cls, parent, shown, preset: str = "", removable: bool = False):
        dialog = cls(shown, preset, removable, parent=parent)
        dialog.exec()
        return dialog._result

    def keys(self) -> list[str]:
        """The kinds that are ticked, in capture.VISIBILITY's order."""
        return [key for key in capture.VISIBILITY if self._boxes[key].isChecked()]

    def _set_all(self, checked: bool) -> None:
        for box in self._boxes.values():
            box.setChecked(checked)

    def _from_viewport(self) -> None:
        try:
            state = capture.visibility_state()
        except capture.CaptureError:
            return
        for key, box in self._boxes.items():
            box.setChecked(bool(state.get(key, False)))

    def _on_use(self) -> None:
        self._result = (self.keys(), self._name.text().strip(), False)
        self.accept()

    def _on_remove(self) -> None:
        self._result = (self.keys(), self._name.text().strip(), True)
        self.accept()
