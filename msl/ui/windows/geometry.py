"""
Позиционирование и геометрия окон относительно экрана.
"""

import logging

import msl_tools.msl.ui.qt_bindings as qt

logger = logging.getLogger(__name__)


def get_cursor_position(offset_x: int = 0, offset_y: int = 0):
    """
    Текущая позиция курсора мыши.

    Args:
        offset_x (int): Смещение по X в пикселях.
        offset_y (int): Смещение по Y в пикселях.

    Returns:
        QtCore.QPoint: Позиция курсора со смещением.
    """
    cursor_position = qt.QtGui.QCursor().pos()
    return qt.QtCore.QPoint(cursor_position.x() + offset_x, cursor_position.y() + offset_y)


def get_main_window_screen_number() -> int:
    """
    Номер экрана, на котором находится активное окно приложения.

    Returns:
        int: Индекс экрана, либо -1, если QApplication не инициализирован.
    """
    app = qt.QtWidgets.QApplication.instance()
    if app is None:
        logger.debug("QApplication instance not found.")
        return -1

    main_window = app.activeWindow() or qt.QtWidgets.QMainWindow()
    screen = qt.QtGui.QGuiApplication.screenAt(main_window.geometry().center())
    if screen is None:
        return -1
    return qt.QtGui.QGuiApplication.screens().index(screen)


def get_window_screen_number(window) -> int:
    """
    Номер экрана, на котором находится указанное окно.

    Args:
        window (QtWidgets.QWidget): Окно, для которого определяется экран.

    Returns:
        int: Индекс экрана, либо -1, если не найден.
    """
    app = qt.QtGui.QGuiApplication.instance()
    if not app:
        logger.warning("QGuiApplication instance is not created.")
        return -1

    widget_global_pos = window.mapToGlobal(window.rect().topLeft())
    for i, screen in enumerate(app.screens()):
        if screen.geometry().contains(widget_global_pos):
            return i
    return -1


def get_screen_center():
    """
    Центр экрана, на котором находится главное окно приложения.

    Returns:
        QtCore.QPoint: Координаты центра экрана.
    """
    screen_number = get_main_window_screen_number()
    screens = qt.QtWidgets.QApplication.screens()
    screen = screens[screen_number] if 0 <= screen_number < len(screens) else screens[0]
    center = screen.geometry().center()
    return qt.QtCore.QPoint(center.x(), center.y())


def center_window(window):
    """
    Перемещает окно в центр экрана.

    Args:
        window (QtWidgets.QWidget): Окно для центрирования.
    """
    rect = window.frameGeometry()
    rect.moveCenter(get_screen_center())
    window.move(rect.topLeft())


def resize_to_screen(
    window,
    percentage: int = 20,
    width_percentage: int | None = None,
    height_percentage: int | None = None,
):
    """
    Изменяет размер окна пропорционально размеру экрана.

    Args:
        window (QtWidgets.QWidget): Окно для изменения размера.
        percentage (int): Процент от размера экрана (0-100). По умолчанию 20.
        width_percentage (int, optional): Переопределяет percentage для ширины.
        height_percentage (int, optional): Переопределяет percentage для высоты.

    Raises:
        ValueError: Если percentage вне диапазона [0, 100].
    """
    if not 0 <= percentage <= 100:
        raise ValueError("Percentage should be between 0 and 100")

    screen = qt.QtGui.QGuiApplication.primaryScreen()
    screen_geometry = screen.availableGeometry()

    width = screen_geometry.width() * (width_percentage or percentage) / 100
    height = screen_geometry.height() * (height_percentage or percentage) / 100

    window.setGeometry(0, 0, int(width), int(height))