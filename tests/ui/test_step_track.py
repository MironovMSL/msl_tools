"""StepTrack (ui/widgets/atoms/progress/step_track.py): what each step shows for a stage."""
import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.widgets.atoms.progress import StepTrack
except ImportError:  # no PySide6 in this Python
    qt = None


@unittest.skipIf(qt is None, "PySide6 is not installed")
class StepTrackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def test_steps_before_are_done_after_are_waiting(self):
        track = StepTrack(["Read", "Open", "Render", "Video"])
        track.set_stage(2, "running", animate=False)
        self.assertEqual([track.step_state(i) for i in range(4)], ["done", "done", "running", "waiting"])
        track.set_stage(2, "error", animate=False)
        self.assertEqual(track.step_state(2), "error")
        track.set_stage(4, "done", animate=False)
        self.assertEqual([track.step_state(i) for i in range(4)], ["done"] * 4)

    def test_it_breathes_only_while_running_and_shown(self):
        track = StepTrack(["A", "B"])
        track.show()
        track.set_stage(0, "running", animate=False)
        self.assertTrue(track._pulse.isActive())
        track.set_stage(2, "done", animate=False)
        self.assertFalse(track._pulse.isActive())
        track.set_stage(1, "running", animate=False)
        track.hide()
        self.assertFalse(track._pulse.isActive())
        track.close()

    def test_it_paints_in_every_state(self):
        # A Python error inside paintEvent leaves the painter active and takes the process down:
        # painting each state here is what would catch it.
        track = StepTrack(["Read", "Open", "Render", "Video"])
        track.resize(320, 44)
        for index, state in ((0, "running"), (1, "waiting"), (2, "error"), (4, "done")):
            track.set_stage(index, state, animate=False)
            image = qt.QtGui.QImage(320, 44, qt.QtGui.QImage.Format.Format_ARGB32)
            image.fill(0)
            track.render(image)
            self.assertNotEqual(image.pixel(int(track.centers()[0]), 10), 0)

    def test_out_of_range_and_unknown_states_are_tamed(self):
        track = StepTrack(["A", "B", "C"])
        track.set_stage(9, "nonsense", animate=False)
        self.assertEqual(track.stage(), (3, "waiting"))


if __name__ == "__main__":
    unittest.main()
