"""BlendSlider (ui/widgets/atoms/sliders/blend_slider.py): marks as even steps, a click on one sends
its weight and shows it, a drag sends the weight under the pointer, Esc cancels."""
import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.widgets.atoms.sliders import BlendSlider
except ImportError:  # no PySide6 in this Python
    qt = None

TWEEN = tuple(2 * f - 1 for f in (0.0, 1 / 8, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 3 / 4, 5 / 6, 7 / 8, 1.0))


@unittest.skipIf(qt is None, "PySide6 is not installed")
class BlendSliderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def slider(self):
        slider = BlendSlider()
        slider.resize(330, BlendSlider.HEIGHT)
        slider.set_marks(TWEEN)
        self.sent = []
        slider.drag_started.connect(lambda mods: self.sent.append(("start", mods)))
        slider.dragged.connect(lambda w: self.sent.append(("drag", w)))
        slider.drag_finished.connect(lambda w: self.sent.append(("end", w)))
        slider.cancelled.connect(lambda: self.sent.append(("cancel",)))
        return slider

    def mouse(self, slider, kind, x, buttons=True):
        left = qt.QtCore.Qt.MouseButton.LeftButton
        button = qt.QtCore.Qt.MouseButton.NoButton if kind == qt.QtCore.QEvent.Type.MouseMove else left
        held = left if (buttons and kind != qt.QtCore.QEvent.Type.MouseButtonRelease) else qt.QtCore.Qt.MouseButton.NoButton
        position = qt.QtCore.QPointF(x, slider.height() / 2)
        event = qt.QtGui.QMouseEvent(kind, position, slider.mapToGlobal(position), button, held,
                                     qt.QtCore.Qt.KeyboardModifier.NoModifier)
        qt.QtWidgets.QApplication.sendEvent(slider, event)

    def test_marks_are_even_steps_smallest_nearest_the_middle(self):
        slider = self.slider()
        right = [p for p, w in slider.mark_positions() if p > 0]
        steps = [round(b - a, 6) for a, b in zip([0.0] + right, right)]
        self.assertEqual(len(set(steps)), 1)
        weights = [w for p, w in sorted(slider.mark_positions())]
        self.assertAlmostEqual(weights[0], -1.0)
        self.assertAlmostEqual(weights[4], 2 * (1 / 3) - 1)   # 1/3: the left mark nearest the middle
        slider.set_limit(2.0)                                  # overshoot: the marks end where 1 lies
        self.assertAlmostEqual(max(p for p, _w in slider.mark_positions()), 2 ** -0.5)

    def test_a_click_on_a_mark_only_sends_its_weight(self):
        slider = self.slider()
        position, weight = sorted(slider.mark_positions())[-2]     # 7/8
        x = slider._x_of(position) + 3
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonPress, x)
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonRelease, x)
        self.assertEqual(self.sent[0], ("start", ""))
        self.assertEqual(self.sent[-1][0], "end")
        self.assertAlmostEqual(self.sent[-1][1], weight)
        self.assertAlmostEqual(slider._position, 0.0)          # the knob stays in the middle
        self.assertNotEqual(slider._opening.endValue(), 1.0)   # the track did not open

    def test_a_held_mark_shows_itself_not_the_knob(self):
        slider = self.slider()
        position, weight = sorted(slider.mark_positions())[1]
        x = slider._x_of(position)
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseMove, x, buttons=False)
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonPress, x)
        slider.set_marks(TWEEN)                       # the owner shows its mode again on the press
        self.assertIsNotNone(slider._hovered)         # ...and the hover is kept
        self.assertEqual(slider._pressed_mark, (position, weight))
        slider.grab()
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonRelease, x)
        self.assertIsNone(slider._pressed_mark)
        self.assertAlmostEqual(self.sent[-1][1], weight)

    def test_the_knob_pressed_and_let_go_sends_0_and_shows_no_number(self):
        slider = self.slider()
        centre = slider.width() / 2
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonPress, centre)
        self.assertEqual(self.sent[-1], ("drag", 0.0))      # held: shown at once (a Tweener's 50 %)
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonRelease, centre)
        self.assertEqual(self.sent[-1], ("end", 0.0))

    def test_a_drag_sends_the_weight_under_the_pointer_and_esc_cancels(self):
        slider = self.slider()
        centre = slider.width() / 2
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonPress, centre)
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseMove, centre + slider._half() / 2)
        self.assertAlmostEqual(self.sent[-1][1], 0.25)                # the square of a half
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonRelease, centre + slider._half() / 2)
        self.assertAlmostEqual(self.sent[-1][1], 0.25)
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseButtonPress, centre)
        self.mouse(slider, qt.QtCore.QEvent.Type.MouseMove, centre - 40)
        escape = qt.QtGui.QKeyEvent(qt.QtCore.QEvent.Type.KeyPress, qt.QtCore.Qt.Key.Key_Escape,
                                    qt.QtCore.Qt.KeyboardModifier.NoModifier)
        qt.QtWidgets.QApplication.sendEvent(slider, escape)
        self.assertEqual(self.sent[-1], ("cancel",))
        self.assertFalse(slider.is_dragging())

    def test_it_paints_in_every_state(self):
        slider = self.slider()
        slider.grab()                               # closed
        slider._open = 1.0
        slider._hovered = slider.mark_positions()[0]
        slider.grab()
        slider._dragging = True
        slider._position = 0.5
        slider.grab()


if __name__ == "__main__":
    unittest.main()
