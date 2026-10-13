# ui/widgets/compositions/option_menu.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon


class _OptionRow(qt.QtWidgets.QFrame):
    """Private: one option of an OptionMenu - a picture, a title over a note, a check mark."""

    def __init__(self, action: qt.QtWidgets.QWidgetAction, title: str, note: str, picture, checked: bool, parent=None):
        super().__init__(parent)
        self._action = action
        self.setObjectName("menuOption")   # widgets.qss
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_Hover, True)   # for QSS :hover
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setProperty("checked", bool(checked))

        title_label = qt.QtWidgets.QLabel(title)
        title_label.setObjectName("menuOptionTitle")
        texts = qt.QtWidgets.QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        texts.addWidget(title_label)
        if note:
            note_label = qt.QtWidgets.QLabel(note)
            note_label.setObjectName("menuOptionNote")
            texts.addWidget(note_label)

        self._check = TintedIcon(UiResources().iconManager.get_icon("check", sub_folder="actions"), size=14)
        self._check.setObjectName("menuOptionCheck")
        policy = self._check.sizePolicy()
        policy.setRetainSizeWhenHidden(True)   # every row's text ends at the same place
        self._check.setSizePolicy(policy)
        if not checked:
            self._check.hide()

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 10, 6)
        layout.setSpacing(10)
        if picture is not None:
            picture.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)  # it only shows
            layout.addWidget(picture, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(texts, 1)
        layout.addWidget(self._check, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            menu = self.parentWidget()
            self._action.trigger()
            if isinstance(menu, qt.QtWidgets.QMenu):
                menu.close()   # a widget's own click doesn't close its menu
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _SwitchRow(qt.QtWidgets.QFrame):
    """Private: a one-line yes / no of an OptionMenu - a text and a check mark; a click
    flips it and the menu STAYS open (several are often set in one go)."""

    def __init__(self, action: qt.QtWidgets.QWidgetAction, text: str, parent=None):
        super().__init__(parent)
        self._action = action
        self.setObjectName("menuSwitch")   # widgets.qss
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("menuSwitchText")
        self._check = TintedIcon(UiResources().iconManager.get_icon("check", sub_folder="actions"), size=14)
        self._check.setObjectName("menuOptionCheck")
        policy = self._check.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self._check.setSizePolicy(policy)
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(9, 4, 10, 4)
        layout.setSpacing(10)
        layout.addWidget(label, 1)
        layout.addWidget(self._check, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        action.toggled.connect(self._show)
        self._show(action.isChecked())

    def _show(self, on: bool) -> None:
        self._check.setVisible(bool(on))
        self.setProperty("on", bool(on))
        repolish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._action.toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class OptionMenu(qt.QtWidgets.QMenu):
    """A menu whose choices can be READ: each option is a row with a picture, a
    title and a line saying what it means, the chosen one ticked and framed;
    a caption line says what the menu is about.

    For the few places where a list of long one-line items was hard to take
    in (the assistant's access in the hub's header). Plain addAction() /
    addSeparator() still work beside the rows. Rounded and themed: create
    it WITH a parent inside a styled window. Rules: OptionMenu in
    ui/theme/widgets.qss.

        menu = OptionMenu(button)
        menu.add_caption("Assistant access")
        menu.add_option("Look only", "Sees the Mayas and reads their logs", picture, checked=True).triggered.connect(...)
        menu.exec(position)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        make_rounded_popup(self)

    def add_caption(self, text: str) -> qt.QtWidgets.QLabel:
        """A quiet line of small capitals: what the options under it are about."""
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("menuCaption")
        action = qt.QtWidgets.QWidgetAction(self)
        action.setDefaultWidget(label)
        action.setEnabled(False)
        self.addAction(action)
        return label

    def add_option(self, title: str, note: str = "", picture: "qt.QtWidgets.QWidget | None" = None,
                   checked: bool = False) -> qt.QtWidgets.QWidgetAction:
        """Adds a row; its action's `triggered` fires on a click, and the menu closes.
        `picture`: any small widget shown at the row's start (it takes no clicks there)."""
        action = qt.QtWidgets.QWidgetAction(self)
        row = _OptionRow(action, title, note, picture, checked, self)
        action.setDefaultWidget(row)
        self.addAction(action)
        repolish(row)
        return action

    def add_switch(self, text: str, on: bool = False) -> qt.QtWidgets.QWidgetAction:
        """Adds a one-line yes / no; its action's `toggled(bool)` fires on a click and the
        menu stays open."""
        action = qt.QtWidgets.QWidgetAction(self)
        action.setCheckable(True)
        action.setChecked(bool(on))
        action.setDefaultWidget(_SwitchRow(action, text, self))
        self.addAction(action)
        return action


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        button = qt.QtWidgets.QPushButton("Open the menu")

        def open_menu() -> None:
            menu = OptionMenu(button)
            menu.add_caption("WHAT IT MAY DO")
            menu.add_option("Look only", "Sees what is there and reads the logs", checked=True)
            menu.add_option("Look and act", "Also runs things - shown in the log")
            menu.addSeparator()
            menu.add_option("Switch off", "Nothing can connect")
            menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

        button.clicked.connect(open_menu)
        dialog.add_case("OptionMenu", button)
        dialog.show()
