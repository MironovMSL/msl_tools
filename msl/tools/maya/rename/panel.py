# tools/maya/rename/panel.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.rename import rules, scene
from msl_tools.msl.tools.maya.rename.buttons import HoverButton, KindButton, SideButton
from msl_tools.msl.tools.maya.rename.dialogs import NumberField, SidesDialog, SuffixesDialog
from msl_tools.msl.tools.maya.rename.library import NameLibrary
from msl_tools.msl.tools.maya.rename.operations import Operation as _Operation, each as _each
from msl_tools.msl.tools.maya.rename.panel_find import _FindMixin
from msl_tools.msl.tools.maya.rename.panel_objects import _ObjectsMixin
from msl_tools.msl.tools.maya.rename.panel_words import _WordsMixin
from msl_tools.msl.tools.maya.rename.preview import PreviewList
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import adopt_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.editors.token_line_edit import TokenLineEdit
from msl_tools.msl.ui.widgets.atoms.layouts.flow_layout import FlowLayout
from msl_tools.msl.ui.widgets.atoms.surfaces.stable_scroll_area import StableScrollArea

StylesheetBuilder.register_template(Path(__file__).with_name("rename.qss"))

# The quick buttons: (key, text, what it does). Each one renames the selection at once; hovered,
# the list shows what it would do.
QUICK = (
    ("upper", "AA", "UPPER CASE"),
    ("capitalize", "Aa", "Capital first letter — the rest stays (armIK → ArmIK)"),
    ("lower", "aa", "lower case"),
    ("snake", "a_b", "camelCase → snake_case (leftArmIK → left_arm_ik)"),
    ("camel", "aB", "snake_case → camelCase (left_arm_ik → leftArmIk)"),
    ("", "", ""),
    ("prefix_off", "x_", "Take the prefix off — the first part before “_” (lf_arm_jnt → arm_jnt)"),
    ("suffix_off", "_x", "Take the suffix off — the last part after “_” (arm_jnt → arm)"),
    ("number_off", "_1", "Take the number at the end off (arm_01 → arm)"),
    ("digits_off", "123", "Take every digit out (arm_01_jnt2 → arm_jnt)"),
    ("first_off", "‹", "Take the first letter off"),
    ("last_off", "›", "Take the last letter off"),
    ("", "", ""),
    ("namespace_off", "ns:", "Out of its namespace (ns:arm → arm)"),
    ("fix", "fix", "Make the name one Maya takes: Cyrillic spelled in Latin, spaces and other signs → “_”"),
)
_EACH = {
    "upper": lambda node: node.name.upper(), "lower": lambda node: node.name.lower(),
    "capitalize": lambda node: rules.capitalize(node.name),
    "snake": lambda node: rules.camel_to_snake(node.name), "camel": lambda node: rules.snake_to_camel(node.name),
    "prefix_off": lambda node: rules.remove_prefix(node.name), "suffix_off": lambda node: rules.remove_suffix(node.name),
    "number_off": lambda node: rules.remove_end_number(node.name), "digits_off": lambda node: rules.remove_digits(node.name),
    "first_off": lambda node: rules.remove_first(node.name), "last_off": lambda node: rules.remove_last(node.name),
    "namespace_off": lambda node: node.name, "fix": lambda node: rules.sanitize(node.name),
}


class TemplateField(TokenLineEdit):
    """The name field: a template with {tokens} (a right click lists them), and completion of the
    word being typed — the part after the last "_" — from the name library. Tab takes the first
    word offered."""

    def __init__(self, parent=None):
        super().__init__({token.strip("{}"): meaning for token, meaning in rules.TOKEN_HELP.items()}, parent)
        self._words = qt.QtCore.QStringListModel(self)
        self._completer = qt.QtWidgets.QCompleter(self._words, self)
        self._completer.setCaseSensitivity(qt.QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(qt.QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        self._completer.setWidget(self)
        self._completer.activated[str].connect(self._take)
        self.textEdited.connect(self._on_edited)

    def set_words(self, words: list) -> None:
        self._words.setStringList(list(words))

    def _word_bounds(self) -> tuple[int, int]:
        text, cursor = self.text(), self.cursorPosition()
        start = max(text.rfind("_", 0, cursor), text.rfind("}", 0, cursor)) + 1
        return start, cursor

    def _on_edited(self, _text) -> None:
        start, cursor = self._word_bounds()
        word = self.text()[start:cursor]
        if len(word) < 2:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(word)
        if self._completer.completionCount() == 0 or (self._completer.completionCount() == 1
                                                       and self._completer.currentCompletion() == word):
            self._completer.popup().hide()
            return
        adopt_popup(self._completer.popup(), self)
        rect = self.cursorRect()
        rect.setWidth(160)
        self._completer.complete(rect)

    def _take(self, word: str) -> None:
        start, cursor = self._word_bounds()
        text = self.text()
        self.setText(text[:start] + word + text[cursor:])
        self.setCursorPosition(start + len(word))
        self.textEdited.emit(self.text())

    def keyPressEvent(self, event) -> None:
        popup = self._completer.popup()
        if popup.isVisible() and event.key() in (qt.QtCore.Qt.Key.Key_Tab, qt.QtCore.Qt.Key.Key_Return,
                                                 qt.QtCore.Qt.Key.Key_Enter):
            index = popup.currentIndex()
            word = index.data() if index.isValid() else self._completer.currentCompletion()
            popup.hide()
            if word:
                self._take(word)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, forward: bool) -> bool:
        return False if self._completer.popup().isVisible() else super().focusNextPrevChild(forward)


class RenamePanel(_WordsMixin, _FindMixin, _ObjectsMixin, qt.QtWidgets.QWidget):
    """The rename tool inside Maya (shown in a RenameWindow).

    On top, what is used all the time: the quick buttons (case, take a part off), the name field
    — a template with tokens, see rules.py — with Rename, the number settings while the template
    numbers, prefix / side / kind / suffix, and the favorite words. Under it the list "before →
    after" of every selected object: what a click WOULD do shows there while the pointer is over a
    button, so nothing is renamed blind. Then cards that fold: WORDS (the name library), FIND &
    REPLACE, OBJECTS (what is selected: kinds, names to look at, sets).

    One click = one undo step. The list follows Maya's selection (a lock keeps it on the objects
    it holds). Settings and the library: configsMayaMng "rename".
    """

    TOOL_NAME = "rename"
    DEFAULTS = {"template": "", "start": 1, "step": 1, "padding": 2, "order": rules.ORDER_SELECTION,
                "prefix": "", "suffix": "", "into_field": False,
                "sides": {"axis": "X", "tolerance": 0.001, **rules.DEFAULT_SIDES},
                "find": "", "replace": "", "scope": scene.SCOPE_SELECTED, "case": True, "regex": False,
                "category": "", "folded": {"words": True, "find": True, "objects": True}}
    REFRESH_MS = 60
    MAX_OBJECTS = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": dict(self.DEFAULTS)})
        self._config = config
        self._settings = config["settings"]
        self.library = NameLibrary(config["library"])
        self._nodes: list = []
        self._locked: list | None = None         # uuids the list is held on (the lock)
        self._source = "template"                # what the list shows when nothing is hovered
        self._hover: _Operation | None = None
        self._last: _Operation | None = None     # for "repeat"
        self._callbacks: list = []
        self._loading = False
        self._refresh_timer = qt.QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(self.REFRESH_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        self._build_widgets()
        self._build_layout()
        self._apply_settings()
        self._connect()

    # ------------------------------------------------------------------ building

    def _build_widgets(self) -> None:
        icons = UiResources().iconManager
        self._quick = qt.QtWidgets.QWidget()
        quick = FlowLayout(self._quick, spacing=2)
        self._quick_buttons = {}
        for key, text, tooltip in QUICK:
            if not key:
                gap = qt.QtWidgets.QWidget()
                gap.setFixedSize(3, 20)
                quick.addWidget(gap)
                continue
            button = HoverButton(text, tooltip + "\nThe list shows what it does while the pointer is here")
            button.setObjectName("renameQuick")
            self._quick_buttons[key] = button
            quick.addWidget(button)

        self._field = TemplateField()
        self._field.setObjectName("renameField")
        self._field.setPlaceholderText("New name — {#} numbers, right click: more tokens")
        self._field.setClearButtonEnabled(True)
        self._number_toggle = HoverButton("01", "Number them: puts “_{#}” at the end of the name (or takes it out)")
        self._number_toggle.setObjectName("renameToggle")
        self._number_toggle.setCheckable(True)
        self._rename = qt.QtWidgets.QPushButton("Rename")
        self._rename.setProperty("primary", True)
        self._rename.setToolTip("Rename the objects in the list to the name in the field (Enter)\n"
                                "Right click: the names used last")
        self._rename.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)

        self._start = NumberField(1, -9999, 99999)
        self._start.setToolTip("The first number")
        self._step = NumberField(1, -999, 999, width=36)
        self._step.setToolTip("Step: how much each next number adds")
        self._padding = NumberField(2, 1, 9, width=30)
        self._padding.setToolTip("Digits: 2 → 01, 3 → 001")
        self._order = BaseComboBox(list(rules.ORDERS), rules.ORDER_SELECTION)
        self._order.setToolTip("The order objects get their numbers / letters in")

        self._prefix = qt.QtWidgets.QLineEdit()
        self._prefix.setPlaceholderText("prefix_")
        self._prefix.setToolTip("Enter or + puts it in front of every name (not twice)")
        self._prefix_add = HoverButton("+", "Put the prefix in front of every name")
        self._prefix_add.setObjectName("renameAdd")
        self._suffix = qt.QtWidgets.QLineEdit()
        self._suffix.setPlaceholderText("_suffix")
        self._suffix.setToolTip("Enter or + puts it at the end of every name (not twice)")
        self._suffix_add = HoverButton("+", "Put the suffix at the end of every name")
        self._suffix_add.setObjectName("renameAdd")
        self._side = SideButton()
        self._kind = KindButton()

        self._count = qt.QtWidgets.QLabel("")
        self._count.setObjectName("renameCount")
        self._lock = GlyphButton("", "Hold the list on these objects — selecting others doesn't change it",
                                 size=qt.QtCore.QSize(22, 20))
        self._lock.setObjectName("renameLock")
        self._lock.set_icon(icons.get_icon("lock", sub_folder="actions"))
        self._lock.setCheckable(True)
        self._select_listed = GlyphButton("", "Select the objects in the list", size=qt.QtCore.QSize(22, 20))
        self._select_listed.setObjectName("renameLock")
        self._select_listed.set_icon(icons.get_icon("select_all", sub_folder="actions"))
        self._preview = PreviewList()
        self._status = qt.QtWidgets.QLabel("")
        self._status.setObjectName("renameStatus")
        self._status.setWordWrap(True)
        self._status.hide()

    def _build_layout(self) -> None:
        name_row = qt.QtWidgets.QHBoxLayout()
        name_row.setSpacing(4)
        name_row.addWidget(self._field, 1)
        name_row.addWidget(self._number_toggle)
        name_row.addWidget(self._rename)

        self._number_row = qt.QtWidgets.QWidget()
        numbers = qt.QtWidgets.QHBoxLayout(self._number_row)
        numbers.setContentsMargins(0, 0, 0, 0)
        numbers.setSpacing(4)
        for caption, widget in (("from", self._start), ("step", self._step), ("digits", self._padding)):
            label = qt.QtWidgets.QLabel(caption)
            label.setObjectName("renameCaption")
            numbers.addWidget(label)
            numbers.addWidget(widget)
        numbers.addSpacing(4)
        numbers.addWidget(self._order, 1)

        affix = qt.QtWidgets.QHBoxLayout()
        affix.setSpacing(4)
        affix.addWidget(self._prefix_add)
        affix.addWidget(self._prefix, 1)
        affix.addWidget(self._side)
        affix.addWidget(self._kind)
        affix.addWidget(self._suffix, 1)
        affix.addWidget(self._suffix_add)

        list_head = qt.QtWidgets.QHBoxLayout()
        list_head.setSpacing(2)
        list_head.addWidget(self._count, 1)
        list_head.addWidget(self._select_listed)
        list_head.addWidget(self._lock)

        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(10, 8, 4, 8)
        column.setSpacing(6)
        column.addWidget(self._quick)
        column.addLayout(name_row)
        column.addWidget(self._number_row)
        column.addLayout(affix)
        column.addWidget(self._favorites_bar())
        column.addLayout(list_head)
        column.addWidget(self._preview)
        column.addWidget(self._status)
        column.addWidget(self._words_card())
        column.addWidget(self._find_card())
        column.addWidget(self._objects_card())
        column.addStretch(1)
        scroll = StableScrollArea()
        scroll.setObjectName("renameScroll")
        scroll.setWidget(body)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def _connect(self) -> None:
        for key, button in self._quick_buttons.items():
            button.clicked.connect(lambda _checked=False, key=key: self._run(self._quick_operation(key)))
            button.hovered.connect(lambda on, key=key: self._set_hover(self._quick_operation(key) if on else None))
        self._field.textEdited.connect(self._on_template_edited)
        self._field.token_inserted.connect(self._on_template_edited)
        self._field.textChanged.connect(self._on_template_changed)
        self._field.returnPressed.connect(self.rename)
        self._field.focused.connect(lambda: self._set_source("template"))
        self._rename.clicked.connect(self.rename)
        self._rename.customContextMenuRequested.connect(self._on_recent_menu)
        self._number_toggle.clicked.connect(self._on_number_toggle)
        for field in (self._start, self._step, self._padding):
            field.textEdited.connect(self._on_numbers_changed)
        self._order.currentTextChanged.connect(self._on_numbers_changed)
        self._prefix.returnPressed.connect(self._on_prefix)
        self._prefix_add.clicked.connect(self._on_prefix)
        self._prefix_add.hovered.connect(lambda on: self._set_hover(self._prefix_operation() if on else None))
        self._suffix.returnPressed.connect(self._on_suffix)
        self._suffix_add.clicked.connect(self._on_suffix)
        self._suffix_add.hovered.connect(lambda on: self._set_hover(self._suffix_operation() if on else None))
        for field in (self._prefix, self._suffix):
            field.textEdited.connect(self._save_settings)
        self._side.clicked.connect(lambda: self._run(self._side_operation()))
        self._side.hovered.connect(lambda on: self._set_hover(self._side_operation() if on else None))
        self._side.menu_requested.connect(self._on_sides_settings)
        self._kind.clicked.connect(lambda: self._run(self._kind_operation()))
        self._kind.hovered.connect(lambda on: self._set_hover(self._kind_operation() if on else None))
        self._kind.menu_requested.connect(self._on_suffix_settings)
        self._lock.toggled.connect(self._on_lock)
        self._select_listed.clicked.connect(self._on_select_listed)
        self._preview.renamed.connect(self._on_one_renamed)
        self._preview.use_name.connect(self._use_name)
        self._preview.select_requested.connect(self._on_select_one)
        self._connect_words()
        self._connect_find()
        self._connect_objects()

    # ------------------------------------------------------------------ settings

    def _apply_settings(self) -> None:
        self._loading = True
        settings = self._settings
        self._field.setText(settings.get("template", ""))
        self._start.set_value(settings.get("start", 1))
        self._step.set_value(settings.get("step", 1))
        self._padding.set_value(settings.get("padding", 2))
        index = self._order.findText(settings.get("order", rules.ORDER_SELECTION))
        self._order.setCurrentIndex(max(index, 0))
        self._prefix.setText(settings.get("prefix", ""))
        self._suffix.setText(settings.get("suffix", ""))
        self._apply_words_settings()
        self._apply_find_settings()
        self._apply_objects_settings()
        self._loading = False
        self._sync_number_row()

    def _save_settings(self, *_args) -> None:
        if self._loading:
            return
        values = {"template": self._field.text(), "start": self._start.value(1), "step": self._step.value(1),
                  "padding": self._padding.value(2), "order": self._order.currentText(),
                  "prefix": self._prefix.text(), "suffix": self._suffix.text()}
        values.update(self._words_settings())
        values.update(self._find_settings())
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value

    def _sides(self) -> rules.Sides:
        saved = dict(self._settings.get("sides") or {})
        prefixes = {side: saved.get(side, rules.DEFAULT_SIDES[side]) for side in rules.DEFAULT_SIDES}
        try:
            tolerance = float(saved.get("tolerance", 0.001))
        except (TypeError, ValueError):
            tolerance = 0.001
        return rules.Sides(axis=saved.get("axis", "X"), tolerance=tolerance, prefixes=prefixes)

    def _suffixes(self) -> dict:
        saved = dict(self._config["type_suffixes"])  # a missing key reads as an empty node
        return saved or dict(rules.DEFAULT_TYPE_SUFFIXES)

    def _numbering(self) -> rules.Numbering:
        return rules.Numbering(start=self._start.value(1), step=self._step.value(1),
                               padding=self._padding.value(2), order=self._order.currentText())

    # ------------------------------------------------------------------ Maya's selection

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._watch()
        self.refresh()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if not self.window().isVisible():
            self._unwatch()

    def _watch(self) -> None:
        if self._callbacks:
            return
        try:
            from maya import cmds
            import maya.api.OpenMaya as om
        except ImportError:
            return  # outside Maya (a test): refresh() is called by hand
        try:
            cmds.selectPref(trackSelectionOrder=True)  # so numbers follow the order things were picked in
        except RuntimeError:
            pass
        for event in ("SelectionChanged", "NameChanged", "Undo", "Redo", "SceneOpened", "NewSceneOpened"):
            try:
                self._callbacks.append(om.MEventMessage.addEventCallback(event, self._on_maya_event))
            except RuntimeError:
                pass

    def _unwatch(self) -> None:
        if not self._callbacks:
            return
        try:
            import maya.api.OpenMaya as om
            om.MMessage.removeCallbacks(self._callbacks)
        except (ImportError, RuntimeError):
            pass
        self._callbacks = []

    def _on_maya_event(self, *_args) -> None:
        try:
            self._refresh_timer.start()
        except RuntimeError:
            pass  # the panel is gone and its callbacks with it a moment later

    def refresh(self) -> None:
        """Reads the objects again (the selection, or the held ones) and redraws the list."""
        if self._locked is not None:
            found = []
            for uuid in self._locked:
                path = scene.current(rules.Node(path="", name="", uuid=uuid))
                if path:
                    found.append(path)
            items = found
        else:
            items = scene.paths(scene.SCOPE_SELECTED)
        self._too_many = len(items) > self.MAX_OBJECTS
        self._nodes = scene.nodes(items[:self.MAX_OBJECTS])
        self._side.set_sides({self._sides().of(node.position) for node in self._nodes if node.uuid})
        self._kind.set_kind(self._nodes[0].kind if self._nodes else "")
        self._refresh_objects()
        self._find_nodes_cache = None
        self._update_preview()

    # ------------------------------------------------------------------ the list

    def _set_source(self, source: str) -> None:
        if source != self._source:
            self._source = source
            self._update_preview()

    def _set_hover(self, operation: "_Operation | None") -> None:
        self._hover = operation
        self._update_preview()

    def _current_operation(self) -> "_Operation | None":
        if self._hover is not None:
            return self._hover
        if self._source == "find":
            operation = self._replace_operation()
            if operation is not None:
                return operation
        if self._field.text().strip():
            return self._template_operation()
        return None

    def _update_preview(self) -> None:
        operation = self._current_operation()
        nodes = operation.nodes() if operation is not None and operation.nodes is not None else self._nodes
        if operation is None:
            changes = [rules.Change(node, node.name, "idle") for node in nodes]
            self._preview.set_changes(changes)
            self._show_count(nodes, None)
            return
        try:
            names = operation.names(nodes)
        except ValueError as error:  # a broken regular expression
            self._preview.set_changes([rules.Change(node, node.name, "idle") for node in nodes])
            self._say(str(error), "error")
            return
        changes = rules.plan(nodes, names, operation.drop_namespace)
        self._preview.set_changes(changes)
        self._show_count(nodes, changes, operation)

    def _show_count(self, nodes, changes, operation=None) -> None:
        held = " · held" if self._locked is not None else ""
        where = "" if operation is None or operation.nodes is None else " found"
        if not nodes:
            text = "Nothing found" if where else "Nothing selected"
        elif changes is None:
            text = f"{len(nodes)}{where} selected{held}" if not where else f"{len(nodes)} found"
        else:
            changing = sum(1 for change in changes if change.changes)
            look = sum(1 for change in changes if change.state in ("clash", "error"))
            text = f"{len(nodes)}{where or (' selected' + held)} · {changing} will change"
            if look:
                text += f" · {look} to look at"
            if operation is not None and operation is self._hover:
                text = f"{operation.label}: " + text
        if getattr(self, "_too_many", False):
            text += f" · only the first {self.MAX_OBJECTS}"
        self._count.setText(text)

    # ------------------------------------------------------------------ operations

    def _quick_operation(self, key: str) -> _Operation:
        label = next(text for each, text, _tip in QUICK if each == key)
        return _Operation(label, _each(_EACH[key]), drop_namespace=key == "namespace_off")

    def _template_operation(self) -> _Operation:
        template = self._field.text().strip()
        numbering, sides, suffixes = self._numbering(), self._sides(), self._suffixes()
        return _Operation("Rename", lambda nodes: rules.from_template(nodes, template, numbering, sides, suffixes))

    def _prefix_operation(self) -> _Operation:
        prefix = self._prefix.text().strip()
        return _Operation(f"Prefix “{prefix}”", _each(lambda node: rules.add_prefix(node.name, prefix)))

    def _suffix_operation(self) -> _Operation:
        suffix = self._suffix.text().strip()
        return _Operation(f"Suffix “{suffix}”", _each(lambda node: rules.add_suffix(node.name, suffix)))

    def _side_operation(self) -> _Operation:
        sides = self._sides()
        return _Operation("Side", _each(lambda node: rules.side_prefix(node.name, node.position, sides)))

    def _kind_operation(self) -> _Operation:
        suffixes = self._suffixes()
        return _Operation("Kind", _each(lambda node: rules.type_suffix(node.name, node.kind, suffixes)))

    def _word_operation(self, word: str, separator: bool) -> _Operation:
        return _Operation(f"“{word}”", _each(lambda node: rules.add_word(node.name, word, separator)))

    def _run(self, operation: _Operation, remember: bool = True) -> int:
        """Renames by `operation`; returns how many were renamed."""
        nodes = operation.nodes() if operation.nodes is not None else self._nodes
        if not nodes:
            self._say("Select the objects to rename first", "error")
            return 0
        try:
            names = operation.names(nodes)
        except ValueError as error:
            self._say(str(error), "error")
            return 0
        changes = rules.plan(nodes, names, operation.drop_namespace)
        if not any(change.changes for change in changes):
            refused = [change for change in changes if change.state == "error"]
            self._say(f"Maya won't take “{refused[0].new}”: {refused[0].note}" if refused
                      else "Nothing to change — the names are like that already", "error" if refused else "")
            return 0
        done = scene.apply(changes, operation.drop_namespace)
        if remember:
            self._last = operation
        self._report(changes, done)
        self.refresh()
        return sum(1 for _change, given, error in done if given and not error)

    def _report(self, changes, done) -> None:
        renamed = [entry for entry in done if entry[1] and not entry[2]]
        failed = [entry for entry in done if entry[2]]
        numbered = [entry for entry in renamed if entry[1].rpartition(":")[2] != entry[0].new]
        skipped = [change for change in changes if change.state in ("locked", "error")]
        parts = [f"Renamed {len(renamed)}" if renamed else "Nothing renamed"]
        if numbered:
            parts.append(f"{len(numbered)} numbered by Maya (the name was taken)")
        if skipped:
            reasons = sorted({change.note for change in skipped})
            parts.append(f"{len(skipped)} skipped ({', '.join(reasons[:2])})")
        if failed:
            parts.append(f"{len(failed)} failed: {failed[0][2]}")
        self._say(" · ".join(parts) + (" · Ctrl+Z undoes it" if renamed else ""),
                  "error" if failed or not renamed else "done")

    def rename(self) -> None:
        """Rename by the template in the field (Enter, the button)."""
        template = self._field.text().strip()
        if not template:
            self._say("Type a name first", "error")
            self._field.setFocus()
            return
        unknown = rules.unknown_tokens(template)
        if unknown:
            self._say(f"Unknown token {unknown[0]} — right click the field for the ones there are", "error")
            return
        if self._run(self._template_operation()):
            self.library.remember(template)
            self._refresh_recent_words()

    def repeat_last(self) -> None:
        """The last operation again, on what is selected now (a hotkey)."""
        if self._last is None:
            self.rename()
        else:
            self._run(self._last)

    # ------------------------------------------------------------------ reactions

    def _on_template_edited(self, *_args) -> None:
        self._set_source("template")
        self._save_settings()

    def _on_template_changed(self, _text) -> None:
        self._sync_number_row()
        self._update_preview()

    def _sync_number_row(self) -> None:
        template = self._field.text()
        numbers = rules.uses_number(template)
        if numbers != self._number_row.isVisibleTo(self):
            if numbers:
                self._number_row.show()
            else:
                self._number_row.hide()
        self._number_toggle.setChecked("{#}" in template)

    def _on_number_toggle(self) -> None:
        text = self._field.text()
        if "{#}" in text:
            text = rules.tidy(text.replace("{#}", ""))
        else:
            text = (text.rstrip("_") + "_{#}") if text.strip() else "{name}_{#}"
        self._field.setText(text)
        self._set_source("template")
        self._save_settings()

    def _on_numbers_changed(self, *_args) -> None:
        self._save_settings()
        self._update_preview()

    def _on_prefix(self) -> None:
        prefix = self._prefix.text().strip()
        if not prefix:
            self._prefix.setFocus()
            return
        if self._into_field():
            self._field.setText(rules.add_prefix(self._field.text(), prefix))
            self._on_template_edited()
        else:
            self._run(self._prefix_operation())

    def _on_suffix(self) -> None:
        suffix = self._suffix.text().strip()
        if not suffix:
            self._suffix.setFocus()
            return
        if self._into_field():
            self._field.setText(rules.add_suffix(self._field.text(), suffix))
            self._on_template_edited()
        else:
            self._run(self._suffix_operation())

    def _on_sides_settings(self) -> None:
        values = dict(self._settings.get("sides") or {})
        result = SidesDialog.ask(self.window(), values)
        if result is not None:
            self._settings["sides"] = result
            self.refresh()

    def _on_suffix_settings(self) -> None:
        kinds = list(dict.fromkeys(node.kind for node in self._nodes))
        result = SuffixesDialog.ask(self.window(), self._suffixes(), kinds)
        if result is not None:
            self._config["type_suffixes"] = result
            self._update_preview()

    def _on_lock(self, locked: bool) -> None:
        self._locked = [node.uuid for node in self._nodes if node.uuid] if locked else None
        self.refresh()

    def _on_select_listed(self) -> None:
        operation = self._current_operation()
        nodes = operation.nodes() if operation is not None and operation.nodes is not None else self._nodes
        scene.select_nodes(nodes)

    def _on_select_one(self, uuid: str) -> None:
        node = next((node for node in self._shown_nodes() if node.uuid == uuid), None)
        if node is not None:
            scene.select_nodes([node])

    def _shown_nodes(self) -> list:
        operation = self._current_operation()
        return operation.nodes() if operation is not None and operation.nodes is not None else self._nodes

    def _on_one_renamed(self, uuid: str, text: str) -> None:
        node = next((node for node in self._shown_nodes() if node.uuid == uuid), None)
        if node is None:
            return
        self._run(_Operation("Rename one", lambda nodes: [text], nodes=lambda: [node]), remember=False)

    def _use_name(self, name: str) -> None:
        if self._field.text().strip() and self._field.text() != name:
            self._field.selectAll()
        self._field.setText(name)
        self._field.setFocus()
        self._on_template_edited()

    def _on_recent_menu(self, position) -> None:
        from msl_tools.msl.ui.theme.qss import make_rounded_popup
        recent = self.library.recent()
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        if not recent:
            action = menu.addAction("No names used yet")
            action.setEnabled(False)
        for text in recent[:12]:
            menu.addAction(text, lambda text=text: self._use_name(text))
        menu.exec(self._rename.mapToGlobal(position))

    def _say(self, text: str, state: str = "") -> None:
        self._status.setText(text)
        if bool(text) != self._status.isVisibleTo(self):
            if text:
                self._status.show()
            else:
                self._status.hide()
        if (self._status.property("state") or "") != state:
            self._status.setProperty("state", state)
            repolish(self._status)

    def focus_field(self) -> None:
        self._field.setFocus()
        self._field.selectAll()
