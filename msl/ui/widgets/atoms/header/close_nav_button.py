import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton


class CloseNavButton(BaseNavButton):
    """Close button — conventional destructive red hover, distinct from the
    neutral hover used by minimize/maximize."""

    HOVER_COLOR = qt.QtGui.QColor("#E81123")

    def __init__(self, icon: qt.QtGui.QIcon | None = None, parent=None):
        super().__init__(glyph="\u2715", icon=icon, parent=parent)