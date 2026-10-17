"""Animation without Maya: the sliders' arithmetic on a run of keys."""
import unittest

from msl_tools.msl.tools.maya.animation import curves as cv


def block(values=(2.0,), times=None, **extra):
    """A run between a key of 0 at frame 1 and a key of 10 at frame 11 (unless told otherwise)."""
    times = list(times) if times is not None else [6.0 + i for i in range(len(values))]
    extra.setdefault("before", (1.0, 0.0))
    extra.setdefault("after", (11.0, 10.0))
    return cv.Block(times=times, values=list(values), **extra)


class TweenTest(unittest.TestCase):
    def test_the_middle_is_half_way_and_the_ends_are_the_neighbors(self):
        self.assertEqual(cv.apply("tween", block(), 0.0), [5.0])
        self.assertEqual(cv.apply("tween", block(), -1.0), [0.0])
        self.assertEqual(cv.apply("tween", block(), 1.0), [10.0])

    def test_the_marks_are_the_classic_fractions(self):
        marks = cv.BY_KEY["tween"].marks
        self.assertAlmostEqual(cv.apply("tween", block(), marks[1])[0], 1.25)    # 1/8
        self.assertAlmostEqual(cv.apply("tween", block(), marks[4])[0], 10 / 3)  # 1/3
        self.assertAlmostEqual(cv.apply("tween", block(), marks[8])[0], 25 / 3)  # 5/6

    def test_overshoot_goes_past_the_neighbor(self):
        self.assertAlmostEqual(cv.apply("tween", block(), 1.5)[0], 12.5)

    def test_without_both_neighbors_nothing_changes(self):
        self.assertEqual(cv.apply("tween", block(after=None), 0.5), [2.0])


class PoseTest(unittest.TestCase):
    def test_neighbors_go_toward_the_side_dragged_to(self):
        self.assertAlmostEqual(cv.apply("neighbors", block(), 0.5)[0], 6.0)
        self.assertAlmostEqual(cv.apply("neighbors", block(), -0.5)[0], 1.0)
        self.assertEqual(cv.apply("neighbors", block(), 0.0), [2.0])

    def test_default_toward_and_away(self):
        b = block(values=[4.0], default=2.0)
        self.assertAlmostEqual(cv.apply("default", b, 1.0)[0], 2.0)
        self.assertAlmostEqual(cv.apply("default", b, -1.0)[0], 6.0)

    def test_frame_without_a_value_changes_nothing(self):
        self.assertEqual(cv.apply("frame", block(), 1.0), [2.0])
        self.assertAlmostEqual(cv.apply("frame", block(frame_value=8.0), 0.5)[0], 5.0)

    def test_infinity_follows_the_line_of_the_two_keys(self):
        b = block(values=[0.0], times=[12.0], before=(11.0, 10.0), before2=(10.0, 8.0), after=None)
        self.assertAlmostEqual(cv.apply("infinity", b, -1.0)[0], 12.0)
        self.assertEqual(cv.apply("infinity", b, 1.0), [0.0])     # nothing after: nothing changes

    def test_undo_goes_back_by_part(self):
        b = block(values=[4.0, 6.0], undo_values=[0.0, 2.0])
        self.assertEqual(cv.apply("undo", b, 0.5), [2.0, 4.0])


class CurveTest(unittest.TestCase):
    def test_pull_ends_on_the_straight_line_and_push_doubles(self):
        self.assertAlmostEqual(cv.apply("pull_push", block(), -1.0)[0], 5.0)
        self.assertAlmostEqual(cv.apply("pull_push", block(), 1.0)[0], -1.0)

    def test_a_run_without_neighbors_hangs_between_its_ends(self):
        b = block(values=[0.0, 5.0, 4.0], times=[1.0, 2.0, 3.0], before=None, after=None)
        self.assertEqual(cv.apply("pull_push", b, -1.0), [0.0, 2.0, 4.0])

    def test_scales(self):
        b = block(values=[2.0, 4.0], times=[5.0, 6.0], default=0.0)
        self.assertEqual(cv.apply("scale_average", b, -1.0), [3.0, 3.0])
        self.assertEqual(cv.apply("scale_default", b, 1.0), [4.0, 8.0])
        self.assertEqual(cv.apply("scale_left", b, 1.0), [4.0, 8.0])        # about the 0 before
        self.assertEqual(cv.apply("scale_right", b, -0.5), [6.0, 7.0])      # halfway to the 10 after
        self.assertEqual(cv.apply("scale_frame", b, 1.0), [2.0, 4.0])       # no frame value: nothing

    def test_smooth_and_rough(self):
        b = block(values=[0.0, 8.0, 0.0], times=[5.0, 6.0, 7.0], before=(4.0, 0.0), after=(8.0, 0.0))
        smooth = cv.apply("smooth_rough", b, -1.0)
        self.assertEqual(smooth, [2.0, 4.0, 2.0])
        rough = cv.apply("smooth_rough", b, 1.0)
        self.assertEqual(rough, [-2.0, 12.0, -2.0])

    def test_ease_grows_like_the_reference(self):
        b = block(values=[5.0], times=[6.0])                          # half way between 0 and 10
        self.assertAlmostEqual(cv.apply("ease", b, -1.0)[0], 10 * 0.5 ** 10, places=4)   # 0.0098, as measured
        self.assertAlmostEqual(cv.apply("ease", b, 1.0)[0], 10 - 10 * 0.5 ** 10, places=4)
        quarter, half, three = (cv.apply("ease", b, w)[0] for w in (0.25, 0.5, 0.75))
        self.assertTrue(5.0 < quarter < half < three < 10.0)
        self.assertAlmostEqual(half, 8.04, delta=0.5)                  # measured ~8.04 (its marks' weights are a guess)
        self.assertAlmostEqual(three, 9.78, delta=0.3)                 # measured ~9.78

    def test_a_small_ease_blends_in(self):
        b = block(values=[2.0], times=[6.0])                           # not on the ease's line
        self.assertAlmostEqual(cv.apply("ease", b, 0.01)[0], 2.0, delta=0.2)

    def test_time_offset_reads_the_curve_earlier(self):
        b = block(values=[6.0], times=[6.0], evaluate=lambda time: time)
        self.assertAlmostEqual(cv.apply("time_offset", b, 0.5)[0], 1.0)   # 5 frames later = the value of frame 1
        stagger = block(values=[6.0], times=[6.0], evaluate=lambda time: time, order=0, count=3)
        self.assertEqual(cv.apply("stagger", stagger, 1.0), [6.0])       # the first object stays
        stagger.order = 2
        self.assertAlmostEqual(cv.apply("stagger", stagger, 1.0)[0], 6.0 - cv.OFFSET_FRAMES)

    def test_noise_is_the_same_for_one_seed_and_wave_alternates(self):
        b = block(values=[2.0, 2.0, 2.0], times=[5.0, 6.0, 7.0], seed=7)
        self.assertEqual(cv.apply("noise_wave", b, -1.0), cv.apply("noise_wave", b, -1.0))
        wave = cv.apply("noise_wave", b, 1.0)
        self.assertGreater(wave[0], 2.0)
        self.assertLess(wave[1], 2.0)

    def test_connect_fades_along_the_run(self):
        b = block(values=[4.0, 4.0, 4.0], times=[5.0, 6.0, 7.0])
        self.assertEqual(cv.apply("connect", b, -1.0), [0.0, 2.0, 4.0])     # first meets the 0 before
        self.assertEqual(cv.apply("connect", b, 1.0), [4.0, 7.0, 10.0])     # last meets the 10 after

    def test_zero_weight_changes_nothing(self):
        for mode in cv.MODES:
            if mode.key != "tween":
                self.assertEqual(cv.apply(mode, block(evaluate=lambda t: 2.0), 0.0), [2.0], mode.key)


class FeelTest(unittest.TestCase):
    def test_weight_grows_with_the_square_and_back(self):
        self.assertAlmostEqual(cv.weight_at(0.5), 0.25)
        self.assertAlmostEqual(cv.weight_at(-1.0, 2.0), -2.0)
        for weight in (-1.5, -0.3, 0.0, 0.1, 1.0):
            self.assertAlmostEqual(cv.weight_at(cv.position_of(weight, 2.0), 2.0), weight)

    def test_modifiers_pick_a_mode_of_the_slider_family(self):
        self.assertEqual(cv.mode_for_modifiers(cv.POSE, "shift").key, "neighbors")
        self.assertEqual(cv.mode_for_modifiers(cv.CURVE, "Shift").key, "smooth_rough")
        self.assertEqual(cv.mode_for_modifiers(cv.CURVE, "shift+alt").key, "scale_default")
        self.assertIsNone(cv.mode_for_modifiers(cv.POSE, ""))

    def test_every_modifier_is_used_once_per_family(self):
        for family in (cv.POSE, cv.CURVE):
            used = [cv.normalize_modifiers(m.modifier) for m in cv.MODES if m.family == family and m.modifier]
            self.assertEqual(len(used), len(set(used)), family)


class RunsTest(unittest.TestCase):
    def test_split_and_block(self):
        self.assertEqual(cv.split_runs([7, 1, 2, 3]), [[1, 2, 3], [7]])
        b = cv.block_from_keys([1, 6, 11, 21], [0, 2, 10, 0], [1, 2])
        self.assertEqual((b.before, b.after, b.before2, b.after2), ((1.0, 0.0), (21.0, 0.0), None, None))


if __name__ == "__main__":
    unittest.main()
