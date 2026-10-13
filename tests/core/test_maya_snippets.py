"""core/link/maya_snippets.py: the ready-made questions are valid Python once filled in, and
their answers are told as text. (What they ask of Maya is checked in a real Maya.)"""
import json
import unittest

from msl_tools.msl.core.link import maya_snippets as snippets


class Code(unittest.TestCase):
    def test_the_filled_templates_compile(self):
        compile(snippets.SCENE_CODE % {"mark": snippets.MARK}, "<scene>", "exec")
        # a name with a quote, a backslash and Cyrillic must stay ONE string literal
        compile(snippets.NODE_CODE % {"mark": snippets.MARK, "node": "|grp|it's\\ \u043a\u0443\u0431"}, "<node>", "exec")

    def test_the_answer_is_found_among_other_output(self):
        output = "something printed\n" + snippets.MARK + json.dumps({"found": []}) + "\n# Result: None"
        self.assertEqual(snippets.parse(output), {"found": []})
        self.assertIsNone(snippets.parse("Traceback ..."))
        self.assertIsNone(snippets.parse(snippets.MARK + "not json"))
        self.assertIsNone(snippets.parse(snippets.MARK + "[1, 2]"))


class Telling(unittest.TestCase):
    def test_a_scene(self):
        text = snippets.tell_scene({
            "file": "C:/shots/a.ma", "modified": True, "time_unit": "film", "linear": "cm", "up": "y", "frame": 12.0,
            "playback": [1.0, 48.0], "range": [1.0, 96.0],
            "counts": {"transforms": 76, "joints": 31, "meshes": 10, "lights": 0},
            "selection": ["hand", "lf_arm_ctrl"], "top": [["hand", "joint", 14], ["crate", "mesh", 0]],
            "namespaces": ["prop"], "references": []})
        self.assertIn("Scene: C:/shots/a.ma  (unsaved changes)", text)
        self.assertIn("playback 1.0-48.0, range 1.0-96.0   Units: cm, y up", text)
        self.assertIn("Holds: 76 transforms, 31 joints, 10 meshes", text)
        self.assertNotIn("lights", text)   # what there is none of is not listed
        self.assertIn("Selected (2): hand, lf_arm_ctrl", text)
        self.assertIn("  hand  [joint]  14 under it", text)
        self.assertIn("  crate  [mesh]", text)
        self.assertIn("Namespaces: prop", text)
        self.assertNotIn("References", text)

    def test_an_empty_scene_and_a_long_list(self):
        text = snippets.tell_scene({"file": "", "counts": {}, "selection": ["n%d" % index for index in range(45)],
                                    "top": []})
        self.assertIn("Scene: untitled", text)
        self.assertIn("Holds: nothing", text)
        self.assertIn("Selected (45): n0, ", text)
        self.assertIn("... and 5 more", text)

    def test_a_node(self):
        text = snippets.tell_node({
            "found": ["|rig|lf_arm_ctrl"], "name": "|rig|lf_arm_ctrl", "type": "transform", "locked": True,
            "referenced": False, "parent": "|rig", "children": ["lf_elbow_ctrl"],
            "shapes": [["lf_arm_ctrlShape", "nurbsCurve"]],
            "values": {"translate": [1.0, 2.0, 0.0], "rotate order": "xyz"}, "closed": ["sx", "sy", "sz"],
            "own": [["stretch", "double", 0.5]], "in": [["lf_arm_ctrl.tx", "anim.output"]],
            "out": [["lf_arm_ctrl.worldMatrix", "mult.matrixIn"]]}, "lf_arm_ctrl")
        self.assertIn("|rig|lf_arm_ctrl  [transform]  (LOCKED node)", text)
        self.assertIn("Parent: |rig", text)
        self.assertIn("Children (1): lf_elbow_ctrl", text)
        self.assertIn("Shapes: lf_arm_ctrlShape [nurbsCurve]", text)
        self.assertIn("  translate     [1.0, 2.0, 0.0]", text)
        self.assertIn("Locked channels: sx, sy, sz", text)
        self.assertIn("  stretch  [double] = 0.5", text)
        self.assertIn("  lf_arm_ctrl.tx <- anim.output", text)
        self.assertIn("  lf_arm_ctrl.worldMatrix -> mult.matrixIn", text)

    def test_no_node_and_several_of_a_name(self):
        self.assertIn("No node is called", snippets.tell_node({"found": []}, "ghost"))
        text = snippets.tell_node({"found": ["|a|box", "|b|box"]}, "box")
        self.assertIn("2 nodes are called", text)
        self.assertIn("  |b|box", text)


if __name__ == "__main__":
    unittest.main()
