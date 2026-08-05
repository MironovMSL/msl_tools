# Tool Version
__version_tuple__ = (0, 0, 1)
__version_suffix__ = ' alpha'
__version__ = '.'.join(str(n) for n in __version_tuple__) + __version_suffix__

from msl_tools.msl.ui.app.application_context import QtApplicationContext
from msl_tools.msl.tools.maya.installer.installer_view import InstallerView
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery

window = None # Глобальная переменная для хранения текущего экземпляра окна

def launcher_entry_point():
    global window

    with QtApplicationContext() as content:
        MayaWindowQuery.close_ui_elements([window])
        window = InstallerView(version=__version__, parent=content.get_parent())
        window.show()


if  __name__ == '__main__':
    launcher_entry_point()