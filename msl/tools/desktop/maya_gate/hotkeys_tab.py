# tools/desktop/maya_gate/hotkeys_tab.py
import os
import time

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.fs.safe_json import JsonUnavailable
from msl_tools.msl.core.link import hotkey_keys, protocol
from msl_tools.msl.tools.maya import hotkey_catalog
from msl_tools.msl.ui.icon_manager import tinted_menu_icon
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.editors.key_capture_field import KeyCaptureField, modifier_names
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.atoms.tooltips.arrow_tooltip import ArrowTooltip
from msl_tools.msl.tools.desktop.maya_gate.hotkeys_keyboard import KeyboardMap
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.toast_stack import show_toast
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.core.theme import ThemeRegistry


# each group's icons in a palette hue (maya_gate.qss: TintedIcon#hotkeyIcon[tone=...]) - the tools' own colors
# where a tool has one (Controls violet, Rename blue...); the colors come from the theme's palette
GROUP_TONES = {"Animation": "success", "Playblast": "orange", "Rename": "accent", "Controls": "violet", "Labels": "yellow", "Scene": "teal",
               "Camera": "pink", "Viewport": "success", "Attributes": "error", "Rig": "violet", "Show": "yellow"}


def _icon(name: str) -> qt.QtGui.QIcon:
    return UiResources().iconManager.get_icon(name, sub_folder="actions")


class _HotkeyRow(qt.QtWidgets.QFrame):
    """One command: its icon, its name (what it does in the tooltip), a mark when its key is used for something
    else, the key as caps, "try it" in a running Maya. A click on the row's free room picks it (Ctrl / Shift
    for more) - for "copy the picked to another environment"."""

    key_changed = qt.QtCore.Signal(str, str)     # (command, key text or "")
    try_requested = qt.QtCore.Signal(str)
    clicked = qt.QtCore.Signal(str, object)      # (command, keyboard modifiers)
    warned = qt.QtCore.Signal(str, str, str)     # (command, the key held back, what else uses it)
    warn_ended = qt.QtCore.Signal()
    free_requested = qt.QtCore.Signal(str, qt.QtCore.QPoint)   # (command, global position): the free keys' menu
    release_toggled = qt.QtCore.Signal(str, bool)              # (command, run again when the key is let go)
    capture_started = qt.QtCore.Signal(str)                    # its key field listens now

    def __init__(self, command, check=None, parent=None):
        super().__init__(parent)
        self.command = command
        self.setObjectName("hotkeyRow")
        self.setProperty("picked", False)
        self._icon = TintedIcon(_icon(command.icon), 16)
        self._icon.setObjectName("hotkeyIcon")
        self._icon.setProperty("tone", GROUP_TONES.get(command.group, "accent"))
        self._name = qt.QtWidgets.QLabel(command.label)
        self._name.setObjectName("hotkeyName")
        self._name.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._name.setMinimumWidth(60)
        tip = "%s\n%s\n(Maya: %s)" % (command.label, command.annotation, command.name)
        for widget in (self, self._name, self._icon):
            widget.setToolTip(tip)
        self._mark = TintedIcon(_icon("warning"), 14)
        self._mark.setObjectName("hotkeyMark")
        self._mark.setProperty("tone", "")
        size_policy = self._mark.sizePolicy()
        size_policy.setRetainSizeWhenHidden(True)
        self._mark.setSizePolicy(size_policy)
        self._mark.hide()
        self.field = KeyCaptureField(accept=lambda text: bool(hotkey_keys.normalize(text)),
                                     check=(lambda text: check(command.name, text)) if check else None)
        self.field.setFixedWidth(150)
        self.field.setToolTip("Click, then press the keys.\nEsc — leave it as it is · × or Backspace — no key\n"
                              "Right click — keys nobody uses")
        self.field.key_changed.connect(lambda text: self.key_changed.emit(self.command.name, text))
        self.field.warned.connect(lambda text, note: self.warned.emit(self.command.name, text, note))
        self.field.warn_ended.connect(self.warn_ended)
        self.field.capture_started.connect(lambda: self.capture_started.emit(self.command.name))
        self.field.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.field.customContextMenuRequested.connect(
            lambda position: self.free_requested.emit(self.command.name, self.field.mapToGlobal(position)))
        # not yet in a running Maya of the environment: "Apply" would change this one
        # what the running Maya has there now, struck through ("~~Alt+3~~ →"), while it differs from the field
        self._pending = qt.QtWidgets.QLabel()
        self._pending.setObjectName("hotkeyPending")
        self._pending.setTextFormat(qt.QtCore.Qt.TextFormat.RichText)
        self.setProperty("changed", False)
        policy = self._pending.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self._pending.setSizePolicy(policy)
        self._pending.hide()
        self.try_button = GlyphButton("▶", "", size=qt.QtCore.QSize(22, 22))
        self.try_button.setObjectName("hotkeyTry")
        self.try_button.set_icon(_icon("play"))
        self.try_button.clicked.connect(lambda: self.try_requested.emit(self.command.name))

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 4, 2)
        layout.setSpacing(8)
        layout.addWidget(self._icon)
        layout.addWidget(self._name, 1)
        layout.addWidget(self._mark)
        layout.addWidget(self._pending)
        layout.addWidget(self.field)
        # on / off commands only: "hold" = Maya runs it again when the key is let go (press shows, release hides)
        self.release = qt.QtWidgets.QPushButton("hold")
        self.release.setObjectName("hotkeyRelease")
        self.release.setCheckable(True)
        self.release.setFixedSize(42, 22)
        self.release.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.release.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.release.setToolTip("Hold to see\nOn: Maya runs it again when the key is let go — hold the key to see, "
                                "let go and it is back as it was.\nOff: one press switches it, the next switches back.")
        self.release.toggled.connect(lambda on: self.release_toggled.emit(self.command.name, on))
        policy = self.release.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.release.setSizePolicy(policy)
        if not command.toggle:
            self.release.hide()
        layout.addWidget(self.release)
        layout.addWidget(self.try_button)

    def set_key(self, text: str) -> None:
        self.field.set_text(text)

    def set_mark(self, tone: str, tooltip: str) -> None:
        """tone "" (none), "warning" (the key does something else in Maya - ours wins), "error" (two of ours)."""
        if not tone:
            self._mark.hide()
            return
        self._mark.set_icon(_icon("error" if tone == "error" else "warning"))
        if self._mark.property("tone") != tone:
            self._mark.setProperty("tone", tone)
            repolish(self._mark)
        self._mark.setToolTip(tooltip)
        self._mark.show()

    def set_release(self, on: bool, has_key: bool) -> None:
        blocked = self.release.blockSignals(True)
        self.release.setChecked(on and has_key)
        self.release.blockSignals(blocked)
        self.release.setEnabled(has_key)

    def set_pending(self, tooltip: str, was=None) -> None:
        """While a running Maya has something else for this command: the row is marked (an accent bar, a tint) and
        what that Maya has now is shown struck through before the field. `was` = (key text, hold) in that Maya,
        or None for no key there; tooltip "" = in sync."""
        changed = bool(tooltip)
        if bool(self.property("changed")) != changed:
            self.setProperty("changed", changed)
            repolish(self)
        self._pending.setToolTip(tooltip)
        if not changed:
            self._pending.hide()
            return
        old_text, old_hold = was if was else ("", False)
        new_text = self.field.text()
        if old_text and old_text == new_text:      # the same key: only "hold" differs
            shown = "hold %s →" % ("on" if old_hold else "off")
        elif old_text:
            shown = "<s>%s</s> →" % old_text
        else:
            shown = "new →"
        self._pending.setText(shown)
        self._pending.show()

    def set_picked(self, picked: bool) -> None:
        if bool(self.property("picked")) != picked:
            self.setProperty("picked", picked)
            repolish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(self.command.name, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)


class HotkeysTab(qt.QtWidgets.QWidget):
    """Maya Gate's "Hotkeys" tab: keys for OUR Maya commands (the tools' windows and MSL Scripts —
    tools/maya/hotkey_catalog.py), per environment, for every Maya started from here.

    A launch carries the environment's keys (MSL_GATE_HOTKEYS); inside Maya tools/maya/hotkey_set.py makes the
    hotkey set "MSL" as a COPY of the set the user is on (animBot's keys and their own keep working) with
    ours on top; the user's set is never changed, and on quit Maya goes back to it. A running Maya takes
    them at once through "Apply to N running Mayas" (protocol.HOTKEYS_APPLY).

    What a key already does in Maya (Maya's own keys, the user's set) is asked of a running Maya of the
    environment (protocol.HOTKEYS_STATE) and kept (HotkeyStore.seen), so a row can say "Alt+Z is animBot's
    Next Frame in your set" while no Maya runs. A row's ▶ runs the command in the newest running Maya of
    the environment (protocol.RUN_COMMAND: by name, only ours).

    Takes the store and the link; reads nothing from disk until shown.
    """

    STATE_TIMEOUT_MS = 15_000
    MODIFIER_POLL_MS = 60
    APPLY_TIMEOUT_MS = 20_000
    ALL = "all"

    menuIconColor = color_property("_menu_icon_color", None)

    def __init__(self, store, environment: str, environments, link, english_for=None, settings=None, parent=None):
        super().__init__(parent)
        self._menu_icon_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_secondary)
        self._store = store
        self._environment = environment
        self._environments = list(environments)
        self._link = link
        self._english_for = english_for       # environment -> its Maya keeps an English layout (Maya Gate's "EN")
        self._settings = settings             # the page's `_ui` node: "hotkeys_keyboard" (the map shown)
        self._seen: dict = {}
        self._seen_for = None            # the environment self._seen belongs to (read when first shown)
        self._asked: set = set()         # (session id) asked for its state already
        self._live: dict = {}            # session id -> the keys that Maya has now (its answer, or what it took)
        self._picked: set = set()
        self._map_choice = ["Ctrl", "Alt"]   # the modifiers picked on the map's chips
        self._held_modifiers: list = []      # Ctrl / Alt / Shift held on the keyboard now: the map follows them
        self._map_pending = ""               # the combination a key field holds back (warned about)
        # like Maya's Hotkey Editor: while the map is on screen, holding modifiers shows what they do
        self._modifier_timer = qt.QtCore.QTimer(self)
        self._modifier_timer.setInterval(self.MODIFIER_POLL_MS)
        self._modifier_timer.timeout.connect(self._poll_modifiers)
        self._last_clicked = ""
        self._group = self.ALL
        self._rows: dict = {}
        self._headers: dict = {}

        self._title = qt.QtWidgets.QLabel()
        self._title.setObjectName("hotkeysTitle")
        hint = qt.QtWidgets.QLabel(
            "Maya gets them as its hotkey set “MSL”, made at every start from the set you are on — your own "
            "keys (animBot…) keep working, a key here wins where both use one. Your set is never changed, and "
            "Maya goes back to it on quit.")
        hint.setObjectName("hotkeysHint")
        hint.setWordWrap(True)

        self._search = qt.QtWidgets.QLineEdit()
        self._search.setObjectName("hotkeysSearch")
        self._search.setPlaceholderText("Find a command or a key")
        self._search.setClearButtonEnabled(True)
        self._search.setMaximumWidth(220)
        self._copy_button = self._tool("arrow_right", "Copy keys to another environment — all, or the picked rows")
        self._import_button = self._tool("file_add", "Import keys from a file…")
        self._export_button = self._tool("save", "Export this environment’s keys to a file…")
        self._clear_button = self._tool("clear", "Clear keys — all, or the picked rows…")
        self._clear_button.setProperty("danger", True)
        self._chips = ChipBar(checkable=True)
        self._chips.set_chips([(self.ALL, "All", "Every command")]
                              + [(group, group, "") for group in hotkey_catalog.GROUPS])
        self._chips.set_current(self.ALL)

        self._list = qt.QtWidgets.QWidget()
        self._list.setObjectName("hotkeysList")
        list_layout = qt.QtWidgets.QVBoxLayout(self._list)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(1)
        for group in hotkey_catalog.GROUPS:
            commands = [command for command in hotkey_catalog.commands() if command.group == group]
            if not commands:
                continue
            header = qt.QtWidgets.QLabel(group.upper())
            header.setObjectName("hotkeysGroup")
            self._headers[group] = header
            list_layout.addWidget(header)
            for command in commands:
                row = _HotkeyRow(command, check=self._check_key)
                row.key_changed.connect(self._on_key_changed)
                row.warned.connect(self._on_warned)
                row.warn_ended.connect(self._end_warning)
                row.free_requested.connect(self._on_free_menu)
                row.release_toggled.connect(self._on_release_toggled)
                row.capture_started.connect(self._on_capture_started)
                row.try_requested.connect(self._on_try)
                row.clicked.connect(self._on_row_clicked)
                self._rows[command.name] = row
                list_layout.addWidget(row)
        list_layout.addStretch()
        self._empty = qt.QtWidgets.QLabel("No command matches.")
        self._empty.setObjectName("hotkeysHint")
        self._empty.hide()
        list_layout.insertWidget(0, self._empty)
        scroll = StableScrollArea()
        scroll.setWidget(self._list)
        self._scroll = scroll

        # the keyboard map: what every key does with the modifiers picked above it (shown by the keyboard button)
        self._keyboard = qt.QtWidgets.QFrame()
        self._keyboard.setObjectName("hotkeysKeyboard")
        self._modifiers = ChipBar(multiple=True)
        self._modifiers.set_chips([(name, name, "") for name in hotkey_keys.MODIFIERS])
        self._modifiers.set_checked(["Ctrl", "Alt"])
        self._map = KeyboardMap()
        self._map_info = qt.QtWidgets.QLabel()
        self._map_info.setObjectName("hotkeysMapInfo")
        self._map_info.setWordWrap(True)
        legend = qt.QtWidgets.QLabel("outlined — ours, in its group’s color · grey — Maya’s or your set’s · "
                                     "dashed — free: click it to give it to the picked command")
        legend.setObjectName("hotkeysHint")
        legend.setWordWrap(True)
        keyboard_layout = qt.QtWidgets.QVBoxLayout(self._keyboard)
        keyboard_layout.setContentsMargins(10, 8, 10, 8)
        keyboard_layout.setSpacing(6)
        keyboard_layout.addWidget(self._modifiers)
        keyboard_layout.addWidget(self._map)
        keyboard_layout.addWidget(self._map_info)
        keyboard_layout.addWidget(legend)
        self._keyboard_button = self._tool("keyboard", "Keyboard map — what each key does, and which are free")
        self._keyboard_button.setCheckable(True)
        shown = bool(settings.get("hotkeys_keyboard", False)) if settings is not None else False
        if not shown:   # never setVisible(True) before the layout adopts it: it would flash as a window
            self._keyboard.hide()
        self._keyboard_button.setChecked(shown)
        self._keyboard_button.setProperty("on", shown)

        # the status bar: how many keys, how many cover something of Maya's / the user's set, the running Mayas
        self._status = qt.QtWidgets.QFrame()
        self._status.setObjectName("hotkeysStatus")
        self._status_keys = self._status_label()
        self._status_cover = self._status_label()
        self._status_sync = self._status_label()
        self._status_layout = self._status_label()
        self._apply_button = qt.QtWidgets.QPushButton()
        self._apply_button.setObjectName("hotkeysApply")
        self._apply_button.setProperty("primary", True)
        self._apply_button.hide()

        top = qt.QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        top.addWidget(self._search, 1)
        top.addStretch()
        top.addWidget(self._keyboard_button)
        for button in (self._copy_button, self._import_button, self._export_button, self._clear_button):
            top.addWidget(button)
        status = qt.QtWidgets.QHBoxLayout(self._status)
        status.setContentsMargins(10, 4, 4, 4)
        status.setSpacing(14)
        for label in (self._status_keys, self._status_cover, self._status_layout, self._status_sync):
            status.addWidget(label)
        status.addStretch()
        status.addWidget(self._apply_button)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(hint)
        layout.addWidget(self._status)
        layout.addLayout(top)
        layout.addWidget(self._chips)
        layout.addWidget(self._keyboard)
        layout.addWidget(scroll, 1)

        self._search.textChanged.connect(self._filter)
        self._chips.clicked.connect(self._on_group)
        self._copy_button.clicked.connect(self._on_copy_menu)
        self._import_button.clicked.connect(self._on_import)
        self._export_button.clicked.connect(self._on_export)
        self._clear_button.clicked.connect(self._on_clear)
        self._apply_button.clicked.connect(self._on_apply)
        self._link.sessions_changed.connect(self._on_sessions_changed)
        self._keyboard_button.clicked.connect(self._on_keyboard_button)
        self._modifiers.clicked.connect(self._on_modifier_chip)
        self._map.hovered.connect(self._on_map_hovered)
        self._map.clicked.connect(self._on_map_clicked)
        self._show_environment()

    @staticmethod
    def _status_label() -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel()
        label.setObjectName("hotkeysStatusPart")
        label.setProperty("state", "")
        return label

    @staticmethod
    def _set_state(label: qt.QtWidgets.QLabel, text: str, state: str, tooltip: str = "") -> None:
        label.setText(text)
        label.setToolTip(tooltip)
        label.setVisible(bool(text))
        if label.property("state") != state:
            label.setProperty("state", state)   # maya_gate.qss: ok / warning / behind / quiet
            repolish(label)

    @staticmethod
    def _tool(icon: str, tooltip: str) -> GlyphButton:
        button = GlyphButton("", tooltip, size=qt.QtCore.QSize(24, 22))
        button.setObjectName("hotkeysTool")
        button.set_icon(_icon(icon))
        return button

    def _menu_icon(self, name: str) -> qt.QtGui.QIcon:
        return tinted_menu_icon(_icon(name), self._menu_icon_color, self.devicePixelRatioF())

    # --- the environment ------------------------------------------------------------------------------

    def set_environment(self, environment: str) -> None:
        self._environment = environment
        self._picked.clear()
        self._show_environment()
        if self.isVisible():
            self._read_seen()
            self._ask_state()

    def _show_environment(self) -> None:
        self._title.setText("Keys in %s" % self._environment)
        keys = self._store.keys(self._environment)
        release = self._store.release(self._environment)
        for name, row in self._rows.items():
            row.set_key(keys.get(name, ""))
            row.set_release(name in release, name in keys)
            row.set_picked(name in self._picked)
        self._show_marks()
        self._filter()

    def refresh(self) -> None:
        """Something around the tab changed (the toolbar's "EN"): say it again."""
        self._show_marks()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._watch_modifiers()
        self._read_seen()
        self._ask_state()
        self._show_marks()

    def _read_seen(self) -> None:
        if self._seen_for != self._environment:
            self._seen_for = self._environment
            self._seen = self._store.seen(self._environment)

    def _running(self) -> list:
        """The connected Mayas of this environment, newest first."""
        return sorted((session for session in self._link.sessions() if session.environment == self._environment),
                      key=lambda session: session.connected_at, reverse=True)

    # --- marks: what a key also does ----------------------------------------------------------------

    def _show_marks(self) -> None:
        keys = self._store.keys(self._environment)
        clashes = hotkey_keys.clashes(keys)
        bindings = self._seen.get("bindings", {}) if self._seen_for == self._environment else {}
        base = self._seen.get("base") or "your set"
        shadowed = 0
        for name, row in self._rows.items():
            text = keys.get(name, "")
            if not text:
                row.set_mark("", "")
                continue
            others = [self._label(other) for other in clashes.get(text, []) if other != name]
            if others:
                row.set_mark("error", "%s is also given to %s here." % (text, ", ".join(others)))
                continue
            binding = bindings.get(text)
            if binding and binding.get("command") != name:
                shadowed += 1
                if binding.get("from") == "set":
                    row.set_mark("warning", "%s\nIn your hotkey set “%s” this key is: %s.\nIn Maya started from here "
                                 "this command wins; the set itself keeps it." % (text, base, binding.get("label")))
                else:
                    row.set_mark("warning", "%s\nMaya’s own key for: %s.\nIn Maya started from here this command "
                                 "wins." % (text, binding.get("label")))
                continue
            row.set_mark("", "")
        self._show_status(keys, shadowed, bool(bindings))
        self._show_counts(keys)
        self._show_map()

    def _show_counts(self, keys: dict) -> None:
        """The group chips say how many of their commands have a key ("Controls · 3")."""
        counts = {}
        for name in keys:
            row = self._rows.get(name)
            if row is not None:
                counts[row.command.group] = counts.get(row.command.group, 0) + 1
        self._chips.set_text(self.ALL, "All · %d" % len(keys) if keys else "All")
        for group in hotkey_catalog.GROUPS:
            self._chips.set_text(group, "%s · %d" % (group, counts[group]) if counts.get(group) else group)

    # --- while a key is typed: what else uses it, and keys nobody uses ----------------------------------

    def _taken(self, name: str) -> dict:
        """{key text: what uses it} - Maya's own and the user's set (as last seen), and our other commands here."""
        taken = {}
        base = self._seen.get("base") or "your set"
        bindings = self._seen.get("bindings", {}) if self._seen_for == self._environment else {}
        for text, binding in bindings.items():
            if binding.get("command") != name:
                if binding.get("from") == "set":
                    taken[text] = "in your set “%s”: %s" % (base, binding.get("label"))
                else:
                    taken[text] = "Maya’s own: %s" % binding.get("label")
        for other, text in self._store.keys(self._environment).items():
            if other != name:
                taken[text] = "%s has it here — it would move to this one" % self._label(other)
        return taken

    def _check_key(self, name: str, text: str) -> str:
        """What the field says before taking `text` for `name` ("" = take it at once)."""
        text = hotkey_keys.normalize(text)
        used = self._taken(name).get(text)
        if used:
            note = used[0].upper() + used[1:] + "."
            if "would move" not in used:
                note += " In Maya started from here this command wins; that one is covered."
            return note
        if text and not hotkey_keys.has_modifier(text):
            return "A key without Ctrl or Alt — Maya and you type plain keys all the time."
        return ""

    def _on_warned(self, name: str, text: str, note: str) -> None:
        field = self._rows[name].field
        rect = qt.QtCore.QRect(field.mapToGlobal(qt.QtCore.QPoint(0, 0)), field.size())
        ArrowTooltip.shared(self).show_at(rect, "%s is taken" % text,
                                          note + "\nPress it again or Enter to take it — or another key; Esc gives up.")
        self._map_pending = text          # the map rings it too
        self._show_map()

    def _end_warning(self) -> None:
        tip = ArrowTooltip.shared(self, create=False)
        if tip is not None:
            tip.dismiss()
        self._map_pending = ""
        self._show_map()

    def _on_free_menu(self, name: str, position) -> None:
        self.free_menu(name).popup(position)

    def free_menu(self, name: str) -> qt.QtWidgets.QMenu:
        """Keys nobody uses (Maya, your set as last seen, our other commands), the command's letters first."""
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        checked = bool(self._seen.get("bindings")) and self._seen_for == self._environment
        caption = menu.addAction("FREE KEYS" + ("" if checked else " — not checked against Maya yet"))
        caption.setEnabled(False)
        for text in hotkey_keys.free_keys(self._label(name), self._taken(name)):
            action = menu.addAction(self._menu_icon("keyboard"), text)
            action.triggered.connect(lambda _checked=False, text=text: self._on_key_changed(name, text))
        if self._store.keys(self._environment).get(name):
            menu.addSeparator()
            menu.addAction(self._menu_icon("clear"), "No key").triggered.connect(
                lambda: self._on_key_changed(name, ""))
        self._free_menu = menu   # for tests
        return menu

    def _on_release_toggled(self, name: str, on: bool) -> None:
        self._store.set_release_of(self._environment, name, on)
        self._show_marks()

    # --- the keyboard map ------------------------------------------------------------------------------

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._modifier_timer.stop()

    def _watch_modifiers(self) -> None:
        if self._keyboard_button.isChecked() and self.isVisible():
            self._modifier_timer.start()
        else:
            self._modifier_timer.stop()
            self._held_modifiers = []

    def _poll_modifiers(self) -> None:
        """The map follows Ctrl / Alt / Shift held on the keyboard (any time, also while a key field listens); let go,
        it is back on the chips' own choice. queryKeyboardModifiers: the keyboard's state, not the last event's."""
        held = modifier_names(qt.QtGui.QGuiApplication.queryKeyboardModifiers())
        if held != self._held_modifiers:
            self._held_modifiers = held
            self._modifiers.set_checked(held or self._map_choice)
            self._show_map()

    def _on_modifier_chip(self, _key: str) -> None:
        self._map_choice = [name for name in hotkey_keys.MODIFIERS if name in self._modifiers.checked()]
        self._show_map()

    def _set_map_choice(self, modifiers) -> None:
        self._map_choice = [name for name in hotkey_keys.MODIFIERS if name in modifiers]
        if not self._held_modifiers:
            self._modifiers.set_checked(self._map_choice)

    def _on_capture_started(self, name: str) -> None:
        """A key field listens: its command is the picked one (the map rings its key, a free key goes to it)."""
        self._picked = {name}
        self._last_clicked = name
        for other, row in self._rows.items():
            row.set_picked(other == name)
        parsed = hotkey_keys.parse(self._store.keys(self._environment).get(name, ""))
        if parsed:
            self._set_map_choice(parsed[0])
        self._show_map()

    def _on_keyboard_button(self) -> None:
        shown = self._keyboard_button.isChecked()
        self._keyboard.setVisible(shown)
        self._watch_modifiers()
        self._keyboard_button.setProperty("on", shown)
        repolish(self._keyboard_button)
        if self._settings is not None:
            self._settings["hotkeys_keyboard"] = shown
        self._show_map()

    def _map_modifiers(self) -> list:
        return list(self._held_modifiers) or [name for name in hotkey_keys.MODIFIERS if name in self._modifiers.checked()]

    def _map_entries(self) -> dict:
        """{character: (state, tone, says)} for the modifiers picked: ours, then what Maya / the user's set use."""
        modifiers = self._map_modifiers()
        entries = {}
        bindings = self._seen.get("bindings", {}) if self._seen_for == self._environment else {}
        base = self._seen.get("base") or "your set"
        for text, binding in bindings.items():
            parsed = hotkey_keys.parse(text)
            if parsed and set(parsed[0]) == set(modifiers):
                says = ("your set “%s”: " % base if binding.get("from") == "set" else "Maya: ") + str(binding.get("label"))
                entries[parsed[1]] = ("taken", "", says)
        for name, text in self._store.keys(self._environment).items():
            parsed = hotkey_keys.parse(text)
            row = self._rows.get(name)
            if parsed and row is not None and set(parsed[0]) == set(modifiers):
                entries[parsed[1]] = ("ours", GROUP_TONES.get(row.command.group, "accent"), "ours: " + row.command.label)
        return entries

    def _show_map(self) -> None:
        if not self._keyboard_button.isChecked():
            return
        entries = self._map_entries()
        self._map.set_keys({key: (state, tone) for key, (state, tone, _says) in entries.items()})
        picked = next(iter(self._picked)) if len(self._picked) == 1 else ""
        ringed = self._map_pending or (self._store.keys(self._environment).get(picked, "") if picked else "")
        parsed = hotkey_keys.parse(ringed)
        self._map.set_highlight(parsed[1] if parsed and set(parsed[0]) == set(self._map_modifiers()) else "")
        self._on_map_hovered("")

    def _combination(self, key: str) -> str:
        return hotkey_keys.compose(self._map_modifiers(), key)

    def _on_map_hovered(self, key: str) -> None:
        if not key:
            checked = bool(self._seen.get("bindings")) and self._seen_for == self._environment
            picked = next(iter(self._picked)) if len(self._picked) == 1 else ""
            self._map_info.setText(("Picked: %s — click a free key to give it to it." % self._label(picked)) if picked
                                   else "Pick a command in the list, then click a free key."
                                   + ("" if checked else " Maya’s keys aren’t known yet: start a Maya of %s."
                                      % self._environment))
            return
        entry = self._map_entries().get(key)
        text = self._combination(key) or key
        self._map_info.setText("%s — %s" % (text, entry[2] if entry else "free"))

    def _on_map_clicked(self, key: str) -> None:
        entry = self._map_entries().get(key)
        text = self._combination(key)
        if entry and entry[0] == "ours":
            name = next((name for name, value in self._store.keys(self._environment).items() if value == text), "")
            if name:   # show that command in the list
                self._picked = {name}
                self._last_clicked = name
                for other, row in self._rows.items():
                    row.set_picked(other == name)
                if self._rows[name].isVisible():
                    self._scroll.ensureWidgetVisible(self._rows[name])
                self._show_map()
            return
        picked = next(iter(self._picked)) if len(self._picked) == 1 else ""
        if not picked:
            show_toast(self, "Pick a command in the list first (one row), then click the key.", seconds=4)
            return
        if entry and entry[0] == "taken":
            answer = ConfirmDialog.ask(self, "%s is taken" % text, "%s.\nGive it to %s anyway? In Maya started from "
                                       "here ours wins." % (entry[2][0].upper() + entry[2][1:], self._label(picked)),
                                       choices=[("take", "Give it"), ("cancel", "Cancel")])
            if answer != "take":
                return
        if text:
            self._on_key_changed(picked, text)

    def _label(self, name: str) -> str:
        row = self._rows.get(name)
        return row.command.label if row else name

    def _show_status(self, keys: dict, shadowed: int, checked: bool) -> None:
        """The bar on top: keys · what they cover · the running Mayas (in sync or not) + Apply; the rows' dots."""
        count = len(keys)
        checked_text = ("Checked against Maya %s (its set “%s”), %s." % (
            self._seen.get("version") or "", self._seen.get("base") or "?",
            time.strftime("%d %b %H:%M", time.localtime(self._seen.get("time") or 0))) if checked else
            "Not checked against Maya yet: when a Maya of %s runs, the keys Maya and your set use are read."
            % self._environment)
        self._set_state(self._status_keys, ("%d key%s" % (count, "" if count == 1 else "s")) if count
                        else "No keys yet — click a field and press the keys", "",
                        "Maya takes them at its next start from Maya Gate.\n" + checked_text)
        if shadowed:
            self._set_state(self._status_cover, "⚠  %d cover a key of Maya or your set — ours win" % shadowed,
                            "warning", checked_text)
        else:
            self._set_state(self._status_cover, "" if checked or not count else "?  not checked against Maya yet",
                            "quiet", checked_text)
        letters = [text for text in keys.values() if (hotkey_keys.parse(text) or ((), ""))[1].isalpha()
                   and len((hotkey_keys.parse(text) or ((), ""))[1]) == 1]
        english = self._english_for(self._environment) if self._english_for is not None else True
        if letters and not english:
            self._set_state(self._status_layout, "⚠  EN is off: letter keys don’t work in a Russian layout", "warning",
                            "Maya’s hotkeys follow the layout: with a Russian layout Ctrl+Alt+R reaches Maya as a "
                            "Cyrillic letter and nothing runs (measured).\nSwitch on “EN” in the toolbar for %s — Maya "
                            "then keeps an English layout while it is active." % self._environment)
        else:
            self._set_state(self._status_layout, "", "")
        running = self._running()
        self._apply_button.setVisible(bool(running))
        pending, was = {}, {}
        signature = self._signature()
        for session in running:
            live = self._live.get(session.session_id)
            if live is None:
                continue        # hasn't answered (yet): nothing to compare with
            for name in set(live) | set(signature):
                if live.get(name) != signature.get(name):
                    pending.setdefault(name, []).append("Maya %s" % session.version)
                    was.setdefault(name, live.get(name))
        for name, row in self._rows.items():
            if name not in pending:
                row.set_pending("")
                continue
            old = was.get(name)
            said = ("%s has %s here" % (", ".join(pending[name]), old[0] + (" (hold)" if old[1] else ""))) if old \
                else "%s has no key here" % ", ".join(pending[name])
            row.set_pending(said + " — “Apply” changes it now, or its next start.", old)
        if not running:
            self._set_state(self._status_sync, "no Maya of %s running" % self._environment, "quiet")
        else:
            behind = self._behind(running, keys)
            plural = lambda number: "s" if number > 1 else ""
            versions = ", ".join("Maya %s" % session.version for session in running)
            if behind:
                waiting = len(pending)
                self._set_state(self._status_sync, ("●  %d change%s not in %s yet" % (waiting, plural(waiting), versions))
                                if waiting else "●  %s — not compared yet" % versions, "behind")
                self._apply_button.setText("Apply to %d running Maya%s" % (len(behind), plural(len(behind))))
                self._apply_button.setToolTip("These keys aren’t in it yet — now, without a restart: " + ", ".join(
                    "Maya %s (pid %d)" % (session.version, session.pid) for session in behind))
            else:
                self._set_state(self._status_sync, "✓  %s in sync" % versions, "ok")
                self._apply_button.setText("✓ Up to date")
                self._apply_button.setToolTip("Every running Maya of %s has exactly these keys." % self._environment)
            self._apply_button.setEnabled(bool(behind))
            if bool(self._apply_button.property("primary")) != bool(behind):
                self._apply_button.setProperty("primary", bool(behind))
                repolish(self._apply_button)
        for row in self._rows.values():
            row.try_button.setEnabled(bool(running))
            row.try_button.setToolTip(("Try it in Maya %s (%s)" % (running[0].version, self._environment)) if running
                                      else "Try it: start a Maya in %s first" % self._environment)

    # --- filtering and picking ------------------------------------------------------------------------

    def _on_group(self, group: str) -> None:
        self._group = group
        self._filter()

    def _filter(self, *_args) -> None:
        query = self._search.text().strip().lower()
        keys = self._store.keys(self._environment)
        shown_groups, any_shown = set(), False
        for name, row in self._rows.items():
            command = row.command
            text = " ".join([command.label, command.annotation, command.name, keys.get(name, "")]).lower()
            shown = (self._group in (self.ALL, command.group)) and (not query or query in text)
            row.setVisible(shown)
            if shown:
                shown_groups.add(command.group)
                any_shown = True
        for group, header in self._headers.items():
            header.setVisible(group in shown_groups)
        self._empty.setVisible(not any_shown)

    def _on_row_clicked(self, name: str, modifiers) -> None:
        Modifier = qt.QtCore.Qt.KeyboardModifier
        visible = [key for key, row in self._rows.items() if row.isVisible()]
        if modifiers & Modifier.ShiftModifier and self._last_clicked in visible and name in visible:
            first, last = sorted((visible.index(self._last_clicked), visible.index(name)))
            self._picked.update(visible[first:last + 1])
        elif modifiers & Modifier.ControlModifier:
            self._picked.symmetric_difference_update({name})
        else:
            self._picked = set() if self._picked == {name} else {name}
        self._last_clicked = name
        for key, row in self._rows.items():
            row.set_picked(key in self._picked)
        if len(self._picked) == 1:   # the map shows the picked command's modifiers, its key ringed
            parsed = hotkey_keys.parse(self._store.keys(self._environment).get(name, ""))
            if parsed and self._keyboard.isVisible():
                self._set_map_choice(parsed[0])
        self._show_map()

    # --- keys -----------------------------------------------------------------------------------------

    def _on_key_changed(self, name: str, text: str) -> None:
        before = self._store.keys(self._environment)
        taken = self._store.set_key(self._environment, name, text)
        self._show_environment()
        if taken:
            environment = self._environment
            show_toast(self, "%s now opens %s; %s has no key any more." % (
                text, self._label(name), ", ".join(self._label(other) for other in taken)),
                title="Key moved", tone="info", action="Undo",
                on_action=lambda: self._restore(environment, before))

    def _restore(self, environment: str, keys: dict) -> None:
        self._store.replace(environment, keys)
        if environment == self._environment:
            self._show_environment()
        show_toast(self, "Keys of %s put back." % environment, tone="success")

    # --- copy, import, export, clear ----------------------------------------------------------------

    def _on_copy_menu(self) -> None:
        menu = self.copy_menu()
        menu.popup(self._copy_button.mapToGlobal(qt.QtCore.QPoint(0, self._copy_button.height())))

    def copy_menu(self) -> qt.QtWidgets.QMenu:
        """The menu "copy to another environment" (returned, so a test can look at it)."""
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        keys = self._store.keys(self._environment)
        picked = {name: text for name, text in keys.items() if name in self._picked}
        caption = menu.addAction("COPY THE KEYS OF %s TO" % self._environment.upper())
        caption.setEnabled(False)
        for target in self._environments:
            if target == self._environment:
                continue
            every = menu.addAction(self._menu_icon("arrow_right"), "%s — all %d keys" % (target, len(keys)))
            every.setEnabled(bool(keys))
            every.triggered.connect(lambda _checked=False, target=target: self._copy(target, None))
            if picked:
                some = menu.addAction(self._menu_icon("arrow_right"),
                                      "%s — the %d picked" % (target, len(picked)))
                some.triggered.connect(lambda _checked=False, target=target, names=set(picked):
                                       self._copy(target, names))
        if not keys:
            menu.addAction("This environment has no keys yet").setEnabled(False)
        self._copy_menu = menu   # for tests
        return menu

    def _copy(self, target: str, names) -> None:
        source = self._store.keys(self._environment)
        wanted = {name: text for name, text in source.items() if names is None or name in names}
        losing = self._store.conflicts_in(target, wanted)
        replace = True
        if losing:
            answer = ConfirmDialog.ask(
                self, "Keys taken in %s" % target,
                "%d of these keys already open another command in %s: %s." % (
                    len(losing), target, ", ".join(self._label(name) for name in losing[:6])
                    + ("…" if len(losing) > 6 else "")),
                choices=[("replace", "Take them over"), ("keep", "Keep %s’s" % target), ("cancel", "Cancel")],
                kind="question")
            if answer in (None, "cancel"):
                return
            replace = answer == "replace"
        before = self._store.keys(target)
        copied, skipped = self._store.copy_to(self._environment, target, names, replace)
        text = "%d key%s copied to %s." % (len(copied), "" if len(copied) == 1 else "s", target)
        if skipped:
            text += " %d left out: %s already uses them." % (len(skipped), target)
        show_toast(self, text, title="Copied", tone="success", action="Undo",
                   on_action=lambda: self._restore(target, before))

    def _on_import(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(self, "Import MSL hotkeys", "",
                                                                 "MSL hotkeys (*.json)")
        if path:
            self.import_file(path)

    def import_file(self, path: str, answer: str = "") -> bool:
        """Takes the keys of an exported file into this environment - all replaced, or added (`answer` "replace" /
        "add" skips the question)."""
        try:
            keys = self._store.read_file(path)
        except (ValueError, JsonUnavailable, OSError) as error:
            show_toast(self, "%s: %s" % (os.path.basename(path), error), title="Not imported", tone="error")
            return False
        if not answer:
            answer = ConfirmDialog.ask(
                self, "Import hotkeys", "%s holds %d keys. Take them into %s:" % (
                    os.path.basename(path), len(keys), self._environment),
                choices=[("add", "Add to the keys here"), ("replace", "Replace all keys here"), ("cancel", "Cancel")])
        if answer not in ("add", "replace"):
            return False
        environment, before = self._environment, self._store.keys(self._environment)
        file_release = set(self._store.last_read_release)
        if answer == "replace":
            self._store.replace(environment, keys)
            self._store.set_release(environment, file_release)
        else:
            merged, _copied, _skipped = hotkey_keys.copied(keys, before)
            self._store.replace(environment, merged)
            self._store.set_release(environment, self._store.release(environment) | file_release)
        self._show_environment()
        show_toast(self, "%d key%s from %s." % (len(keys), "" if len(keys) == 1 else "s", os.path.basename(path)),
                   title="Imported", tone="success", action="Undo", on_action=lambda: self._restore(environment, before))
        return True

    def _on_export(self) -> None:
        name = "msl_hotkeys_%s.json" % (self._environment.strip("<>") or "default")
        path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Export MSL hotkeys", name,
                                                                 "MSL hotkeys (*.json)")
        if path:
            self.export_file(path)

    def export_file(self, path: str) -> bool:
        try:
            count = self._store.export_file(path, self._environment)
        except OSError as error:
            show_toast(self, str(error), title="Not exported", tone="error")
            return False
        show_toast(self, "%d key%s of %s → %s" % (count, "" if count == 1 else "s", self._environment,
                                                  os.path.basename(path)), title="Exported", tone="success")
        return True

    def _on_clear(self) -> None:
        keys = self._store.keys(self._environment)
        names = {name for name in self._picked if name in keys} or None
        count = len(names) if names else len(keys)
        if not count:
            show_toast(self, "%s has no keys to clear." % self._environment)
            return
        answer = ConfirmDialog.ask(
            self, "Clear keys", "Take away %s in %s?" % (
                ("the keys of the %d picked commands" % count) if names else ("all %d keys" % count),
                self._environment),
            choices=[("clear", "Clear"), ("cancel", "Cancel")], kind="danger")
        if answer == "clear":
            self.clear(names)

    def clear(self, names=None) -> None:
        environment = self._environment
        before = self._store.clear(environment, names)
        self._show_environment()
        show_toast(self, "Keys of %s cleared." % environment, tone="info", action="Undo",
                   on_action=lambda: self._restore(environment, before))

    # --- running Mayas ------------------------------------------------------------------------------

    def _signature(self) -> dict:
        """{command: (key, runs again on release)} of this environment - what a running Maya is compared with."""
        release = self._store.release(self._environment)
        return {name: (text, name in release) for name, text in self._store.keys(self._environment).items()}

    def _behind(self, running: list, keys: dict) -> list:
        """The running Mayas whose keys differ from this environment's (or aren't known yet: they haven't answered)."""
        signature = self._signature()
        return [session for session in running if self._live.get(session.session_id) != signature]

    def _on_sessions_changed(self) -> None:
        self._show_marks()
        if self.isVisible():
            self._ask_state()

    def _ask_state(self) -> None:
        """What the keys do in Maya and which of ours it has - asked of each running Maya of this environment, once
        per session (and again after an apply)."""
        for session in self._running():
            if session.session_id in self._asked:
                continue
            self._asked.add(session.session_id)
            self._link.request(session.session_id, protocol.HOTKEYS_STATE,
                               lambda reply, session=session: self._on_state(session, reply), self.STATE_TIMEOUT_MS)

    def _on_state(self, session, reply: dict) -> None:
        if not reply.get("success"):
            return   # an older Maya ("unknown request") or one that left: nothing to show
        data = reply.get("data") or {}
        released = set(data.get("release") or [])
        self._live[session.session_id] = {name: (text, name in released)
                                           for name, text in hotkey_keys.cleaned(data.get("ours") or {}).items()}
        environment = session.environment
        kept = self._store.save_seen(environment, data, session.version)
        if environment == self._environment:
            self._seen, self._seen_for = kept, environment
        self._show_marks()

    def _on_try(self, name: str) -> None:
        running = self._running()
        if not running:
            return
        session = running[0]
        label = self._label(name)
        self._link.request(session.session_id, protocol.RUN_COMMAND,
                           lambda reply: self._on_tried(label, session.version, reply), self.STATE_TIMEOUT_MS,
                           command=name)

    def _on_tried(self, label: str, version: str, reply: dict) -> None:
        if reply.get("success"):
            show_toast(self, "%s ran in Maya %s." % (label, version), tone="success", seconds=3)
        else:
            show_toast(self, self._why(reply), title="%s didn’t run" % label, tone="error")

    @staticmethod
    def _why(reply: dict) -> str:
        error = str(reply.get("error") or "no answer")
        if "unknown request" in error:
            return "That Maya runs older MSL code — its session menu’s “Reload code” brings it up to date."
        return error

    def _on_apply(self) -> None:
        keys = self._store.keys(self._environment)
        release = sorted(self._store.release(self._environment) & set(keys))
        signature = self._signature()
        running = self._running()
        results: dict = {}

        def answered(session, reply) -> None:
            results[session.session_id] = (session, reply)
            if reply.get("success"):
                self._live[session.session_id] = dict(signature)
            if len(results) == len(running):
                self._applied(list(results.values()), len(keys))

        for session in running:
            self._link.request(session.session_id, protocol.HOTKEYS_APPLY,
                               lambda reply, session=session: answered(session, reply), self.APPLY_TIMEOUT_MS,
                               keys=keys, release=release)
        self._apply_button.setEnabled(False)

    def _applied(self, results: list, count: int) -> None:
        self._show_marks()      # the button: up to date, or still behind for a Maya that failed
        failed = [(session, reply) for session, reply in results if not reply.get("success")]
        done = [(session, reply) for session, reply in results if reply.get("success")]
        if done:
            session, reply = done[0]
            data = reply.get("data") or {}
            clashes = data.get("clashes") or {}
            text = "%d key%s in %s now (set “%s”, made from “%s”)." % (
                count, "" if count == 1 else "s", ", ".join("Maya %s" % s.version for s, _r in done),
                data.get("current") or "", data.get("base") or "")
            if clashes:
                text += " %d replace a key of that set." % len(clashes)
            show_toast(self, text, title="Applied", tone="success")
            for session, _reply in done:
                self._asked.discard(session.session_id)
            self._ask_state()     # what the keys do now
        for session, reply in failed:
            show_toast(self, self._why(reply), title="Maya %s didn’t take them" % session.version, tone="error")
