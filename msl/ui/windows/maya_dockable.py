"""
Метакласс для докабельных Qt-окон в Maya.
"""

import logging

from msl_tools.msl.core.environment.maya.maya_environment import MayaEnvironment
from msl_tools.msl.core.fs.paths import Paths
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.windows.maya_window_query import get_maya_main_window_qt_elements, close_ui_elements

logger = logging.getLogger(__name__)


class MayaWindowMeta(type):
    """
    Метакласс Maya-окна. Делает Qt-класс докабельным в Maya (когда это возможно) и добавляет:
      - автозакрытие предыдущих окон того же класса перед открытием нового;
      - сохранение/восстановление geometry при доке;
      - Tool-modality на macOS в non-dockable режиме.

    Example:
        class ToolView(metaclass=MayaWindowMeta):
            ...
    """

    def __new__(mcs, name, bases, attrs, base_inheritance=None, dockable=True):
        if not MayaEnvironment.is_interactive():
            dockable = False

        if not base_inheritance:
            base_inheritance = (qt.QtWidgets.QDialog,)
        if not isinstance(base_inheritance, tuple):
            base_inheritance = (base_inheritance,)

        if dockable:
            from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
            bases = (MayaQWidgetDockableMixin,) + base_inheritance
        else:
            bases = base_inheritance

        new_class = type(name, bases, attrs)

        base_class_vars = vars(new_class)
        if "__init__" in base_class_vars:
            original_init = base_class_vars["__init__"]

            def custom_init(self, *args, **kwargs):
                try:
                    found_elements = get_maya_main_window_qt_elements(type(self))
                    close_ui_elements(found_elements)
                except Exception as e:
                    logger.debug(f'Unable to close previous Qt elements. Issue: "{e}".')

                if dockable and "show" in dir(self):
                    original_show = self.show

                    def custom_show(*args_show, **kwargs_show):
                        if not hasattr(self, "_original_geometry"):
                            geo, pos = self.geometry(), self.pos()
                            self._original_geometry = [pos.x(), pos.y(), geo.width(), geo.height()]
                        original_show(*args_show, **kwargs_show, dockable=True)
                        try:
                            window_parent = self.parent().parent().parent().parent().parent()
                            qt.QtWidgets.QWidget.setWindowIcon(window_parent, self.windowIcon())
                            x, y, width, height = self._original_geometry
                            window_parent.move(x, y)
                            window_parent.resize(width, height)
                        except (AttributeError, ValueError) as e:
                            logger.debug(f'Unable to restore dockable window geometry. Issue: "{e}".')

                    self.show = custom_show

                original_init(self, *args, **kwargs)

                try:
                    if Paths.is_macos() and not dockable:
                        self.setWindowFlag(qt.QtCore.Qt.WindowType.Tool, True)
                except Exception as e:
                    logger.debug(f'Unable to set MacOS Tool Modality. Issue: "{e}".')

            new_class.__init__ = custom_init

        return new_class