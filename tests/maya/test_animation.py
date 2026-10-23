"""Animation without Maya: the sliders' arithmetic on a run of keys."""
import unittest

from msl_tools.msl.tools.maya.animation import curves as cv
from msl_tools.msl.tools.maya.animation import keys as ky


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
        for family in (cv.POSE, cv.CURVE, cv.TANGENT):
            used = [cv.normalize_modifiers(m.modifier) for m in cv.MODES + cv.TANGENT_MODES
                    if m.family == family and m.modifier]
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

    def test_gap_stitcher_matches_the_reference(self):
        import math
        values = [round(2 * math.sin(f * 0.8) + (10 if f >= 16 else 0), 4) for f in range(1, 31)]
        b = cv.block_from_keys([float(f) for f in range(1, 31)], values, list(range(10, 20)))   # frames 11..20
        measured = {1: (0.035, 0.277, 0.936, 2.219, 4.334), 0.5: (0.095, 0.381, 0.858, 1.525, 2.383),
                    0.15: (0.094, 0.232, 0.393, 0.572, 0.764), 0.05: (0.044, 0.095, 0.148, 0.203, 0.26)}
        for weight, left in measured.items():
            for sign in (-1, 1):                                       # both sides of the slider alike
                moved = [g - v for g, v in zip(cv.apply("gap", b, sign * weight), b.values)]
                for got, wanted in zip(moved, left + tuple(-x for x in reversed(left))):
                    self.assertAlmostEqual(got, wanted, delta=0.002, msg=f"gap at {sign * weight}")

    def test_gap_stitcher_on_a_run_split_unevenly(self):
        # measured: 13 keys picked (frames 16..28), a drop of 6 between 22 and 23 - 7 keys before it, 6 after
        base = [-0.4931, -0.6137, -1.0878, -1.4034, -1.1893, -0.9188, -0.2844, -6.258, -5.9985, -5.6892,
                -5.7937, -6.3896, -6.8165]
        b = cv.Block(times=[float(f) for f in range(16, 29)], values=base, before=(15.0, 0.636), after=(29.0, -7.5681))
        measured = {1: (-0.009, -0.07, -0.235, -0.557, -1.089, -1.881, -2.987, 1.881, 1.088, 0.557, 0.235, 0.07, 0.009),
                    0.5: (-0.03, -0.122, -0.274, -0.488, -0.762, -1.097, -1.493, 1.097, 0.762, 0.488, 0.274, 0.122,
                          0.03),
                    0.05: (-0.018, -0.038, -0.059, -0.081, -0.103, -0.126, -0.149, 0.126, 0.103, 0.081, 0.059,
                           0.038, 0.018)}
        for weight, wanted in measured.items():
            moved = [g - v for g, v in zip(cv.apply("gap", b, weight), base)]
            for got, value in zip(moved, wanted):
                self.assertAlmostEqual(got, value, delta=0.002, msg=f"gap at {weight}")

    def test_simplify_keeps_what_the_reference_keeps(self):
        import math
        times = [float(f) for f in range(1, 32)]
        values = [round(5 * math.sin(f * 0.3) + 0.3 * math.sin(f * 2.1), 4) for f in range(1, 32)]
        self.assertEqual([len(cv.simplify_keep(times, values, w)) for w in (-0.05, -0.15, -0.5, -1)],
                         [30, 29, 22, 12])
        self.assertEqual([int(times[i]) for i in cv.simplify_keep(times, values, -1)],
                         [1, 4, 7, 10, 11, 14, 17, 20, 22, 25, 28, 31])

    def test_bake_adds_whole_frames(self):
        keys = [1.0, 7.0, 13.0, 19.0, 25.0]
        self.assertEqual(cv.bake_times(keys, 0.5), [3.0, 5.0, 9.0, 11.0, 15.0, 17.0, 21.0, 23.0])
        self.assertEqual(len(cv.bake_times(keys, 1.0)), 20)
        self.assertEqual(cv.bake_times(keys, 0.15), [])                 # measured: nothing at the small marks
        uneven = [1.0, 5.0, 12.0, 20.0, 23.0, 30.0]                     # measured: counted back from each later key
        self.assertEqual(sorted(cv.bake_times(uneven, 0.5) + uneven),
                         [1, 3, 5, 6, 8, 10, 12, 14, 16, 18, 20, 21, 23, 24, 26, 28, 30])

    def test_the_blend_marks_are_the_references(self):
        self.assertEqual(cv.BLEND_MARKS, (-1.0, -0.5, -0.15, -0.05, 0.05, 0.15, 0.5, 1.0))


class BlendToEaseTest(unittest.TestCase):
    """The reference's Blend to Ease, every mark clicked on the 11-key probe (keys 5 9 2 7 4 on frames 7..15
    picked, 8 at 5 before them, 10 at 17 after)."""

    MEASURED = {-1: (8.0, 8.0, 7.994, 7.983, 7.354), -0.5: (8.0, 8.004, 7.812, 7.868, 6.392),
                -0.15: (7.796, 8.192, 5.879, 7.456, 4.957), -0.05: (6.775, 8.577, 3.757, 7.184, 4.349),
                0.05: (5.436, 9.184, 4.343, 8.268, 7.551), 0.15: (6.196, 9.456, 7.172, 9.423, 9.592),
                0.5: (7.991, 9.868, 9.75, 9.988, 9.999), 1: (9.192, 9.983, 9.992, 10.0, 10.0)}

    def test_every_mark_is_the_references(self):
        b = block(values=[5, 9, 2, 7, 4], times=[7, 9, 11, 13, 15], before=(5.0, 8.0), after=(17.0, 10.0))
        for weight, wanted in self.MEASURED.items():
            for got, value in zip(cv.apply("blend_ease", b, weight), wanted):
                self.assertAlmostEqual(got, value, delta=0.002, msg=f"blend to ease at {weight}")

    def test_it_holds_ctrl_shift_like_the_reference(self):
        self.assertEqual(cv.mode_for_modifiers(cv.POSE, "ctrl+shift").key, "blend_ease")


class KeysTest(unittest.TestCase):
    """Keys and timing (keys.py) - the numbers are the reference's, measured on a probe of
    A tx 1 5 9 13 20, A ry 1 9 20, B tx 1 4 11 17, C ty 2 7 15."""

    TX = [1.0, 5.0, 9.0, 13.0, 20.0]

    def test_nudge_moves_the_picked_keys(self):
        self.assertEqual(ky.nudge(self.TX, [2], -3), {2: 6.0})
        self.assertEqual(ky.nudge(self.TX, [1, 2], 2), {1: 7.0, 2: 11.0})

    def test_nudge_onto_a_key_replaces_it_and_past_one_refuses_all(self):
        self.assertEqual(ky.nudge(self.TX, [3], -4), {3: 9.0, 2: None})      # 13 -> 9 took 9's place
        self.assertIsNone(ky.nudge(self.TX, [2], -5))                         # 9 would pass 5
        self.assertIsNone(ky.nudge(self.TX, [1, 3], -6))                      # 13 would pass 9: 5 stays too

    def test_the_nearest_key_on_a_side(self):
        times = [1.0, 5.0, 9.0, 4.0, 11.0]
        self.assertEqual(ky.nearest_key(times, 7.0, 1), 9.0)
        self.assertEqual(ky.nearest_key(times, 7.0, -1), 5.0)
        self.assertIsNone(ky.nearest_key(times, 20.0, 1))

    def test_inbetween_after_the_current_frame(self):
        self.assertEqual(ky.inbetween(self.TX, [9.0], 1), [1, 5, 9, 14, 21])
        self.assertEqual(ky.inbetween(self.TX, [7.0], 2), [1, 5, 11, 15, 22])
        self.assertEqual(ky.inbetween(self.TX, [7.0], -3), [1, 5, 6, 10, 17])

    def test_inbetween_after_each_anchor(self):
        self.assertEqual(ky.inbetween(self.TX, [5.0, 13.0], 1), [1, 5, 10, 14, 22])       # picked 5 and 13
        self.assertEqual(ky.inbetween(self.TX, [4, 5, 9, 11], 1), [1, 6, 11, 17, 24])     # a range's key times
        self.assertEqual(ky.inbetween([1.0, 4.0, 11.0, 17.0], [4, 5, 9, 11], -1), [1, 4, 8, 13])

    def test_a_removal_onto_the_key_before_is_refused(self):
        self.assertIsNone(ky.inbetween(self.TX, [7.0], -4))
        self.assertIsNone(ky.inbetween(self.TX, [7.0], -5))

    def test_spacing_the_times_in_play(self):
        self.assertEqual(ky.remap(self.TX, ky.spaced([5, 9, 13], 2)), [1, 5, 7, 9, 20])
        self.assertEqual(ky.spaced([9, 13, 11, 17], 2), {9: 9, 11: 11, 13: 13, 17: 15})
        self.assertEqual(ky.remap(self.TX, ky.spaced([5, 9, 13], 6)), [1, 5, 11, 17, 20])
        self.assertIsNone(ky.remap(self.TX, ky.spaced([5, 9, 13], 8)))           # 13 -> 21 would pass 20

    def test_bake_on_a_grid_keeps_keys_outside(self):
        grid, removed = ky.bake_plan([2.0, 7.0, 15.0], 1, 40, 3)
        self.assertEqual(grid[:6], [1, 4, 7, 10, 13, 16])
        self.assertEqual(grid[-1], 40)
        self.assertEqual(removed, [0, 2])
        grid, removed = ky.bake_plan([2.0, 7.0, 15.0], 7, 15, 2)                # picked 7 .. 15
        self.assertEqual((grid, removed), ([7, 9, 11, 13, 15], []))
        self.assertEqual(ky.bake_grid(1, 10, 2.5), [1, 3.5, 6, 8.5])

    def test_snap_goes_to_the_nearest_frame_half_way_down(self):
        self.assertEqual([ky.snap_frame(t) for t in (3.4, 5.6, 8.5, 4.5, 6.5, 3.45)], [3, 6, 8, 4, 6, 3])
        groups = ky.snap_plan([1.0, 3.4, 3.45, 4.5, 6.5, 8.0])
        self.assertEqual(groups, {3.0: [1, 2], 4.0: [3], 6.0: [4]})
        self.assertEqual(ky.snap_plan([1.0, 3.6, 4.0]), {4.0: [1, 2]})            # joins the key on its frame

    def test_pasting_key_times(self):
        c = [2.0, 7.0, 15.0]
        self.assertEqual(ky.paste_times(c, self.TX, ky.MERGE), ([2, 7, 15], []))
        self.assertEqual(ky.paste_times(c, self.TX, ky.REPLACE), ([2, 7, 15], [1, 2, 3]))     # 1 and 20 stay
        self.assertEqual(ky.paste_times(c, self.TX, ky.INSERT, now=9), ([14, 22], [3, 4]))     # 9 14 22

    def test_union_of_key_times(self):
        self.assertEqual(ky.union(self.TX, [1, 9, 20], [1, 4, 11, 17]), [1, 4, 5, 9, 11, 13, 17, 20])

    def test_colors_are_maya_flags(self):
        self.assertEqual(ky.color_of(False, False), ky.RED)
        self.assertEqual(ky.color_of(False, True), ky.YELLOW)
        self.assertEqual(ky.color_of(True, False), ky.GREEN)
        self.assertEqual(ky.COLOR_FLAGS[ky.YELLOW], (False, True))

    def test_infinity_repeats_the_cycle_inside_the_range(self):
        # C ty 2:5 7:1 15:6 cycling, range 1-30 (measured: 2 7 15 20 28 inside, a seam at 15 and 28)
        found = ky.infinity_keys([2.0, 7.0, 15.0], [5.0, 1.0, 6.0], 1, 30, ky.CYCLE, ky.CYCLE)
        self.assertEqual([t for t, _v, _s in found], [1.99, 15.01, 20.0, 28.0, 28.01])
        self.assertEqual([v for _t, v, _s in found], [6.0, 5.0, 1.0, 6.0, 5.0])

    def test_infinity_with_offset_rises_and_meets_without_a_seam(self):
        found = ky.infinity_keys([0.0, 5.0, 10.0], [0.0, 3.0, 2.0], 0, 25, ky.CONSTANT, ky.CYCLE_OFFSET)
        self.assertEqual(found, [(15.0, 5.0, 1), (20.0, 4.0, 2), (25.0, 7.0, 1)])
        self.assertEqual(ky.infinity_keys([0.0, 5.0], [0.0, 1.0], 0, 20, ky.LINEAR, ky.CONSTANT), [])


if __name__ == "__main__":
    unittest.main()


class ToolGroupNumbersTest(unittest.TestCase):
    """The tool groups' numbers (keys.fill / precise_times) and the hotkeys reaching real functions."""

    def test_fill_puts_in_the_frames_and_the_precise_step(self):
        self.assertEqual(ky.fill(("N", "-N", "STEP", "-STEP", 3, True, "all"), 2.0, 0.5),
                         [2.0, -2.0, 0.5, -0.5, 3, True, "all"])

    def test_precise_steps_measured_on_the_reference(self):
        self.assertEqual(ky.precise_times(False, False), 1.0)
        self.assertEqual(ky.precise_times(True, False), 0.1)     # a tenth of the field
        self.assertEqual(ky.precise_times(False, True), 5.0)     # five times it
        self.assertEqual(ky.precise_times(True, True), 0.1)

    def test_the_wheel_weights_match_the_reference(self):
        # one notch = the middle, each next notch 0.3 of the half track: weight 0.09 (n - 1)^2 (measured)
        weights = [cv.weight_at(-0.3 * (n - 1)) for n in range(1, 5)]
        for got, want in zip(weights, (0.0, -0.09, -0.36, -0.81)):
            self.assertAlmostEqual(got, want)

    def test_every_animation_hotkey_names_a_function_that_exists(self):
        import ast
        from pathlib import Path
        from msl_tools.msl.tools.maya.hotkey_catalog import KEY_COMMANDS
        folder = Path(ky.__file__).parent
        defined = {}
        for module in ("keys_scene", "precise", "default_pose", "tangents_scene", "transfer_scene",
                       "mirror_scene", "align_scene", "xform_scene",
                       "space_menu"):
            tree = ast.parse((folder / f"{module}.py").read_text(encoding="utf-8"))
            defined[module] = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        for command in KEY_COMMANDS:
            call = ast.parse(command.python.split("; ", 1)[1]).body[0].value
            name = call.args[0].value
            module, _, function = name.rpartition(".")
            self.assertIn(function, defined[module or "keys_scene"], command.name)


class TangentsTest(unittest.TestCase):
    """The TANGENTS group's arithmetic (tangents.py) - the numbers measured on the reference (Maya 2025)."""

    def setUp(self):
        from msl_tools.msl.tools.maya.animation import tangents
        self.tg = tangents

    def test_best_guess_clamps_the_ends_and_the_extremes(self):
        guess = self.tg.best_guess
        self.assertEqual("".join(k[0] for k in guess([0, 3, 8, 5, 9, 2, 7, 4, 10, 6, 1])), "cacccccccac")
        self.assertEqual("".join(k[0] for k in guess([0, 0, 5, 5, 5, 0])), "caaaac")
        self.assertEqual("".join(k[0] for k in guess([1, 1, 4, 1, 1])), "cacac")

    def test_the_end_rule_matches_bounce_and_polished_ends(self):
        rule = self.tg.end_rule
        for d, m, want in ((2.5, 2.0, 2.7222), (-1.5, 0.25, -2.2777), (2.0, -0.75, 3.2223), (2.5, 0.0, 3.6110),
                           (0.5, 0.25, 0.6111), (2.0, 1.3438, 2.2916), (-3.5, -0.75, -4.7221)):
            self.assertAlmostEqual(rule(d, m), want, places=3)

    def test_bounce_points_straight_at_bounced_neighbors(self):
        times, values = [1, 3, 5, 7, 9, 11], [0, 3, 8, 5, 9, 2]
        ins = outs = [1.5, 2.0, 0.5, 0.25, -0.75, -3.5]
        plan = self.tg.bounce(times, values, [1, 2, 3], ins, outs)
        self.assertAlmostEqual(plan[1][0][1], 1.5)
        self.assertAlmostEqual(plan[1][1][1], 2.5)
        self.assertAlmostEqual(plan[3][1][1], 3.2222, places=3)    # the neighbor after is not bounced
        everything = self.tg.bounce(times, values, range(6), ins, outs)
        self.assertEqual(everything[0][0][0], "linear")
        self.assertEqual(everything[5][1][0], "linear")
        only_in = self.tg.bounce(times, values, [1, 2, 3], ins, outs, "in")
        self.assertAlmostEqual(only_in[3][0][1], -2.3889, places=3)
        self.assertIsNone(only_in[3][1])

    def test_polished_gives_extremes_spline_and_leans_the_ends(self):
        plan = self.tg.polished([1, 5, 9], [0, 10, 0], [0, 1, 2], [2.5, 0, -2.5], [2.5, 0, -2.5])
        self.assertEqual(plan[1][0], ("spline", 0.0))
        self.assertAlmostEqual(plan[0][1][1], 3.6110, places=3)
        self.assertEqual(plan[0][0][0], "spline")                  # the outer side: Maya's spline (measured)
        self.assertAlmostEqual(plan[2][0][1], -3.6110, places=3)

    def test_options_and_cycle_match(self):
        self.assertEqual(self.tg.option_indices(6, [1, 2], "both"), [0, 5])
        self.assertEqual(self.tg.option_indices(6, [1, 2], "all"), list(range(6)))
        plan = self.tg.cycle_match(4, [2.5, 0.375, -1.25, -0.75], [2.5, 0.375, -1.25, -0.75])
        self.assertEqual(plan, {3: (("fixed", 2.5), ("fixed", 2.5))})
        self.assertEqual(self.tg.cycle_match(4, [0, 1, 1, -0.75], [2.5, 1, 1, -0.75], True),
                         {0: (("fixed", -0.75), ("fixed", -0.75))})

    def test_flow_as_measured_on_the_reference(self):
        line = self.tg.flow_slopes([1, 2, 3, 4, 5], [0, 1, 2, 3, 4])           # a straight line: held by the bounds
        for got, want in zip(line, [0.5, 0.765625, 0.703125, 0.817708, 0.5]):
            self.assertAlmostEqual(got, want, places=4)
        bend = self.tg.flow_slopes([1, 2, 3], [0, 1, 1.5])                   # a bend: the kernel alone
        for got, want in zip(bend, [0.4375, 0.8125, 0.1875]):
            self.assertAlmostEqual(got, want, places=4)
        uneven = self.tg.flow_slopes([1, 3, 4], [0, 2, 2.9])                 # the right bound wins by the spacing
        for got, want in zip(uneven, [0.375, 0.6854, 0.4375]):
            self.assertAlmostEqual(got, want, places=3)
        wide = self.tg.flow_slopes([1, 2, 5, 7], [0, 3, -1, 4])              # uneven spacing, kernel only
        self.assertAlmostEqual(wide[0], (3 * 3 + (2 * 3 - 1) * (-4 / 3)) / 8, places=6)

    def test_polished_holds_and_tops_as_measured(self):
        def plan(values):
            times = [1 + 3 * i for i in range(len(values))]
            slopes = [0.0] * len(values)
            return self.tg.polished(times, values, range(len(values)), slopes, slopes)
        top = plan([0, 10, 10, 0])                                 # an even two-key top: both spline
        self.assertEqual((top[1][0][0], top[2][0][0]), ("spline", "spline"))
        three = plan([0, 5, 5, 5, 0])                              # a three-key one goes flat
        self.assertEqual([three[i][0][1] for i in (1, 2, 3)], [0.0, 0.0, 0.0])
        self.assertEqual(plan([0, 10, 10, 20])[1][0][1], 0.0)       # a hold on the way: flat
        lopsided = plan([0, 1.05, 0.8, 0.8, 3.56, 4.61])           # a lopsided two-key bottom: flat (measured)
        self.assertEqual((lopsided[2][0], lopsided[3][0]), (("fixed", 0.0), ("fixed", 0.0)))

    def test_polished_limits_as_measured_on_the_reference(self):
        slopes = self.tg.polished_slopes
        self.assertAlmostEqual(slopes([1, 2, 3], [0, 1, 21])[1][1], 1.591174, places=4)   # a steep side
        self.assertAlmostEqual(slopes([1, 2, 3], [0, 1, 6.5])[1][1], 2.6875, places=4)    # 5.5: not yet - the kernel
        self.assertAlmostEqual(slopes([1, 2, 3], [0, 1, -9])[1][1], -1.4306, places=3)    # an extreme past 83/17
        self.assertEqual(slopes([1, 2, 3], [0, 1, -2])[1][0], "spline")                   # an extreme below it
        self.assertAlmostEqual(slopes([1, 2, 4], [0, 1, -9])[1][1], -0.9538, places=3)    # uneven: rises / mean
        line = slopes([1, 2, 3, 4, 5, 6], [0, 1, 2, 3, 4, 5])                             # a line: the bounds
        for got, want in zip(line[1:-1], [0.4236, 0.7562, 0.6084, 0.7504]):
            self.assertAlmostEqual(got[1], want, places=3)
        mixed = slopes([1, 2, 3, 4, 5, 6, 7], [0, 3.55, -2.61, -2.9, 3.38, -3.38, 0])     # a step at a bottom
        self.assertEqual((mixed[2][0], mixed[3][0]), ("spline", "spline"))
        ends = self.tg.polished([1, 2, 3, 4], [0, 3.05, 0.42, -0.27], range(4), [0] * 4, [0] * 4)
        self.assertAlmostEqual(ends[3][0][1], 0.0183, places=3)    # the end rule may turn against its chord

    def test_the_tangent_slider_blends_the_angle_as_measured(self):
        blend = self.tg.blend_angle
        self.assertAlmostEqual(blend(-31.4, 56.31, 0.5), 12.455)          # half way (measured)
        self.assertAlmostEqual(blend(36.87, 0.0, -0.5), 55.305)           # Flat to the left: steeper (measured)
        self.assertEqual(blend(40.5, -20.556, -1.0), 90.0)                # held to +-90 (measured)
        self.assertEqual(blend(10.0, 30.0, 0.0), 10.0)
        self.assertEqual(cv.mode_for_modifiers(cv.TANGENT, "ctrl").key, "t_polished")
        for mode in cv.TANGENT_MODES:
            self.assertIn(mode.key[2:], ("best_guess", "polished", "flow", "bounce") + self.tg.NATIVE)

    def test_the_end_rule_is_flat_toward_a_hold(self):
        self.assertEqual(self.tg.end_rule(0.0, -0.8333), 0.0)


class TransferTest(unittest.TestCase):
    def setUp(self):
        from msl_tools.msl.tools.maya.animation import transfer
        self.tf = transfer

    def test_one_copied_object_goes_onto_every_target(self):
        self.assertEqual(self.tf.pair(["|A"], ["|ns:A", "|Other"]), [(0, "|ns:A"), (0, "|Other")])

    def test_several_pair_by_name_then_by_order(self):
        copied = ["|rig|L_arm", "|rig|R_arm"]
        self.assertEqual(self.tf.pair(copied, ["|hero:rig|hero:R_arm"]), [(1, "|hero:rig|hero:R_arm")])
        self.assertEqual(self.tf.pair(copied, ["|a", "|b"]), [(0, "|a"), (1, "|b")])
        self.assertEqual(self.tf.pair(copied, ["|a"]), [])

    def test_insert_lands_as_measured(self):
        self.assertEqual(self.tf.landing(1, 40, 12), (11, 12, 51))        # span start on the current frame
        self.assertEqual(self.tf.landing(1, 60, 12, (20, 25)), (19, 20, 25))  # on the span highlighted when pasting

    def test_text_round_trip_and_refusals(self):
        data = {"format": self.tf.FORMAT, "version": 1, "kind": self.tf.POSE, "frame": 5.0,
                "objects": [{"name": "A", "path": "|A", "channels": {"tx": {"value": 5.0}}}]}
        text = self.tf.to_text(data)
        self.assertEqual(self.tf.from_text(text, self.tf.POSE), data)
        self.assertIsNone(self.tf.from_text(text, self.tf.ANIMATION))
        self.assertIsNone(self.tf.from_text("hello"))
        self.assertIsNone(self.tf.from_text('{"format": "msl_transfer"'))
        self.assertEqual(self.tf.describe(data), "1 object, 1 channel (frame 5)")
        self.assertEqual(self.tf.short_name("|rig|ns:arm_ctrl"), "arm_ctrl")


class MirrorTest(unittest.TestCase):
    """Mirror as data; the signs MEASURED on the reference (2026-10-22)."""

    def setUp(self):
        from msl_tools.msl.tools.maya.animation import mirror
        self.mr = mirror

    @staticmethod
    def _frame(rx=0.0, ry=0.0, rz=0.0):
        """Axes of an XYZ Euler turn (degrees) as row vectors, Maya's way (x first)."""
        import math
        def turn(vector, axis, degrees):
            c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
            x, y, z = vector
            if axis == 0:
                return (x, c * y - s * z, s * y + c * z)
            if axis == 1:
                return (c * x + s * z, y, -s * x + c * z)
            return (c * x - s * y, s * x + c * y, z)
        rows = []
        for vector in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            for axis, degrees in ((0, rx), (1, ry), (2, rz)):
                vector = turn(vector, axis, degrees)
            rows.append(vector)
        return rows

    def _signs(self, left, right):
        found, loose = self.mr.channel_signs(left, right)
        return "".join("+" if found[c] > 0 else "-" for c in self.mr.TRANSLATE + self.mr.ROTATE), loose

    def test_measured_sign_sets(self):
        world = self._frame()
        self.assertEqual(self._signs(world, world), ("-++" "+--", []))            # world-aligned pair, middle
        # a pair mirrored with Maya's Behavior (left turned 30 about Z, right (180, 0, -30))
        self.assertEqual(self._signs(self._frame(rz=30), self._frame(rx=180, rz=-30)), ("---" "+++", []))
        # groups turned 90 / -90 about Y
        self.assertEqual(self._signs(self._frame(ry=90), self._frame(ry=-90)), ("-++" "+--", []))

    def test_axes_that_are_no_mirror_are_reported(self):
        signs, loose = self._signs(self._frame(), self._frame(rz=90))
        self.assertIn("translateX", loose)

    def test_name_side(self):
        side = self.mr.name_side
        self.assertEqual(side("|rig|ns:lf_hand_ctrl"), self.mr.LEFT)
        self.assertEqual(side("arm_R"), self.mr.RIGHT)
        self.assertEqual(side("leftArm"), self.mr.LEFT)
        self.assertEqual(side("armRight"), self.mr.RIGHT)
        self.assertEqual(side("spine_ctrl"), "")
        self.assertEqual(side("Lips_ctrl"), "")
        self.assertEqual(side("gauche_arm", left_words=["gauche"]), self.mr.LEFT)

    def test_pairs(self):
        opposite = {"lf_a": "rt_a", "rt_a": "lf_a", "mid": "mid", "lf_b": "rt_b", "rt_b": "lf_b", "x": ""}.get
        side = lambda node: {"l": self.mr.LEFT, "r": self.mr.RIGHT}.get(node[0], self.mr.CENTER)
        pairs = lambda selected, mode: self.mr.pairs(selected, opposite, side, mode)
        self.assertEqual(pairs(["lf_a", "mid", "x"], self.mr.POSE), ([("lf_a", "rt_a"), ("mid", "mid")], ["x"]))
        self.assertEqual(pairs(["lf_a", "rt_a"], self.mr.POSE)[0], [("lf_a", "rt_a"), ("rt_a", "lf_a")])
        self.assertEqual(pairs(["rt_a", "lf_b", "mid"], self.mr.TO_RIGHT)[0], [("lf_a", "rt_a"), ("lf_b", "rt_b")])
        self.assertEqual(pairs(["rt_a", "lf_a", "lf_b"], self.mr.TO_LEFT)[0], [("rt_a", "lf_a"), ("rt_b", "lf_b")])

    def test_mirrored_row(self):
        row = [10.0, 2.0, "fixed", "fixed", 30.0, 25.0, 1.0, 1.0, True, True, False, False]
        self.assertEqual(self.mr.mirrored_row(row, -1)[:6], [10.0, -2.0, "fixed", "fixed", -30.0, -25.0])
        self.assertEqual(self.mr.mirrored_row(row, 1), row)


class AlignTest(unittest.TestCase):
    """On which frames Align keys (MEASURED on the reference, 2026-10-22)."""

    def test_frames(self):
        from msl_tools.msl.tools.maya.animation import align
        own, target = [5, 15, 25], [1, 10, 20, 1, 12]
        self.assertEqual(align.frames(own, target), [1, 5, 10, 12, 15, 20, 25])        # all keys
        self.assertEqual(align.frames(own, target, (3, 20)), [5, 10, 12, 15, 20])      # a span 3-20
        self.assertEqual(align.frames([], [], (1, 10)), [])
        self.assertEqual(align.describe(2, 5), "Aligned 2 objects to the last selected on 5 frames")


class XformTest(unittest.TestCase):
    """Which copied frame a paste takes and where it keys (MEASURED on the reference, 2026-10-22)."""

    def setUp(self):
        from msl_tools.msl.tools.maya.animation import xform
        self.xf = xform

    def test_plan(self):
        xf, keys = self.xf, [1, 10, 20, 1, 15]
        self.assertIsNone(xf.plan(xf.NOW, keys, 10))                              # values only
        self.assertEqual(xf.plan(xf.NOW, keys, 10, (5, 20)), [10, 15, 20])        # a span's key frames
        self.assertEqual(xf.plan(xf.NOW, keys, 10, (2, 8)), [2, 3, 4, 5, 6, 7, 8])  # a span with none: baked
        self.assertEqual(xf.plan(xf.NEXT, keys, 10), [11.0])
        self.assertEqual(xf.plan(xf.ALL, keys, 10), [1, 10, 15, 20])
        self.assertEqual(len(xf.plan(xf.BAKE, keys, 10, None, (1, 120))), 120)

    def test_copied_frame(self):
        frames = {"1": "a", "5": "b", "9": "c"}
        self.assertEqual(self.xf.at(frames, 5), "b")
        self.assertEqual(self.xf.at(frames, 30), "c")
        self.assertEqual(self.xf.at({"1": "a"}, 40), "a")
        self.assertIsNone(self.xf.at({}, 1))


class SpaceTest(unittest.TestCase):
    """The space switcher's names and the rotate orders' rating (MEASURED on the reference, 2026-10-23)."""

    def setUp(self):
        from msl_tools.msl.tools.maya.animation import space
        self.sp = space

    def test_nice_names(self):
        self.assertEqual(self.sp.nice("fkIk"), "Fk Ik")
        self.assertEqual(self.sp.nice("space"), "Space")
        self.assertEqual(self.sp.nice("rotateOrder"), "Rotate Order")
        self.assertEqual(self.sp.nice("follow_space"), "Follow Space")

    def test_orders_round_trip(self):
        import random
        random.seed(5)
        for _ in range(100):
            rotation = [random.uniform(-170, 170) for _ in range(3)]
            now, other = random.choice(self.sp.ORDERS), random.choice(self.sp.ORDERS)
            converted = self.sp.euler(self.sp.matrix(rotation, now), other)
            a, b = self.sp.matrix(rotation, now), self.sp.matrix(converted, other)
            self.assertTrue(all(abs(a[i][j] - b[i][j]) < 1e-9 for i in range(3) for j in range(3)))

    def test_rating(self):
        rate = lambda rotation: self.sp.rate_orders([rotation], [rotation], "xyz")
        for ry, label in ((30, "OK"), (40, "OK"), (45, ""), (70, "")):
            labels = rate((0, ry, 0))
            self.assertEqual((labels["xyz"], labels["zyx"]), (label, label), ry)
            self.assertEqual({labels[o] for o in ("yzx", "zxy", "xzy", "yxz")}, {"Best"})
        # ours on a mixed turn (the reference differs here): the least largest middle angle is Best
        labels = rate((20, 40, 10))
        self.assertEqual(labels["yzx"], "Best")
        self.assertEqual((labels["xyz"], labels["zyx"]), ("OK", "OK"))


class XformSliderTest(unittest.TestCase):
    """The XFORM slider's modes (MEASURED on the reference, 2026-10-23)."""

    def test_modifiers_pick_the_modes(self):
        for held, key in (("Alt", "x_mirror"), ("Ctrl", "x_mirror_frame"), ("Shift", "x_align"),
                          ("Alt+Shift", "x_relationship"), ("Ctrl+Shift", "x_world")):
            self.assertEqual(cv.mode_for_modifiers(cv.XFORM, held).key, key)
        self.assertEqual(cv.BY_KEY["x_align"].marks, cv.BLEND_MARKS)

    def test_world_blends_are_half_as_strong_to_the_left(self):
        import ast
        from pathlib import Path
        tree = ast.parse((Path(cv.__file__).parent / "xform_slider.py").read_text(encoding="utf-8"))
        source = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "strength")
        namespace = {"WORLD_MODES": ("x_align", "x_relationship", "x_world")}
        exec(compile(ast.Module([source], []), "strength", "exec"), namespace)
        strength = namespace["strength"]
        self.assertEqual(strength("x_align", -1.0), -0.5)
        self.assertEqual(strength("x_world", 0.5), 0.5)
        self.assertEqual(strength("x_mirror", -1.0), -1.0)
