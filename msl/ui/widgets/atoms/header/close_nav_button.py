import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton


class CloseNavButton(BaseNavButton):
    """Close button. Its own class so ui/theme/widgets.qss can give it the
    conventional destructive look: a red hover (--danger), a visibly darker
    red when pressed (--danger-pressed — hover is already opaque, so a
    lighter tweak on top of it would be invisible), and a white icon on it
    (--on-danger)."""

    def __init__(self, width: int = 36, parent=None):
        super().__init__(width, parent=parent)
