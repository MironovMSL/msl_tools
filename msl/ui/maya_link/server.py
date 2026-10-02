# ui/maya_link/server.py
"""The hub's end of the hub <-> Maya link: a local TCP server every Maya
started from the hub connects to.

The HUB is the server, each Maya a client (tools/maya/hub_link.py) — the
reverse of Maya's own commandPort. One known port instead of one per Maya;
any number of Mayas at once; both sides can speak over the one connection;
and the hub knows at once when a Maya is gone (its connection drops).

Lives in ui/ (like process_launcher): it is built on QTcpServer. Nothing
blocks — Qt delivers connections and data as signals in the GUI thread.

Safety: it listens on 127.0.0.1 only (not reachable from the network), and
a connection is a session only after a hello carrying the hub's token, which
only a Maya launched by this hub was given (environment variable). Anything
else is dropped. Messages are data (core/link/protocol.py) — nothing here
executes code that arrives.
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
        self.decoder = protocol.FrameDecoder()
        self.session: MayaSession | None = None


class MayaLinkServer(qt.QtCore.QObject):
    """Accepts Maya sessions and keeps the list of them.

    Signals:
        sessions_changed() — a session connected, changed (its scene) or left.
        listening_changed() — the server started or stopped listening.
    """

    DEFAULT_PORT = 47611
    PORT_ATTEMPTS = 10          # DEFAULT_PORT busy (another hub?) -> the next ones are tried
    HELLO_TIMEOUT_MS = 5000     # a connection that doesn't introduce itself in time is dropped
    CONFIG_NAME = "maya_link"
    PORT_VARIABLE = "MSL_GATE_LINK_PORT"    # handed to a launched Maya
    TOKEN_VARIABLE = "MSL_GATE_LINK_TOKEN"

    sessions_changed = qt.QtCore.Signal()
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
                self.listening_changed.emit()
                return True
        return False

    def close(self) -> None:
        """Stops listening and drops every session."""
        for peer in list(self._peers):
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
            self._handle(peer, message)

    def _handle(self, peer: _Peer, message: dict) -> None:
        kind, name = message.get("type"), message.get("name")
        data = message.get("data") if isinstance(message.get("data"), dict) else {}
        if peer.session is None:
            # The first message must be a hello with our token - otherwise it isn't one of ours.
            if kind != protocol.EVENT or name != protocol.HELLO or \
                    not secrets.compare_digest(str(data.get("token", "")), self._token):
                peer.socket.abort()
                return
            peer.session = MayaSession.from_hello(self._next_id, data)
            peer.session.connected_at = time.time()
            self._next_id += 1
            self.sessions_changed.emit()
            return
        if kind == protocol.EVENT and name == protocol.SCENE:
            scene = str(data.get("scene") or "")
            if scene != peer.session.scene:
                peer.session.scene = scene
                self.sessions_changed.emit()
        elif kind == protocol.REQUEST and name == protocol.PING:
            peer.socket.write(protocol.encode(protocol.reply(message.get("id", 0))))

    def _on_disconnected(self, peer: _Peer) -> None:
        if peer not in self._peers:
            return
        self._peers.remove(peer)
        peer.socket.deleteLater()
        if peer.session is not None:
            self.sessions_changed.emit()
