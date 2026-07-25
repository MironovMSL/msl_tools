"""
Метакласс для управления Maya Qt окнами.

Features:
    - Maya dockable windows
    - auto close previous windows
    - singleton / unique / multi lifecycle
    - restore geometry after docking
    - macOS Tool flag
"""

import logging

from msl_tools.msl.core.environment.maya.maya_environment import MayaEnvironment
from msl_tools.msl.core.fs.paths import Paths
from msl_tools.msl.core.fs.system_info import SystemInfo
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery
import msl_tools.msl.ui.qt_bindings as qt


_QtMetaBase = type(qt.QtWidgets.QWidget)
logger = logging.getLogger(__name__)


class MayaWindowMeta(_QtMetaBase):
    def __new__(mcs, name, bases, attrs, *, base_inheritance=None, dockable=True, window_mode="singleton"):

        maya_available = MayaEnvironment.is_interactive()
        # ---------------------------------------
        # Maya standalone / batch
        # ---------------------------------------
        if not maya_available:
            dockable = False
        # ---------------------------------------
        # Base Qt class
        # ---------------------------------------

        if base_inheritance is None:
            base_inheritance = qt.QtWidgets.QDialog

        if not isinstance(base_inheritance, tuple):
            base_inheritance = (base_inheritance,)

        # ---------------------------------------
        # Maya Dockable
        # ---------------------------------------

        if dockable:
            from maya.app.general.mayaMixin import (MayaQWidgetDockableMixin)
            bases = (MayaQWidgetDockableMixin,) + base_inheritance

        else:
            bases = base_inheritance

        # ---------------------------------------
        # Create class
        # ---------------------------------------

        new_class = super().__new__(mcs, name, bases, attrs)

        # Store settings
        new_class._window_mode = window_mode
        new_class._window_instance = None
        new_class._window_instances = []

        # ---------------------------------------
        # Wrap init
        # ---------------------------------------
        original_init = new_class.__init__

        def custom_init(self, *args, **kwargs):

            # -------------------------------
            # Close previous Maya windows
            # -------------------------------
            if maya_available and window_mode == "unique":
                try:
                    old_windows = (MayaWindowQuery.get_maya_main_window_qt_elements(type(self)))
                    MayaWindowQuery.close_ui_elements(old_windows)
                except Exception as e:
                    logger.warning(f"Unable to close old windows: {e}")

            # -------------------------------
            # Real init FIRST — the underlying
            # Qt/C++ object must exist before we
            # touch window flags, geometry, etc.
            # -------------------------------
            original_init(self, *args, **kwargs)

            # -------------------------------
            # macOS Tool window
            # -------------------------------
            try:
                if SystemInfo.is_macos() and not dockabl:
                    self.setWindowFlag(qt.QtCore.Qt.WindowType.Tool, True)
            except Exception as e:
                logger.warning(f"Unable to set Tool flag: {e}")

        new_class.__init__ = custom_init

        # ---------------------------------------
        # Wrap show
        # ---------------------------------------
        if dockable and hasattr(new_class, "show"):
            original_show = new_class.show

            def custom_show(self, *args, **kwargs):

                if not hasattr(self, "_original_geometry"):
                    geo = self.geometry()
                    pos = self.pos()

                    self._original_geometry = [pos.x(), pos.y(), geo.width(), geo.height()]

                kwargs["dockable"] = True

                original_show(self, *args, **kwargs)

                try:
                    maya_window = mcs._find_maya_main_window(self)
                    if maya_window is None:
                        raise RuntimeError("Maya main window not found in parent chain")

                    qt.QtWidgets.QWidget.setWindowIcon(maya_window, self.windowIcon())

                    x, y, w, h = (self._original_geometry)

                    maya_window.move(x, y)
                    maya_window.resize(w, h)

                except Exception as e:
                    logger.warning(f"Unable to restore geometry: {e}")

            new_class.show = custom_show

        return new_class

    # ==================================================
    # Helpers
    # ==================================================

    @staticmethod
    def _find_maya_main_window(widget):
        """
        Walk up the parent chain looking for the workspaceControl / dock
        host QMainWindow, instead of relying on a fixed number of
        .parent() hops (which breaks whenever Maya's docking wrapper
        structure changes between versions or dock/float states).
        """
        current = widget.parent()
        while current is not None:
            if isinstance(current, qt.QtWidgets.QMainWindow):
                return current
            current = current.parent()
        return None

    @staticmethod
    def _is_valid(instance):
        """
        Safe check for whether the underlying Qt/C++ object is still alive.
        QWidget has no isDestroyed() method — that was a bug. shiboken6's
        isValid() is the correct way to check this in PySide6.
        """
        if instance is None:
            return False
        try:
            from shiboken6 import isValid
            return isValid(instance)
        except Exception as e:
            logger.warning(f"Unable to validate window instance: {e}")
            return False

    # ==================================================
    # Instance manager
    # ==================================================

    def get_instance(cls, *args, **kwargs):
        mode = cls._window_mode

        # -----------------------------------
        # Singleton
        # -----------------------------------
        if mode == "singleton":
            if not MayaWindowMeta._is_valid(cls._window_instance):
                cls._window_instance = cls(*args, **kwargs)
            return cls._window_instance

        # -----------------------------------
        # Unique
        # -----------------------------------
        if mode == "unique":

            if MayaWindowMeta._is_valid(cls._window_instance):
                cls._window_instance.close()
                cls._window_instance.deleteLater()

            cls._window_instance = cls(*args, **kwargs)
            return cls._window_instance

        # -----------------------------------
        # Multi
        # -----------------------------------
        if mode == "multi":
            instance = cls(*args, **kwargs)
            cls._window_instances.append(instance)

            def _on_destroyed(_=None, cls=cls, instance=instance):
                if instance in cls._window_instances:
                    cls._window_instances.remove(instance)

            instance.destroyed.connect(_on_destroyed)
            return instance

        raise ValueError(f"Unknown window mode: {mode}")

    def show_window(cls, *args, **kwargs):
        window = cls.get_instance(*args, **kwargs)

        if window.isHidden():
            window.show()
        else:
            window.raise_()
            window.activateWindow()
        return window




class MayaWindowMetaOld(type):
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