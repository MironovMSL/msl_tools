# tools/maya/rename/panel_find.py
"""The rename panel's FIND & REPLACE card. Methods of RenamePanel, kept apart by concern.

While its fields are being worked in, the "before -> after" list shows what Replace would do — on
the objects that MATCH, in the scope picked (the selection, the selection with everything under
it, the whole scene)."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.rename import rules, scene
from msl_tools.msl.tools.maya.rename.buttons import HoverButton
from msl_tools.msl.tools.maya.rename.operations import Operation
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard


class _FocusLineEdit(qt.QtWidgets.QLineEdit):
    focused = qt.QtCore.Signal()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit()


class _FindMixin:

    _find_nodes_cache = None

    def _find_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        self._case = HoverButton("Aa", "Match case: “Arm” isn't “arm”")
        self._regex = HoverButton(".*", "A regular expression (Python): \\d+ any number, ^ the start, $ the end;\n"
                                        "in the new text \\1 is what the first ( ) found")
        for toggle in (self._case, self._regex):
            toggle.setObjectName("renameToggle")
            toggle.setCheckable(True)
        card = self._find = FoldingCard("FIND & REPLACE", icons.get_icon("search", sub_folder="actions"),
                                        extras=[self._case, self._regex])
        self._find_text = _FocusLineEdit()
        self._find_text.setPlaceholderText("Find")
        self._find_text.setClearButtonEnabled(True)
        self._replace_text = _FocusLineEdit()
        self._replace_text.setPlaceholderText("Replace with (empty: take it out)")
        self._scope = SegmentedControl(list(scene.SCOPES), scene.SCOPE_SELECTED)
        self._scope.setToolTip("Where to look: the selection · the selection and everything under it · the whole scene")
        self._find_select = qt.QtWidgets.QPushButton("Select")
        self._find_select.setToolTip("Select what matches")
        self._find_replace = qt.QtWidgets.QPushButton("Replace")
        self._find_replace.setToolTip("Replace in every name that matches — every occurrence")
        fields = qt.QtWidgets.QHBoxLayout()
        fields.setSpacing(4)
        fields.addWidget(self._find_text, 1)
        arrow = qt.QtWidgets.QLabel("→")
        arrow.setObjectName("renameCaption")
        fields.addWidget(arrow)
        fields.addWidget(self._replace_text, 1)
        actions = qt.QtWidgets.QHBoxLayout()
        actions.setSpacing(4)
        actions.addWidget(self._scope, 1)
        actions.addWidget(self._find_select)
        actions.addWidget(self._find_replace)
        card.body_layout.addLayout(fields)
        card.body_layout.addLayout(actions)
        return card

    def _connect_find(self) -> None:
        for field in (self._find_text, self._replace_text):
            field.textEdited.connect(self._on_find_changed)
            field.focused.connect(lambda: self._set_source("find"))
            field.returnPressed.connect(self._on_replace)
        self._find_text.textChanged.connect(self._on_find_cleared)
        self._scope.current_changed.connect(self._on_find_changed)
        for toggle in (self._case, self._regex):
            toggle.toggled.connect(self._on_find_changed)
        self._find_select.clicked.connect(self._on_find_select)
        self._find_replace.clicked.connect(self._on_replace)
        self._find.toggled.connect(self._on_find_folded)

    def _apply_find_settings(self) -> None:
        settings = self._settings
        self._find_text.setText(settings.get("find", ""))
        self._replace_text.setText(settings.get("replace", ""))
        self._scope.set_current(settings.get("scope", scene.SCOPE_SELECTED), animate=False)
        self._case.setChecked(bool(settings.get("case", True)))
        self._regex.setChecked(bool(settings.get("regex", False)))
        folded = dict(settings.get("folded") or {})
        self._find.set_open(not folded.get("find", True))
        self._sum_up_find()

    def _find_settings(self) -> dict:
        return {"find": self._find_text.text(), "replace": self._replace_text.text(), "scope": self._scope.current(),
                "case": self._case.isChecked(), "regex": self._regex.isChecked()}

    def _sum_up_find(self) -> None:
        find = self._find_text.text()
        self._find.set_summary(f"“{find}” → “{self._replace_text.text()}” · {self._scope.current()}" if find else "")

    # ------------------------------------------------------------------ what matches

    def _find_nodes(self) -> list:
        find = self._find_text.text()
        case, regex, scope = self._case.isChecked(), self._regex.isChecked(), self._scope.current()
        key = (find, case, regex, scope, tuple(node.uuid for node in self._nodes))
        if self._find_nodes_cache is not None and self._find_nodes_cache[0] == key:
            return self._find_nodes_cache[1]
        if scope == scene.SCOPE_SELECTED:
            found = [node for node in self._nodes if rules.matches(node.name, find, case, regex)]
        else:
            paths = [path for path in scene.paths(scope)
                     if rules.matches(path.rpartition("|")[2].rpartition(":")[2], find, case, regex)]
            found = scene.nodes(paths[:self.MAX_OBJECTS])
        self._find_nodes_cache = (key, found)
        return found

    def _replace_operation(self):
        find = self._find_text.text()
        if not find:
            return None
        new, case, regex = self._replace_text.text(), self._case.isChecked(), self._regex.isChecked()
        return Operation("Replace", lambda nodes: [rules.replace(node.name, find, new, case, regex) for node in nodes],
                          nodes=self._find_nodes)

    # ------------------------------------------------------------------ reactions

    def _on_find_changed(self, *_args) -> None:
        self._find_nodes_cache = None
        self._source = "find"
        self._sum_up_find()
        self._save_settings()
        self._update_preview()

    def _on_find_cleared(self, text: str) -> None:
        if not text and self._source == "find":
            self._update_preview()

    def _on_find_folded(self, opened: bool) -> None:
        self._save_folded("find", opened)
        if not opened and self._source == "find":
            self._set_source("template")

    def _on_find_select(self) -> None:
        if not self._find_text.text():
            self._say("Type what to find first", "error")
            return
        found = self._find_nodes()
        scene.select_nodes(found)
        self._say(f"Selected {len(found)}" if found else "Nothing matches", "" if found else "error")

    def _on_replace(self) -> None:
        operation = self._replace_operation()
        if operation is None:
            self._say("Type what to find first", "error")
            self._find_text.setFocus()
            return
        self._source = "find"
        self._run(operation)
        self._find_nodes_cache = None
        self._update_preview()
