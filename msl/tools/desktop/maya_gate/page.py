# tools/desktop/maya_gate/page.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.core.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.tools.desktop.maya_gate.toolbar import MayaGateToolbar
from msl_tools.msl.tools.desktop.maya_gate.version_row import MayaVersionRow
from msl_tools.msl.tools.desktop.maya_gate.variable_group import CollapsibleVariableGroup
from msl_tools.msl.tools.desktop.maya_gate.variable_adder import EnvVariableAdder


class MayaGatePage(qt.QtWidgets.QWidget):
    """Maya Gate's tool page, fully assembled: pick a Maya version and a
    named environment, optionally open the advanced editor to add/edit/
    reorder/remove per-environment variables, then click a version icon
    to launch it with the selected environment's variables merged in
    (plus the always-applied "Additional" section).

    Config-backed via Resources().configsMayaMng.get_config("maya_gate")
    — one JsonConfig replaces MSL_MayaGate's separate config.ini +
    json_config.json entirely.

    Resize handling deliberately NOT ported: the original chained
    `.update_size()` calls up to resize its own standalone top-level
    window whenever a group's row count changed. That doesn't apply
    here — Maya Gate is one page inside the hub's fixed-size dialog, not
    its own window, so the advanced section is wrapped in its own
    QScrollArea instead: growing content scrolls, it never asks the hub
    to resize itself.
    """

    ENVIRONMENTS = ["<default>", "Stable", "Dev"]
    ADDITIONAL_SECTION = "Additional"
    DEFAULT_ENVIRONMENT = "Dev"

    # "_ui" holds editor state (which groups are collapsed), not variables — it's
    # never merged into a launch environment (_launch reads named sections only).
    UI_SECTION = "_ui"
    DEFAULTS = {"<default>": {}, "Stable": {}, "Dev": {}, "Additional": {},
                UI_SECTION: {"collapsed": {"environment": False, "additional": False}}}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = Resources().configsMayaMng.get_config("maya_gate", defaults=self.DEFAULTS)
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

        self._adder = EnvVariableAdder()
        collapsed = self._config[self.UI_SECTION]["collapsed"]
        self._environment_group = CollapsibleVariableGroup(
            "Maya Environment", self._environment, self._config,
            collapsed=bool(collapsed.get("environment", False)))
        self._additional_group = CollapsibleVariableGroup(
            "Additional", self.ADDITIONAL_SECTION, self._config,
            collapsed=bool(collapsed.get("additional", False)))

        advanced_container = qt.QtWidgets.QWidget()
        advanced_layout = qt.QtWidgets.QVBoxLayout(advanced_container)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(5)
        advanced_layout.addWidget(self._adder)
        advanced_layout.addWidget(self._environment_group)
        advanced_layout.addWidget(self._additional_group)
        advanced_layout.addStretch()

        self._advanced_scroll = StableScrollArea()
        self._advanced_scroll.setWidget(advanced_container)
        self._advanced_scroll.setVisible(False)

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._version_row)
        layout.addWidget(self._advanced_scroll, 1)
        # Takes the free space only while the advanced editor is hidden, so the
        # toolbar and version row stay pinned to the top instead of being
        # vertically centered (and jumping up once the editor is shown).
        self._top_pin = qt.QtWidgets.QSpacerItem(0, 0, qt.QtWidgets.QSizePolicy.Policy.Minimum,
                                                 qt.QtWidgets.QSizePolicy.Policy.Expanding)
        layout.addSpacerItem(self._top_pin)

    def _build_connections(self) -> None:
        self._toolbar.year_changed.connect(self._version_row.on_min_year_changed)
        self._toolbar.environment_changed.connect(self._on_environment_changed)
        self._toolbar.advanced_toggled.connect(self._on_advanced_toggled)
        self._version_row.clicked.connect(self._launch)

        self._adder.known_variable_added.connect(self._environment_group.add_variable)
        self._adder.custom_variable_added.connect(self._additional_group.add_variable)

        self._environment_group.collapsed_changed.connect(
            lambda state: self._save_collapsed("environment", state))
        self._additional_group.collapsed_changed.connect(
            lambda state: self._save_collapsed("additional", state))

    def _save_collapsed(self, group_key: str, collapsed: bool) -> None:
        self._config[self.UI_SECTION]["collapsed"][group_key] = collapsed

    def _on_environment_changed(self, environment: str) -> None:
        self._environment = environment
        self._environment_group.set_section(environment)

    def _on_advanced_toggled(self, visible: bool) -> None:
        self._advanced_scroll.setVisible(visible)
        policy = qt.QtWidgets.QSizePolicy.Policy
        self._top_pin.changeSize(0, 0, policy.Minimum, policy.Minimum if visible else policy.Expanding)
        self.layout().invalidate()
        self._adder.setVisible(visible)
        self._environment_group.set_advanced_visible(visible)
        self._additional_group.set_advanced_visible(visible)

    def _launch(self, year: str) -> None:
        environment_vars: dict[str, str] = {}
        environment_vars.update(dict(self._config[self._environment]))
        environment_vars.update(dict(self._config[self.ADDITIONAL_SECTION]))
        ProcessLauncher.launch_maya(version=year, environment=environment_vars)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        page = MayaGatePage()
        page.resize(500, 400)
        page.show()