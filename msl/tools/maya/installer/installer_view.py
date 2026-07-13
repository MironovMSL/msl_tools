"""
View тула установки. Чистый UI без бизнес-логики.
"""

from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.windows.maya_dockable import MayaWindowMeta

import msl_tools.msl.ui.qt_bindings as qt


class InstallerView(metaclass=MayaWindowMeta):

    NAME   = 'MSL Installer'

    CORE    = Resources()
    UI_CORE = UiResources()
    CONFIG  = CORE.configManager.get_config(NAME, ".ini")
    LOG     = CORE.configManager.get_config(NAME)

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.setWindowTitle(self.NAME)


