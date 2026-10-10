"""Controls without Maya: the shapes as data (built-in ones, sizes, turning, the drawn B-spline,
the user's library) and a control's name."""
import math
import unittest

from msl_tools.msl.tools.maya.controls import shapes
from msl_tools.msl.tools.maya.controls.naming import base_name, control_name
from msl_tools.msl.tools.maya.rename.rules import Sides


def reach(curves, sampled=True):
    points = [point for curve in curves for point in (shapes.polyline(curve, 8) if sampled else curve.points)]
    return max(abs(value) for point in points for value in point)


class BuiltIn(unittest.TestCase):
    def test_every_shape_is_drawn_to_unit_size(self):
        for name, shape in shapes.BUILT_IN.items():
            with self.subTest(name):
                self.assertTrue(shape.curves)
                self.assertAlmostEqual(reach(shape.curves), 1.0, places=2)
                self.assertIn(shape.category, shapes.CATEGORIES)

    def test_a_circle_is_as_wide_as_a_square(self):
        circle, square = shapes.BUILT_IN["circle"], shapes.BUILT_IN["square"]
        self.assertAlmostEqual(reach(circle.curves), reach(square.curves), places=2)

    def test_flat_shapes_face_y_and_turn_to_x_or_z(self):
        circle = shapes.BUILT_IN["circle"].curves
        self.assertTrue(all(abs(point[1]) < 1e-6 for point in circle[0].points))
        facing_x = shapes.oriented(circle, "X")
        self.assertTrue(all(abs(point[0]) < 1e-6 for point in facing_x[0].points))
        facing_z = shapes.oriented(circle, "Z")
        self.assertTrue(all(abs(point[2]) < 1e-6 for point in facing_z[0].points))

    def test_turn_a_quarter(self):
        curve = [shapes.Curve([(1.0, 0.0, 0.0)])]
        x, y, z = shapes.turned(curve, "Z", 90)[0].points[0]
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 1.0)


class Drawing(unittest.TestCase):
    def test_a_closed_cubic_is_a_loop_inside_its_cvs(self):
        ring = shapes.Curve([(math.cos(a), 0.0, math.sin(a)) for a in (i * math.pi / 4 for i in range(8))], 3, True)
        line = shapes.polyline(ring, 8)
        self.assertEqual(line[0], line[-1])
        radii = [math.hypot(x, z) for x, _y, z in line]
        self.assertTrue(all(0.8 < radius <= 1.0 for radius in radii))

    def test_an_open_cubic_starts_and_ends_on_its_end_cvs(self):
        curve = shapes.Curve([(0, 0, 0), (1, 1, 0), (2, -1, 0), (3, 0, 0)], 3, False)
        line = shapes.polyline(curve, 4)
        self.assertEqual(tuple(round(v, 6) for v in line[0]), (0, 0, 0))
        self.assertEqual(tuple(round(v, 6) for v in line[-1]), (3, 0, 0))

    def test_a_closed_polygon_comes_back_to_its_start(self):
        square = shapes.BUILT_IN["square"].curves[0]
        line = shapes.polyline(square)
        self.assertEqual(line[0], line[-1])
        self.assertEqual(len(line), len(square.points) + 1)


class Library(unittest.TestCase):
    def test_add_normalize_find_remove(self):
        store = {}
        library = shapes.ShapeLibrary(store)
        name = library.add("My Star!", [shapes.Curve([(0, 0, 0), (4, 0, 0), (0, 0, 2)], 1, True)])
        self.assertEqual(name, "my_star")
        shape = library.get(name)
        self.assertTrue(shape.user)
        self.assertEqual(shape.category, "Mine")
        self.assertAlmostEqual(reach(shape.curves), 1.0, places=3)
        self.assertEqual(library.add("circle", shape.curves), "circle_2")   # never over a built-in one
        self.assertTrue(library.remove(name))
        self.assertIsNone(library.get(name))
        self.assertFalse(library.remove("circle"))                          # built-in ones stay

    def test_shapes_go_to_a_file_and_back(self):
        import tempfile
        from pathlib import Path
        mine = shapes.ShapeLibrary({})
        mine.add("hook", [shapes.Curve([(0, 0, 0), (2, 0, 0), (2, 0, 1)], 1, False)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shapes.json"
            self.assertEqual(mine.export_file(path), 1)
            other = shapes.ShapeLibrary({})
            self.assertEqual(other.import_file(path), ["hook"])
            self.assertEqual(other.get("hook").curves[0].points, mine.get("hook").curves[0].points)
            self.assertEqual(other.import_file(path), [])                   # the same shape isn't added twice
            other._store["hook"]["curves"][0]["points"][0] = [0.5, 0, 0]
            self.assertEqual(other.import_file(path), ["hook_2"])           # a taken name: numbered, never replaced
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                other.import_file(path)
            self.assertTrue(path.exists())                                  # the user's file is left alone

    def test_a_broken_entry_is_skipped(self):
        library = shapes.ShapeLibrary({"bad": "not a shape"})
        self.assertNotIn("bad", library.all())


class Colors(unittest.TestCase):
    def test_hex_both_ways(self):
        from msl_tools.msl.tools.maya.controls import colors
        self.assertEqual(colors.to_hex((1.0, 0.5, 0.0)), "#ff8000")
        self.assertTrue(colors.same(colors.from_hex("#ff8000"), (1.0, 0.502, 0.0)))
        with self.assertRaises(ValueError):
            colors.from_hex("#fff")

    def test_outliner_gamma_round_trip(self):
        from msl_tools.msl.tools.maya.controls import colors
        lifted = colors.to_outliner((0.25, 0.5, 1.0))
        self.assertGreater(lifted[0], 0.25)            # the Outliner gets lighter numbers
        self.assertEqual(lifted[2], 1.0)
        self.assertTrue(colors.same(colors.from_outliner(lifted), (0.25, 0.5, 1.0), 2e-3))

    def test_the_palette_has_32_colors(self):
        from msl_tools.msl.tools.maya.controls import colors
        self.assertEqual(len(colors.INDEX_COLORS), 32)
        self.assertEqual(set(colors.SIDE_COLORS), {"left", "right", "center"})


class Naming(unittest.TestCase):
    def test_base_name(self):
        self.assertEqual(base_name("lf_arm_jnt"), "arm")
        self.assertEqual(base_name("ns:spine_01_JNT"), "spine_01")
        self.assertEqual(base_name("|grp|hand"), "hand")

    def test_side_from_where_it_stands(self):
        sides = Sides()
        self.assertEqual(control_name("{side}_{name}_ctrl", "rt_arm_jnt", (3, 0, 0), sides), "lf_arm_ctrl")
        self.assertEqual(control_name("{side}_{name}_ctrl", "spine_jnt", (0, 0, 0), sides), "mid_spine_ctrl")
        self.assertEqual(control_name("{side}_{name}_ctrl", "", None, sides), "control_ctrl")
        self.assertEqual(control_name("{name}_{#}_ctrl", "arm_jnt", None, sides, 3), "arm_03_ctrl")


if __name__ == "__main__":
    unittest.main()
