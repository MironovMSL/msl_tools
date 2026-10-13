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
Nothing that arrives is executed: every request is looked up in _HANDLERS,
anything else is refused.
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
    """

    PORT_ATTEMPTS = 10
    HELLO_TIMEOUT_MS = 5000
    MAX_CLIENTS = 4

    listening_changed = qt.QtCore.Signal()
    clients_changed = qt.QtCore.Signal()

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
        self._HANDLERS = {assistant.SESSIONS: self._sessions, assistant.READ_LOG: self._read_log}

    # --- listening ---------------------------------------------------------------

    def _settings(self):
        if self._config is None:
            from msl_tools.msl.core.resources import Resources
            self._config = Resources().configsDesktopHubMng.get_config(
                assistant.CONFIG_NAME, defaults={"port": assistant.DEFAULT_PORT, "token": "", "enabled": False})
        return self._config

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
        return {"sessions": [assistant.describe(session, self.log.problems(session.pid))
                             for session in self._link.sessions()]}

    def _read_log(self, data: dict) -> dict:
        pid, after, limit = int(data.get("pid") or 0), int(data.get("after") or 0), int(data.get("limit") or 200)
        levels = data.get("levels")
        levels = [level for level in levels if level in protocol.LOG_LEVELS] if isinstance(levels, list) else None
        entries, last = self.log.read(pid, after, limit, levels)
        known = self.log.knows(pid) or any(session.pid == pid for session in self._link.sessions())
        return {"entries": entries, "last": last, "known": known}
