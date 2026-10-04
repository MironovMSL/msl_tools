# ui/maya_link/server.py
"""The hub's end of the hub <-> Maya link: a local TCP server every Maya
started from the hub connects to.

The HUB is the server, each Maya a client (tools/maya/hub_link.py) — the
reverse of Maya's own commandPort. One known port instead of one per Maya;
any number of Mayas at once; both sides can speak over the one connection;
and the hub knows at once when a Maya is gone (its connection drops).

Lives in ui/ (like process_launcher): it is built on QTcpServer. Nothing
blocks — Qt delivers connections and data as signals in the GUI thread.

Requests. `request(session_id, name, on_reply, ...)` asks a Maya to do
something from the fixed list in core/link/protocol.py and calls
`on_reply(reply)` when the answer comes — or with a failure reply if the
Maya left or took longer than the timeout. Replies are matched by id, so a
slow answer is never mistaken for the answer to a later question.

Safety: it listens on 127.0.0.1 only (not reachable from the network), and
a connection is a session only after it proved it knows the hub's token,
which only a Maya launched by this hub was given (environment variable) —
the token itself never goes over the wire, and Maya first checks the hub's
proof in turn (core/link/protocol.py). Anything else is dropped; until then
a peer may send 64 KB per message. Messages are data (core/link/protocol.py) — nothing here
executes code that arrives. The other way round there is exactly one
request that carries code, `run_python` (the Sessions tab's console), and
Maya's side refuses it unless that Maya was launched with the console
allowed — see tools/maya/hub_link.py.
"""
import secrets
import time

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import protocol
from msl_tools.msl.core.link.session import MayaSession


class _Peer:
    """Private: one accepted connection — its socket, its unfinished bytes,
    and its session once it said hello."""

    def __init__(self, socket: "qt.QtNetwork.QTcpSocket"):
        self.socket = socket
        self.decoder = protocol.FrameDecoder(max_body=protocol.MAX_BODY_BEFORE_AUTH)
        self.session: MayaSession | None = None
        self.hello: dict | None = None  # its hello, kept until its proof comes (see protocol.py)
        self.hub_nonce = ""             # what the hub's welcome asked it to prove itself with
        self.said_bye = False   # it announced that it is leaving (a quit, a link restart)
        self.bye_reason = ""    # why it left: protocol.BYE_* / ENDED_BY_HUB; "" = the connection just broke
        self.pinging = False    # a ping is out and not answered yet


class MayaLinkServer(qt.QtCore.QObject):
    """Accepts Maya sessions and keeps the list of them.

    Signals:
        sessions_changed() — a session connected, changed (its scene, unsaved state, busy) or left.
        log_received(int, list) — (session id, [(level, text), ...]): what
            that Maya's Script Editor just printed (warnings and errors;
            plain messages too once asked for with SET_LOG_LEVEL).
        listening_changed() — the server started or stopped listening.
        session_ended(MayaSession, bool, str) — a session is gone. `clean` is
            True when it said goodbye first or the hub dropped it itself;
            False when the connection just broke — Maya crashed or was
            killed. The third value says why: protocol.BYE_QUIT (Maya is
            closing), protocol.BYE_RESTART (only its link restarts — "Reload
            code"; it will be back), ENDED_BY_HUB (the hub stopped
            listening; Maya is still running), "" (the connection broke).
        attention_changed() — unread_errors() changed.

    Busy: every PING_INTERVAL_MS each Maya is pinged; one that doesn't
    answer within PING_TIMEOUT_MS has `session.busy` set (its main thread
    is working — a long script, a heavy scene) until it answers again.

    Unread errors: a number any view of the log may set (set_unread_errors)
    for errors that arrived while nobody was looking — so another part of
    the hub (the header indicator) can show it without knowing that view.
    """

    DEFAULT_PORT = 47611
    PORT_ATTEMPTS = 10          # DEFAULT_PORT busy (another hub?) -> the next ones are tried
    HELLO_TIMEOUT_MS = 5000     # a connection that doesn't introduce itself in time is dropped
    CONFIG_NAME = "maya_link"
    PORT_VARIABLE = "MSL_GATE_LINK_PORT"    # handed to a launched Maya
    TOKEN_VARIABLE = "MSL_GATE_LINK_TOKEN"

    MAX_LOG_ENTRIES = 500       # per message; more than that is cut
    MAX_LOG_TEXT = 8000         # characters per entry

    PING_INTERVAL_MS = 4000     # how often every Maya is asked "are you there?"
    PING_TIMEOUT_MS = 3000      # no answer in this time = busy
    ENDED_BY_HUB = "hub"        # session_ended's reason when the hub itself dropped the session

    sessions_changed = qt.QtCore.Signal()
    log_received = qt.QtCore.Signal(int, list)
    session_ended = qt.QtCore.Signal(object, bool, str)   # (MayaSession, clean, reason): see the class docstring
    attention_changed = qt.QtCore.Signal()
    listening_changed = qt.QtCore.Signal()

    _instance: "MayaLinkServer | None" = None

    @classmethod
    def instance(cls) -> "MayaLinkServer":
        """The hub's one server (created on first use, not yet listening)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = qt.QtNetwork.QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._peers: list[_Peer] = []
        self._token = ""
        self._next_id = 1
        self._next_request_id = 1
        # request id -> (peer, on_reply, timeout timer): the questions still waiting for an answer
        self._pending: dict[int, tuple[_Peer, object, qt.QtCore.QTimer]] = {}
        self._unread_errors = 0
        self._ping_timer = qt.QtCore.QTimer(self)
        self._ping_timer.setInterval(self.PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._ping_all)

    # --- listening ---------------------------------------------------------------

    def ensure_listening(self) -> bool:
        """Starts listening with the port / token kept in the hub's config
        (configs/desktop/maya_link) unless it already is. The token is made
        once and kept, the port is reused: a Maya that outlives a hub
        restart finds the new hub at the same address and reconnects."""
        if self.is_listening():
            return True
        from msl_tools.msl.core.resources import Resources
        config = Resources().configsDesktopHubMng.get_config(
            self.CONFIG_NAME, defaults={"port": self.DEFAULT_PORT, "token": ""})
        token = str(config["token"] or "")
        if not token:
            token = secrets.token_hex(16)
            config["token"] = token
        try:
            port = int(config["port"])
        except (TypeError, ValueError):
            port = self.DEFAULT_PORT
        return self.listen(port, token)

    def listen(self, port: int, token: str) -> bool:
        """Listens on 127.0.0.1:`port` — or the first free of the next
        PORT_ATTEMPTS ports. False if none could be taken."""
        self._token = token
        for candidate in range(port, port + self.PORT_ATTEMPTS):
            if self._server.listen(qt.QtNetwork.QHostAddress(qt.QtNetwork.QHostAddress.SpecialAddress.LocalHost),
                                   candidate):
                self._ping_timer.start()
                self.listening_changed.emit()
                return True
        return False

    def close(self) -> None:
        """Stops listening and drops every session."""
        self._ping_timer.stop()
        for peer in list(self._peers):
            peer.said_bye = True  # we are the ones leaving: not a crash
            peer.bye_reason = self.ENDED_BY_HUB
            peer.socket.abort()
        self._server.close()
        self.listening_changed.emit()

    def is_listening(self) -> bool:
        return self._server.isListening()

    def port(self) -> int:
        """The port in use (0 while not listening)."""
        return int(self._server.serverPort()) if self._server.isListening() else 0

    def error_text(self) -> str:
        return self._server.errorString()

    def launch_variables(self) -> dict[str, str]:
        """What a Maya needs to find and join this hub ({} while not listening)."""
        if not self.is_listening():
            return {}
        return {self.PORT_VARIABLE: str(self.port()), self.TOKEN_VARIABLE: self._token}

    # --- sessions ------------------------------------------------------------------

    def sessions(self) -> list[MayaSession]:
        """Connected Mayas, oldest connection first."""
        return [peer.session for peer in self._peers if peer.session is not None]

    def unread_errors(self) -> int:
        return self._unread_errors

    def set_unread_errors(self, count: int) -> None:
        count = max(int(count), 0)
        if count != self._unread_errors:
            self._unread_errors = count
            self.attention_changed.emit()

    def _ping_all(self) -> None:
        for peer in self._peers:
            if peer.session is None or peer.pinging:
                continue
            peer.pinging = True
            self.request(peer.session.session_id, protocol.PING, timeout_ms=self.PING_TIMEOUT_MS,
                         on_reply=lambda reply, peer=peer: self._on_ping(peer, reply))

    def _on_ping(self, peer: _Peer, reply: dict) -> None:
        peer.pinging = False
        if peer not in self._peers or peer.session is None:
            return
        busy = not reply.get("success")
        if busy != peer.session.busy:
            peer.session.busy = busy
            peer.session.busy_since = time.time() if busy else 0.0
            self.sessions_changed.emit()

    def session(self, session_id: int) -> MayaSession | None:
        return next((s for s in self.sessions() if s.session_id == session_id), None)

    # --- requests --------------------------------------------------------------------

    def request(self, session_id: int, name: str, on_reply=None, timeout_ms: int = 10_000, **data) -> bool:
        """Asks session `session_id` to do `name` (a protocol.* request).

        `on_reply(reply: dict)` is called exactly once, in the GUI thread:
        with Maya's reply ({"success": bool, "data": {...}, "error": str}),
        or with {"success": False, "error": ...} if the Maya disconnected or
        didn't answer within `timeout_ms`. Returns False (and calls
        `on_reply` with a failure) if there is no such session.
        """
        peer = next((p for p in self._peers if p.session is not None and p.session.session_id == session_id), None)
        if peer is None:
            if on_reply is not None:
                on_reply({"success": False, "error": "That Maya is no longer connected.", "data": {}})
            return False
        request_id = self._next_request_id
        self._next_request_id += 1
        timer = qt.QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._finish(request_id, {
            "success": False, "error": "Maya didn\u2019t answer in time (it may be busy).", "data": {}}))
        self._pending[request_id] = (peer, on_reply, timer)
        timer.start(timeout_ms)
        peer.socket.write(protocol.encode(protocol.request(name, request_id, **data)))
        return True

    def _finish(self, request_id: int, reply: dict) -> None:
        """Hands `reply` to whoever asked request `request_id` — once."""
        entry = self._pending.pop(request_id, None)
        if entry is None:
            return  # already answered / timed out
        _peer, on_reply, timer = entry
        timer.stop()
        timer.deleteLater()
        if on_reply is not None:
            on_reply(reply)

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            peer = _Peer(socket)
            self._peers.append(peer)
            socket.readyRead.connect(lambda peer=peer: self._on_ready_read(peer))
            socket.disconnected.connect(lambda peer=peer: self._on_disconnected(peer))
            qt.QtCore.QTimer.singleShot(self.HELLO_TIMEOUT_MS, lambda peer=peer: self._drop_if_silent(peer))

    def _drop_if_silent(self, peer: _Peer) -> None:
        if peer in self._peers and peer.session is None:
            peer.socket.abort()

    def _on_ready_read(self, peer: _Peer) -> None:
        try:
            messages = peer.decoder.feed(bytes(peer.socket.readAll().data()))
        except protocol.ProtocolError:
            peer.socket.abort()  # out of step: nothing after this can be trusted
            return
        for message in messages:
            if peer not in self._peers:
                return
            try:
                self._handle(peer, message)
            except Exception:  # a well-framed message with wrong types in it: that peer is out of step
                peer.socket.abort()
                return

    def _handle(self, peer: _Peer, message: dict) -> None:
        kind, name = message.get("type"), message.get("name")
        data = message.get("data") if isinstance(message.get("data"), dict) else {}
        if peer.session is None:
            self._authenticate(peer, kind, name, data)
            return
        if kind == protocol.EVENT and name == protocol.BYE:
            peer.said_bye = True
            peer.bye_reason = str(data.get("reason") or protocol.BYE_QUIT)
        elif kind == protocol.EVENT and name == protocol.SCENE:
            session = peer.session
            state = (str(data.get("scene") or ""), bool(data.get("modified")),
                     bool(data.get("autosave", session.autosave)),  # absent from a Maya with older code
                     str(data.get("autosave_folder", session.autosave_folder) or ""))
            if state != (session.scene, session.modified, session.autosave, session.autosave_folder):
                session.scene, session.modified, session.autosave, session.autosave_folder = state
                self.sessions_changed.emit()
        elif kind == protocol.EVENT and name == protocol.LOG:
            entries = []
            for entry in (data.get("entries") or [])[:self.MAX_LOG_ENTRIES]:
                if isinstance(entry, (list, tuple)) and len(entry) == 2:
                    level = entry[0] if entry[0] in protocol.LOG_LEVELS else protocol.LOG_INFO
                    entries.append((level, str(entry[1])[:self.MAX_LOG_TEXT]))
            dropped = data.get("dropped")
            if isinstance(dropped, int) and dropped > 0:
                entries.append((protocol.LOG_TRACE, f"\u2026 {dropped} more lines were not sent (too many at once)"))
            if entries:
                self.log_received.emit(peer.session.session_id, entries)
        elif kind == protocol.REQUEST and name == protocol.PING:
            peer.socket.write(protocol.encode(protocol.reply(message.get("id", 0))))
        elif kind == protocol.REPLY:
            request_id = message.get("id")
            entry = self._pending.get(request_id) if isinstance(request_id, int) else None
            if entry is not None and entry[0] is peer:  # only the Maya that was asked may answer
                self._finish(request_id, {"success": bool(message.get("success")), "data": data,
                                          "error": str(message.get("error") or "")})

    def _authenticate(self, peer: _Peer, kind, name, data: dict) -> None:
        """A connection becomes a session only once it proved it knows the token — hello, welcome,
        proof (protocol.py); anything else, or a wrong proof, and it is dropped."""
        if kind == protocol.EVENT and name == protocol.HELLO and peer.hello is None:
            maya_nonce = data.get("nonce")
            if protocol.is_nonce(maya_nonce):
                peer.hello, peer.hub_nonce = data, protocol.new_nonce()
                peer.socket.write(protocol.encode(protocol.event(
                    protocol.WELCOME, nonce=peer.hub_nonce,
                    proof=protocol.hub_proof(self._token, maya_nonce, peer.hub_nonce))))
                return
            # A Maya with code from before the proofs sends the token itself (see protocol.py).
            if protocol.same_secret(self._token, data.get("token")):
                self._open_session(peer, data)
                return
        elif kind == protocol.EVENT and name == protocol.PROOF and peer.hello is not None:
            expected = protocol.maya_proof(self._token, peer.hello["nonce"], peer.hub_nonce)
            if protocol.same_secret(expected, data.get("proof")):
                self._open_session(peer, peer.hello)
                return
        peer.socket.abort()

    def _open_session(self, peer: _Peer, hello: dict) -> None:
        peer.session = MayaSession.from_hello(self._next_id, hello)
        peer.session.connected_at = time.time()
        peer.decoder.max_body = protocol.MAX_BODY_SIZE  # proven: full-size messages (logs, replies)
        self._next_id += 1
        self.sessions_changed.emit()

    def _on_disconnected(self, peer: _Peer) -> None:
        if peer not in self._peers:
            return
        self._peers.remove(peer)
        try:
            peer.socket.deleteLater()
            for request_id in [key for key, entry in self._pending.items() if entry[0] is peer]:
                self._finish(request_id, {"success": False, "error": "Maya disconnected.", "data": {}})
            if peer.session is not None:
                self.sessions_changed.emit()
                self.session_ended.emit(peer.session, peer.said_bye, peer.bye_reason)
        except RuntimeError:
            pass  # the application is shutting down: Qt already deleted this server / the socket
