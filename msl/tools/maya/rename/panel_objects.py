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
        kinds_caption = qt.QtWidgets.QLabel("KINDS IN THE LIST — a click selects that kind")
        kinds_caption.setObjectName("renameSubtitle")
        self._kinds = ChipBar()
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
        for button in (self._check_same, self._check_bad, self._check_skin):
            row.addWidget(button)
        row.addStretch(1)
        sets_caption = qt.QtWidgets.QLabel("SETS — for this Maya session")
        sets_caption.setObjectName("renameSubtitle")
        self._sets = ChipBar(add_text="+ set of the selection", name_placeholder="Set name, then Enter",
                             custom_menu=True)
        self._sets.setToolTip("Click: select it · right click: add / take out the selection, a Maya set")
        for widget in (kinds_caption, self._kinds, checks_caption, checks, sets_caption, self._sets):
            card.body_layout.addWidget(widget)
        return card

    def _connect_objects(self) -> None:
        self._objects.toggled.connect(lambda opened: (self._save_folded("objects", opened), self._refresh_objects()))
        self._kinds.clicked.connect(self._on_kind_chip)
        self._check_same.clicked.connect(self._on_check_same)
        self._check_bad.clicked.connect(self._on_check_bad)
        self._check_skin.clicked.connect(self._on_check_skin)
        self._sets.clicked.connect(self._on_set)
        self._sets.add_requested.connect(self._on_add_set)
        self._sets.menu_requested.connect(self._on_set_menu)

    def _apply_objects_settings(self) -> None:
        folded = dict(self._settings.get("folded") or {})
        self._objects.set_open(not folded.get("objects", True))
        self._refresh_sets()

    def _refresh_objects(self) -> None:
        counts: dict = {}
        for node in self._nodes:
            counts[node.kind] = counts.get(node.kind, 0) + 1
        ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        if self._objects.is_open():
            self._kinds.set_chips([(kind, f"{kind} {count}", f"Select the {count} {kind} in the list")
                                   for kind, count in ranked])
        parts = [f"{kind} {count}" for kind, count in ranked[:3]]
        if self._quick_sets:
            parts.append(f"{len(self._quick_sets)} sets")
        self._objects.set_summary(" · ".join(parts))

    # ------------------------------------------------------------------ kinds and checks

    def _on_kind_chip(self, kind: str) -> None:
        nodes = [node for node in self._nodes if node.kind == kind]
        scene.select_nodes(nodes)
        self._say(f"Selected {len(nodes)} {kind}")

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
