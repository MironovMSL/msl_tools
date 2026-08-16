from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton
import msl_tools.msl.ui.qt_bindings as qt

class MaximizeNavButton(BaseNavButton):
    """Toggles between maximize and restore glyphs — the owning window is
    responsible for calling set_maximized() when its state actually changes
    (including changes triggered outside this button, e.g. double-click)."""

    _MAXIMIZE_GLYPH = "\u25a1"
    _RESTORE_GLYPH = "\u2752"

    def __init__(self, icon: qt.QtGui.QIcon | None = None,
                 restore_icon: qt.QtGui.QIcon | None = None, parent=None):
        super().__init__(glyph=self._MAXIMIZE_GLYPH, icon=icon, parent=parent)
        self._maximize_icon = icon
        self._restore_icon = restore_icon

    def set_maximized(self, is_maximized: bool) -> None:
        self.set_glyph(self._RESTORE_GLYPH if is_maximized else self._MAXIMIZE_GLYPH)
        if self._maximize_icon is not None:
            self.set_icon(self._restore_icon if is_maximized else self._maximize_icon)