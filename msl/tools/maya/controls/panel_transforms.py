# tools/maya/controls/panel_transforms.py
"""The Controls panel's TRANSFORMS card (shown from the window's header, hidden until wanted).

ONE grid says what everything in the card works on: move / rotate / scale × X Y Z, each channel
on, on INVERTED (its value goes over with the other sign — what a mirrored control needs) or off.
Beside each channel its number: the first selected object's value, typed or dragged for all selected.
Under the grid: Match (the selected onto the LAST selected), Reset, Freeze; Copy / Paste of a pose —
it travels as text on the system clipboard, so it is pasted in another Maya too (and kept in a file
from the buttons' menus); and the pose carried from one side of a rig to the other (L → R, R → L,
Swap; the pairs are found by the names, as Rename does). "World / Local" in the heading: objects are
put where another one STANDS, or the channels' own numbers go over.

Methods of ControlsPanel, kept apart by concern; the scene side is transforms.py."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.controls.attribute_rows import ValueSlider
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

GROUPS = (("Move", ("tx", "ty", "tz")), ("Rotate", ("rx", "ry", "rz")), ("Scale", ("sx", "sy", "sz")))
ALL_CHANNELS = tuple(attr for _title, attrs in GROUPS for attr in attrs)
SPACES = ("World", "Local")
POSE_FILTER = "MSL pose (*.json)"
STATES = ("on", "inv", "off")           # a channel: taken, taken inverted, left out


class _TransformsMixin:

    _pose = None             # the pose copied last, kept by the CLASS (the system clipboard holds it as text too)

    # ------------------------------------------------------------------ building

    def _transforms_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        self._space = SegmentedControl(list(SPACES), "World")
        self._space.setToolTip("World: an object is put where the other one STANDS (whatever each is parented "
                               "under) · Local: the channels' own numbers go over, as the Channel Box shows them")
        card = self._transforms = FoldingCard("TRANSFORMS", icons.get_icon("move", sub_folder="actions"),
                                              extras=[self._space])
        self._picks, self._pick_rows, self._numbers = {}, {}, {}
        for title, attrs in GROUPS:
            row = qt.QtWidgets.QHBoxLayout()
            row.setSpacing(3)
            whole = qt.QtWidgets.QPushButton(title)
            whole.setObjectName("controlsChannelRow")
            whole.setFlat(True)
            whole.setFixedWidth(46)
            whole.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            whole.setToolTip(f"{title}: all three taken — or all three left out")
            whole.clicked.connect(lambda _checked=False, attrs=attrs: self._toggle_pick_row(attrs))
            self._pick_rows[title] = whole
            row.addWidget(whole)
            for attr in attrs:
                pick = qt.QtWidgets.QPushButton(attr[1].upper())
                pick.setObjectName("controlsPick")
                pick.setFixedSize(26, 22)
                pick.setProperty("axis", attr[1].upper())
                pick.setProperty("state", "on")
                pick.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
                pick.clicked.connect(lambda _checked=False, attr=attr: self._cycle_pick(attr))
                self._picks[attr] = pick
                row.addWidget(pick)
            row.addSpacing(8)
            for attr in attrs:
                number = ValueSlider(1.0 if attr[0] == "s" else 0.0)
                number.setObjectName("controlsAttrValue")
                number.setFixedWidth(58)
                number.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.NoContextMenu)
                number.drag_started.connect(lambda attr=attr: self._on_number_drag_started(attr))
                number.dragged.connect(lambda value, attr=attr: self._on_number_dragged(attr, value))
                number.drag_finished.connect(lambda value, attr=attr: self._on_number_drag_finished(attr, value))
                number.value_set.connect(lambda value, attr=attr: self._on_number_set(attr, value))
                self._numbers[attr] = number
                row.addWidget(number)
            row.addStretch(1)
            card.body_layout.addLayout(row)
        # said in the card itself while NO channel is taken: every button under the grid then does nothing
        self._no_channels = qt.QtWidgets.QLabel("No channel is taken — click X, Y or Z above (or Move / Rotate / "
                                                "Scale for a whole row): the buttons below work on the taken ones")
        self._no_channels.setObjectName("controlsHint")
        self._no_channels.setWordWrap(True)
        self._no_channels.hide()
        card.body_layout.addWidget(self._no_channels)
        rule = qt.QtWidgets.QFrame()
        rule.setObjectName("controlsRule")
        rule.setFixedHeight(1)
        card.body_layout.addWidget(rule)

        def word(text: str, tip: str) -> qt.QtWidgets.QPushButton:
            button = qt.QtWidgets.QPushButton(text)
            button.setObjectName("controlsQuick")
            button.setToolTip(tip)
            return button

        self._match = word("Match", "The selected objects take the LAST selected one's transform, on the chosen "
                                    "channels — World: they are put where it stands · Local: they get its channel "
                                    "values (an inverted channel with the other sign)")
        self._reset_pick = word("Reset", "The chosen channels of the selected objects back to rest (0, scale 1) — "
                                         "locked and driven ones are left")
        self._freeze = word("Freeze", "Freeze Transformations — for move / rotate / scale that have a channel "
                                      "chosen (Maya freezes a whole group, not one axis)")
        self._pose_copy = word("Copy", "Copy the selected objects' pose: their channel values and where they stand "
                                       "in the world. It goes onto the clipboard as text too — paste it in "
                                       "ANOTHER Maya\nRight click: save it to a file")
        self._pose_paste = word("Paste", "")
        for button in (self._pose_copy, self._pose_paste):
            button.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        doing = qt.QtWidgets.QHBoxLayout()
        doing.setSpacing(3)
        caption = self._caption("Do")
        caption.setFixedWidth(46)
        doing.addWidget(caption)
        for button in (self._match, self._reset_pick, self._freeze):
            doing.addWidget(button)
        doing.addStretch(1)
        doing.addWidget(self._caption("Pose"))
        doing.addWidget(self._pose_copy)
        doing.addWidget(self._pose_paste)
        card.body_layout.addLayout(doing)

        self._side_buttons = {"left": word("L → R", "The LEFT side's values onto the right: each selected object "
                                                    "and its other-side twin (found by the names, as Rename does "
                                                    "it) — the chosen channels, inverted ones with the other sign"),
                              "right": word("R → L", "The RIGHT side's values onto the left"),
                              "swap": word("Swap", "The two sides exchange their values")}
        sides = qt.QtWidgets.QHBoxLayout()
        sides.setSpacing(3)
        caption = self._caption("Sides")
        caption.setFixedWidth(46)
        sides.addWidget(caption)
        for button in self._side_buttons.values():
            sides.addWidget(button)
        sides.addStretch(1)
        card.body_layout.addLayout(sides)

        self._space.current_changed.connect(self._on_space)
        self._match.clicked.connect(self._on_match)
        self._reset_pick.clicked.connect(self._on_reset_pick)
        self._freeze.clicked.connect(self._on_freeze)
        self._pose_copy.clicked.connect(self._on_pose_copy)
        self._pose_paste.clicked.connect(self._on_pose_paste)
        self._pose_copy.customContextMenuRequested.connect(
            lambda position: self._pose_menu(True).exec(self._pose_copy.mapToGlobal(position)))
        self._pose_paste.customContextMenuRequested.connect(
            lambda position: self._pose_menu(False).exec(self._pose_paste.mapToGlobal(position)))
        for direction, button in self._side_buttons.items():
            button.clicked.connect(lambda _checked=False, direction=direction: self._on_sides(direction))
        self._number_drag = None
        return card

    def _apply_transform_settings(self) -> None:
        space = self._settings.get("transform_space", "World")
        self._space.set_current(space if space in SPACES else "World", animate=False)
        stored = dict(self._settings.get("transform_channels") or {})
        for attr, pick in self._picks.items():
            state = stored.get(attr, "off" if attr[0] == "s" else "on")       # scale is left out at first
            self._show_pick(attr, state if state in STATES else "on")
        self._show_pose()
        self._sync_transform_buttons()

    # ------------------------------------------------------------------ the grid of channels

    def _show_pick(self, attr: str, state: str) -> None:
        pick = self._picks[attr]
        if (pick.property("state") or "") != state:
            pick.setProperty("state", state)
            repolish(pick)
        letter = attr[1].upper()
        pick.setText(("−" + letter) if state == "inv" else letter)
        pick.setToolTip({"on": f"{attr}: taken", "inv": f"{attr}: taken INVERTED — its value goes over with the "
                                                         "other sign (Local, and from side to side)",
                         "off": f"{attr}: left out"}[state] + "\nClick: taken → inverted → left out")

    def _pick_state(self, attr: str) -> str:
        return self._picks[attr].property("state") or "on"

    def _sync_transform_buttons(self) -> None:
        """With no channel taken the buttons under the grid can do nothing: they are greyed and the
        card says why (a Match that silently did nothing looked like a bug)."""
        any_taken = bool(self._picked_channels())
        for button in (self._match, self._reset_pick, self._freeze, self._pose_paste, *self._side_buttons.values()):
            button.setEnabled(any_taken)
        if any_taken == (not self._no_channels.isHidden()):
            self._no_channels.setVisible(not any_taken)

    def _save_picks(self) -> None:
        self._settings["transform_channels"] = {attr: self._pick_state(attr) for attr in self._picks}
        self._sync_transform_buttons()

    def _cycle_pick(self, attr: str) -> None:
        self._show_pick(attr, STATES[(STATES.index(self._pick_state(attr)) + 1) % len(STATES)])
        self._save_picks()

    def _toggle_pick_row(self, attrs) -> None:
        state = "off" if any(self._pick_state(attr) != "off" for attr in attrs) else "on"
        for attr in attrs:
            self._show_pick(attr, state)
        self._save_picks()

    def _picked_channels(self) -> dict:
        """{channel: +1 / -1} of the channels taken."""
        return {attr: (-1 if self._pick_state(attr) == "inv" else 1) for attr in ALL_CHANNELS
                if self._pick_state(attr) != "off"}

    def _world(self) -> bool:
        return self._space.current() == "World"

    def _on_space(self, *_args) -> None:
        if not self._loading and self._settings.get("transform_space") != self._space.current():
            self._settings["transform_space"] = self._space.current()

    # ------------------------------------------------------------------ the numbers

    def _refresh_transform_values(self) -> None:
        """The nine numbers show the first selected object's channels (only while the card is on screen)."""
        if self._transforms.isHidden() or not self._transforms.is_open() or self._number_drag is not None:
            return
        values, node = {}, ""
        try:
            from msl_tools.msl.tools.maya.controls import scene, transforms
            nodes = scene.selected_transforms()
            if nodes:
                node = nodes[0]
                values = transforms.values_of(node)
        except ImportError:
            pass
        except Exception as error:
            self._report("Couldn't read the transform", error)
        for attr, number in self._numbers.items():
            number.setEnabled(attr in values)
            if attr in values:
                number.set_value(values[attr])
            number.setToolTip(f"{attr} of {node.rpartition('|')[2]} (the first selected) — drag sideways, double "
                              "click: type a number\nIt goes to EVERY selected object — also to the one you "
                              "match to" if node else "Select an object")
        self._show_pose()

    def _transform_nodes(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        nodes = scene.selected_transforms()
        if not nodes:
            self._say("Select objects first", "error")
        return nodes

    def _on_number_set(self, attr: str, value) -> None:
        from msl_tools.msl.tools.maya.controls import attributes, scene
        nodes = scene.selected_transforms()
        if nodes and not attributes.set_value(nodes, attr, float(value)):
            self._say(f"{attr} is locked or driven on the selection: not changed", "error")

    def _on_number_drag_started(self, attr: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes, scene
        nodes = scene.selected_transforms()
        self._number_drag = (attr, attributes.get_values(nodes, attr)) if nodes else None

    def _on_number_dragged(self, attr: str, value) -> None:
        from msl_tools.msl.tools.maya.controls import attributes
        if self._number_drag and self._number_drag[0] == attr:
            attributes.set_value(list(self._number_drag[1]), attr, float(value), undoable=False)

    def _on_number_drag_finished(self, attr: str, value) -> None:
        """A drag is ONE undo step (as in the ATTRIBUTES rows)."""
        from msl_tools.msl.tools.maya.controls import attributes
        drag, self._number_drag = self._number_drag, None
        if drag and drag[0] == attr and drag[1]:
            attributes.restore_values(drag[1], attr)
            attributes.set_value(list(drag[1]), attr, float(value))

    # ------------------------------------------------------------------ match, reset, freeze

    def _channels_or_say(self) -> dict:
        channels = self._picked_channels()
        if not channels:
            self._say("No channel is taken — switch some on in the grid", "error")
        return channels

    @staticmethod
    def _left_text(left: list) -> str:
        return (" · left (locked or driven): " + ", ".join(left[:3]) + ("…" if len(left) > 3 else "")) if left else ""

    def _on_match(self) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        nodes, channels = self._transform_nodes(), self._channels_or_say()
        if not nodes or not channels:
            return
        if len(nodes) < 2:
            self._say("Select what to move, then — LAST — the object to match it to", "error")
            return
        done, left = transforms.match(nodes, channels, self._world())
        target = nodes[-1].rpartition("|")[2]
        space = self._space.current().lower()
        if done:
            text, state = f"{done} matched to {target} ({space}, {len(channels)} channels)", "done"
        elif left:
            text, state = f"Nothing matched to {target}", "error"
        else:
            # nothing moved and nothing refused: they hold its transform already
            text, state = (f"Already matched: the selected hold {target}'s transform on the taken channels "
                           f"({space}) — it is the LAST selected object they are matched to"), ""
        self._say(text + self._left_text(left) + (" · Ctrl+Z undoes it" if done else ""), state)
        self._refresh_transform_values()

    def _on_reset_pick(self) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        nodes, channels = self._transform_nodes(), self._channels_or_say()
        if nodes and channels:
            done, left = transforms.reset(nodes, channels)
            self._say((f"{done} channel{'s' if done != 1 else ''} back to rest" if done else "They are at rest already") +
                      (f" · {left} locked or driven left" if left else "") + (" · Ctrl+Z undoes it" if done else ""),
                      "done" if done else "")
            self._refresh_transform_values()

    def _on_freeze(self) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        nodes, channels = self._transform_nodes(), self._channels_or_say()
        if nodes and channels:
            done, left = transforms.freeze(nodes, channels)
            self._say((f"{done} frozen" if done else "Nothing frozen") +
                      (f" · not: {left[0]}" + (f" (+{len(left) - 1})" if len(left) > 1 else "") if left else "") +
                      (" · Ctrl+Z undoes it" if done else ""), "done" if done else "error")
            self._refresh_transform_values()

    # ------------------------------------------------------------------ a pose: copy, paste, a file

    def _clipboard_pose(self) -> "dict | None":
        """The pose on the system clipboard (copied here, or in another Maya), else the one copied last."""
        try:
            from msl_tools.msl.tools.maya.controls import transforms
            text = qt.QtWidgets.QApplication.clipboard().text()
            if text and len(text) < 4_000_000 and transforms.POSE_MARK in text[:200]:
                pose = transforms.pose_from_text(text)
                if pose:
                    return pose
        except ImportError:
            pass
        return _TransformsMixin._pose

    def _show_pose(self) -> None:
        pose = self._clipboard_pose()
        count = len(pose["objects"]) if pose else 0
        names = ", ".join(entry["name"] for entry in pose["objects"][:3]) + ("…" if count > 3 else "") if pose else ""
        self._pose_paste.setToolTip((f"Paste the copied pose ({count} object{'s' if count != 1 else ''}: {names}) onto "
                                     "the selection, on the chosen channels — ONE copied object goes onto every "
                                     "selected one; several find theirs by NAME (namespaces don't matter), else by "
                                     "the order picked" if pose else "Nothing copied yet — Copy a pose first (here, "
                                     "or in another Maya)") + "\nRight click: load a pose from a file")
        if bool(self._pose_paste.property("primary")) != bool(pose):
            self._pose_paste.setProperty("primary", bool(pose))
            repolish(self._pose_paste)

    def _on_pose_copy(self) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        nodes = self._transform_nodes()
        if nodes:
            pose = transforms.pose_of(nodes)
            _TransformsMixin._pose = pose
            qt.QtWidgets.QApplication.clipboard().setText(transforms.pose_text(pose))
            self._show_pose()
            self._say(f"The pose of {len(nodes)} object{'s' if len(nodes) != 1 else ''} is copied — paste it here or "
                      "in another Maya", "done")

    def _paste_pose(self, pose: "dict | None") -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        if not pose:
            self._say("Nothing copied yet — Copy a pose first (here, or in another Maya)", "error")
            return
        nodes, channels = self._transform_nodes(), self._channels_or_say()
        if not nodes or not channels:
            return
        done, left, how = transforms.apply_pose(nodes, pose, channels, self._world())
        if not how:
            self._say(f"The pose is of {len(pose['objects'])} objects and none of the {len(nodes)} selected has one of "
                      "their names — select as many, in the same order", "error")
            return
        words = {"one": "the copied object's pose", "name": "found by name", "order": "by the order picked"}[how]
        self._say((f"{done} got the pose ({words}, {self._space.current().lower()})" if done else "Nothing pasted") +
                  self._left_text(left) + (" · Ctrl+Z undoes it" if done else ""), "done" if done else "error")
        self._refresh_transform_values()

    def _on_pose_paste(self) -> None:
        self._paste_pose(self._clipboard_pose())

    def _pose_menu(self, copying: bool) -> "qt.QtWidgets.QMenu":
        menu = self._menu()
        if copying:
            self._menu_caption(menu, "The selected objects' pose")
            self._menu_item(menu, "copy", "Copy", self._on_pose_copy, "Onto the clipboard, as text", hint="click")
            self._menu_item(menu, "save", "Save to a file…", self._on_pose_save, "To keep a pose, or hand it over")
        else:
            self._menu_caption(menu, "A pose onto the selection")
            self._menu_item(menu, "paste", "Paste", self._on_pose_paste, "From the clipboard", hint="click")
            self._menu_item(menu, "file_add", "Load from a file…", self._on_pose_load, "A pose saved with Copy's menu")
        return menu

    def _on_pose_save(self) -> None:
        from msl_tools.msl.core.fs.safe_json import write_json_atomic
        from msl_tools.msl.tools.maya.controls import transforms
        nodes = self._transform_nodes()
        if not nodes:
            return
        path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Save the pose", "", POSE_FILTER)
        if path:
            write_json_atomic(path, transforms.pose_of(nodes))
            self._say(f"The pose of {len(nodes)} saved to {path}", "done")

    def _on_pose_load(self) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(self, "Load a pose", "", POSE_FILTER)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as file:
                pose = transforms.pose_from_text(file.read())
        except OSError as error:
            self._say(f"Couldn't read the file: {error}", "error")
            return
        if not pose:
            self._say("That file holds no pose", "error")
            return
        self._paste_pose(pose)

    # ------------------------------------------------------------------ from one side to the other

    def _on_sides(self, direction: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene, transforms
        nodes, channels = self._transform_nodes(), self._channels_or_say()
        if not nodes or not channels:
            return
        sides = self._sides()
        pairs = transforms.side_pairs(nodes, lambda node: scene.other_side(node, sides, "X"))
        if not pairs:
            self._say("No other side found for the selection — the names must say a side (lf_ / rt_, _L / _R…) and "
                      "the twin must be in the scene", "error")
            return
        done, left = transforms.transfer_sides(pairs, direction, channels)
        words = {"left": "left → right", "right": "right → left", "swap": "the sides swapped"}[direction]
        self._say((f"{done} pair{'s' if done != 1 else ''}: {words} ({len(channels)} channels)" if done else
                   "Nothing carried over") + self._left_text(left) + (" · Ctrl+Z undoes it" if done else ""),
                  "done" if done else "error")
        self._refresh_transform_values()
