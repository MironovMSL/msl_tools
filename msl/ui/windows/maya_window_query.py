"""
Запросы состояния Maya main window: поиск и закрытие Qt-элементов внутри неё.
"""

import logging
import msl_tools.msl.ui.qt_bindings as qt

logger = logging.getLogger(__name__)


class MayaWindowQuery:
    """
    Утилитный класс для работы с главным окном Maya и его Qt-дочерними элементами.
    Не инстанцируется — используется как класс-реф (по аналогии с Paths, SystemInfo).
    """

    @classmethod
    def get_maya_main_window(cls):
        """
        Находит инстанс главного окна Maya.

        Returns:
            QtWidgets.QWidget | None: Главное окно Maya, либо None, если Maya недоступна.
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
        Возвращает список Qt-элементов заданного класса внутри главного окна Maya.

        Args:
            class_object (type | str): Класс, либо полный путь к классу строкой.

        Returns:
            list: Найденные элементы (пустой список, если не найдено или Maya недоступна).
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
        Закрывает и удаляет список Qt-элементов.

        Args:
            obj_list (list): Элементы для закрытия.
        """
        for obj in obj_list:
            if not cls.is_widget_valid(obj):
                continue  # объект уже мёртв или None -- штатная ситуация, не ошибка

            try:
                obj.close()
                obj.deleteLater()
            except Exception as e:
                logger.warning(f'Unable to close and delete window object. Issue: "{e}".')