# tools/maya/rename/panel.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.rename import rules, scene
from msl_tools.msl.tools.maya.rename.buttons import HoverButton, KindButton, QuickButton, SideButton, ToggleIconButton
from msl_tools.msl.tools.maya.rename.dialogs import NumberField, SidesDialog, SuffixesDialog
from msl_tools.msl.tools.maya.rename.library import NameLibrary
from msl_tools.msl.tools.maya.rename.recipes import RecipeStore
from msl_tools.msl.tools.maya.rename.operations import Operation as _Operation, each as _each
from msl_tools.msl.tools.maya.rename.panel_find import _FindMixin
from msl_tools.msl.tools.maya.rename.panel_objects import _ObjectsMixin
from msl_tools.msl.tools.maya.rename.panel_words import _WordsMixin
from msl_tools.msl.tools.maya.rename.preview import HeightGrip, PreviewList
from msl_tools.msl.tools.maya.rename.word_fields import TemplateField, WordField  # (TemplateField: also used by others)
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.layouts.flow_layout import FlowLayout
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.tools.maya.rename.buttons import maya_type_icon
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
    ("", "", ""),
    ("namespace_off", "ns:", "Out of its namespace (ns:arm → arm)"),
    ("fix", "fix", "Make the name one Maya takes: Cyrillic spelled in Latin, spaces and other signs → “_”"),
    ("clean", "clean", "Clean what an import or a Duplicate leaves: pasted__ in front, a number glued to a "
                       "suffix (arm_jnt1 → arm_jnt), “__”"),
    ("", "", ""),
    ("mirror", "L↔R", "The other side's name: lf_ ↔ rt_, _L ↔ _R, left ↔ right (lf_arm → rt_arm)"),
    ("shapes", "Shape", "Name the SHAPES after their transforms: pCubeShape3 under “body” → bodyShape"),
)
# Each quick button's icon (assets/icons/actions): the case ones show the letters, snake_case a
# snake and camelCase a camel's humps (where the names come from), the "take off" ones a dashed
# part going, the one-letter ones a backspace key pointing that way.
QUICK_ICONS = {
    "upper": "case_upper", "capitalize": "case_capital", "lower": "case_lower", "snake": "case_snake",
    "camel": "case_camel", "prefix_off": "cut_prefix", "suffix_off": "cut_suffix", "number_off": "cut_number",
    "digits_off": "cut_digits", "first_off": "cut_first", "last_off": "cut_last", "namespace_off": "namespace_out",
    "fix": "magic_fix", "clean": "sweep", "mirror": "mirror_sides", "shapes": "shape_name",
}
_EACH = {
    "upper": lambda node: node.name.upper(), "lower": lambda node: node.name.lower(),
    "capitalize": lambda node: rules.capitalize(node.name),
    "snake": lambda node: rules.camel_to_snake(node.name), "camel": lambda node: rules.snake_to_camel(node.name),
    "prefix_off": lambda node: rules.remove_prefix(node.name), "suffix_off": lambda node: rules.remove_suffix(node.name),
    "number_off": lambda node: rules.remove_end_number(node.name), "digits_off": lambda node: rules.remove_digits(node.name),
    "first_off": lambda node: rules.remove_first(node.name), "last_off": lambda node: rules.remove_last(node.name),
    "namespace_off": lambda node: node.name, "fix": lambda node: rules.sanitize(node.name),
}
# The quick buttons sit in four GROUPS (a GroupButton each: shows the action used last, a click
# repeats it, its corner opens the rest): (key, title, tone, actions).
QUICK_GROUPS = (
    ("case", "Case", "blue", ("upper", "capitalize", "lower", "snake", "camel")),
    ("cut", "Take a part off", "orange", ("prefix_off", "suffix_off", "number_off", "digits_off")),
    ("clean", "Clean", "green", ("namespace_off", "fix", "clean")),
    ("sides", "Sides & shapes", "teal", ("mirror", "shapes")),
)
# The quick buttons' colors by group (rename.qss `tone`): case = blue, taking a part off = orange,
# cleaning = green, sides / shapes = teal — the strip beside the list speaks the same palette.
QUICK_TONES = {
    **dict.fromkeys(("upper", "capitalize", "lower", "snake", "camel"), "blue"),
    **dict.fromkeys(("prefix_off", "suffix_off", "number_off", "digits_off", "first_off", "last_off"), "orange"),
    **dict.fromkeys(("namespace_off", "fix", "clean"), "green"),
    **dict.fromkeys(("mirror", "shapes"), "teal"),
}
QUICK_ICON_SIZE = 17
# The two one-letter buttons sit at the ends of the name field (the end they work on).
EDGE = (("first_off", "‹", "Take the first letter off"), ("last_off", "›", "Take the last letter off"))
CONVENTION_PLACEHOLDER = "Convention, e.g. {side}_{name}_{type}"


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

    # what the panel says (text, state "" / "done" / "error"): the window shows it in its header
    status_changed = qt.QtCore.Signal(str, str)

    TOOL_NAME = "rename"
    DEFAULTS = {"template": "", "start": 1, "step": 1, "padding": 2, "order": rules.ORDER_SELECTION,
                "prefix": "", "suffix": "", "into_field": False,
                "sides": {"axis": "X", "tolerance": 0.001, **rules.DEFAULT_SIDES},
                "find": "", "replace": "", "scope": scene.SCOPE_SELECTED, "case": True, "regex": False,
                "category": "", "folded": {"words": True, "find": True, "objects": True},
                "list_source": "Selected"}
    LIST_SOURCES = ("Selected", "Hierarchy")  # what the list holds: the selection / it and all under it
    REFRESH_MS = 60
    MAX_OBJECTS = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": dict(self.DEFAULTS)})
        self._config = config
        self._settings = config["settings"]
        self.library = NameLibrary(config["library"])
        self.recipes = RecipeStore(config["library"])  # beside the words (a ConfigNode: a JsonConfig has no get())
        self._nodes: list = []
        self._locked: list | None = None         # uuids the list is held on (the lock)
        self._kind_filter: set = set()           # kinds the list shows ("" none = all)
        self._filter_base: list | None = None    # uuids of the whole list while a kind filter holds it
        self._filter_selection: set = set()      # uuids the filter selected in Maya itself
        self._all_nodes: list = []               # the list before the kind filter
        self._manual_order: list = []            # uuids in the order the user dragged the rows into
        self._manual_set: frozenset = frozenset()  # ...for which list (another list drops it)
        self._name_filter = ""                   # the list's search field
        self._picked: list = []                  # rows picked in the list: only they are renamed
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
        from msl_tools.msl.tools.maya.rename.buttons import GroupButton
        self._quick_buttons = {}
        self._groups = {}
        for group, _title, tone, _keys in QUICK_GROUPS:
            self._groups[group] = GroupButton(tone, icon_size=QUICK_ICON_SIZE)

        for key, text, tooltip in EDGE:
            icon = icons.get_icon(QUICK_ICONS[key], sub_folder="actions")
            button = QuickButton(icon, text, f"{tooltip}\nThe list shows what it does while the pointer is here",
                                 icon_size=QUICK_ICON_SIZE)
            button.setObjectName("renameQuick")
            button.setProperty("tone", QUICK_TONES.get(key, ""))
            self._quick_buttons[key] = button

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
        self._order.setToolTip("The order objects get their numbers / letters in.\n"
                               "Chains: the numbers start again in every chain (parent → child), {A} counts the chains\n"
                               "— five fingers picked at once: finger_A_01…03, finger_B_01…03")
        self._end_last = HoverButton("end", "Chains: the last one of each chain gets “end” instead of its number")
        self._end_last.setObjectName("renameToggle")
        self._end_last.setCheckable(True)

        self._prefix = WordField()
        self._prefix.setPlaceholderText("prefix_")
        self._prefix.setToolTip("Enter or + puts it in front of every name (not twice)")
        self._prefix_add = HoverButton("+", "Put the prefix in front of every name")
        self._prefix_add.setObjectName("renameAdd")
        self._suffix = WordField()
        self._suffix.setPlaceholderText("_suffix")
        self._suffix.setToolTip("Enter or + puts it at the end of every name (not twice)")
        self._suffix_add = HoverButton("+", "Put the suffix at the end of every name")
        self._suffix_add.setObjectName("renameAdd")
        self._side = SideButton()
        self._kind = KindButton()

        # Recipes: one button right of Rename, its menu holds them (a row of chips took a whole line)
        self._recipes = QuickButton(icons.get_icon("bookmark", sub_folder="actions"), "R", "")
        self._recipes.setObjectName("renameRecipe")
        self._list_source = SegmentedControl(list(self.LIST_SOURCES), "Selected")
        self._list_source.setToolTip("Selected: what is selected · Hierarchy: it and everything under it\n"
                                     "(shapes stay out — Maya renames them with their transforms)")
        self._list_search = qt.QtWidgets.QLineEdit()  # a plain filter: no word completion here
        self._list_search.setObjectName("renameListSearch")
        self._list_search.setPlaceholderText("Find in the list")
        self._list_search.setClearButtonEnabled(True)
        self._list_search.setMinimumWidth(80)
        self._list_search.hide()
        self._list_search.installEventFilter(self)
        self._search_button = GlyphButton("", "Find in the list (Ctrl+F)", size=qt.QtCore.QSize(22, 20))
        self._search_button.setObjectName("renameLock")
        self._search_button.set_icon(icons.get_icon("search", sub_folder="actions"))
        self._list_search.setToolTip("Only the rows whose name holds this — renames act on them only")
        self._kinds = ChipBar(multiple=True)
        self._kinds.setObjectName("renameKinds")
        self._kinds.setToolTip("Show and select one kind only · Ctrl+click: several · “all”: everything again")
        self._count = qt.QtWidgets.QLabel("")
        self._count.setObjectName("renameCount")
        self._lock = ToggleIconButton(icons.get_icon("lock", sub_folder="actions"), "Hold the list",
                                      "The list stays on these objects — selecting others doesn't change it")
        self._lock.setObjectName("renameToggleIcon")
        self._list_fold = GlyphButton("", "Fold the list", size=qt.QtCore.QSize(16, 20))
        self._list_fold.setObjectName("renameLock")
        self._list_fold.set_icon(icons.get_icon("chevron_down", sub_folder="actions"))
        self._select_listed = GlyphButton("", "Select the objects in the list", size=qt.QtCore.QSize(22, 20))
        self._select_listed.setObjectName("renameLock")
        self._select_listed.set_icon(icons.get_icon("select_all", sub_folder="actions"))
        self._preview = PreviewList()
        self._list_grip = HeightGrip()
        self._list_grip.setObjectName("renameListGrip")
        self._status = qt.QtWidgets.QLabel("")
        self._status.setObjectName("renameStatus")
        self._status.setWordWrap(True)
        self._status.hide()

    def _build_layout(self) -> None:
        # the quick groups with Rename on one row, the name field under it, as wide as the window
        self._quick = qt.QtWidgets.QWidget()
        quick = qt.QtWidgets.QHBoxLayout(self._quick)
        quick.setContentsMargins(0, 0, 0, 0)
        quick.setSpacing(3)
        for button in self._groups.values():
            quick.addWidget(button)
        quick.addStretch(1)
        quick.addWidget(self._number_toggle)
        quick.addWidget(self._rename)
        quick.addWidget(self._recipes)
        name_row = qt.QtWidgets.QHBoxLayout()
        name_row.setSpacing(4)
        name_row.addWidget(self._quick_buttons["first_off"])
        name_row.addWidget(self._field, 1)
        name_row.addWidget(self._quick_buttons["last_off"])

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
        numbers.addWidget(self._end_last)

        affix = qt.QtWidgets.QHBoxLayout()
        affix.setSpacing(4)
        affix.addWidget(self._prefix_add)
        affix.addWidget(self._prefix, 1)
        affix.addWidget(self._side)
        affix.addWidget(self._kind)
        affix.addWidget(self._suffix, 1)
        affix.addWidget(self._suffix_add)
        affix.addWidget(self._favorites_button())

        list_head = qt.QtWidgets.QHBoxLayout()
        list_head.setSpacing(6)
        list_head.addWidget(self._list_fold)
        list_head.addWidget(self._list_source)
        list_head.addWidget(self._count, 1)
        list_head.addWidget(self._list_search, 1)
        list_head.addWidget(self._search_button)
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
        column.addLayout(list_head)
        # what folds with the list's chevron: kinds + search, the strip + the list, its grip
        self._list_body = qt.QtWidgets.QWidget()
        list_body = qt.QtWidgets.QVBoxLayout(self._list_body)
        list_body.setContentsMargins(0, 0, 0, 0)
        list_body.setSpacing(6)
        list_body.addWidget(self._kinds)
        self._strip_frame = self._objects_strip()
        self._lay_strip(True)   # a row over the list: the list keeps the height of its rows
        list_body.addWidget(self._strip_frame)
        list_body.addWidget(self._preview)
        list_body.addWidget(self._list_grip)
        list_body.addWidget(self._empty_hint())
        column.addWidget(self._list_body)
        column.addWidget(self._status)
        column.addWidget(self._words_card())
        column.addWidget(self._find_card())
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
        for group, button in self._groups.items():
            button.run_requested.connect(lambda group=group: self._run(self._quick_operation(self._group_last(group))))
            button.hovered.connect(lambda on, group=group:
                                   self._set_hover(self._quick_operation(self._group_last(group)) if on else None))
            button.menu_requested.connect(lambda group=group: self._on_group_menu(group))
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
        self._end_last.toggled.connect(self._on_numbers_changed)
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
        self._recipes.clicked.connect(self._on_recipes_menu)
        self._list_source.current_changed.connect(self._on_list_source)
        self._kinds.clicked.connect(self._on_kind_chip)
        self._select_listed.clicked.connect(self._on_select_listed)
        self._preview.renamed.connect(self._on_one_renamed)
        self._preview.included_changed.connect(self._on_included)
        self._preview.include_all.connect(self._on_include_all)
        self._list_grip.dragged.connect(self._on_grip_dragged)
        self._list_grip.released.connect(self._on_grip_released)
        self._list_grip.reset.connect(self._on_grip_reset)
        self._preview.lock_requested.connect(self._on_lock_one)
        self._preview.use_name.connect(self._use_name)
        self._preview.select_requested.connect(self._on_select_one)
        self._preview.show_requested.connect(self._on_show_one)
        self._preview.rows_picked.connect(self._on_rows_picked)
        self._preview.frame_requested.connect(lambda _uuid: scene.frame_selection())
        self._preview.order_changed.connect(self._on_order_changed)
        self._preview.order_reset.connect(self._on_order_reset)
        self._preview.mirror_requested.connect(self._on_mirror_one)
        self._preview.branch_requested.connect(self._on_branch)
        self._preview.fix_requested.connect(self._on_fix_menu)
        self._preview.paste_requested.connect(self._on_paste_names)
        self._preview.paste_hovered.connect(lambda on: self._set_hover(self._paste_operation() if on else None))
        self._list_search.textChanged.connect(self._on_list_search)
        self._list_fold.clicked.connect(lambda: self._set_list_open(self._list_body.isHidden()))
        self._search_button.clicked.connect(self._open_search)
        find = qt.QtGui.QShortcut(qt.QtGui.QKeySequence("Ctrl+F"), self)
        find.setContext(qt.QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(self._open_search)
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
        self._end_last.setChecked(bool(settings.get("end_last", False)))
        self._prefix.setText(settings.get("prefix", ""))
        self._preview.set_user_height(settings.get("list_height") or None)
        source = settings.get("list_source", "Selected")
        self._list_source.set_current(source if source in self.LIST_SOURCES else "Selected", animate=False)
        self._suffix.setText(settings.get("suffix", ""))
        self._apply_words_settings()
        self._apply_find_settings()
        self._apply_objects_settings()
        for group in self._groups:
            self._show_group(group)
        folded = dict(settings.get("folded") or {})
        for key in ("words", "find"):
            self._show_card(key, not folded.get(key, True), save=False)
        self._set_list_open(not dict(settings.get("folded") or {}).get("list", False), save=False)
        self._loading = False
        self._sync_number_row()
        self._refresh_recipes()

    def _save_settings(self, *_args) -> None:
        if self._loading:
            return
        values = {"template": self._field.text(), "start": self._start.value(1), "step": self._step.value(1),
                  "padding": self._padding.value(2), "order": self._order.currentText(),
                  "end_last": self._end_last.isChecked(),
                  "prefix": self._prefix.text(), "suffix": self._suffix.text()}
        values.update(self._words_settings())
        values.update(self._find_settings())
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value
        self._mark_recipes()

    # ------------------------------------------------------------------ recipes

    def _recipe_values(self) -> dict:
        return {"template": self._field.text().strip(), "start": self._start.value(1), "step": self._step.value(1),
                "padding": self._padding.value(2), "order": self._order.currentText(),
                "end_last": self._end_last.isChecked()}

    def _refresh_recipes(self) -> None:
        self._mark_recipes()

    def _mark_recipes(self) -> None:
        """The button is lit (the accent) while the settings on screen are one of the recipes."""
        if not hasattr(self, "_recipes"):
            return
        matching = self.recipes.matching(self._recipe_values())
        self._recipes.setToolTip(("Recipe: " + ", ".join(matching) if matching else "Recipes") +
                                 "\nA click: the recipes — a way of naming (the name, its numbering and order)"
                                 "\nto put in, then Rename; save the current one, change or remove one")
        on = bool(matching)
        if bool(self._recipes.property("on")) != on:
            self._recipes.setProperty("on", on)
            repolish(self._recipes)

    def _on_recipes_menu(self) -> None:
        """Every recipe (its name, its template on the right; the matching one ticked), "Change"
        submenus, a field to save the current settings as one, and the built-in ones back."""
        from msl_tools.msl.ui.theme.qss import make_rounded_popup
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        recipes = self.recipes.all()
        matching = self.recipes.matching(self._recipe_values())
        for name, values in recipes.items():
            action = menu.addAction(f"{name}\t{values.get('template', '')}", lambda name=name: self._on_recipe(name))
            action.setCheckable(True)
            action.setChecked(name in matching)
        if recipes:
            change = make_rounded_popup(menu.addMenu("Change"))
            for name in recipes:
                one = make_rounded_popup(change.addMenu(name))
                one.addAction("Save the current settings over it",
                              lambda name=name: (self.recipes.save(name, self._recipe_values()),
                                                 self._refresh_recipes(), self._say(f"Saved over “{name}”", "done")))
                one.addAction("Remove", lambda name=name: (self.recipes.remove(name), self._refresh_recipes()))
            menu.addSeparator()
        title = menu.addAction("Save the current as a recipe:")
        title.setEnabled(False)
        _field_action(menu, "", "Recipe name", self._on_save_recipe)
        menu.addSeparator()
        menu.addAction("Back to the built-in recipes", lambda: (self.recipes.reset(), self._refresh_recipes()))
        menu.exec(self._recipes.mapToGlobal(qt.QtCore.QPoint(0, self._recipes.height())))

    def _on_recipe(self, name: str) -> None:
        recipe = self.recipes.all().get(name)
        if not recipe:
            return
        self._loading = True
        self._field.setText(recipe.get("template", ""))
        self._start.set_value(recipe.get("start", 1))
        self._step.set_value(recipe.get("step", 1))
        self._padding.set_value(recipe.get("padding", 2))
        index = self._order.findText(recipe.get("order", rules.ORDER_SELECTION))
        self._order.setCurrentIndex(max(index, 0))
        self._end_last.setChecked(bool(recipe.get("end_last", False)))
        self._loading = False
        self._set_source("template")
        self._sync_number_row()
        self._save_settings()
        self._update_preview()
        self._field.setFocus()
        self._say(f"Recipe “{name}” — the list shows what it does · Rename (Enter) to apply")

    def _on_save_recipe(self, name: str) -> None:
        if not self._field.text().strip():
            self._say("Type the name first — a recipe keeps the name with its numbering", "error")
            return
        self.recipes.save(name, self._recipe_values())
        self._refresh_recipes()
        self._say(f"Saved the recipe “{name}”", "done")

    def _sides(self) -> rules.Sides:
        return rules.Sides.from_settings(self._settings.get("sides"))

    def _suffixes(self) -> dict:
        saved = dict(self._config["type_suffixes"])  # a missing key reads as an empty node
        return saved or dict(rules.DEFAULT_TYPE_SUFFIXES)

    def _numbering(self) -> rules.Numbering:
        return rules.Numbering(start=self._start.value(1), step=self._step.value(1),
                               padding=self._padding.value(2), order=self._order.currentText(),
                               end_last=self._end_last.isChecked())

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
        """Reads the objects again (the selection — with everything under it on "Hierarchy" —, or
        the held ones) and redraws the list. A kind filter holds the list on its objects while the
        selection in Maya is the one the filter made; a selection made by hand lets it go."""
        if self._filter_base is not None and self._locked is None \
                and scene.selection_uuids() != self._filter_selection:
            self._kind_filter, self._filter_base = set(), None   # the user picked something else
            self._picked = []
        held = self._locked if self._locked is not None else self._filter_base
        if held is not None:
            items = [path for path in (scene.current(rules.Node(path="", name="", uuid=uuid)) for uuid in held) if path]
        else:
            hierarchy = self._list_source.current() == "Hierarchy"
            items = scene.paths(scene.SCOPE_HIERARCHY if hierarchy else scene.SCOPE_SELECTED)
        self._too_many = len(items) > self.MAX_OBJECTS
        self._all_nodes = scene.nodes(items[:self.MAX_OBJECTS])
        listed = frozenset(node.uuid for node in self._all_nodes)
        if self._manual_order and listed != self._manual_set:
            self._manual_order, self._manual_set = [], frozenset()   # another list: its own order
        if self._manual_order:
            place = {uuid: index for index, uuid in enumerate(self._manual_order)}
            self._all_nodes.sort(key=lambda node: place.get(node.uuid, len(place)))
        needle = self._name_filter.lower()
        self._nodes = [node for node in self._all_nodes
                       if (not self._kind_filter or node.kind in self._kind_filter)
                       and (not needle or needle in (node.namespace + node.name).lower())]
        self._show_empty(not self._all_nodes)
        self._refresh_kinds()
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
            changes = self._convention_marks(nodes)
            self._preview.set_changes(changes, bool(self._manual_order), self._tree_view())
            self._preview.set_picked(self._picked)
            self._show_count(nodes, None, marked=sum(1 for change in changes if change.state == "nonconform"))
            return
        try:
            changes = self._plan(operation, nodes)
        except ValueError as error:  # a broken regular expression
            self._preview.set_changes([rules.Change(node, node.name, "idle") for node in nodes], bool(self._manual_order), self._tree_view())
            self._say(str(error), "error")
            return
        self._preview.set_changes(changes, bool(self._manual_order), self._tree_view())
        self._preview.set_picked(self._picked)
        self._show_count(nodes, changes, operation)

    def _convention_marks(self, nodes) -> list:
        """Idle rows; with a convention set, the names that don't follow it say why."""
        pattern = self._convention_pattern()
        sides, suffixes = self._sides(), self._suffixes()
        changes = []
        for node in nodes:
            why = rules.convention_problem(node, pattern, sides, suffixes) if pattern else ""
            if why:
                changes.append(rules.Change(node, node.name, "nonconform", why))
            elif node.locked:
                changes.append(rules.Change(node, node.name, "locked", node.locked))
            else:
                changes.append(rules.Change(node, node.name, "idle"))
        return changes

    # Objects unticked in the list: left out of every rename for this Maya session (by uuid, kept
    # by the CLASS so closing the window doesn't forget them).
    _left_out: set = set()

    def _plan(self, operation, nodes) -> list:
        """The changes `operation` would make; the objects left out keep their names and don't take
        a number (the others are numbered without gaps). Raises ValueError like operation.names."""
        respect = getattr(operation, "respect_left_out", True)  # a name typed for one row overrides it
        picked = set(self._picked) & {node.uuid for node in nodes} if respect else set()
        kept = [node for node in nodes if not respect
                or (node.uuid not in self._left_out and (not picked or node.uuid in picked))]
        planned = {change.node.uuid: change
                   for change in rules.plan(kept, operation.names(kept), operation.drop_namespace)}
        return [planned.get(node.uuid)
                or rules.Change(node, node.name, "skipped", "left out" if node.uuid in self._left_out else "not picked")
                for node in nodes]

    def _on_included(self, uuid: str, included: bool) -> None:
        if included:
            type(self)._left_out.discard(uuid)
        else:
            type(self)._left_out.add(uuid)
        self._update_preview()

    def _on_include_all(self) -> None:
        type(self)._left_out.clear()
        self._update_preview()

    def _show_count(self, nodes, changes, operation=None, marked: int = 0) -> None:
        found = operation is not None and operation.nodes is not None
        if found:
            what = f"{len(nodes)} found"
        elif self._kind_filter or self._name_filter:
            what = f"{len(nodes)} of {len(self._all_nodes)}"
        else:
            what = f"{len(nodes)} " + ("in the hierarchy" if self._list_source.current() == "Hierarchy" else "selected")
        if self._locked is not None and not found:
            what += " · held"
        if not nodes:
            text = "Nothing found" if found else "Nothing selected"
        elif changes is None:
            text = what + (f" · {marked} not by the convention" if marked else "")
        else:
            changing = sum(1 for change in changes if change.changes)
            look = sum(1 for change in changes if change.state in ("clash", "error"))
            out = sum(1 for change in changes if change.state == "skipped" and change.note == "left out")
            if self._picked:
                what += f" · {len([uuid for uuid in self._picked if uuid in {c.node.uuid for c in changes}])} picked"
            text = (f"{what} · {changing} will change" + (f" · {look} to look at" if look else "")
                    + (f" · {out} left out" if out else ""))
            if operation is not None and operation is self._hover:
                text = f"{operation.label}: " + text
        if getattr(self, "_too_many", False):
            text += f" · only the first {self.MAX_OBJECTS}"
        self._count.setText(text)

    # ------------------------------------------------------------------ operations

    def _quick_operation(self, key: str) -> _Operation:
        label = next(text for each, text, _tip in QUICK + EDGE if each == key)
        if key == "mirror":
            sides = self._sides()
            return _Operation(label, _each(lambda node: rules.mirror(node.name, sides)))
        if key == "shapes":
            return self._shapes_operation()
        if key == "clean":
            suffixes = self._suffixes()
            return _Operation(label, _each(lambda node: rules.clean_import(node.name, suffixes)))
        return _Operation(label, _each(_EACH[key]), drop_namespace=key == "namespace_off")

    def _shapes_operation(self) -> _Operation:
        """The shapes of the listed objects, each to "<transform>Shape" (the second "…Shape1")."""
        expected: dict = {}

        def shapes():
            found, names = scene.shapes_of(self._nodes)
            expected.clear()
            expected.update({node.uuid: name for node, name in zip(found, names)})
            return found
        return _Operation("Shape", lambda nodes: [expected.get(node.uuid, node.name) for node in nodes], nodes=shapes)

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
            changes = self._plan(operation, nodes)
        except ValueError as error:
            self._say(str(error), "error")
            return 0
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
        self._sync_end_toggle()

    def _sync_end_toggle(self) -> None:
        chains = self._order.currentText() == rules.ORDER_CHAINS
        if chains != self._end_last.isVisibleTo(self._number_row):
            self._end_last.setVisible(chains)  # (in the row already: no stray window)

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
        self._sync_end_toggle()
        self._save_settings()
        self._update_preview()

    def _on_prefix(self) -> None:
        prefix = self._prefix.text().strip()
        if not prefix:
            self._prefix.setFocus()
            return
        self._run(self._prefix_operation())  # always the objects ("into the field" is for words)

    def _on_suffix(self) -> None:
        suffix = self._suffix.text().strip()
        if not suffix:
            self._suffix.setFocus()
            return
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

    def _on_grip_dragged(self, distance: int) -> None:
        if getattr(self, "_grip_start", None) is None:
            self._grip_start = self._preview.height()
        self._preview.set_user_height(self._grip_start + distance)

    def _on_grip_released(self) -> None:
        self._grip_start = None
        if self._settings.get("list_height") != self._preview.height():
            self._settings["list_height"] = self._preview.height()

    def _on_grip_reset(self) -> None:
        self._grip_start = None
        self._preview.set_user_height(None)
        self._settings["list_height"] = 0

    def _on_lock(self, locked: bool) -> None:
        source = self._all_nodes if self._kind_filter else self._nodes
        self._locked = [node.uuid for node in source if node.uuid] if locked else None
        self.refresh()

    # ------------------------------------------------------------------ hierarchy and kinds

    def _on_list_source(self, source: str) -> None:
        if self._settings.get("list_source") != source:
            self._settings["list_source"] = source
        self._kind_filter, self._filter_base = set(), None
        self._picked = []
        self.refresh()

    def _refresh_kinds(self) -> None:
        """The kinds in the list as chips with Maya's icons: "all N" first, then by count."""
        counts: dict = {}
        for node in self._all_nodes:
            counts[node.kind] = counts.get(node.kind, 0) + 1
        ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        chips = [("", f"all {len(self._all_nodes)}", "Everything in the list")]
        chips += [(kind, "" if not maya_type_icon(kind).isNull() else kind,
                   f"{kind} · {count}\nOnly these: show them and select them in Maya (Ctrl+click: add)", maya_type_icon(kind))
                  for kind, count in ranked]
        if [key for key, *_rest in chips] != self._kinds.keys() or self._kinds.property("counts") != str(ranked):
            self._kinds.setProperty("counts", str(ranked))
            self._kinds.set_chips(chips)
        self._kinds.set_checked(self._kind_filter or {""})
        wanted = len(ranked) > 1 or bool(self._kind_filter)  # one kind only: nothing to filter
        if wanted != self._kinds.isVisibleTo(self):
            self._kinds.setVisible(wanted)

    def _on_kind_chip(self, kind: str) -> None:
        ctrl = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
        if not kind:
            wanted = set()
        elif ctrl:
            wanted = set(self._kind_filter) ^ {kind}
        else:
            wanted = set() if self._kind_filter == {kind} else {kind}
        base = self._filter_base if self._filter_base is not None else [node.uuid for node in self._all_nodes if node.uuid]
        self._kind_filter = wanted
        self._picked = []   # a kind is a new pick of its own
        shown = [node for node in self._all_nodes if not wanted or node.kind in wanted]
        if self._locked is None:
            self._filter_base = base
            self._filter_selection = {node.uuid for node in shown if node.uuid}
        scene.select_nodes(shown)      # (its SelectionChanged comes back as a refresh — the base holds)
        if not wanted:
            # all again: back to following the selection — which is now the whole list
            self._filter_base, self._filter_selection = None, set()
        self.refresh()
        what = " + ".join(sorted(wanted)) if wanted else "everything"
        self._say(f"Showing and selecting {len(shown)}: {what}")

    def _on_select_listed(self) -> None:
        operation = self._current_operation()
        nodes = operation.nodes() if operation is not None and operation.nodes is not None else self._nodes
        scene.select_nodes(nodes)

    def _hold_list(self, selected_uuids: set) -> None:
        """Keeps the list on its objects while Maya's selection is `selected_uuids` (what the tool
        selected itself) — the same hold a kind filter uses; a selection made by hand lets it go."""
        if self._locked is None:
            if self._filter_base is None:
                self._filter_base = [node.uuid for node in self._all_nodes if node.uuid]
            self._filter_selection = set(selected_uuids)

    def _on_show_one(self, uuid: str) -> None:
        node = next((node for node in self._shown_nodes() if node.uuid == uuid), None)
        if node is None:
            return
        self._hold_list({uuid})   # selecting it must not shrink the list to that one
        scene.show(node)
        self.refresh()
        self._say(f"{node.name} — selected and framed · the list stays until you pick something else")

    def _on_rows_picked(self, uuids: list) -> None:
        """Rows picked in the list (a click, Ctrl / Shift+click): those objects are selected in Maya
        (the list holds) and ONLY THEY are renamed; none picked = the whole list again."""
        shown = {node.uuid: node for node in self._shown_nodes()}
        self._picked = [uuid for uuid in uuids if uuid in shown]
        if self._picked:
            self._hold_list(set(self._picked))
            scene.select_nodes([shown[uuid] for uuid in self._picked])
            first = shown[self._picked[0]].name
            self._say(f"{first} — picked: only it is renamed" if len(self._picked) == 1 else
                      f"{len(self._picked)} picked — only they are renamed · click an empty spot: the whole list")
        else:
            everything = [node for node in self._all_nodes if node.uuid]
            self._hold_list({node.uuid for node in everything})
            scene.select_nodes(everything)
            self._say("The whole list again")
        self.refresh()

    def _on_order_changed(self, order: list) -> None:
        self._manual_order = list(order) + [node.uuid for node in self._all_nodes if node.uuid not in set(order)]
        self._manual_set = frozenset(node.uuid for node in self._all_nodes)
        if self._order.currentText() not in (rules.ORDER_SELECTION, rules.ORDER_CHAINS):
            self._order.setCurrentText(rules.ORDER_SELECTION)
            self._say("Numbers follow the list's order now (order: Selection)")
        self.refresh()

    def _on_order_reset(self) -> None:
        self._manual_order, self._manual_set = [], frozenset()
        self.refresh()

    def _set_list_open(self, opened: bool, save: bool = True) -> None:
        """Folds / unfolds the list (kinds, search, the strip, the list): the head row stays."""
        if opened:
            self._list_body.show()
        else:
            self._list_body.hide()
        self._list_fold.set_icon(UiResources().iconManager.get_icon(
            "chevron_down" if opened else "chevron_right", sub_folder="actions"))
        self._list_fold.setToolTip("Fold the list" if opened else "Unfold the list")
        if save:
            self._save_folded("list", opened)

    def _open_search(self) -> None:
        """The search field opens in the list's head (in place of the count)."""
        if self._list_body.isHidden():
            self._set_list_open(True)
        self._count.hide()
        self._list_search.show()
        self._list_search.setFocus()
        self._list_search.selectAll()

    def _close_search(self) -> None:
        self._list_search.clear()
        self._list_search.hide()
        self._count.show()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._list_search:
            kind = event.type()
            if kind == qt.QtCore.QEvent.Type.KeyPress and event.key() == qt.QtCore.Qt.Key.Key_Escape:
                self._close_search()
                self._field.setFocus()
                return True
            if kind == qt.QtCore.QEvent.Type.FocusOut and not self._list_search.text():
                qt.QtCore.QTimer.singleShot(0, self._close_search)
        return super().eventFilter(watched, event)

    def _on_list_search(self, text: str) -> None:
        self._name_filter = text.strip()
        self.refresh()

    def _on_select_one(self, uuid: str) -> None:
        node = next((node for node in self._shown_nodes() if node.uuid == uuid), None)
        if node is not None:
            scene.select_nodes([node])

    def _shown_nodes(self) -> list:
        operation = self._current_operation()
        return operation.nodes() if operation is not None and operation.nodes is not None else self._nodes

    def _tree_view(self) -> bool:
        """The list as a tree: on "Hierarchy", in the Outliner's order (not one dragged by hand)."""
        return self._list_source.current() == "Hierarchy" and not self._manual_order

    # ------------------------------------------------------------------ one row's actions

    def _one(self, uuid: str):
        return next((node for node in self._shown_nodes() if node.uuid == uuid), None)

    def _run_one(self, node, label: str, name: str) -> None:
        operation = _Operation(label, lambda nodes: [name], nodes=lambda: [node])
        operation.respect_left_out = False
        self._run(operation, remember=False)

    def _on_mirror_one(self, uuid: str) -> None:
        node = self._one(uuid)
        if node is None:
            return
        name = rules.mirror(node.name, self._sides())
        if name == node.name:
            self._say(f"“{node.name}” says no side to swap (lf_ / rt_, _L / _R, left / right)", "error")
            return
        self._run_one(node, "Other side", name)

    def _on_branch(self, uuid: str) -> None:
        node = self._one(uuid)
        if node is not None:
            count = scene.select_branch(node)
            self._say(f"Selected {node.name} and everything under it: {count}")

    def _on_fix_menu(self, uuid: str, position) -> None:
        """A problem dot clicked: the fixes for that row's problems, for this one object only."""
        from msl_tools.msl.ui.theme.qss import make_rounded_popup
        node = self._one(uuid)
        if node is None:
            return
        issues = dict(self._preview._row_issues.get(uuid, []))
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        suffixes = self._suffixes()
        if "same" in issues:
            def unique():
                taken = set(scene.all_short_names())
                self._run_one(node, "Make unique", rules.unique_names([node], taken)[0])
            menu.addAction("Make it unique (_01, _02…)", unique)
        if "bad" in issues:
            fixed, cleaned = rules.sanitize(node.name), rules.clean_import(node.name, suffixes)
            if fixed != node.name:
                menu.addAction(f"Fix the signs → {fixed}", lambda: self._run_one(node, "Fix", fixed))
            if cleaned != node.name:
                menu.addAction(f"Clean the leftovers → {cleaned}", lambda: self._run_one(node, "Clean", cleaned))
        if "convention" in issues:
            fixed = rules.convention_fix(node, self._convention_pattern(), self._sides(), suffixes)
            if fixed and fixed != node.name:
                menu.addAction(f"By the convention → {fixed}", lambda: self._run_one(node, "Fix by the convention", fixed))
            else:
                hint = menu.addAction("The convention can't be worked out for this name")
                hint.setEnabled(False)
        if "shape" in issues:
            wrong = scene.shape_mismatches([node]).get(uuid, [])
            for shape, wanted in wrong:
                menu.addAction(f"Name its shape → {wanted}",
                               lambda shape=shape, wanted=wanted: self._run_one(shape, "Shape", wanted))
        if menu.isEmpty():
            return
        menu.exec(position)

    def _paste_operation(self) -> "_Operation | None":
        from msl_tools.msl.tools.maya.rename.preview import paste_lines
        names = paste_lines(qt.QtWidgets.QApplication.clipboard().text())
        if not names:
            return None
        return _Operation("Paste names", lambda nodes: [names[index] if index < len(names) else node.name
                                                         for index, node in enumerate(nodes)])

    def _on_paste_names(self) -> None:
        from msl_tools.msl.tools.maya.rename.preview import paste_lines
        operation = self._paste_operation()
        if operation is None:
            self._say("Copy a column of names first — one per line", "error")
            return
        self._set_hover(None)
        count = len(paste_lines(qt.QtWidgets.QApplication.clipboard().text()))
        renamed = self._run(operation)
        rows = len(self._nodes)
        if renamed and count != rows:
            self._say(self._status.text() + f" · {count} names for {rows} rows", "done")

    def _on_one_renamed(self, uuid: str, text: str) -> None:
        node = next((node for node in self._shown_nodes() if node.uuid == uuid), None)
        if node is None:
            return
        operation = _Operation("Rename one", lambda nodes: [text], nodes=lambda: [node])
        operation.respect_left_out = False
        self._run(operation, remember=False)

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
        """What the panel has to say goes to the window's header (status_changed); the label only
        keeps the text (never shown: a line of its own made everything under it jump)."""
        self._status.setText(text)
        self.status_changed.emit(text, state)

    # ------------------------------------------------------------------ the quick groups

    def _group_last(self, group: str) -> str:
        """The action of `group` used last (its first one until then)."""
        keys = next(keys for key, _title, _tone, keys in QUICK_GROUPS if key == group)
        last = dict(self._settings.get("quick_last") or {}).get(group, "")
        return last if last in keys else keys[0]

    def _show_group(self, group: str) -> None:
        key = self._group_last(group)
        text, tooltip = next((text, tooltip) for k, text, tooltip in QUICK if k == key)
        title = next(title for g, title, _tone, _keys in QUICK_GROUPS if g == group)
        button = self._groups[group]
        button.set_source_icon(UiResources().iconManager.get_icon(QUICK_ICONS[key], sub_folder="actions"))
        button.setToolTip(f"{tooltip}\nClick: do it · the corner, a right click or holding it: all of “{title}”\n"
                          "The list shows what it does while the pointer is here")

    def _on_group_menu(self, group: str) -> None:
        """Every action of the group with its icon and name: hovered = the list shows it, a click
        does it and makes it the group's button."""
        from msl_tools.msl.ui.icon_manager import tinted_menu_icon
        from msl_tools.msl.ui.theme.qss import make_rounded_popup
        button = self._groups[group]
        button.setDown(False)
        keys = next(keys for g, _title, _tone, keys in QUICK_GROUPS if g == group)
        last = self._group_last(group)
        icons = UiResources().iconManager
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        for key in keys:
            text, tooltip = next((text, tooltip) for k, text, tooltip in QUICK if k == key)
            name = tooltip.split(" — ")[0].split(" (")[0]
            icon = tinted_menu_icon(icons.get_icon(QUICK_ICONS[key], sub_folder="actions"), button._icon_color,
                                    self.devicePixelRatioF(), side=18)
            action = menu.addAction(icon, name + ("\tlast" if key == last else ""),
                                    lambda key=key: self._use_group_action(group, key))
            action.setToolTip(tooltip)
            action.hovered.connect(lambda key=key: self._set_hover(self._quick_operation(key)))
        menu.setToolTipsVisible(True)
        menu.aboutToHide.connect(lambda: self._set_hover(None))
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height() + 2)))

    def _use_group_action(self, group: str, key: str) -> None:
        last = dict(self._settings.get("quick_last") or {})
        last[group] = key
        self._settings["quick_last"] = last
        self._show_group(group)
        self._run(self._quick_operation(key))

    # ------------------------------------------------------------------ the header's buttons

    def header_widgets(self) -> list:
        """Buttons for the window's header: WORDS and FIND & REPLACE shown / hidden, the settings."""
        icons = UiResources().iconManager
        self._card_toggles = {}
        for key, icon, title, text in (("words", "book", "Words", "The name library by category, the names used last"),
                                       ("find", "replace", "Find & Replace", "Find a part of the names and replace it")):
            button = ToggleIconButton(icons.get_icon(icon, sub_folder="actions"), title, text)
            button.setObjectName("renameHeaderToggle")
            button.setChecked(not self._words.isHidden() if key == "words" else not self._find.isHidden())
            button.toggled.connect(lambda on, key=key: self._show_card(key, on))
            self._card_toggles[key] = button
        gear = GlyphButton("", "Settings: sides, suffixes by kind, the convention, where words go",
                           size=qt.QtCore.QSize(24, 22))
        gear.setObjectName("renameHeaderGear")
        gear.set_icon(icons.get_icon("sliders", sub_folder="actions"))
        gear.clicked.connect(lambda: self._on_settings_menu(gear))
        return [self._card_toggles["words"], self._card_toggles["find"], gear]

    def _show_card(self, key: str, on: bool, save: bool = True) -> None:
        """Shows a card open, or hides it altogether (its header button follows)."""
        card = self._words if key == "words" else self._find
        card.set_open(bool(on))
        if on:
            card.show()
        else:
            card.hide()
            if key == "find" and save:
                self._on_find_folded(False)
        toggle = getattr(self, "_card_toggles", {}).get(key)
        if toggle is not None and toggle.isChecked() != bool(on):
            toggle.blockSignals(True)
            toggle.setChecked(bool(on))
            toggle._follow()
            toggle.blockSignals(False)
        if save:
            self._save_folded(key, bool(on))
        if on and save:
            qt.QtCore.QTimer.singleShot(0, self._reveal_cards)

    def _reveal_cards(self) -> None:
        scroll = self.findChild(StableScrollArea, "renameScroll")
        if scroll is not None:
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())

    def _on_card_toggled(self, key: str, opened: bool) -> None:
        """A click on a card's heading: folding it hides it (the header's button brings it back)."""
        self._show_card(key, opened)

    def _on_settings_menu(self, button) -> None:
        from msl_tools.msl.ui.theme.qss import make_rounded_popup
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.addAction("Sides (left / right / middle)…", self._on_sides_settings)
        menu.addAction("Suffixes by kind…", self._on_suffix_settings)
        menu.addAction("Naming convention…", self._on_convention_menu)
        menu.addSeparator()
        into = menu.addAction("Words go into the name field")
        into.setCheckable(True)
        into.setChecked(self._into_on)
        into.triggered.connect(self._set_into)
        fit = menu.addAction("The window fits its height to what it shows")
        fit.setCheckable(True)
        fit.setChecked(self.fits_height())
        fit.triggered.connect(self.set_fits_height)
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height())))

    # the window asks these (RenameWindow): on unless the user set a height by hand
    fit_changed = qt.QtCore.Signal(bool)

    def fits_height(self) -> bool:
        return bool(self._settings.get("fit_height", True))

    def set_fits_height(self, on: bool) -> None:
        self._settings["fit_height"] = bool(on)
        self.fit_changed.emit(bool(on))

    def content_height_change(self) -> int:
        """How much taller (+) or shorter (-) the panel wants to be to show everything without
        scrolling and without empty room under it."""
        scroll = self.findChild(StableScrollArea, "renameScroll")
        if scroll is None or scroll.widget() is None:
            return 0
        body = scroll.widget()
        return body.sizeHint().height() - scroll.viewport().height()

    # ------------------------------------------------------------------ an empty list

    def _empty_hint(self) -> qt.QtWidgets.QWidget:
        """What shows instead of an empty list: a line, and the names used last to start from."""
        self._empty = qt.QtWidgets.QWidget()
        self._empty.hide()
        box = qt.QtWidgets.QVBoxLayout(self._empty)
        box.setContentsMargins(2, 2, 2, 2)
        box.setSpacing(4)
        line = qt.QtWidgets.QLabel("Select objects in Maya to rename them · the checks above look at the whole "
                                   "scene while nothing is selected")
        line.setObjectName("renameHint")
        line.setWordWrap(True)
        self._empty_recent = ChipBar()
        self._empty_recent.setToolTip("Names used last — a click puts one into the name field")
        self._empty_recent.clicked.connect(self._use_name)
        box.addWidget(line)
        box.addWidget(self._empty_recent)
        self._is_empty = None
        return self._empty

    def _show_empty(self, empty: bool) -> None:
        if empty:
            recent = self.library.recent()[:6]
            self._empty_recent.set_chips([(text, text, "") for text in recent])
            if bool(recent) == self._empty_recent.isHidden():
                self._empty_recent.setVisible(bool(recent))
        if empty == self._is_empty:
            return
        self._is_empty = empty
        for widget in (self._preview, self._list_grip):
            widget.setVisible(not empty)
        self._empty.setVisible(empty)

    def focus_field(self) -> None:
        self._field.setFocus()
        self._field.selectAll()
