from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton
import msl_tools.msl.ui.qt_bindings as qt

class MinimizeNavButton(BaseNavButton):
    def __init__(self, icon: qt.QtGui.QIcon | None = None, parent=None):
        super().__init__(glyph="\u2212", icon=icon, parent=parent)