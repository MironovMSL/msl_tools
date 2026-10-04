# tools/desktop/maya_gate/sessions_tab.py
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import protocol
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.core.link.session import MayaSession
from msl_tools.msl.core.environment.processes import process_memory
from msl_tools.msl.tools.desktop.maya_gate.snippets import SnippetStore
from msl_tools.msl.tools.desktop.maya_gate.session_history import (LOG_FOLDER_NAME, SessionHistory, SessionRecord,
                                                                   find_autosave, read_log, write_log)
from msl_tools.msl.ui.maya_link.server import MayaLinkServer
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.widgets.atoms.editors import LogView
from msl_tools.msl.ui.widgets.atoms.layouts import FlowLayout
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.tools.desktop.maya_gate.session_rows import _EndedRow, _HistoryRow, _SessionRow
from msl_tools.msl.tools.desktop.maya_gate.sessions_console_widgets import _ConsoleInput, _NameField
from msl_tools.msl.tools.desktop.maya_gate.sessions_console import _ConsoleMixin
from msl_tools.msl.tools.desktop.maya_gate.sessions_control import _ControlMixin


class SessionsTab(_ConsoleMixin, _ControlMixin, qt.QtWidgets.QWidget):
    """Maya Gate's "Sessions" tab: the Mayas running right now that were
    started from the hub — live, through the hub <-> Maya link
    (ui/maya_link/server.py; each Maya connects by itself on startup).

    Unlike the other tabs it isn't about ONE environment's settings: it
    lists every connected Maya, whatever environment it was started in.

    Each row shows version, environment, open scene, boost and the time
    since it connected. A Maya that closes (or crashes) leaves the list at
    once — its connection drops.

    What can be asked of a running Maya (MayaLinkServer.request(), a fixed
    list — see core/link/protocol.py):
    - Report: its launch report, shown here in a TextDialog;
    - Reload code: re-read msl_tools from disk in that Maya (its link
      restarts on the new code, so the row blinks out and back);
    - Plug-ins (boosted sessions): a menu of the plug-ins boost start left
      out — load one, or all, in that Maya without restarting it.
    The outcome of the last request is the line under the list.

    The log (below the list): what the SELECTED Maya's Script Editor prints,
    as it happens — warnings and errors, or everything except command echo
    with the "All" switch (asked of Maya with SET_LOG_LEVEL, so plain
    messages don't travel unless someone wants them). Each row counts its
    errors / warnings. Logs are kept per Maya PROCESS (pid), so "Reload
    code" — which gives the session a new id — doesn't lose them; a Maya
    that closed (or crashed) keeps its log on screen for GONE_GRACE_S.

    Around the list: a Maya that doesn't answer the server's pings shows
    "busy" (its dot turns to the warning tone). A Maya that went away
    WITHOUT a goodbye (MayaLinkServer.session_ended, clean=False) — crashed
    or killed — stays as an "ended unexpectedly" line until dismissed, with
    its log written to logs/desktop/maya_gate/sessions/. Errors that come
    in while the tab isn't on screen are counted for the server's
    unread_errors (the tab's title and the header's indicator show a mark),
    and cleared when the tab is shown.

    Scenes: a row's scene name carries a "*" while that scene has unsaved
    changes, and is a link to the file (_SceneLabel).

    History: every session that is over is kept (SessionHistory — it
    survives a hub restart) together with what it reported, as a log file.
    "Recent sessions" sits under the live rows: open while nothing runs,
    folded (a click on its caption opens it) while a Maya does. A click on
    one of them shows its saved log below; "Reopen" starts that Maya again
    with the same scene. A link restart ("Reload code") and the hub's own
    shutdown are not ends of a session.

    Close / Restart (a row's "Close"): asks first — with unsaved changes it
    offers to save, to drop them, or to leave Maya alone — then sends QUIT.
    Maya checks the scene again itself and refuses if it changed meanwhile.
    A restart waits until that Maya's process is really gone (it is still
    writing its preferences), then starts the same version in the same
    environment with the same scene.

    A Maya that doesn't answer (busy) gets "Force close…" in its menu: its
    process is ended after a question; it then reads "force closed", not
    "ended unexpectedly". After any unclean end the newest autosave Maya
    wrote for the scene (find_autosave — Maya reports its autosave folder)
    is offered as "Open autosave".

    The tab launches nothing itself: `launch(year, environment, scene)` is
    handed in by the page (it returns "" or what went wrong); without it
    there is no Restart / Reopen. `settings` is where the log's "Wrap"
    switch is remembered ("log_wrap").

    The console (under the log, only while the selected Maya allows it —
    one started in a Dev environment): a small Python editor; Ctrl+Enter or
    "Run" sends the code to that Maya (RUN_PYTHON), which runs it like its
    Script Editor would. The code, what it printed, its result or its
    traceback go into that Maya's log. Whether a Maya accepts code is
    decided by Maya itself (it was launched with MSL_GATE_CONSOLE=1); the
    tab only hides the console where it would be refused.
    Snippets (SnippetStore): code saved under a name becomes a chip above
    the input — a click runs it in the selected Maya, a right click offers
    Edit (the code goes into the input) and Delete. "+ Save as snippet"
    asks for the name in place (_NameField).

    Colors: maya_gate.qss (SessionsTab ...).
    """

    REFRESH_MS = 30_000  # "12 min" labels
    CONSOLE_TIMEOUT_MS = 600_000  # code may run long; Maya is busy meanwhile anyway
    MESSAGE_MS = 8000    # how long the last request's outcome stays
    REPORT_TIMEOUT_MS = 15_000
    RELOAD_TIMEOUT_MS = 20_000
    PLUGINS_TIMEOUT_MS = 180_000  # loading heavy plug-ins takes Maya a while
    LIST_ROWS_SHOWN = 4           # the list is this tall at most; the log gets the rest
    LOG_PROBLEMS, LOG_ALL = "Problems", "All"
    LOG_KEPT = 2000               # entries kept per Maya
    GONE_GRACE_S = 60             # how long a Maya that left keeps its log (and the selection)
    RELOAD_GRACE_S = 5            # ... and how long one that left with an empty log does
    QUIT_TIMEOUT_MS = 120_000     # "save and close": saving a heavy scene takes Maya a while
    RESTART_WAIT_S = 90           # how long a restart waits for the old Maya's process to be gone
    LOG_PLACEHOLDER = "Warnings and errors from the selected Maya’s Script Editor appear here."
    SNIPPET_TIP_LINES = 12        # lines of a snippet's code shown in its chip's tooltip
    MENU_ICON_SIZE = 16

    # Colors of the row menu's icons (maya_gate.qss): a menu's icons are QIcons, which QSS
    # can't tint - the tab takes the colors as properties and tints them when the menu opens.
    menuIconColor = color_property("_menu_icon_color", None)
    menuDangerColor = color_property("_menu_danger_color", None)
    HISTORY_CAPTION_HEIGHT = 24

    def __init__(self, server: MayaLinkServer, history: SessionHistory | None = None, launch=None,
                 settings=None, snippets: SnippetStore | None = None, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._menu_icon_color = qt.QtGui.QColor(fallback.text_secondary)
        self._menu_danger_color = qt.QtGui.QColor(fallback.error)
        self._snippets = snippets                 # None: the console has no snippets
        self._snippet_chips: list = []
        self._snippets_shown = False              # the snippet file is first read when the console shows
        self._editing_snippet = ""                # the snippet whose code was put into the editor to change
        self._server = server
        self._history = history                   # None: finished sessions aren't kept
        self._launch = launch                     # (year, environment, scene) -> "" or an error; None: can't launch
        self._settings = settings                 # a mapping that remembers "log_wrap"; None: not remembered
        self._history_open: bool | None = None    # None: open while nothing runs, folded otherwise
        self._history_open_while = False          # ... the caption's click holds while this stays as it was
        self._history_shown_open = False
        self._history_selected = None             # key of the finished session whose log is shown
        self._restarts: dict[int, tuple] = {}     # pid -> (asked at, version, environment, scene): start again once gone
        self._forced: set[int] = set()            # pids force closed from here (their end isn't a crash)
        self._history_rows: list[_HistoryRow] = []
        self._history_key = None                  # what the history rows on screen were built from
        # "Reopen": the new Maya is another session (another process, its own log) — but it is
        # shown as the continuation of the one it was reopened from.
        self._reopen_pending: dict = {}           # (version, environment, scene) -> (record key, when asked)
        self._continues: dict[int, tuple] = {}    # pid of a running Maya -> key of the record it continues
        self._seen = False                        # the history file is first read when the tab is shown
        self._names: dict[int, str] = {}          # pid -> "Maya 2025 · Dev" (for a closed Maya's log title)
        self._rows: dict[int, _SessionRow] = {}
        self._logs: dict[int, list] = {}          # pid -> [(level, text, time), ...]
        self._problems: dict[int, list] = {}      # pid -> [errors, warnings]
        self._console_running: set[int] = set()  # pids of the Mayas running code from the console
        self._selected_pid = 0
        self._gone: dict[int, float] = {}         # pid -> when that Maya left (its log is kept a while)
        self._ended: dict[int, dict] = {}         # pid -> {"session", "when", "file"}: gone without a goodbye
        self._ended_rows: dict[int, _EndedRow] = {}
        self._log_all = False

        self._title_label = qt.QtWidgets.QLabel("Sessions")
        self._title_label.setObjectName("sessionsTitle")
        self._summary_label = qt.QtWidgets.QLabel()
        self._summary_label.setObjectName("sessionsSummary")
        self._status_label = qt.QtWidgets.QLabel()
        self._status_label.setObjectName("sessionsStatus")

        self._list = qt.QtWidgets.QWidget()
        self._list_layout = qt.QtWidgets.QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(0)
        self._empty_label = qt.QtWidgets.QLabel()
        self._empty_label.setObjectName("sessionsEmpty")
        self._empty_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._list_layout.addWidget(self._empty_label)
        self._history_caption = qt.QtWidgets.QWidget()
        self._history_caption.setFixedHeight(self.HISTORY_CAPTION_HEIGHT)
        self._history_toggle = qt.QtWidgets.QPushButton()
        self._history_toggle.setObjectName("sessionsHistoryToggle")
        self._history_toggle.setFlat(True)
        self._history_toggle.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._history_toggle.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._history_toggle.setToolTip("The Maya sessions that are over — click to show or fold them")
        self._clear_history_button = _SessionRow._action("Clear", "Forget these sessions and delete their saved logs")
        caption_layout = qt.QtWidgets.QHBoxLayout(self._history_caption)
        caption_layout.setContentsMargins(8, 0, 6, 0)
        caption_layout.addWidget(self._history_toggle)
        caption_layout.addStretch(1)
        caption_layout.addWidget(self._clear_history_button)
        self._history_toggle.clicked.connect(self._on_toggle_history)
        self._list_layout.addWidget(self._history_caption)
        self._history_caption.hide()
        self._clear_history_button.clicked.connect(self._on_clear_history)
        self._list_layout.addStretch(1)
        self._scroll = StableScrollArea()
        self._scroll.setObjectName("sessionsScroll")
        self._scroll.setWidget(self._list)

        self._log_title = qt.QtWidgets.QLabel("Log")
        self._log_title.setObjectName("sessionsTitle")
        self._log_section = qt.QtWidgets.QLabel()
        self._log_section.setObjectName("sessionsSummary")
        self._log_section.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._level_switch = SegmentedControl([self.LOG_PROBLEMS, self.LOG_ALL], self.LOG_PROBLEMS)
        self._level_switch.setToolTip("Problems: warnings and errors.\nAll: also what scripts print (not the command echo).")
        self._copy_log_button = _SessionRow._action("Copy", "Copy the log")
        self._clear_log_button = _SessionRow._action("Clear", "Empty this Maya\u2019s log here (nothing changes in Maya)")
        self._log_view = LogView(self.LOG_PLACEHOLDER)
        wrap = bool(self._settings.get("log_wrap", True)) if self._settings is not None else True
        self._log_view.set_wrap(wrap)
        self._wrap_button = qt.QtWidgets.QPushButton("Wrap")
        self._wrap_button.setObjectName("sessionToggle")  # maya_gate.qss: quiet, accent while on
        self._wrap_button.setFlat(True)
        self._wrap_button.setCheckable(True)
        self._wrap_button.setChecked(wrap)
        self._wrap_button.setToolTip("Long lines continue on the next line instead of running off to the right")
        self._wrap_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._wrap_button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._wrap_button.toggled.connect(self._on_wrap_toggled)

        self._console_input = _ConsoleInput()
        self._run_button = qt.QtWidgets.QPushButton("Run")
        self._run_button.setProperty("primary", True)
        self._run_button.setToolTip("Run this code in the selected Maya (Ctrl+Enter)")
        # Snippets: saved pieces of code as chips above the input - one click runs one.
        self._save_snippet_button = _SessionRow._action(
            "+ Save as snippet", "Keep the code in the console under a name — it becomes a chip here, "
                                 "one click runs it in the selected Maya")
        self._snippet_name = _NameField()
        self._snippet_name.setPlaceholderText("Snippet name, then Enter")
        self._snippet_name.setFixedWidth(190)
        self._snippets_bar = qt.QtWidgets.QWidget()
        self._snippets_layout = FlowLayout(self._snippets_bar, spacing=6)
        self._snippets_layout.addWidget(self._save_snippet_button)
        self._snippets_layout.addWidget(self._snippet_name)
        self._snippet_name.hide()
        self._save_snippet_button.clicked.connect(self._on_save_snippet)
        self._snippet_name.returnPressed.connect(self._on_snippet_named)
        self._snippet_name.cancelled.connect(self._snippet_name.hide)

        self._console = qt.QtWidgets.QWidget()
        input_row = qt.QtWidgets.QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(6)
        input_row.addWidget(self._console_input, 1)
        input_row.addWidget(self._run_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignBottom)
        console_layout = qt.QtWidgets.QVBoxLayout(self._console)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(4)
        console_layout.addWidget(self._snippets_bar)
        console_layout.addLayout(input_row)
        if self._snippets is None:
            self._snippets_bar.hide()
        self._console.hide()
        self._console_input.run_requested.connect(self._on_run_code)
        self._run_button.clicked.connect(self._on_run_code)

        self._message_label = qt.QtWidgets.QLabel()
        self._message_label.setObjectName("sessionsMessage")
        self._message_label.setWordWrap(True)
        self._message_label.hide()
        self._message_timer = qt.QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.setInterval(self.MESSAGE_MS)
        self._message_timer.timeout.connect(self._message_label.hide)

        self._hint_label = qt.QtWidgets.QLabel(
            "Every Maya started from here connects to MSL Tools by itself and shows up in this list. "
            "Maya 2020 and Mayas started some other way don’t.")
        self._hint_label.setObjectName("sessionsHint")
        self._hint_label.setWordWrap(True)

        header = qt.QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self._title_label)
        header.addWidget(self._summary_label, 1)
        header.addWidget(self._status_label)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        log_header = qt.QtWidgets.QHBoxLayout()
        log_header.setContentsMargins(0, 2, 0, 0)
        log_header.setSpacing(6)
        log_header.addWidget(self._log_title)
        log_header.addWidget(self._log_section, 1)
        log_header.addWidget(self._wrap_button)
        log_header.addWidget(self._copy_log_button)
        log_header.addWidget(self._clear_log_button)
        log_header.addWidget(self._level_switch)

        layout.addLayout(header)
        layout.addWidget(self._scroll)
        layout.addWidget(self._message_label)
        layout.addLayout(log_header)
        # The log over the console, with a handle between them: drag it to give the console the
        # room of a real editor (taken from the log) or to get the log back. Remembered.
        self._split = qt.QtWidgets.QSplitter(qt.QtCore.Qt.Orientation.Vertical)
        self._split.setObjectName("sessionsSplit")
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(6)
        self._split.addWidget(self._log_view)
        self._split.addWidget(self._console)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 0)
        self._split_save_timer = qt.QtCore.QTimer(self)
        self._split_save_timer.setSingleShot(True)
        self._split_save_timer.setInterval(400)
        self._split_save_timer.timeout.connect(self._save_console_height)
        self._split.splitterMoved.connect(self._on_split_moved)
        self._log_view.setMinimumHeight(60)
        layout.addWidget(self._split, 1)
        layout.addWidget(self._hint_label)

        self._server.log_received.connect(self._on_log)
        self._server.session_ended.connect(self._on_session_ended)
        self._level_switch.current_changed.connect(self._on_level_changed)
        self._copy_log_button.clicked.connect(
            lambda: qt.QtGui.QGuiApplication.clipboard().setText(self._log_view.plain_text()))
        self._clear_log_button.clicked.connect(self._on_clear_log)

        self._timer = qt.QtCore.QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._server.sessions_changed.connect(self.refresh)
        self._server.listening_changed.connect(self.refresh)
        self.refresh()

    def _place_split(self) -> None:
        """The console at its remembered height (the first time: just its few lines)."""
        if not self._console.isVisible():
            return
        least = self._console.minimumSizeHint().height()
        wanted = least
        if self._settings is not None:
            try:
                wanted = int(self._settings.get("console_height", least) or least)
            except (TypeError, ValueError):
                wanted = least
        total = self._split.height() - self._split.handleWidth()
        height = max(least, min(wanted, total - self._log_view.minimumHeight()))
        self._split.setSizes([max(0, total - height), height])

    def _on_split_moved(self, *_args) -> None:
        # Saved once the grip rests: every pixel of a drag would rewrite the whole config file.
        if self._settings is not None and self._console.isVisible():
            self._split_save_timer.start()

    def _save_console_height(self) -> None:
        if self._settings is not None and self._console.isVisible():
            self._settings["console_height"] = self._split.sizes()[1]

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._server.set_unread_errors(0)  # whatever came in meanwhile is being looked at now
        self._seen = True
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def refresh(self) -> None:
        """Brings the rows in line with the server's sessions."""
        sessions = {session.session_id: session for session in self._server.sessions()}
        self._link_reopened(sessions.values())
        for session_id in [key for key in self._rows if key not in sessions]:
            row = self._rows.pop(session_id)
            row.hide()
            row.deleteLater()
        for index, (session_id, session) in enumerate(sessions.items()):
            row = self._rows.get(session_id)
            if row is None:
                row = _SessionRow(session)
                row.set_session(session, process_memory(session.pid))
                row.menu_requested.connect(self._on_row_menu)
                row.selected.connect(self._select_session)
                row.scene_label.reveal_failed.connect(self._on_reveal_failed)
                self._rows[session_id] = row
                if self._log_all:  # a Maya that just joined (or reloaded) starts on "Problems"
                    self._server.request(session_id, protocol.SET_LOG_LEVEL, **{"all": True})
                self._list_layout.insertWidget(index, row)
            else:
                row.set_session(session, process_memory(session.pid))

        # Mayas that ended unexpectedly: listed under the live ones until dismissed.
        live_pids = {session.pid for session in sessions.values()}
        for pid in [pid for pid in self._ended if pid in live_pids]:
            info = self._ended.pop(pid)  # it is back (an older Maya restarting its link): not ended after all
            if self._history is not None:
                self._history.discard(pid, info["when"])
        for pid in [pid for pid in self._ended_rows if pid not in self._ended]:
            row = self._ended_rows.pop(pid)
            row.hide()
            row.deleteLater()
        for offset, (pid, info) in enumerate(self._ended.items()):
            if pid not in self._ended_rows:
                row = _EndedRow(info["session"], info["when"], info["file"] is not None, self._launch is not None,
                                info.get("forced", False), info.get("autosave", ""))
                row.reopen_requested.connect(self._on_reopen_ended)
                row.autosave_requested.connect(lambda pid: self._open_autosave(
                    self._ended[pid]["session"].version, self._ended[pid]["session"].environment,
                    self._ended[pid]["autosave"]) if pid in self._ended else None)
                row.selected.connect(self._select_pid)
                row.file_requested.connect(self._on_show_log_file)
                row.dismissed.connect(self._on_dismiss_ended)
                self._ended_rows[pid] = row
                self._list_layout.insertWidget(len(sessions) + offset, row)

        count = len(sessions)
        self._summary_label.setText("" if not count else f"· {count} running")
        if self._server.is_listening():
            self._status_label.setText(f"listening on port {self._server.port()}")
            self._status_label.setProperty("state", "")
            self._empty_label.setText("No Maya is running from here.\nStart one with the icons above.")
        else:
            self._status_label.setText("not listening")
            self._status_label.setProperty("state", "error")
            self._empty_label.setText("MSL Tools isn’t listening for Maya sessions.\n"
                                      + (self._server.error_text() or "It starts with the first launch."))
        repolish(self._status_label)
        # The sessions that are over: under the live ones — open while nothing runs, folded
        # while a Maya does (unless the caption was clicked). One that still waits above as
        # an "ended unexpectedly" line isn't listed twice.
        listed = count + len(self._ended)
        waiting = {(pid, info["when"]) for pid, info in self._ended.items()}
        records = [record for record in self._history_records() if record.key not in waiting]
        if self._history_open is not None and self._history_open_while != bool(listed):
            self._history_open = None  # the caption was clicked in the other situation: back to the default
        opened = self._history_open if self._history_open is not None else not listed
        if self._history_selected is not None and self._history_selected not in {record.key for record in records}:
            self._history_selected = None  # it was cleared away
            self._show_log()
        self._show_history(records, opened)
        self._empty_label.setVisible(not listed and not records)
        if records and not count:
            self._summary_label.setText("· none running")

        # The list is as tall as its rows (up to LIST_ROWS_SHOWN); the log gets the rest.
        if not listed and not records:
            self._scroll.setFixedHeight(_SessionRow.HEIGHT + 10 + 26)
        else:
            rows = listed + (len(records) if opened else 0)
            self._scroll.setFixedHeight(min(rows, self.LIST_ROWS_SHOWN) * _SessionRow.HEIGHT
                                        + (self.HISTORY_CAPTION_HEIGHT if records else 0) + 10)

        # Selection follows the PROCESS. A Maya that leaves keeps its log (and the selection)
        # for GONE_GRACE_S: "Reload code" makes it leave and rejoin under a new session id,
        # and a Maya that just crashed is exactly the one whose log one wants to read.
        pids = {session.pid: session for session in sessions.values()}
        now = time.time()
        for pid in list(self._logs) + [self._selected_pid]:
            if pid and pid not in pids and pid not in self._ended:  # an ended Maya keeps its log until dismissed
                self._gone.setdefault(pid, now)
        for pid in [pid for pid in self._gone if pid in pids]:
            del self._gone[pid]
        expired = {pid for pid, since in self._gone.items() if now - since > self.GONE_GRACE_S}
        for pid, session in pids.items():
            self._names[pid] = f"Maya {session.version}" + (f" · {session.environment}" if session.environment else "")
        selected_here = self._selected_pid in pids or self._selected_pid in self._ended
        # A Maya that left with nothing in its log holds the selection only long enough to
        # come back from a "Reload code"; one with a log holds it for the whole grace time.
        left_empty = (not self._logs.get(self._selected_pid)
                      and now - self._gone.get(self._selected_pid, now) > self.RELOAD_GRACE_S)
        if not selected_here and self._history_selected is None \
                and (not self._selected_pid or self._selected_pid in expired or left_empty):
            if pids:
                self._selected_pid = next(iter(pids))
                self._show_log()
            elif self._selected_pid and not self._logs.get(self._selected_pid):
                self._selected_pid = 0  # that Maya is gone and left nothing to read
        for pid in expired:
            if pid != self._selected_pid:
                self._logs.pop(pid, None)
                self._problems.pop(pid, None)
                self._gone.pop(pid, None)
                self._names.pop(pid, None)
        for session_id, row in self._rows.items():
            session = sessions[session_id]
            row.set_selected(session.pid == self._selected_pid)
            row.set_problems(*self._problems.get(session.pid, [0, 0]))
        for pid, row in self._ended_rows.items():
            row.set_selected(pid == self._selected_pid)
        for row in self._history_rows:
            row.set_selected(row.record.key == self._history_selected)
        self._clear_log_button.setEnabled(self._history_selected is None)
        self._update_log_title(pids.get(self._selected_pid))
        # The console: only for a selected Maya that is here and accepts code.
        selected = pids.get(self._selected_pid)
        console_was_shown = self._console.isVisible()
        self._console.setVisible(selected is not None and selected.console)
        self._sync_run_button()
        if self._console.isVisible() and not console_was_shown:
            qt.QtCore.QTimer.singleShot(0, self._place_split)  # once the splitter knows its own height
        if self._console.isVisible() and not self._snippets_shown:
            self._snippets_shown = True  # first time the console is on screen: read the snippets
            self._rebuild_snippets()

    # --- the log ---------------------------------------------------------------------

    def _session_by_pid(self, pid: int) -> MayaSession | None:
        return next((session for session in self._server.sessions() if session.pid == pid), None)

    def _update_log_title(self, session: MayaSession | None) -> None:
        record = self._selected_record()
        if record is not None:
            text = (f"· Maya {record.version}" + (f" · {record.environment}" if record.environment else "")
                    + " · " + record.outcome_text() + " " + record.ended_text())
        elif session is not None:
            text = "· " + self._names.get(session.pid, f"Maya {session.version}")
        elif self._selected_pid in self._ended:
            ended = self._ended[self._selected_pid]["session"]
            text = (f"· Maya {ended.version}" + (f" · {ended.environment}" if ended.environment else "")
                    + (" · force closed" if self._ended[self._selected_pid].get("forced") else " · ended unexpectedly"))
        elif self._selected_pid and self._logs.get(self._selected_pid):
            # A Maya that closed: its log stays readable for a while. Without a log there is nothing to title.
            text = "· " + self._names.get(self._selected_pid, "that Maya") + " · closed"
        else:
            text = ""
        self._log_section.setText(text)

    def _select_session(self, session_id: int) -> None:
        session = self._server.session(session_id)
        if session is None or (session.pid == self._selected_pid and self._history_selected is None):
            return
        if self._selected_pid in self._gone:  # leaving a closed Maya's log: it isn't kept any longer
            self._logs.pop(self._selected_pid, None)
            self._problems.pop(self._selected_pid, None)
            self._gone.pop(self._selected_pid, None)
        self._history_selected = None
        self._selected_pid = session.pid
        self._show_log()
        self.refresh()

    def _selected_record(self) -> SessionRecord | None:
        """The finished session whose saved log is shown (None: a live Maya's log is)."""
        if self._history_selected is None:
            return None
        return next((row.record for row in self._history_rows if row.record.key == self._history_selected), None) \
            or next((record for record in self._history_records() if record.key == self._history_selected), None)

    def _show_log(self) -> None:
        record = self._selected_record()
        if record is None:
            self._log_view.setPlaceholderText(self.LOG_PLACEHOLDER)
            self._log_view.set_entries(self._logs.get(self._selected_pid, []))
            return
        entries = read_log(record.log_file, record.ended_at) if record.log_file else []
        self._log_view.setPlaceholderText("That Maya reported no warnings or errors." if entries is not None
                                          else "The saved log of that session isn’t there any more.")
        self._log_view.set_entries(entries or [])

    def _on_log(self, session_id: int, entries: list) -> None:
        """Script Editor output of one Maya: kept for that process, shown if it is the selected one."""
        session = self._server.session(session_id)
        if session is None:
            return
        now = time.time()
        log = self._logs.setdefault(session.pid, [])
        problems = self._problems.setdefault(session.pid, [0, 0])
        for level, text in entries:
            log.append((level, text, now))
            if level == protocol.LOG_ERROR:
                problems[0] += 1
            elif level == protocol.LOG_WARNING:
                problems[1] += 1
            if session.pid == self._selected_pid:
                self._log_view.append_entry(level, text, now)
        del log[:-self.LOG_KEPT]
        row = self._rows.get(session_id)
        if row is not None:
            row.set_problems(*problems)
        # Errors that arrive while this tab isn't on screen: the tab's title and the
        # header's indicator carry a mark until someone looks.
        new_errors = sum(1 for level, _text in entries if level == protocol.LOG_ERROR)
        if new_errors and not self.isVisible():
            self._server.set_unread_errors(self._server.unread_errors() + new_errors)

    # --- a Maya that ended unexpectedly ---------------------------------------------------

    def _on_session_ended(self, session: MayaSession, clean: bool, reason: str) -> None:
        """A session is gone. Every real end goes into the history, with what
        that Maya reported saved as a file; one without a goodbye (a crash, a
        killed process) also stays in the list until dismissed."""
        if reason in (protocol.BYE_RESTART, MayaLinkServer.ENDED_BY_HUB):
            return  # its link restarts ("Reload code") / the hub is the one leaving: that Maya is still running
        now = time.time()
        record = SessionRecord(
            pid=session.pid, version=session.version, environment=session.environment, scene=session.scene,
            modified=session.modified, boosted=session.boosted, connected_at=session.connected_at,
            ended_at=now, clean=clean)
        if not clean:
            record.forced = session.pid in self._forced
            self._forced.discard(session.pid)
            # What Maya itself saved along the way: the newest autosave of this scene, if any.
            record.autosave = find_autosave(session.autosave_folder, session.scene, session.connected_at)
        entries = self._logs.get(session.pid, [])
        file = None
        if entries or not clean:
            folder = Path(Resources().fsManager.logsDesktop) / "maya_gate" / LOG_FOLDER_NAME
            file = write_log(folder, record, entries, session.full_version)
            record.log_file = str(file) if file is not None else ""
        if not clean:
            self._ended[session.pid] = {"session": session, "when": now, "file": file,
                                        "forced": record.forced, "autosave": record.autosave}
            self._gone.pop(session.pid, None)
            self._say(f"Maya {session.version} " + ("was force closed" if record.forced else "ended unexpectedly")
                      + " — its log was saved."
                      + (" Its newest autosave can be opened from its line." if record.autosave else ""), "error")
            if not self.isVisible() and not record.forced:
                self._server.set_unread_errors(self._server.unread_errors() + 1)
        if self._history is not None:
            self._history.add(record)
        self.refresh()
        restart = self._restarts.pop(session.pid, None)
        if restart is not None and clean and now - restart[0] < self.RESTART_WAIT_S:
            self._start_when_gone(session.pid, *restart[1:], deadline=now + self.RESTART_WAIT_S)

    # --- the sessions that are over ---------------------------------------------------------

    def _history_records(self) -> list:
        """The finished sessions. Nothing before the tab was first shown: the
        history file isn't read while the page is being built."""
        if self._history is None or not self._seen:
            return []
        return self._history.records()

    def _show_history(self, records: list, opened: bool) -> None:
        """Brings the caption and the history rows in line with `records`
        ([] = no history at all); rows only while `opened`."""
        self._history_shown_open = opened
        self._history_caption.setVisible(bool(records))
        self._history_toggle.setText(("▾" if opened else "▸") + f"  Recent sessions · {len(records)}")
        self._clear_history_button.setVisible(opened)
        continued = set(self._continues.values())
        key = ([record.key for record in records], opened, sorted(continued))
        if key == self._history_key:
            return
        self._history_key = key
        for row in self._history_rows:
            row.hide()
            row.deleteLater()
        self._history_rows = []
        first = self._list_layout.indexOf(self._history_caption) + 1
        for offset, record in enumerate(records if opened else []):
            row = _HistoryRow(record, self._launch is not None, reopened=record.key in continued)
            row.selected.connect(self._select_history)
            row.file_requested.connect(self._on_show_history_file)
            row.reopen_requested.connect(self._on_reopen_record)
            row.autosave_requested.connect(lambda r: self._open_autosave(r.version, r.environment, r.autosave))
            row.scene_label.reveal_failed.connect(self._on_reveal_failed)
            self._history_rows.append(row)
            self._list_layout.insertWidget(first + offset, row)

    def _on_toggle_history(self) -> None:
        self._history_open = not self._history_shown_open
        self._history_open_while = bool(self._rows or self._ended)  # (something is listed above the caption)
        self.refresh()

    def _select_history(self, key) -> None:
        """Shows the saved log of a finished session."""
        if key == self._history_selected:
            return
        self._history_selected = key
        self._selected_pid = 0
        self._show_log()
        self.refresh()

    def _on_clear_history(self) -> None:
        if self._history is not None:
            for record in self._history.records():
                if record.log_file and record.pid not in self._ended:  # a waiting "ended" line keeps its file
                    try:
                        if Path(record.log_file).parent.name == LOG_FOLDER_NAME:
                            Path(record.log_file).unlink()
                    except OSError:
                        pass
            self._history.clear()
        self.refresh()

    def _on_show_history_file(self, path: str) -> None:
        if not ProcessLauncher.open_file_explorer(path):
            self._say("That log file isn’t there any more.", "error")

    def _on_reveal_failed(self, path: str) -> None:
        self._say(f"That scene isn’t there any more: {path}", "error")

    REOPEN_WAIT_S = 300   # how long a "Reopen" waits for its Maya to show up

    def _select_pid(self, pid: int) -> None:
        """Shows the log of the Maya with process id `pid` (an ended one)."""
        if pid == self._selected_pid and self._history_selected is None:
            return
        self._history_selected = None
        self._selected_pid = pid
        self._show_log()
        self.refresh()

    def _on_show_log_file(self, pid: int) -> None:
        info = self._ended.get(pid)
        if info is not None and info["file"] is not None:
            ProcessLauncher.open_file_explorer(info["file"])

    def _on_dismiss_ended(self, pid: int) -> None:
        self._ended.pop(pid, None)
        self._logs.pop(pid, None)
        self._problems.pop(pid, None)
        if self._selected_pid == pid:
            self._selected_pid = 0
            self._log_view.clear_entries()
        self.refresh()

    def _add_to_log(self, pid: int, level: str, text: str) -> None:
        """A line of ours in Maya `pid`'s log (console input / output) — not counted as a problem."""
        now = time.time()
        self._logs.setdefault(pid, []).append((level, text, now))
        if pid == self._selected_pid:
            self._log_view.append_entry(level, text, now)

    def _on_level_changed(self, option: str) -> None:
        """Problems / All — for every connected Maya (and those that join later)."""
        self._log_all = option == self.LOG_ALL
        for session in self._server.sessions():
            self._server.request(session.session_id, protocol.SET_LOG_LEVEL, **{"all": self._log_all})

    def _on_wrap_toggled(self, wrap: bool) -> None:
        self._log_view.set_wrap(wrap)
        if self._settings is not None:
            self._settings["log_wrap"] = wrap

    def _on_clear_log(self) -> None:
        self._logs.pop(self._selected_pid, None)
        self._problems.pop(self._selected_pid, None)
        self._log_view.clear_entries()
        self.refresh()
