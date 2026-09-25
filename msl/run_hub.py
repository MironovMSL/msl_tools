"""Standalone entry point for the desktop hub application.

Follows the same QtApplicationContext pattern used in the __main__ blocks
of frameless_dialog.py / frameless_main_window.py, rather than creating a
QApplication by hand — inferred from those examples, not yet run against
the real QtApplicationContext, so worth a quick smoke test.
"""

from msl_tools.msl.ui.app.application_context import QtApplicationContext
from msl_tools.msl.tools.desktop.registry import TOOLS
from msl_tools.msl.ui.widgets.windows.hub import HubWindow


def main() -> None:
    with QtApplicationContext():
        window = HubWindow(tools=TOOLS)
        window.show()


if __name__ == "__main__":
    main()