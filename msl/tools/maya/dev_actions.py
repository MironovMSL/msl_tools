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