"""Spinner (ui/widgets/atoms/progress/spinner.py): the arc's angles, turning only while shown,
and DropArea showing it in the icon's place while something is read."""
import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.widgets.atoms.progress import Spinner
    from msl_tools.msl.ui.widgets.compositions.drop_area import DropArea
except ImportError:  # no PySide6 in this Python
    qt = None


@unittest.skipIf(qt is None, "PySide6 is not installed")
class SpinnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def test_the_arc_turns_clockwise_and_breathes_within_its_limits(self):
        spinner = Spinner()
        spans = []
        for step in range(40):
            start, span = spinner.angles(step * 0.05)
            self.assertTrue(0 <= start < 360)
            self.assertTrue(Spinner.SPAN_MIN - 1e-6 <= span <= Spinner.SPAN_MAX + 1e-6)
            spans.append(span)
        self.assertAlmostEqual(spinner.angles(0)[1], Spinner.SPAN_MIN)
        self.assertGreater(max(spans) - min(spans), 150)
        # clockwise: a moment later the head stands at a smaller Qt angle (mod 360)
        self.assertAlmostEqual(spinner.angles(Spinner.TURN_S / 4)[0], 270.0)

    def test_it_turns_only_while_shown(self):
        spinner = Spinner(16)
        self.assertFalse(spinner.is_spinning())
        spinner.show()
        self.assertTrue(spinner.is_spinning())
        spinner.hide()
        self.assertFalse(spinner.is_spinning())

    def test_a_drop_area_reading_shows_it_instead_of_its_icon(self):
        area = DropArea(None, "Drop a video here", "or pick one")
        area.show()
        area.set_busy("Reading clip.mp4…")
        self.assertTrue(area._spinner.isVisible())
        self.assertFalse(area._icon.isVisible())
        area.set_texts("Drop a video here", "or pick one")
        self.assertFalse(area._spinner.isVisible())
        self.assertTrue(area._icon.isVisible())
        area.close()


if __name__ == "__main__":
    unittest.main()
