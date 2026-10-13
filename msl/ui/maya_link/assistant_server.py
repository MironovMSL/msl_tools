# ui/maya_link/assistant_server.py
"""The hub's door for an assistant: a second local server, beside the one
Mayas connect to (server.py), that answers a short fixed list of questions
about the connected Mayas (core/link/assistant.py).

Why a server of its own and not one more kind of peer on the Maya link: it
is OFF until the user switches it on, and it has its own token — what a
launched Maya is given must not open it.

Safety, as for the Maya link: 127.0.0.1 only; a connection is served only
after it proved it knows the token, the hub having proven itself first;
before that a peer may send 64 KB per message and has HELLO_TIMEOUT_MS.
Nothing that arrives is executed HERE: every request is looked up in
_HANDLERS, anything else is refused. One request carries code, `run_python`:
the hub hands it to the Maya it names exactly as the Sessions tab's console
does (protocol.RUN_PYTHON) - only while the user allowed code for the
assistant (`code_allowed`, off at first, a switch of its own), one run per
Maya at a time, and Maya's side still refuses it unless it was launched with
the console allowed. What was sent and what came back is announced
(code_started / code_finished) so the Sessions tab shows it in that Maya's log.
"""
import secrets

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import assistant
from msl_tools.msl.core.link import protocol
from msl_tools.msl.ui.maya_link.server import MayaLinkServer


class _Client:
    """Private: one accepted connection and where its handshake stands."""

    def __init__(self, socket: "qt.QtNetwork.QTcpSocket"):
        self.socket = socket
        self.decoder = protocol.FrameDecoder(max_body=protocol.MAX_BODY_BEFORE_AUTH)
        self.nonce = ""        # the client's, from its hello
        self.hub_nonce = ""    # what our welcome asked it to prove itself with
        self.proven = False


class AssistantServer(qt.QtCore.QObject):
    """Serves assistants from what `link` (the hub's MayaLinkServer) knows.

    It keeps its own LogBook of what the Mayas report — from the moment it
    is created, listening or not, so a log is there when access is switched on.

    Signals:
        listening_changed() — it started or stopped listening.
        clients_changed() — an assistant proved itself, or left.
        code_started(int, str) — (Maya's pid, code): an assistant's code went to that Maya.
        code_finished(int, dict) — (pid, the link's reply): it came back, or failed.
    """

    PORT_ATTEMPTS = 10
    HELLO_TIMEOUT_MS = 5000
    MAX_CLIENTS = 4
    SCREENSHOT_DELAY_MS = 350   # after opening a tool's page, before its picture is taken

    listening_changed = qt.QtCore.Signal()
    clients_changed = qt.QtCore.Signal()
    access_changed = qt.QtCore.Signal()   # the second switch (may it run code) was set
    code_started = qt.QtCore.Signal(int, str)
    code_finished = qt.QtCore.Signal(int, dict)

    _instance: "AssistantServer | None" = None

    @classmethod
    def instance(cls) -> "AssistantServer":
        """The hub's one assistant server, on the hub's one Maya link (created on first use, not listening)."""
        if cls._instance is None:
            cls._instance = cls(MayaLinkServer.instance())
        return cls._instance

    def __init__(self, link: MayaLinkServer, parent=None):
        super().__init__(parent)
        self._link = link
        self._server = qt.QtNetwork.QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._clients: list[_Client] = []
        self._token = ""
        self._config = None
        self.log = assistant.LogBook()
        link.log_received.connect(self._on_log)
        # Read from the config by ensure_listening() only: a server given its port by listen()
        # (a test) never opens the hub's config.
        self._code_allowed = False
        self._running: set[int] = set()          # pids with an assistant's code out
        self._launch = None        # set_launcher(): starts a Maya
        self._environments: list = []
        self._window = None        # set_window(): the hub's window
        self._HANDLERS = {assistant.SESSIONS: self._sessions, assistant.READ_LOG: self._read_log,
                          assistant.HUB_INFO: self._hub_info, assistant.LAUNCH_MAYA: self._launch_maya}

    # --- listening ---------------------------------------------------------------

    def _settings(self):
        if self._config is None:
            from msl_tools.msl.core.resources import Resources
            self._config = Resources().configsDesktopHubMng.get_config(
                assistant.CONFIG_NAME, defaults={"port": assistant.DEFAULT_PORT, "token": "", "enabled": False,
                                                 "code": False})
        return self._config

    def code_allowed(self) -> bool:
        """May an assistant run code in the connected Mayas (the user's second switch; off at first)."""
        return self._code_allowed

    def set_code_allowed(self, allowed: bool) -> None:
        """Remembers the second switch in the hub's config."""
        self._code_allowed = bool(allowed)
        self._settings()["code"] = self._code_allowed
        self.access_changed.emit()

    def running(self) -> set:
        """Pids of the Mayas that have an assistant's code out right now."""
        return set(self._running)

    def is_enabled(self) -> bool:
        """The user's switch (kept in the hub's config; off on a fresh install)."""
        return bool(self._settings()["enabled"])

    def set_enabled(self, enabled: bool) -> bool:
        """Remembers the switch and starts / stops listening. False if it couldn't listen."""
        self._settings()["enabled"] = bool(enabled)
        if enabled:
            return self.ensure_listening()
        self.close()
        return True

    def ensure_listening(self) -> bool:
        """Listens with the port / token of the hub's config if switched on (the token is made once)."""
        if not self.is_enabled():
            return False
        if self.is_listening():
            return True
        config = self._settings()
        self._code_allowed = bool(config["code"])
        token = str(config["token"] or "")
        if not token:
            token = secrets.token_hex(16)
            config["token"] = token
        try:
            port = int(config["port"])
        except (TypeError, ValueError):
            port = assistant.DEFAULT_PORT
        if not self.listen(port, token):
            return False
        if self.port() != port:
            config["port"] = self.port()   # the client reads the address from this file
        return True

    def listen(self, port: int, token: str) -> bool:
        """Listens on 127.0.0.1:`port` — or the first free of the next PORT_ATTEMPTS ports."""
        self._token = token
        for candidate in range(port, port + self.PORT_ATTEMPTS):
            if self._server.listen(qt.QtNetwork.QHostAddress(qt.QtNetwork.QHostAddress.SpecialAddress.LocalHost),
                                   candidate):
                self.listening_changed.emit()
                return True
        return False

    def close(self) -> None:
        """Stops listening and drops every assistant."""
        for client in list(self._clients):
            client.socket.abort()
        if self._server.isListening():
            self._server.close()
            self.listening_changed.emit()

    def is_listening(self) -> bool:
        return self._server.isListening()

    def port(self) -> int:
        return int(self._server.serverPort()) if self._server.isListening() else 0

    def clients(self) -> int:
        """How many assistants are connected and proven."""
        return sum(1 for client in self._clients if client.proven)

    # --- what the Mayas report -----------------------------------------------------

    def _on_log(self, session_id: int, entries: list) -> None:
        session = self._link.session(session_id)
        if session is not None:
            self.log.add(session.pid, entries)

    # --- connections ---------------------------------------------------------------

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if len(self._clients) >= self.MAX_CLIENTS:
                socket.abort()
                socket.deleteLater()
                continue
            client = _Client(socket)
            self._clients.append(client)
            socket.readyRead.connect(lambda client=client: self._on_ready_read(client))
            socket.disconnected.connect(lambda client=client: self._on_disconnected(client))
            qt.QtCore.QTimer.singleShot(self.HELLO_TIMEOUT_MS, lambda client=client: self._drop_if_silent(client))

    def _drop_if_silent(self, client: _Client) -> None:
        if client in self._clients and not client.proven:
            client.socket.abort()

    def _on_disconnected(self, client: _Client) -> None:
        if client not in self._clients:
            return
        self._clients.remove(client)
        try:
            client.socket.deleteLater()
            if client.proven:
                self.clients_changed.emit()
        except RuntimeError:
            pass  # the application is shutting down: Qt already deleted this server / the socket

    def _on_ready_read(self, client: _Client) -> None:
        try:
            messages = client.decoder.feed(bytes(client.socket.readAll().data()))
        except protocol.ProtocolError:
            client.socket.abort()
            return
        for message in messages:
            if client not in self._clients:
                return
            try:
                self._handle(client, message)
            except Exception:  # a well-framed message with wrong types in it: that peer is out of step
                client.socket.abort()
                return

    def _handle(self, client: _Client, message: dict) -> None:
        kind, name = message.get("type"), message.get("name")
        data = message.get("data") if isinstance(message.get("data"), dict) else {}
        if not client.proven:
            self._authenticate(client, kind, name, data)
            return
        if kind != protocol.REQUEST:
            return
        request_id = message.get("id")
        if not isinstance(request_id, int):
            client.socket.abort()
            return
        if name == assistant.RUN_PYTHON:
            self._run_python(client, request_id, data)   # answered when Maya is back
            return
        if name in self._FORWARDED:
            self._forward(client, request_id, name, data)
            return
        if name == assistant.HUB_SCREENSHOT:
            self._hub_screenshot(client, request_id, data)   # answered once the page has laid out
            return
        handler = self._HANDLERS.get(name)
        if handler is None:
            answer = protocol.reply(request_id, False, "MSL Tools doesn’t know the request “%s”." % name)
        else:
            answer = protocol.reply(request_id, **handler(data))
        client.socket.write(protocol.encode(answer))

    def _authenticate(self, client: _Client, kind, name, data: dict) -> None:
        """hello (a nonce) -> our welcome (our nonce + proof) -> its proof; anything else and it is dropped."""
        if kind == protocol.EVENT and name == protocol.HELLO and not client.nonce:
            if data.get("role") == assistant.ROLE and protocol.is_nonce(data.get("nonce")):
                client.nonce, client.hub_nonce = data["nonce"], protocol.new_nonce()
                client.socket.write(protocol.encode(protocol.event(
                    protocol.WELCOME, nonce=client.hub_nonce,
                    proof=protocol.hub_proof(self._token, client.nonce, client.hub_nonce))))
                return
        elif kind == protocol.EVENT and name == protocol.PROOF and client.nonce:
            expected = protocol.maya_proof(self._token, client.nonce, client.hub_nonce)
            if protocol.same_secret(expected, data.get("proof")):
                client.proven = True
                client.decoder.max_body = protocol.MAX_BODY_SIZE
                self.clients_changed.emit()
                return
        client.socket.abort()

    # --- requests ------------------------------------------------------------------

    def _sessions(self, _data: dict) -> dict:
        described = []
        for session in self._link.sessions():
            entry = assistant.describe(session, self.log.problems(session.pid))
            entry["runs_code"] = bool(session.console and self.code_allowed())
            described.append(entry)
        return {"sessions": described}

    # Requests passed on to the Maya they name as they are - fixed ones of the hub <-> Maya link,
    # no arguments of the assistant's go with them:
    # ours -> (the link's request, ms to wait, needs the code switch because it changes that Maya)
    _FORWARDED = {assistant.LAUNCH_REPORT: (protocol.LAUNCH_REPORT, 15_000, False),
                  assistant.RELOAD_CODE: (protocol.RELOAD_CODE, 20_000, True),
                  # protocol.QUIT without "save" / "discard": Maya itself refuses while the scene has
                  # unsaved changes, so an assistant can't close work away.
                  assistant.CLOSE_MAYA: (protocol.QUIT, 15_000, True)}

    # --- the hub itself: what its owner (run_hub, Maya Gate's page) lets an assistant reach -------------

    def set_launcher(self, launch, environments) -> None:
        """`launch(version, environment, scene) -> "" or an error` starts a Maya as the hub does;
        `environments` are the names it takes. Given by Maya Gate's page; without it an
        assistant can't start a Maya."""
        self._launch = launch
        self._environments = [str(name) for name in environments]

    def set_window(self, window) -> None:
        """The hub's window, for pictures of it (anything with grab(); `open_tool(id)` and
        `tool_ids()` are used when it has them)."""
        self._window = window

    def _tool_ids(self) -> list:
        ids = getattr(self._window, "tool_ids", None)
        return list(ids()) if callable(ids) else []

    def _hub_info(self, _data: dict) -> dict:
        from msl_tools.msl.core.fs.maya_paths import MayaPaths
        return {"versions": sorted(str(version) for version in MayaPaths.get_available_installs()),
                "environments": list(self._environments), "tools": self._tool_ids()}

    def _launch_maya(self, data: dict) -> dict:
        from msl_tools.msl.core.fs.maya_paths import MayaPaths
        version, environment = str(data.get("version") or ""), str(data.get("environment") or "")
        scene = data.get("scene") if isinstance(data.get("scene"), str) else ""
        versions = sorted(str(found) for found in MayaPaths.get_available_installs())
        if not self.code_allowed():
            why = ("Starting a Maya is switched off for the assistant in MSL Tools "
                   "(right click the robot’s head in the window’s header).")
        elif self._launch is None:
            why = "Maya Gate has not been opened in MSL Tools yet - open it once (hub_screenshot with tool maya_gate)."
        elif version not in versions:
            why = "Maya “%s” isn’t installed here. Installed: %s." % (version, ", ".join(versions) or "none")
        elif environment not in self._environments:
            why = "There is no environment “%s”. Environments: %s." % (environment, ", ".join(self._environments))
        else:
            why = self._launch(version, environment, scene)
        return {"success": False, "error": why} if why else {"started": True}

    def _hub_screenshot(self, client: _Client, request_id: int, data: dict) -> None:
        """A picture of the hub's window - after opening the tool it names and letting it lay out."""
        def refuse(why: str) -> None:
            client.socket.write(protocol.encode(protocol.reply(request_id, False, why)))

        window, tool = self._window, str(data.get("tool") or "")
        if window is None:
            return refuse("This MSL Tools has no window to show.")
        if tool:
            if tool not in self._tool_ids():
                return refuse("There is no tool “%s”. Tools: %s." % (tool, ", ".join(self._tool_ids())))
            window.open_tool(tool)

        def shoot() -> None:
            if client not in self._clients:
                return
            import tempfile
            import time
            from pathlib import Path
            folder = Path(tempfile.gettempdir()) / "msl_tools" / "assistant"
            try:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / ("hub_%s.png" % time.strftime("%H%M%S"))
                picture = window.grab()
                saved = picture.save(str(path), "PNG")
            except (OSError, RuntimeError) as error:
                return refuse("The picture could not be made: %s" % error)
            if not saved:
                return refuse("The picture could not be saved.")
            current = getattr(window, "current_tool_id", None)
            client.socket.write(protocol.encode(protocol.reply(
                request_id, path=str(path), tool=str(current() if callable(current) else tool),
                width=picture.width(), height=picture.height())))

        qt.QtCore.QTimer.singleShot(self.SCREENSHOT_DELAY_MS if tool else 0, shoot)

    def _forward(self, client: _Client, request_id: int, name: str, data: dict) -> None:
        link_name, timeout_ms, changes = self._FORWARDED[name]
        pid = int(data.get("pid") or 0)
        session = next((s for s in self._link.sessions() if s.pid == pid), None)
        if session is None:
            why = "MSL Tools knows no connected Maya with pid %d." % pid
        elif changes and not self.code_allowed():
            why = ("That changes the Maya, which is switched off for the assistant in MSL Tools "
                   "(right click the robot’s head in the window’s header).")
        else:
            why = ""
        if why:
            client.socket.write(protocol.encode(protocol.reply(request_id, False, why)))
            return

        def done(reply: dict) -> None:
            if client not in self._clients:
                return
            if reply.get("success"):
                answer = protocol.reply(request_id, **{key: value for key, value in (reply.get("data") or {}).items()
                                                       if key not in ("message_id", "success", "error")})
            else:
                answer = protocol.reply(request_id, False, str(reply.get("error") or "the request failed"))
            client.socket.write(protocol.encode(answer))

        self._link.request(session.session_id, link_name, on_reply=done, timeout_ms=timeout_ms)

    def _run_python(self, client: _Client, request_id: int, data: dict) -> None:
        """Passes an assistant's code to the Maya it names and answers when that Maya did."""
        def refuse(why: str) -> None:
            client.socket.write(protocol.encode(protocol.reply(request_id, False, why)))

        pid, code = int(data.get("pid") or 0), data.get("code")
        session = next((s for s in self._link.sessions() if s.pid == pid), None)
        if not self.code_allowed():
            return refuse("Running code is switched off for the assistant in MSL Tools "
                          "(right click the robot’s head in the window’s header).")
        if session is None:
            return refuse("MSL Tools knows no connected Maya with pid %d." % pid)
        if not session.console:
            return refuse("That Maya takes no code (it was not started from MSL Tools with the console allowed).")
        if not isinstance(code, str) or not code.strip() or len(code) > assistant.MAX_CODE:
            return refuse("No code to run (or more than %d characters of it)." % assistant.MAX_CODE)
        if pid in self._running:
            return refuse("That Maya is still running the assistant’s previous code.")
        least, most = assistant.RUN_SECONDS
        try:
            seconds = min(max(int(data.get("seconds") or assistant.RUN_SECONDS_DEFAULT), least), most)
        except (TypeError, ValueError):
            seconds = assistant.RUN_SECONDS_DEFAULT

        def done(reply: dict) -> None:
            self._running.discard(pid)
            self.code_finished.emit(pid, reply)
            if client not in self._clients:
                return   # the assistant left meanwhile; the Sessions tab still shows what came back
            if reply.get("success"):
                result = reply.get("data") or {}
                answer = protocol.reply(request_id, output=str(result.get("output") or ""),
                                        result=str(result.get("result") or ""),
                                        traceback=str(result.get("traceback") or ""))
            else:
                answer = protocol.reply(request_id, False, str(reply.get("error") or "the request failed"))
            client.socket.write(protocol.encode(answer))

        self._running.add(pid)
        self.code_started.emit(pid, code)
        self._link.request(session.session_id, protocol.RUN_PYTHON, on_reply=done,
                           timeout_ms=seconds * 1000, code=code)

    def _read_log(self, data: dict) -> dict:
        pid, after, limit = int(data.get("pid") or 0), int(data.get("after") or 0), int(data.get("limit") or 200)
        levels = data.get("levels")
        levels = [level for level in levels if level in protocol.LOG_LEVELS] if isinstance(levels, list) else None
        entries, last = self.log.read(pid, after, limit, levels)
        known = self.log.knows(pid) or any(session.pid == pid for session in self._link.sessions())
        return {"entries": entries, "last": last, "known": known}
