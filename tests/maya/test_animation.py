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
        two = block(frame_value=8.0, frame_value_right=12.0)                # the left and the right frame
        self.assertAlmostEqual(cv.apply("frame", two, -0.5)[0], 5.0)        # half way to the left one's 8
        self.assertAlmostEqual(cv.apply("frame", two, 0.5)[0], 7.0)         # half way to the right one's 12

    def test_buffer_toward_and_away_and_none_without_one(self):
        b = block(values=[7.0, 5.0], times=[5.0, 9.0], buffer_values=[4.0, 2.0])
        self.assertEqual(cv.apply("buffer", b, 1.0), [4.0, 2.0])
        self.assertEqual(cv.apply("buffer", b, 0.5), [5.5, 3.5])
        self.assertEqual(cv.apply("buffer", b, -1.0), [10.0, 8.0])
        self.assertEqual(cv.apply("buffer", block(values=[7.0]), 1.0), [7.0])

    def test_undo_goes_back_by_part(self):
        b = block(values=[4.0, 6.0], undo_values=[0.0, 2.0])
        self.assertEqual(cv.apply("undo", b, 0.5), [2.0, 4.0])


class CurveTest(unittest.TestCase):
    def test_a_run_without_neighbors_hangs_between_its_ends(self):
        b = block(values=[0.0, 5.0, 4.0], times=[1.0, 2.0, 3.0], before=None, after=None)
        self.assertEqual(cv.apply("pull_push", b, -1.0), [0.0, 2.0, 4.0])

    def test_ease_is_the_reference_measured(self):
        # keys 3 / 5 / 7 / 9 (a zigzag) between unpicked 0 at 1 and 10 at 11, as clicked on the reference
        b = block(values=[7.0, 1.0, 9.0, 2.0], times=[3.0, 5.0, 7.0, 9.0])
        measured = {0.0: (2.0, 4.0, 6.0, 8.0),             # the knob: straight, whatever the keys held
                    -1.0: (0.0, 0.001, 0.06, 1.074), -0.75: (0.001, 0.065, 0.602, 2.931),
                    -0.5: (0.228, 1.161, 3.011, 5.919), -0.25: (0.969, 2.648, 4.768, 7.236),
                    0.25: (2.764, 5.232, 7.352, 9.031), 0.5: (4.081, 6.989, 8.839, 9.772),
                    0.75: (7.069, 9.398, 9.935, 9.999), 1.0: (8.926, 9.94, 9.999, 10.0)}
        for weight, wanted in measured.items():
            for got, value in zip(cv.apply("ease", b, weight), wanted):
                self.assertAlmostEqual(got, value, delta=0.02, msg=f"weight {weight}")

    def test_time_offset_slides_the_curve_under_the_keys(self):
        b = block(values=[6.0], times=[6.0], evaluate=lambda time: time)
        self.assertAlmostEqual(cv.apply("time_offset", b, 0.25)[0], 3.5)    # a quarter of 10 frames later
        marks = [round(w * cv.OFFSET_FRAMES, 6) for w in cv.BY_KEY["time_offset"].marks if w > 0]
        self.assertEqual(marks, [0.5, 1.0, 2.0, 3.0, 10.0])                  # the reference's marks, in frames

    def test_time_offset_wraps_round_the_curve_as_a_cycle(self):
        # keys 0 / 10 / 0 every 4 frames; the key on the last frame takes the value from just after the first
        times, values = [1.0, 5.0, 9.0], [0.0, 10.0, 0.0]
        b = cv.block_from_keys(times, values, [2], evaluate=lambda t: 10.0 - abs(t - 5.0) * 2.5)
        self.assertEqual(b.cycle, (1.0, 9.0))
        self.assertAlmostEqual(cv.apply("time_offset", b, -0.5 / cv.OFFSET_FRAMES)[0], 1.25)   # 9.5 -> 1.5

    def test_stagger_goes_root_to_tip_whatever_the_pick(self):
        tail = ["|tail_root|tail_01|tail_02|tail_03", "|tail_root|tail_01", "|tail_root|tail_01|tail_02"]
        ranks = cv.chain_ranks(tail)
        self.assertEqual(sorted(ranks, key=ranks.get), [tail[1], tail[2], tail[0]])    # root first, tip last
        self.assertEqual(cv.chain_ranks(["|C", "|A", "|B"]), {"|A": 0, "|B": 1, "|C": 2})  # side by side: by name

    def test_stagger_gives_each_object_its_part_in_order(self):
        # measured: three objects get 1/3, 2/3 and the whole shift
        got = []
        for order in range(3):
            b = block(values=[6.0], times=[6.0], evaluate=lambda time: time, order=order, count=3)
            got.append(round(6.0 - cv.apply("stagger", b, 1.0)[0], 6))
        self.assertEqual(got, [round(cv.OFFSET_FRAMES / 3, 6), round(cv.OFFSET_FRAMES * 2 / 3, 6),
                               cv.OFFSET_FRAMES])

    def test_zero_weight_changes_nothing(self):
        for mode in cv.MODES:
            if mode.key not in ("tween", "ease"):        # these two are places, not changes
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



# The reference MEASURED (2026-10-17, the user's Maya 2025): a probe of 11 keys - 0 3 8 5 9 2 7 4 10 6 1 on frames
# 1, 3 .. 21 -, the five on frames 7 .. 15 picked in the Graph Editor, every mark clicked. weight -> the five keys.
PROBE = dict(times=[7.0, 9.0, 11.0, 13.0, 15.0], values=[5.0, 9.0, 2.0, 7.0, 4.0], before=(5.0, 8.0), after=(17.0, 10.0),
             before2=(3.0, 3.0), after2=(19.0, 6.0), default=0.0)
MEASURED = {
    "neighbors": {-1: (8, 8, 8, 8, 8), -0.5: (6.5, 8.5, 5, 7.5, 6), -0.05: (5.15, 8.95, 2.3, 7.05, 4.2),
                  0.05: (5.25, 9.05, 2.4, 7.15, 4.3), 0.5: (7.5, 9.5, 6, 8.5, 7), 1: (10, 10, 10, 10, 10)},
    "default": {-1: (10, 18, 4, 14, 8), -0.5: (7.5, 13.5, 3, 10.5, 6), 0.5: (2.5, 4.5, 1, 3.5, 2), 1: (0, 0, 0, 0, 0)},
    "infinity": {-1: (30, 26, 22, 18, 14), -0.5: (17.5, 17.5, 12, 12.5, 9), -0.05: (6.25, 9.85, 3.0, 7.55, 4.5),
                 0.05: (5.4, 9.45, 3.05, 8.05, 5.45), 0.5: (9, 13.5, 12.5, 17.5, 18.5), 1: (13, 18, 23, 28, 33)},
    "pull_push": {-1: (8.3333, 8.6667, 9, 9.3333, 9.6667), -0.5: (6.6667, 8.8333, 5.5, 8.1667, 6.8333),
                  0.05: (4.6667, 9.0333, 1.3, 6.7667, 3.4333), 0.5: (1.6667, 9.3333, -5, 4.6667, -1.6667),
                  1: (-1.6667, 9.6667, -12, 2.3333, -7.3333)},
    "smooth_rough": {-1: (6.75, 6.25, 5, 5, 6.25), -0.5: (5.875, 7.625, 3.5, 6, 5.125),
                     -0.05: (5.0875, 8.8625, 2.15, 6.9, 4.1125), 0.05: (4.825, 9.275, 1.7, 7.2, 3.775),
                     0.5: (3.25, 11.75, -1, 9, 1.75), 1: (1.5, 14.5, -4, 11, -0.5)},
    "scale_average": {-1: (6, 2, 9, 4, 7), -0.5: (5.5, 5.5, 5.5, 5.5, 5.5), -0.05: (5.05, 8.65, 2.35, 6.85, 4.15),
                      0.05: (4.95, 9.35, 1.65, 7.15, 3.85), 0.5: (4.5, 12.5, -1.5, 8.5, 2.5), 1: (4, 16, -5, 10, 1)},
    "scale_default": {-1: (-5, -9, -2, -7, -4), -0.5: (0, 0, 0, 0, 0), -0.05: (4.5, 8.1, 1.8, 6.3, 3.6),
                      0.05: (5.5, 9.9, 2.2, 7.7, 4.4), 0.5: (10, 18, 4, 14, 8), 1: (15, 27, 6, 21, 12)},
    "connect": {-1: (8, 12, 5, 10, 7), -0.5: (6.5, 10.5, 3.5, 8.5, 5.5), -0.05: (5.15, 9.15, 2.15, 7.15, 4.15),
                0.05: (5.3, 9.3, 2.3, 7.3, 4.3), 0.5: (8, 12, 5, 10, 7), 1: (11, 15, 8, 13, 10)},
    "noise_wave": {0.05: (4.65, 9.35, 1.65, 7.35, 3.65), 0.5: (1.5, 12.5, -1.5, 10.5, 0.5),
                   1: (-2, 16, -5, 14, -3)},
}


class MeasuredTest(unittest.TestCase):
    def test_every_mode_matches_the_reference(self):
        for mode, rows in MEASURED.items():
            for weight, wanted in rows.items():
                got = cv.apply(mode, cv.Block(**PROBE), weight)
                for value, expected in zip(got, wanted):
                    self.assertAlmostEqual(value, expected, delta=0.002, msg=f"{mode} at {weight}")

    def test_noise_stays_within_the_runs_range(self):
        b = cv.Block(**PROBE, seed=3)
        noisy = cv.apply("noise_wave", b, -1.0)
        self.assertEqual(noisy, cv.apply("noise_wave", b, -1.0))         # the same within one drag
        self.assertTrue(all(abs(n - v) <= 7.0 for n, v in zip(noisy, PROBE["values"])))
        self.assertNotEqual(noisy, PROBE["values"])

    def test_the_blend_marks_are_the_references(self):
        self.assertEqual(cv.BLEND_MARKS, (-1.0, -0.5, -0.15, -0.05, 0.05, 0.15, 0.5, 1.0))

if __name__ == "__main__":
    unittest.main()
