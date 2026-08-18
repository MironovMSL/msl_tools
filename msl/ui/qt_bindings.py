"""
Централизованная точка доступа к PySide6.

Namespace:
    import msl.ui.qt_bindings as ui_qt

Пример:
    ui_qt.QtWidgets.QLabel("Привет")
"""

import logging

logger = logging.getLogger(__name__)

try:
    import PySide6 as PySide
    from PySide6 import (
        QtCore,
        QtGui,
        QtWidgets,
        QtSvg,
    )
    import shiboken6 as shiboken
except ImportError as e:
    logger.warning(f'PySide6 не найден в текущем окружении. Issue: "{e}".')
    raise


def get_pyside_version(major_only: bool = False) -> str | None:
    """
    Версия установленного PySide6.

    Args:
        major_only (bool): Если True, вернёт только major-версию ("6" вместо "6.7.1").

    Returns:
        str | None: Версия PySide6, либо None если атрибут недоступен.
    """
    version = getattr(PySide, "__version__", None)
    if not version:
        logger.debug("Не удалось определить версию PySide6.")
        return None
    return version.split(".")[0] if major_only else version


if __name__ == "__main__":
    print(get_pyside_version())