"""
Queries on Maya's main window: finding and closing Qt elements inside it.
"""

import logging
import msl_tools.msl.ui.qt_bindings as qt

logger = logging.getLogger(__name__)


class MayaWindowQuery:
    """
    Utility class for Maya's main window and its Qt children.
    Never instantiated — used as a class reference (like Paths, SystemInfo).
    """

    @classmethod
    def get_maya_main_window(cls):
        """
        Finds the instance of Maya's main window.

        Returns:
            QtWidgets.QWidget | None: Maya's main window, or None if Maya is unavailable.
        """
        try:
            from maya import OpenMayaUI
        except ImportError as e:
            logger.warning(f'Unable to import OpenMayaUI. Issue: "{e}".')
            return None

        ptr = OpenMayaUI.MQtUtil.mainWindow()
        if not ptr:
            logger.debug("Maya main window pointer not found.")
            return None
        return qt.shiboken.wrapInstance(int(ptr), qt.QtWidgets.QWidget)

    @classmethod
    def get_maya_main_window_qt_elements(cls, class_object):
        """
        Returns the Qt elements of the given class inside Maya's main window.

        Args:
            class_object (type | str): A class, or the class's full path as a string.

        Returns:
            list: The elements found (an empty list if none or Maya is unavailable).
        """
        if isinstance(class_object, str):
            from msl_tools.msl.core.reflection import Reflection
            class_object = Reflection.import_from_path(class_object)

        if not class_object:
            logger.debug('The requested class was not found or is "None".')
            return []

        maya_window = cls.get_maya_main_window()
        if not maya_window:
            logger.debug("Maya window was not found.")
            return []

        return maya_window.findChildren(class_object)

    @classmethod
    def is_widget_valid(cls, instance) -> bool:
        """
        Safe check for whether the underlying Qt/C++ object is still alive.
        """
        if instance is None:
            return False
        try:
            from shiboken6 import isValid
            return isValid(instance)
        except Exception as e:
            logger.warning(f"Unable to validate window instance: {e}")
            return False

    @classmethod
    def close_ui_elements(cls, obj_list):
        """
        Closes and deletes a list of Qt elements.

        Args:
            obj_list (list): The elements to close.
        """
        for obj in obj_list:
            if not cls.is_widget_valid(obj):
                continue  # the object is already dead or None -- expected, not an error

            try:
                obj.close()
                obj.deleteLater()
            except Exception as e:
                logger.warning(f'Unable to close and delete window object. Issue: "{e}".')