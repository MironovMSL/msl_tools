# tools/maya/rename/panel_objects.py
"""The rename panel's OBJECTS card: what is selected by kind (a click selects one kind), checks
of names (the same short name twice in the scene, names Maya would refuse), the joints a mesh is
skinned to, and quick sets of objects for this session. Methods of RenamePanel, kept apart by
concern."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.rename import rules, scene
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard


class _ObjectsMixin:

    # Quick sets: name -> uuids. Kept by the CLASS for the Maya session (the window may be closed
    # and opened again); never saved — a uuid means nothing in another scene.
    _quick_sets: dict = {}

    def _objects_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        card = self._objects = FoldingCard("OBJECTS", icons.get_icon("select_all", sub_folder="actions"))
        checks_caption = qt.QtWidgets.QLabel("CHECK — in the selection and under it (nothing selected: the scene)")
        checks_caption.setObjectName("renameSubtitle")
        checks_caption.setWordWrap(True)
        checks = qt.QtWidgets.QWidget()
        row = qt.QtWidgets.QHBoxLayout(checks)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._check_same = qt.QtWidgets.QPushButton("Same names")
        self._check_same.setToolTip("Select objects whose short name another object of the scene has too\n"
                                    "(“More than one object matches name”)")
        self._check_bad = qt.QtWidgets.QPushButton("Bad names")
        self._check_bad.setToolTip("Select names with Cyrillic letters, spaces, other signs, a digit first, “__”\n"
                                   "— then “fix” on top cleans them")
        self._check_skin = qt.QtWidgets.QPushButton("Skin joints")
        self._check_skin.setToolTip("Select the joints the selected meshes are skinned to")
        self._check_other = qt.QtWidgets.QPushButton("Other side")
        self._check_other.setToolTip("Select the same objects on the other side: lf_arm → rt_arm, arm_L → arm_R")
        for button in (self._check_same, self._check_bad, self._check_skin, self._check_other):
            row.addWidget(button)
        row.addStretch(1)
        from msl_tools.msl.tools.maya.rename.buttons import HoverButton
        clean_caption = qt.QtWidgets.QLabel("CLEAN UP — the list shows what a button does while the pointer is on it")
        clean_caption.setObjectName("renameSubtitle")
        clean_caption.setWordWrap(True)
        clean = qt.QtWidgets.QWidget()
        cleans = qt.QtWidgets.QHBoxLayout(clean)
        cleans.setContentsMargins(0, 0, 0, 0)
        cleans.setSpacing(4)
        self._make_unique = HoverButton("Make unique", "Names another object of the scene has too get _01, _02… "
                                                       "(in the selection and under it, nothing selected: the scene)")
        self._name_related = HoverButton("Name related", "Name what belongs to the listed objects after them: "
                                                         "shading group body_SG, material body_mtl, body_skin, "
                                                         "body_bs, constraints arm_parCon…\n"
                                                         "A shading group or material used by several objects is left alone")
        for button in (self._make_unique, self._name_related):
            cleans.addWidget(button)
        cleans.addStretch(1)
        self._clean_row = (clean_caption, clean)
        lock_caption = qt.QtWidgets.QLabel("LOCK — a locked node can't be renamed, deleted or re-parented "
                                           "(Maya shows it nowhere; here it has a lock in the list)")
        lock_caption.setObjectName("renameSubtitle")
        lock_caption.setWordWrap(True)
        lock_row = qt.QtWidgets.QWidget()
        locks = qt.QtWidgets.QHBoxLayout(lock_row)
        locks.setContentsMargins(0, 0, 0, 0)
        locks.setSpacing(4)
        self._lock_selected = qt.QtWidgets.QPushButton("Lock")
        self._lock_selected.setToolTip("Lock the selected objects (one undo step)")
        self._unlock_selected = qt.QtWidgets.QPushButton("Unlock")
        self._unlock_selected.setToolTip("Unlock the selected objects (one undo step)")
        self._find_locked = qt.QtWidgets.QPushButton("Locked")
        self._find_locked.setToolTip("Select the locked nodes — in the selection and under it, nothing selected: the scene")
        for button in (self._lock_selected, self._unlock_selected, self._find_locked):
            locks.addWidget(button)
        locks.addStretch(1)
        convention_caption = qt.QtWidgets.QLabel("CONVENTION — names that don't follow it are marked in the list")
        convention_caption.setObjectName("renameSubtitle")
        convention_caption.setWordWrap(True)
        from msl_tools.msl.tools.maya.rename.panel import CONVENTION_PLACEHOLDER, TemplateField
        self._convention = TemplateField()
        self._convention.setPlaceholderText(CONVENTION_PLACEHOLDER)
        self._convention.setClearButtonEnabled(True)
        self._convention.setToolTip("The shape every name should have, with the tokens of the name field.\n"
                                    "{side} must be where the object stands, {type} its kind's suffix.\n"
                                    "Empty: no convention")
        self._check_convention = qt.QtWidgets.QPushButton("Check")
        self._check_convention.setToolTip("Select what doesn't follow it — in the selection and under it, "
                                          "nothing selected: the scene")
        convention = qt.QtWidgets.QHBoxLayout()
        convention.setSpacing(4)
        convention.addWidget(self._convention, 1)
        convention.addWidget(self._check_convention)
        self._fix_convention = HoverButton("Fix", "Put the listed names right by the convention: the side where the "
                                                  "object stands, its kind's suffix — what it says in between stays")
        convention.addWidget(self._fix_convention)
        sets_caption = qt.QtWidgets.QLabel("SETS — for this Maya session")
        sets_caption.setObjectName("renameSubtitle")
        self._sets = ChipBar(add_text="+ set of the selection", name_placeholder="Set name, then Enter",
                             custom_menu=True)
        self._sets.setToolTip("Click: select it · right click: add / take out the selection, a Maya set")
        for widget in (checks_caption, checks) + self._clean_row + (lock_caption, lock_row, convention_caption):
            card.body_layout.addWidget(widget)
        card.body_layout.addLayout(convention)
        for widget in (sets_caption, self._sets):
            card.body_layout.addWidget(widget)
        return card

    def _connect_objects(self) -> None:
        self._objects.toggled.connect(lambda opened: (self._save_folded("objects", opened), self._refresh_objects()))
        self._check_same.clicked.connect(self._on_check_same)
        self._check_bad.clicked.connect(self._on_check_bad)
        self._check_skin.clicked.connect(self._on_check_skin)
        self._check_other.clicked.connect(self._on_check_other)
        self._lock_selected.clicked.connect(lambda: self._lock_selection(True))
        self._unlock_selected.clicked.connect(lambda: self._lock_selection(False))
        self._find_locked.clicked.connect(self._on_find_locked)
        self._convention.textEdited.connect(self._on_convention_edited)
        self._convention.token_inserted.connect(self._on_convention_edited)
        self._check_convention.clicked.connect(self._on_check_convention)
        for button, operation in ((self._make_unique, self._unique_operation), (self._name_related, self._related_operation),
                                  (self._fix_convention, self._fix_operation)):
            button.clicked.connect(lambda _checked=False, operation=operation: self._run_cleanup(operation))
            button.hovered.connect(lambda on, operation=operation: self._set_hover(operation() if on else None))
        self._sets.clicked.connect(self._on_set)
        self._sets.add_requested.connect(self._on_add_set)
        self._sets.menu_requested.connect(self._on_set_menu)

    def _apply_objects_settings(self) -> None:
        folded = dict(self._settings.get("folded") or {})
        self._objects.set_open(not folded.get("objects", True))
        self._convention.setText(self._settings.get("convention", ""))
        self._refresh_sets()

    def _refresh_objects(self) -> None:
        parts = []
        if self._quick_sets:
            parts.append(f"{len(self._quick_sets)} sets")
        self._objects.set_summary(" · ".join(parts))

    # ------------------------------------------------------------------ kinds and checks

    def _on_check_same(self) -> None:
        found = scene.not_unique(scene.look_in())
        self._select_found(found, "with a name another object has too", "Every name is unique")

    def _on_check_bad(self) -> None:
        found = [path for path in scene.look_in()
                 if (lambda name: rules.problem(name) or rules.notice(name))(path.rpartition("|")[2].rpartition(":")[2])]
        self._select_found(found, "with a name to fix — “fix” on top cleans them", "Every name is fine")

    def _on_check_skin(self) -> None:
        if not scene.selection():
            self._say("Select a skinned mesh first", "error")
            return
        found = scene.skin_joints(scene.selection())
        self._select_found(found, "joints in the skin", "No skinCluster on what is selected")

    def _lock_selection(self, locked: bool) -> None:
        nodes = scene.nodes(scene.selection())
        if not nodes:
            self._say("Select the objects first", "error")
            return
        self._report_lock(*scene.set_locked(nodes, locked), locked)

    def _on_lock_one(self, uuid: str, locked: bool) -> None:
        node = next((node for node in self._shown_nodes() if node.uuid == uuid), None)
        if node is not None:
            self._report_lock(*scene.set_locked([node], locked), locked)

    def _report_lock(self, changed: int, skipped: int, locked: bool) -> None:
        verb = "Locked" if locked else "Unlocked"
        text = f"{verb} {changed}" if changed else f"Nothing to {verb.lower()[:-2]}"
        if skipped:
            text += f" · {skipped} left alone (referenced)"
        self._say(text + (" · Ctrl+Z undoes it" if changed else ""), "done" if changed else "")
        self.refresh()

    def _on_find_locked(self) -> None:
        found = scene.locked_ones(scene.look_in())
        self._select_found(found, "locked", "Nothing is locked")

    # ------------------------------------------------------------------ clean up

    def _unique_operation(self):
        from msl_tools.msl.tools.maya.rename.operations import Operation
        taken: set = set()

        def found():
            listed = scene.nodes(scene.not_unique(scene.look_in()))
            taken.clear()
            taken.update(scene.all_short_names())
            return listed
        return Operation("Make unique", lambda nodes: rules.unique_names(nodes, taken), nodes=found)

    def _related_operation(self):
        from msl_tools.msl.tools.maya.rename.operations import Operation
        expected: dict = {}
        notes: list = []
        suffixes = self._suffixes()

        def found():
            related, names, left = scene.related(self._nodes, suffixes)
            expected.clear()
            expected.update({node.uuid: name for node, name in zip(related, names)})
            notes[:] = left
            return related
        operation = Operation("Name related", lambda nodes: [expected.get(node.uuid, node.name) for node in nodes],
                              nodes=found)
        operation.notes = notes
        return operation

    def _fix_operation(self):
        from msl_tools.msl.tools.maya.rename.operations import Operation
        pattern = self._convention_pattern()
        sides, suffixes = self._sides(), self._suffixes()
        return Operation("Fix by the convention",
                         lambda nodes: [rules.convention_fix(node, pattern, sides, suffixes) or node.name for node in nodes])

    def _run_cleanup(self, make) -> None:
        operation = make()
        if operation.label == "Fix by the convention" and not self._convention_pattern():
            self._say("Type the convention first, e.g. {side}_{name}_{type}", "error")
            return
        if operation.nodes is not None and not operation.nodes():
            self._say({"Make unique": "Every name is unique already",
                       "Name related": "Nothing belongs to the listed objects that could be named after them"}
                      .get(operation.label, "Nothing to do"), "done")
            return
        self._run(operation)
        left = getattr(operation, "notes", [])
        if left:
            self._say(self._status.text() + " · " + "; ".join(left[:2]), "done")

    def _on_check_other(self) -> None:
        nodes = scene.nodes(scene.selection())
        if not nodes:
            self._say("Select objects of one side first", "error")
            return
        sides = self._sides()
        wanted = [node.namespace + rules.mirror(node.name, sides) for node in nodes]
        wanted = [name for name, node in zip(wanted, nodes) if name != node.namespace + node.name]
        found = scene.named(wanted)
        self._select_found(found, "on the other side", "No other side found: the names say no side, or it isn't there")

    def _convention_pattern(self) -> str:
        return self._convention.text().strip()

    def _on_convention_edited(self, *_args) -> None:
        if self._settings.get("convention", "") != self._convention.text():
            self._settings["convention"] = self._convention.text()
        self._update_preview()

    def _on_check_convention(self) -> None:
        pattern = self._convention_pattern()
        if not pattern:
            self._say("Type the convention first, e.g. {side}_{name}_{type}", "error")
            self._convention.setFocus()
            return
        unknown = rules.unknown_tokens(pattern)
        if unknown:
            self._say(f"Unknown token {unknown[0]}", "error")
            return
        sides, suffixes = self._sides(), self._suffixes()
        nodes = scene.nodes(scene.look_in()[:self.MAX_OBJECTS])
        found = [(node, rules.convention_problem(node, pattern, sides, suffixes)) for node in nodes]
        found = [(node, why) for node, why in found if why]
        if not found:
            self._say(f"All {len(nodes)} follow {pattern}", "done")
            return
        scene.select_nodes([node for node, _why in found])
        self._say(f"{len(found)} of {len(nodes)} don't follow {pattern} — the list says why", "error")

    def _select_found(self, found: list, what: str, none: str) -> None:
        if not found:
            self._say(none, "done")
            return
        scene.select(found)
        self._say(f"Selected {len(found)} {what}")

    # ------------------------------------------------------------------ sets

    def _refresh_sets(self) -> None:
        self._sets.set_chips([(name, f"{name} {len(uuids)}", f"{len(uuids)} objects") for name, uuids in
                              self._quick_sets.items()])

    def _set_nodes(self, name: str) -> list:
        return [rules.Node(path="", name="", uuid=uuid) for uuid in self._quick_sets.get(name, [])]

    def _on_set(self, name: str) -> None:
        nodes = self._set_nodes(name)
        scene.select_nodes(nodes)
        found = len(scene.selection())
        self._say(f"Selected “{name}”: {found}" + (f" of {len(nodes)} (the rest is gone)" if found < len(nodes) else ""))

    def _on_add_set(self, name: str) -> None:
        uuids = [node.uuid for node in scene.nodes(scene.selection()) if node.uuid]
        if not uuids:
            self._say("Select the objects for the set first", "error")
            return
        type(self)._quick_sets[name] = uuids
        self._refresh_sets()
        self._refresh_objects()

    def _on_set_menu(self, name: str, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.addAction("Select", lambda: self._on_set(name))
        menu.addAction("Add the selection", lambda: self._change_set(name, add=True))
        menu.addAction("Take the selection out", lambda: self._change_set(name, add=False))
        menu.addSeparator()
        menu.addAction("Make a Maya set of it", lambda: self._make_maya_set(name))
        menu.addAction("Remove", lambda: (type(self)._quick_sets.pop(name, None), self._refresh_sets(),
                                          self._refresh_objects()))
        menu.exec(position)

    def _change_set(self, name: str, add: bool) -> None:
        selected = [node.uuid for node in scene.nodes(scene.selection()) if node.uuid]
        uuids = list(self._quick_sets.get(name, []))
        if add:
            uuids += [uuid for uuid in selected if uuid not in uuids]
        else:
            uuids = [uuid for uuid in uuids if uuid not in set(selected)]
        type(self)._quick_sets[name] = uuids
        self._refresh_sets()

    def _make_maya_set(self, name: str) -> None:
        paths = [path for path in (scene.current(node) for node in self._set_nodes(name)) if path]
        if not paths:
            self._say("None of its objects is in the scene", "error")
            return
        made = scene.make_set(rules.sanitize(name), paths)
        self._say(f"Made the set “{made}” ({len(paths)} objects)", "done")
