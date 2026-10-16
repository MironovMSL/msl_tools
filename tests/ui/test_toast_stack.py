"""ToastStack (ui/widgets/compositions/toast_stack.py): where the cards go, how many stay, the
action button, closing, and the clock that stands still under the pointer."""
import os
import time
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.widgets.compositions.toast_stack import Toast, ToastStack, show_toast
except ImportError:  # no PySide6 in this Python
    qt = None


@unittest.skipIf(qt is None, "PySide6 is not installed")
class ToastStackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def setUp(self):
        self.window = qt.QtWidgets.QWidget()
        self.window.resize(600, 400)
        self.inner = qt.QtWidgets.QLabel("page", self.window)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _wait(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_one_stack_per_window_bottom_right_newest_lowest(self):
        first = show_toast(self.inner, "First", seconds=0)
        second = show_toast(self.window, "Second", seconds=0)
        self.assertIs(ToastStack.of(self.inner), ToastStack.of(self.window))
        self._wait(0.3)
        right = 600 - ToastStack.MARGIN + Toast.SHADOW
        self.assertEqual(second.geometry().right() + 1, right)
        self.assertEqual(second.geometry().bottom() + 1, 400 - ToastStack.MARGIN + Toast.SHADOW)
        self.assertLess(first.y(), second.y())
        # the cards (not their shadow room) are GAP apart
        self.assertEqual((second.y() + Toast.SHADOW) - (first.geometry().bottom() + 1 - Toast.SHADOW), ToastStack.GAP)

    def test_at_most_most_the_oldest_goes(self):
        toasts = [show_toast(self.window, f"n{i}", seconds=0) for i in range(ToastStack.MOST + 2)]
        stack = ToastStack.of(self.window)
        self.assertEqual(stack.toasts(), toasts[2:])
        self.assertTrue(toasts[0].is_closing())

    def test_the_action_runs_and_closes_it(self):
        calls = []
        toast = show_toast(self.window, "Done", tone="success", action="Undo", on_action=lambda: calls.append(1),
                           seconds=0)
        self.assertEqual(toast.property("tone"), "success")
        toast.action_button.click()
        self.assertEqual(calls, [1])
        self.assertTrue(toast.is_closing())
        self.assertNotIn(toast, ToastStack.of(self.window).toasts())

    def test_closing_one_moves_the_older_down(self):
        older = show_toast(self.window, "Older", seconds=0)
        newer = show_toast(self.window, "Newer", seconds=0)
        self._wait(0.3)
        bottom, height = newer.y(), newer.height()
        newer.close_toast()
        self._wait(0.4)
        self.assertEqual(older.y(), bottom + height - older.height())

    def test_it_goes_by_itself_but_not_while_hovered(self):
        toast = show_toast(self.window, "Short", seconds=0.15)
        qt.QtWidgets.QApplication.sendEvent(toast, qt.QtGui.QEnterEvent(
            qt.QtCore.QPointF(5, 5), qt.QtCore.QPointF(5, 5), qt.QtCore.QPointF(5, 5)))
        self._wait(0.3)
        self.assertFalse(toast.is_closing())
        qt.QtWidgets.QApplication.sendEvent(toast, qt.QtCore.QEvent(qt.QtCore.QEvent.Type.Leave))
        self._wait(0.3)
        self.assertTrue(toast.is_closing())

    def test_an_unknown_tone_is_info_and_zero_seconds_stays(self):
        toast = show_toast(self.window, "Stays", tone="nonsense", seconds=0)
        self.assertEqual(toast.property("tone"), "info")
        self._wait(0.2)
        self.assertFalse(toast.is_closing())

    def test_a_long_text_makes_a_taller_card(self):
        short = show_toast(self.window, "Short", seconds=0)
        long = show_toast(self.window, "word " * 60, seconds=0)
        self.assertGreater(long.height(), short.height())


if __name__ == "__main__":
    unittest.main()
