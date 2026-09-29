# tools/desktop/maya_gate/page.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.tools.desktop.maya_gate.toolbar import MayaGateToolbar
from msl_tools.msl.tools.desktop.maya_gate.version_row import MayaVersionRow
from msl_tools.msl.tools.desktop.maya_gate.variable_group import CollapsibleVariableGroup
from msl_tools.msl.tools.desktop.maya_gate.variable_adder import EnvVariableAdder
from msl_tools.msl.tools.desktop.maya_gate.user_setup import UserSetupStore
from msl_tools.msl.tools.desktop.maya_gate.user_setup_tab import UserSetupTab
from msl_tools.msl.tools.desktop.maya_gate.maya_variables import VariableKind, kind_of
from msl_tools.msl.ui.widgets.compositions import BrowseMode

# How a variable's browse button behaves, by what the variable holds (maya_variables).
_BROWSE_MODE = {VariableKind.PATH_LIST: BrowseMode.APPEND,
                VariableKind.PATH: BrowseMode.REPLACE,
                VariableKind.VALUE: BrowseMode.NONE}


def _browse_mode_for(name: str) -> BrowseMode:
    return _BROWSE_MODE[kind_of(name)]


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

    Config-backed via Resources().configsMayaMng.get_config("maya_gate")
    — one JsonConfig replaces MSL_MayaGate's separate config.ini +
    json_config.json; userSetup scripts are plain .py files next to it.

    Resize handling deliberately NOT ported: the original chained
    `.update_size()` calls up to resize its own standalone top-level
    window whenever a group's row count changed. Maya Gate is one page
    inside the hub's dialog, so the Variables tab scrolls instead.
    """

    ENVIRONMENTS = ["<default>", "Stable", "Dev"]
    DEFAULT_ENVIRONMENT = "Dev"
    TOOL_NAME = "maya_gate"

    # Config layout:
    #   "<env>":             Maya variables of that environment ("Maya Variables" group)
    #   "custom": {"<env>":} its custom variables ("Custom Variables" group)
    #   "_ui":               editor state (which groups are collapsed)
    # _launch reads only the first two, for the chosen environment.
    CUSTOM_KEY = "custom"
    UI_SECTION = "_ui"
    DEFAULTS = {**{env: {} for env in ENVIRONMENTS},
                CUSTOM_KEY: {env: {} for env in ENVIRONMENTS},
                UI_SECTION: {"collapsed": {"maya": False, "custom": False}}}

    # Keys renamed with the "Maya Variables" / "Custom Variables" groups;
    # _migrate_legacy_config() moves old configs over once.
    _LEGACY_CUSTOM_KEY = "additional"
    _LEGACY_COLLAPSED_KEYS = {"environment": "maya", "additional": "custom"}

    def __init__(self, parent=None):
        super().__init__(parent)
        configs = Resources().configsMayaMng
        self._config = configs.get_config(self.TOOL_NAME, defaults=self.DEFAULTS)
        self._migrate_legacy_config()
        self._user_setup_store = UserSetupStore(configs.base_dir / self.TOOL_NAME)
        self._environment = self.DEFAULT_ENVIRONMENT

        self._build_widgets()
        self._build_layout()
        self._build_connections()

    def _build_widgets(self) -> None:
        installs = MayaPaths.get_available_installs()
        years = sorted(installs, key=int)
        min_year = years[0] if years else ""

        self._version_row = MayaVersionRow(min_year=min_year)
        self._toolbar = MayaGateToolbar(
            years=years,
            current_year=min_year,
            environments=self.ENVIRONMENTS,
            current_environment=self._environment,
        )

        self._tabs = qt.QtWidgets.QTabWidget()
        self._tabs.setDocumentMode(True)
        # Line the tab bar up with the variable groups' frames (after their gutter).
        self._tabs.setStyleSheet(
            f"QTabWidget::tab-bar {{ left: {CollapsibleVariableGroup.SELECTION_GUTTER}px; }}")
        self._tabs.addTab(self._build_variables_tab(), "Variables")
        self._user_setup_tab = UserSetupTab(self._user_setup_store, self._environment)
        self._tabs.addTab(self._indented(self._user_setup_tab), "userSetup")

    def _build_variables_tab(self) -> qt.QtWidgets.QWidget:
        self._adder = EnvVariableAdder()
        collapsed = self._config[self.UI_SECTION]["collapsed"]
        self._maya_group = CollapsibleVariableGroup(
            "Maya Variables", self._environment, self._config,
            collapsed=bool(collapsed.get("maya", False)), copy_targets=self.ENVIRONMENTS,
            browse_mode_for=_browse_mode_for)
        # Same group, pointed at the "custom" branch: its sections are the environments too.
        self._custom_group = CollapsibleVariableGroup(
            "Custom Variables", self._environment, self._config[self.CUSTOM_KEY],
            collapsed=bool(collapsed.get("custom", False)), copy_targets=self.ENVIRONMENTS,
            browse_mode_for=_browse_mode_for)

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
        layout.addWidget(self._toolbar)
        layout.addWidget(self._indented(self._version_row))
        layout.addWidget(self._tabs, 1)

    def _build_connections(self) -> None:
        self._toolbar.year_changed.connect(self._version_row.on_min_year_changed)
        self._toolbar.environment_changed.connect(self._on_environment_changed)
        self._version_row.clicked.connect(self._launch)

        self._adder.known_variable_added.connect(self._maya_group.add_variable)
        self._adder.custom_variable_added.connect(self._custom_group.add_variable)

        self._maya_group.collapsed_changed.connect(
            lambda state: self._save_collapsed("maya", state))
        self._custom_group.collapsed_changed.connect(
            lambda state: self._save_collapsed("custom", state))

    def _migrate_legacy_config(self) -> None:
        """One-time move of configs saved before the rename: "additional"
        (custom variables) -> "custom", and the "_ui" collapsed flags
        "environment"/"additional" -> "maya"/"custom". A name already present
        under the new key wins; nothing else is dropped."""
        data = self._config.data
        legacy = data.get(self._LEGACY_CUSTOM_KEY)
        collapsed = data.get(self.UI_SECTION, {}).get("collapsed", {})
        legacy_collapsed = {old: collapsed[old] for old in self._LEGACY_COLLAPSED_KEYS if old in collapsed}
        if legacy is None and not legacy_collapsed:
            return

        with self._config.batch():
            if isinstance(legacy, dict):
                custom = self._config[self.CUSTOM_KEY]
                for environment, variables in legacy.items():
                    if not isinstance(variables, dict):
                        continue
                    for name, value in variables.items():
                        if name not in custom[environment]:
                            custom[environment][name] = value
            if legacy is not None:
                del self._config[self._LEGACY_CUSTOM_KEY]
            for old, state in legacy_collapsed.items():
                self._config[self.UI_SECTION]["collapsed"][self._LEGACY_COLLAPSED_KEYS[old]] = state
                del self._config[self.UI_SECTION]["collapsed"][old]

    def _save_collapsed(self, group_key: str, collapsed: bool) -> None:
        self._config[self.UI_SECTION]["collapsed"][group_key] = collapsed

    def _on_environment_changed(self, environment: str) -> None:
        self._environment = environment
        self._maya_group.set_section(environment)
        self._custom_group.set_section(environment)
        self._user_setup_tab.set_environment(environment)

    def _launch(self, year: str) -> None:
        environment_vars: dict[str, str] = {}
        environment_vars.update(dict(self._config[self._environment]))
        environment_vars.update(dict(self._config[self.CUSTOM_KEY][self._environment]))

        self._user_setup_tab.save()  # launch with what's on screen, not the last autosave
        environment_vars = self._user_setup_store.launch_environment(self._environment, environment_vars)
        ProcessLauncher.launch_maya(version=year, environment=environment_vars)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        page = MayaGatePage()
        page.resize(500, 400)
        page.show()
