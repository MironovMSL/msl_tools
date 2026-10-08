# tools/maya/rename/panel_words.py
"""The rename panel's words: the favorites (a star button right of the suffix — its menu holds them;
they were a row of chips) and the WORDS card (the name library by category, the names used last).
Methods of RenamePanel, kept apart by concern."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog

WORD_HINT = "Click: adds “_word” · Alt+click: without “_” · drag it into a field"


def _alt_held() -> bool:
    return bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.AltModifier)


def _field_action(menu, text: str, placeholder: str, on_done) -> None:
    """A line edit inside a menu: Enter takes the text (on_done(text)) and closes the menu."""
    field = qt.QtWidgets.QLineEdit(text)
    field.setPlaceholderText(placeholder)
    field.setMinimumWidth(160)
    holder = qt.QtWidgets.QWidget()
    box = qt.QtWidgets.QHBoxLayout(holder)
    box.setContentsMargins(8, 4, 8, 4)
    box.addWidget(field)
    action = qt.QtWidgets.QWidgetAction(menu)
    action.setDefaultWidget(holder)
    menu.addAction(action)

    def finish():
        value = field.text().strip()
        menu.close()
        if value:
            on_done(value)
    field.returnPressed.connect(finish)
    qt.QtCore.QTimer.singleShot(0, lambda: (field.setFocus(), field.selectAll()))


class _WordsMixin:

    def _favorites_button(self) -> qt.QtWidgets.QPushButton:
        """A star button: its menu holds the favorite words (lit while words go into the name field)."""
        from msl_tools.msl.tools.maya.rename.buttons import QuickButton
        self._into_on = False
        self._favorites = QuickButton(UiResources().iconManager.get_icon("star", sub_folder="actions"), "*", "")
        self._favorites.setObjectName("renameRecipe")  # framed like the recipes' button
        self._show_into()
        return self._favorites

    def _show_into(self) -> None:
        from msl_tools.msl.ui.theme.qss import repolish
        self._favorites.setToolTip("Favorite words — a click: the list of them\n" +
                                   ("Words go into the name field (build the name, then Rename)" if self._into_on else
                                    "A word renames the objects at once: adds “_word” (Alt: without “_”)"))
        if bool(self._favorites.property("on")) != self._into_on:
            self._favorites.setProperty("on", self._into_on)
            repolish(self._favorites)

    def _set_into(self, on: bool) -> None:
        self._into_on = bool(on)
        self._show_into()
        self._save_settings()

    def _on_favorites_menu(self) -> None:
        """The favorite words (hovered = the list shows what it does; a click uses it), "Change"
        (move / take out), a field for a new one, and where words go."""
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        favorites = self.library.favorites()
        for word in favorites:
            action = menu.addAction(word, lambda word=word: self._on_word(word))
            action.hovered.connect(lambda word=word: self._on_word_hovered(word))
        if not favorites:
            none = menu.addAction("No favorites yet")
            none.setEnabled(False)
        else:
            change = make_rounded_popup(menu.addMenu("Change"))
            for index, word in enumerate(favorites):
                one = make_rounded_popup(change.addMenu(word))
                up = one.addAction("Move up", lambda word=word: self._move_favorite(word, -1))
                up.setEnabled(index > 0)
                down = one.addAction("Move down", lambda word=word: self._move_favorite(word, 1))
                down.setEnabled(index < len(favorites) - 1)
                one.addSeparator()
                one.addAction("Take out of the favorites",
                              lambda word=word: (self.library.remove_favorite(word), self._refresh_words()))
        menu.addSeparator()
        title = menu.addAction("A new favorite:")
        title.setEnabled(False)
        _field_action(menu, "", "A word, then Enter", self._on_add_favorite)
        menu.addSeparator()
        into = menu.addAction("Words go into the name field")
        into.setCheckable(True)
        into.setChecked(self._into_on)
        into.triggered.connect(self._set_into)
        menu.aboutToHide.connect(lambda: self._on_word_hovered(""))
        menu.exec(self._favorites.mapToGlobal(qt.QtCore.QPoint(0, self._favorites.height())))

    def _words_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        more = GlyphButton("", "More", size=qt.QtCore.QSize(22, 18))
        more.setObjectName("renameLock")
        more.set_icon(icons.get_icon("more", sub_folder="actions"))
        more.clicked.connect(lambda: self._on_words_more(more))
        card = self._words = FoldingCard("WORDS", icons.get_icon("book", sub_folder="actions"), extras=[more])
        self._categories = ChipBar(checkable=True, add_text="+ category", name_placeholder="Category, then Enter",
                                   custom_menu=True)
        self._words_bar = ChipBar(add_text="+ word", name_placeholder="A word, then Enter", custom_menu=True,
                                  draggable=True)
        self._words_bar.setToolTip(WORD_HINT)
        rule = qt.QtWidgets.QFrame()
        rule.setObjectName("renameRule")
        rule.setFixedHeight(1)
        recent_caption = self._recent_caption = qt.QtWidgets.QLabel("USED LAST")
        recent_caption.setObjectName("renameSubtitle")
        self._recent_words = ChipBar(custom_menu=True, draggable=True)
        self._recent_words.setToolTip("Click: into the name field · right click: more")
        hint = qt.QtWidgets.QLabel(WORD_HINT)
        hint.setObjectName("renameHint")
        hint.setWordWrap(True)
        for widget in (self._categories, rule, self._words_bar, hint, recent_caption, self._recent_words):
            card.body_layout.addWidget(widget)
        return card

    def _connect_words(self) -> None:
        self._favorites.clicked.connect(self._on_favorites_menu)
        self._words.toggled.connect(lambda opened: self._on_card_toggled("words", opened))
        self._categories.clicked.connect(self._on_category)
        self._categories.add_requested.connect(self._on_add_category)
        self._categories.menu_requested.connect(self._on_category_menu)
        self._words_bar.clicked.connect(self._on_word)
        self._words_bar.hovered.connect(self._on_word_hovered)
        self._words_bar.add_requested.connect(self._on_add_word)
        self._words_bar.menu_requested.connect(self._on_word_menu)
        self._recent_words.clicked.connect(self._use_name)
        self._recent_words.menu_requested.connect(self._on_recent_word_menu)

    def _apply_words_settings(self) -> None:
        self._into_on = bool(self._settings.get("into_field", False))
        self._show_into()
        self._refresh_words()
        self._refresh_recent_words()

    def _words_settings(self) -> dict:
        return {"into_field": self._into_on, "category": self._categories.current()}

    def _save_folded(self, key: str, opened: bool) -> None:
        folded = dict(self._settings.get("folded") or {})
        folded[key] = not opened
        self._settings["folded"] = folded

    def _into_field(self) -> bool:
        return self._into_on

    # ------------------------------------------------------------------ filling

    def _refresh_words(self) -> None:
        library = self.library
        categories = library.categories()
        wanted = self._categories.current() or self._settings.get("category", "")
        self._categories.set_chips([(name, name, f"{len(words)} words") for name, words in categories.items()])
        if wanted in categories:
            self._categories.set_current(wanted)
        current = self._categories.current()
        words = categories.get(current, [])
        favorites = set(library.favorites())
        self._words_bar.set_chips([(word, word, "★ a favorite" if word in favorites else "") for word in words])
        self._words.set_summary(f"{current} · {len(words)} words" if current else "")
        pairs = [(word, name) for name, words in categories.items() for word in words]
        pairs += [(word, "favorite") for word in library.favorites()]
        for field in (self._field, self._prefix, self._suffix, self._find_text, self._replace_text):
            field.set_words(pairs)

    def _refresh_recent_words(self) -> None:
        recent = self.library.recent()
        self._recent_words.set_chips([(text, text, "") for text in recent[:10]])
        for widget in (self._recent_caption, self._recent_words):  # (in the card already: no stray window)
            widget.setVisible(bool(recent))

    # ------------------------------------------------------------------ using a word

    def _on_word(self, word: str) -> None:
        separator = not _alt_held()
        if self._into_field():
            self._field.setText(rules.add_word(self._field.text().strip(), word, separator) if self._field.text().strip()
                                else word)
            self._field.setFocus()
            self._on_template_edited()
        else:
            self._run(self._word_operation(word, separator))

    def _on_word_hovered(self, word: str) -> None:
        if self._into_field():
            return
        self._set_hover(self._word_operation(word, not _alt_held()) if word else None)

    # ------------------------------------------------------------------ editing the library

    def _on_category(self, name: str) -> None:
        self._refresh_words()
        self._save_settings()

    def _on_add_category(self, name: str) -> None:
        if self.library.add_category(name):
            self._categories.set_current(name)
            self._refresh_words()
            self._save_settings()

    def _on_add_word(self, word: str) -> None:
        word = rules.sanitize(word)
        if self.library.add_word(self._categories.current(), word):
            self._refresh_words()

    def _on_add_favorite(self, word: str) -> None:
        if self.library.add_favorite(rules.sanitize(word)):
            self._refresh_words()

    def _on_word_menu(self, word: str, position) -> None:
        category = self._categories.current()
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        if word in self.library.favorites():
            menu.addAction("Take out of the favorites", lambda: (self.library.remove_favorite(word), self._refresh_words()))
        else:
            menu.addAction("Add to the favorites", lambda: (self.library.add_favorite(word), self._refresh_words()))
        menu.addAction("Into the name field", lambda: self._use_name(word))
        menu.addSeparator()
        rename = menu.addMenu("Rename")
        _field_action(rename, word, "New word, then Enter",
                      lambda text: (self.library.rename_word(category, word, rules.sanitize(text)), self._refresh_words()))
        move = menu.addMenu("Move to")
        for name in self.library.categories():
            if name != category:
                move.addAction(name, lambda name=name: (self.library.move_word(category, word, name), self._refresh_words()))
        menu.addAction("Remove", lambda: (self.library.remove_word(category, word), self._refresh_words()))
        menu.exec(position)

    def _move_favorite(self, word: str, steps: int) -> None:
        favorites = self.library.favorites()
        index = favorites.index(word)
        target = max(0, min(len(favorites) - 1, index + steps))
        favorites.insert(target, favorites.pop(index))
        self.library.set_favorites(favorites)
        self._refresh_words()

    def _on_category_menu(self, name: str, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        rename = menu.addMenu("Rename")
        _field_action(rename, name, "New name, then Enter", lambda text: self._rename_category(name, text))
        remove = menu.addAction("Remove…", lambda: self._remove_category(name))
        remove.setEnabled(len(self.library.categories()) > 1)
        menu.exec(position)

    def _rename_category(self, old: str, new: str) -> None:
        if self.library.rename_category(old, new):
            if self._categories.current() == old:
                self._categories.set_current(new)
                self._settings["category"] = new
            self._refresh_words()
            self._categories.set_current(new)
            self._refresh_words()

    def _remove_category(self, name: str) -> None:
        words = self.library.categories().get(name, [])
        if words:
            choice = ConfirmDialog.ask(self, "Remove a category", f"Remove “{name}” and its {len(words)} words?",
                                       choices=(("remove", "Remove"), ("cancel", "Cancel")), kind="danger")
            if choice != "remove":
                return
        self.library.remove_category(name)
        self._refresh_words()

    def _on_recent_word_menu(self, text: str, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.addAction("Into the name field", lambda: self._use_name(text))
        menu.addAction("Forget this one", lambda: (self.library.forget(text), self._refresh_recent_words()))
        menu.addAction("Forget them all", lambda: (self.library.forget(), self._refresh_recent_words()))
        menu.exec(position)

    def _on_words_more(self, button) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.addAction("Words in more than one category…", self._show_duplicate_words)
        menu.addSeparator()
        menu.addAction("Back to the built-in words…", self._reset_library)
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height())))

    def _show_duplicate_words(self) -> None:
        duplicates = self.library.duplicates()
        if not duplicates:
            self._say("Every word sits in one category only")
            return
        from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
        text = "\n".join(f"{word:<16} {', '.join(names)}" for word, names in sorted(duplicates.items()))
        TextDialog.show_for(self.window(), "Words in more than one category", text)

    def _reset_library(self) -> None:
        choice = ConfirmDialog.ask(self, "The built-in words",
                                   "Put the built-in categories, words and favorites back? Your own go away.",
                                   choices=(("reset", "Put them back"), ("cancel", "Cancel")), kind="danger")
        if choice == "reset":
            self.library.reset()
            self._refresh_words()
