# ui/app/instance_link.py
import hashlib
import json
import os
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt


class InstanceLink(qt.QtCore.QObject):
    """A line from a second start of the program to the one already running,
    so that start can hand over what it was asked to do and quit — e.g.
    Explorer's "Send to → MSL Media" starting the hub with files when a hub
    is open already: the files go to that hub, no second window appears.

        if InstanceLink.send(name, {"open": paths}):   # in the new start
            return                                      # handed over
        link = InstanceLink(name)                       # in the one that keeps running
        link.received.connect(...)                      # dict

    A local socket of the operating system (QLocalServer) — this machine
    only, this user only. instance_name() makes the name from the program's
    folder, so two installs (a stable copy and a developer's checkout) are
    two programs and don't take each other's messages.

    Signals:
        received(object) — a message (a dict) from another start.
    """

    TIMEOUT_MS = 800

    received = qt.QtCore.Signal(object)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._name = name
        self._server = qt.QtNetwork.QLocalServer(self)
        self._server.setSocketOptions(qt.QtNetwork.QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        if not self._server.listen(name):
            # A name left behind by a program that crashed: take it over.
            qt.QtNetwork.QLocalServer.removeServer(name)
            self._server.listen(name)

    @staticmethod
    def instance_name(root: str | Path, program: str = "msl_tools") -> str:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
        digest = hashlib.sha1(f"{Path(root).resolve()}|{user}".lower().encode("utf-8")).hexdigest()[:12]
        return f"{program}_{digest}"

    def is_listening(self) -> bool:
        return self._server.isListening()

    @classmethod
    def send(cls, name: str, message: dict) -> bool:
        """Hands `message` to the program listening under `name`. False if none is running."""
        socket = qt.QtNetwork.QLocalSocket()
        socket.connectToServer(name)
        if not socket.waitForConnected(cls.TIMEOUT_MS):
            return False
        socket.write(json.dumps(message).encode("utf-8") + b"\n")
        sent = socket.waitForBytesWritten(cls.TIMEOUT_MS)
        socket.disconnectFromServer()
        return sent

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setParent(self)
            buffer = bytearray()

            def read(socket=socket, buffer=buffer) -> None:
                buffer.extend(bytes(socket.readAll()))
                while b"\n" in buffer:
                    line, _, rest = bytes(buffer).partition(b"\n")
                    buffer[:] = rest
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    if isinstance(message, dict):
                        self.received.emit(message)

            socket.readyRead.connect(read)
            socket.disconnected.connect(socket.deleteLater)
            read()
