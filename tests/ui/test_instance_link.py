"""ui/app/instance_link.py + run_hub's second start: one hub per install.

Uses a PRIVATE link name — never InstanceLink.instance_name() of this
folder: a hub the user has running would take the message.
"""
import json
import os
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

_PARENT = str(Path(__file__).resolve().parents[3])  # the folder holding msl_tools

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.app.instance_link import InstanceLink
except ImportError:  # no PySide6 in this Python
    qt = None


@unittest.skipIf(qt is None, "PySide6 is not installed")
class SecondStart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def setUp(self):
        self.name = f"msl_tools_test_{uuid.uuid4().hex[:12]}"

    def deliver(self, receiver, message: dict):
        """Sends `message` from ANOTHER PROCESS, as a second start does (send() waits on the
        receiver, whose event loop must run meanwhile), and collects what the receiver got."""
        received = []
        receiver.received.connect(received.append)
        script = ("import json, sys; from msl_tools.msl.ui.app.instance_link import InstanceLink; "
                  "sys.exit(0 if InstanceLink.send(sys.argv[1], json.loads(sys.argv[2])) else 1)")
        environment = dict(os.environ, PYTHONPATH=_PARENT + os.pathsep + os.environ.get("PYTHONPATH", ""))
        sender = subprocess.Popen([sys.executable, "-c", script, self.name, json.dumps(message)], env=environment)
        deadline = time.monotonic() + 15
        while (sender.poll() is None or not received) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        if sender.poll() is None:
            sender.kill()
        return sender.wait() == 0, received

    def test_nothing_running_means_start_normally(self):
        self.assertFalse(InstanceLink.send(self.name, {"raise": True}))

    def test_plain_second_start_is_handed_over(self):
        receiver = InstanceLink(self.name)
        self.addCleanup(receiver.deleteLater)
        sent, received = self.deliver(receiver, {"raise": True})
        self.assertTrue(sent)
        self.assertEqual(received, [{"raise": True}])

    def test_files_are_handed_over(self):
        receiver = InstanceLink(self.name)
        self.addCleanup(receiver.deleteLater)
        sent, received = self.deliver(receiver, {"open": ["C:/a.mp4"]})
        self.assertTrue(sent)
        self.assertEqual(received, [{"open": ["C:/a.mp4"]}])

    def test_second_start_without_files_only_raises(self):
        from msl_tools.msl import run_hub
        calls = []
        window = object()
        original = run_hub._bring_to_front, run_hub._open_in_media
        run_hub._bring_to_front = lambda w: calls.append(("front", w))
        run_hub._open_in_media = lambda w, files: calls.append(("media", files))
        try:
            run_hub._on_second_start(window, {"raise": True})
            run_hub._on_second_start(window, {"open": ["C:/a.mp4"]})
        finally:
            run_hub._bring_to_front, run_hub._open_in_media = original
        self.assertEqual(calls, [("front", window), ("media", ["C:/a.mp4"])])


if __name__ == "__main__":
    unittest.main()
