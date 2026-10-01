# tools/desktop/maya_gate/page.py
import os

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.atoms.tabs import BaseTabWidget
from msl_tools.msl.tools.desktop.maya_gate.toolbar import MayaGateToolbar
from msl_tools.msl.tools.desktop.maya_gate.version_row import MayaVersionRow
from msl_tools.msl.tools.desktop.maya_gate.variable_group import CollapsibleVariableGroup
from msl_tools.msl.tools.desktop.maya_gate.variable_adder import EnvVariableAdder
from msl_tools.msl.tools.desktop.maya_gate.user_setup import UserSetupStore
from msl_tools.msl.tools.desktop.maya_gate.user_setup_tab import UserSetupTab
from msl_tools.msl.tools.desktop.maya_gate.boost import BoostStore
from msl_tools.msl.tools.desktop.maya_gate.boost_tab import BoostTab
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
    TAB_KEYS = ("variables", "user_setup", "boost")  # tab order; stored by key, not index
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
        resources = Resources()
        configs = resources.configsDesktopHubMng
        self._logger = resources.logsDesktopHub.get(self.TOOL_NAME)
        self._config = configs.get_config(self.TOOL_NAME, defaults=self.DEFAULTS)
        self._migrate_legacy_config()
        self._ui = self._config[self.UI_SECTION]
        self._user_setup_store = UserSetupStore(configs.base_dir / self.TOOL_NAME)
        self._boost_store = BoostStore(configs.base_dir / self.TOOL_NAME)
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

        self._tabs = BaseTabWidget()  # sliding accent indicator
        # Line the tab bar up with the variable groups' frames (after their gutter).
        self._tabs.setStyleSheet(
            f"QTabWidget::tab-bar {{ left: {CollapsibleVariableGroup.SELECTION_GUTTER}px; }}")
        self._tabs.addTab(self._build_variables_tab(), "Variables")
        self._user_setup_tab = UserSetupTab(self._user_setup_store, self._environment)
        self._tabs.addTab(self._indented(self._user_setup_tab), "userSetup")
        self._boost_tab = BoostTab(self._boost_store, self._config[self.BOOST_KEY], self._environment, years,
                                   app_dir_for=lambda: self._launch_variables().get("MAYA_APP_DIR", ""),
                                   blocked_reason_for=lambda: BoostStore.blocked_reason(self._launch_variables()))
        self._tabs.addTab(self._indented(self._boost_tab), "Boost start")
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
        layout.addWidget(self._tabs, 1)

    def _build_connections(self) -> None:
        self._toolbar.year_changed.connect(self._version_row.on_min_year_changed)
        self._toolbar.year_changed.connect(lambda year: self._save_ui("year", year))
        self._toolbar.environment_changed.connect(self._on_environment_changed)
        self._tabs.currentChanged.connect(lambda index: self._save_ui("tab", self.TAB_KEYS[index]))
        self._version_row.clicked.connect(self._launch)

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

    def _launch_variables(self) -> dict[str, str]:
        """The current environment's variables as a launch passes them
        (Maya + custom, empty ones left out)."""
        variables: dict[str, str] = {}
        variables.update(dict(self._config[self.MAYA_KEY][self._environment]))
        variables.update(dict(self._config[self.CUSTOM_KEY][self._environment]))
        # Empty = not passed: a flag switched off, a choice not made, a blank field.
        return launch_values(variables)

    def _launch(self, year: str) -> None:
        environment_vars = self._launch_variables()
        # Boost: only when its loader can run and has a list to work from - otherwise Maya,
        # started without auto-load, would save an (almost) empty auto-load list of its own.
        boosted = (self._boost_tab.is_enabled() and not BoostStore.blocked_reason(environment_vars)
                   and bool(self._boost_store.autoload_plugins(year, environment_vars.get("MAYA_APP_DIR") or None)))
        set_here = list(environment_vars)
        if "PYTHONPATH" not in set_here:
            set_here.append("PYTHONPATH")  # always extended by the launch (msl_tools, userSetup)
        environment_vars[self.ENVIRONMENT_VARIABLE] = self._environment
        environment_vars[self.VARIABLES_VARIABLE] = os.pathsep.join(set_here)

        self._user_setup_tab.save()  # launch with what's on screen, not the last autosave
        environment_vars = self._user_setup_store.launch_environment(self._environment, environment_vars)
        arguments: list[str] = []
        if boosted:
            environment_vars, arguments = self._boost_store.prepare_launch(
                self._environment, year, self._boost_tab.skipped(), environment_vars)
        self._logger.info(f'Launching Maya {year}, environment "{self._environment}"'
                          + (" (boost start)" if boosted else ""))
        if not ProcessLauncher.launch_maya(version=year, environment=environment_vars, arguments=arguments):
            self._logger.warning(f'Maya {year} did not start (environment "{self._environment}")')


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        page = MayaGatePage()
        page.resize(500, 400)
        page.show()
