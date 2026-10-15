"""Standalone entry point for the desktop hub application.

Follows the same QtApplicationContext pattern used in the __main__ blocks
of frameless_dialog.py / frameless_main_window.py, rather than creating a
QApplication by hand.

In a source checkout, theme files hot-reload (edit assets/themes/*.css or
ui/theme/base.qss, save, the hub repaints). MSL_THEME_HOT_RELOAD=0/1
forces it off/on.

One hub per install (InstanceLink): a second start hands over what it was
asked to do and quits without a window. `--open <files...>` (what
Explorer's "Send to → MSL Media" runs): the files are opened in Media of
the hub already running; a plain second start (the shortcut clicked
again) brings that hub to the front.
"""
import sys
import threading
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl import __version__
from msl_tools.msl.core.installer.hub_updater import HubUpdater, UpdateResult
from msl_tools.msl.core.link import assistant as assistant_names
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.core.version.version import Version
from msl_tools.msl.ui.app.application_context import QtApplicationContext
from msl_tools.msl.ui.app.instance_link import InstanceLink
from msl_tools.msl.ui.theme import ThemeHotReloader
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.tools.desktop.assistant.connect_dialog import ConnectAssistantDialog
from msl_tools.msl.tools.desktop.registry import TOOLS
from msl_tools.msl.tools.desktop.scenes import REPLACED_TOOL_IDS as SCENES_REPLACED
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.maya_link import AssistantServer, MayaLinkServer
from msl_tools.msl.ui.widgets.atoms.header.assistant_button import AssistantButton
from msl_tools.msl.ui.widgets.compositions.option_menu import OptionMenu
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


MAYA_GATE_TOOL_ID = "maya_gate"
CONFIRM_CODE_LINES = 14   # of an assistant's code shown in the question "may it run this?"
CONFIRM_WIDTH = 480        # ... wide enough for lines of code


def _show_link_on_tile(window: HubWindow, link: MayaLinkServer) -> None:
    """The hub <-> Maya link, told on Maya Gate's sidebar tile - seen from every tool: a green
    count of the connected Mayas, or a red one of the errors a Maya reported that nobody
    looked at yet (red "!" too when the link itself isn't listening). A click on the tile
    while it is red opens the Sessions tab."""
    def refresh() -> None:
        sessions, errors = len(link.sessions()), link.unread_errors()
        if not link.is_listening():
            window.set_tool_badge(MAYA_GATE_TOOL_ID, "!", "attention",
                                  "Maya link: not listening" + (f" - {link.error_text()}" if link.error_text() else ""))
        elif errors:
            window.set_tool_badge(MAYA_GATE_TOOL_ID, str(errors), "attention",
                                  f"{errors} new error(s) in Maya — click to see")
        elif sessions:
            window.set_tool_badge(MAYA_GATE_TOOL_ID, str(sessions), "",
                                  "1 Maya connected" if sessions == 1 else f"{sessions} Mayas connected")
        else:
            window.set_tool_badge(MAYA_GATE_TOOL_ID, "")

    def on_tile_clicked(*_args) -> None:
        if link.unread_errors():   # the page is open by now (the tile's own click came first)
            show = getattr(window.tool_page(MAYA_GATE_TOOL_ID), "show_sessions", None)   # not open_tool():
            if show is not None:                                                        # that clicks the tile again
                show()

    link.listening_changed.connect(refresh)
    link.sessions_changed.connect(refresh)
    link.attention_changed.connect(refresh)
    tile = window.tool_button(MAYA_GATE_TOOL_ID)
    if tile is not None:
        tile.clicked.connect(on_tile_clicked)
    refresh()


def _assistant_menu(button: AssistantButton, assistant: AssistantServer, toggle) -> OptionMenu:
    """The menu of the header's assistant switch: what the assistant may do (each choice
    pictured by the head as it then looks), and switching the channel on / off."""
    def face(on: bool, acting: bool = False) -> AssistantButton:
        """The head as it looks in a state - the picture of a menu row."""
        picture = AssistantButton()
        picture.set_state(on, acting)
        return picture

    listening, code, clients = assistant.is_listening(), assistant.code_allowed(), assistant.clients()
    popup = OptionMenu(button)
    popup.add_caption("WHAT THE ASSISTANT MAY DO")
    popup.add_option("Look only", "Sees which Mayas are connected and reads their logs",
                     face(True), checked=not code).triggered.connect(lambda: assistant.set_code_allowed(False))
    popup.add_option("Look and run Python", "Also runs code in the connected Mayas — shown in their logs",
                     face(True, True), checked=code).triggered.connect(lambda: assistant.set_code_allowed(True))
    if code:   # finer than the one switch: where it may act, and whether it asks first
        if assistant.environments():
            popup.add_caption("IT MAY ACT IN MAYAS OF")
            off = assistant.off_environments()
            for environment in assistant.environments():
                popup.add_switch(environment, environment not in off).toggled.connect(
                    lambda allowed, environment=environment: assistant.set_environment_allowed(environment, allowed))
        popup.add_caption("BEFORE IT SAVES, OPENS OR CLOSES A SCENE, OR DELETES FILES")
        popup.add_switch("Ask me first", assistant.confirms()).toggled.connect(assistant.set_confirms)
        popup.add_switch("Open / new scenes without asking (until restart)",
                         assistant.scenes_free()).toggled.connect(assistant.set_scenes_free)
    popup.addSeparator()
    if listening:
        who = "%d connected now" % clients if clients else "nobody connected now"
        popup.add_option("Switch off", "On, port %d · %s" % (assistant.port(), who),
                         face(False, code)).triggered.connect(toggle)
    else:
        popup.add_option("Switch on", "Off — no assistant can connect",
                         face(True, code)).triggered.connect(toggle)
    popup.addAction("Connect a coding assistant…").triggered.connect(
        lambda: ConnectAssistantDialog.show_for(button))
    journal = assistant.journal_file()
    if journal is not None:
        popup.addAction("Show the journal of what it did").triggered.connect(
            lambda: ProcessLauncher.open_file_explorer(journal if journal.exists() else journal.parent))
    return popup


def _confirm_assistant_code(window: HubWindow, session, code: str, reasons: list, answer) -> None:
    """Asks the user whether an assistant's code that saves, opens, closes or deletes may run
    (AssistantServer.set_confirmer). Unanswered for CONFIRM_SECONDS = refused."""
    lines = code.strip("\n").split("\n")
    shown = "\n".join(lines[:CONFIRM_CODE_LINES]) + (
        "\n… %d more lines" % (len(lines) - CONFIRM_CODE_LINES) if len(lines) > CONFIRM_CODE_LINES else "")
    where = "Maya %s · %s · %s" % (session.version, session.environment or "no environment", session.scene_name)
    qt.QtWidgets.QApplication.alert(window)   # the taskbar button, if the hub is not in front
    choice = ConfirmDialog.ask(
        window, "The assistant asks", "The assistant wants to run code that " + ", ".join(reasons) + ".",
        details=where + "\n\n" + shown, choices=[("allow", "Allow"), ("refuse", "Refuse")], kind="danger",
        timeout_ms=assistant_names.CONFIRM_SECONDS * 1000, width=CONFIRM_WIDTH)
    answer(choice == "allow")


def _add_assistant_button(window: HubWindow, assistant: AssistantServer) -> None:
    """The header's switch of the assistant's channel (ui/maya_link/assistant_server.py): a
    click switches it on / off, a right click says what the assistant may do. It also shows
    whether an assistant is connected and when its code is running in a Maya."""
    button = AssistantButton()

    def refresh(*_args) -> None:
        listening, code, clients = assistant.is_listening(), assistant.code_allowed(), assistant.clients()
        button.set_state(listening, code, clients, bool(assistant.running()))
        if listening:
            state = "Assistant access: ON · port %d · %s" % (
                assistant.port(), "%d connected" % clients if clients else "nobody connected")
        elif assistant.is_enabled():
            state = "Assistant access: switched on, but no port could be taken"
        else:
            state = "Assistant access: off"
        button.setToolTip(
            state + "\nLets a coding assistant on this computer (the msl-maya MCP server) see which Mayas "
                    "are connected and read their logs"
            + (" — and RUN PYTHON in them (shown in each Maya’s log)." if code else ".")
            + "\nThis computer only, with a key of its own.\nClick: on / off  ·  right click: what it may do")

    def toggle() -> None:
        assistant.set_enabled(not assistant.is_listening())
        refresh()

    def menu(position) -> None:
        _assistant_menu(button, assistant, toggle).exec(position)

    for signal in (assistant.listening_changed, assistant.clients_changed, assistant.access_changed,
                   assistant.code_started, assistant.code_finished):
        signal.connect(refresh)
    button.clicked.connect(toggle)
    button.menu_requested.connect(menu)
    window.add_header_widget(button)
    refresh()


def _files_to_open(argv: list) -> list:
    """The paths after `--open` (Explorer's "Send to" appends the files it was given)."""
    if "--open" not in argv:
        return []
    return [argument for argument in argv[argv.index("--open") + 1:] if not argument.startswith("--")]


def _bring_to_front(window: HubWindow) -> None:
    if window.isMinimized():
        window.showNormal()
    window.raise_()
    window.activateWindow()


def _open_in_media(window: HubWindow, paths: list) -> None:
    """Media, in front, with `paths` loaded."""
    page = window.open_tool("media")
    if page is not None and paths:
        page.open(paths)
    _bring_to_front(window)


def _on_second_start(window: HubWindow, message: dict) -> None:
    """What another start of this install handed over: files to open, or just "come to the front"."""
    files = list(message.get("open") or [])
    if files:
        _open_in_media(window, files)
    else:
        _bring_to_front(window)


def main() -> None:
    # One hub per install: a start that only brings files hands them to the hub that is running
    # and quits - BEFORE the application context, whose exit runs the event loop in any case.
    # Without files it asks that hub to come to the front: two hubs of one install would each
    # keep their own copy of the configs and save over each other's changes.
    instance_name = InstanceLink.instance_name(Resources().fsManager.ROOT_DIR)
    files = _files_to_open(sys.argv)
    if InstanceLink.send(instance_name, {"open": files} if files else {"raise": True}):
        return
    _use_own_taskbar_icon()
    with QtApplicationContext():
        if ThemeHotReloader.enabled_by_default(_REPO_ROOT):
            ThemeHotReloader(UiResources().themeManager, Resources().themeRegistry.themes_dir)
        # The hub's own state (which tool is open) lives in configs/desktop/hub/.
        hub_config = Resources().configsDesktopHubMng.get_config("hub", defaults=HUB_CONFIG_DEFAULTS)
        icon = UiResources().iconManager.get_icon("hub", sub_folder="brand")
        current_tool = str(hub_config["current_tool"] or "")
        if current_tool in SCENES_REPLACED:   # Batch / Paths are tabs of Scenes now
            current_tool = "scenes"
        window = HubWindow(tools=TOOLS, current_tool_id=current_tool, icon=icon,
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
        # The hub <-> Maya link: listen from the start, so a Maya that outlived the
        # previous hub (it retries every few seconds) finds this one.
        link = MayaLinkServer.instance()
        _show_link_on_tile(window, link)
        link.media_requested.connect(lambda paths: _open_in_media(window, paths))  # e.g. a playblast from Maya
        link.ensure_listening()
        # The assistant's channel (off unless the user switched it on); created now so it keeps
        # the Mayas' logs from the start.
        assistant = AssistantServer.instance()
        assistant.set_window(window)   # an assistant may ask for a picture of the hub
        assistant.set_confirmer(lambda session, code, reasons, answer: _confirm_assistant_code(
            window, session, code, reasons, answer))
        assistant.ensure_listening()
        _add_assistant_button(window, assistant)
        if last_update is not None:
            qt.QtCore.QTimer.singleShot(300, lambda: report_update(last_update))
        instance_link = InstanceLink(instance_name, window)
        instance_link.received.connect(lambda message: _on_second_start(window, message))
        if files:
            qt.QtCore.QTimer.singleShot(0, lambda: _open_in_media(window, files))


if __name__ == "__main__":
    main()
