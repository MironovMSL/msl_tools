# ui/widgets/compositions/folding_card.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel


class FoldingCard(qt.QtWidgets.QFrame):
    """A card of settings that folds: a heading — chevron, an icon, a title in capitals, small
    widgets at its end — over a body that a click on the heading hides. Folded, the heading says
    in a few words what is set under it (`set_summary`), so a compact window shows only what is
    being worked on.

        card = FoldingCard("FIND & REPLACE", icon, extras=[case_toggle])
        card.body_layout.addWidget(...)

    Looks: ui/theme/widgets.qss (`QFrame#foldingCard`, `#foldingCardTitle`, `#foldingCardSummary`,
    `TintedIcon#foldingCardIcon`).

    Signals:
        toggled(bool) — the heading was clicked; True = open now.
    """

    toggled = qt.QtCore.Signal(bool)

    def __init__(self, title: str, icon: "qt.QtGui.QIcon | None" = None, extras=(), parent=None):
        super().__init__(parent)
        self.setObjectName("foldingCard")
        from msl_tools.msl.ui.ui_resources import UiResources
        icons = UiResources().iconManager
        self._chevrons = {True: icons.get_icon("chevron_down", sub_folder="actions"),
                          False: icons.get_icon("chevron_right", sub_folder="actions")}
        self._chevron = TintedIcon(self._chevrons[True], 10)
        self._chevron.setObjectName("foldingCardChevron")
        heading = qt.QtWidgets.QLabel(title)
        heading.setObjectName("foldingCardTitle")
        self._summary = ElidedLabel("", qt.QtCore.Qt.TextElideMode.ElideRight)
        self._summary.setObjectName("foldingCardSummary")
        self._summary_text = ""
        self._header = qt.QtWidgets.QWidget()
        self._header.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._header.setToolTip("Click to show or hide")
        self._header.installEventFilter(self)
        top = qt.QtWidgets.QHBoxLayout(self._header)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(self._chevron)
        if icon is not None and not icon.isNull():
            mark = TintedIcon(icon, 14)
            mark.setObjectName("foldingCardIcon")
            top.addWidget(mark)
        top.addWidget(heading)
        top.addWidget(self._summary, 1)
        for extra in extras:
            top.addWidget(extra)
        self.body = qt.QtWidgets.QWidget()
        self.body_layout = qt.QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        box = qt.QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 8)
        box.setSpacing(6)
        box.addWidget(self._header)
        box.addWidget(self.body)
        self._open = True

    def is_open(self) -> bool:
        return self._open

    def set_open(self, opened: bool) -> None:
        self._open = bool(opened)
        self.body.setVisible(self._open)
        self._chevron.set_icon(self._chevrons[self._open])
        self._summary.setText("" if self._open else self._summary_text)
        # a folded card keeps a little room under its heading otherwise
        self.layout().setContentsMargins(8, 6, 8, 8 if self._open else 6)

    def set_summary(self, text: str) -> None:
        self._summary_text = text
        self._summary.setText("" if self._open else text)

    def eventFilter(self, watched, event) -> bool:
        if (watched is self._header and event.type() == qt.QtCore.QEvent.Type.MouseButtonRelease
                and event.button() == qt.QtCore.Qt.MouseButton.LeftButton):
            self.set_open(not self._open)
            self.toggled.emit(self._open)
            return True
        return super().eventFilter(watched, event)
