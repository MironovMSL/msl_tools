"""
Контекст-менеджер для жизненного цикла QApplication.
"""

import logging
import sys

from msl_tools.msl.core.environment.maya.maya_environment import MayaEnvironment
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.windows.maya_window_query import get_maya_main_window

logger = logging.getLogger(__name__)


class QtApplicationContext:
    """
    Context manager для QtWidgets.QApplication.

    Usage:
        with QtApplicationContext() as context:
            view = SomeWindow(parent=context.get_parent())

    Attributes:
        app (QtWidgets.QApplication | None): Инстанс QApplication (только вне интерактивной Maya).
    """

    def __init__(self):
        self.app = None
        self.parent = None

    def is_in_interactive_maya(self) -> bool:
        """True, если скрипт выполняется внутри интерактивной Maya (не mayapy/batch)."""
        return MayaEnvironment.is_interactive()

    def get_parent(self):
        """Maya main window, если внутри Maya, иначе None."""
        return self.parent

    def __enter__(self):
        if self.is_in_interactive_maya():
            self.parent = get_maya_main_window()
        else:
            logger.debug("Running Qt outside interactive Maya. Initializing QApplication.")
            self.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication(sys.argv)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            logger.warning(f'Exception inside QtApplicationContext: "{exc_value}".')
        if self.app and not self.is_in_interactive_maya():
            sys.exit(self.app.exec())
        return False