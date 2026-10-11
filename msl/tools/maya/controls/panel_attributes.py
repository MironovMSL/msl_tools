# tools/maya/controls/panel_attributes.py
"""The Controls panel's CHANNELS and ATTRIBUTES cards — shown and hidden by two buttons in the
window's header, hidden until wanted; a click on a card's heading only FOLDS it, like the other
cards. Both work on what is selected in the scene, at once:

CHANNELS — the ten transform channels as buttons that SHOW their state (open / locked / locked and
hidden); a click closes or opens one, a row's caption its three; ready sets; values back to their
defaults; the rotate order changed without turning the object.

ATTRIBUTES — the first selected object's own attributes in the Channel Box's order, each a row of
WIDGETS (attribute_rows.py): the name renamed by a double click, the value changed in place (a
field that is a slider, a check box, a drop-down), K and the lock clicked; rows dragged to another
place; add (a number, a whole number, on / off, a list of names, a separator line), remove, copy to
the other selected objects; a number's range changed from its menu. A change goes to EVERY
selected object that has the attribute.

Methods of ControlsPanel, kept apart by concern; the scene side is attributes.py."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.rename.buttons import ToggleIconButton
from msl_tools.msl.tools.maya.controls.attribute_rows import AttributeRows
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.compositions.bulk_action_bar import BulkActionBar
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

# what the cards know without Maya (attributes.py imports maya.cmds: it is imported when used)
MOVE, TURN, SCALE = ("tx", "ty", "tz"), ("rx", "ry", "rz"), ("sx", "sy", "sz")
ROTATE_ORDERS = ("xyz", "yzx", "zxy", "xzy", "yxz", "zyx")
QUICK = ("Move", "Rotate", "Move + rotate", "All")
KINDS = ("Number", "Whole number", "On / off", "List", "Separator")
STATE_WORDS = {"open": "open", "locked": "locked (still shown)", "hidden": "locked and hidden",
               "mixed": "not the same on every selected object"}
CARDS = (("channels", "channels", "Channels", "Lock and hide the move / rotate / scale channels of the selection, "
                                           "put values back, change the rotate order"),
         ("attributes", "attributes", "Attributes", "The selected object's own attributes: values, names, "
                                                    "order, add and remove, copy and paste, saved sets"),
         ("transforms", "move", "Transforms", "Match, reset and freeze by channel, type the numbers, copy a "
                                              "pose and paste it (in another Maya too), carry it from side to side"))


# the cards the header can also put away, shown unless switched off (the two above: hidden until wanted)
MAIN_CARDS = (("control", "controls", "Control", "The shape library and how a new control is made"),
              ("color", "brush", "Color", "Colors of the selected controls: the palette, your own, the "
                                               "Outliner, the line's width"))
SHOWN_AT_FIRST = {"control": True, "color": True, "channels": False, "attributes": False, "transforms": False}


class _AttributesMixin:

    # ------------------------------------------------------------------ building

    def _channels_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        self._open_all = self._tool_button("unlock", "Open every channel", "Move, rotate, scale and visibility "
                                           "of the selection unlocked and shown again")
        self._reset_values = self._tool_button("restart", "Values back", "Move and rotate to 0, scale to 1, "
                                               "visibility on, the objects' own attributes to their defaults — "
                                               "locked and driven channels are left alone")
        card = self._channels = FoldingCard("CHANNELS", icons.get_icon("channels", sub_folder="actions"),
                                            extras=[self._open_all, self._reset_values])
        self._channel_buttons, self._row_buttons = {}, {}
        self._rotate_order = BaseComboBox(list(ROTATE_ORDERS), ROTATE_ORDERS[0], enable_wheel=False)
        self._rotate_order.setObjectName("controlsRotateOrder")
        self._rotate_order.setFixedWidth(58)
        self._rotate_order.setToolTip("The rotate order of the selection — changed WITHOUT turning it: the "
                                      "rotation is written again in the new order")
        for title, attrs in (("Move", MOVE), ("Rotate", TURN), ("Scale", SCALE)):
            row = qt.QtWidgets.QHBoxLayout()
            row.setSpacing(3)
            whole = qt.QtWidgets.QPushButton(title)
            whole.setObjectName("controlsChannelRow")
            whole.setFlat(True)
            whole.setFixedWidth(46)
            whole.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            whole.setToolTip(f"{title}: all three at once — open ones are locked and hidden, closed ones opened")
            whole.clicked.connect(lambda _checked=False, attrs=attrs: self._toggle_channels(attrs))
            self._row_buttons[title] = whole
            row.addWidget(whole)
            for attr in attrs:
                row.addWidget(self._channel_button(attr, attr[1].upper()))
            if title == "Move":
                row.addSpacing(12)
                row.addWidget(self._caption("Visibility"))
                row.addWidget(self._channel_button("v", "V"))
            elif title == "Rotate":
                row.addSpacing(12)
                row.addWidget(self._caption("Order"))
                row.addWidget(self._rotate_order)
            row.addStretch(1)
            card.body_layout.addLayout(row)
        quick = qt.QtWidgets.QHBoxLayout()
        quick.setSpacing(3)
        only = self._caption("Only")
        only.setFixedWidth(46)
        only.setToolTip("Ready sets: what stays open — everything else is locked and hidden")
        quick.addWidget(only)
        self._quick_buttons = {}
        for name in QUICK:
            button = qt.QtWidgets.QPushButton(name)
            button.setObjectName("controlsQuick")
            button.setToolTip(("Every channel open again" if name == "All" else
                               f"Only {name.lower()} stays open; the rest is locked and hidden"))
            button.clicked.connect(lambda _checked=False, name=name: self._quick_channels(name))
            self._quick_buttons[name] = button
            quick.addWidget(button)
        quick.addStretch(1)
        card.body_layout.addLayout(quick)
        return card

    def _channel_button(self, attr: str, text: str) -> qt.QtWidgets.QPushButton:
        button = qt.QtWidgets.QPushButton(text)
        button.setObjectName("controlsChannel")
        button.setFixedSize(24, 22)
        button.setProperty("state", "open")
        button.setProperty("axis", text if text in "XYZ" else "")
        button.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        button.clicked.connect(lambda _checked=False, attr=attr: self._toggle_channels((attr,)))
        button.customContextMenuRequested.connect(
            lambda position, attr=attr, button=button: self._channel_menu(attr).exec(button.mapToGlobal(position)))
        self._channel_buttons[attr] = button
        return button

    def _attributes_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        self._attr_copy = self._tool_button("copy", "Copy the attributes", "The first selected object's own "
                                            "attributes are remembered — all of them (pick rows first: only "
                                            "those) with their kind, range, default and value — to be pasted "
                                            "onto whatever you select next")
        self._attr_paste = self._tool_button("paste", "Paste the attributes", "The copied attributes made on every "
                                             "selected object. One that is there already is left as it is")
        self._attr_sets = self._tool_button("bookmark", "Saved sets", "Sets of attributes you kept under a name "
                                            "(FK / IK, a foot roll…): a click puts one on the selection; save "
                                            "the copied attributes as a new set here")
        # the picked rows' own bar: it takes the heading's place while rows are picked
        bar = self._attr_bar = BulkActionBar()
        bar.setObjectName("controlsAttrBar")
        self._bulk_buttons = {}
        for key, icon, tip, danger in (("key", "keyframe", "Key the picked attributes at the current frame", False),
                                       ("default", "restart", "The picked attributes back to their defaults", False),
                                       ("lock", "lock", "Lock / unlock the picked attributes", False),
                                       ("hide", "eye_off", "Keyable / shown only / hidden — how they show in the "
                                                           "Channel Box", False),
                                       ("copy", "copy", "Copy the picked attributes — paste them onto another "
                                                        "object", False),
                                       ("delete", "delete", "Remove the picked attributes from every selected "
                                                            "object", True)):
            button = bar.add_action("", tip, danger=danger)
            button.set_icon(icons.get_icon(icon, sub_folder="actions"))
            self._bulk_buttons[key] = button
        bar.hide()
        card = self._attributes = FoldingCard("ATTRIBUTES", icons.get_icon("attributes", sub_folder="actions"),
                                              extras=[bar, self._attr_copy, self._attr_paste, self._attr_sets])
        self._attr_extras = (self._attr_copy, self._attr_paste, self._attr_sets)
        # each attribute is a row of widgets: grip · name · its value · K · lock (attribute_rows.py)
        self._attr_rows = AttributeRows()
        self._attr_hint = qt.QtWidgets.QLabel("Select an object: its own attributes are listed here")
        self._attr_hint.setObjectName("controlsCaption")
        self._attr_hint.setWordWrap(True)
        card.body_layout.addWidget(self._attr_hint)
        card.body_layout.addWidget(self._attr_rows)
        self._attr_rows.hide()

        # a new attribute: its name, what it is, and what that kind needs
        self._attr_name = qt.QtWidgets.QLineEdit()
        self._attr_name.setPlaceholderText("New attribute")
        self._attr_name.setMinimumWidth(60)
        self._attr_kind = BaseComboBox(list(KINDS), KINDS[0], enable_wheel=False)
        self._attr_kind.setObjectName("controlsAttrKind")
        self._attr_kind.setFixedWidth(104)
        self._attr_min, self._attr_max, self._attr_default = (qt.QtWidgets.QLineEdit() for _ in range(3))
        for field, hint, tip in ((self._attr_min, "min", "The least it can be (empty: no limit)"),
                                 (self._attr_max, "max", "The most it can be (empty: no limit)"),
                                 (self._attr_default, "0", "The value it starts with (its default)")):
            field.setPlaceholderText(hint)
            field.setToolTip(tip)
            field.setFixedWidth(36)
        self._attr_names = qt.QtWidgets.QLineEdit()
        self._attr_names.setPlaceholderText("world, chest, hip")
        self._attr_names.setToolTip("The names of the list, separated by commas — the first is the default")
        self._attr_names.setMinimumWidth(60)
        self._attr_add = self._tool_button("add", "Add", "The attribute made on every selected object (Enter in "
                                                         "the name does the same)")
        adding = qt.QtWidgets.QHBoxLayout()
        adding.setSpacing(3)
        adding.addWidget(self._attr_name, 2)
        adding.addWidget(self._attr_kind)
        adding.addWidget(self._attr_min)
        adding.addWidget(self._attr_max)
        adding.addWidget(self._attr_default)
        adding.addWidget(self._attr_names, 2)
        adding.addWidget(self._attr_add)
        card.body_layout.addLayout(adding)
        self._show_kind_fields(KINDS[0])
        return card

    def _connect_attributes(self) -> None:
        self._open_all.clicked.connect(lambda: self._quick_channels("All"))
        self._reset_values.clicked.connect(self._on_reset_values)
        self._rotate_order.activated.connect(lambda _index: self._on_rotate_order())
        self._attr_kind.currentTextChanged.connect(self._show_kind_fields)
        self._attr_add.clicked.connect(self._on_add_attribute)
        self._attr_name.returnPressed.connect(self._on_add_attribute)
        self._attr_names.returnPressed.connect(self._on_add_attribute)
        self._attr_copy.clicked.connect(lambda: self._copy_attrs())
        self._attr_paste.clicked.connect(lambda: self._paste_attrs())
        self._attr_sets.clicked.connect(lambda: self._attr_sets_menu().exec(
            self._attr_sets.mapToGlobal(qt.QtCore.QPoint(0, self._attr_sets.height()))))
        bulk = self._bulk_buttons
        bulk["key"].clicked.connect(lambda: self._bulk("key"))
        bulk["default"].clicked.connect(lambda: self._bulk("default"))
        bulk["lock"].clicked.connect(lambda: self._bulk("lock"))
        bulk["hide"].clicked.connect(lambda: self._bulk("hide"))
        bulk["copy"].clicked.connect(lambda: self._copy_attrs())
        bulk["delete"].clicked.connect(lambda: self._on_remove_attributes())
        self._attr_bar.clear_requested.connect(lambda: self._attr_rows.clear_picked())
        self._attr_bar.select_all_requested.connect(lambda: self._attr_rows.pick_all())
        rows = self._attr_rows
        rows.picked_changed.connect(self._show_attr_heading)
        rows.action_requested.connect(self._on_attr_action)
        rows.order_changed.connect(self._on_attr_order)
        rows.renamed.connect(self._on_attr_renamed)
        rows.value_set.connect(self._on_attr_value)
        rows.drag_started.connect(self._on_attr_drag_started)
        rows.dragged.connect(self._on_attr_dragged)
        rows.drag_finished.connect(self._on_attr_drag_finished)
        rows.key_clicked.connect(self._on_attr_key_clicked)
        rows.lock_clicked.connect(self._on_attr_lock_clicked)
        rows.menu_requested.connect(self._on_attr_menu)
        for key, card in (("channels", self._channels), ("attributes", self._attributes),
                          ("transforms", self._transforms)):
            # a click on the heading FOLDS the card, like the others; only the header's button puts
            # it away altogether and brings it back
            card.toggled.connect(lambda opened, key=key: self._on_card_folded(key, opened))

    # ------------------------------------------------------------------ the header's buttons

    def header_widgets(self) -> list:
        """Buttons for the window's header, one per card it can put away: CONTROL, COLOR, CHANNELS,
        ATTRIBUTES — in the order the cards stand in."""
        icons = UiResources().iconManager
        self._card_toggles = {}
        for key, icon, title, text in MAIN_CARDS + CARDS:
            button = ToggleIconButton(icons.get_icon(icon, sub_folder="actions"), title, text)
            button.setObjectName("controlsHeaderToggle")
            button.setChecked(not self._card(key).isHidden())
            button.toggled.connect(lambda on, key=key: self._show_card(key, on))
            self._card_toggles[key] = button
        return list(self._card_toggles.values())

    def _card(self, key: str) -> FoldingCard:
        return {"control": self._control_card, "color": self._color, "channels": self._channels,
                "transforms": self._transforms}.get(key, self._attributes)

    def _card_extras(self, key: str) -> tuple:
        if key in ("control", "color", "transforms"):
            return ()                 # (CONTROL's heading looks after its own: _show_heading)
        return self._attr_extras if key == "attributes" else (self._open_all, self._reset_values)

    _attr_clipboard: list = []      # the copied attributes, kept by the CLASS: they outlive a closed window

    def _show_attr_heading(self) -> None:
        """The ATTRIBUTES heading: its own buttons — or, while rows are picked, their bar."""
        usable = not self._attributes.isHidden() and self._attributes.is_open()
        picked, total = len(self._attr_rows.picked()), len(self._attr_rows.rows())
        self._attr_bar.set_count(picked if usable else 0, total)
        if not usable or not picked:
            self._attr_bar.hide() if not usable else None
        for extra in self._attr_extras:
            extra.setVisible(usable and not picked)
        copied = len(_AttributesMixin._attr_clipboard)
        if bool(self._attr_paste.property("on")) != bool(copied):
            self._attr_paste.setProperty("on", bool(copied))
            repolish(self._attr_paste)
        base = self._attr_paste.toolTip().split("\n● ")[0]
        self._attr_paste.setToolTip(base + (f"\n● {copied} attribute{'s' if copied != 1 else ''} copied" if copied else
                                            "\n● nothing copied yet"))

    def _on_card_folded(self, key: str, opened: bool) -> None:
        """The card's heading was clicked: folded or open (its heading stays); remembered."""
        self._save_folded(key, opened)
        for extra in self._card_extras(key):
            extra.setVisible(bool(opened))
        if key == "attributes":
            self._show_attr_heading()
        if opened:
            self._refresh_attributes()
            self._refresh_transform_values()

    def _show_card(self, key: str, on: bool) -> None:
        """The header's button: the card shown (folded or open, as it was left) or put away
        altogether; remembered."""
        card = self._card(key)
        if on:
            card.show()
        else:
            card.hide()
        for extra in self._card_extras(key):
            extra.setVisible(bool(on) and card.is_open())
        if key == "attributes":
            self._show_attr_heading()
        elif key == "control" and on:
            self._show_heading()
        toggle = getattr(self, "_card_toggles", {}).get(key)
        if toggle is not None and toggle.isChecked() != bool(on):
            toggle.blockSignals(True)
            toggle.setChecked(bool(on))
            toggle.blockSignals(False)
            toggle._follow()
        shown = dict(self._settings.get("shown") or {})
        if shown.get(key, SHOWN_AT_FIRST[key]) != bool(on):
            shown[key] = bool(on)
            self._settings["shown"] = shown
        if on and key in ("channels", "attributes"):
            self._refresh_attributes()
        elif on and key == "transforms":
            self._refresh_transform_values()

    def _apply_attribute_settings(self) -> None:
        shown = dict(self._settings.get("shown") or {})
        folded = dict(self._settings.get("folded") or {})
        for key, _icon, _title, _text in CARDS:
            card = self._card(key)
            card.set_open(not folded.get(key, False))
            for extra in self._card_extras(key):
                if not card.is_open():
                    extra.hide()
            if not shown.get(key, False):
                card.hide()
        for key, _icon, _title, _text in MAIN_CARDS:       # their fold state is the panel's own
            if not shown.get(key, True):
                self._card(key).hide()

    # ------------------------------------------------------------------ reading the selection

    def _attribute_nodes(self) -> list:
        try:
            from msl_tools.msl.tools.maya.controls import scene
            return scene.selected_transforms()
        except (ImportError, RuntimeError, ValueError):
            return []

    def _refresh_attributes(self) -> None:
        """Both cards show what the selection IS now (only while they are on screen)."""
        channels = not self._channels.isHidden() and self._channels.is_open()
        attributes = not self._attributes.isHidden() and self._attributes.is_open()
        if not (channels or attributes):
            return
        nodes = self._attribute_nodes()
        try:
            from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        except ImportError:
            scene_attributes = None
        if channels:
            states = {}
            order = ""
            if scene_attributes is not None and nodes:
                try:
                    states = scene_attributes.channel_states(nodes)
                    order = scene_attributes.rotate_order(nodes)
                except Exception as error:
                    self._report("Couldn't read the channels", error)
            for attr, button in self._channel_buttons.items():
                state = states.get(attr, "open")
                if (button.property("state") or "") != state:
                    button.setProperty("state", state)
                    repolish(button)
                button.setToolTip(f"{attr}: {STATE_WORDS.get(state, state)}\nClick: "
                                  f"{'lock and hide it' if state == 'open' else 'open it'} · right click: more")
                button.setEnabled(bool(nodes))
            self._rotate_order.setEnabled(bool(nodes))
            if order and self._rotate_order.currentText() != order:
                self._rotate_order.blockSignals(True)
                self._rotate_order.setCurrentText(order)
                self._rotate_order.blockSignals(False)
        if self._attr_drag is not None and not qt.QtWidgets.QApplication.mouseButtons():
            self._attr_drag = None          # a drag whose end never came must not freeze the list
        if attributes and not self._attr_rows.is_busy() and self._attr_drag is None:
            # (never while a name is typed, a row is held or a value is dragged)
            rows = []
            if scene_attributes is not None and nodes:
                try:
                    rows = scene_attributes.own_attributes(nodes[0])
                    # the rows show the FIRST object's values: where the others differ, say so
                    differing = scene_attributes.differing(nodes, [info["name"] for info in rows])
                    for info in rows:
                        info["mixed"] = info["name"] in differing
                except Exception as error:
                    self._report("Couldn't read the attributes", error)
            self._attr_rows.set_infos(rows)
            self._attr_rows.setVisible(bool(rows))
            self._attr_hint.setVisible(not rows)
            self._show_attr_heading()
            short = nodes[0].rpartition("|")[2] if nodes else ""
            self._attr_hint.setText(f"{short} has no attributes of its own yet — add one below" if nodes else
                                    "Select an object: its own attributes are listed here")

    def _after_attribute_change(self) -> None:
        qt.QtCore.QTimer.singleShot(0, self._refresh_attributes)

    # ------------------------------------------------------------------ channels

    def _needs_selection(self) -> list:
        nodes = self._attribute_nodes()
        if not nodes:
            self._say("Select objects first", "error")
        return nodes

    def _toggle_channels(self, attrs) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if not nodes:
            return
        states = scene_attributes.channel_states(nodes)
        closing = any(states.get(attr) == scene_attributes.OPEN for attr in attrs)
        scene_attributes.set_channels(nodes, attrs, scene_attributes.HIDDEN if closing else scene_attributes.OPEN)
        self._say(f"{', '.join(attrs)} {'locked and hidden' if closing else 'open'} on {len(nodes)} · Ctrl+Z undoes it", "done")
        self._after_attribute_change()

    def _set_channel_state(self, attr: str, state: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if nodes:
            scene_attributes.set_channels(nodes, (attr,), state)
            self._say(f"{attr}: {STATE_WORDS[state]} on {len(nodes)}", "done")
            self._after_attribute_change()

    def _channel_menu(self, attr: str) -> "qt.QtWidgets.QMenu":
        menu = self._menu()
        self._menu_caption(menu, f"{attr} of the selection")
        current = self._channel_buttons[attr].property("state")
        for state, icon, text, tip in (("open", "unlock", "Open", "Unlocked, in the Channel Box, can be keyed"),
                                       ("locked", "lock", "Locked, still shown", "It can't be changed, but it is seen"),
                                       ("hidden", "eye_off", "Locked and hidden", "Out of the Channel Box")):
            self._menu_item(menu, icon, text, lambda state=state: self._set_channel_state(attr, state), tip,
                            hint="✓" if state == current else "")
        return menu

    def _quick_channels(self, name: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if nodes:
            scene_attributes.keep_open(nodes, scene_attributes.QUICK[name])
            self._say(("Every channel open" if name == "All" else f"Only {name.lower()} is open — the rest is locked "
                       "and hidden") + f" on {len(nodes)} · Ctrl+Z undoes it", "done")
            self._after_attribute_change()

    def _on_reset_values(self) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if nodes:
            done, left = scene_attributes.reset_values(nodes)
            self._say(f"{done} value{'s' if done != 1 else ''} back to default" +
                      (f" · {left} locked or driven left alone" if left else "") if done or left else
                      "Everything is at its default already", "done" if done else "")
            self._after_attribute_change()

    def _on_rotate_order(self) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if nodes:
            order = self._rotate_order.currentText()
            count = scene_attributes.set_rotate_order(nodes, order)
            self._say(f"Rotate order {order} on {count} — nothing turned · Ctrl+Z undoes it", "done")
            self._after_attribute_change()

    # ------------------------------------------------------------------ attributes

    def _show_kind_fields(self, kind: str) -> None:
        numbers = kind in ("Number", "Whole number")
        self._attr_default.clear()           # "on" typed for a switch is no default of a number
        self._attr_min.setVisible(numbers)
        self._attr_max.setVisible(numbers)
        self._attr_default.setVisible(numbers or kind == "On / off")
        self._attr_default.setPlaceholderText("off" if kind == "On / off" else "0")
        self._attr_default.setToolTip("on / off: what it starts as (1 or on = on)" if kind == "On / off" else
                                      "The value it starts with (its default)")
        self._attr_names.setVisible(kind == "List")
        self._attr_name.setPlaceholderText("The line's text (may be empty)" if kind == "Separator" else "New attribute")

    @staticmethod
    def _number(text: str):
        text = text.strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return False

    def _on_add_attribute(self) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if not nodes:
            return
        kind, name = self._attr_kind.currentText(), self._attr_name.text().strip()
        if kind != "Separator" and not name:
            self._say("Give the attribute a name first", "error")
            self._attr_name.setFocus()
            return
        low, high, default = (self._number(field.text()) for field in (self._attr_min, self._attr_max, self._attr_default))
        names = [part.strip() for part in self._attr_names.text().split(",") if part.strip()]
        if kind == "On / off":
            default = self._attr_default.text().strip().lower() in ("1", "on", "yes", "true")
            low = high = None
        elif kind == "List":
            if len(names) < 2:
                self._say("A list needs two names or more, separated by commas", "error")
                self._attr_names.setFocus()
                return
            low = high = None
            default = 0
        elif kind == "Separator":
            low = high = None
            default = 0
        elif any(value is False for value in (low, high, default)):       # (0.0 == False: by identity)
            self._say("min, max and the default are numbers (or empty)", "error")
            return
        made_name, made, had = scene_attributes.add_attribute(nodes, name, kind, low, high, default or 0, names)
        if not made:
            self._say(f"“{name}” is there already on the selection", "error")
            return
        self._attr_name.clear()
        self._say((f"A separator on {made}" if kind == "Separator" else f"“{made_name}” added to {made}") +
                  (f" · {had} had it already" if had else "") + " · Ctrl+Z undoes it", "done")
        self._after_attribute_change()

    def _picked_attributes(self, also: str = "") -> list:
        """The picked rows' attributes — or, with none picked, the one the menu was opened on."""
        picked = self._attr_rows.picked()
        if also and also not in picked:
            picked = [also]
        if not picked:
            self._say("Pick rows first — a click on a row (Ctrl / Shift for several)", "error")
        return picked

    def _on_remove_attributes(self, also: str = "") -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        picked = self._picked_attributes(also) if nodes else None
        if picked:
            count = scene_attributes.remove_attributes(nodes, picked)
            self._say(f"{len(picked)} attribute{'s' if len(picked) != 1 else ''} removed ({count} in all) · "
                      "Ctrl+Z undoes it", "done")
            self._after_attribute_change()

    # ---- copy, paste, saved sets

    def _copy_attrs(self, also: str = "") -> None:
        """The first selected object's attributes (the picked rows / the one of the menu / all) are
        remembered, to be pasted onto whatever is selected next."""
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if not nodes:
            return
        names = self._attr_rows.picked() or ([also] if also else None)
        copied = scene_attributes.snapshot(nodes[0], names)
        if not copied:
            self._say(f"{nodes[0].rpartition('|')[2]} has no attributes of its own to copy", "error")
            return
        _AttributesMixin._attr_clipboard = copied
        self._show_attr_heading()
        self._say(f"{len(copied)} attribute{'s' if len(copied) != 1 else ''} copied from "
                  f"{nodes[0].rpartition('|')[2]} — select other objects and paste", "done")

    def _paste_attrs(self, infos: "list | None" = None, what: str = "") -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        infos = list(_AttributesMixin._attr_clipboard) if infos is None else list(infos)
        if not infos:
            self._say("Nothing copied yet — copy an object's attributes first, or pick a saved set", "error")
            return
        nodes = self._needs_selection()
        if not nodes:
            return
        made, touched, had = scene_attributes.paste(nodes, infos)
        text = (f"{what + ': ' if what else ''}{made} attribute{'s' if made != 1 else ''} made on {touched} "
                f"object{'s' if touched != 1 else ''}" if made else "Nothing new: the selection has those attributes")
        self._say(text + (f" · {had} were there already and are left as they are" if had and made else "") +
                  (" · Ctrl+Z undoes it" if made else ""), "done" if made else "")
        self._after_attribute_change()

    def _attribute_sets(self) -> dict:
        stored = self._settings.get("attribute_sets", None)
        return {str(name): list(infos) for name, infos in dict(stored).items()} if isinstance(stored, dict) or \
            hasattr(stored, "items") else {}

    def _save_attribute_set(self, name: str) -> None:
        """What is copied (else the selection's attributes: the picked rows, or all) kept under a name."""
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        infos = list(_AttributesMixin._attr_clipboard)
        if not infos:
            nodes = self._attribute_nodes()
            infos = scene_attributes.snapshot(nodes[0], self._attr_rows.picked() or None) if nodes else []
        if not infos:
            self._say("Nothing to save: copy attributes first, or select an object that has some", "error")
            return
        sets = self._attribute_sets()
        replaced = name in sets
        sets[name] = infos
        self._settings["attribute_sets"] = sets
        self._say(f"The set “{name}” {'saved over' if replaced else 'saved'}: {len(infos)} "
                  f"attribute{'s' if len(infos) != 1 else ''}", "done")

    def _remove_attribute_set(self, name: str) -> None:
        sets = self._attribute_sets()
        if sets.pop(name, None) is not None:
            self._settings["attribute_sets"] = sets
            self._say(f"The set “{name}” removed", "done")

    def _attr_sets_menu(self) -> "qt.QtWidgets.QMenu":
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        tone = self._attr_sets.iconColor
        menu = self._menu()
        sets = self._attribute_sets()
        self._menu_caption(menu, "Put a set on the selection" if sets else "No sets saved yet")
        for name, infos in sets.items():
            listed = ", ".join(str(info.get("name", "")) if info.get("kind") != "Separator" else "—" for info in infos[:6])
            self._menu_item(menu, "bookmark", name, lambda infos=infos, name=name: self._paste_attrs(infos, name),
                            listed + ("…" if len(infos) > 6 else ""), tone, hint=str(len(infos)))
        menu.addSeparator()
        copied = len(_AttributesMixin._attr_clipboard)
        self._menu_caption(menu, (f"Save the {copied} copied as a set" if copied else
                                  "Save the selection's attributes as a set") + " — its name:")
        _field_action(menu, "", "Set name", self._save_attribute_set)
        if sets:
            menu.addSeparator()
            removing = menu.addMenu("Remove a set")
            removing.setToolTipsVisible(True)
            for name in sets:
                self._menu_item(removing, "delete", name, lambda name=name: self._remove_attribute_set(name))
        return menu

    # ---- the picked rows' bar, a hovered row's small buttons

    def _bulk(self, key: str) -> None:
        picked = self._attr_rows.picked()
        if not picked:
            return
        first = picked[0]
        if key == "key":
            self._key_attributes(first)
        elif key == "default":
            self._default_attributes(first)
        elif key == "lock":
            self._on_attr_lock_clicked(first)
        elif key == "hide":
            button = self._bulk_buttons["hide"]
            self._attr_row_menu(first, "key").exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height())))

    def _on_attr_action(self, name: str, key: str, position) -> None:
        """One of the small buttons beside a hovered row's name — for THAT attribute alone."""
        if key == "range":
            self._attr_row_menu(name, "range").exec(position)
            return
        was = self._attr_rows.picked()
        if name in was and len(was) > 1:
            # the button of one row acts on that row, whatever else is picked
            from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
            nodes = self._attribute_nodes()
            if nodes and key == "key":
                count = scene_attributes.set_key(nodes, [name])
                self._say(f"{count} key{'s' if count != 1 else ''} on {name}", "done" if count else "error")
            elif nodes:
                scene_attributes.to_default(nodes, [name])
                self._say(f"{name} back to default", "done")
            self._after_attribute_change()
        elif key == "key":
            self._key_attributes(name)
        else:
            self._default_attributes(name)

    def _on_attr_order(self, names: list) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        if not nodes:
            return
        refused, done = "", 0
        for node in nodes:
            why = scene_attributes.reorder(node, names)
            if why:
                refused = refused or why
            else:
                done += 1
        if refused and not done:
            self._say("Not moved: " + refused, "error")
        else:
            self._say(f"The attributes are in that order on {done}" + (f" · not on all: {refused}" if refused else "")
                      + " · Ctrl+Z undoes it", "done")
        self._after_attribute_change()

    # ---- what a row's own widgets do

    def _on_attr_renamed(self, old: str, new: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._needs_selection()
        if not nodes:
            return
        name, done, why = scene_attributes.rename_attribute(nodes, old, new)
        if why:
            self._say(f"Not renamed: {why}", "error")
        elif done:
            self._say((f"The line reads “{new}”" if name == old else f"“{old}” is “{name}” now") +
                      f" on {done} · Ctrl+Z undoes it", "done")
        self._after_attribute_change()

    def _on_attr_value(self, name: str, value) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        if nodes:
            count = scene_attributes.set_value(nodes, name, value)
            if not count:
                self._say(f"“{name}” is locked or fed by a connection: not changed", "error")
            self._after_attribute_change()

    _attr_drag = None        # (the attribute, {node: the value it had}) while a value is dragged

    def _on_attr_drag_started(self, name: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        self._attr_drag = (name, scene_attributes.get_values(nodes, name)) if nodes else None

    def _on_attr_dragged(self, name: str, value) -> None:
        """The in-between values of a drag go into the scene at once — and leave no undo steps."""
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        if self._attr_drag and self._attr_drag[0] == name:
            scene_attributes.set_value(list(self._attr_drag[1]), name, value, undoable=False)

    def _on_attr_drag_finished(self, name: str, value) -> None:
        """The drag is ONE undo step: back to where it started (no trace), then to where it ended."""
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        drag, self._attr_drag = self._attr_drag, None
        if drag and drag[0] == name and drag[1]:
            scene_attributes.restore_values(drag[1], name)
            scene_attributes.set_value(list(drag[1]), name, value)
        self._after_attribute_change()

    def _on_attr_key_clicked(self, name: str) -> None:
        """K: keyable <-> shown only (a hidden one becomes keyable)."""
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        if nodes:
            info = scene_attributes.describe(nodes[0], name) or {}
            self._set_attr_show(name, "shown" if info.get("keyable") else "key")

    def _set_attr_show(self, name: str, state: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        if not nodes:
            return
        names = self._attr_rows.picked() if name in self._attr_rows.picked() else [name]
        if state == "hidden":
            scene_attributes.set_flags(nodes, names, hidden=True)
        else:
            scene_attributes.set_flags(nodes, names, keyable=state == "key")
        words = {"key": "keyable", "shown": "shown only, not keyable", "hidden": "out of the Channel Box"}[state]
        self._say(f"{', '.join(names[:3])}{'…' if len(names) > 3 else ''}: {words}", "done")
        self._after_attribute_change()

    def _on_attr_lock_clicked(self, name: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        if nodes:
            info = scene_attributes.describe(nodes[0], name) or {}
            names = self._attr_rows.picked() if name in self._attr_rows.picked() else [name]
            now = not info.get("locked", False)
            scene_attributes.set_flags(nodes, names, locked=now)
            self._say(f"{', '.join(names[:3])}{'…' if len(names) > 3 else ''}: {'locked' if now else 'unlocked'}", "done")
            self._after_attribute_change()

    def _key_attributes(self, name: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        if nodes:
            names = self._attr_rows.picked() if name in self._attr_rows.picked() else [name]
            count = scene_attributes.set_key(nodes, names)
            self._say(f"{count} key{'s' if count != 1 else ''} set at the current frame · Ctrl+Z undoes it"
                      if count else "No key set: locked", "done" if count else "error")
            self._after_attribute_change()

    def _default_attributes(self, name: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        if nodes:
            names = self._attr_rows.picked() if name in self._attr_rows.picked() else [name]
            count = scene_attributes.to_default(nodes, names)
            self._say(f"{count} back to default · Ctrl+Z undoes it" if count else
                      "Nothing changed: locked or fed by a connection", "done" if count else "")
            self._after_attribute_change()

    def _apply_range(self, name: str, low: str, high: str, default: str) -> None:
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        nodes = self._attribute_nodes()
        values = [self._number(text) for text in (low, high, default)]
        if any(value is False for value in values):
            self._say("min, max and the default are numbers (min and max may be empty: no limit)", "error")
            return
        if nodes:
            count = scene_attributes.edit_range(nodes, name, *values)
            self._say(f"The range of “{name}” changed on {count}" if count else f"“{name}” has no range to change",
                      "done" if count else "error")
            self._after_attribute_change()

    def _range_fields(self, menu, name: str, info: dict) -> None:
        """min · max · default as three fields inside a menu; Enter in any of them applies all three."""
        holder = qt.QtWidgets.QWidget()
        box = qt.QtWidgets.QHBoxLayout(holder)
        box.setContentsMargins(8, 4, 8, 4)
        box.setSpacing(4)
        fields = []
        for key, hint, tip in (("minimum", "min", "The least (empty: no limit)"),
                               ("maximum", "max", "The most (empty: no limit)"),
                               ("default", "default", "The value it starts with")):
            field = qt.QtWidgets.QLineEdit("" if info.get(key) is None else f"{info[key]:g}")
            field.setPlaceholderText(hint)
            field.setToolTip(tip)
            field.setFixedWidth(56)
            box.addWidget(field)
            fields.append(field)
        action = qt.QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)

        def finish():
            texts = [field.text() for field in fields]
            menu.close()
            self._apply_range(name, *texts)
        for field in fields:
            field.returnPressed.connect(finish)

    def _attr_row_menu(self, name: str, where: str) -> "qt.QtWidgets.QMenu":
        """The menu of a row: `where` = "value" (key it, default, its range), "key" (how it shows in
        the Channel Box) or "row" (everything)."""
        from msl_tools.msl.tools.maya.controls import attributes as scene_attributes
        menu = self._menu()
        nodes = self._attribute_nodes()
        info = (scene_attributes.describe(nodes[0], name) if nodes else None) or {}
        separator = info.get("kind") == scene_attributes.SEPARATOR
        picked = self._attr_rows.picked()
        several = len(picked) if name in picked else 1
        title = f"{several} attributes" if several > 1 else ("The separator line" if separator else name)
        if where == "range":
            self._menu_caption(menu, f"The range of {name}: min · max · default (Enter applies)")
            self._range_fields(menu, name, info)
            return menu
        if where == "key":
            self._menu_caption(menu, f"{title} in the Channel Box")
            state = "key" if info.get("keyable") else "shown" if info.get("shown") else "hidden"
            for key, icon, text, tip in (("key", "timeline", "Keyable", "Shown, and it can be keyed"),
                                         ("shown", "eye", "Shown only", "Shown, but it can't be keyed"),
                                         ("hidden", "eye_off", "Hidden", "Not in the Channel Box at all")):
                self._menu_item(menu, icon, text, lambda key=key: self._set_attr_show(name, key), tip,
                                hint="✓" if key == state else "")
            return menu
        self._menu_caption(menu, title)
        if not separator:
            self._menu_item(menu, "timeline", "Key it", lambda: self._key_attributes(name),
                            "A key at the current frame, on every selected object")
            self._menu_item(menu, "restart", "Back to default", lambda: self._default_attributes(name),
                            f"default: {info.get('default')}")
            if several == 1 and info.get("kind") in (scene_attributes.FLOAT, scene_attributes.WHOLE):
                menu.addSeparator()
                self._menu_caption(menu, "Its range: min · max · default (Enter applies)")
                self._range_fields(menu, name, info)
        if where == "row":
            menu.addSeparator()
            if several == 1:
                row = self._attr_rows.row(name)
                self._menu_item(menu, "edit", "Change its text" if separator else "Rename",
                                lambda: row is not None and row._start_rename(), hint="double click")
            self._menu_item(menu, "copy", "Copy", lambda: self._copy_attrs(name),
                            "Remembered with its kind, range, default and value — select another object and "
                            "paste (the button in the card's heading)")
            self._menu_item(menu, "delete", "Remove", lambda: self._on_remove_attributes(name),
                            "From every selected object")
        return menu

    def _on_attr_menu(self, name: str, where: str, position) -> None:
        self._attr_row_menu(name, where).exec(position)
