"""
Startup entry point of msl_tools inside Maya.

Deliberately light: importing this module has no side effects and pulls in no Qt and no
`Resources`. Everything heavy is imported lazily inside functions.

The entry point is trigger-agnostic - `bootstrap()` does not care who calls it. Today it is
a line in userSetup.py; later MSL_MayaLauncher can start Maya with arguments/environment
and call the very same function.
"""

import logging

logger = logging.getLogger(__name__)


def bootstrap() -> bool:
    """Initializes msl_tools in the current Maya session (currently: creates the main menu).

    Safe to call repeatedly (the menu is rebuilt, never duplicated). Never raises.

    Returns:
        True if the menu build was scheduled, False if there was nothing to do or it failed.
    """
    try:
        from msl_tools.msl.core.environment.maya.maya_environment import MayaEnvironment

        if not MayaEnvironment.is_running():
            logger.warning("Unable to bootstrap. Maya is not running in this process.")
            return False
        return rebuild_menu()
    except Exception as e:
        logger.warning(f'Unable to bootstrap. Issue: "{e}".', exc_info=True)
        return False


def rebuild_menu() -> bool:
    """Schedules (re)creation of the MSL main menu on Maya's idle loop.

    Deferred on purpose: at userSetup time the Maya main window may not exist yet, and a
    menu item (e.g. "Rebuild Menu") must not delete its own menu from inside its command.

    Returns:
        True if the build was scheduled, False on failure.
    """
    try:
        import maya.utils
        maya.utils.executeDeferred(_load_main_menu)
        return True
    except Exception as e:
        logger.warning(f'Unable to schedule menu build. Issue: "{e}".')
        return False


def _load_main_menu() -> bool:
    """Builds the MSL main menu. Runs deferred; skipped in batch / mayapy sessions.

    The interactive check lives here (not in `bootstrap`) because it must run once Maya's UI
    is fully loaded - the state query is unreliable during the very first startup moments.
    """
    try:
        from msl_tools.msl.core.environment.maya.maya_environment import MayaEnvironment

        if not MayaEnvironment.is_interactive():
            logger.debug("Skipping menu build. Maya is not interactive.")
            return False

        from msl_tools.msl.core.maya_menu import MayaMenuBuilder
        from msl_tools.msl.tools.maya.menu_definition import MslMenuDefinition

        menu = MayaMenuBuilder().build(MslMenuDefinition.build())
        if menu is not None:
            print("MSL: main menu loaded.")  # TODO remove once startup is verified
        return menu is not None
    except Exception as e:
        logger.warning(f'Unable to build main menu. Issue: "{e}".', exc_info=True)
        return False