"""
Window positioning and geometry relative to the screen.
"""

import logging

import msl_tools.msl.ui.qt_bindings as qt

logger = logging.getLogger(__name__)


def get_cursor_position(offset_x: int = 0, offset_y: int = 0):
    """
    Current position of the mouse cursor.

    Args:
        offset_x (int): X offset in pixels.
        offset_y (int): Y offset in pixels.

    Returns:
        QtCore.QPoint: Cursor position with the offset applied.
    """
    cursor_position = qt.QtGui.QCursor().pos()
    return qt.QtCore.QPoint(cursor_position.x() + offset_x, cursor_position.y() + offset_y)


def get_main_window_screen_number() -> int:
    """
    Index of the screen the application's active window is on.

    Returns:
        int: Screen index, or -1 if QApplication is not initialized.
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
    Index of the screen the given window is on.

    Args:
        window (QtWidgets.QWidget): The window whose screen is looked up.

    Returns:
        int: Screen index, or -1 if not found.
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
    Center of the screen the application's main window is on.

    Returns:
        QtCore.QPoint: Coordinates of the screen's center.
    """
    screen_number = get_main_window_screen_number()
    screens = qt.QtWidgets.QApplication.screens()
    screen = screens[screen_number] if 0 <= screen_number < len(screens) else screens[0]
    center = screen.geometry().center()
    return qt.QtCore.QPoint(center.x(), center.y())


def center_window(window):
    """
    Moves the window to the center of the screen.

    Args:
        window (QtWidgets.QWidget): The window to center.
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
    Resizes the window in proportion to the screen size.

    Args:
        window (QtWidgets.QWidget): The window to resize.
        percentage (int): Percentage of the screen size (0-100). Defaults to 20.
        width_percentage (int, optional): Overrides percentage for the width.
        height_percentage (int, optional): Overrides percentage for the height.

    Raises:
        ValueError: If percentage is outside [0, 100].
    """
    if not 0 <= percentage <= 100:
        raise ValueError("Percentage should be between 0 and 100")

    screen = qt.QtGui.QGuiApplication.primaryScreen()
    screen_geometry = screen.availableGeometry()

    width = screen_geometry.width() * (width_percentage or percentage) / 100
    height = screen_geometry.height() * (height_percentage or percentage) / 100

    window.setGeometry(0, 0, int(width), int(height))