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
from msl_tools.msl.core.installer.hub_updater import HubUpdater, UpdateResult
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.version.version import Version
from msl_tools.msl.ui.app.application_context import QtApplicationContext
from msl_tools.msl.ui.theme import ThemeHotReloader
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.tools.desktop.registry import TOOLS
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.hub import HubWindow
from msl_tools.msl.ui.widgets.windows.whats_new_dialog import WhatsNewDialog

_REPO_ROOT = Path(__file__).resolve().parents[1]
# "window": the hub's last un-maximized geometry, {} until the first close
# (first start = default placement).
HUB_CONFIG_DEFAULTS = {"current_tool": "", "window": {}}
UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000  # a hub left open for days still learns about a new release


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
    must not delay the window) — on start, then every UPDATE_CHECK_INTERVAL_MS
    — and, if there is one, has the hub announce it (header button + marked
    sidebar version). Silent on failure: no network is not worth a message."""
    notifier = _UpdateNotifier(window)
    notifier.update_available.connect(window.set_update_available)  # queued: the window lives in the GUI thread
    announced = []  # versions already announced (one announcement per version)

    def check() -> None:
        try:
            info = Resources().versionManager.check_for_remote_update()
            version = str(info.latest_version) if info.has_update else ""
            if version and version not in announced:
                announced.append(version)
                notifier.update_available.emit(version)
        except Exception:
            pass  # includes RuntimeError: the window was closed meanwhile

    def start_check() -> None:
        threading.Thread(target=check, daemon=True).start()

    start_check()
    timer = qt.QtCore.QTimer(window)
    timer.setInterval(UPDATE_CHECK_INTERVAL_MS)
    timer.timeout.connect(start_check)
    timer.start()


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

        # One-click update (core/installer/hub_updater.py): "What's new" downloads + checks the
        # release, then a helper process swaps it in while the hub is closed and starts it again.
        updater = HubUpdater(Resources().fsManager.ROOT_DIR, Resources().releaseArchiveUrl,
                             logger=Resources().logsDesktopHub.get("updater"))
        last_update = updater.take_result()  # what the helper did, if this start follows an update

        def prepare_update(note, progress) -> None:
            updater.prepare(note.tag, note.version, progress)

        def show_whats_new(notice: str = "") -> None:
            prepared = WhatsNewDialog.show_for(
                window, Resources().versionManager.get_releases, __version__, Resources().releasesPageUrl,
                update_handler=None if updater.blocked_reason() else prepare_update,
                update_blocked_reason=updater.blocked_reason() or "", notice=notice,
                can_install=lambda note: updater.can_install(note.version))  # older ones too: a way back
            if prepared is None:
                return
            if updater.start_apply(prepared.version, __version__):
                window.close()  # stores the window placement (finished)
                qt.QtWidgets.QApplication.quit()
            else:
                ConfirmDialog.ask(window, "Update", "The update could not be started.",
                                  details="See the log in logs/desktop/updater.", kind="warning")

        def report_update(result: UpdateResult) -> None:
            if result.succeeded:
                try:
                    went_back = Version.compare(result.version, result.previous_version) == Version.SMALLER
                except ValueError:
                    went_back = False
                show_whats_new(notice=f"Back on version {result.version}" if went_back
                               else f"Updated to {result.version}")
                return
            restored = result.status == "rolled_back"
            choice = ConfirmDialog.ask(
                window, "Update",
                f"Version {result.version} could not be installed"
                + (" \u2014 the previous version was restored." if restored else "."),
                details=result.message.strip().splitlines()[0] if result.message.strip() else None,
                choices=[("ok", "OK"), ("log", "Show the log")], kind="warning")
            if choice == "log":
                ProcessLauncher.open_file_explorer(updater.log_file)

        window.footer_clicked.connect(lambda: show_whats_new())
        window.update_clicked.connect(lambda: show_whats_new())  # its banner offers "Update now"

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
        if last_update is not None:
            qt.QtCore.QTimer.singleShot(300, lambda: report_update(last_update))


if __name__ == "__main__":
    main()
