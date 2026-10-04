"""core/installer/update_helper.py: a failure at ANY step of applying an update
leaves a working install — never a half-deleted backup over the code in place."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msl_tools.msl.core.installer import update_helper as helper

ROOT_FILES = ["requirements.txt", "README.md"]


def _write_version(folder: Path, version: str) -> None:
    """A minimal msl/ package of `version` + the root files, in `folder`."""
    main = folder / "msl"
    (main / "core").mkdir(parents=True, exist_ok=True)
    (main / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (main / "core" / "code.py").write_text(f"# {version}\n", encoding="utf-8")
    (folder / "README.md").write_text(f"readme {version}", encoding="utf-8")
    (folder / "requirements.txt").write_text("PySide6-Essentials>=6.8,<6.9\n", encoding="utf-8")


def _version_in(folder: Path) -> str:
    return (folder / "msl" / "__init__.py").read_text(encoding="utf-8").split('"')[1]


class _Install(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # resolve(): the helper resolves --root, and %TEMP% may hold an 8.3 short name (S_MIRO~1)
        self.root = Path(temp.name).resolve() / "msl_tools"
        _write_version(self.root, "0.1.7")
        self.work = self.root / ".update"
        self.staged, self.backup = self.work / "staged", self.work / "backup"
        _write_version(self.staged, "0.1.8")
        for name, value in (("MOVE_RETRY_SECONDS", 0.05), ("HEALTH_SECONDS", 0.1)):
            patch = mock.patch.object(helper, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def run_helper(self) -> int:
        return helper.main(["--root", str(self.root), "--version", "0.1.8", "--previous-version", "0.1.7",
                            "--root-files", *ROOT_FILES, "--no-start"])

    def result(self) -> dict:
        return json.loads((self.work / helper.RESULT_NAME).read_text(encoding="utf-8"))

    def failing_move(self, when):
        """A folder rename that Windows refuses (a file in it held by an antivirus scan)
        whenever when(source, destination) is true. Copying still works."""
        real = helper.os.replace

        def replace(source, destination):
            if when(Path(source), Path(destination)):
                raise PermissionError(13, "Access is denied", str(source))
            return real(source, destination)
        return mock.patch.object(helper.os, "replace", replace)

    def assert_clean_root(self):
        names = {path.name for path in self.root.iterdir()}
        self.assertNotIn(helper.INCOMING_NAME, names)
        self.assertNotIn(helper.RESTORING_NAME, names)


class Update(_Install):
    def test_update_puts_the_new_version_in_and_keeps_the_old_one(self):
        self.assertEqual(self.run_helper(), 0)
        self.assertEqual(_version_in(self.root), "0.1.8")
        self.assertEqual(_version_in(self.backup), "0.1.7")
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), "readme 0.1.8")
        self.assertEqual((self.backup / "README.md").read_text(encoding="utf-8"), "readme 0.1.7")
        self.assertEqual(self.result()["status"], "updated")
        self.assertFalse(self.staged.exists())
        self.assert_clean_root()

    def test_old_backup_is_replaced(self):
        _write_version(self.backup, "0.1.5")
        self.assertEqual(self.run_helper(), 0)
        self.assertEqual(_version_in(self.backup), "0.1.7")
        self.assertEqual(list(self.work.glob(helper.TRASH_PREFIX + "*")), [])

    def test_leftovers_of_an_interrupted_run_are_cleared(self):
        _write_version(self.root / helper.INCOMING_NAME, "0.0.1")
        (self.work / (helper.TRASH_PREFIX + "old")).mkdir()
        self.assertEqual(self.run_helper(), 0)
        self.assertEqual(_version_in(self.root), "0.1.8")
        self.assert_clean_root()
        self.assertEqual(list(self.work.glob(helper.TRASH_PREFIX + "*")), [])


class FailureLeavesAWorkingInstall(_Install):
    def test_old_backup_that_cant_be_removed(self):
        # Before: the old backup was half-deleted in place, then "restored" over the good code.
        _write_version(self.backup, "0.1.5")
        with self.failing_move(lambda source, _destination: source == self.backup):
            self.assertEqual(self.run_helper(), 1)
        self.assertEqual(_version_in(self.root), "0.1.7")
        self.assertEqual(self.result()["status"], "rolled_back")
        self.assert_clean_root()

    def test_current_code_that_cant_be_moved(self):
        with self.failing_move(lambda source, _destination: source == self.root / "msl"):
            self.assertEqual(self.run_helper(), 1)
        self.assertEqual(_version_in(self.root), "0.1.7")
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), "readme 0.1.7")
        self.assertEqual(self.result()["status"], "rolled_back")
        self.assert_clean_root()

    def test_new_code_that_cant_be_moved_in(self):
        with self.failing_move(lambda _source, destination: destination == self.root / "msl"):
            self.assertEqual(self.run_helper(), 1)
        self.assertEqual(_version_in(self.root), "0.1.7")
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), "readme 0.1.7")
        self.assertEqual(self.result()["status"], "rolled_back")
        self.assert_clean_root()

    def test_staged_code_that_cant_be_moved_is_copied(self):
        with self.failing_move(lambda source, _destination: source == self.staged / "msl"):
            self.assertEqual(self.run_helper(), 0)
        self.assertEqual(_version_in(self.root), "0.1.8")
        self.assert_clean_root()

    def test_rollback_after_the_new_version_fails_to_start(self):
        swap = helper.Swap()
        log = lambda _message: None
        helper.swap_in(self.root, self.staged, self.backup, ROOT_FILES, log, swap)
        self.assertEqual(_version_in(self.root), "0.1.8")
        self.assertTrue(helper.restore(self.root, self.backup, ROOT_FILES, log, swap))
        self.assertEqual(_version_in(self.root), "0.1.7")
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), "readme 0.1.7")
        self.assert_clean_root()

    def test_restore_does_nothing_when_nothing_was_backed_up(self):
        _write_version(self.backup, "0.1.5")  # some older backup: must not be put over the code
        self.assertTrue(helper.restore(self.root, self.backup, ROOT_FILES, lambda _m: None, helper.Swap()))
        self.assertEqual(_version_in(self.root), "0.1.7")


if __name__ == "__main__":
    unittest.main()
