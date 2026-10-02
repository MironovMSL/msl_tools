# tools/desktop/maya_gate/sessions_tab.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import protocol
from msl_tools.msl.core.link.session import MayaSession
from msl_tools.msl.ui.maya_link.server import MayaLinkServer
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog


class _SessionRow(qt.QtWidgets.QWidget):
    """Private: one running Maya — a live dot, "Maya 2025", its environment,
    the open scene, a "boost" mark, what can be asked of it (quiet text
    buttons), and how long it has been connected. The row only says what
    was clicked; the tab talks to Maya."""

    HEIGHT = 30
    DOT_SIZE = 8

    report_requested = qt.QtCore.Signal(int)    # session id
    reload_requested = qt.QtCore.Signal(int)
    plugins_requested = qt.QtCore.Signal(int)

    def __init__(self, session: MayaSession, parent=None):
        super().__init__(parent)
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
        self.scene_label = qt.QtWidgets.QLabel()
        self.scene_label.setObjectName("sessionScene")
        # The scene's name is what gives way in a narrow window (clipped), not the rest.
        self.scene_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self.time_label = qt.QtWidgets.QLabel()
        self.time_label.setObjectName("sessionTime")
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
        layout.addWidget(self.scene_label, 1)
        layout.addWidget(self.plugins_button)
        layout.addWidget(self.reload_button)
        layout.addWidget(self.report_button)
        layout.addWidget(self.time_label)
        self.set_session(session)

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
        self.scene_label.setText(session.scene_name)
        self.time_label.setText(session.connected_for())
        self.setToolTip(f"Maya {session.full_version or session.version}  ·  process {session.pid}\n"
                        f"Scene: {session.scene or 'untitled'}\n"
                        f"msl_tools {session.msl_version} in that Maya")


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

    Colors: maya_gate.qss (SessionsTab ...).
    """

    REFRESH_MS = 30_000  # "12 min" labels
    MESSAGE_MS = 8000    # how long the last request's outcome stays
    REPORT_TIMEOUT_MS = 15_000
    RELOAD_TIMEOUT_MS = 20_000
    PLUGINS_TIMEOUT_MS = 180_000  # loading heavy plug-ins takes Maya a while

    def __init__(self, server: MayaLinkServer, parent=None):
        super().__init__(parent)
        self._server = server
        self._rows: dict[int, _SessionRow] = {}

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
        self._list_layout.addStretch(1)
        self._scroll = StableScrollArea()
        self._scroll.setObjectName("sessionsScroll")
        self._scroll.setWidget(self._list)

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
        layout.addLayout(header)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._message_label)
        layout.addWidget(self._hint_label)

        self._timer = qt.QtCore.QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._server.sessions_changed.connect(self.refresh)
        self._server.listening_changed.connect(self.refresh)
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
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
                self._rows[session_id] = row
                self._list_layout.insertWidget(index, row)
            else:
                row.set_session(session)

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
        self._empty_label.setVisible(not count)

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
