"""The hub <-> Maya handshake (core/link/protocol.py): the token never goes over the wire,
the hub opens no session without Maya's proof, and Maya answers nothing until the hub
proved itself.

The hub's server listens on a PRIVATE port with a private token — never
ensure_listening(): a real Maya running on this machine would join the test.
"""
import json
import os
import socket
import sys
import time
import types
import unittest
from unittest import mock

from msl_tools.msl.core.link import protocol

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.maya_link.server import MayaLinkServer
except ImportError:  # no PySide6 in this Python
    qt = None

TOKEN = "f00d" * 8


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@unittest.skipIf(qt is None, "PySide6 is not installed")
class _Qt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def pump(self, until, seconds=3.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if until():
                return True
            time.sleep(0.005)
        return until()


class FakeMaya:
    """A Maya's side of the link on a plain socket, step by step."""

    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.sock.setblocking(False)
        self.decoder = protocol.FrameDecoder()
        self.received: list = []
        self.closed = False

    def send(self, message: dict) -> None:
        self.sock.sendall(protocol.encode(message))

    def send_raw(self, data: bytes) -> None:
        self.sock.sendall(data)

    def poll(self) -> None:
        try:
            data = self.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self.closed = True
            return
        if not data:
            self.closed = True
            return
        self.received += self.decoder.feed(data)


class HubSide(_Qt):
    def setUp(self):
        self.server = MayaLinkServer()
        self.assertTrue(self.server.listen(_free_port(), TOKEN))
        self.server._ping_timer.stop()  # no pings in the middle of these steps
        self.addCleanup(self.server.close)
        self.maya = FakeMaya(self.server.port())
        self.addCleanup(self.maya.sock.close)
        self.nonce = protocol.new_nonce()

    def hello(self, **extra) -> None:
        data = dict(pid=4242, version="2025", nonce=self.nonce)
        data.update(extra)
        self.maya.send(protocol.event(protocol.HELLO, **data))

    def welcome(self) -> dict:
        self.assertTrue(self.pump(lambda: (self.maya.poll(), self.maya.received)[1]), "no welcome")
        message = self.maya.received.pop(0)
        self.assertEqual(message["name"], protocol.WELCOME)
        return message["data"]

    def test_proofs_both_ways_open_a_session(self):
        self.hello()
        welcome = self.welcome()
        self.assertNotIn(TOKEN, json.dumps(welcome))  # the token itself never goes out
        self.assertEqual(welcome["proof"], protocol.hub_proof(TOKEN, self.nonce, welcome["nonce"]))
        self.assertEqual(self.server.sessions(), [])  # not before Maya's proof
        self.maya.send(protocol.event(protocol.PROOF, proof=protocol.maya_proof(TOKEN, self.nonce, welcome["nonce"])))
        self.assertTrue(self.pump(lambda: len(self.server.sessions()) == 1))
        self.assertEqual(self.server.sessions()[0].pid, 4242)

    def assert_dropped(self):
        self.assertTrue(self.pump(lambda: (self.maya.poll(), self.maya.closed)[1]), "not dropped")
        self.assertEqual(self.server.sessions(), [])

    def test_wrong_proof_is_dropped(self):
        self.hello()
        welcome = self.welcome()
        self.maya.send(protocol.event(protocol.PROOF, proof=protocol.maya_proof("wrong", self.nonce, welcome["nonce"])))
        self.assert_dropped()

    def test_the_hubs_proof_sent_back_is_no_proof(self):
        self.hello()
        welcome = self.welcome()
        self.maya.send(protocol.event(protocol.PROOF, proof=welcome["proof"]))
        self.assert_dropped()

    def test_older_maya_with_the_token_still_joins(self):
        self.maya.send(protocol.event(protocol.HELLO, pid=7, version="2024", token=TOKEN))
        self.assertTrue(self.pump(lambda: len(self.server.sessions()) == 1))

    def test_hello_without_nonce_or_token_is_dropped(self):
        self.maya.send(protocol.event(protocol.HELLO, pid=7, token="nope"))
        self.assert_dropped()

    def test_non_ascii_token_is_dropped_not_an_error(self):
        # Before: secrets.compare_digest raised TypeError inside the server's slot.
        self.maya.send(protocol.event(protocol.HELLO, pid=7, token="токен"))
        self.assert_dropped()

    def test_big_message_before_the_proof_is_dropped(self):
        self.maya.send_raw(b"%010d" % (protocol.MAX_BODY_BEFORE_AUTH + 1))
        self.assert_dropped()

    def test_wrong_types_in_a_proven_hello_are_dropped_not_an_error(self):
        self.hello(pid="abc")  # int("abc") in the session
        welcome = self.welcome()
        self.maya.send(protocol.event(protocol.PROOF, proof=protocol.maya_proof(TOKEN, self.nonce, welcome["nonce"])))
        self.assert_dropped()


class _FakeHub:
    """What sits on the hub's port: a QTcpServer that answers the way it is told."""

    def __init__(self, token: str):
        self.server = qt.QtNetwork.QTcpServer()
        self.server.listen(qt.QtNetwork.QHostAddress("127.0.0.1"), 0)
        self.token = token
        self.socket = None
        self.decoder = protocol.FrameDecoder()
        self.received: list = []
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        self.socket = self.server.nextPendingConnection()
        self.socket.readyRead.connect(self._on_read)

    def _on_read(self):
        self.received += self.decoder.feed(bytes(self.socket.readAll().data()))

    def send(self, message: dict) -> None:
        self.socket.write(protocol.encode(message))


class MayaSide(_Qt):
    """tools/maya/hub_link.py's HubLink (with a fake maya.cmds) against what sits on the port."""

    def setUp(self):
        cmds = mock.MagicMock()
        cmds.about.return_value = "2025"
        cmds.file.return_value = ""
        cmds.autoSave.return_value = False
        maya = types.ModuleType("maya")
        maya.cmds = cmds
        patch = mock.patch.dict(sys.modules, {"maya": maya, "maya.cmds": cmds})
        patch.start()
        self.addCleanup(patch.stop)
        from msl_tools.msl.tools.maya import hub_link
        self.hub_link = hub_link

    def connect(self, hub: _FakeHub):
        self.hub = hub  # both kept by the test until it is over
        self.link = link = self.hub_link.HubLink(hub.server.serverPort(), TOKEN)
        link._retry.setInterval(60_000)  # one attempt per test
        link._connect()
        self.assertTrue(self.pump(lambda: hub.received), "no hello")
        hello = hub.received.pop(0)
        self.assertEqual(hello["name"], protocol.HELLO)
        self.assertNotIn(TOKEN, json.dumps(hello))  # the token itself never goes out
        self.addCleanup(lambda: self.link._socket.abort())
        return link, hello["data"]["nonce"]

    def test_answers_nothing_to_an_impostor(self):
        # Before: whatever listened on the port got the token in the hello and could send
        # quit_maya {"discard": true}, or code to a Dev Maya.
        hub = _FakeHub("not the token")
        link, nonce = self.connect(hub)
        hub_nonce = protocol.new_nonce()
        hub.send(protocol.event(protocol.WELCOME, nonce=hub_nonce, proof=protocol.hub_proof(hub.token, nonce, hub_nonce)))
        hub.send(protocol.request(protocol.PING, 1))
        self.pump(lambda: False, seconds=0.5)
        self.assertEqual(hub.received, [])  # no proof, no reply
        self.assertFalse(link._verified)

    def test_request_without_a_welcome_is_never_answered(self):
        hub = _FakeHub(TOKEN)
        link, _nonce = self.connect(hub)
        hub.send(protocol.request(protocol.PING, 1))
        self.pump(lambda: False, seconds=0.5)
        self.assertEqual(hub.received, [])
        self.assertFalse(link._verified)

    def test_the_real_hub_gets_the_proof_then_answers(self):
        hub = _FakeHub(TOKEN)
        link, nonce = self.connect(hub)
        hub_nonce = protocol.new_nonce()
        hub.send(protocol.event(protocol.WELCOME, nonce=hub_nonce, proof=protocol.hub_proof(TOKEN, nonce, hub_nonce)))
        self.assertTrue(self.pump(lambda: hub.received))
        proof = hub.received.pop(0)
        self.assertEqual(proof["name"], protocol.PROOF)
        self.assertEqual(proof["data"]["proof"], protocol.maya_proof(TOKEN, nonce, hub_nonce))
        hub.send(protocol.request(protocol.PING, 5))
        self.assertTrue(self.pump(lambda: hub.received))
        self.assertEqual((hub.received[0]["type"], hub.received[0]["id"]), (protocol.REPLY, 5))


if __name__ == "__main__":
    unittest.main()
