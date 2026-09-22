"""
Temporary development actions for the MSL menu ("Dev" sub-menu). Safe to delete.
"""

import sys
from pathlib import Path

from msl_tools.msl.core.environment.maya.maya_environment import MayaEnvironment


def print_hello() -> None:
    """Prints a test message to the Script Editor."""
    print("MSL: hello from the Maya menu!")


def print_environment() -> None:
    """Prints basic facts about the running Maya session and where the package is loaded from."""
    print("MSL environment:")
    print(f"  Maya version : {MayaEnvironment.get_version()}")
    print(f"  Maya state   : {MayaEnvironment.get_state().value}")
    print(f"  Python       : {sys.version.split()[0]}")
    print(f"  Package path : {Path(__file__).resolve().parents[2]}")  # .../msl


def reload_package() -> None:
    """Drops msl_tools from sys.modules and rebuilds the MSL menu, so edits made to .py files
    on disk since Maya started take effect without restarting Maya.

    Only affects code reached *after* this runs (menu clicks, newly opened windows). An already
    open window (e.g. the Installer, if it's open right now) keeps running the code it was built
    from - close and reopen it to pick up its own edits. See module_reloader.unload_package for
    the mechanism and its caveats.
    """
    from msl_tools.msl.core.reflection.module_reloader import unload_package

    removed = unload_package("msl_tools")
    print(f"MSL: reloaded {len(removed)} module(s).")

    from msl_tools.msl.startup import rebuild_menu  # re-imported fresh, see unload_package() above
    rebuild_menu()