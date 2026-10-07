"""Rename without Maya: the template and its tokens, one-name operations, sides and kinds, checks,
the plan of "before -> after", the name library."""
import unittest

from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.tools.maya.rename.library import DEFAULT_FAVORITES, NameLibrary
from msl_tools.msl.tools.maya.rename.rules import Node, Numbering, Sides

SUFFIXES = rules.DEFAULT_TYPE_SUFFIXES


def node(name, path=None, **kwargs):
    return Node(path=path or f"|{name}", name=name, **kwargs)


class Template(unittest.TestCase):
    def test_number_letter_and_name(self):
        nodes = [node("a"), node("b"), node("c")]
        names = rules.from_template(nodes, "arm_{#}", Numbering(start=1, padding=2), Sides(), SUFFIXES)
        self.assertEqual(names, ["arm_01", "arm_02", "arm_03"])
        names = rules.from_template(nodes, "{name}_{A}", Numbering(), Sides(), SUFFIXES)
        self.assertEqual(names, ["a_A", "b_B", "c_C"])
        names = rules.from_template(nodes, "x{#}", Numbering(start=10, step=5, padding=3), Sides(), SUFFIXES)
        self.assertEqual(names, ["x010", "x015", "x020"])

    def test_side_and_type(self):
        nodes = [node("a", position=(2, 0, 0), shape_type="mesh"), node("b", position=(-2, 0, 0), type="joint"),
                 node("c", position=(0.0001, 1, 0))]
        names = rules.from_template(nodes, "{side}_arm_{type}", Numbering(), Sides(), SUFFIXES)
        self.assertEqual(names, ["lf_arm_geo", "rt_arm_jnt", "mid_arm_grp"])

    def test_an_empty_token_leaves_no_double_underscore(self):
        names = rules.from_template([node("a", type="unknownThing")], "arm_{type}", Numbering(), Sides(), SUFFIXES)
        self.assertEqual(names, ["arm"])

    def test_order_by_position(self):
        nodes = [node("a", position=(5, 0, 0)), node("b", position=(1, 0, 0)), node("c", position=(3, 0, 0))]
        names = rules.from_template(nodes, "f{#}", Numbering(padding=1, order=rules.ORDER_X), Sides(), SUFFIXES)
        self.assertEqual(names, ["f3", "f1", "f2"])

    def test_letters_go_past_z(self):
        self.assertEqual([rules.letters(i) for i in (0, 25, 26, 27, 701, 702)], ["A", "Z", "AA", "AB", "ZZ", "AAA"])

    def test_unknown_tokens(self):
        self.assertEqual(rules.unknown_tokens("a_{#}_{nope}"), ["{nope}"])


class Operations(unittest.TestCase):
    def test_case(self):
        self.assertEqual(rules.capitalize("armIK"), "ArmIK")
        self.assertEqual(rules.capitalize("ARM"), "Arm")
        self.assertEqual(rules.camel_to_snake("leftArmIK"), "left_arm_ik")
        self.assertEqual(rules.snake_to_camel("left_arm_ik"), "leftArmIk")

    def test_removing_parts(self):
        self.assertEqual(rules.remove_prefix("lf_arm_jnt"), "arm_jnt")
        self.assertEqual(rules.remove_suffix("arm_jnt"), "arm")
        self.assertEqual(rules.remove_suffix("arm"), "arm")
        self.assertEqual(rules.remove_end_number("arm_01"), "arm")
        self.assertEqual(rules.remove_end_number("12"), "12")      # nothing would be left
        self.assertEqual(rules.remove_digits("arm_01_jnt2"), "arm_jnt")
        self.assertEqual(rules.remove_first("arm"), "rm")
        self.assertEqual(rules.remove_last("a"), "a")

    def test_adding(self):
        self.assertEqual(rules.add_prefix("arm", "lf_"), "lf_arm")
        self.assertEqual(rules.add_prefix("lf_arm", "lf_"), "lf_arm")
        self.assertEqual(rules.add_word("arm", "jnt"), "arm_jnt")
        self.assertEqual(rules.add_word("arm_jnt", "jnt"), "arm_jnt")
        self.assertEqual(rules.add_word("arm", "End", separator=False), "armEnd")

    def test_side_prefix_replaces_an_old_one(self):
        self.assertEqual(rules.side_prefix("rt_arm", (3, 0, 0), Sides()), "lf_arm")
        self.assertEqual(rules.side_prefix("L_arm", (0, 0, 0), Sides()), "mid_arm")
        self.assertEqual(rules.side_prefix("arm", (0, 0, 4), Sides(axis="Z")), "lf_arm")

    def test_type_suffix_replaces_another_kinds(self):
        self.assertEqual(rules.type_suffix("arm_grp", "mesh", SUFFIXES), "arm_geo")
        self.assertEqual(rules.type_suffix("arm_geo", "mesh", SUFFIXES), "arm_geo")
        self.assertEqual(rules.type_suffix("arm_upper", "joint", SUFFIXES), "arm_upper_jnt")

    def test_replace(self):
        self.assertEqual(rules.replace("l_arm_l", "l", "r"), "r_arm_r")             # every one
        self.assertEqual(rules.replace("arm_old", "_old", ""), "arm")              # out
        self.assertEqual(rules.replace("Arm_arm", "arm", "leg", case=False), "leg_leg")
        self.assertEqual(rules.replace("arm_12", r"(\d+)", r"0\1", regex=True), "arm_012")
        self.assertEqual(rules.replace("a.b", ".", "_"), "a_b")                    # not a pattern
        with self.assertRaises(ValueError):
            rules.replace("a", "(", "", regex=True)


class Checks(unittest.TestCase):
    def test_problems(self):
        self.assertEqual(rules.problem("arm_01"), "")
        self.assertIn("digit", rules.problem("1arm"))
        self.assertIn("Cyrillic", rules.problem("рука"))
        self.assertIn("space", rules.problem("arm l"))
        self.assertTrue(rules.problem("arm-l"))

    def test_sanitize(self):
        self.assertEqual(rules.sanitize("Рука лев"), "Ruka_lev")
        self.assertEqual(rules.sanitize("1arm"), "_1arm")
        self.assertEqual(rules.sanitize("arm--l"), "arm_l")

    def test_plan_marks_what_needs_a_look(self):
        nodes = [node("a", path="|g|a"), node("b", path="|g|b"), node("c", path="|h|c"),
                 node("d", locked="referenced"), node("e"), node("f", path="|g|f", siblings=("taken",))]
        changes = rules.plan(nodes, ["x", "x", "x", "y", "e", "taken"])
        self.assertEqual([change.state for change in changes], ["", "clash", "", "locked", "same", "clash"])

    def test_a_sibling_that_is_renamed_away_is_no_clash(self):
        nodes = [node("a", path="|g|a", siblings=("b",)), node("b", path="|g|b", siblings=("a",))]
        changes = rules.plan(nodes, ["b", "c"])
        self.assertEqual([change.state for change in changes], ["", ""])


class Library(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self.library = NameLibrary(self.store)

    def test_built_in_until_changed(self):
        self.assertIn("Limbs", self.library.categories())
        self.assertEqual(self.library.favorites(), DEFAULT_FAVORITES)
        self.assertNotIn("categories", self.store)
        self.assertTrue(self.library.add_word("Limbs", "claw"))
        self.assertFalse(self.library.add_word("Limbs", "claw"))
        self.assertIn("claw", self.store["categories"]["Limbs"])
        self.library.move_word("Limbs", "claw", "Base", before="root")
        self.assertEqual(self.library.categories()["Base"][0], "claw")
        self.library.reset()
        self.assertNotIn("claw", self.library.words())

    def test_categories(self):
        self.assertTrue(self.library.add_category("Props"))
        self.assertTrue(self.library.rename_category("Props", "Items"))
        self.assertEqual(list(self.library.categories())[-1], "Items")   # keeps its place
        self.library.add_word("Items", "geo")
        self.assertIn("geo", self.library.duplicates())

    def test_recent_newest_first_and_capped(self):
        for index in range(25):
            self.library.remember(f"n{index}")
        self.library.remember("n3")
        recent = self.library.recent()
        self.assertEqual(recent[0], "n3")
        self.assertEqual(len(recent), 20)
        self.library.forget()
        self.assertEqual(self.library.recent(), [])


if __name__ == "__main__":
    unittest.main()
