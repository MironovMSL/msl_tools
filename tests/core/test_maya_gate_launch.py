"""Maya Gate's launch: the scene path is never shadowed inside _prepare_launch.

A local variable named `scene` there (the Scene tab's settings, 2026-10-14) replaced the scene PATH,
and every launch got `-file <that>` - Maya said "Unrecognized file type". Read from the source (ast),
so no window and no config is needed.
"""
import ast
import os
import unittest

PAGE = os.path.join(os.path.dirname(__file__), "..", "..", "msl", "tools", "desktop", "maya_gate", "page.py")


class PrepareLaunch(unittest.TestCase):
    def test_the_scene_parameter_is_never_assigned(self):
        with open(PAGE, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "_prepare_launch")
        assigned = {target.id for node in ast.walk(function) if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                    if isinstance(target, ast.Name)}
        self.assertNotIn("scene", assigned)


if __name__ == "__main__":
    unittest.main()
