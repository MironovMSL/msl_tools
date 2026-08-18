import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton


class MaximizeNavButton(BaseNavButton):
    """Toggles between maximize/restore icons on state change (not on hover —
    that's a discrete swap driven by the actual window state, unrelated to
    BaseNavButton's hover cross-fade). The owning window calls set_maximized()
    whenever its state actually changes, including changes triggered outside
    this button (e.g. double-click on the header) — this is the single source
    of truth for the toggle, so the button is deliberately not checkable."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._maximize_icon: qt.QtGui.QIcon | None = None
        self._restore_icon: qt.QtGui.QIcon | None = None
        self._is_maximized = False

    def set_icons(self, maximize_icon: qt.QtGui.QIcon, restore_icon: qt.QtGui.QIcon | None = None) -> None:
        self._maximize_icon = maximize_icon
        self._restore_icon = restore_icon
        self._apply_current_icon()

    def set_maximized(self, is_maximized: bool) -> None:
        self._is_maximized = is_maximized
        self._apply_current_icon()

    def _apply_current_icon(self) -> None:
        icon = self._restore_icon if self._is_maximized else self._maximize_icon
        if icon is not None:
            self.set_icon(icon)