"""
Запросы состояния Maya main window: поиск и закрытие Qt-элементов внутри неё.
"""

import logging
import msl_tools.msl.ui.qt_bindings as qt

logger = logging.getLogger(__name__)


def get_maya_main_window():
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


def get_maya_main_window_qt_elements(class_object):
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

    maya_window = get_maya_main_window()
    if not maya_window:
        logger.debug("Maya window was not found.")
        return []

    return maya_window.findChildren(class_object)


def close_ui_elements(obj_list):
    """
    Закрывает и удаляет список Qt-элементов.

    Args:
        obj_list (list): Элементы для закрытия.
    """
    for obj in obj_list:
        try:
            obj.close()
            obj.deleteLater()
        except Exception as e:
            logger.debug(f'Unable to close and delete window object. Issue: "{e}".')