# tools/maya/rename/panel_words.py
"""The rename panel's words: the favorites row under the name field and the WORDS card (the name
library by category, the names used last). Methods of RenamePanel, kept apart by concern."""
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

    def _favorites_bar(self) -> qt.QtWidgets.QWidget:
        icons = UiResources().iconManager
        self._favorites = ChipBar(add_text="+", name_placeholder="A word, then Enter", custom_menu=True, draggable=True)
        self._favorites.setObjectName("renameFavorites")
        self._favorites.setToolTip(WORD_HINT)
        self._into = GlyphButton("", "Words, prefix and suffix go INTO THE NAME FIELD instead of renaming at once\n"
                                     "(build the name, then Rename)", size=qt.QtCore.QSize(22, 20))
        self._into.setObjectName("renameInto")
        self._into.set_icon(icons.get_icon("text_frame", sub_folder="actions"))
        self._into.setCheckable(True)
        row = qt.QtWidgets.QWidget()
        line = qt.QtWidgets.QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(4)
        line.addWidget(self._favorites, 1)
        line.addWidget(self._into, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        return row

    def _words_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        more = GlyphButton("", "More", size=qt.QtCore.QSize(22, 18))
        more.setObjectName("renameLock")
        more.set_icon(icons.get_icon("more", sub_folder="actions"))
        more.clicked.connect(lambda: self._on_words_more(more))
        card = self._words = FoldingCard("WORDS", icons.get_icon("bookmark", sub_folder="actions"), extras=[more])
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
        self._favorites.clicked.connect(self._on_word)
        self._favorites.hovered.connect(self._on_word_hovered)
        self._favorites.add_requested.connect(self._on_add_favorite)
        self._favorites.menu_requested.connect(self._on_favorite_menu)
        self._into.toggled.connect(self._save_settings)
        self._words.toggled.connect(lambda opened: self._save_folded("words", opened))
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
        self._into.setChecked(bool(self._settings.get("into_field", False)))
        folded = dict(self._settings.get("folded") or {})
        for key, card in (("words", self._words),):
            card.set_open(not folded.get(key, True))
        self._refresh_words()
        self._refresh_recent_words()

    def _words_settings(self) -> dict:
        return {"into_field": self._into.isChecked(), "category": self._categories.current()}

    def _save_folded(self, key: str, opened: bool) -> None:
        folded = dict(self._settings.get("folded") or {})
        folded[key] = not opened
        self._settings["folded"] = folded

    def _into_field(self) -> bool:
        return self._into.isChecked()

    # ------------------------------------------------------------------ filling

    def _refresh_words(self) -> None:
        library = self.library
        self._favorites.set_chips([(word, word, "") for word in library.favorites()])
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
        self._field.set_words(library.words())

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

    def _on_favorite_menu(self, word: str, position) -> None:
        favorites = self.library.favorites()
        index = favorites.index(word) if word in favorites else -1
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.addAction("Into the name field", lambda: self._use_name(word))
        left = menu.addAction("Move left", lambda: self._move_favorite(word, -1))
        left.setEnabled(index > 0)
        right = menu.addAction("Move right", lambda: self._move_favorite(word, 1))
        right.setEnabled(0 <= index < len(favorites) - 1)
        menu.addSeparator()
        menu.addAction("Take out of the favorites", lambda: (self.library.remove_favorite(word), self._refresh_words()))
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
