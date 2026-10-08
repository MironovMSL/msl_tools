# tools/desktop/maya_gate/toolbar.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.segmented import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources


class MayaGateToolbar(qt.QtWidgets.QWidget):
    """Top bar of the Maya Gate tool: the environment to work in and launch
    with (left — the page's main context: tabs, variable groups and the
    launch all follow it), and which Maya versions the row below shows
    (right — "From <year>": versions from that year on).

    The environment is a SegmentedControl — every environment visible and
    one click away; the year stays a combo box (a filter, set rarely).

    Storage-agnostic on purpose — never reads or writes config itself.
    The owning page supplies the initial selections and listens to these
    signals to persist whatever it decides is worth persisting. Ported
    from MSL_MayaGate's QCustomComboBoxWidget, minus its theme combo box
    (the window chrome already has a theme toggle) and minus its
    QCustomButton's direct config write (moved to the owner).

    Beside the environment: "EN" — keep the keyboard English while Maya is the
    active window (tools/maya/keyboard_keeper.py), the CURRENT environment's
    setting, one of ENGLISH_MODES: a click switches it off / on, a right click
    offers "English only" (no other layout inside Maya at all — a lock icon).
    `set_english()` shows another environment's without a signal.

    Signals:
        year_changed(str)
        environment_changed(str)
        english_changed(str)   one of ENGLISH_MODES
    """

    ENGLISH_OFF, ENGLISH_ON, ENGLISH_ONLY = "off", "on", "only"
    ENGLISH_MODES = (ENGLISH_OFF, ENGLISH_ON, ENGLISH_ONLY)

    HEIGHT = 26

    year_changed = qt.QtCore.Signal(str)
    environment_changed = qt.QtCore.Signal(str)
    english_changed = qt.QtCore.Signal(str)

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
        self.year_combo.setToolTip("Show Maya versions from this year on")
        self.environment_switch = SegmentedControl(environments, current_environment)
        self.environment_switch.setToolTip("Environment to edit and launch Maya with")
        self.english_toggle = IconPushButton(UiResources().iconManager.get_icon("keyboard", sub_folder="actions"),
                                             fallback_text="EN")
        self.english_toggle.setText("EN")
        self.english_toggle.setObjectName("gateEnglish")
        self.english_toggle.setCheckable(True)
        self.english_toggle.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.english_toggle.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.english_toggle.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._english_mode = self.ENGLISH_OFF
        self._english_icons = {
            False: UiResources().iconManager.get_icon("keyboard", sub_folder="actions"),
            True: UiResources().iconManager.get_icon("lock", sub_folder="actions"),
        }

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(self._caption("Environment"))
        layout.addSpacing(2)
        layout.addWidget(self.environment_switch)
        layout.addSpacing(4)
        layout.addWidget(self.english_toggle)
        layout.addStretch()
        layout.addWidget(self._caption("From"))
        layout.addSpacing(2)
        layout.addWidget(self.year_combo)

    @staticmethod
    def _caption(text: str) -> qt.QtWidgets.QLabel:
        """Dimmed label in front of a control (maya_gate.qss: QLabel#toolbarCaption)."""
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("toolbarCaption")
        return label

    def _build_connections(self) -> None:
        self.year_combo.currentTextChanged.connect(self.year_changed)
        self.environment_switch.current_changed.connect(self.environment_changed)
        self.english_toggle.clicked.connect(self._on_english_clicked)
        self.english_toggle.customContextMenuRequested.connect(self._on_english_menu)

    def set_english(self, mode: str) -> None:
        """Shows an environment's "English in Maya" setting (no signal)."""
        self._english_mode = mode if mode in self.ENGLISH_MODES else self.ENGLISH_ON
        self._show_english()

    def english_mode(self) -> str:
        return self._english_mode

    def _pick_english(self, mode: str) -> None:
        if mode != self._english_mode:
            self.set_english(mode)
            self.english_changed.emit(mode)
        else:
            self._show_english()

    def _on_english_clicked(self, *_args) -> None:
        # a click: off <-> on (an "English only" one goes off; the menu brings it back)
        self._pick_english(self.ENGLISH_ON if self._english_mode == self.ENGLISH_OFF else self.ENGLISH_OFF)

    def _on_english_menu(self, position) -> None:
        menu = qt.QtWidgets.QMenu(self)
        group = qt.QtGui.QActionGroup(menu)
        for mode, text in ((self.ENGLISH_OFF, "Off — Maya keeps whatever layout there is"),
                           (self.ENGLISH_ON, "English while Maya is active — switching by hand works"),
                           (self.ENGLISH_ONLY, "English only — no other layout inside Maya")):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(mode == self._english_mode)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, m=mode: self._pick_english(m))
        menu.exec(self.english_toggle.mapToGlobal(position))

    def _show_english(self, *_args) -> None:
        mode = self._english_mode
        on = mode != self.ENGLISH_OFF
        self.english_toggle.setChecked(on)
        self.english_toggle.set_source_icon(self._english_icons[mode == self.ENGLISH_ONLY])
        heading = {self.ENGLISH_OFF: "English in Maya — off",
                   self.ENGLISH_ON: "English in Maya — ON",
                   self.ENGLISH_ONLY: "English ONLY in Maya"}[mode]
        detail = ("\nInside a Maya started in this environment the keyboard is ALWAYS English: a switch to\n"
                  "another layout (Alt+Shift, Win+Space) is turned back at once." if mode == self.ENGLISH_ONLY else
                  "\nWhile a Maya started in this environment is the active window, the keyboard is English\n"
                  "(Maya's hotkeys don't work on a Cyrillic layout). Switching by hand inside Maya still works.")
        self.english_toggle.setToolTip(
            heading + detail + "\nLeaving Maya gives back the layout that was there. Takes effect at the next launch."
            "\nClick: on / off · right click: English only")
        if bool(self.english_toggle.property("on")) != on:
            self.english_toggle.setProperty("on", on)
            repolish(self.english_toggle)


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
