import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton


class CloseNavButton(BaseNavButton):
    """Close button — hover/pressed backgrounds are the conventional
    destructive red family, fixed regardless of theme (both setters are
    no-ops here on purpose). Pressed is a visibly darker red than hover,
    not just a delta — hover is already fully opaque, so any additive
    tweak on top of it would be invisible."""

    DEFAULT_HOVER_COLOR = qt.QtGui.QColor("#E81123")
    DEFAULT_PRESSED_COLOR = qt.QtGui.QColor("#C42B1C")

    def __init__(self, parent=None):
        super().__init__(parent=parent)

    def set_hover_color(self, color: qt.QtGui.QColor) -> None:
        pass

    def set_pressed_color(self, color: qt.QtGui.QColor) -> None:
        pass