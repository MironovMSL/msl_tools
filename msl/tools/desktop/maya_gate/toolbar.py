# tools/desktop/maya_gate/toolbar.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox


class MayaGateToolbar(qt.QtWidgets.QWidget):
    """Top bar of the Maya Gate tool: pick which Maya version and which
    named environment to launch with.

    Storage-agnostic on purpose — never reads or writes config itself.
    The owning page supplies the initial selections and listens to these
    signals to persist whatever it decides is worth persisting. Ported
    from MSL_MayaGate's QCustomComboBoxWidget, minus its theme combo box
    (the window chrome already has a theme toggle) and minus its
    QCustomButton's direct config write (moved to the owner).

    "Environment:" used to be a checkable button that toggled the advanced
    editor; the editor now lives in always-visible tabs below, so it's a
    plain label.

    Signals:
        year_changed(str)
        environment_changed(str)
    """

    HEIGHT = 25

    year_changed = qt.QtCore.Signal(str)
    environment_changed = qt.QtCore.Signal(str)

    def __init__(self,
                 years: list[str], current_year: str,
                 environments: list[str], current_environment: str,
                 parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)

        self._build_widgets(years, current_year, environments, current_environment)
        self._build_layout()
        self._build_connections()

    def _build_widgets(self, years, current_year, environments, current_environment) -> None:
        self.year_combo = BaseComboBox(years, current_year, enable_wheel=False)
        self.environment_combo = BaseComboBox(environments, current_environment, enable_wheel=False)

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addStretch()
        layout.addWidget(qt.QtWidgets.QLabel("Year:"))
        layout.addWidget(self.year_combo)
        layout.addSpacing(8)
        layout.addWidget(qt.QtWidgets.QLabel("Environment:"))
        layout.addWidget(self.environment_combo)

    def _build_connections(self) -> None:
        self.year_combo.currentTextChanged.connect(self.year_changed)
        self.environment_combo.currentTextChanged.connect(self.environment_changed)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        bar = MayaGateToolbar(["2024", "2025", "2026"], "2025", ["Dev", "Stable", "<default>"], "Dev")
        bar.year_changed.connect(lambda y: print("year:", y))
        bar.environment_changed.connect(lambda e: print("env:", e))
        dialog.add_case("MayaGateToolbar", bar)
        dialog.show()
