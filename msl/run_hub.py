"""Standalone entry point for the desktop hub application.

Follows the same QtApplicationContext pattern used in the __main__ blocks
of frameless_dialog.py / frameless_main_window.py, rather than creating a
QApplication by hand.

In a source checkout, theme files hot-reload (edit assets/themes/*.css or
ui/theme/base.qss, save, the hub repaints). MSL_THEME_HOT_RELOAD=0/1
forces it off/on.
"""
import sys
import threading
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl import __version__
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.app.application_context import QtApplicationContext
from msl_tools.msl.ui.theme import ThemeHotReloader
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.tools.desktop.registry import TOOLS
from msl_tools.msl.ui.widgets.windows.hub import HubWindow
from msl_tools.msl.ui.widgets.windows.whats_new_dialog import WhatsNewDialog

_REPO_ROOT = Path(__file__).resolve().parents[1]
# "window": the hub's last un-maximized geometry, {} until the first close
# (first start = default placement).
HUB_CONFIG_DEFAULTS = {"current_tool": "", "window": {}}


def _use_own_taskbar_icon() -> None:
    """Windows groups a script's window under python.exe — and shows the
    Python icon — unless the process has its own AppUserModelID."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("msl_tools.hub")


class _UpdateNotifier(qt.QtCore.QObject):
    """Carries "an update is available" from the check thread to the GUI thread."""

    update_available = qt.QtCore.Signal(str)  # the newer version, "1.2.3"


def _watch_for_update(window: HubWindow) -> None:
    """Checks GitHub for a newer release in the background (a network request
    must not delay the window) and, if there is one, has the hub announce it
    (header button + marked sidebar version). Silent on failure: no network
    is not worth a message."""
    notifier = _UpdateNotifier(window)
    notifier.update_available.connect(window.set_update_available)  # queued: the window lives in the GUI thread

    def check() -> None:
        try:
            info = Resources().versionManager.check_for_remote_update()
            if info.has_update:
                notifier.update_available.emit(str(info.latest_version))
        except Exception:
            pass  # includes RuntimeError: the window was closed meanwhile

    threading.Thread(target=check, daemon=True).start()


def main() -> None:
    _use_own_taskbar_icon()
    with QtApplicationContext():
        if ThemeHotReloader.enabled_by_default(_REPO_ROOT):
            ThemeHotReloader(UiResources().themeManager, Resources().themeRegistry.themes_dir)
        # The hub's own state (which tool is open) lives in configs/desktop/hub/.
        hub_config = Resources().configsDesktopHubMng.get_config("hub", defaults=HUB_CONFIG_DEFAULTS)
        icon = UiResources().iconManager.get_icon("hub", sub_folder="brand")
        window = HubWindow(tools=TOOLS, current_tool_id=hub_config["current_tool"], icon=icon,
                           footer_text=f"v{__version__}", footer_tooltip="What\u2019s new")

        def show_whats_new() -> None:
            WhatsNewDialog.show_for(window, Resources().versionManager.get_releases, __version__,
                                    Resources().releasesPageUrl)

        window.footer_clicked.connect(show_whats_new)
        window.update_clicked.connect(show_whats_new)  # its banner links to the new release

        def remember_tool(tool_id: str) -> None:
            hub_config["current_tool"] = tool_id

        window.tool_changed.connect(remember_tool)

        saved = dict(hub_config["window"])
        if {"x", "y", "width", "height"} <= saved.keys():
            window.restore_normal_geometry(
                qt.QtCore.QRect(saved["x"], saved["y"], saved["width"], saved["height"]))

        def remember_geometry() -> None:
            rect = window.normal_geometry()
            hub_config["window"] = {"x": rect.x(), "y": rect.y(),
                                    "width": rect.width(), "height": rect.height()}

        window.finished.connect(remember_geometry)  # QDialog: emitted on every close
        window.show()
        _watch_for_update(window)


if __name__ == "__main__":
    main()
