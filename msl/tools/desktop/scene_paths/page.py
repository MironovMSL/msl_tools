# tools/desktop/scene_paths/page.py
import os
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.batch import environments
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.core.scene_paths import coverage, finder, ma_paths, mb_paths
from msl_tools.msl.core.scene_paths.roots import roots_from, why_not
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.tools.desktop.maya_gate.maya_variables import KNOWN_VARIABLES
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.drop_area import DropArea
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.ui.workers.result_worker import run_in_background

StylesheetBuilder.register_template(Path(__file__).with_name("scene_paths.qss"))

PATH_ROLE = qt.QtCore.Qt.ItemDataRole.UserRole          # a scene row: its file
TONE_ROLE = qt.QtCore.Qt.ItemDataRole.UserRole + 1      # how a row is colored: change / missing / quiet / ""
KEY_ROLE = qt.QtCore.Qt.ItemDataRole.UserRole + 2       # a missing path's row: finder.key_of(its path)
STATE_TEXT = {ma_paths.CHANGE: "", ma_paths.VARIABLE: "already a variable", ma_paths.OUTSIDE: "under no variable",
              ma_paths.LEFT: "inside a script — left as it is"}


def card(title: str, icon: str) -> tuple:
    """(a card frame, the layout for its body, its heading row) — the look of the page's cards."""
    frame = qt.QtWidgets.QFrame()
    frame.setObjectName("pathsCard")
    heading = qt.QtWidgets.QHBoxLayout()
    heading.setContentsMargins(0, 0, 0, 0)
    heading.setSpacing(8)
    symbol = TintedIcon(UiResources().iconManager.get_icon(icon, sub_folder="actions"), 16)
    symbol.setObjectName("pathsCardIcon")
    label = qt.QtWidgets.QLabel(title.upper())
    label.setObjectName("pathsCardTitle")
    heading.addWidget(symbol)
    heading.addWidget(label, 1)
    layout = qt.QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(12, 9, 12, 10)
    layout.setSpacing(8)
    layout.addLayout(heading)
    return frame, layout, heading


class ScenePathsPage(qt.QtWidgets.QWidget):
    """Paths — absolute paths inside Maya ASCII scenes swapped for Maya Gate's variables
    ("E:/branches/Animation/..." -> "$WG_ANIM/..."), for many scenes at once and without Maya.

    - VARIABLES: a Maya Gate environment, and which of its folder variables stand in for their
      folder (core/scene_paths/roots.py says which can). Maya's own catalog variables start off,
      the user's own (custom) on; the choice is kept per environment.
    - SCENES: files and folders dropped (or chosen) are read on a worker (core/scene_paths/
      ma_paths.py) — a row per scene, "3 to change · 1 file missing", unfolded: each path, what it
      becomes, and what it is (reference, texture, a reference's edit...).
    - the bottom bar: a copy of each scene first (.bak beside it), then "Replace in N scenes".

    Nothing is written before that click, and then only the folder at a path's start: the rest
    of each scene stays byte for byte. A scene changed since it was read, a read-only one and one
    open in a Maya connected to the hub are refused (that Maya would save its own paths over ours).
    Binary scenes (.mb) are read and written by a mayapy (core/scene_paths/mb_paths.py,
    tools/maya/scene_paths_runner.py): read once, then only re-sorted when the roots change;
    saved only by the Maya version they were saved with.
    """

    TOOL_NAME = "scene_paths"    # its config (configs/desktop/scene_paths)
    MESSAGE_MS = 12000

    # For the Scenes tool around it (tools/desktop/scenes): these scenes wanted in the Render tab.
    render_requested = qt.QtCore.Signal(list)

    changeColor = color_property("_change_color", "_recolor")
    missingColor = color_property("_missing_color", "_recolor")
    quietColor = color_property("_quiet_color", "_recolor")

    def __init__(self, parent=None, embedded: bool = False):
        super().__init__(parent)
        self._embedded = embedded   # a tab of Scenes: no heading of its own (the tool has one)
        fallback = ThemeRegistry.fallback()
        self._change_color = qt.QtGui.QColor(fallback.accent)
        self._missing_color = qt.QtGui.QColor(fallback.warning)
        self._quiet_color = qt.QtGui.QColor(fallback.text_secondary)
        resources = Resources()
        self._config = resources.configsDesktopHubMng.get_config(self.TOOL_NAME, defaults={"settings": {}})
        self._settings = self._config["settings"]
        self._gate_config = resources.configsDesktopHubMng.base_dir / "maya_gate" / "config.json"
        self._scenes: list[Path] = []
        self._scans: dict[str, ma_paths.SceneScan] = {}
        self._mb_raw: dict[str, dict] = {}     # what mayapy found in each binary scene (kept: roots only re-sort it)
        self._mb_reading: set[str] = set()     # binary scenes a mayapy is reading now
        self._found: dict[str, list] = {}      # a missing path (finder.key_of) -> files of its name, best first
        self._picked: dict[str, str] = {}      # the user's pick for one ("" = don't relink it)
        self._searching = False
        self._coverage: dict = {}            # variable -> coverage.Coverage (where it is set)
        self._coverage_names: list = []
        self._workers: list = []
        self._reading = 0          # the newest read; an older one that finishes later is dropped
        self._busy = False
        self.setAcceptDrops(True)
        self._build()
        self._connect()
        self._fill_environments()

    # --- construction ---------------------------------------------------------------------------

    def _build(self) -> None:
        icons = UiResources().iconManager
        title_icon = TintedIcon(icons.get_icon("paths", sub_folder="tools"), 16)
        title_icon.setObjectName("pathsCardIcon")
        title = qt.QtWidgets.QLabel("PATHS")
        title.setObjectName("pathsCardTitle")
        subtitle = qt.QtWidgets.QLabel("Absolute paths in Maya scenes → Maya Gate’s variables")
        subtitle.setObjectName("pathsSubtitle")
        header = qt.QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(title_icon)
        header.addWidget(title)
        header.addWidget(subtitle, 1)

        # VARIABLES
        variables_card, variables_layout, _heading = card("Variables", "sliders")
        caption = qt.QtWidgets.QLabel("Environment")
        caption.setObjectName("pathsCaption")
        self._environment = BaseComboBox([], "", enable_wheel=False)
        self._environment.setMinimumWidth(130)
        row = qt.QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(caption)
        row.addWidget(self._environment)
        row.addStretch(1)
        self._roots = ChipBar(multiple=True)
        self._roots_hint = qt.QtWidgets.QLabel()
        self._roots_hint.setObjectName("pathsHint")
        self._roots_hint.setWordWrap(True)
        variables_layout.addLayout(row)
        variables_layout.addWidget(self._roots)
        variables_layout.addWidget(self._roots_hint)
        # Where the variables are set (coverage.py): a scene written with $WG_ANIM opened by a Maya
        # that doesn't have it finds none of its files.
        self._coverage_line = qt.QtWidgets.QLabel()
        self._coverage_line.setObjectName("pathsCoverage")
        self._coverage_line.setWordWrap(True)
        self._coverage_details = self._link("Where it is set")
        coverage_row = qt.QtWidgets.QHBoxLayout()
        coverage_row.setSpacing(6)
        coverage_row.addWidget(self._coverage_line, 1)
        coverage_row.addWidget(self._coverage_details, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        variables_layout.addLayout(coverage_row)
        self._coverage_line.hide()
        self._coverage_details.hide()

        # SCENES
        self._scenes_card, scenes_layout, scenes_heading = card("Files", "scene")   # "Scenes" is the tool's own name
        self._scenes_title = scenes_heading.itemAt(1).widget()
        self._show_all = BaseCheckbox("Every path")
        self._show_all.setToolTip("Also the paths that stay: already a variable, under no variable, in a script")
        self._show_all.setChecked(bool(self._settings.get("show_all", False)))
        self._add_files = self._link("+ Scenes")
        self._add_folder = self._link("+ Folder")
        self._clear = self._link("Clear")
        self._find = self._link("Find missing ▾")
        self._find.setToolTip("Missing files looked for by their name — in the ticked variables’ folders\n"
                              "and in folders you add; a found file is written through the variable")
        for widget in (self._show_all, self._find, self._add_files, self._add_folder, self._clear):
            scenes_heading.addWidget(widget)
        self._tree = qt.QtWidgets.QTreeWidget()
        self._tree.setObjectName("pathsTree")
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Scene / path", "Becomes", "What it is"])
        self._tree.setUniformRowHeights(True)
        self._tree.setTextElideMode(qt.QtCore.Qt.TextElideMode.ElideMiddle)   # the file's name stays readable
        self._tree.setAlternatingRowColors(False)
        self._tree.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.header().setStretchLastSection(True)
        self._tree.header().setSectionResizeMode(0, qt.QtWidgets.QHeaderView.ResizeMode.Interactive)
        self._tree.header().resizeSection(0, 330)
        self._tree.header().resizeSection(1, 260)
        self._drop = DropArea(icons.get_icon("paths", sub_folder="tools"), "Drop Maya scenes or folders here",
                              ".ma are read as text, .mb by a Maya without a window; folders are searched all the way down")
        self._drop_files = self._drop.add_button(icons.get_icon("file_add", sub_folder="actions"), "Choose scenes", "+")
        self._drop_folder = self._drop.add_button(icons.get_icon("browse", sub_folder="actions"), "Choose a folder", "…")
        scenes_layout.addWidget(self._tree, 1)
        scenes_layout.addWidget(self._drop, 1)

        self._message = qt.QtWidgets.QLabel()
        self._message.setObjectName("pathsMessage")
        self._message.setWordWrap(True)
        self._message.hide()
        self._message_timer = qt.QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.setInterval(self.MESSAGE_MS)
        self._message_timer.timeout.connect(self._message.hide)

        # the bottom bar
        bottom = qt.QtWidgets.QFrame()
        bottom.setObjectName("pathsCard")
        self._summary = qt.QtWidgets.QLabel()
        self._summary.setObjectName("pathsSummary")
        self._backup = BaseCheckbox("Keep a copy (.bak)")
        self._backup.setToolTip("Before a scene is written, its old file is copied beside it as\n"
                                "<scene>.ma.<date-time>.bak — Maya’s file dialog doesn’t list it")
        self._backup.setChecked(bool(self._settings.get("backup", True)))
        self._reread = qt.QtWidgets.QPushButton("Read again")
        self._reread.setIcon(icons.get_icon("restart", sub_folder="actions"))
        self._apply = qt.QtWidgets.QPushButton("Replace")
        self._apply.setProperty("primary", True)
        self._apply.setMinimumWidth(120)
        bottom_layout = qt.QtWidgets.QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 7, 10, 7)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(self._summary, 1)
        bottom_layout.addWidget(self._backup)
        bottom_layout.addWidget(self._reread)
        bottom_layout.addWidget(self._apply)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*((0, 8, 0, 0) if self._embedded else (16, 10, 12, 10)))
        layout.setSpacing(10)
        if not self._embedded:   # embedded: the heading's widgets are never put anywhere, so never shown
            layout.addLayout(header)
        layout.addWidget(variables_card)
        layout.addWidget(self._message)
        layout.addWidget(self._scenes_card, 1)
        layout.addWidget(bottom)
        self._show()

    def _link(self, text: str) -> qt.QtWidgets.QPushButton:
        button = qt.QtWidgets.QPushButton(text)
        button.setObjectName("pathsLink")
        button.setFlat(True)
        button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        return button

    def _connect(self) -> None:
        self._environment.currentTextChanged.connect(self._on_environment)
        self._roots.clicked.connect(self._on_root_clicked)
        self._add_files.clicked.connect(self._on_choose_files)
        self._drop_files.clicked.connect(self._on_choose_files)
        self._add_folder.clicked.connect(self._on_choose_folder)
        self._drop_folder.clicked.connect(self._on_choose_folder)
        self._clear.clicked.connect(self._on_clear)
        self._find.clicked.connect(self._on_find_menu)
        self._coverage_details.clicked.connect(self._on_coverage_details)
        self._show_all.toggled.connect(self._on_show_all)
        self._backup.toggled.connect(lambda checked: self._settings.__setitem__("backup", bool(checked)))
        self._reread.clicked.connect(lambda: self._read(again=True))
        self._apply.clicked.connect(self._on_apply)
        self._tree.customContextMenuRequested.connect(self._on_tree_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)

    # --- variables --------------------------------------------------------------------------------

    def _fill_environments(self) -> None:
        names = environments.names(self._gate_config)
        wanted = str(self._settings.get("environment") or "Dev")
        self._environment.blockSignals(True)
        self._environment.clear()
        self._environment.addItems(names)
        self._environment.setCurrentText(wanted if wanted in names else names[0])
        self._environment.blockSignals(False)
        self._fill_roots()

    def _variables(self) -> dict:
        return environments.variables(self._gate_config, self._environment.currentText(), base={})

    def _fill_roots(self) -> None:
        """The chips: every folder variable of the environment; the switched-off ones unticked."""
        variables = self._variables()
        candidates = roots_from(variables)
        off = set(self._off_names())
        self._roots.set_chips([(root.name, root.name, f"${root.name}  =  {root.value}") for root in candidates])
        self._roots.set_checked([root.name for root in candidates if root.name not in off])
        self._roots.setVisible(bool(candidates))
        environment = self._environment.currentText()
        if not candidates:
            skipped = [f"{name} ({why_not(name, value)})" for name, value in variables.items() if why_not(name, value)]
            text = (f"{environment} has no variable that names one folder. Add one in Maya Gate → Variables "
                    f"(Custom Variables · {environment}), e.g. WG_ANIM = E:/branches/Animation.")
            if skipped:
                text += "  Not usable here: " + ", ".join(skipped[:6]) + ("…" if len(skipped) > 6 else "")
        else:
            ticked = [root for root in candidates if root.name not in off]
            text = ("   ".join(f"${root.name} = {root.value}" for root in ticked) + "  —  a path that starts with "
                    "that folder gets the variable in its place." if ticked
                    else "Tick a variable: a path that starts with its folder gets the variable in its place.")
        self._roots_hint.setText(text)
        if hasattr(self, "_coverage_line"):
            self._refresh_coverage(force=True)

    def _off_names(self) -> list:
        """The environment's variables switched off here; Maya's own catalog variables are off until ticked."""
        stored = (self._settings.get("off") or {}).get(self._environment.currentText())
        if stored is None:
            return [name for name in self._variables() if name in KNOWN_VARIABLES]
        return list(stored)

    def roots(self) -> list:
        """The roots in use now: the ticked variables, deepest folder first."""
        ticked = set(self._roots.checked())
        return [root for root in roots_from(self._variables()) if root.name in ticked]

    def _on_environment(self, name: str) -> None:
        self._settings["environment"] = name
        self._fill_roots()
        self._read()

    def _on_root_clicked(self, _key: str) -> None:
        ticked = set(self._roots.checked())
        off = self._settings.get("off") or {}
        off[self._environment.currentText()] = [name for name in self._variables() if name not in ticked]
        self._settings["off"] = off
        self._fill_roots()
        self._read()

    # --- scenes -------------------------------------------------------------------------------------

    def add(self, paths) -> None:
        """Scenes and folders to look at (a folder: every scene under it). Repeats are dropped."""
        scenes, cut = ma_paths.collect_scenes(paths)
        known = {os.path.normcase(str(scene)) for scene in self._scenes}
        fresh = [scene for scene in scenes if os.path.normcase(str(scene)) not in known]
        if not fresh:
            self._say("No new Maya scenes there (.ma / .mb; incrementalSave folders are left out).",
                      "error" if not scenes else "")
            return
        self._scenes.extend(fresh)
        if cut:
            self._say(f"Only the first {ma_paths.COLLECT_AT_MOST} scenes are taken — drop a smaller folder.", "error")
        self._read()

    def open(self, paths) -> None:
        """Scenes handed to the page from outside (the hub, a test)."""
        self.add(paths)

    def _read(self, again: bool = False) -> None:
        """Reads the scenes (on a worker) with the roots in use now: .ma as text; .mb from what a mayapy
        found in them (kept — only a new scene, `again` or a write makes Maya read one again)."""
        if again:
            self._mb_raw.clear()
        if not self._scenes:
            self._scans.clear()
            self._show()
            return
        self._reading += 1
        token = self._reading
        scenes, roots, environment = list(self._scenes), self.roots(), self._variables()
        raw = dict(self._mb_raw)
        self._summary.setText(f"Reading {len(scenes)} scene{'s' if len(scenes) != 1 else ''}…")
        self._set_busy(True)

        def read() -> dict:
            cache: dict = {}
            found = {}
            for scene in scenes:
                if scene.suffix.lower() == ma_paths.BINARY_SUFFIX:
                    if str(scene) in raw:
                        found[str(scene)] = mb_paths.scan_from_raw(scene, raw[str(scene)], roots, environment, cache)
                else:
                    found[str(scene)] = ma_paths.scan(scene, roots, environment=environment, exists_cache=cache)
            return found

        run_in_background(read, lambda result: self._on_read(token, result),
                          lambda error: self._on_failed(token, error), keep=self._workers, parent=self)

    def _on_read(self, token: int, result: dict) -> None:
        if token != self._reading:
            return
        self._scans = result
        self._set_busy(False)
        self._show()
        self._read_binary()

    def _read_binary(self) -> None:
        """Binary scenes nobody has read yet go to a mayapy (one per Maya version, ~15 s and more each)."""
        need = [scene for scene in self._scenes if scene.suffix.lower() == ma_paths.BINARY_SUFFIX
                and str(scene) not in self._mb_raw and str(scene) not in self._mb_reading]
        if not need:
            return
        self._mb_reading.update(str(scene) for scene in need)
        environment = mb_paths.environment_for(self._variables())
        self._show()

        def read() -> dict:
            return mb_paths.read_raw(need, MayaPaths.get_available_installs(), environment)

        def failed(error) -> None:
            self._on_binary_read({str(scene): {"maya": "", "data": {"error": f"reading failed: {error}"}}
                                  for scene in need})

        run_in_background(read, self._on_binary_read, failed, keep=self._workers, parent=self)

    def _on_binary_read(self, raw: dict) -> None:
        self._mb_reading.difference_update(raw)
        self._mb_raw.update(raw)
        roots, environment, cache = self.roots(), self._variables(), {}
        wanted = {str(scene) for scene in self._scenes}
        for path, found in raw.items():
            if path in wanted:   # (a scene left out meanwhile stays out)
                self._scans[path] = mb_paths.scan_from_raw(path, found, roots, environment, cache)
        self._show()

    def _on_failed(self, token: int, error) -> None:
        if token == self._reading:
            self._set_busy(False)
            self._say(f"Reading failed: {error}", "error")
            self._show()

    def _on_clear(self) -> None:
        self._scenes.clear()
        self._scans.clear()
        self._reading += 1
        self._show()

    def _remove(self, path: str) -> None:
        self._scenes = [scene for scene in self._scenes if str(scene) != path]
        self._scans.pop(path, None)
        self._show()

    # --- the list -------------------------------------------------------------------------------------

    def _show(self) -> None:
        """Rebuilds the tree from the scans; scenes open before stay open."""
        empty = not self._scenes
        self._tree.setVisible(not empty)
        self._drop.setVisible(empty)
        self._clear.setVisible(not empty)
        self._show_all.setVisible(not empty)
        self._find.setVisible(not empty)
        opened = {self._tree.topLevelItem(index).data(0, PATH_ROLE)
                  for index in range(self._tree.topLevelItemCount()) if self._tree.topLevelItem(index).isExpanded()}
        self._tree.clear()
        everything = self._show_all.isChecked()
        roots = self.roots()
        scenes_to_write = changes = relinks = missing = 0
        for scene in self._scenes:
            result = self._scans.get(str(scene))
            item = qt.QtWidgets.QTreeWidgetItem([scene.name])
            item.setData(0, PATH_ROLE, str(scene))
            item.setToolTip(0, str(scene))
            if result is None:
                binary = str(scene) in self._mb_reading
                item.setText(2, "reading it in Maya…" if binary else "reading…")
                item.setToolTip(2, "A binary scene (.mb) can’t be read as text: a Maya without a window opens it"
                                if binary else "")
                item.setData(0, TONE_ROLE, "quiet")
            elif result.error:
                item.setText(2, result.error)
                item.setData(0, TONE_ROLE, "missing")
            else:
                self._relink(result, roots)
                count, found = len(result.changes), len(result.relinks)
                lost = len(result.missing) - found
                scenes_to_write += bool(count or found)
                changes += count
                relinks += found
                missing += lost
                said = [f"{count} to change"] if count else []
                if found:
                    said.append(f"{found} found again")
                item.setText(1, "  ·  ".join(said) or "nothing to change")
                parts = [f"{len(result.uses)} path{'s' if len(result.uses) != 1 else ''}"]
                if result.binary:
                    parts.insert(0, f".mb · Maya {result.maya}")
                if result.via_variable:
                    parts.append(f"{len(result.via_variable)} through a variable")
                if lost:
                    parts.append(f"{lost} file{'s' if lost != 1 else ''} missing")
                item.setText(2, "  ·  ".join(parts))
                item.setData(0, TONE_ROLE, "change" if count or found else "quiet")
                lost_ids = {id(use) for use in result.missing}
                for use in result.uses:
                    if everything or use.state == ma_paths.CHANGE or id(use) in lost_ids:
                        item.addChild(self._use_item(use, id(use) in lost_ids))
            self._tree.addTopLevelItem(item)
            item.setExpanded(str(scene) in opened)
        self._recolor()
        self._find.setEnabled(bool(missing or relinks) and not self._searching)
        self._refresh_coverage()
        total = len(self._scenes)
        self._scenes_title.setText(f"FILES  ·  {total}" if total else "FILES")
        self._apply.setText(f"Replace in {scenes_to_write}" if scenes_to_write else "Replace")
        self._apply.setEnabled(bool(scenes_to_write) and not self._busy)
        if self._busy:
            return
        reading = len(self._mb_reading)
        if reading:
            self._summary.setText(f"Reading {reading} binary scene{'s' if reading != 1 else ''} in Maya — "
                                  "that takes a while…")
            return
        if self._searching:
            self._summary.setText("Looking for the missing files…")
            return
        parts = []
        if changes:
            parts.append(f"{changes} path{'s' if changes != 1 else ''} to change")
        if relinks:
            parts.append(f"{relinks} missing file{'s' if relinks != 1 else ''} found again")
        if parts:
            parts[-1] += f" in {scenes_to_write} scene{'s' if scenes_to_write != 1 else ''}"
        elif total:
            parts.append("Nothing to change")
        if missing:
            parts.append(f"{missing} file{'s' if missing != 1 else ''} missing")
        self._summary.setText("  ·  ".join(parts))

    def _relink(self, result, roots) -> None:
        """Gives each missing file of `result` what the finder found for it: the user's pick, else the
        one candidate ahead of the rest (written through a root). History entries of a reference
        (its old file names) are not relinked: nothing loads them."""
        for use in result.missing:
            use.relink, use.found = "", []
            if use.kind == ma_paths.REFERENCE_HISTORY or use.state == ma_paths.LEFT:
                continue
            key = finder.key_of(use.path)
            use.found = list(self._found.get(key) or [])
            chosen = self._picked.get(key)
            if chosen is None:
                chosen = finder.best(use.path, use.found)
            use.relink = finder.through_root(chosen, roots) if chosen else ""

    def _use_item(self, use, missing: bool) -> qt.QtWidgets.QTreeWidgetItem:
        """A path's row; `missing`: a file the scene needs isn't there (not said of a script's path)."""
        what = use.kind + (f"  ·  {use.where}" if use.where else "") + (f"  ·  line {use.line}" if use.line else "")
        note = (use.note if use.state == ma_paths.LEFT and use.note else STATE_TEXT.get(use.state, ""))
        if missing and not use.relink:
            note = ("file missing" + (f", {note}" if note else ""))
            if use.found:
                note = f"missing · {len(use.found)} found — right click to pick"
        child = qt.QtWidgets.QTreeWidgetItem([use.path, use.new_path or note, what])
        child.setData(0, KEY_ROLE, finder.key_of(use.path) if missing else "")
        tip = f"{use.path}\n→ {use.new_path}" if use.new_path else use.path
        if missing:
            tip += "\n\nThis file isn’t there."
            if use.relink:
                tip += "  Found again — it becomes the path above."
            if use.found:
                tip += "\n\nFiles of that name:\n" + "\n".join(use.found[:8]) + (
                    f"\n… and {len(use.found) - 8} more" if len(use.found) > 8 else "")
        child.setToolTip(0, tip)
        child.setToolTip(1, tip)
        child.setToolTip(2, what)
        child.setData(0, TONE_ROLE, "change" if use.relink or (use.state == ma_paths.CHANGE and not missing)
                      else "missing" if missing else "quiet")
        return child

    def _recolor(self) -> None:
        """Rows take their colors from QSS (qproperty changeColor / missingColor / quietColor)."""
        colors = {"change": self._change_color, "missing": self._missing_color, "quiet": self._quiet_color}
        tree = getattr(self, "_tree", None)
        if tree is None:
            return
        for index in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(index)
            self._paint(top, colors, columns=(1, 2))
            for child_index in range(top.childCount()):
                self._paint(top.child(child_index), colors, columns=(1,))

    @staticmethod
    def _paint(item, colors: dict, columns) -> None:
        color = colors.get(item.data(0, TONE_ROLE) or "")
        for column in columns:
            if color is None:
                item.setData(column, qt.QtCore.Qt.ItemDataRole.ForegroundRole, None)
            else:
                item.setForeground(column, qt.QtGui.QBrush(color))

    def _on_show_all(self, checked: bool) -> None:
        self._settings["show_all"] = bool(checked)
        self._show()

    def _on_double_click(self, item, _column: int) -> None:
        if item.parent() is None and item.childCount() == 0 and item.data(0, PATH_ROLE):
            self._say("Nothing listed under it: tick “Every path” to see the paths that stay.")

    def _on_tree_menu(self, position) -> None:
        item = self._tree.itemAt(position)
        if item is None:
            return
        scene_item = item if item.parent() is None else item.parent()
        path = scene_item.data(0, PATH_ROLE)
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if item.parent() is not None:
            key = item.data(0, KEY_ROLE) or ""
            if key and self._found.get(key):
                self._add_pick_items(menu, key)
            text = item.text(0)
            menu.addAction("Copy the path").triggered.connect(
                lambda: qt.QtWidgets.QApplication.clipboard().setText(text))
            if item.text(1).startswith("$"):
                new = item.text(1)
                menu.addAction("Copy the new path").triggered.connect(
                    lambda: qt.QtWidgets.QApplication.clipboard().setText(new))
            menu.addSeparator()
        menu.addAction("Show the scene").triggered.connect(lambda: ProcessLauncher.open_file_explorer(Path(path)))
        if self._embedded:
            menu.addAction("Render it (Render tab)").triggered.connect(lambda: self.render_requested.emit([path]))
        menu.addAction("Leave this scene out").triggered.connect(lambda: self._remove(path))
        self._tree_menu = menu   # for tests; deletes itself on close
        menu.popup(self._tree.viewport().mapToGlobal(position))



    # --- where the variables are set ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_coverage(force=True)   # Maya Gate / a Maya.env may have changed meanwhile

    def _dependencies(self) -> list:
        """The variables the listed scenes depend on, or will after a write: the ticked roots and
        every $NAME a path already starts with."""
        names = {root.name for root in self.roots()}
        for result in self._scans.values():
            if not result.error:
                names.update(use.variable for use in result.via_variable if use.variable)
        return sorted(names)

    def _refresh_coverage(self, force: bool = False) -> None:
        names = self._dependencies()
        if not force and names == self._coverage_names:
            return
        self._coverage_names = names
        try:
            installs = MayaPaths.get_available_installs()
            self._coverage = coverage.coverage(names, self._gate_config, list(installs),
                                               MayaPaths.get_preferences_root()) if names else {}
        except Exception as error:   # a warning that can't be worked out must not break the page
            self._coverage = {}
            self._coverage_line.setText(f"Couldn’t check where the variables are set: {error}")
            self._coverage_line.show()
            return
        self._show_coverage()

    def _gaps(self) -> dict:
        return {name: found.gaps() for name, found in self._coverage.items() if found.gaps()}

    def _show_coverage(self) -> None:
        gaps = self._gaps()
        if not self._coverage:
            self._coverage_line.hide()
            self._coverage_details.hide()
            return
        if gaps:
            lines = [f"⚠ ${name} isn’t set for {', '.join(places)} — scenes written with it open there "
                     f"without their files." for name, places in gaps.items()]
            state = "warning"
        else:
            names = ", ".join(f"${name}" for name in self._coverage)
            lines = [f"✓ {names}: set for every Maya on this machine. Another machine or a render farm "
                     f"needs {'it' if len(self._coverage) == 1 else 'them'} too."]
            state = "ok"
        problems = [problem for found in self._coverage.values() for problem in found.problems]
        if problems:   # Maya.env lines meant for a variable that don't set it ("$WG_anim = …;")
            lines += [f"✗ {problem}" for problem in problems]
            state = "warning"
        self._coverage_line.setText("\n".join(lines))
        self._coverage_line.setToolTip("\n\n".join(found.describe() for found in self._coverage.values()))
        if self._coverage_line.property("state") != state:
            self._coverage_line.setProperty("state", state)
            repolish(self._coverage_line)
        self._coverage_line.show()
        self._coverage_details.show()

    def _on_coverage_details(self) -> None:
        text = "\n\n".join(found.describe() for found in self._coverage.values())
        gaps = self._gaps()
        if gaps:
            text += "\n\nA Maya starts WITHOUT them here:\n" + "\n".join(
                f"  ${name}: {place}" for name, places in gaps.items() for place in places)
        text += ("\n\nHow to set one for everything on this machine: Windows → “Edit environment variables for "
                 "your account”, or a line NAME = value in Documents/maya/<version>/Maya.env (Maya reads only "
                 "the file in its version’s folder; a variable Maya Gate sets wins over it). Another machine or "
                 "a render farm needs it as well — that can’t be checked from here.")
        TextDialog.show_for(self, "Where the variables are set", text)

    # --- finding missing files --------------------------------------------------------------------------

    def _search_folders(self) -> list:
        return [root.value for root in self.roots()] + [str(folder) for folder in self._settings.get("search_in") or []]

    def _on_find_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        folders = self._search_folders()
        where = ", ".join(f"${root.name}" for root in self.roots()) or "no variable ticked"
        extra = list(self._settings.get("search_in") or [])
        find = menu.addAction(f"Find them — in {where}" + (f" + {len(extra)} folder{'s' if len(extra) != 1 else ''}"
                                                          if extra else ""))
        find.setEnabled(bool(folders))
        find.triggered.connect(self._find_missing)
        menu.addAction("Also look in a folder…").triggered.connect(self._on_add_search_folder)
        if extra:
            menu.addSeparator()
            for folder in extra:
                menu.addAction(f"Stop looking in {folder}").triggered.connect(
                    lambda _checked=False, folder=folder: self._remove_search_folder(folder))
        if self._picked:
            menu.addSeparator()
            menu.addAction("Forget my picks").triggered.connect(self._forget_picks)
        self._find_menu = menu   # for tests; deletes itself on close
        menu.popup(self._find.mapToGlobal(qt.QtCore.QPoint(0, self._find.height())))

    def _on_add_search_folder(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "Also look for missing files in",
                                                               str(self._settings.get("last_folder", "") or ""))
        if folder:
            extra = [each for each in self._settings.get("search_in") or [] if each != folder]
            self._settings["search_in"] = extra + [folder]
            self._find_missing()

    def _remove_search_folder(self, folder: str) -> None:
        self._settings["search_in"] = [each for each in self._settings.get("search_in") or [] if each != folder]

    def _forget_picks(self) -> None:
        self._picked.clear()
        self._show()

    def _find_missing(self) -> None:
        """Walks the search folders once (a worker) and looks every missing file up by its name."""
        folders = self._search_folders()
        missing = {finder.key_of(use.path): use.path for result in self._scans.values() if not result.error
                   for use in result.missing if use.kind != ma_paths.REFERENCE_HISTORY}
        if not folders or not missing:
            return
        self._searching = True
        self._show()

        def search() -> tuple:
            index = finder.build_index(folders)
            return index, {key: finder.candidates(path, index) for key, path in missing.items()}

        run_in_background(search, self._on_found, self._on_find_failed, keep=self._workers, parent=self)

    def _on_found(self, answer: tuple) -> None:
        index, found = answer
        self._searching = False
        self._found.update(found)
        self._show()
        relinked = sum(len(result.relinks) for result in self._scans.values() if not result.error)
        unfound = sum(1 for files in found.values() if not files)
        ties = sum(1 for key, files in found.items()
                   if len(files) > 1 and not finder.best(key, files) and key not in self._picked)
        text = f"Looked through {index.count:,} files: {relinked} missing path{'s' if relinked != 1 else ''} found again"
        if unfound:
            text += f", {unfound} file{'s' if unfound != 1 else ''} not found anywhere"
        if ties:
            text += f", {ties} with several files of that name — right click its row to pick one"
        if index.cut:
            text += f" (stopped at {finder.INDEX_AT_MOST:,} files — look in a smaller folder)"
        self._say(text + ".", "error" if index.cut else "")

    def _on_find_failed(self, error) -> None:
        self._searching = False
        self._say(f"Looking for the missing files failed: {error}", "error")
        self._show()

    def _add_pick_items(self, menu, key: str) -> None:
        """A missing file's candidates as items of the row's menu: a click picks one."""
        files = self._found.get(key) or []
        current = self._picked.get(key)
        if current is None:
            current = finder.best(key, files)
        title = menu.addAction("USE THE FILE")
        title.setEnabled(False)
        for file in files[:12]:
            action = menu.addAction(file)
            action.setCheckable(True)
            action.setChecked(file == current)
            action.triggered.connect(lambda _checked=False, file=file: self._pick(key, file))
        if len(files) > 12:
            menu.addAction(f"… {len(files) - 12} more").setEnabled(False)
        none = menu.addAction("Leave it missing")
        none.setCheckable(True)
        none.setChecked(current == "")
        none.triggered.connect(lambda: self._pick(key, ""))
        menu.addSeparator()

    def _pick(self, key: str, file: str) -> None:
        self._picked[key] = file
        self._show()

    # --- writing --------------------------------------------------------------------------------------

    def _open_in_maya(self) -> dict:
        """Scenes open in a Maya connected to the hub: normcase(path) -> "Maya 2024"."""
        try:
            from msl_tools.msl.ui.maya_link.server import MayaLinkServer
            sessions = MayaLinkServer.instance().sessions()
        except Exception:
            return {}
        return {os.path.normcase(os.path.normpath(session.scene)): f"Maya {session.version}"
                for session in sessions if session.scene}

    def _on_apply(self) -> None:
        open_now = self._open_in_maya()
        targets, held = [], []
        for scene in self._scenes:
            result = self._scans.get(str(scene))
            if result is None or result.error or not result.writes:
                continue
            maya = open_now.get(os.path.normcase(os.path.normpath(str(scene))))
            (held if maya else targets).append((result, maya))
        if not targets:
            self._say("Every scene with paths to change is open in Maya — close it there first.", "error")
            return
        count = sum(len(result.writes) for result, _maya in targets)
        roots = ", ".join(f"${root.name}" for root in self.roots())
        details = "\n".join(str(result.path) for result, _maya in targets[:12])
        if len(targets) > 12:
            details += f"\n… and {len(targets) - 12} more"
        if held:
            details += "\n\nLeft out — open in Maya (it would save its own paths over these):\n" + "\n".join(
                f"{result.path.name} ({maya})" for result, maya in held)
        backup = self._backup.isChecked()
        binary = [result for result, _maya in targets if result.binary]
        found = sum(len(result.relinks) for result, _maya in targets)
        what = [f"{count - found} get {roots}"] if count - found else []
        if found:
            what.append(f"{found} missing file{'s' if found != 1 else ''} found again")
        message = (f"{count} path{'s' if count != 1 else ''} in {len(targets)} scene{'s' if len(targets) != 1 else ''} "
                   f"are written ({', '.join(what)}). "
                   + ("A copy of each scene is kept beside it (.bak)." if backup
                      else "No copy is kept — this can’t be undone."))
        if binary:
            years = ", ".join(sorted({result.maya for result in binary}))
            message += (f"  {len(binary)} binary scene{'s are' if len(binary) != 1 else ' is'} opened and saved "
                        f"by Maya {years} without a window — that takes a while.")
        gaps = {name: places for name, places in self._gaps().items() if name in {root.name for root in self.roots()}}
        if gaps:
            message += "  " + " ".join(f"${name} isn’t set for {', '.join(places)}: these scenes open there "
                                       f"without their files." for name, places in gaps.items())
        choice = ConfirmDialog.ask(self, "Replace paths", message, details,
                                   (("replace", "Replace"), ("cancel", "Cancel")),
                                   kind="question" if backup and not gaps else "warning")
        if choice != "replace":
            return
        scans = [result for result, _maya in targets]
        self._set_busy(True)
        self._summary.setText(f"Writing {len(scans)} scene{'s' if len(scans) != 1 else ''}…")

        roots_now = self.roots()
        environment = mb_paths.environment_for(self._variables())

        def write() -> list:
            outcome = []
            for result in scans:
                if result.binary:
                    continue
                try:
                    outcome.append((result.path, ma_paths.apply(result, backup=backup), ""))
                except ma_paths.ScenePathsError as error:
                    outcome.append((result.path, None, str(error)))
            binary_scans = [result for result in scans if result.binary]
            if binary_scans:   # each in the Maya it was saved with (mb_paths.maya_to_write)
                outcome += mb_paths.apply_binary(binary_scans, roots_now, MayaPaths.get_available_installs(),
                                                 environment, backup=backup)
            return outcome

        run_in_background(write, lambda outcome: self._on_written(outcome, held), self._on_write_failed,
                          keep=self._workers, parent=self)

    def _on_written(self, outcome: list, held: list) -> None:
        self._set_busy(False)
        written = [done for _path, done, error in outcome if done is not None and done.changed]
        failed = [error for _path, _done, error in outcome if error]
        paths = sum(done.changed for done in written)
        text = f"Done: {paths} path{'s' if paths != 1 else ''} in {len(written)} scene{'s' if len(written) != 1 else ''}."
        if held:
            text += f"  {len(held)} left out: open in Maya."
        if failed:
            text += "  Not written: " + "; ".join(failed[:4]) + ("…" if len(failed) > 4 else "")
        self._say(text, "error" if failed else "done")
        for path, _done, _error in outcome:   # a binary scene Maya saved (or tried to) is read again by Maya
            if str(path).lower().endswith(ma_paths.BINARY_SUFFIX):
                self._mb_raw.pop(str(path), None)
        self._read()

    def _on_write_failed(self, error) -> None:
        self._set_busy(False)
        self._say(f"Writing failed: {error}", "error")
        self._read()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self._apply, self._reread, self._environment, self._roots, self._clear):
            widget.setEnabled(not busy)
        if not busy:
            self._apply.setEnabled(any(result.writes for result in self._scans.values() if not result.error))

    # --- choosing / dropping -------------------------------------------------------------------------

    def _on_choose_files(self) -> None:
        paths, _filter = qt.QtWidgets.QFileDialog.getOpenFileNames(
            self, "Maya scenes", str(self._settings.get("last_folder", "") or ""), "Maya scenes (*.ma *.mb)")
        if paths:
            self._settings["last_folder"] = str(Path(paths[0]).parent)
            self.add(paths)

    def _on_choose_folder(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "A folder of Maya scenes",
                                                               str(self._settings.get("last_folder", "") or ""))
        if folder:
            self._settings["last_folder"] = folder
            self.add([folder])

    @staticmethod
    def _dropped(event) -> list:
        data = event.mimeData()
        if not data.hasUrls():
            return []
        return [url.toLocalFile() for url in data.urls() if url.isLocalFile()
                and (url.toLocalFile().lower().endswith(ma_paths.SCENE_SUFFIXES) or os.path.isdir(url.toLocalFile()))]

    def _set_dragging(self, dragging: bool) -> None:
        self._drop.set_dragging(dragging)
        if bool(self._scenes_card.property("dragging")) != dragging:
            self._scenes_card.setProperty("dragging", dragging)   # scene_paths.qss: the card lights up
            repolish(self._scenes_card)

    def dragEnterEvent(self, event) -> None:
        if self._dropped(event):
            event.acceptProposedAction()
            self._set_dragging(True)

    def dragMoveEvent(self, event) -> None:
        if self._dropped(event):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_dragging(False)

    def dropEvent(self, event) -> None:
        self._set_dragging(False)
        paths = self._dropped(event)
        if paths:
            event.acceptProposedAction()
            self.add(paths)

    def _say(self, text: str, state: str = "") -> None:
        self._message.setText(text)
        if self._message.property("state") != state:
            self._message.setProperty("state", state)
            repolish(self._message)
        self._message.show()
        self._message_timer.start()
