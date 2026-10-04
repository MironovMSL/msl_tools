# tools/desktop/maya_gate/page.py
import os
import threading

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tinted_menu_icon
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.atoms.tabs import BaseTabWidget
from msl_tools.msl.tools.desktop.maya_gate.toolbar import MayaGateToolbar
from msl_tools.msl.tools.desktop.maya_gate.version_row import MayaVersionRow
from msl_tools.msl.tools.desktop.maya_gate.variable_group import CollapsibleVariableGroup
from msl_tools.msl.tools.desktop.maya_gate.variable_adder import EnvVariableAdder
from msl_tools.msl.tools.desktop.maya_gate.user_setup import ScriptUnavailable, UserSetupStore
from msl_tools.msl.tools.desktop.maya_gate.user_setup_tab import UserSetupTab
from msl_tools.msl.tools.desktop.maya_gate import launch_check
from msl_tools.msl.tools.desktop.maya_gate.boost import BoostStore, LaunchLog
from msl_tools.msl.tools.desktop.maya_gate.boost_tab import BoostTab
from msl_tools.msl.tools.desktop.maya_gate.session_history import SessionHistory
from msl_tools.msl.tools.desktop.maya_gate.snippets import SnippetStore
from msl_tools.msl.tools.desktop.maya_gate.sessions_tab import SessionsTab
from msl_tools.msl.ui.maya_link import MayaLinkServer
from msl_tools.msl.tools.desktop.maya_gate.maya_variables import VariableKind, launch_values, spec_of
from msl_tools.msl.ui.widgets.compositions import BrowseMode, ValueSpec

# How a variable's browse button behaves, by what the variable holds (maya_variables).
_BROWSE_MODE = {VariableKind.PATH_LIST: BrowseMode.APPEND,
                VariableKind.PATH: BrowseMode.REPLACE,
                VariableKind.FILE: BrowseMode.FILE}


def _value_spec_for(name: str) -> ValueSpec:
    """How variable `name`'s row edits its value (EnvVarRow knows nothing
    about Maya): a path field per kind, a switch for a flag, a drop-down
    for a choice."""
    spec = spec_of(name)
    return ValueSpec(browse=_BROWSE_MODE.get(spec.kind, BrowseMode.NONE),
                     choices=spec.choices if spec.kind is VariableKind.CHOICE else (),
                     toggle_value=spec.on_value if spec.kind is VariableKind.FLAG else "",
                     description=spec.description, file_filter=spec.file_filter)


def _default_value_for(name: str) -> str:
    return spec_of(name).default_value


class MayaGatePage(qt.QtWidgets.QWidget):
    """Maya Gate's tool page, fully assembled: pick a Maya version and a
    named environment, edit what that environment brings along in the tabs
    below, then click a version icon to launch it.

    Tabs (both follow the environment picked in the toolbar):
    - "Variables": two groups per environment — "Maya Variables" (known
      Maya variables) and "Custom Variables" (your own) — both merged into
      that environment's launch. Nothing is shared between environments;
      "Copy to…" on a selection copies variables to another environment.
    - "userSetup": a Python script Maya runs at startup next to the user's
      own userSetup.py (see UserSetupStore for how it's injected).
    - "Boost start": which of Maya's auto-load plug-ins this environment
      starts without, so Maya opens faster (see boost.py).
    - "Sessions": the Mayas running right now, whatever their environment
      (live, through the hub <-> Maya link: ui/maya_link/).

    Config-backed via Resources().configsDesktopHubMng.get_config("maya_gate")
    (configs/desktop/maya_gate/) — one JsonConfig replaces MSL_MayaGate's
    separate config.ini + json_config.json; userSetup scripts are plain .py
    files next to it. The page also remembers its own state there (year,
    environment, tab, folded groups) and restores it on the next start.

    Resize handling deliberately NOT ported: the original chained
    `.update_size()` calls up to resize its own standalone top-level
    window whenever a group's row count changed. Maya Gate is one page
    inside the hub's dialog, so the Variables tab scrolls instead.
    """

    _problems_found = qt.QtCore.Signal(int, list)   # (which check, its lines): from the checking thread

    ENVIRONMENTS = ["<default>", "Stable", "Dev"]
    DEFAULT_ENVIRONMENT = "Dev"
    TOOL_NAME = "maya_gate"

    # Config layout (both variable branches have the same shape):
    #   "maya":   {"<env>": {...}}  Maya variables per environment ("Maya Variables" group)
    #   "custom": {"<env>": {...}}  custom variables per environment ("Custom Variables" group)
    #   "_ui":    page state restored on start: picked year / environment,
    #             open tab, folded groups. Never part of a launch.
    # _launch reads only "maya"."<env>" + "custom"."<env>".
    MAYA_KEY = "maya"
    CUSTOM_KEY = "custom"
    UI_SECTION = "_ui"
    BOOST_KEY = "boost"   # {"<env>": {"enabled": bool, "skip": [plug-in, ...]}} - see BoostTab
    # Tells the launched Maya which environment it is (read by the MSL menu's "Print Launch Report").
    ENVIRONMENT_VARIABLE = "MSL_GATE_ENVIRONMENT"
    VARIABLES_VARIABLE = "MSL_GATE_VARIABLES"   # names of the variables this launch sets (os.pathsep-joined)
    # Environments whose Mayas accept code from the Sessions tab's console. The launched Maya
    # is told with MSL_GATE_CONSOLE=1 and enforces it itself (tools/maya/hub_link.py).
    CONSOLE_ENVIRONMENTS = ("Dev",)
    RECENT_SCENES_SHOWN = 8   # in a version's right-click menu
    HIDDEN_VARIABLES = (MayaLinkServer.TOKEN_VARIABLE,)   # never shown in a launch preview

    # Color of the icons in a version's right-click menu (maya_gate.qss) - see tinted_menu_icon().
    menuIconColor = color_property("_menu_icon_color", None)
    CONSOLE_VARIABLE = "MSL_GATE_CONSOLE"
    TAB_KEYS = ("variables", "user_setup", "boost", "sessions")  # tab order; stored by key, not index
    SESSIONS_TAB_TITLE = "Sessions"
    DEFAULTS = {MAYA_KEY: {env: {} for env in ENVIRONMENTS},
                CUSTOM_KEY: {env: {} for env in ENVIRONMENTS},
                BOOST_KEY: {env: {"enabled": False, "skip": []} for env in ENVIRONMENTS},
                UI_SECTION: {"year": "", "environment": DEFAULT_ENVIRONMENT, "tab": TAB_KEYS[0],
                             "collapsed": {"maya": False, "custom": False}}}

    # Older layouts, moved over once by _migrate_legacy_config(): Maya variables
    # sat at the top level ("<env>": {...}), custom ones under "additional",
    # and the fold flags were named "environment"/"additional".
    _LEGACY_CUSTOM_KEY = "additional"
    _LEGACY_COLLAPSED_KEYS = {"environment": "maya", "additional": "custom"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._menu_icon_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_secondary)  # until QSS applies
        resources = Resources()
        configs = resources.configsDesktopHubMng
        self._logger = resources.logsDesktopHub.get(self.TOOL_NAME)
        self._config = configs.get_config(self.TOOL_NAME, defaults=self.DEFAULTS)
        self._migrate_legacy_config()
        self._ui = self._config[self.UI_SECTION]
        self._user_setup_store = UserSetupStore(configs.base_dir / self.TOOL_NAME)
        self._boost_store = BoostStore(configs.base_dir / self.TOOL_NAME)
        self._session_history = SessionHistory(configs.base_dir / self.TOOL_NAME)
        self._snippet_store = SnippetStore(configs.base_dir / self.TOOL_NAME)
        saved_environment = self._ui.get("environment")
        self._environment = (saved_environment if saved_environment in self.ENVIRONMENTS
                             else self.DEFAULT_ENVIRONMENT)

        self._build_widgets()
        self._build_layout()
        self._build_connections()

    def _build_widgets(self) -> None:
        installs = MayaPaths.get_available_installs()
        years = sorted(installs, key=int)
        # The saved year only while that Maya is still installed; else the earliest one.
        saved_year = self._ui.get("year")
        year = saved_year if saved_year in years else (years[0] if years else "")

        self._version_row = MayaVersionRow(min_year=year)
        self._version_row.set_environment(self._environment)
        self._toolbar = MayaGateToolbar(
            years=years,
            current_year=year,
            environments=self.ENVIRONMENTS,
            current_environment=self._environment,
        )

        # What is wrong with the environment before a launch (launch_check.py): a quiet link under
        # the versions, there only while there is something to say; a click lists it.
        self._problems_link = qt.QtWidgets.QPushButton()
        self._problems_link.setObjectName("gateProblems")
        self._problems_link.setFlat(True)
        self._problems_link.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._problems_link.hide()
        self._problems: list[str] = []
        self._problems_check = 0
        self._problems_busy = False   # a check thread is out (see _check_environment)
        self._problems_again = False  # another was asked for meanwhile
        self._problems_timer = qt.QtCore.QTimer(self)
        self._problems_timer.setInterval(self.CHECK_EVERY_MS)
        self._problems_timer.timeout.connect(self._check_environment)

        self._tabs = BaseTabWidget()  # sliding accent indicator
        # Line the tab bar up with the variable groups' frames (after their gutter).
        self._tabs.setStyleSheet(
            f"QTabWidget::tab-bar {{ left: {CollapsibleVariableGroup.SELECTION_GUTTER}px; }}")
        self._tabs.addTab(self._build_variables_tab(), "Variables")
        self._user_setup_tab = UserSetupTab(self._user_setup_store, self._environment)
        self._tabs.addTab(self._indented(self._user_setup_tab), "userSetup")
        self._boost_tab = BoostTab(self._boost_store, self._config[self.BOOST_KEY], self._environment, years,
                                   app_dir_for=lambda: self._launch_variables().get("MAYA_APP_DIR", ""),
                                   blocked_reason_for=lambda: BoostStore.blocked_reason(self._launch_variables()),
                                   running_years_for=lambda: {session.version
                                                              for session in MayaLinkServer.instance().sessions()})
        self._tabs.addTab(self._indented(self._boost_tab), "Boost start")
        self._link = MayaLinkServer.instance()  # the hub's one server; run_hub starts it listening
        self._sessions_tab = SessionsTab(self._link, self._session_history,
                                         launch=self._launch_scene, settings=self._ui,
                                         snippets=self._snippet_store)
        self._tabs.addTab(self._indented(self._sessions_tab), self.SESSIONS_TAB_TITLE)
        self._link.sessions_changed.connect(self._update_sessions_tab_title)
        self._link.attention_changed.connect(self._update_sessions_tab_title)
        self._update_sessions_tab_title()
        saved_tab = self._ui.get("tab")
        self._tabs.setCurrentIndex(self.TAB_KEYS.index(saved_tab) if saved_tab in self.TAB_KEYS else 0)

    def _build_variables_tab(self) -> qt.QtWidgets.QWidget:
        self._adder = EnvVariableAdder()
        collapsed = self._ui["collapsed"]
        # Both groups get a branch whose sections are the environments.
        self._maya_group = CollapsibleVariableGroup(
            "Maya Variables", self._environment, self._config[self.MAYA_KEY],
            collapsed=bool(collapsed.get("maya", False)), copy_targets=self.ENVIRONMENTS,
            value_spec_for=_value_spec_for, default_value_for=_default_value_for)
        self._custom_group = CollapsibleVariableGroup(
            "Custom Variables", self._environment, self._config[self.CUSTOM_KEY],
            collapsed=bool(collapsed.get("custom", False)), copy_targets=self.ENVIRONMENTS,
            value_spec_for=_value_spec_for, default_value_for=_default_value_for)

        container = qt.QtWidgets.QWidget()
        container_layout = qt.QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 6, 0, 0)
        container_layout.setSpacing(5)
        container_layout.addWidget(self._indented(self._adder))
        container_layout.addWidget(self._maya_group)
        container_layout.addWidget(self._custom_group)
        container_layout.addStretch()

        scroll = StableScrollArea()
        scroll.setWidget(container)
        return scroll

    @staticmethod
    def _indented(widget: qt.QtWidgets.QWidget) -> qt.QtWidgets.QWidget:
        """Wraps `widget` so its left edge lines up with the variable groups'
        frames, which start after their drag-handle gutter."""
        wrapper = qt.QtWidgets.QWidget()
        wrapper_layout = qt.QtWidgets.QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(CollapsibleVariableGroup.SELECTION_GUTTER, 0, 0, 0)
        wrapper_layout.addWidget(widget)
        return wrapper

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        layout.addWidget(self._indented(self._toolbar))  # environment lines up with the row below
        layout.addWidget(self._indented(self._version_row))
        problems = qt.QtWidgets.QHBoxLayout()
        problems.setContentsMargins(CollapsibleVariableGroup.SELECTION_GUTTER, 0, 0, 0)
        problems.addWidget(self._problems_link)
        problems.addStretch(1)
        layout.addLayout(problems)
        layout.addWidget(self._tabs, 1)

    def _build_connections(self) -> None:
        self._toolbar.year_changed.connect(self._version_row.on_min_year_changed)
        self._toolbar.year_changed.connect(lambda year: self._save_ui("year", year))
        self._toolbar.environment_changed.connect(self._on_environment_changed)
        self._tabs.currentChanged.connect(lambda index: self._save_ui("tab", self.TAB_KEYS[index]))
        self._version_row.clicked.connect(self._launch)
        self._problems_found.connect(self._on_problems_found)
        self._problems_link.clicked.connect(self._show_problems)
        self._version_row.scene_dropped.connect(self._open_scene)  # from the file manager or a session row
        self._version_row.menu_requested.connect(self._on_version_menu)

        self._adder.known_variable_added.connect(self._maya_group.add_variable)
        self._adder.custom_variable_added.connect(self._custom_group.add_variable)

        self._maya_group.collapsed_changed.connect(
            lambda state: self._save_collapsed("maya", state))
        self._custom_group.collapsed_changed.connect(
            lambda state: self._save_collapsed("custom", state))

    def _migrate_legacy_config(self) -> None:
        """One-time move of configs saved in an older layout:
        - Maya variables at the top level ("<env>": {...}) -> "maya"."<env>";
        - custom variables under "additional" -> "custom";
        - "_ui" fold flags "environment"/"additional" -> "maya"/"custom".
        A name already present under the new key wins; nothing else is
        dropped. Top-level keys are then re-ordered maya, custom, _ui."""
        data = self._config.data
        # Only ENVIRONMENT sections are legacy Maya variables - never another top-level
        # branch ("boost" was once swept into "maya" by a looser test, on every start).
        legacy_maya = {key: value for key, value in data.items()
                       if key in self.ENVIRONMENTS and isinstance(value, dict)}
        stray = [key for key in data.get(self.MAYA_KEY, {}) if key not in self.ENVIRONMENTS]
        for key in stray:  # what that looser test left behind
            del self._config[self.MAYA_KEY][key]
        legacy_custom = data.get(self._LEGACY_CUSTOM_KEY)
        collapsed = data.get(self.UI_SECTION, {}).get("collapsed", {})
        legacy_collapsed = {old: collapsed[old] for old in self._LEGACY_COLLAPSED_KEYS if old in collapsed}
        if not legacy_maya and legacy_custom is None and not legacy_collapsed:
            return

        with self._config.batch():
            self._merge_variables(self._config[self.MAYA_KEY], legacy_maya)
            for key in legacy_maya:
                del self._config[key]
            if isinstance(legacy_custom, dict):
                self._merge_variables(self._config[self.CUSTOM_KEY], legacy_custom)
            if legacy_custom is not None:
                del self._config[self._LEGACY_CUSTOM_KEY]
            for old, state in legacy_collapsed.items():
                self._config[self.UI_SECTION]["collapsed"][self._LEGACY_COLLAPSED_KEYS[old]] = state
                del self._config[self.UI_SECTION]["collapsed"][old]

            # Re-insert so the file reads maya, custom, _ui (then anything else).
            snapshot = self._config.data
            order = [self.MAYA_KEY, self.CUSTOM_KEY, self.UI_SECTION]
            order += [key for key in snapshot if key not in order]
            for key in order:
                del self._config[key]
            for key in order:
                self._config[key] = snapshot[key]

    @staticmethod
    def _merge_variables(target, source: dict) -> None:
        """Copies {"<env>": {name: value}} into `target`; names already there win."""
        for environment, variables in source.items():
            if not isinstance(variables, dict):
                continue
            for name, value in variables.items():
                if name not in target[environment]:
                    target[environment][name] = value

    def _save_collapsed(self, group_key: str, collapsed: bool) -> None:
        self._ui["collapsed"][group_key] = collapsed

    def _save_ui(self, key: str, value: str) -> None:
        self._ui[key] = value

    def _on_environment_changed(self, environment: str) -> None:
        self._environment = environment
        self._save_ui("environment", environment)
        self._version_row.set_environment(environment)
        self._maya_group.set_section(environment)
        self._custom_group.set_section(environment)
        self._user_setup_tab.set_environment(environment)
        self._boost_tab.set_environment(environment)
        self._check_environment()

    # --- the environment, checked before a launch ----------------------------------

    CHECK_EVERY_MS = 4000   # while the page is on screen: variables and the script are edited right here

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._check_environment()
        self._problems_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._problems_timer.stop()

    def _check_environment(self) -> None:
        """Looks the current environment over on a thread (it reads the disk: a folder on a slow
        drive must not stall the window); the answer comes back as _problems_found."""
        self._problems_check += 1  # also when deferred: a check still out is then for old settings
        if self._problems_busy:
            # One check at a time: a folder on a dead network drive blocks os.path.exists() for
            # up to a minute, and a new thread every CHECK_EVERY_MS would pile up meanwhile.
            self._problems_again = True
            return
        self._problems_busy = True
        number, environment = self._problems_check, self._environment
        variables = self._launch_variables(environment)
        try:
            script = self._user_setup_store.read(environment)
        except ScriptUnavailable:
            script = ""  # nothing to look over now; the tab says it can't be read
        boost = self._boost_settings(environment)
        blocked = BoostStore.blocked_reason(variables)
        emit = self._problems_found.emit

        def run() -> None:
            try:
                lines = launch_check.check(variables, script, boost["enabled"], blocked)
            except Exception:
                lines = []
            try:
                emit(number, lines)
            except RuntimeError:
                pass  # the page is gone

        threading.Thread(target=run, daemon=True).start()

    def _on_problems_found(self, number: int, lines: list) -> None:
        self._problems_busy = False
        if self._problems_again:  # asked for while this one ran: look again, with what is set now
            self._problems_again = False
            self._check_environment()
            return
        if number != self._problems_check:
            return  # an older check: the environment changed meanwhile
        self._problems = list(lines)
        count = len(lines)
        name = self._environment.strip("<>")
        self._problems_link.setText(f"⚠  {name}: {count} thing{'s' if count != 1 else ''} to check before a launch")
        self._problems_link.setToolTip(chr(10).join(lines[:8]) + (chr(10) + "…" if count > 8 else ""))
        self._problems_link.setVisible(bool(lines))

    def _show_problems(self) -> None:
        if self._problems:
            TextDialog.show_for(self.window(), f"{self._environment.strip('<>')}: before a launch",
                                chr(10).join(self._problems))

    def _update_sessions_tab_title(self) -> None:
        """"Sessions" / "Sessions · 2": the count is seen from any tab."""
        count = len(self._link.sessions())
        # Which versions are running: a mark on their tiles.
        running: dict[str, int] = {}
        for session in self._link.sessions():
            running[session.version] = running.get(session.version, 0) + 1
        self._version_row.set_running(running)
        index = self._tabs.indexOf(self._sessions_tab.parentWidget())
        if self._link.unread_errors():  # errors nobody has looked at: seen from any tab
            self._tabs.setTabText(index, self.SESSIONS_TAB_TITLE + (f" \u00b7 {count}" if count else "") + " \u00b7 !")
            return
        self._tabs.setTabText(index, self.SESSIONS_TAB_TITLE + (f" \u00b7 {count}" if count else ""))

    def show_sessions(self) -> None:
        """Opens the Sessions tab (the header's link indicator leads here)."""
        self._tabs.setCurrentIndex(self._tabs.indexOf(self._sessions_tab.parentWidget()))

    def _launch_variables(self, environment: str | None = None) -> dict[str, str]:
        """An environment's variables as a launch passes them (Maya + custom,
        empty ones left out); the current environment unless one is named."""
        environment = environment or self._environment
        variables: dict[str, str] = {}
        variables.update(dict(self._config[self.MAYA_KEY][environment]))
        variables.update(dict(self._config[self.CUSTOM_KEY][environment]))
        # Empty = not passed: a flag switched off, a choice not made, a blank field.
        return launch_values(variables)

    def _boost_settings(self, environment: str) -> dict:
        """{"enabled", "skip"} of `environment`'s boost start (as BoostTab stores them)."""
        try:
            node = dict(self._config[self.BOOST_KEY][environment])
        except (KeyError, TypeError):
            node = {}
        return {"enabled": bool(node.get("enabled", False)), "skip": [str(name) for name in node.get("skip", [])]}

    def _prepare_launch(self, year: str, environment: str | None = None, scene: str = "",
                        preview: bool = False) -> dict:
        """Everything a launch of Maya `year` hands to Maya, as a dict:
        environment, variables (what is added to the system's own), arguments,
        boosted, skip, own (the names the environment's settings set), and
        boost_note (why boost, though switched on, isn't applied).

        With preview=True nothing is changed on disk beyond what is rewritten
        identically anyway: no backup of Maya's plug-in list, no launch
        record, the editor's script isn't saved."""
        environment = environment if environment in self.ENVIRONMENTS else self._environment
        environment_vars = self._launch_variables(environment)
        own = list(environment_vars)
        boost = self._boost_settings(environment)
        # Boost: only when its loader can run and has a list to work from - otherwise Maya,
        # started without auto-load, would save an (almost) empty auto-load list of its own.
        blocked = BoostStore.blocked_reason(environment_vars)
        has_list = bool(self._boost_store.autoload_plugins(year, environment_vars.get("MAYA_APP_DIR") or None))
        boosted = boost["enabled"] and not blocked and has_list
        boost_note = ""
        if boost["enabled"] and not boosted:
            boost_note = blocked or (f"Maya {year} has no plug-in list in this environment's preferences yet: "
                                     f"this start is a normal one.")
        set_here = list(environment_vars)
        if "PYTHONPATH" not in set_here:
            set_here.append("PYTHONPATH")  # always extended by the launch (msl_tools, userSetup)
        environment_vars[self.ENVIRONMENT_VARIABLE] = environment
        environment_vars[self.VARIABLES_VARIABLE] = os.pathsep.join(set_here)
        if environment in self.CONSOLE_ENVIRONMENTS:
            environment_vars[self.CONSOLE_VARIABLE] = "1"

        if environment == self._environment and not preview:
            self._user_setup_tab.save()  # launch with what's on screen, not the last autosave
        environment_vars = self._user_setup_store.launch_environment(environment, environment_vars)
        arguments: list[str] = []
        # The loader goes along in every launch: it also measures the startup time.
        environment_vars = self._boost_store.attach_loader(environment_vars)
        if boosted:
            environment_vars, arguments = self._boost_store.prepare_launch(
                environment, year, boost["skip"], environment_vars, backup=not preview)
        if scene:
            arguments = arguments + ["-file", scene]
        if not preview:
            self._link.ensure_listening()  # normally already is (run_hub); a Maya can't join a hub that isn't
        environment_vars.update(self._link.launch_variables())
        return {"environment": environment, "variables": environment_vars, "arguments": arguments,
                "boosted": boosted, "skip": boost["skip"] if boosted else [], "own": own, "boost_note": boost_note}

    def _launch(self, year: str, environment: str | None = None, scene: str = "") -> bool:
        """Starts Maya `year` in `environment` (the current one unless named —
        a restart or a reopened session names its own), opening `scene` if given."""
        launch = self._prepare_launch(year, environment, scene)
        environment, boosted = launch["environment"], launch["boosted"]
        environment_vars = self._boost_store.launch_log().start(
            year, environment, boosted, len(launch["skip"]), launch["variables"])
        self._logger.info(f'Launching Maya {year}, environment "{environment}"'
                          + (" (boost start)" if boosted else "") + (f", scene {scene}" if scene else ""))
        started = ProcessLauncher.launch_maya(version=year, environment=environment_vars,
                                              arguments=launch["arguments"])
        if not started:
            self._logger.warning(f'Maya {year} did not start (environment "{environment}")')
        return started

    def launch_preview(self, year: str) -> str:
        """What a launch of Maya `year` in the current environment would hand to
        Maya, as text: the executable, its arguments, boost, and every variable
        — the environment's own first, then what MSL Tools adds."""
        launch = self._prepare_launch(year, preview=True)
        variables, own = launch["variables"], launch["own"]
        lines = [f'Maya {year}  ·  environment "{launch["environment"]}"', "",
                 f"Executable    {MayaPaths.get_executable_path(str(year)) or 'not found'}",
                 "Arguments     " + (" ".join(launch["arguments"]) or "none")]
        if launch["boosted"]:
            lines.append(f"Boost start   on — {len(launch['skip'])} plug-in(s) not loaded at startup")
        else:
            lines.append("Boost start   " + ("on, but not applied" if launch["boost_note"] else "off"))
            if launch["boost_note"]:
                lines.append("              " + launch["boost_note"])
        try:
            script = self._user_setup_store.read(launch["environment"])
            lines.append("userSetup     " + (f"this environment's script ({len(script.splitlines())} lines)"
                                             if script.strip() else "none (the script is blank)"))
        except ScriptUnavailable as error:
            lines.append(f"userSetup     this environment's script — {error}; Maya reads it itself")

        def show(names: list) -> list:
            width = max((len(name) for name in names), default=0)
            shown = []
            for name in names:
                value = "(hidden)" if name in self.HIDDEN_VARIABLES else variables[name]
                entries = [entry for entry in value.split(os.pathsep) if entry]
                if os.pathsep in value and len(entries) > 1:  # a list of folders: one per line
                    shown.append(f"  {name}")
                    shown += [f"      {entry}" for entry in entries]
                else:
                    shown.append(f"  {name.ljust(width)}  =  {value}")
            return shown

        from_environment = [name for name in own if name in variables and name != "PYTHONPATH"]
        added = [name for name in variables if name not in from_environment]
        lines += ["", f"From this environment's variables ({len(from_environment)})"]
        lines += show(from_environment) or ["  none"]
        lines += ["", f"Added or extended by MSL Tools ({len(added)})"]
        lines += show(added)
        lines += ["", f"Also set at the click: {LaunchLog.TIME_VARIABLE}, {LaunchLog.FILE_VARIABLE} "
                      "(they time the start).",
                  "Everything else Maya sees comes from Windows' own environment."]
        return chr(10).join(lines)

    def _show_launch_preview(self, year: str) -> None:
        TextDialog.show_for(self, f"What Maya {year} will get  ·  {self._environment}", self.launch_preview(year))

    # --- launching with a scene -------------------------------------------------------

    def _launch_scene(self, year: str, environment: str | None, scene: str) -> str:
        """Starts Maya `year` with `scene` ("" = no scene) after checking that
        both are still there. Returns "" or what went wrong, for the caller to show."""
        if str(year) not in {str(version) for version in MayaPaths.get_available_installs()}:
            return f"Maya {year} isn’t installed here any more."
        if scene and not os.path.isfile(scene):
            return f"That scene isn’t there any more: {scene}"
        if not self._launch(str(year), environment=environment, scene=scene):
            return f"Maya {year} didn’t start."
        return ""

    def _recent_scenes(self) -> list[str]:
        """Scenes of the running and the recent sessions, newest first, each once."""
        scenes = [session.scene for session in reversed(self._link.sessions())]
        scenes += [record.scene for record in self._session_history.records()]
        unique: list[str] = []
        for scene in scenes:
            if scene and scene not in unique:
                unique.append(scene)
        return unique[:self.RECENT_SCENES_SHOWN]

    def _on_version_menu(self, year: str, position) -> None:
        """Right click on a version: launch it, or open a scene in it."""
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.setToolTipsVisible(True)

        def icon(name: str, sub_folder: str = "actions") -> qt.QtGui.QIcon:
            return tinted_menu_icon(UiResources().iconManager.get_icon(name, sub_folder=sub_folder),
                                    self._menu_icon_color, self.devicePixelRatioF())

        menu.addAction(icon("play"), f"Launch Maya {year}").triggered.connect(lambda: self._launch(year))
        menu.addAction(icon("browse"), "Open a scene…").triggered.connect(lambda: self._browse_scene(year))
        preview = menu.addAction(icon("report"), "What Maya will get…")
        preview.setToolTip("Everything this launch hands to Maya: arguments, boost, every variable")
        preview.triggered.connect(lambda: self._show_launch_preview(year))
        recent = self._recent_scenes()
        if recent:
            menu.addSeparator()
            header = menu.addAction(f"Recent scenes — open in Maya {year}, {self._environment}")
            header.setEnabled(False)
            scene_icon = icon("scene")
            for scene in recent:
                action = menu.addAction(scene_icon, os.path.basename(scene))
                action.setToolTip(scene)
                action.triggered.connect(lambda _checked=False, scene=scene: self._open_scene(year, scene))
        self._version_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(position)

    def _open_scene(self, year: str, scene: str) -> None:
        error = self._launch_scene(year, None, scene)
        if error:
            ConfirmDialog.ask(self, "Scene not opened", error, choices=[("ok", "OK")], kind="warning")

    def _browse_scene(self, year: str) -> None:
        recent = self._recent_scenes()
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(
            self, f"Open a scene in Maya {year}", os.path.dirname(recent[0]) if recent else "",
            "Maya scenes (*.ma *.mb)")
        if path:
            self._open_scene(year, path)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        page = MayaGatePage()
        page.resize(500, 400)
        page.show()
