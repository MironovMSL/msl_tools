# tools/desktop/maya_gate/sessions_control.py
"""The Sessions tab's actions on a Maya: start / reopen / close / restart / force close,
and the requests to a running one."""
import os
import time

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import protocol
from msl_tools.msl.core.link.session import MayaSession
from msl_tools.msl.core.environment.processes import is_process_running, terminate_process
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.icon_manager import tinted_menu_icon
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.tools.desktop.maya_gate.session_rows import _duration


class _ControlMixin:
    """SessionsTab's actions on a Maya: start, reopen, close, restart, force close, and the
    requests to a running one (report, reload, plug-ins). A mixin: the state it uses is
    made in SessionsTab.__init__."""

    # --- starting, closing, restarting a Maya -----------------------------------------------

    def _start(self, version: str, environment: str, scene: str) -> None:
        """Asks the page to start Maya `version` in `environment` with `scene`; says how it went."""
        if self._launch is None:
            return
        error = self._launch(version, environment, scene)
        if error:
            self._say(error, "error")
        else:
            self._say(f"Starting Maya {version}" + (f" with {os.path.basename(scene)}" if scene else "") + "…")

    @staticmethod
    def _scene_key(version: str, environment: str, scene: str) -> tuple:
        return (str(version), str(environment), os.path.normcase(os.path.normpath(scene)) if scene else "")

    def _on_reopen_record(self, record) -> None:
        """"Reopen" on a finished session: starts that Maya again and remembers what it continues."""
        self._reopen_pending[self._scene_key(record.version, record.environment, record.scene)] = (record.key, time.time())
        self._start(record.version, record.environment, record.scene)

    def _link_reopened(self, sessions) -> None:
        """Ties running Mayas to the records they were reopened from (same version, environment and
        scene, connected after the click), and forgets the ties of Mayas that are gone."""
        now = time.time()
        self._reopen_pending = {key: value for key, value in self._reopen_pending.items()
                                if now - value[1] < self.REOPEN_WAIT_S}
        alive = set()
        for session in sessions:
            alive.add(session.pid)
            if session.pid in self._continues:
                continue
            key = self._scene_key(session.version, session.environment, session.scene)
            pending = self._reopen_pending.get(key)
            if pending is not None and session.connected_at >= pending[1] - 1:
                self._continues[session.pid] = pending[0]
                del self._reopen_pending[key]
        self._continues = {pid: key for pid, key in self._continues.items() if pid in alive}

    def _previous_record(self, pid: int):
        """The record of the session the running Maya `pid` continues (None if it continues none)."""
        key = self._continues.get(pid)
        if key is None or self._history is None:
            return None
        return next((record for record in self._history.records() if record.key == key), None)

    def _open_autosave(self, version: str, environment: str, autosave: str) -> None:
        """Starts Maya with an autosave file as its scene."""
        if not os.path.isfile(autosave):
            self._say(f"That autosave isn’t there any more: {autosave}", "error")
            return
        self._start(version, environment, autosave)

    def _on_reopen_ended(self, pid: int) -> None:
        info = self._ended.get(pid)
        if info is not None:
            session = info["session"]
            self._reopen_pending[self._scene_key(session.version, session.environment, session.scene)] = (
                (pid, info["when"]), time.time())
            self._start(session.version, session.environment, session.scene)

    def _menu_icon(self, name: str, sub_folder: str = "actions", danger: bool = False) -> qt.QtGui.QIcon:
        """A one-color icon for a menu item, in the theme's color (an empty icon if the file is missing)."""
        return tinted_menu_icon(UiResources().iconManager.get_icon(name, sub_folder=sub_folder),
                                self._menu_danger_color if danger else self._menu_icon_color,
                                self.devicePixelRatioF(), self.MENU_ICON_SIZE)

    def _on_row_menu(self, session_id: int) -> None:
        """Everything that can be asked of one running Maya, as a menu under the
        row's button. While that Maya works on a request, or doesn't answer at
        all, the requests are greyed out — and one that doesn't answer gets
        "Force close…"."""
        row, session = self._rows.get(session_id), self._server.session(session_id)
        if row is None or session is None:
            return
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.setToolTipsVisible(True)
        reachable = not row.pending and not session.busy

        def add(text: str, icon: tuple, tooltip: str, handler, danger: bool = False, enabled: bool = True) -> None:
            action = menu.addAction(self._menu_icon(*icon, danger=danger), text)
            action.setToolTip(tooltip)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False: handler())

        previous = self._previous_record(session.pid)
        if previous is not None:
            add("Log of the previous session", ("report", "actions"),
                f"This Maya was reopened from the session that ended {previous.ended_text()} "
                f"({previous.outcome_text()}): show what that one reported", lambda: self._select_history(previous.key))
        add("Launch report", ("report", "actions"), "How this Maya was started: environment, preferences, "
            "variables, userSetup files, plug-ins", lambda: self._on_report(session_id), enabled=reachable)
        add("Reload code", ("code", "actions"), "Re-read msl_tools from disk in this Maya and rebuild the MSL menu"
            + chr(10) + "(open windows keep their old code until reopened)", lambda: self._on_reload(session_id),
            enabled=reachable)
        if session.skipped:
            add("Load plug-ins…", ("plugin", "plugins"), "Load plug-ins that boost start left out — in this "
                "running Maya, no restart", lambda: self._on_plugins(session_id), enabled=reachable)
        menu.addSeparator()
        if self._launch is not None:
            add("Restart Maya…", ("restart", "actions"), "Close this Maya and start it again: same version, "
                "environment and scene (asks first)", lambda: self._close_maya(session_id, restart=True),
                enabled=reachable)
        add("Close Maya…", ("power", "actions"), "Close this Maya (asks first)",
            lambda: self._close_maya(session_id, restart=False), danger=not session.busy, enabled=reachable)
        if session.busy:
            menu.addSeparator()
            add("Force close…", ("stop", "actions"), "This Maya isn’t answering. End its process at once — "
                "what wasn’t saved is lost (asks first)", lambda: self._force_close(session_id), danger=True)
        self._row_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(row.menu_button.mapToGlobal(qt.QtCore.QPoint(0, row.menu_button.height())))

    def _force_close(self, session_id: int) -> None:
        """Ends the process of a Maya that doesn't answer — after asking."""
        session = self._server.session(session_id)
        if session is None:
            return
        name = self._names.get(session.pid, f"Maya {session.version}")
        silent = ("for " + _duration(time.time() - session.busy_since)) if session.busy_since else "right now"
        details = [session.scene or "untitled scene"]
        if session.modified:
            details.append("It has unsaved changes." + (
                " Maya’s autosave is on: if it wrote one, “Open autosave” will offer it afterwards."
                if session.autosave else " Maya’s autosave is off — they can’t be brought back."))
        choice = ConfirmDialog.ask(
            self, f"Force close {name}",
            f"It hasn’t answered {silent}. It may only be busy — a long playblast, a cache, a heavy scene — "
            f"and come back by itself. Force closing ends it at once: what wasn’t saved is lost.",
            details=chr(10).join(details), choices=[("force", "Force close"), ("cancel", "Wait")], kind="danger")
        if choice != "force":
            return
        # The question was open a while: that Maya may have come back, or left by itself.
        session = self._server.session(session_id)
        if session is None:
            return
        if not session.busy:
            self._say(f"{name} answers again — it wasn’t closed.")
            return
        self._forced.add(session.pid)
        if not terminate_process(session.pid):
            self._forced.discard(session.pid)
            self._say(f"{name} couldn’t be closed — Windows refused.", "error")

    def _close_maya(self, session_id: int, restart: bool) -> None:
        """Closes (or restarts) a Maya after asking: unsaved changes are saved,
        dropped, or keep Maya open — never lost silently."""
        session = self._server.session(session_id)
        if session is None:
            return
        verb = "Restart" if restart else "Close"
        name = self._names.get(session.pid, f"Maya {session.version}")
        save = False
        if session.modified:
            choices = [("save", f"Save and {verb.lower()}")] if session.scene else []
            choices += [("discard", f"{verb} without saving"), ("cancel", "Cancel")]
            choice = ConfirmDialog.ask(
                self, f"{verb} {name}", f"{session.scene_name} has unsaved changes.",
                details=session.scene or "The scene has no file yet, so it can’t be saved from here.",
                choices=choices, kind="warning" if session.scene else "danger")
            if choice not in ("save", "discard"):
                return
            save = choice == "save"
        else:
            choice = ConfirmDialog.ask(
                self, f"{verb} {name}", f"{verb} this Maya? Its scene has no unsaved changes.",
                details=session.scene or None, choices=[("yes", verb), ("cancel", "Cancel")], kind="question")
            if choice != "yes":
                return
        scene = session.scene

        def done(session: MayaSession, _data: dict) -> None:
            self._say(f"{name} is closing" + (" and will start again." if restart else "."))
            if restart:
                self._restarts[session.pid] = (time.time(), session.version, session.environment, scene)

        self._ask(session_id, protocol.QUIT, done, self.QUIT_TIMEOUT_MS, save=save,
                  discard=session.modified and not save)

    def _start_when_gone(self, pid: int, version: str, environment: str, scene: str, deadline: float) -> None:
        """Starts the new Maya of a restart once the old one's process is gone —
        it said goodbye, but is still writing its preferences on the way out."""
        if is_process_running(pid):
            if time.time() < deadline:
                # With `self` as the context: the wait ends with the tab, never calls into a deleted one.
                qt.QtCore.QTimer.singleShot(
                    500, self, lambda: self._start_when_gone(pid, version, environment, scene, deadline))
            else:
                self._say(f"Maya {version} is still closing — start it again yourself once it is gone.", "error")
            return
        self._start(version, environment, scene)

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
        session = self._server.session(session_id)
        if session is None:  # it left while its menu was open
            return
        self._ask(session_id, protocol.PLUGIN_STATE,
                  lambda session, data: self._show_plugins_menu(session, set(data.get("loaded") or [])),
                  self.REPORT_TIMEOUT_MS, names=list(session.skipped))

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
        menu.popup(row.menu_button.mapToGlobal(qt.QtCore.QPoint(0, row.menu_button.height())))

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
