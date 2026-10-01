# tools/desktop/maya_gate/variable_adder.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import adopt_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons import IconPushButton
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.scrollbars import SlimScrollBar
from msl_tools.msl.tools.desktop.maya_gate import maya_variables


class EnvVariableAdder(qt.QtWidgets.QWidget):
    """Row for adding a new environment variable to Maya Gate's config —
    either pick a known Maya variable (added to whichever environment is
    currently selected) or type a custom one (added to the CURRENT
    environment's "Custom Variables" group).

    That known-vs-custom split isn't just labeling — it's real routing:
    in the original (MSL_MayaGate's EnvVariableAdder +
    MayaLauncher.add_new_variable), which target section a new variable
    goes to depends on which button/field it came from. Kept as two
    separate signals here so that routing lives with the caller instead
    of being re-derived from a string tag.

    The known-variables dropdown is the catalog of maya_variables.py:
    listed by GROUP under small headers (not pickable), each variable with
    its description as a tooltip. The list opens as wide as its longest
    name, wider than the field; typing still filters across all groups
    (the completer, with the same tooltips).

    Storage-agnostic — never touches config itself. Icon-file buttons
    (add1.svg etc.) replaced with a plain "+" — no matching assets in
    msl_tools yet (same reasoning as EnvVarRow's hover panels).

    Signals:
        known_variable_added(str) — name picked from the known-variables
            dropdown; the caller adds it to the CURRENT environment.
        custom_variable_added(str) — freeform name typed by the user; the
            caller adds it to the current environment's "Custom Variables" group.
    """

    KNOWN_VARIABLES = maya_variables.KNOWN_VARIABLES  # single source: maya_variables.py

    HEIGHT = 25
    COMBO_WIDTH = 170
    POPUP_EXTRA_WIDTH = 28   # list padding + the scroll bar's column
    HEADER_FONT_DELTA = -1   # group headers: a point smaller, semibold
    LINE_EDIT_WIDTH = 170
    ADD_BUTTON_SIZE = qt.QtCore.QSize(24, 22)  # field height, so "+" lines up with its field

    known_variable_added = qt.QtCore.Signal(str)
    custom_variable_added = qt.QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self._build_widgets()
        self._build_layout()
        self._build_connections()

    def _build_widgets(self) -> None:
        self.add_known_button = self._add_button("Add this Maya variable")

        # BaseComboBox: styled rows, slim scroll bar, animated arrow.
        self.known_combo = BaseComboBox([], "")
        self._fill_known_combo()
        self.known_combo.setFixedWidth(self.COMBO_WIDTH)
        self.known_combo.setCurrentIndex(-1)
        self.known_combo.setEditable(True)
        self.known_combo.lineEdit().setPlaceholderText("Maya variable…")
        self.known_combo.setMaxVisibleItems(18)

        # Names only (no group headers), each with its description as a tooltip.
        completer_model = qt.QtGui.QStandardItemModel(self.known_combo)
        for name in self.KNOWN_VARIABLES:
            item = qt.QtGui.QStandardItem(name)
            item.setToolTip(maya_variables.spec_of(name).description)
            completer_model.appendRow(item)
        completer = qt.QtWidgets.QCompleter(completer_model, self.known_combo)
        completer.setCaseSensitivity(qt.QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(qt.QtCore.Qt.MatchFlag.MatchContains)
        self.known_combo.setCompleter(completer)
        # Typing opens the completer's own list, created parentless (so unstyled,
        # native white even in the dark theme). Adopted by the combo box it gets
        # the window QSS — the same `QComboBox QAbstractItemView` look as the
        # drop-down — and the same slim scroll bar.
        popup = adopt_popup(completer.popup(), self.known_combo)
        popup.setItemDelegate(qt.QtWidgets.QStyledItemDelegate(popup))
        popup.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical))

        # Both lists open as wide as the longest name: the field is narrower than most of them.
        metrics = self.known_combo.fontMetrics()
        list_width = max(metrics.horizontalAdvance(name) for name in self.KNOWN_VARIABLES) + self.POPUP_EXTRA_WIDTH
        self.known_combo.view().setMinimumWidth(max(list_width, self.COMBO_WIDTH))
        popup.setMinimumWidth(max(list_width, self.COMBO_WIDTH))

        self.custom_line_edit = qt.QtWidgets.QLineEdit()
        self.custom_line_edit.setPlaceholderText("Custom variable…")
        self.custom_line_edit.setFixedWidth(self.LINE_EDIT_WIDTH)

        self.add_custom_button = self._add_button("Add this custom variable")

    def _fill_known_combo(self) -> None:
        """The catalog, group by group: a header row (disabled, so it can't
        be picked and the keyboard skips it), then the group's variables."""
        model = self.known_combo.model()
        header_font = self.known_combo.font()
        header_font.setPointSize(max(header_font.pointSize() + self.HEADER_FONT_DELTA, 6))
        header_font.setWeight(qt.QtGui.QFont.Weight.DemiBold)
        header_font.setLetterSpacing(qt.QtGui.QFont.SpacingType.AbsoluteSpacing, 0.5)
        for title, specs in maya_variables.GROUPS:
            self.known_combo.addItem(title.upper())
            header = model.item(self.known_combo.count() - 1)
            header.setFlags(qt.QtCore.Qt.ItemFlag.NoItemFlags)  # base.qss: ::item:disabled = dimmed
            header.setFont(header_font)
            for spec in specs:
                self.known_combo.addItem(spec.name)
                self.known_combo.setItemData(self.known_combo.count() - 1, spec.description,
                                             qt.QtCore.Qt.ItemDataRole.ToolTipRole)

    def _add_button(self, tooltip: str) -> IconPushButton:
        """Framed "+" button (a regular button: a flat one didn't read as clickable)."""
        button = IconPushButton(UiResources().iconManager.get_icon("add", sub_folder="actions"),
                                tooltip, fallback_text="+")
        button.setFixedSize(self.ADD_BUTTON_SIZE)
        return button

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(self.add_known_button)
        layout.addWidget(self.known_combo)
        layout.addStretch()
        layout.addWidget(self.custom_line_edit)
        layout.addWidget(self.add_custom_button)

    def _build_connections(self) -> None:
        self.add_known_button.clicked.connect(self._on_add_known)
        self.known_combo.lineEdit().returnPressed.connect(self._on_add_known)
        self.add_custom_button.clicked.connect(self._on_add_custom)
        self.custom_line_edit.returnPressed.connect(self._on_add_custom)

    def _on_add_known(self) -> None:
        var = self.known_combo.currentText()
        if var and var in self.KNOWN_VARIABLES:
            self.known_variable_added.emit(var)

    def _on_add_custom(self) -> None:
        var = self.custom_line_edit.text()
        if var:
            self.custom_variable_added.emit(var)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        adder = EnvVariableAdder()
        adder.known_variable_added.connect(lambda v: print("known:", v))
        adder.custom_variable_added.connect(lambda v: print("custom:", v))
        dialog.add_case("EnvVariableAdder", adder)
        dialog.show()