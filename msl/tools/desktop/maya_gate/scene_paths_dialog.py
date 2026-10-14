# tools/desktop/maya_gate/scene_paths_dialog.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog

DEEPEST = "the most exact for each"


class ScenePathsDialog(FramelessDialog):
    """"Paths to variables" for one running Maya (the session menu): every path of its scene one of its
    variables could stand for, as a row — ticked = swapped; its variable picked from the ones whose folder
    holds it (a drop-down only where there is a choice; the deepest first), what it becomes beside it.
    "All ticked" sets one variable for every ticked row that can take it.

    It only asks: `ask()` returns {key: new path} of the ticked rows (None = cancelled), the session tab
    sends it to Maya (protocol.SCENE_PATHS_APPLY), which checks each new path is one of that path's own.

        writes = ScenePathsDialog.ask(parent, "Maya 2026 · Dev", "gift.ma", changes, notes)
    """

    WIDTH = 820
    ROW_HEIGHT = 26
    ROWS_SHOWN = 14
    WHERE, PATH, VARIABLE, BECOMES = range(4)

    def __init__(self, maya: str, scene: str, changes: list, notes: list, parent=None, referenced=()):
        """`changes`: the Maya's answer's rows {"key", "kind", "where", "path", "new", "options": [[name, new]]};
        `referenced`: [{"file", "count"}] — referenced files holding paths of their own (fixed there)."""
        self._referenced = [entry for entry in referenced if entry.get("file")]
        self._fix = []
        super().__init__(title=f"Paths to variables · {maya}", width=self.WIDTH, height=10,
                         show_minimize_button=False, show_maximize_button=False, show_theme_toggle=False,
                         parent=parent)
        self.setMinimumWidth(self.WIDTH)
        self._rows: list[dict] = []
        self._writes = None
        self._build(scene, changes, notes)

    # --- building -------------------------------------------------------------------------

    def _build(self, scene: str, changes: list, notes: list) -> None:
        head = qt.QtWidgets.QLabel(
            f"Paths of {scene} under a folder one of this Maya’s variables names. Tick the ones to swap and "
            "pick the variable for each." if changes else
            f"Nothing in {scene} itself to swap — its references hold paths of their own (below).")
        head.setObjectName("confirmMessage")
        head.setWordWrap(True)
        self.add_widget(head)
        if notes:
            note = qt.QtWidgets.QLabel("  ".join(notes))
            note.setObjectName("confirmDetails")
            note.setWordWrap(True)
            self.add_widget(note)

        self._tree = qt.QtWidgets.QTreeWidget()
        self._tree.setObjectName("scenePathsChoices")
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Where", "Path now", "Variable", "Becomes"])
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setTextElideMode(qt.QtCore.Qt.TextElideMode.ElideMiddle)
        self._tree.header().setStretchLastSection(True)
        for column, width in ((self.WHERE, 190), (self.PATH, 250), (self.VARIABLE, 120)):
            self._tree.header().resizeSection(column, width)
        names = []
        for change in changes:
            options = [(str(option[0]), str(option[1])) for option in change.get("options") or [] if len(option) == 2]
            if not options:   # a Maya with older code: only the deepest, as it found it
                new = str(change.get("new") or "")
                options = [(new[1:].split("/", 1)[0], new)] if new.startswith("$") else []
            if not options:
                continue
            names += [name for name, _new in options if name not in names]
            item = qt.QtWidgets.QTreeWidgetItem([str(change.get("where") or ""), str(change.get("path") or ""), "", ""])
            item.setFlags(item.flags() | qt.QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(self.WHERE, qt.QtCore.Qt.CheckState.Checked)
            item.setToolTip(self.WHERE, f"{change.get('where')} — {change.get('kind')}")
            item.setToolTip(self.PATH, str(change.get("path") or ""))
            self._tree.addTopLevelItem(item)
            row = {"key": str(change.get("key") or ""), "item": item, "options": options, "combo": None}
            if len(options) > 1:
                combo = BaseComboBox([f"${name}" for name, _new in options], f"${options[0][0]}", enable_wheel=False)
                combo.setToolTip("Each variable whose folder holds this path — the first is the most exact")
                combo.currentIndexChanged.connect(lambda _index, row=row: self._show_row(row))
                self._tree.setItemWidget(item, self.VARIABLE, combo)
                row["combo"] = combo
            else:
                item.setText(self.VARIABLE, f"${options[0][0]}")
            self._rows.append(row)
            self._show_row(row)
        self._tree.itemChanged.connect(self._on_item_changed)
        rows = min(max(len(self._rows), 3), self.ROWS_SHOWN)
        self._tree.setMinimumHeight(self.ROW_HEIGHT * (rows + 1) + 6)
        if self._rows:   # nothing of the scene's own: no empty table taking the room
            self.add_widget(self._tree)
        if self._referenced:
            self.add_widget(self._referenced_block())

        bottom = qt.QtWidgets.QWidget()
        bottom_layout = qt.QtWidgets.QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 10, 0, 0)
        bottom_layout.setSpacing(8)
        caption = qt.QtWidgets.QLabel("All ticked:")
        caption.setObjectName("confirmDetails")
        self._all = BaseComboBox([DEEPEST] + [f"${name}" for name in names], DEEPEST, enable_wheel=False)
        self._all.setToolTip("One variable for every ticked path that can take it")
        self._all.setVisible(len(names) > 1)
        caption.setVisible(len(names) > 1)
        self._all.currentTextChanged.connect(self._on_all)
        self._count = qt.QtWidgets.QLabel()
        self._count.setObjectName("confirmDetails")
        self._replace = qt.QtWidgets.QPushButton("Replace")
        self._replace.setProperty("primary", True)
        self._replace.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._replace.clicked.connect(self._on_replace)
        cancel = qt.QtWidgets.QPushButton("Cancel" if self._rows else "Close")
        cancel.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(caption)
        bottom_layout.addWidget(self._all)
        bottom_layout.addWidget(self._count)
        bottom_layout.addStretch(1)   # the buttons keep their size at the right, whatever is hidden
        bottom_layout.addWidget(self._replace)
        bottom_layout.addWidget(cancel)
        self.add_widget(bottom)
        self._replace.setDefault(True)
        self._replace.setFocus()
        self.content_surface.content_layout().setContentsMargins(16, 14, 16, 14)
        self.content_surface.content_layout().setSpacing(6)
        self._show_count()
        self.adjustSize()
        # adjustSize() measures wrapped labels at a narrower width than the window gets: fit the height to it
        fitted = self.heightForWidth(self.width())
        if fitted > 0:
            self.resize(self.width(), fitted)

    def _referenced_block(self) -> qt.QtWidgets.QWidget:
        """The referenced files holding paths of their own: fixed in the file (a texture of a rig), so every
        scene using it gets the fix — "Fix them in those files…" opens them in Scenes › Paths."""
        block = qt.QtWidgets.QFrame()
        block.setObjectName("scenePathsReferenced")
        layout = qt.QtWidgets.QVBoxLayout(block)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        total = sum(int(entry.get("count") or 0) for entry in self._referenced)
        title = qt.QtWidgets.QLabel(f"{total} path{'s' if total != 1 else ''} live in referenced files — they are "
                                    "fixed there, not in this scene:")
        title.setObjectName("scenePathsReferencedTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        for entry in self._referenced[:8]:
            name = str(entry["file"]).replace("\\", "/").rsplit("/", 1)[-1]
            line = qt.QtWidgets.QLabel(f"    {name}   ·   {entry.get('count')}")
            line.setObjectName("confirmDetails")
            line.setToolTip(str(entry["file"]))
            layout.addWidget(line)
        if len(self._referenced) > 8:
            more = qt.QtWidgets.QLabel(f"    … and {len(self._referenced) - 8} more files")
            more.setObjectName("confirmDetails")
            layout.addWidget(more)
        note = qt.QtWidgets.QLabel("What Maya shows for them may be where it FOUND a file; the file itself may hold "
                                   "another path (another machine’s D:/…). Scenes › Paths reads the file and looks "
                                   "for its missing files by name.")
        note.setObjectName("confirmDetails")
        note.setWordWrap(True)
        layout.addWidget(note)
        fix = qt.QtWidgets.QPushButton("Fix them in those files…")
        fix.setObjectName("scenePathsFix")
        fix.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        fix.setToolTip("Opens these files in Scenes › Paths and looks for their missing files there — nothing is "
                       "replaced in this scene now (do it afterwards if you like)")
        fix.clicked.connect(self._on_fix)
        layout.addWidget(fix, 0, qt.QtCore.Qt.AlignmentFlag.AlignLeft)
        return block

    def _on_fix(self) -> None:
        self._fix = [str(entry["file"]) for entry in self._referenced]
        self.accept()

    # --- the rows ----------------------------------------------------------------------------

    def _picked(self, row: dict) -> tuple:
        index = row["combo"].currentIndex() if row["combo"] is not None else 0
        return row["options"][max(index, 0)]

    def _ticked(self, row: dict) -> bool:
        return row["item"].checkState(self.WHERE) == qt.QtCore.Qt.CheckState.Checked

    def _show_row(self, row: dict) -> None:
        name, new = self._picked(row)
        row["item"].setText(self.BECOMES, new if self._ticked(row) else "stays as it is")
        row["item"].setToolTip(self.BECOMES, new)

    def _on_item_changed(self, item, column: int) -> None:
        if column != self.WHERE:
            return
        for row in self._rows:
            if row["item"] is item:
                self._show_row(row)
        self._show_count()

    def _on_all(self, text: str) -> None:
        name = text[1:] if text.startswith("$") else ""
        for row in self._rows:
            if row["combo"] is None or not self._ticked(row):
                continue
            names = [option[0] for option in row["options"]]
            row["combo"].setCurrentIndex(names.index(name) if name in names else 0)

    def _show_count(self) -> None:
        ticked = sum(1 for row in self._rows if self._ticked(row))
        self._count.setText(f"{ticked} of {len(self._rows)} ticked")
        self._replace.setText(f"Replace {ticked}" if ticked else "Replace")
        self._replace.setEnabled(bool(ticked))
        self._replace.setVisible(bool(self._rows))
        self._count.setVisible(bool(self._rows))

    def _on_replace(self) -> None:
        self._writes = {row["key"]: self._picked(row)[1] for row in self._rows if self._ticked(row) and row["key"]}
        self.accept()

    def writes(self):
        """{key: new path} of the ticked rows, or None when cancelled / closed."""
        return self._writes

    def fix_files(self) -> list:
        """The referenced files to fix in Scenes › Paths ("Fix them in those files…"), else []."""
        return list(self._fix)

    @classmethod
    def ask(cls, parent, maya: str, scene: str, changes: list, notes: list, referenced=()):
        """-> (writes or None, files to fix in Scenes › Paths or [])."""
        dialog = cls(maya, scene, changes, notes, parent, referenced)
        window = parent.window() if parent is not None else None
        blur = getattr(window, "set_blurred", None)
        if blur is not None:
            blur(True)
        try:
            dialog.exec()
        finally:
            if blur is not None:
                blur(False)
        answer = dialog.writes(), dialog.fix_files()
        # Gone once answered: a closed one left behind as a hidden child (with no rows) took the hub down a
        # moment later (offscreen, 2026-10-14; the exact Qt path wasn't found - deleting it ends it).
        dialog.deleteLater()
        return answer
