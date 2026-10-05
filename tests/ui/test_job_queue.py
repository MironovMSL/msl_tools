"""Media's JobQueue as a farm's queue: pause holds the line, waiting jobs are reordered, a
forgotten pause doesn't outlive the batch. No ffmpeg: nothing is started while paused, and the
runner is never reached (tools = None makes a started job fail at once)."""
import os
import time
import unittest
from pathlib import Path

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.core.media import Job
    from msl_tools.msl.tools.desktop.media.job_queue import FAILED, WAITING, JobQueue
except ImportError:  # no PySide6 in this Python
    qt = None


@unittest.skipIf(qt is None, "PySide6 is not installed")
class FarmQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def setUp(self):
        self.queue = JobQueue(lambda: None)
        self.queue.pause()
        self.items = [self.queue.add(Job(title=name, output=Path(name), passes=[[]])) for name in "abcd"]

    def order(self):
        return [item.job.title for item in self.queue.waiting()]

    def test_paused_nothing_starts(self):
        self.assertTrue(self.queue.is_paused())
        self.assertEqual(self.order(), list("abcd"))
        self.assertTrue(all(item.state == WAITING for item in self.items))

    def test_reorder(self):
        self.queue.run_next(self.items[3].id)
        self.assertEqual(self.order(), list("dabc"))
        self.queue.move(self.items[3].id, 2)
        self.assertEqual(self.order(), list("abdc"))
        self.queue.move(self.items[0].id, -5)      # already first: stays
        self.assertEqual(self.order(), list("abdc"))
        self.queue.run_last(self.items[0].id)
        self.assertEqual(self.order(), list("bdca"))

    def test_resume_runs_them_in_the_new_order_and_the_pause_ends_with_the_batch(self):
        self.queue.run_last(self.items[0].id)
        ended = []
        self.queue.changed.connect(lambda item: ended.append(item.job.title) if item.state == FAILED else None)
        self.queue.resume()
        deadline = time.monotonic() + 3
        while self.queue.busy() and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertEqual(ended, list("bcda"))      # no ffmpeg: each fails at once, in the line's order
        self.assertFalse(self.queue.busy())
        self.queue.pause()
        self.queue.cancel(self.queue.add(Job(title="e", output=Path("e"), passes=[[]])).id)
        self.assertFalse(self.queue.is_paused())   # the batch is over: the pause went with it


if __name__ == "__main__":
    unittest.main()
