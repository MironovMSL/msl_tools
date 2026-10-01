# tools/desktop/maya_gate/boost_tab.py
from typing import Callable, Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.icons import TintedIcon
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.tools.desktop.maya_gate.boost import BoostStore


class _RowCheckbox(BaseCheckbox):
    """Private: BaseCheckbox sized for a dense list row."""

    BOX_SIZE = 14
    CORNER_RADIUS = 4


class _NameLabel(qt.QtWidgets.QLabel):
    """Private: the plug-in's name; a click on it toggles the row's check box."""

    clicked = qt.QtCore.Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _PluginRow(qt.QtWidgets.QWidget):
    """Private: one plug-in — a check box (checked = loaded at startup), an
    icon (its heavy family's, else the generic plug: assets/icons/plugins/),
    its name, the family's name as a pill, and how long it took to load
    last time."""

    HEIGHT = 23
    TIME_WIDTH = 64
    ICON_SIZE = 14
    ICON_SUB_FOLDER = "plugins"
    GENERIC_ICON = "plugin"

    toggled = qt.QtCore.Signal(str, bool)  # (plug-in, load it)

    def __init__(self, name: str, family: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFixedHeight(self.HEIGHT)
        self.checkbox = _RowCheckbox()
        self.checkbox.toggled.connect(lambda checked: self.toggled.emit(self.name, checked))
        icons = UiResources().iconManager
        self.icon = TintedIcon(icons.get_icon(family.lower() if family else self.GENERIC_ICON,
                                              sub_folder=self.ICON_SUB_FOLDER), self.ICON_SIZE)
        self.icon.setProperty("family", bool(family))  # maya_gate.qss: a family's icon is stronger
        self.name_label = _NameLabel(name)
        self.name_label.setObjectName("boostName")
        self.name_label.clicked.connect(self.checkbox.toggle)
        self.family_label = qt.QtWidgets.QLabel(family)
        self.family_label.setObjectName("boostFamily")
        if not family:
            # hide(), never setVisible(True): the label has no parent yet, and showing a
            # parentless widget pops it up as a tiny window of its own for a moment.
            self.family_label.hide()
        self.time_label = qt.QtWidgets.QLabel()
        self.time_label.setObjectName("boostTime")
        self.time_label.setFixedWidth(self.TIME_WIDTH)
        self.time_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignRight | qt.QtCore.Qt.AlignmentFlag.AlignVCenter)

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.icon)
        layout.addWidget(self.name_label)
        layout.addWidget(self.family_label)
        layout.addStretch(1)
        layout.addWidget(self.time_label)

    def set_note(self, text: str, state: str = "", tooltip: str = "") -> None:
        """The right-hand note: a load time ("0.41 s"), "failed", ..."""
        self.time_label.setText(text)
        self.time_label.setToolTip(tooltip)
        if self.time_label.property("state") != state:
            self.time_label.setProperty("state", state)  # maya_gate.qss: QLabel#boostTime[state]
            repolish(self.time_label)


class BoostTab(qt.QtWidgets.QWidget):
    """Maya Gate's "Boost start" tab: which of Maya's auto-load plug-ins the
    current environment starts WITHOUT, so Maya opens faster (see boost.py
    for how a boosted launch works and why Maya's own list stays intact).

    - Off / On: boost for this environment. Off = Maya starts as it always does.
    - The list: every plug-in Maya auto-loads, across the installed versions
      (read from each version's pluginPrefs.mel when the tab is shown — no
      I/O at construction). Checked = loaded at startup. Heavy families
      (Bifrost, Arnold, XGen, ...) are named and listed first; "Heavy off"
      unchecks them. A skipped plug-in can still come up as a dependency of
      a loaded one (LookdevX pulls in USD).
    - After a boosted start each row shows how long its plug-in took to
      load, from the report Maya's side wrote.
    - The version filter ("All versions" / "Maya 2025" ...) narrows the list
      to ONE Maya's auto-load list, with that version's load times — to see
      what a start of exactly that Maya will and won't load. It is a view:
      the skip list stays one per environment, so unchecking a plug-in
      there switches it off for every version. "All on" / "Heavy off" act
      on the rows shown.
    - A notice appears when boost can't work in this environment
      (MAYA_SKIP_USERSETUP_PY) or when Maya's own auto-load list has shrunk
      since the last boosted launch — with "Restore" for the stored copy.

    Storage: `config` is the "boost" branch of the tool's config —
    {"<environment>": {"enabled": bool, "skip": [plug-in, ...]}}. The skip
    list (not a load list) is what's stored, so a plug-in Maya gains later
    is loaded by default.

    Colors: maya_gate.qss (BoostTab ...).
    """

    OFF, ON = "Off", "On"
    ALL_VERSIONS = "All versions"
    YEAR_COMBO_WIDTH = 104

    def __init__(self, store: BoostStore, config, environment: str, years: Sequence[str],
                 app_dir_for: Callable[[], str] | None = None,
                 blocked_reason_for: Callable[[], str] | None = None, parent=None):
        """
        Args:
            store: Maya-side knowledge (autoload lists, reports, backups).
            config: The "boost" config branch (see the class docstring).
            environment: The environment shown first.
            years: Installed Maya versions ("2024", ...).
            app_dir_for: Returns the current environment's MAYA_APP_DIR
                ("" = Maya's default preferences folder).
            blocked_reason_for: Returns why the current environment can't be
                boosted ("" = it can).
        """
        super().__init__(parent)
        self._store = store
        self._config = config
        self._environment = environment
        self._years = list(years)
        self._app_dir_for = app_dir_for or (lambda: "")
        self._blocked_reason_for = blocked_reason_for or (lambda: "")
        self._rows: dict[str, _PluginRow] = {}
        self._fade: qt.QtCore.QPropertyAnimation | None = None
        self._restore_year = ""
        self._year = ""  # the version filter: "" = every installed version
        self._syncing = False  # check boxes are being set from the config, not by the user

        self._build_widgets()
        self._build_layout()
        self._build_connections()
        self._update_title()

    # --- construction ------------------------------------------------------------

    def _build_widgets(self) -> None:
        self._title_label = qt.QtWidgets.QLabel("Boost start")
        self._title_label.setObjectName("boostTitle")
        self._section_label = qt.QtWidgets.QLabel()
        self._section_label.setObjectName("boostSection")
        self._summary_label = qt.QtWidgets.QLabel()
        self._summary_label.setObjectName("boostSummary")
        # The part of the header that gives way (clipped) - it must not widen the whole window.
        self._summary_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored,
                                          qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._switch = SegmentedControl([self.OFF, self.ON], self.OFF)

        newest_first = sorted(self._years, key=int, reverse=True)
        self._year_combo = BaseComboBox([self.ALL_VERSIONS] + [f"Maya {year}" for year in newest_first],
                                        self.ALL_VERSIONS, enable_wheel=False)
        self._year_combo.setFixedWidth(self.YEAR_COMBO_WIDTH)
        self._year_combo.setToolTip("Show one Maya version’s auto-load list.\n"
                                    "The check marks are shared: one list per environment, for every version.")
        if len(self._years) <= 1:
            self._year_combo.hide()  # not setVisible(True) - it has no parent yet (see _PluginRow)

        self._all_button = qt.QtWidgets.QPushButton("All on")
        self._all_button.setToolTip("Load every plug-in at startup, as Maya does by itself")
        self._heavy_button = qt.QtWidgets.QPushButton("Heavy off")
        self._heavy_button.setToolTip("Don’t load the heavy families at startup:\n"
                                      + ", ".join(BoostStore.HEAVY))

        self._notice_label = qt.QtWidgets.QLabel()
        self._notice_label.setObjectName("boostNotice")
        self._notice_label.setWordWrap(True)
        self._restore_button = qt.QtWidgets.QPushButton("Restore")
        self._restore_button.setToolTip("Put back the copy of Maya’s auto-load list stored before the last boosted launch")
        self._notice = qt.QtWidgets.QFrame()
        self._notice.setObjectName("boostNoticeFrame")
        notice_layout = qt.QtWidgets.QHBoxLayout(self._notice)
        notice_layout.setContentsMargins(10, 6, 8, 6)
        self._accept_button = qt.QtWidgets.QPushButton("It\u2019s fine")
        self._accept_button.setToolTip("I removed them from Maya\u2019s auto-load list myself \u2014 stop asking")
        notice_layout.addWidget(self._notice_label, 1)
        notice_layout.addWidget(self._accept_button)
        notice_layout.addWidget(self._restore_button)
        self._notice.hide()

        self._list = qt.QtWidgets.QWidget()
        self._list.setObjectName("boostList")
        self._list_layout = qt.QtWidgets.QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(0)
        self._empty_label = qt.QtWidgets.QLabel("No Maya preferences found yet — start Maya once, then come back.")
        self._empty_label.setObjectName("boostEmpty")
        self._empty_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._list_layout.addWidget(self._empty_label)
        self._list_layout.addStretch(1)
        self._scroll = StableScrollArea()
        self._scroll.setObjectName("boostScroll")
        self._scroll.setWidget(self._list)

        self._hint_label = qt.QtWidgets.QLabel(
            "Unchecked plug-ins aren’t loaded when Maya starts from here. Maya’s own Auto load settings stay "
            "as they are, and a scene that needs a plug-in still loads it.")
        self._hint_label.setObjectName("boostHint")
        self._hint_label.setWordWrap(True)

        # How long the last start took (measured by the loader inside Maya), boost vs. normal.
        self._timing_label = qt.QtWidgets.QLabel()
        self._timing_label.setObjectName("boostTiming")
        self._timing_label.setWordWrap(True)
        self._timing_label.setTextFormat(qt.QtCore.Qt.TextFormat.RichText)
        self._timing_label.hide()

    def _build_layout(self) -> None:
        header = qt.QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self._title_label)
        header.addWidget(self._section_label)
        header.addSpacing(6)
        header.addWidget(self._summary_label, 1)
        header.addWidget(self._year_combo)
        header.addWidget(self._heavy_button)
        header.addWidget(self._all_button)
        header.addSpacing(4)
        header.addWidget(self._switch)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._notice)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._timing_label)
        layout.addWidget(self._hint_label)

    def _build_connections(self) -> None:
        self._switch.current_changed.connect(self._on_switched)
        self._all_button.clicked.connect(self._on_all_on)
        self._year_combo.activated.connect(self._on_year_picked)
        self._heavy_button.clicked.connect(self._on_heavy_off)
        self._restore_button.clicked.connect(self._on_restore)
        self._accept_button.clicked.connect(self._on_accept)

    # --- state ---------------------------------------------------------------------

    FADE_MS = 200

    def set_environment(self, environment: str) -> None:
        self._environment = environment
        self._update_title()
        if self.isVisible():
            self.refresh()
            self._fade_in()

    def _fade_in(self) -> None:
        """The list eases in after it changed wholesale (another environment
        or version), instead of snapping to the new rows."""
        if self._fade is not None:
            self._fade.stop()
        effect = qt.QtWidgets.QGraphicsOpacityEffect(self._list)
        effect.setOpacity(0.0)
        self._list.setGraphicsEffect(effect)  # replaces (and deletes) a previous one
        self._fade = qt.QtCore.QPropertyAnimation(effect, b"opacity", self)
        self._fade.setDuration(self.FADE_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        # Drop the effect when done: a widget with one is painted through an offscreen buffer.
        self._fade.finished.connect(lambda: self._list.setGraphicsEffect(None))
        self._fade.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()  # the files are small; fresh every time the tab comes up

    def _settings(self) -> dict:
        """{"enabled", "skip"} of the current environment (defaults if unset)."""
        try:
            node = dict(self._config[self._environment])
        except (KeyError, TypeError):
            node = {}
        return {"enabled": bool(node.get("enabled", False)), "skip": [str(n) for n in node.get("skip", [])]}

    def _store_settings(self, enabled: bool, skip: Sequence[str]) -> None:
        self._config[self._environment] = {"enabled": bool(enabled), "skip": sorted(skip, key=str.lower)}

    def is_enabled(self) -> bool:
        return self._settings()["enabled"]

    def skipped(self) -> list[str]:
        return self._settings()["skip"]

    def _update_title(self) -> None:
        self._section_label.setText(f"· {self._environment}")

    def refresh(self) -> None:
        """Re-reads Maya's lists and reports and shows the current environment."""
        app_dir = self._app_dir_for() or None
        per_year = {year: self._store.autoload_plugins(year, app_dir) for year in self._years}
        settings = self._settings()
        if self._year:
            names = list(per_year.get(self._year, []))  # exactly what that Maya auto-loads
        else:
            names = []
            for year in sorted(per_year, key=int, reverse=True):
                names += [name for name in per_year[year] if name not in names]
            names += [name for name in settings["skip"] if name not in names]  # skipped, but gone from Maya's lists
        # The heavy families first (they are what one comes here for), then the rest by name.
        names.sort(key=lambda name: (not BoostStore.family_of(name), BoostStore.family_of(name), name.lower()))
        self._rebuild_rows(names, per_year)

        skip = set(settings["skip"])
        for name, row in self._rows.items():
            row.checkbox.blockSignals(True)
            row.checkbox.set_checked_immediate(name not in skip)
            row.checkbox.blockSignals(False)
        self._switch.set_current(self.ON if settings["enabled"] else self.OFF, animate=False)
        self._apply_reports()
        self._update_notice(app_dir)
        self._update_summary()
        self._update_timing()

    def _update_timing(self) -> None:
        """"Last start: Maya 2025 - 18.2 s with boost (plug-ins 3.6 s) - 33.0 s without" for the
        current environment (and the filtered version), from the launches Maya's side timed."""
        log = self._store.launch_log()
        last = log.last_measured(self._environment, self._year)
        if last is None:
            self._timing_label.hide()
            return
        year = str(last.get("year", ""))

        def describe(entry: dict) -> str:
            text = f"<b>{float(entry['ready_seconds']):.1f} s</b> " + ("with boost" if entry.get("boosted") else "without boost")
            if entry.get("boosted") and "plugin_seconds" in entry:
                text += f" (plug-ins {float(entry['plugin_seconds']):.1f} s)"
            return text

        parts = [describe(last)]
        other = log.last_measured(self._environment, year, boosted=not last.get("boosted"))
        if other is not None:
            parts.append(describe(other))
        self._timing_label.setText(f"Last start of Maya {year} here: " + " \u00b7 ".join(parts))
        self._timing_label.setToolTip(f"From the click in Maya Gate until Maya was idle after starting up.\n"
                                      f"Last start: {last.get('clicked', '')}")
        self._timing_label.show()

    def _rebuild_rows(self, names: list[str], per_year: dict[str, list[str]]) -> None:
        if list(self._rows) == names:
            return
        for row in self._rows.values():
            row.hide()
            row.deleteLater()
        self._rows = {}
        for index, name in enumerate(names):
            row = _PluginRow(name, BoostStore.family_of(name))
            years = [year for year in sorted(per_year, key=int) if name in per_year[year]]
            where = "Maya " + ", ".join(years) if years else "not in any Maya’s auto-load list now"
            row.setToolTip(f"{name}\nAuto-loaded by: {where}")
            row.toggled.connect(self._on_row_toggled)
            self._list_layout.insertWidget(index, row)
            self._rows[name] = row
        self._empty_label.setText(
            f"Maya {self._year} has no preferences in this environment’s folder yet — start it once, then come back."
            if self._year else "No Maya preferences found yet — start Maya once, then come back.")
        self._empty_label.setVisible(not names)

    def _apply_reports(self) -> None:
        """Load times from the newest report that mentions each plug-in —
        or only from the filtered version's report."""
        notes: dict[str, tuple[str, str, str]] = {}
        for year in ([self._year] if self._year else sorted(self._years, key=int)):  # newer years overwrite
            report = self._store.report(year)
            if not report:
                continue
            source = f"Maya {year}, {report.get('time', '')}".strip(", ")
            for name, entry in report["plugins"].items():
                status = entry.get("status", "")
                if status in ("loaded", "kept"):
                    notes[name] = (f"{float(entry.get('seconds', 0)):.2f} s", "", f"Load time in {source}")
                elif status == "failed":
                    notes[name] = ("failed", "error", f"{entry.get('error', '')}\n{source}".strip())
        for name, row in self._rows.items():
            row.set_note(*notes.get(name, ("", "", "")))

    def _update_summary(self) -> None:
        settings = self._settings()
        total = len(self._rows)
        loading = sum(1 for name in self._rows if name not in set(settings["skip"]))
        if not total:
            text = ""
        elif not settings["enabled"]:
            text = "off — Maya loads all of them"
        else:
            text = f"{loading} of {total} plug-ins at startup"
        if text and self._year:
            text += f" · Maya {self._year}"
        self._summary_label.setText(text)
        active = settings["enabled"] and not self._blocked_reason_for()
        if self._list.property("active") != active:
            self._list.setProperty("active", active)  # maya_gate.qss could dim an inactive list
        for row in self._rows.values():
            row.setEnabled(settings["enabled"])
        self._all_button.setEnabled(settings["enabled"])
        self._heavy_button.setEnabled(settings["enabled"])

    def _update_notice(self, app_dir: str | None) -> None:
        """Blocked environment, or a Maya list that lost plug-ins since the last boosted launch."""
        self._restore_year = ""
        blocked = self._blocked_reason_for()
        if blocked:
            self._show_notice(blocked, restore=False)
            return
        for year in sorted(self._years, key=int, reverse=True):
            lost = self._store.lost_plugins(year, app_dir)
            if lost:
                self._restore_year = year
                shown = ", ".join(lost[:4]) + ("…" if len(lost) > 4 else "")
                self._show_notice(f"Maya {year}’s auto-load list lost {len(lost)} plug-in(s) since the last "
                                  f"boosted launch ({shown}). If you didn’t switch them off in Maya, restore "
                                  f"the stored copy (close Maya {year} first).", restore=True)
                return
        # A Maya with no preferences in this environment's folder yet: its first start can't be boosted.
        fresh = [year for year in sorted(self._years, key=int) if not self._store.autoload_plugins(year, app_dir)]
        # (Only in the all-versions view: with one version picked, the list itself says it.)
        if fresh and len(fresh) < len(self._years) and self._settings()["enabled"] and not self._year:
            self._show_notice(f"No preferences in this environment\u2019s folder yet for Maya {', '.join(fresh)}: "
                              f"the first start of those from here is a normal one, boost applies from the second.",
                              restore=False)
            return
        self._notice.hide()

    def _show_notice(self, text: str, restore: bool) -> None:
        self._notice_label.setText(text)
        self._restore_button.setVisible(restore)
        self._accept_button.setVisible(restore)
        self._notice.show()

    # --- actions -------------------------------------------------------------------

    def _on_switched(self, option: str) -> None:
        self._store_settings(option == self.ON, self._settings()["skip"])
        self._update_notice(self._app_dir_for() or None)
        self._update_summary()

    def _on_row_toggled(self, name: str, load: bool) -> None:
        if self._syncing:
            return
        skip = set(self._settings()["skip"])
        skip.discard(name) if load else skip.add(name)
        self._store_settings(self._settings()["enabled"], skip)
        self._update_summary()

    def _set_skipped(self, skip: set) -> None:
        self._store_settings(self._settings()["enabled"], skip)
        # Not blockSignals(): BaseCheckbox animates from its own toggled signal.
        self._syncing = True
        try:
            for name, row in self._rows.items():
                row.checkbox.setChecked(name not in skip)  # animated: the change is the user's
        finally:
            self._syncing = False
        self._update_summary()

    def _on_year_picked(self, _index: int) -> None:
        text = self._year_combo.currentText()
        self._year = "" if text == self.ALL_VERSIONS else text.rsplit(" ", 1)[-1]
        self.refresh()
        self._fade_in()

    def _on_all_on(self) -> None:
        """Checks every row SHOWN (with a version filter: that version's plug-ins only)."""
        self._set_skipped(set(self._settings()["skip"]) - set(self._rows))

    def _on_heavy_off(self) -> None:
        heavy = {name for name in self._rows if name in BoostStore.heavy_plugins()}
        self._set_skipped(set(self._settings()["skip"]) | heavy)

    def _on_accept(self) -> None:
        if self._restore_year:
            self._store.accept_current(self._restore_year, self._app_dir_for() or None)
            self.refresh()

    def _on_restore(self) -> None:
        year = self._restore_year
        if not year:
            return
        choice = ConfirmDialog.ask(
            self, "Restore Maya’s auto-load list",
            f"Put back the stored copy of Maya {year}’s auto-load list?",
            details=f"Close Maya {year} first: it rewrites the list when it exits.",
            choices=[("restore", "Restore"), ("cancel", "Cancel")], kind="warning")
        if choice == "restore":
            self._store.restore_backup(year, self._app_dir_for() or None)
            self.refresh()
