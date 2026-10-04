"""core/fs/safe_json.py and the config / history stores built on it: a broken or
locked file must never be written over."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from msl_tools.msl.core.config.json_config import JsonConfig
from msl_tools.msl.core.fs import safe_json
from msl_tools.msl.core.fs.safe_json import JsonUnavailable, read_json_object, write_json_atomic
from msl_tools.msl.tools.desktop.maya_gate.session_history import SessionHistory, SessionRecord
from msl_tools.msl.tools.desktop.maya_gate.snippets import SnippetStore
from msl_tools.msl.tools.desktop.media.history import ResultHistory, ResultRecord


def _locked(path: Path):
    """Makes reading ``path`` fail the way a file held by an antivirus scan does."""
    real = Path.read_bytes

    def read_bytes(self):
        if self == path:
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real(self)
    return mock.patch.object(Path, "read_bytes", read_bytes)


class _TempFolder(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.folder = Path(self._temp.name)
        retry = mock.patch.object(safe_json, "RETRY_SECONDS", 0.05)
        retry.start()
        self.addCleanup(retry.stop)
        self.addCleanup(self._temp.cleanup)
        quiet = mock.patch.object(safe_json.logger, "warning")  # the expected warnings would only clutter the output
        quiet.start()
        self.addCleanup(quiet.stop)

    def broken_copies(self, name: str) -> list[Path]:
        stem, suffix = name.rsplit(".", 1)
        return sorted(self.folder.glob(f"{stem}.broken-*.{suffix}"))


class ReadJsonObject(_TempFolder):
    def test_missing_file_is_empty(self):
        self.assertEqual(read_json_object(self.folder / "none.json"), {})

    def test_object_is_returned(self):
        path = self.folder / "a.json"
        path.write_text('{"a": {"b": 1}}', encoding="utf-8")
        self.assertEqual(read_json_object(path), {"a": {"b": 1}})

    def test_utf8_bom_is_accepted(self):
        path = self.folder / "a.json"
        path.write_bytes(b"\xef\xbb\xbf" + '{"name": "Мaya"}'.encode("utf-8"))
        self.assertEqual(read_json_object(path), {"name": "Мaya"})

    def test_truncated_file_is_moved_aside(self):
        path = self.folder / "config.json"
        path.write_text('{"maya": {"Dev": {"PYTHONPATH": "C:/x"', encoding="utf-8")
        self.assertEqual(read_json_object(path), {})
        self.assertFalse(path.exists())
        [kept] = self.broken_copies("config.json")
        self.assertIn("PYTHONPATH", kept.read_text(encoding="utf-8"))

    def test_json_that_is_not_an_object_is_moved_aside(self):
        path = self.folder / "config.json"
        path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(read_json_object(path), {})
        self.assertEqual(len(self.broken_copies("config.json")), 1)

    def test_two_broken_files_in_one_second_keep_both(self):
        path = self.folder / "config.json"
        for text in ("{", "[]"):
            path.write_text(text, encoding="utf-8")
            read_json_object(path)
        self.assertEqual(len(self.broken_copies("config.json")), 2)

    def test_locked_file_raises_and_stays(self):
        path = self.folder / "config.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        with _locked(path), self.assertRaises(JsonUnavailable):
            read_json_object(path)
        self.assertEqual(path.read_text(encoding="utf-8"), '{"a": 1}')

    def test_broken_file_that_cannot_be_moved_raises(self):
        path = self.folder / "config.json"
        path.write_text("{", encoding="utf-8")
        with mock.patch.object(safe_json.os, "replace", side_effect=PermissionError(13, "in use")):
            with self.assertRaises(JsonUnavailable):
                read_json_object(path)
        self.assertEqual(path.read_text(encoding="utf-8"), "{")


class WriteJsonAtomic(_TempFolder):
    def test_writes_and_creates_folders(self):
        path = self.folder / "a" / "b" / "config.json"
        write_json_atomic(path, {"x": "ё"})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"x": "ё"})
        self.assertEqual([p.name for p in path.parent.iterdir()], ["config.json"])  # no temporary left

    def test_failed_replace_keeps_the_old_file_and_no_temporary(self):
        path = self.folder / "config.json"
        write_json_atomic(path, {"v": 1})
        with mock.patch.object(safe_json.os, "replace", side_effect=PermissionError(13, "in use")):
            with self.assertRaises(OSError):
                write_json_atomic(path, {"v": 2})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"v": 1})
        self.assertEqual([p.name for p in self.folder.iterdir()], ["config.json"])

    def test_replace_is_retried_while_the_file_is_in_use(self):
        path = self.folder / "config.json"
        real, calls = safe_json.os.replace, []

        def flaky(source, target):
            calls.append(target)
            if len(calls) == 1:
                raise PermissionError(13, "in use")
            real(source, target)
        with mock.patch.object(safe_json.os, "replace", flaky):
            write_json_atomic(path, {"v": 1})
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"v": 1})

    def test_concurrent_writers_never_leave_a_broken_file(self):
        path = self.folder / "config.json"
        errors = []

        def writer(n):
            for i in range(20):
                try:
                    write_json_atomic(path, {"writer": n, "i": i, "pad": "x" * 2000})
                except OSError:  # Windows may refuse a replace while another one runs; the file stays whole
                    pass
                except Exception as error:  # anything else is a failure
                    errors.append(error)
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertIn("writer", json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual([p.name for p in self.folder.iterdir()], ["config.json"])


class JsonConfigKeepsUserData(_TempFolder):
    DEFAULTS = {"maya": {}, "_ui": {"tab": "variables"}}

    def setUp(self):
        super().setUp()
        quiet = mock.patch("msl_tools.msl.core.config.json_config.logger.warning")
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_broken_config_is_kept_aside_and_defaults_used(self):
        path = self.folder / "config.json"
        path.write_text('{"maya": {"Dev": {"MAYA_APP_DIR": "D:/prefs"}}', encoding="utf-8")  # a typo: one } short
        config = JsonConfig(str(path), defaults=self.DEFAULTS)
        self.assertEqual(config.data, self.DEFAULTS)
        [kept] = self.broken_copies("config.json")
        self.assertIn("D:/prefs", kept.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.DEFAULTS)

    def test_locked_config_is_never_written_over(self):
        path = self.folder / "config.json"
        original = '{"maya": {"Dev": {"MAYA_APP_DIR": "D:/prefs"}}}'
        path.write_text(original, encoding="utf-8")
        with _locked(path):
            config = JsonConfig(str(path), defaults=self.DEFAULTS)
        self.assertTrue(config.read_only)
        config["maya"]["Stable"] = {"X": "1"}  # an edit in this session must not reach the file
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        config.reload()  # readable again: the user's data comes back, saving works again
        self.assertFalse(config.read_only)
        self.assertEqual(config["maya"]["Dev"]["MAYA_APP_DIR"], "D:/prefs")
        config["_ui"]["tab"] = "boost"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["_ui"]["tab"], "boost")

    def test_good_config_round_trip(self):
        path = self.folder / "config.json"
        config = JsonConfig(str(path), defaults=self.DEFAULTS)
        config["maya"]["Dev"] = {"PYTHONPATH": "C:/tools"}
        again = JsonConfig(str(path), defaults=self.DEFAULTS)
        self.assertEqual(again["maya"]["Dev"]["PYTHONPATH"], "C:/tools")


class StoresKeepUserData(_TempFolder):
    def test_media_history_locked_is_not_overwritten(self):
        history = ResultHistory(self.folder)
        history.save([ResultRecord(title="a", output="C:/a.mp4")])
        path = self.folder / "history.json"
        before = path.read_text(encoding="utf-8")
        with _locked(path):
            self.assertEqual(history.load(), [])
        history.save([])
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertEqual([r.output for r in history.load()], ["C:/a.mp4"])

    def test_media_history_broken_is_kept_aside(self):
        path = self.folder / "history.json"
        path.write_text('{"results": [', encoding="utf-8")
        self.assertEqual(ResultHistory(self.folder).load(), [])
        self.assertEqual(len(self.broken_copies("history.json")), 1)

    def test_session_history_skips_one_bad_record(self):
        path = self.folder / "sessions" / "history.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"sessions": [{"pid": "abc"}, {"pid": 7, "version": "2025"}, "junk"]}),
                        encoding="utf-8")
        self.assertEqual([r.pid for r in SessionHistory(self.folder).records()], [7])

    def test_session_history_locked_is_not_overwritten(self):
        SessionHistory(self.folder).add(SessionRecord(pid=1, version="2025"))
        path = self.folder / "sessions" / "history.json"
        before = path.read_text(encoding="utf-8")
        locked = SessionHistory(self.folder)
        with _locked(path):
            self.assertEqual(locked.records(), [])
        locked.add(SessionRecord(pid=2, version="2024"))
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_snippets_round_trip_and_locked(self):
        SnippetStore(self.folder).save("hello", "print(1)")
        self.assertEqual(SnippetStore(self.folder).code("hello"), "print(1)")
        path = self.folder / "console" / "snippets.json"
        before = path.read_text(encoding="utf-8")
        locked = SnippetStore(self.folder)
        with _locked(path):
            self.assertEqual(locked.names(), [])
        locked.save("other", "pass")
        self.assertEqual(path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
