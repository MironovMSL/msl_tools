"""core/link/assistant_setup.py: what an assistant is told to start our MCP server with."""
import json
import os
import shutil
import tempfile
import unittest

from msl_tools.msl.core.link import assistant_setup as setup

ENTRY = {"command": "C:/MSL/runtime/.venv/Scripts/python.exe", "args": ["C:/MSL/msl_tools/msl/run_maya_mcp.py"]}


class Texts(unittest.TestCase):
    def test_the_script_is_this_installs_own(self):
        self.assertTrue(os.path.isfile(setup.server_script()))
        self.assertTrue(setup.server_script().endswith(os.path.join("msl", "run_maya_mcp.py")))

    def test_a_console_python_is_preferred_to_pythonw(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        windowless, console = os.path.join(folder, "pythonw.exe"), os.path.join(folder, "python.exe")
        open(windowless, "w").close()
        self.assertEqual(setup.console_python(windowless), windowless)   # no python.exe beside it
        open(console, "w").close()
        self.assertEqual(setup.console_python(windowless), console)
        self.assertEqual(setup.console_python(console), console)

    def test_the_claude_line_and_the_json(self):
        self.assertEqual(setup.claude_command(ENTRY),
                         'claude mcp add --scope user msl-maya -- "C:/MSL/runtime/.venv/Scripts/python.exe" '
                         '"C:/MSL/msl_tools/msl/run_maya_mcp.py"')
        self.assertEqual(json.loads(setup.config_text(ENTRY)), {"mcpServers": {"msl-maya": ENTRY}})


class ProjectFile(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, ".mcp.json")

    def read(self) -> dict:
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_new_file(self):
        self.assertEqual(str(setup.write_project_config(self.folder, ENTRY)), self.path)
        self.assertEqual(self.read(), {"mcpServers": {"msl-maya": ENTRY}})

    def test_the_other_servers_and_keys_stay(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"mcpServers": {"other": {"command": "x"}, "msl-maya": {"command": "old"}}, "note": 1}, handle)
        setup.write_project_config(self.folder, ENTRY)
        self.assertEqual(self.read(), {"mcpServers": {"other": {"command": "x"}, "msl-maya": ENTRY}, "note": 1})

    def test_a_broken_file_is_kept_aside_not_lost(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        setup.write_project_config(self.folder, ENTRY)
        self.assertEqual(self.read(), {"mcpServers": {"msl-maya": ENTRY}})
        self.assertEqual(len([name for name in os.listdir(self.folder) if ".broken-" in name]), 1)


if __name__ == "__main__":
    unittest.main()
