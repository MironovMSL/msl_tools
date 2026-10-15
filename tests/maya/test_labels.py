"""Labels without Maya: the layout as data — namespaces, mirroring, checks, JSON both ways."""
import json
import tempfile
import unittest
from pathlib import Path

from msl_tools.msl.tools.maya.labels import layout as lay
from msl_tools.msl.tools.maya.rename import rules


def sample_layout():
    arm = lay.Column(name="lf_arm", header="ARM L", corner=lay.TOP_LEFT, lines=[
        lay.Line(attribute="lf_arm_ctrl.ikFk", label="IK/FK",
                 color_keys=[(0.0, (0.2, 0.55, 1.0)), (1.0, (0.3, 0.9, 0.35))]),
        lay.Line(attribute="lf_arm_ctrl.stretch", blend=lay.STEPS, opacity_keys=[(0.0, 0.2), (1.0, 1.0)]),
    ])
    head = lay.Column(name="head", mode=lay.SPACE, anchor="head_ctrl", distance_scale=10.0,
                      lines=[lay.Line(attribute="head_ctrl.rotateY", decimals=1)])
    return lay.Layout(name="hero labels", namespace="hero", columns=[arm, head])


class Namespaces(unittest.TestCase):
    def test_put_in(self):
        self.assertEqual(lay.with_namespace("arm_ctrl.ikFk", "hero"), "hero:arm_ctrl.ikFk")
        self.assertEqual(lay.with_namespace("|grp|arm_ctrl.tx", "hero:"), "|hero:grp|hero:arm_ctrl.tx")
        self.assertEqual(lay.with_namespace("arm_ctrl", "a:b"), "a:b:arm_ctrl")
        self.assertEqual(lay.with_namespace("arm_ctrl.ikFk", ""), "arm_ctrl.ikFk")

    def test_take_out(self):
        self.assertEqual(lay.without_namespace("hero:arm_ctrl.ikFk", "hero"), "arm_ctrl.ikFk")
        self.assertEqual(lay.without_namespace("|hero:grp|hero:arm.tx", "hero"), "|grp|arm.tx")
        self.assertEqual(lay.without_namespace("villain:arm.tx", "hero"), "villain:arm.tx")  # not ours: kept
        self.assertEqual(lay.without_namespace("a:b:arm.tx"), "arm.tx")
        self.assertEqual(lay.without_namespace("arm.translate.translateX", ""), "arm.translate.translateX")

    def test_there_and_back(self):
        for path in ("arm_ctrl.ikFk", "|grp|arm_ctrl.rx", "arm_ctrl"):
            self.assertEqual(lay.without_namespace(lay.with_namespace(path, "x:y"), "x:y"), path)


class Mirroring(unittest.TestCase):
    def test_a_column_goes_to_the_other_side(self):
        column = sample_layout().columns[0]
        other = lay.mirror_column(column, rules.mirror)
        self.assertEqual(other.name, "rt_arm")
        self.assertEqual(other.corner, lay.TOP_RIGHT)
        self.assertEqual([line.attribute for line in other.lines], ["rt_arm_ctrl.ikFk", "rt_arm_ctrl.stretch"])
        self.assertEqual(other.lines[0].color_keys, column.lines[0].color_keys)
        self.assertEqual(column.lines[0].attribute, "lf_arm_ctrl.ikFk")  # the original untouched

    def test_corner_may_stay(self):
        other = lay.mirror_column(sample_layout().columns[0], rules.mirror, flip_corner=False)
        self.assertEqual(other.corner, lay.TOP_LEFT)

    def test_a_label_with_a_side_is_mirrored(self):
        line = lay.mirror_line(lay.Line(attribute="arm_L.tx", label="arm_L"), rules.mirror)
        self.assertEqual((line.attribute, line.label), ("arm_R.tx", "arm_R"))


class Checks(unittest.TestCase):
    def test_a_good_layout_has_none(self):
        self.assertEqual(lay.problems(sample_layout()), [])

    def test_what_is_wrong(self):
        layout = lay.Layout(columns=[lay.Column(name="a", mode=lay.SPACE, lines=[lay.Line()]),
                                     lay.Column(name="a")])
        found = "\n".join(lay.problems(layout))
        self.assertIn("Two columns", found)
        self.assertIn("at no object", found)
        self.assertIn("shows nothing", found)
        self.assertIn("1 line(s) show no attribute", found)


class Data(unittest.TestCase):
    def test_there_and_back(self):
        layout = sample_layout()
        data = json.loads(json.dumps(lay.to_dict(layout)))
        self.assertTrue(lay.is_layout(data))
        back = lay.from_dict(data)
        self.assertEqual(back, layout)

    def test_keys_come_back_sorted(self):
        line = lay.line_from_dict({"color_keys": [[5, [1, 0, 0]], [-1, [0, 0, 1]]], "opacity_keys": [[2, 9], [1, 0]]})
        self.assertEqual([key[0] for key in line.color_keys], [-1.0, 5.0])
        self.assertEqual(line.opacity_keys, [(1.0, 0.0), (2.0, 1.0)])  # opacity held to 0..1

    def test_forgiving(self):
        data = {"name": 5, "columns": [{"mode": "sideways", "size": 500, "corner": None, "x": "far",
                                        "header_color": [2, -1], "lines": [{"opacity": 3, "show": "yes",
                                                                            "color_keys": [[0, [1, 0]], "x"],
                                                                            "blend": "jump", "new": 1}],
                                        "unknown": True}, "nonsense"]}
        layout = lay.from_dict(data)
        column = layout.columns[0]
        self.assertEqual(layout.name, "labels")
        self.assertEqual((column.mode, column.size, column.corner, column.x), (lay.HUD, 96, lay.TOP_LEFT, 40))
        self.assertEqual(column.header_color, lay.Column().header_color)
        line = column.lines[0]
        self.assertEqual((line.opacity, line.show, line.color_keys, line.blend), (1.0, True, [], lay.SMOOTH))
        self.assertEqual(layout.columns[1], lay.Column())
        self.assertEqual(lay.from_dict(None), lay.Layout())

    def test_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hero.json"
            lay.save(path, sample_layout())
            self.assertEqual(lay.load(path), sample_layout())
            other = Path(folder) / "other.json"
            other.write_text('{"something": 1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                lay.load(other)
            broken = Path(folder) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                lay.load(broken)
            self.assertTrue(broken.exists())  # not ours: never moved aside


if __name__ == "__main__":
    unittest.main()
