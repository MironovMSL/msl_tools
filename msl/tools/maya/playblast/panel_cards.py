# tools/maya/playblast/panel_cards.py
"""The Playblast panel's small building blocks: a yes / no icon button, a card that folds."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel


class _Toggle(IconPushButton):
    """A yes / no choice as a small icon button (playblast.qss: #playblastToggle, switched on =
    the accent; the icon's color follows through the dynamic property `on`). It carries no
    words: `title` is the first line of its tooltip, `tooltip` the rest."""

    def __init__(self, title: str, icon: str, tooltip: str, parent=None):
        text = ""
        tooltip = f"{title}\n{tooltip}" if title else tooltip
        super().__init__(UiResources().iconManager.get_icon(icon, sub_folder="actions"), tooltip, parent=parent)
        self.setObjectName("playblastToggle")
        self.setCheckable(True)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        if text:
            self.setText(text)
        else:
            self.setFixedSize(28, 22)
            self.setProperty("bare", True)
        self.toggled.connect(self._follow)

    def _follow(self, *_args) -> None:
        if bool(self.property("on")) != self.isChecked():
            self.setProperty("on", self.isChecked())
            repolish(self)

    def set_checked_immediate(self, checked: bool) -> None:
        self.setChecked(bool(checked))
        self._follow()


class _Card(qt.QtWidgets.QFrame):
    """A card of the panel: a heading (chevron, icon, title, small widgets at its end) over a body
    that a click on the heading folds away. Folded, the heading says in a few words what is set
    under it (`set_summary`).

    Signals:
        toggled(bool) — the heading was clicked; True = open now.
    """

    toggled = qt.QtCore.Signal(bool)

    def __init__(self, title: str, icon: str, extras=(), parent=None):
        super().__init__(parent)
        self.setObjectName("playblastCard")
        icons = UiResources().iconManager
        self._chevrons = {True: icons.get_icon("chevron_down", sub_folder="actions"),
                          False: icons.get_icon("chevron_right", sub_folder="actions")}
        self._chevron = TintedIcon(self._chevrons[True], 10)
        mark = TintedIcon(icons.get_icon(icon, sub_folder="actions"), 14)
        mark.setObjectName("playblastCardIcon")
        heading = qt.QtWidgets.QLabel(title)
        heading.setObjectName("playblastSection")
        self._summary = ElidedLabel("", qt.QtCore.Qt.TextElideMode.ElideRight)
        self._summary.setObjectName("playblastHint")
        self._summary_text = ""
        self._header = qt.QtWidgets.QWidget()
        self._header.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._header.setToolTip("Click to show or hide these settings")
        self._header.installEventFilter(self)
        top = qt.QtWidgets.QHBoxLayout(self._header)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(self._chevron)
        top.addWidget(mark)
        top.addWidget(heading)
        top.addWidget(self._summary, 1)
        for extra in extras:
            top.addWidget(extra)
        self.body = qt.QtWidgets.QWidget()
        self.body_layout = qt.QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        box = qt.QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
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
