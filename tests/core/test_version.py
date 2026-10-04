"""core/version: version strings and the GitHub release list."""
import json
import tempfile
import unittest
from pathlib import Path

from msl_tools.msl.core.version.local_version import LocalVersionReader
from msl_tools.msl.core.version.release_notes import parse_releases, split_sections
from msl_tools.msl.core.version.version import Version


class Parse(unittest.TestCase):
    def test_plain_and_prefixed(self):
        for text, expected in (("0.1.7", "0.1.7"), ("v0.1.7", "0.1.7"), ("MSL Tools v1.2.3", "1.2.3"),
                               ("v10.20.30", "10.20.30"), ("1.2.34", "1.2.34")):
            self.assertEqual(Version.parse(text), expected, text)

    def test_suffix_is_ignored_not_glued_on(self):
        # Before: every digit was kept, and "v0.2.0-rc1" read as 0.2.1.
        for text in ("v0.2.0-rc1", "0.2.0rc1", "0.2.0+build5", "0.2.0.4", "0.2.0-beta.2"):
            self.assertEqual(Version.parse(text), "0.2.0", text)

    def test_as_tuple(self):
        self.assertEqual(Version.parse("v1.2.3", as_tuple=True), (1, 2, 3))

    def test_invalid(self):
        for text in ("1.2", "abc", "", None, "v.1.2"):
            with self.assertRaises(ValueError, msg=text):
                Version.parse(text)

    def test_compare(self):
        self.assertEqual(Version.compare("0.1.10", "0.1.9"), Version.BIGGER)
        self.assertEqual(Version.compare("v0.1.7", "0.1.7"), Version.EQUAL)
        self.assertEqual(Version.compare("0.2.0-rc1", "0.2.1"), Version.SMALLER)


class LocalVersion(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def read(self, source: str):
        (self.folder / "__init__.py").write_text(source, encoding="utf-8")
        return LocalVersionReader.get_version(self.folder)

    def test_the_package_itself(self):
        import msl_tools.msl as package
        self.assertEqual(LocalVersionReader.get_version(Path(package.__file__).parent), package.__version__)

    def test_tuple_and_suffix(self):
        self.assertEqual(self.read('__version_tuple__ = (0, 2, 0)\n__version_suffix__ = "-rc1"\n'
                                   '__version__ = ".".join(str(n) for n in __version_tuple__) + __version_suffix__\n'),
                         "0.2.0-rc1")

    def test_plain_string(self):
        self.assertEqual(self.read('__version__ = "1.2.3"\n'), "1.2.3")

    def test_the_file_is_never_run(self):
        # Before: the downloaded __init__.py was executed inside the hub to learn its version.
        marker = self.folder / "ran.txt"
        source = f'open({str(marker)!r}, "w").write("x")\n__version__ = "1.0.0"\n'
        self.assertEqual(self.read(source), "1.0.0")
        self.assertFalse(marker.exists())

    def test_missing_or_broken(self):
        self.assertIsNone(LocalVersionReader.get_version(self.folder))  # no __init__.py
        self.assertIsNone(self.read("def (:\n"))
        self.assertIsNone(self.read("x = 1\n"))


class Releases(unittest.TestCase):
    def test_newest_first_drafts_and_bad_tags_skipped(self):
        content = json.dumps([
            {"tag_name": "v0.1.7", "name": "v0.1.7 — Playblast", "body": "### New\n- a"},
            {"tag_name": "v0.2.0-rc1", "prerelease": True},
            {"tag_name": "v0.1.10"},
            {"tag_name": "v9.9.9", "draft": True},
            {"tag_name": "nightly"},
        ])
        notes = parse_releases(content)
        self.assertEqual([note.version for note in notes], ["0.2.0", "0.1.10", "0.1.7"])
        self.assertTrue(notes[0].prerelease)
        self.assertIn("Playblast", notes[-1].display_title)
        self.assertNotIn("0.1.7", notes[-1].display_title)

    def test_not_a_list(self):
        for content in ("{}", "nope"):
            with self.assertRaises(ValueError):
                parse_releases(content)

    def test_sections(self):
        self.assertEqual(split_sections("intro\n### New\n- a\n### Fixed\n\n### Improved\n- b"),
                         [("", "intro"), ("New", "- a"), ("Improved", "- b")])


if __name__ == "__main__":
    unittest.main()
