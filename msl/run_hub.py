"""Standalone entry point for the desktop hub application.

Follows the same QtApplicationContext pattern used in the __main__ blocks
of frameless_dialog.py / frameless_main_window.py, rather than creating a
QApplication by hand.

In a source checkout, theme files hot-reload (edit assets/themes/*.css or
ui/theme/base.qss, save, the hub repaints). MSL_THEME_HOT_RELOAD=0/1
forces it off/on.
"""
from pathlib import Path

from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.app.application_context import QtApplicationContext
from msl_tools.msl.ui.theme import ThemeHotReloader
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.tools.desktop.registry import TOOLS
from msl_tools.msl.ui.widgets.windows.hub import HubWindow

_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with QtApplicationContext():
        if ThemeHotReloader.enabled_by_default(_REPO_ROOT):
            ThemeHotReloader(UiResources().themeManager, Resources().themeRegistry.themes_dir)
        window = HubWindow(tools=TOOLS)
        window.show()


if __name__ == "__main__":
    main()
