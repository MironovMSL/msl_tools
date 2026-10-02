# tools/desktop/maya_gate/sessions_tab.py
import os
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import protocol
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.core.link.session import MayaSession
from msl_tools.msl.tools.desktop.maya_gate.session_history import SessionHistory, SessionRecord
from msl_tools.msl.ui.maya_link.server import MayaLinkServer
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.widgets.atoms.editors import CodeEditor, LogView
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog


class _ConsoleInput(CodeEditor):
    """Private: the console's input — a small Python editor. Ctrl+Enter
    sends it; Ctrl+Up / Ctrl+Down walk through what was sent before."""

    HEIGHT = 74
    HISTORY_KEPT = 50

    run_requested = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setPlaceholderText("Python for the selected Maya \u2014 Ctrl+Enter runs it, Ctrl+Up / Down: earlier code")
        self._history: list[str] = []
        self._history_index = 0   # == len(history): the line being written, not an old one
        self._draft = ""

    def remember(self, code: str) -> None:
        """Adds `code` to the history (called once it was sent)."""
        if code and (not self._history or self._history[-1] != code):
            self._history.append(code)
            del self._history[:-self.HISTORY_KEPT]
        self._history_index = len(self._history)
        self._draft = ""

    def keyPressEvent(self, event) -> None:
        control = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        if control and key in (qt.QtCore.Qt.Key.Key_Return, qt.QtCore.Qt.Key.Key_Enter):
            self.run_requested.emit()
        elif control and key in (qt.QtCore.Qt.Key.Key_Up, qt.QtCore.Qt.Key.Key_Down) and self._history:
            self._walk_history(-1 if key == qt.QtCore.Qt.Key.Key_Up else 1)
        else:
            super().keyPressEvent(event)

    def _walk_history(self, step: int) -> None:
        if self._history_index == len(self._history):
            self._draft = self.toPlainText()  # what was being written comes back at the end
        self._history_index = max(0, min(len(self._history), self._history_index + step))
        at_end = self._history_index == len(self._history)
        self.setPlainText(self._draft if at_end else self._history[self._history_index])
        self.moveCursor(qt.QtGui.QTextCursor.MoveOperation.End)


class _SceneLabel(qt.QtWidgets.QLabel):
    """Private: a scene's file name — "hero_rig_v07.ma", with a "*" while it
    has unsaved changes (as in Maya's title bar). When the scene is a file,
    the NAME (not the empty space after it) is a link: a click shows the file
    in the system's file manager, a right click offers that and "Copy path".

    Signals:
        reveal_failed(str) — neither the file nor its folder is there any more.
    """

    reveal_failed = qt.QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionScene")
        # The scene's name is what gives way in a narrow window (clipped), not the rest.
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self._path = ""
        self._pressed = False

    def set_scene(self, path: str, modified: bool = False) -> None:
        self._path = path
        self.setText((os.path.basename(path) if path else "untitled") + ("*" if modified else ""))
        lines = [path or "This scene hasn’t been saved to a file yet."]
        if modified:
            lines.append("It has unsaved changes.")
        if path:
            lines.append("Click: show in folder  ·  right click: copy the path")
        self.setToolTip(chr(10).join(lines))

    def reveal(self) -> None:
        """Shows the scene file in the file manager (its folder, if the file is gone)."""
        path = Path(self._path)
        target = path if path.exists() else path.parent
        if not (self._path and target.exists() and ProcessLauncher.open_file_explorer(target)):
            self.reveal_failed.emit(self._path)

    def _over_name(self, event) -> bool:
        return bool(self._path) and event.position().x() <= self.fontMetrics().horizontalAdvance(self.text())

    def _set_hover(self, hover: bool) -> None:
        if bool(self.property("hover")) != hover:
            self.setProperty("hover", hover)  # maya_gate.qss: QLabel#sessionScene[hover="true"]
            repolish(self)
            if hover:
                self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()

    def mouseMoveEvent(self, event) -> None:
        self._set_hover(self._over_name(event))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self._over_name(event):
            self._pressed = True
            event.accept()  # a click on the name is for the file, not for selecting the row
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed:
            self._pressed = False
            if self._over_name(event):
                self.reveal()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        if not self._path:
            return
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.addAction("Show in folder").triggered.connect(self.reveal)
        menu.addAction("Copy path").triggered.connect(
            lambda: qt.QtGui.QGuiApplication.clipboard().setText(self._path))
        self._menu = menu  # for tests; the menu deletes itself on close
        menu.popup(event.globalPos())


class _SessionRow(qt.QtWidgets.QWidget):
    """Private: one running Maya — a live dot, "Maya 2025", its environment,
    the open scene, a "boost" mark, what can be asked of it (quiet text
    buttons), how many errors / warnings it has printed, and how long it
    has been connected. A click on the row selects it (its log is shown
    below the list). The row only says what was clicked; the tab talks to
    Maya."""

    HEIGHT = 30
    DOT_SIZE = 8

    report_requested = qt.QtCore.Signal(int)    # session id
    reload_requested = qt.QtCore.Signal(int)
    plugins_requested = qt.QtCore.Signal(int)
    selected = qt.QtCore.Signal(int)

    def __init__(self, session: MayaSession, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionRow")
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)  # for the selected tint (QSS)
        self.setFixedHeight(self.HEIGHT)
        self.dot = qt.QtWidgets.QLabel()
        self.dot.setObjectName("sessionDot")
        self.dot.setFixedSize(self.DOT_SIZE, self.DOT_SIZE)
        self.version_label = qt.QtWidgets.QLabel()
        self.version_label.setObjectName("sessionVersion")
        self.environment_label = qt.QtWidgets.QLabel()
        self.environment_label.setObjectName("sessionEnvironment")
        self.boost_label = qt.QtWidgets.QLabel("boost")
        self.boost_label.setObjectName("sessionBoost")
        self.busy_label = qt.QtWidgets.QLabel("busy")
        self.busy_label.setObjectName("sessionBusy")
        self.busy_label.setToolTip("This Maya isn\u2019t answering right now: it is working "
                                   "(a long script, a heavy scene).\nRequests wait until it is free.")
        self.scene_label = _SceneLabel()
        self.time_label = qt.QtWidgets.QLabel()
        self.time_label.setObjectName("sessionTime")
        self.errors_label = qt.QtWidgets.QLabel()
        self.errors_label.setObjectName("sessionErrors")
        self.warnings_label = qt.QtWidgets.QLabel()
        self.warnings_label.setObjectName("sessionWarnings")
        self.plugins_button = self._action("Plug-ins", "Load plug-ins that boost start left out \u2014 "
                                                       "in this running Maya, no restart")
        self.reload_button = self._action("Reload code", "Re-read msl_tools from disk in this Maya and rebuild "
                                                         "the MSL menu\n(open windows keep their old code until reopened)")
        self.report_button = self._action("Report", "How this Maya was started: environment, preferences, "
                                                    "variables, userSetup files, plug-ins")
        self.plugins_button.clicked.connect(lambda: self.plugins_requested.emit(self.session_id))
        self.reload_button.clicked.connect(lambda: self.reload_requested.emit(self.session_id))
        self.report_button.clicked.connect(lambda: self.report_requested.emit(self.session_id))

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(self.dot)
        layout.addWidget(self.version_label)
        layout.addWidget(self.environment_label)
        layout.addWidget(self.boost_label)
        layout.addWidget(self.busy_label)
        layout.addWidget(self.scene_label, 1)
        layout.addWidget(self.errors_label)
        layout.addWidget(self.warnings_label)
        layout.addWidget(self.plugins_button)
        layout.addWidget(self.reload_button)
        layout.addWidget(self.report_button)
        layout.addWidget(self.time_label)
        self.set_session(session)
        self.set_problems(0, 0)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.selected.emit(self.session_id)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) != selected:
            self.setProperty("selected", selected)  # maya_gate.qss: QWidget#sessionRow[selected="true"]
            repolish(self)

    def set_problems(self, errors: int, warnings: int) -> None:
        """Counters of what this Maya printed since it connected (or since "Clear")."""
        self.errors_label.setText(str(errors))
        self.errors_label.setToolTip(f"{errors} error(s) in this Maya\u2019s Script Editor")
        self.errors_label.setVisible(errors > 0)
        self.warnings_label.setText(str(warnings))
        self.warnings_label.setToolTip(f"{warnings} warning(s) in this Maya\u2019s Script Editor")
        self.warnings_label.setVisible(warnings > 0)

    @staticmethod
    def _action(text: str, tooltip: str) -> qt.QtWidgets.QPushButton:
        button = qt.QtWidgets.QPushButton(text)
        button.setObjectName("sessionAction")  # maya_gate.qss: a quiet accent link
        button.setFlat(True)
        button.setToolTip(tooltip)
        button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        return button

    def set_busy(self, busy: bool) -> None:
        """While Maya works on a request, nothing else can be asked of it."""
        for button in (self.plugins_button, self.reload_button, self.report_button):
            button.setEnabled(not busy)

    def set_session(self, session: MayaSession) -> None:
        self.session_id = session.session_id
        self.version_label.setText(f"Maya {session.version}")
        self.environment_label.setText(session.environment)
        # Safe here (unlike on a parentless widget): the labels already belong to this row.
        self.environment_label.setVisible(bool(session.environment))
        self.boost_label.setVisible(session.boosted)
        self.plugins_button.setVisible(bool(session.skipped))
        self.busy_label.setVisible(session.busy)
        state = "busy" if session.busy else ""
        if self.dot.property("state") != state:
            self.dot.setProperty("state", state)  # maya_gate.qss: QLabel#sessionDot[state]
            repolish(self.dot)
        self.scene_label.set_scene(session.scene, session.modified)
        self.time_label.setText(session.connected_for())
        self.setToolTip(chr(10).join([
            f"Maya {session.full_version or session.version}  ·  process {session.pid}",
            f"Scene: {session.scene or 'untitled'}" + (" (unsaved changes)" if session.modified else ""),
            f"msl_tools {session.msl_version} in that Maya"]))


class _EndedRow(qt.QtWidgets.QWidget):
    """Private: a Maya that is gone without saying goodbye (it crashed or was
    killed). Stays in the list until dismissed; a click shows its log."""

    selected = qt.QtCore.Signal(int)        # pid
    file_requested = qt.QtCore.Signal(int)
    dismissed = qt.QtCore.Signal(int)

    def __init__(self, session: MayaSession, when: float, has_file: bool, parent=None):
        super().__init__(parent)
        self.pid = session.pid
        self.setObjectName("sessionRow")
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(_SessionRow.HEIGHT)

        dot = qt.QtWidgets.QLabel()
        dot.setObjectName("sessionDot")
        dot.setProperty("state", "ended")
        dot.setFixedSize(_SessionRow.DOT_SIZE, _SessionRow.DOT_SIZE)
        version_label = qt.QtWidgets.QLabel(f"Maya {session.version}")
        version_label.setObjectName("sessionVersion")
        environment_label = qt.QtWidgets.QLabel(session.environment)
        environment_label.setObjectName("sessionEnvironment")
        ended_label = qt.QtWidgets.QLabel("ended unexpectedly at " + time.strftime("%H:%M", time.localtime(when))
                                          + (" · unsaved changes" if session.modified else ""))
        ended_label.setObjectName("sessionEnded")
        ended_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        file_button = _SessionRow._action("Log file", "Show the log saved when this Maya went away")
        file_button.clicked.connect(lambda: self.file_requested.emit(self.pid))
        dismiss_button = _SessionRow._action("Dismiss", "Remove this line (the saved log file stays)")
        dismiss_button.clicked.connect(lambda: self.dismissed.emit(self.pid))

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(dot)
        layout.addWidget(version_label)
        layout.addWidget(environment_label)
        layout.addWidget(ended_label, 1)
        layout.addWidget(file_button)
        layout.addWidget(dismiss_button)
        environment_label.setVisible(bool(session.environment))  # safe: it already belongs to this row
        file_button.setVisible(has_file)
        self.setToolTip(chr(10).join([
            f"Maya {session.full_version or session.version}  ·  process {session.pid}",
            "Its connection dropped without a goodbye: Maya crashed or was closed by force.",
            f"Scene at the time: {session.scene or 'untitled'}" + (" (with unsaved changes)" if session.modified else "")]))

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.selected.emit(self.pid)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) != selected:
            self.setProperty("selected", selected)
            repolish(self)


class _HistoryRow(qt.QtWidgets.QWidget):
    """Private: a Maya session that is over (a SessionRecord) — shown while
    nothing is running. A hollow dot = it quit, a red one = it ended
    unexpectedly (then with a link to the log saved at that moment); the
    scene's name is the same link as in a live row."""

    file_requested = qt.QtCore.Signal(str)   # path of the saved log

    def __init__(self, record: SessionRecord, parent=None):
        super().__init__(parent)
        self.record = record
        self.setObjectName("sessionRow")
        self.setFixedHeight(_SessionRow.HEIGHT)

        dot = qt.QtWidgets.QLabel()
        dot.setObjectName("sessionDot")
        dot.setProperty("state", "closed" if record.clean else "ended")
        dot.setFixedSize(_SessionRow.DOT_SIZE, _SessionRow.DOT_SIZE)
        version_label = qt.QtWidgets.QLabel(f"Maya {record.version}")
        version_label.setObjectName("sessionVersion")
        version_label.setProperty("past", True)
        environment_label = qt.QtWidgets.QLabel(record.environment)
        environment_label.setObjectName("sessionEnvironment")
        self.scene_label = _SceneLabel()
        self.scene_label.set_scene(record.scene, record.modified)
        self.scene_label.setProperty("past", True)
        self.outcome_label = qt.QtWidgets.QLabel("closed" if record.clean else "ended unexpectedly")
        self.outcome_label.setObjectName("sessionOutcome")
        self.outcome_label.setProperty("state", "" if record.clean else "error")
        self.time_label = qt.QtWidgets.QLabel(f"{record.ended_text()}  ·  {record.duration_text()}")
        self.time_label.setObjectName("sessionTime")

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(dot)
        layout.addWidget(version_label)
        layout.addWidget(environment_label)
        layout.addWidget(self.scene_label, 1)
        layout.addWidget(self.outcome_label)
        if record.log_file:
            file_button = _SessionRow._action("Log file", "Show the log saved when this Maya went away")
            file_button.clicked.connect(lambda: self.file_requested.emit(self.record.log_file))
            layout.addWidget(file_button)
        layout.addWidget(self.time_label)
        if not record.environment:
            environment_label.hide()
        lines = [f"Maya {record.version}  ·  process {record.pid}",
                 "Started " + time.strftime("%d %b %H:%M", time.localtime(record.connected_at))
                 + ", " + ("closed " if record.clean else "ended unexpectedly ")
                 + time.strftime("%d %b %H:%M", time.localtime(record.ended_at)) + f" ({record.duration_text()})",
                 f"Scene at the end: {record.scene or 'untitled'}"
                 + (" (with unsaved changes)" if record.modified else "")]
        if not record.clean:
            lines.append("Its connection dropped without a goodbye: Maya crashed or was closed by force.")
        self.setToolTip(chr(10).join(lines))


class SessionsTab(qt.QtWidgets.QWidget):
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
    survives a hub restart). While nothing is running the list shows those
    "Recent sessions" instead of an empty box. A link restart ("Reload
    code") and the hub's own shutdown are not ends of a session.

    The console (under the log, only while the selected Maya allows it —
    one started in a Dev environment): a small Python editor; Ctrl+Enter or
    "Run" sends the code to that Maya (RUN_PYTHON), which runs it like its
    Script Editor would. The code, what it printed, its result or its
    traceback go into that Maya's log. Whether a Maya accepts code is
    decided by Maya itself (it was launched with MSL_GATE_CONSOLE=1); the
    tab only hides the console where it would be refused.

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
    HISTORY_CAPTION_HEIGHT = 24

    def __init__(self, server: MayaLinkServer, history: SessionHistory | None = None, parent=None):
        super().__init__(parent)
        self._server = server
        self._history = history                   # None: finished sessions aren't kept
        self._history_rows: list[_HistoryRow] = []
        self._history_key: list = []              # what the history rows on screen were built from
        self._seen = False                        # the history file is first read when the tab is shown
        self._names: dict[int, str] = {}          # pid -> "Maya 2025 · Dev" (for a closed Maya's log title)
        self._rows: dict[int, _SessionRow] = {}
        self._logs: dict[int, list] = {}          # pid -> [(level, text, time), ...]
        self._problems: dict[int, list] = {}      # pid -> [errors, warnings]
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
        caption_label = qt.QtWidgets.QLabel("Recent sessions")
        caption_label.setObjectName("sessionsSummary")
        self._clear_history_button = _SessionRow._action("Clear", "Forget these sessions (saved log files stay)")
        caption_layout = qt.QtWidgets.QHBoxLayout(self._history_caption)
        caption_layout.setContentsMargins(12, 0, 6, 0)
        caption_layout.addWidget(caption_label, 1)
        caption_layout.addWidget(self._clear_history_button)
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
        self._log_view = LogView("Warnings and errors from the selected Maya\u2019s Script Editor appear here.")

        self._console_input = _ConsoleInput()
        self._run_button = qt.QtWidgets.QPushButton("Run")
        self._run_button.setProperty("primary", True)
        self._run_button.setToolTip("Run this code in the selected Maya (Ctrl+Enter)")
        self._console = qt.QtWidgets.QWidget()
        console_layout = qt.QtWidgets.QHBoxLayout(self._console)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(6)
        console_layout.addWidget(self._console_input, 1)
        console_layout.addWidget(self._run_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignBottom)
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
        log_header.addWidget(self._copy_log_button)
        log_header.addWidget(self._clear_log_button)
        log_header.addWidget(self._level_switch)

        layout.addLayout(header)
        layout.addWidget(self._scroll)
        layout.addWidget(self._message_label)
        layout.addLayout(log_header)
        layout.addWidget(self._log_view, 1)
        layout.addWidget(self._console)
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
        for session_id in [key for key in self._rows if key not in sessions]:
            row = self._rows.pop(session_id)
            row.hide()
            row.deleteLater()
        for index, (session_id, session) in enumerate(sessions.items()):
            row = self._rows.get(session_id)
            if row is None:
                row = _SessionRow(session)
                row.report_requested.connect(self._on_report)
                row.reload_requested.connect(self._on_reload)
                row.plugins_requested.connect(self._on_plugins)
                row.selected.connect(self._select_session)
                row.scene_label.reveal_failed.connect(self._on_reveal_failed)
                self._rows[session_id] = row
                if self._log_all:  # a Maya that just joined (or reloaded) starts on "Problems"
                    self._server.request(session_id, protocol.SET_LOG_LEVEL, **{"all": True})
                self._list_layout.insertWidget(index, row)
            else:
                row.set_session(session)

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
                row = _EndedRow(info["session"], info["when"], info["file"] is not None)
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
        # Nothing running: the list shows the sessions that are over instead of an empty box.
        records = self._history_records() if not count and not self._ended else []
        self._show_history(records)
        self._empty_label.setVisible(not count and not self._ended and not records)
        if records:
            self._summary_label.setText("· none running")

        # The list is as tall as its rows (up to LIST_ROWS_SHOWN); the log gets the rest.
        listed = count + len(self._ended)
        if records:
            shown = min(len(records), self.LIST_ROWS_SHOWN)
            self._scroll.setFixedHeight(self.HISTORY_CAPTION_HEIGHT + shown * _SessionRow.HEIGHT + 10)
        else:
            shown = max(min(listed, self.LIST_ROWS_SHOWN), 1)
            self._scroll.setFixedHeight(shown * _SessionRow.HEIGHT + 10 + (26 if not listed else 0))

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
        if not selected_here and (not self._selected_pid or self._selected_pid in expired or left_empty):
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
        self._update_log_title(pids.get(self._selected_pid))
        # The console: only for a selected Maya that is here and accepts code.
        selected = pids.get(self._selected_pid)
        self._console.setVisible(selected is not None and selected.console)

    # --- the log ---------------------------------------------------------------------

    def _session_by_pid(self, pid: int) -> MayaSession | None:
        return next((session for session in self._server.sessions() if session.pid == pid), None)

    def _update_log_title(self, session: MayaSession | None) -> None:
        if session is not None:
            text = "· " + self._names.get(session.pid, f"Maya {session.version}")
        elif self._selected_pid in self._ended:
            ended = self._ended[self._selected_pid]["session"]
            text = (f"· Maya {ended.version}" + (f" · {ended.environment}" if ended.environment else "")
                    + " · ended unexpectedly")
        elif self._selected_pid and self._logs.get(self._selected_pid):
            # A Maya that closed: its log stays readable for a while. Without a log there is nothing to title.
            text = "· " + self._names.get(self._selected_pid, "that Maya") + " · closed"
        else:
            text = ""
        self._log_section.setText(text)

    def _select_session(self, session_id: int) -> None:
        session = self._server.session(session_id)
        if session is None or session.pid == self._selected_pid:
            return
        if self._selected_pid in self._gone:  # leaving a closed Maya's log: it isn't kept any longer
            self._logs.pop(self._selected_pid, None)
            self._problems.pop(self._selected_pid, None)
            self._gone.pop(self._selected_pid, None)
        self._selected_pid = session.pid
        self._show_log()
        self.refresh()

    def _show_log(self) -> None:
        self._log_view.set_entries(self._logs.get(self._selected_pid, []))

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
        """A session is gone. Every real end goes into the history; one without
        a goodbye (a crash, a killed process) also has its log written to a
        file and stays in the list until dismissed."""
        if reason in (protocol.BYE_RESTART, MayaLinkServer.ENDED_BY_HUB):
            return  # its link restarts ("Reload code") / the hub is the one leaving: that Maya is still running
        now = time.time()
        file = None
        if not clean:
            file = self._save_log(session, now)
            self._ended[session.pid] = {"session": session, "when": now, "file": file}
            self._gone.pop(session.pid, None)
            self._say(f"Maya {session.version} ended unexpectedly — its log was saved.", "error")
            if not self.isVisible():
                self._server.set_unread_errors(self._server.unread_errors() + 1)
        if self._history is not None:
            self._history.add(SessionRecord(
                pid=session.pid, version=session.version, environment=session.environment, scene=session.scene,
                modified=session.modified, boosted=session.boosted, connected_at=session.connected_at,
                ended_at=now, clean=clean, log_file=str(file) if file is not None else ""))
        self.refresh()

    # --- the sessions that are over ---------------------------------------------------------

    def _history_records(self) -> list:
        """What the "Recent sessions" list shows. Nothing before the tab was first
        shown: the history file isn't read while the page is being built."""
        if self._history is None or not self._seen:
            return []
        return self._history.records()

    def _show_history(self, records: list) -> None:
        """Brings the history rows in line with `records` ([] = none shown)."""
        key = [(record.pid, record.ended_at) for record in records]
        if key == self._history_key:
            return
        self._history_key = key
        for row in self._history_rows:
            row.hide()
            row.deleteLater()
        self._history_rows = []
        self._history_caption.setVisible(bool(records))
        first = self._list_layout.indexOf(self._history_caption) + 1
        for offset, record in enumerate(records):
            row = _HistoryRow(record)
            row.file_requested.connect(self._on_show_history_file)
            row.scene_label.reveal_failed.connect(self._on_reveal_failed)
            self._history_rows.append(row)
            self._list_layout.insertWidget(first + offset, row)

    def _on_clear_history(self) -> None:
        if self._history is not None:
            self._history.clear()
        self.refresh()

    def _on_show_history_file(self, path: str) -> None:
        if not ProcessLauncher.open_file_explorer(path):
            self._say("That log file isn’t there any more.", "error")

    def _on_reveal_failed(self, path: str) -> None:
        self._say(f"That scene isn’t there any more: {path}", "error")

    def _save_log(self, session: MayaSession, when: float) -> Path | None:
        """Writes what that Maya reported to logs/desktop/maya_gate/sessions/. None if it couldn't."""
        try:
            folder = Path(Resources().fsManager.logsDesktop) / "maya_gate" / "sessions"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(when))
            path = folder / f"maya{session.version}_{stamp}_pid{session.pid}.log"
            lines = [f"Maya {session.full_version or session.version}, process {session.pid}",
                     f"Environment: {session.environment or '-'}   boost: {'on' if session.boosted else 'off'}",
                     f"Scene: {session.scene or 'untitled'}",
                     f"Unsaved changes in the scene: {'yes' if session.modified else 'no'}",
                     "Connected: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.connected_at)),
                     "Ended unexpectedly: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when)),
                     "", "--- what its Script Editor reported (warnings and errors; everything if \"All\" was on) ---"]
            entries = self._logs.get(session.pid, [])
            for level, text, at in entries:
                first, *rest = (text.rstrip("\n").split("\n") or [""])
                lines.append(f"{time.strftime('%H:%M:%S', time.localtime(at))}  {level:7s}  {first}")
                lines += ["                   " + line for line in rest]
            if not entries:
                lines.append("(nothing was reported)")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path
        except OSError:
            return None

    def _select_pid(self, pid: int) -> None:
        """Shows the log of the Maya with process id `pid` (an ended one)."""
        if pid == self._selected_pid:
            return
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

    # --- the console -------------------------------------------------------------------

    def _on_run_code(self) -> None:
        """Sends the console's code to the selected Maya; code, output, result and
        traceback all land in that Maya's log."""
        session = self._session_by_pid(self._selected_pid)
        code = self._console_input.toPlainText().strip("\n")
        if session is None or not session.console or not code.strip() or not self._run_button.isEnabled():
            return
        pid = session.pid
        self._add_to_log(pid, protocol.LOG_INPUT, code)
        self._console_input.remember(code)
        self._console_input.clear()
        self._run_button.setEnabled(False)

        def done(reply: dict) -> None:
            self._run_button.setEnabled(True)
            row = self._rows.get(session.session_id)
            if row is not None:
                row.set_busy(False)
            data = reply.get("data") or {}
            if not reply.get("success"):
                self._add_to_log(pid, protocol.LOG_ERROR, reply.get("error") or "the request failed")
                return
            if data.get("output"):
                self._add_to_log(pid, protocol.LOG_INFO, str(data["output"]).rstrip("\n"))
            if data.get("traceback"):
                self._add_to_log(pid, protocol.LOG_ERROR, str(data["traceback"]).rstrip("\n"))
            elif data.get("result"):
                self._add_to_log(pid, protocol.LOG_INFO, str(data["result"]))

        row = self._rows.get(session.session_id)
        if row is not None:
            row.set_busy(True)
        self._server.request(session.session_id, protocol.RUN_PYTHON, on_reply=done,
                             timeout_ms=self.CONSOLE_TIMEOUT_MS, code=code)

    def _on_level_changed(self, option: str) -> None:
        """Problems / All — for every connected Maya (and those that join later)."""
        self._log_all = option == self.LOG_ALL
        for session in self._server.sessions():
            self._server.request(session.session_id, protocol.SET_LOG_LEVEL, **{"all": self._log_all})

    def _on_clear_log(self) -> None:
        self._logs.pop(self._selected_pid, None)
        self._problems.pop(self._selected_pid, None)
        self._log_view.clear_entries()
        self.refresh()

    # --- requests to a running Maya ------------------------------------------------

    def _say(self, text: str, state: str = "") -> None:
        """The outcome of the last request, under the list ("" / "success" / "error")."""
        self._message_label.setText(text)
        if self._message_label.property("state") != state:
            self._message_label.setProperty("state", state)  # maya_gate.qss: QLabel#sessionsMessage[state]
            repolish(self._message_label)
        self._message_label.show()
        self._message_timer.start()

    def _ask(self, session_id: int, name: str, on_done, timeout_ms: int, **data) -> None:
        """Sends request `name`; the row is busy until `on_done(session, reply)`
        ran. A failed reply is reported here and `on_done` isn't called."""
        session = self._server.session(session_id)
        if session is None:
            return
        row = self._rows.get(session_id)
        if row is not None:
            row.set_busy(True)

        def finished(reply: dict) -> None:
            current = self._rows.get(session_id)
            if current is not None:
                current.set_busy(False)
            if reply.get("success"):
                on_done(session, reply.get("data") or {})
            else:
                self._say(f"Maya {session.version}: {reply.get('error') or 'the request failed'}", "error")

        self._server.request(session_id, name, on_reply=finished, timeout_ms=timeout_ms, **data)

    def _on_report(self, session_id: int) -> None:
        self._ask(session_id, protocol.LAUNCH_REPORT,
                  lambda session, data: TextDialog.show_for(
                      self, f"Launch report \u00b7 Maya {session.version} \u00b7 {session.environment or 'no environment'}",
                      str(data.get("text", "")).strip("\n")),
                  self.REPORT_TIMEOUT_MS)

    def _on_reload(self, session_id: int) -> None:
        def done(session: MayaSession, data: dict) -> None:
            menu = ", MSL menu rebuilt" if data.get("menu") else ""
            self._say(f"Maya {session.version}: msl_tools reloaded \u2014 {data.get('modules', 0)} modules will be "
                      f"re-read from disk{menu}.", "success")

        self._ask(session_id, protocol.RELOAD_CODE, done, self.RELOAD_TIMEOUT_MS)

    def _on_plugins(self, session_id: int) -> None:
        """Asks which of the skipped plug-ins are loaded by now, then offers the rest."""
        self._ask(session_id, protocol.PLUGIN_STATE,
                  lambda session, data: self._show_plugins_menu(session, set(data.get("loaded") or [])),
                  self.REPORT_TIMEOUT_MS, names=list(self._server.session(session_id).skipped))

    def _show_plugins_menu(self, session: MayaSession, loaded: set) -> None:
        row = self._rows.get(session.session_id)
        if row is None:
            return
        waiting = [name for name in session.skipped if name not in loaded]
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if len(waiting) > 1:
            menu.addAction(f"Load all {len(waiting)}").triggered.connect(
                lambda: self._load_plugins(session.session_id, waiting))
            menu.addSeparator()
        for name in session.skipped:
            if name in loaded:
                action = menu.addAction(f"{name}  \u2014 loaded")
                action.setEnabled(False)
            else:
                menu.addAction(name).triggered.connect(
                    lambda _checked=False, name=name: self._load_plugins(session.session_id, [name]))
        self._plugins_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(row.plugins_button.mapToGlobal(qt.QtCore.QPoint(0, row.plugins_button.height())))

    def _load_plugins(self, session_id: int, names: list) -> None:
        def done(session: MayaSession, data: dict) -> None:
            loaded, failed = data.get("loaded") or [], data.get("failed") or {}
            parts = []
            if loaded:
                parts.append("loaded " + ", ".join(loaded))
            if failed:
                parts.append("failed: " + "; ".join(f"{name} ({why})" for name, why in failed.items()))
            self._say(f"Maya {session.version}: " + (" \u2014 ".join(parts) or "nothing to load") + ".",
                      "error" if failed else "success")

        self._say("Loading " + ", ".join(names) + "\u2026")
        self._ask(session_id, protocol.LOAD_PLUGINS, done, self.PLUGINS_TIMEOUT_MS, names=list(names))
