# ui/ui_resources.py — Qt-зависимый, отдельная точка входа
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.pattern.singleton import SingletonMeta
from msl_tools.msl.ui.icon_manager import IconManager


class UiResources(metaclass=SingletonMeta):
    def __init__(self):
        self.core        = Resources()
        self.iconManager = IconManager(self.core.fsManager.icons)


if __name__ == '__main__':
    uiCore = UiResources()
    print(uiCore.iconManager.get_icon("test"))