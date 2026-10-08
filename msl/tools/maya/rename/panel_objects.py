# tools/maya/rename/panel_objects.py
"""The rename panel's strip beside the list (it was the OBJECTS card): icon buttons, colored by
what they do — FIND (select: the same short name twice, bad names, skin joints, the other side,
locked nodes, names off the convention; how many of the list's objects each would find is a badge),
FIX (make unique, name related, fix by the convention — previewed in the list while hovered),
LOCK / UNLOCK, and quick SETS of objects for this session (a menu). The convention is typed in the
right click menu of its two buttons. Methods of RenamePanel, kept apart by concern."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.rename import rules, scene
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources


class _ObjectsMixin:

    # Quick sets: name -> uuids. Kept by the CLASS for the Maya session (the window may be closed
    # and opened again); never saved — a uuid means nothing in another scene.
    _quick_sets: dict = {}

    # (key, icon, title, what it does, tone, group): the strip, top to bottom. The tone is the
    # icon's color (rename.qss): find = the hue of what it finds, fix = green, lock = orange.
    STRIP = (
        ("same", "names_same", "Same names",
         "Select objects whose short name another object of the scene has too\n"
         "(“More than one object matches name”)", "amber", "find"),
        ("bad", "name_bad", "Bad names",
         "Select names with Cyrillic letters, spaces, other signs, a digit first, “__”, Maya's own (pCube3)\n"
         "— then the quick buttons “fix” / “clean” put them right", "red", "find"),
        ("skin", "skin_joints", "Skin joints", "Select the joints the selected meshes are skinned to",
         "violet", "find"),
        ("other", "side_other", "Other side",
         "Select the same objects on the other side: lf_arm → rt_arm, arm_L → arm_R", "teal", "find"),
        ("check", "convention_check", "Check by the convention",
         "Select what doesn't follow the naming convention — the list says why", "blue", "find"),
        ("unique", "names_unique", "Make unique",
         "Names another object of the scene has too get _01, _02…\n"
         "In the selection and under it — nothing selected: the scene", "green", "fix"),
        ("related", "name_related", "Name related",
         "Name what belongs to the listed objects after them: shading group body_SG, material body_mtl,\n"
         "body_skin, body_bs, constraints arm_parCon… A shading group or material used by several\n"
         "objects is left alone", "green", "fix"),
        ("fix", "convention_fix", "Fix by the convention",
         "Put the listed names right by the convention: the side where the object stands, its kind's\n"
         "suffix — what it says in between stays", "green", "fix"),
        ("locked", "lock_find", "Locked", "Select the locked nodes", "orange", "lock"),
        ("lock", "lock", "Lock",
         "Lock the selected objects (one undo step) — a locked node can't be renamed, deleted or\n"
         "re-parented; Maya shows that nowhere, the list has a lock", "orange", "lock"),
        ("unlock", "unlock", "Unlock", "Unlock the selected objects (one undo step)", "green", "lock"),
        ("sets", "sets", "Sets", "Quick sets of objects for this Maya session", "blue", "sets"),
    )
    WHERE = "\nIn the selection and under it — nothing selected: the scene"
    BADGES = {"same": "{} in the list have a name another object has too",
              "bad": "{} in the list have a name to fix",
              "locked": "{} in the list are locked",
              "check": "{} in the list don't follow it"}

    def _objects_strip(self) -> qt.QtWidgets.QFrame:
        """The strip of icon buttons beside the list."""
        from msl_tools.msl.tools.maya.rename.buttons import StripButton
        icons = UiResources().iconManager
        frame = qt.QtWidgets.QFrame()
        frame.setObjectName("renameStripFrame")
        column = self._strip_layout = qt.QtWidgets.QVBoxLayout(frame)
        column.setContentsMargins(2, 3, 2, 3)
        column.setSpacing(1)
        self._strip_lines: list = []
        self._strip: dict = {}
        self._strip_tips: dict = {}
        group = None
        for key, icon, title, text, tone, kind in self.STRIP:
            if group is not None and kind != group:
                line = qt.QtWidgets.QFrame()
                line.setObjectName("renameStripLine")
                line.setFixedHeight(1)
                self._strip_lines.append(line)
                column.addSpacing(2)
                column.addWidget(line)
                column.addSpacing(2)
            group = kind
            where = self.WHERE if key in ("same", "bad", "check", "locked") else ""
            hover = "\nThe list shows what it does while the pointer is on it" if kind == "fix" else ""
            self._strip_tips[key] = f"{title}\n{text}{where}{hover}"
            button = StripButton(icons.get_icon(icon, sub_folder="actions"), title[:2], self._strip_tips[key], tone)
            self._strip[key] = button
            if key == "skin":  # the joints over a grey mesh
                button.set_under_icon(icons.get_icon("skin_mesh", sub_folder="actions"))
            column.addWidget(button, 0, qt.QtCore.Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        self._badge_timer = qt.QtCore.QTimer(self)
        self._badge_timer.setSingleShot(True)
        self._badge_timer.setInterval(300)
        self._badge_timer.timeout.connect(self._refresh_badges)
        self._convention_text = ""
        return frame

    def _lay_strip(self, flat: bool) -> None:
        """The strip as a column beside the list, or as one ROW while the list is empty."""
        direction = qt.QtWidgets.QBoxLayout.Direction
        self._strip_layout.setDirection(direction.LeftToRight if flat else direction.TopToBottom)
        for line in self._strip_lines:
            if flat:
                line.setFixedSize(1, 18)
            else:
                line.setMinimumWidth(0)
                line.setMaximumWidth(16777215)
                line.setFixedHeight(1)

    def _connect_objects(self) -> None:
        strip = self._strip
        strip["same"].clicked.connect(self._on_check_same)
        strip["bad"].clicked.connect(self._on_check_bad)
        strip["skin"].clicked.connect(self._on_check_skin)
        strip["other"].clicked.connect(self._on_check_other)
        strip["locked"].clicked.connect(self._on_find_locked)
        strip["check"].clicked.connect(self._on_check_convention)
        strip["check"].menu_requested.connect(self._on_convention_menu)
        strip["fix"].menu_requested.connect(self._on_convention_menu)
        strip["lock"].clicked.connect(lambda: self._lock_selection(True))
        strip["unlock"].clicked.connect(lambda: self._lock_selection(False))
        strip["sets"].clicked.connect(self._on_sets_menu)
        strip["sets"].menu_requested.connect(self._on_sets_menu)
        for key, operation in (("unique", self._unique_operation), ("related", self._related_operation),
                               ("fix", self._fix_operation)):
            strip[key].clicked.connect(lambda _checked=False, operation=operation: self._run_cleanup(operation))
            strip[key].hovered.connect(lambda on, operation=operation: self._set_hover(operation() if on else None))

    def _apply_objects_settings(self) -> None:
        self._convention_text = self._settings.get("convention", "")
        self._show_convention()
        self._refresh_sets()

    def _refresh_objects(self) -> None:
        """The badges follow the list — counted a moment later (the scene's names are read)."""
        self._badge_timer.start()

    def _refresh_badges(self) -> None:
        try:
            nodes = list(getattr(self, "_all_nodes", None) or [])
            counts = {"bad": sum(1 for node in nodes if rules.problem(node.name) or rules.notice(node.name)),
                      "locked": sum(1 for node in nodes if node.locked == "locked node"),
                      "check": 0}
            pattern = self._convention_pattern()
            if pattern and nodes and not rules.unknown_tokens(pattern):
                sides, suffixes = self._sides(), self._suffixes()
                counts["check"] = sum(1 for node in nodes if rules.convention_problem(node, pattern, sides, suffixes))
            issues = self._refresh_marks(nodes, pattern)
            counts["same"] = sum(1 for found in issues.values() if any(kind == "same" for kind, _why in found))
            for key, count in counts.items():
                self._strip[key].set_badge(count)
                self._strip[key].setToolTip(self._strip_tips[key] +
                                            ("\n\n" + self.BADGES[key].format(count) if count else ""))
        except RuntimeError:
            pass  # the panel is gone

    def _refresh_marks(self, nodes, pattern: str) -> None:
        """The list's marks: the side each object stands on, and its problems as dots."""
        sides, suffixes = self._sides(), self._suffixes()
        side_of = {node.uuid: sides.of(node.position) for node in nodes
                   if node.uuid and "|" in node.path}  # DAG objects: a material stands nowhere
        same = set(scene.not_unique([node.path for node in nodes if node.path])) if nodes else set()
        shapes = scene.shape_mismatches(nodes[:400]) if nodes else {}
        known_pattern = bool(pattern) and not rules.unknown_tokens(pattern)
        issues = {}
        for node in nodes:
            found = []
            if node.path in same:
                found.append(("same", "Another object of the scene has this name"))
            why = rules.problem(node.name) or rules.notice(node.name)
            if why:
                found.append(("bad", why))
            if known_pattern:
                why = rules.convention_problem(node, pattern, sides, suffixes)
                if why:
                    found.append(("convention", f"Convention: {why}"))
            if node.uuid in shapes:
                found.append(("shape", "Shape: " + ", ".join(f"{shape.name} → {wanted}"
                                                             for shape, wanted in shapes[node.uuid])))
            if found:
                issues[node.uuid] = found
        self._preview.set_marks(side_of, issues)
        return issues

    # ------------------------------------------------------------------ kinds and checks

    def _on_check_same(self) -> None:
        found = scene.not_unique(scene.look_in())
        self._select_found(found, "with a name another object has too", "Every name is unique")

    def _on_check_bad(self) -> None:
        found = [path for path in scene.look_in()
                 if (lambda name: rules.problem(name) or rules.notice(name))(path.rpartition("|")[2].rpartition(":")[2])]
        self._select_found(found, "with a name to fix — “fix” / “clean” on top put them right", "Every name is fine")

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
            self._on_convention_menu()
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

    # ------------------------------------------------------------------ the convention

    def _convention_pattern(self) -> str:
        return (getattr(self, "_convention_text", "") or "").strip()

    def _show_convention(self) -> None:
        pattern = self._convention_pattern()
        said = f"Convention: {pattern}" if pattern else "No convention yet"
        for key in ("check", "fix"):
            title, rest = self._strip_tips[key].split("\n", 1)
            self._strip_tips[key] = f"{title}\n{said} — right click to change it\n" + \
                                    (rest.split("\n", 1)[1] if rest.startswith(("Convention:", "No convention")) else rest)
            self._strip[key].setToolTip(self._strip_tips[key])

    def _on_convention_menu(self) -> None:
        from msl_tools.msl.tools.maya.rename.panel import CONVENTION_PLACEHOLDER
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        title = menu.addAction("The shape every name should have — Enter takes it")
        title.setEnabled(False)
        _field_action(menu, self._convention_pattern(), CONVENTION_PLACEHOLDER, self._set_convention)
        hint = menu.addAction("{side}: where it stands · {type}: its kind's suffix · {name} {#} {A}")
        hint.setEnabled(False)
        if self._convention_pattern():
            menu.addSeparator()
            menu.addAction("No convention", lambda: self._set_convention(""))
        menu.exec(qt.QtGui.QCursor.pos())

    def _set_convention(self, text: str) -> None:
        text = text.strip()
        unknown = rules.unknown_tokens(text) if text else []
        if unknown:
            self._say(f"Unknown token {unknown[0]}", "error")
            return
        self._convention_text = text
        if self._settings.get("convention", "") != text:
            self._settings["convention"] = text
        self._show_convention()
        self._say(f"Convention: {text} — names that don't follow it are marked in the list" if text
                  else "No convention", "done")
        self._update_preview()
        self._refresh_objects()

    def _on_check_convention(self) -> None:
        pattern = self._convention_pattern()
        if not pattern:
            self._on_convention_menu()
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
        names = "\n".join(f"{name} · {len(uuids)}" for name, uuids in self._quick_sets.items())
        self._strip["sets"].setToolTip(self._strip_tips["sets"] + " — a click: the sets\n"
                                       + (names if names else "None yet"))

    def _set_nodes(self, name: str) -> list:
        return [rules.Node(path="", name="", uuid=uuid) for uuid in self._quick_sets.get(name, [])]

    def _on_sets_menu(self) -> None:
        """Every set (a click selects it, "Change" alters one) and a field for a new one."""
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        for name, uuids in self._quick_sets.items():
            menu.addAction(f"{name}  ·  {len(uuids)}", lambda name=name: self._on_set(name))
        if self._quick_sets:
            change = make_rounded_popup(menu.addMenu("Change"))
            for name in self._quick_sets:
                one = make_rounded_popup(change.addMenu(name))
                one.addAction("Add the selection", lambda name=name: self._change_set(name, add=True))
                one.addAction("Take the selection out", lambda name=name: self._change_set(name, add=False))
                one.addSeparator()
                one.addAction("Make a Maya set of it", lambda name=name: self._make_maya_set(name))
                one.addAction("Remove", lambda name=name: self._remove_set(name))
            menu.addSeparator()
        title = menu.addAction("A new set of the selection — its name, then Enter")
        title.setEnabled(False)
        _field_action(menu, "", "Set name", self._on_add_set)
        menu.exec(qt.QtGui.QCursor.pos())

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
        self._say(f"Set “{name}”: {len(uuids)} objects", "done")

    def _remove_set(self, name: str) -> None:
        type(self)._quick_sets.pop(name, None)
        self._refresh_sets()

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
