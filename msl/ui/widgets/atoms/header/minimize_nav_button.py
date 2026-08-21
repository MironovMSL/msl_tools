from msl_tools.msl.ui.widgets.atoms.header.base_nav_button import BaseNavButton


class MinimizeNavButton(BaseNavButton):
    def __init__(self, width: int = 36, parent=None):
        super().__init__(width, parent=parent)