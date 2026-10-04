"""Maya Gate's Qt-free stores: the userSetup script and its wrapper, the launch records."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msl_tools.msl.tools.desktop.maya_gate.boost import LaunchLog
from msl_tools.msl.tools.desktop.maya_gate.user_setup import ScriptUnavailable, UserSetupStore, decode_script


def _python27() -> list | None:
    """A Python 2.7 to run the wrapper with (Maya 2020's), if this machine has one."""
    try:
        done = subprocess.run(["py", "-2.7", "-c", "print(1)"], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return ["py", "-2.7"] if done.returncode == 0 else None


class _Store(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        # A user name Python 2.7 can't take as plain ASCII, and a quote
        self.store = UserSetupStore(self.temp / "Сергей O'Brien" / "maya_gate")

    def wrapper(self, environment="Dev") -> Path:
        variables = self.store.launch_environment(environment, {})
        return Path(variables["PYTHONPATH"].split(os.pathsep)[0]) / "userSetup.py"


class ScriptText(_Store):
    def test_utf8_bom_and_ansi(self):
        self.assertEqual(decode_script("x = 'Привет'".encode("utf-8")), "x = 'Привет'")
        self.assertEqual(decode_script(b"\xef\xbb\xbfx = 1"), "x = 1")
        # Before: one "é" from an editor saving in cp1252 stopped every launch of the environment.
        self.assertIn("caf", decode_script("x = 'café'".encode("cp1252")))

    def test_never_saved_reads_as_the_default(self):
        self.assertEqual(self.store.read("Dev"), UserSetupStore.DEFAULT_SCRIPT)

    def test_round_trip(self):
        self.store.write("Dev", "print('Привет')\n")
        self.assertEqual(self.store.read("Dev"), "print('Привет')\n")

    def test_locked_script_raises_and_launch_still_works(self):
        self.store.write("Dev", "print(1)\n")
        path = self.store.script_path("Dev")
        real = Path.read_bytes

        def read_bytes(self_path):
            if self_path == path:
                raise PermissionError(13, "in use")
            return real(self_path)
        with mock.patch.object(Path, "read_bytes", read_bytes):
            with self.assertRaises(ScriptUnavailable):
                self.store.read("Dev")
            wrapper = self.wrapper()  # Maya reads the script itself: the wrapper still goes along
        self.assertTrue(wrapper.is_file())
        self.assertEqual(path.read_text(encoding="utf-8"), "print(1)\n")  # untouched


class Wrapper(_Store):
    def test_wrapper_is_ascii_and_python3_runs_it(self):
        self.store.write("Dev", "RAN = 'Привет'\n")
        wrapper = self.wrapper()
        source = wrapper.read_bytes()
        self.assertTrue(source.isascii())
        scope = {"__name__": "__main__"}
        exec(compile(source.decode("ascii"), str(wrapper), "exec"), scope)
        self.assertEqual(scope.get("RAN"), "Привет")

    def test_wrapper_unchanged_is_not_rewritten(self):
        self.store.write("Dev", "x = 1\n")
        wrapper = self.wrapper()
        stamp = wrapper.stat().st_mtime_ns
        self.wrapper()
        self.assertEqual(wrapper.stat().st_mtime_ns, stamp)  # Maya's trust hash stays valid

    @unittest.skipIf(_python27() is None, "no Python 2.7 on this machine")
    def test_python27_runs_it_with_a_cyrillic_path(self):
        # Before: "SyntaxError: Non-ASCII character" in Maya 2020 for such a user name.
        self.store.write("Dev", "print('ok')\n")
        copy = self.temp / "wrapper.py"  # run from an ASCII path: 2.7 can't take the other in its argv
        shutil.copy(self.wrapper(), copy)
        done = subprocess.run(_python27() + [str(copy)], capture_output=True, timeout=30,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        output = (done.stdout + done.stderr).decode("utf-8", "replace")
        self.assertEqual(done.returncode, 0, output)
        self.assertIn("ok", output)
        self.assertNotIn("failed", output)


class LaunchRecords(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.log = LaunchLog(Path(temp.name) / "launches")

    def test_two_launches_in_one_second_keep_two_records(self):
        with mock.patch("time.time", return_value=1_790_000_000.25):
            first = self.log.start("2025", "Dev", False, 0, {})
        with mock.patch("time.time", return_value=1_790_000_000.75):
            second = self.log.start("2025", "Dev", True, 3, {})
        self.assertNotEqual(first[LaunchLog.FILE_VARIABLE], second[LaunchLog.FILE_VARIABLE])
        self.assertEqual(len(self.log.entries()), 2)

    def test_last_measured_takes_the_year_as_text_or_number(self):
        variables = self.log.start("2025", "Dev", True, 1, {})
        path = Path(variables[LaunchLog.FILE_VARIABLE])
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(year=2025, ready_seconds=28.0)  # a record whose year was written as a number
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNotNone(self.log.last_measured("Dev", year="2025"))
        self.assertEqual(len(self.log.measured("Dev", "2025")), 1)


if __name__ == "__main__":
    unittest.main()
