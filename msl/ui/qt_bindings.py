"""
The central access point to PySide6.

Namespace:
    import msl.ui.qt_bindings as ui_qt

Example:
    ui_qt.QtWidgets.QLabel("Hello")
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
        QtNetwork,
    )
    import shiboken6 as shiboken
except ImportError as e:
    logger.warning(f'PySide6 was not found in the current environment. Issue: "{e}".')
    raise


def get_pyside_version(major_only: bool = False) -> str | None:
    """
    Version of the installed PySide6.

    Args:
        major_only (bool): If True, returns only the major version ("6" instead of "6.7.1").

    Returns:
        str | None: The PySide6 version, or None if the attribute is unavailable.
    """
    version = getattr(PySide, "__version__", None)
    if not version:
        logger.debug("Could not determine the PySide6 version.")
        return None
    return version.split(".")[0] if major_only else version


if __name__ == "__main__":
    print(get_pyside_version())