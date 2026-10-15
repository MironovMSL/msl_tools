"""MSL Scripts without Maya: the list every hotkey command and the menu's Scripts come from."""
import ast
import unittest
from pathlib import Path

from msl_tools.msl.tools.maya import scripts

PACKAGE_ROOT = Path(__file__).resolve().parents[2]   # the folder named msl_tools


def _defined(call: str) -> bool:
    """Whether the dotted path names a function the module's source defines (no import: Maya)."""
    module, function = call.rsplit(".", 1)
    parts = module.split(".")[1:]                       # without the leading msl_tools
    path = PACKAGE_ROOT.joinpath(*parts)
    source = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    return any(isinstance(node, ast.FunctionDef) and node.name == function for node in tree.body)


class Registry(unittest.TestCase):
    def test_names_are_unique(self):
        commands = [script.command for script in scripts.SCRIPTS]
        self.assertEqual(len(commands), len(set(commands)))
        self.assertTrue(all(command.startswith("MSL") for command in commands))

    def test_every_group_is_known(self):
        self.assertTrue({script.group for script in scripts.SCRIPTS} <= set(scripts.GROUPS))

    def test_every_function_exists(self):
        for script in scripts.SCRIPTS:
            self.assertTrue(_defined(script.call), script.call)

    def test_the_python_a_command_runs(self):
        script = scripts.Script("MSLx", "x", "x", "msl_tools.msl.tools.maya.scripts.rig.joints", "Rig")
        self.assertEqual(script.python(), "from msl_tools.msl.tools.maya.scripts.rig import joints; joints()")

    def test_no_command_is_in_both_categories(self):
        source = (PACKAGE_ROOT / "msl" / "tools" / "maya" / "hotkeys.py").read_text(encoding="utf-8")
        for script in scripts.SCRIPTS:
            self.assertNotIn(f'"{script.command}":', source, script.command)


if __name__ == "__main__":
    unittest.main()
