"""ui/workers/result_worker.py: a worker with a parent is gone once it is over."""
import os
import time
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.workers.result_worker import ResultWorker
except ImportError:  # no PySide6 in this Python
    qt = None


@unittest.skipIf(qt is None, "PySide6 is not installed")
class Lifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def pump_until(self, condition, seconds=5.0):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            # deleteLater runs on DeferredDelete, which processEvents() alone doesn't deliver
            qt.QtCore.QCoreApplication.sendPostedEvents(None, qt.QtCore.QEvent.Type.DeferredDelete)
            time.sleep(0.01)

    def test_parented_worker_deletes_itself_and_still_delivers(self):
        owner = qt.QtCore.QObject()
        results, gone = [], []
        worker = ResultWorker(lambda: 42, parent=owner)
        worker.done.connect(results.append)
        worker.destroyed.connect(lambda *_: gone.append(True))
        worker.start()
        self.pump_until(lambda: gone)
        self.assertEqual(results, [42])
        self.assertEqual(gone, [True])
        self.assertEqual(owner.findChildren(ResultWorker), [])

    def test_parentless_worker_is_left_to_its_owner(self):
        worker = ResultWorker(lambda: 1)
        results = []
        worker.done.connect(results.append)
        worker.start()
        self.pump_until(lambda: results and worker.isFinished())
        self.pump_until(lambda: False, seconds=0.2)
        self.assertEqual(results, [1])
        self.assertTrue(worker.isFinished())  # still a live object: not deleted


if __name__ == "__main__":
    unittest.main()
