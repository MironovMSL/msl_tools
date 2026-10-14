"""core/scene_paths: which variables can stand for a folder, and swapping that folder for $NAME in a .ma."""
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from msl_tools.msl.core.scene_paths import coverage, finder, ma_paths, mb_paths
from msl_tools.msl.core.scene_paths.roots import Root, normalized, roots_from, why_not

SCENE = (
    '//Maya ASCII 2024 scene\r\n'
    '//Codeset: 1252\r\n'
    'file -rdi 1 -ns ":" -rfn "RigRN" -typ "mayaAscii" "E:/branches/Animation/Rig/Rig.ma";\r\n'
    'file -r -ns ":" -dr 1 -rfn "RigRN" -typ "mayaAscii" "E:/branches/Animation/Rig/Rig.ma";\r\n'
    'requires maya "2024";\r\n'
    'createNode file -n "file1";\r\n'
    '\tsetAttr ".ftn" -type "string" "e:\\\\Branches\\\\animation\\\\tex\\\\a.png";\r\n'
    'createNode file -n "file2";\r\n'
    '\tsetAttr ".ftn" -type "string" "E:/branches/AnimationOld/b.png";\r\n'
    'createNode file -n "file3";\r\n'
    '\tsetAttr ".ftn" -type "string" "$WG_ANIM/tex/c.png";\r\n'
    'createNode file -n "file4";\r\n'
    '\tsetAttr ".ftn" -type "string" "E:/branches/Animation/chars/dog/d.<UDIM>.png";\r\n'
    'createNode reference -n "RigRN";\r\n'
    '\tsetAttr ".fn[0]" -type "string" "C:/Users/someone/Rig.ma";\r\n'
    '\tsetAttr ".ed" -type "dataReferenceEdits"\r\n'
    '\t\t2 "file5" "fileTextureName" " -type \\"string\\" \\"E:/branches/Animation/tex/e.png\\""\r\n'
    'createNode script -n "uiConfigurationScriptNode";\r\n'
    '\tsetAttr ".b" -type "string" (\r\n'
    '\t\t"hyperGraph -image \\"E:/branches/Animation/bg.jpg\\" ;"\r\n'
    '\t\t+ "$panelName = 1;");\r\n'
)
ROOTS = roots_from({"WG_ANIM": "E:/branches/Animation", "WG_DOG": "E:\\branches\\Animation\\chars\\dog\\"})


class Roots(unittest.TestCase):
    def test_only_one_absolute_folder_can_be_a_root(self):
        self.assertEqual(why_not("WG_ANIM", "E:/branches/Animation"), "")
        self.assertEqual(why_not("NAS", "\\\\server\\share\\anim"), "")
        self.assertIn("drive", why_not("X", "E:/"))
        self.assertIn("share", why_not("X", "//server/share"))
        self.assertIn("list", why_not("X", "E:/a;E:/b"))
        self.assertIn("other variables", why_not("X", "%USERPROFILE%/maya"))
        self.assertIn("absolute", why_not("X", "relative/folder"))
        self.assertIn("name", why_not("1BAD", "E:/a"))
        self.assertIn("empty", why_not("X", "  "))

    def test_deepest_folder_first_and_slashes_made_forward(self):
        self.assertEqual([root.name for root in ROOTS], ["WG_DOG", "WG_ANIM"])
        self.assertEqual(ROOTS[0].value, "E:/branches/Animation/chars/dog")
        self.assertEqual(normalized("\\\\srv\\\\share\\x\\"), "//srv/share/x")
        self.assertEqual(Root("WG_ANIM", "E:/a").token, "$WG_ANIM")


class Scenes(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(self._clean)
        self.scene = self.folder / "shot.ma"
        self.scene.write_bytes(SCENE.encode("cp1252"))

    def _clean(self):
        for file in self.folder.rglob("*"):
            if file.is_file():
                os.chmod(file, stat.S_IWRITE)
        shutil.rmtree(self.folder, True)

    def uses(self, result):
        return {(use.line, use.where): use for use in result.uses}

    def test_every_path_is_found_with_what_it_is_for(self):
        result = ma_paths.scan(self.scene, ROOTS, environment={}, check_files=False)
        self.assertEqual(result.codeset, "cp1252")
        self.assertEqual(result.error, "")
        found = [(use.line, use.kind, use.where, use.state) for use in result.uses]
        self.assertEqual(found, [
            (3, ma_paths.REFERENCE, "RigRN", ma_paths.CHANGE),
            (4, ma_paths.REFERENCE, "RigRN", ma_paths.CHANGE),
            (7, ma_paths.TEXTURE, "file1.ftn", ma_paths.CHANGE),        # any case, escaped backslashes
            (9, ma_paths.TEXTURE, "file2.ftn", ma_paths.OUTSIDE),       # AnimationOld is another folder
            (11, ma_paths.TEXTURE, "file3.ftn", ma_paths.VARIABLE),
            (13, ma_paths.TEXTURE, "file4.ftn", ma_paths.CHANGE),
            (15, ma_paths.REFERENCE_HISTORY, "RigRN.fn[0]", ma_paths.OUTSIDE),
            (17, ma_paths.REFERENCE_EDIT, "file5.fileTextureName", ma_paths.CHANGE),
            (20, ma_paths.SCRIPT, "uiConfigurationScriptNode", ma_paths.LEFT),   # MEL code: left alone
        ])
        by_line = {use.line: use for use in result.uses}
        self.assertEqual(by_line[13].root.name, "WG_DOG")                  # the deeper root wins
        self.assertEqual(by_line[13].new_path, "$WG_DOG/d.<UDIM>.png")
        self.assertEqual(by_line[7].path, "e:/Branches/animation/tex/a.png")
        self.assertEqual(by_line[7].new_path, "$WG_ANIM/tex/a.png")
        self.assertEqual(by_line[11].variable, "WG_ANIM")

    def test_the_swap_touches_nothing_but_the_folder(self):
        result = ma_paths.scan(self.scene, ROOTS, environment={}, check_files=False)
        updated = ma_paths.rewrite(self.scene.read_bytes(), result.uses, result.codeset).decode("cp1252")
        expected = (SCENE
                    .replace('"E:/branches/Animation/Rig/Rig.ma"', '"$WG_ANIM/Rig/Rig.ma"')
                    .replace('"e:\\\\Branches\\\\animation\\\\tex', '"$WG_ANIM\\\\tex')
                    .replace('"E:/branches/Animation/chars/dog/d.', '"$WG_DOG/d.')
                    .replace('\\"E:/branches/Animation/tex/e.png', '\\"$WG_ANIM/tex/e.png'))
        self.assertEqual(updated, expected)          # CRLF kept, the script's path kept

    def test_files_are_checked_through_the_variables(self):
        (self.folder / "tex").mkdir()
        (self.folder / "tex" / "c.png").write_bytes(b"")
        result = ma_paths.scan(self.scene, ROOTS, environment={"WG_ANIM": str(self.folder)})
        by_line = {use.line: use for use in result.uses}
        self.assertIs(by_line[11].exists, True)      # $WG_ANIM/tex/c.png, through the environment given
        self.assertIsNone(by_line[13].exists)        # <UDIM>: a pattern, not a file
        self.assertIs(by_line[15].exists, False)
        self.assertIs(by_line[20].exists, False)
        self.assertNotIn(by_line[20], result.missing)    # a UI layout's picture is no file the scene needs
        self.assertNotIn(by_line[15], result.missing)    # a reference's old file name: nothing loads it

    def test_a_root_the_file_can_hold_in_its_own_encoding(self):
        scene = self.folder / "ru.ma"
        scene.write_bytes('//Maya ASCII 2024 scene\n//Codeset: 1251\ncreateNode file -n "f";\n'
                          '\tsetAttr ".ftn" -type "string" "D:/Проекты/Пёс/a.png";\n'.encode("cp1251"))
        roots = roots_from({"PROJ": "D:/Проекты"})
        result = ma_paths.scan(scene, roots, environment={}, check_files=False)
        self.assertEqual([use.new_path for use in result.changes], ["$PROJ/Пёс/a.png"])
        self.assertEqual(ma_paths.apply(result, backup=False).changed, 1)
        self.assertIn('"$PROJ/Пёс/a.png"', scene.read_bytes().decode("cp1251"))

    def test_apply_writes_a_backup_and_refuses_what_it_must_not_write(self):
        original = self.scene.read_bytes()
        result = ma_paths.scan(self.scene, ROOTS, environment={}, check_files=False)
        done = ma_paths.apply(result)
        self.assertEqual(done.changed, 5)
        self.assertEqual(done.backup.read_bytes(), original)
        self.assertTrue(done.backup.name.startswith("shot.ma.") and done.backup.suffix == ".bak")
        again = ma_paths.scan(self.scene, ROOTS, environment={}, check_files=False)
        self.assertEqual(len(again.changes), 0)
        self.assertEqual(len(again.via_variable), 6)
        self.scene.write_bytes(original)
        stale = ma_paths.scan(self.scene, ROOTS, environment={}, check_files=False)
        self.scene.write_bytes(original + b"// saved again in Maya\n")   # read, then changed by someone else
        with self.assertRaises(ma_paths.ScenePathsError) as raised:
            ma_paths.apply(stale)
        self.assertIn("changed since", str(raised.exception))
        self.scene.write_bytes(original)
        fresh = ma_paths.scan(self.scene, ROOTS, environment={}, check_files=False)
        os.chmod(self.scene, stat.S_IREAD)
        with self.assertRaises(ma_paths.ScenePathsError) as raised:
            ma_paths.apply(fresh)
        self.assertIn("read-only", str(raised.exception))
        self.assertEqual(self.scene.read_bytes(), original)

    def test_what_is_not_read(self):
        binary = self.folder / "b.mb"
        binary.write_bytes(b"FOR4")
        self.assertIn(".mb", ma_paths.scan(binary, ROOTS).error)
        other = self.folder / "x.ma"
        other.write_bytes(b"hello")
        self.assertIn("Maya ASCII", ma_paths.scan(other, ROOTS).error)
        self.assertIn("read", ma_paths.scan(self.folder / "gone.ma", ROOTS).error)

    def test_scenes_of_a_drop(self):
        (self.folder / "seq" / "incrementalSave").mkdir(parents=True)
        (self.folder / "seq" / "incrementalSave" / "old.ma").write_bytes(b"")
        (self.folder / "seq" / "b.mb").write_bytes(b"")
        (self.folder / "seq" / "notes.txt").write_bytes(b"")
        (self.folder / ".hidden").mkdir()
        (self.folder / ".hidden" / "h.ma").write_bytes(b"")
        scenes, cut = ma_paths.collect_scenes([self.scene, self.folder])
        self.assertEqual([scene.name for scene in scenes], ["shot.ma", "b.mb"])
        self.assertFalse(cut)
        self.assertEqual(ma_paths.collect_scenes([self.folder], limit=1), ([self.scene], True))


class BinaryScenes(unittest.TestCase):
    """mb_paths without Maya: which Maya may read / write a scene, and sorting what a mayapy found."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def scene(self, name, year):
        path = self.folder / name
        path.write_bytes(b"FOR8" + bytes(4) + b"HEADVERS" + year.encode() + b'requires maya "' + year.encode() + b'"')
        return path

    def test_reading_may_go_forward_writing_never(self):
        installed = {"2024": Path("A"), "2026": Path("B")}
        old, odd = self.scene("old.mb", "2023"), self.scene("odd.mb", "2027")
        self.assertEqual(mb_paths.maya_to_read(old, installed), "2024")      # the oldest newer one reads it
        self.assertEqual(mb_paths.maya_to_read(odd, installed), "")           # nothing older reads a newer scene
        self.assertEqual(mb_paths.maya_to_write(self.scene("s.mb", "2024"), installed), ("2024", ""))
        year, why = mb_paths.maya_to_write(old, installed)
        self.assertEqual(year, "")
        self.assertIn("2023", why)

    def test_what_a_mayapy_found_is_sorted_by_the_roots(self):
        raw = {"maya": "2024", "size": 10, "mtime_ns": 20, "data": {"uses": [
            {"kind": "reference", "node": "rigRN", "path": "E:/branches/Animation/rig.mb"},
            {"kind": "attribute", "node": "rig:tex", "attribute": "fileTextureName",
             "path": r"E:\\branches\Animation\t.png", "inside": True, "note": "inside the referenced file"},
            {"kind": "texture", "node": "own", "attribute": "fileTextureName", "path": "$WG_ANIM/x.png"},
            {"kind": "texture", "node": "far", "attribute": "fileTextureName", "path": "W:/x.png"}]}}
        result = mb_paths.scan_from_raw(self.folder / "s.mb", raw, ROOTS, environment={})
        self.assertTrue(result.binary)
        self.assertEqual((result.maya, result.size, result.mtime_ns), ("2024", 10, 20))
        self.assertEqual([use.state for use in result.uses],
                         [ma_paths.CHANGE, ma_paths.LEFT, ma_paths.VARIABLE, ma_paths.OUTSIDE])
        self.assertEqual(result.uses[0].new_path, "$WG_ANIM/rig.mb")
        self.assertEqual(result.uses[1].note, "inside the referenced file")
        with self.assertRaises(ma_paths.ScenePathsError):     # the text road never writes a binary scene
            ma_paths.apply(result)


class FindingMissingFiles(unittest.TestCase):
    """finder.py: a missing file found again by its name, and the relink written into the scene."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        for relative in ("Project/Labrador/model/Pet_AM.tga", "Project/Labrador/model/normal.png",
                         "Project/Husky/model/normal.png", "Old/Labrador 1/texture/bake.png",
                         "Project/incrementalSave/bake.png", "Project/.hidden/Pet_AM.tga"):
            file = self.folder / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"")
        self.root = Root("WG_ANIM", normalized(str(self.folder)))

    def test_found_by_name_the_most_alike_wins_a_tie_is_left(self):
        index = finder.build_index([self.folder, self.folder / "Project"])   # a folder inside another: once
        self.assertEqual(index.count, 4)
        found = finder.candidates("W:/Maya/assets/Labrador 1/texture/PET_am.tga", index)
        self.assertEqual(len(found), 1)
        self.assertEqual(finder.best("W:/x/Pet_AM.tga", found), found[0])
        normals = finder.candidates("C:/old/Labrador/model/normal.png", index)
        self.assertTrue(normals[0].endswith("Labrador/model/normal.png"))
        self.assertEqual(finder.best("C:/old/Labrador/model/normal.png", normals), normals[0])
        self.assertEqual(finder.best("C:/old/normal.png", finder.candidates("C:/old/normal.png", index)), "")
        self.assertEqual(finder.candidates("C:/old/none.png", index), [])
        self.assertEqual(finder.through_root(normals[0], [self.root]), "$WG_ANIM/Project/Labrador/model/normal.png")
        self.assertEqual(finder.through_root("D:/elsewhere/a.png", [self.root]), "D:/elsewhere/a.png")
        self.assertEqual(finder.key_of("W:\\Maya\\A.TGA"), finder.key_of("w:/maya/a.tga"))
        self.assertTrue(finder.build_index([self.folder], limit=2).cut)

    def test_a_relink_replaces_the_whole_path_in_a_ma(self):
        scene = self.folder / "shot.ma"
        scene.write_bytes(("//Maya ASCII 2024 scene\n//Codeset: 1252\ncreateNode file -n \"f\";\n"
                           "\tsetAttr \".ftn\" -type \"string\" \"W:/Maya/Labrador 1/texture/Pet_AM.tga\";\n"
                           + r'		2 "g" "fileTextureName" " -type \"string\" \"C:\\\\old\\\\normal.png\""'
                           + "\n").encode("cp1252"))
        result = ma_paths.scan(scene, [self.root], environment={})
        self.assertEqual(len(result.missing), 2)
        for use, new in zip(result.missing, ("$WG_ANIM/Project/Labrador/model/Pet_AM.tga", "$WG_ANIM/x/normal.png")):
            use.relink = new
        self.assertEqual((len(result.relinks), len(result.writes), len(result.changes)), (2, 2, 0))
        self.assertEqual(ma_paths.apply(result, backup=False).changed, 2)
        text = scene.read_bytes().decode("cp1252")
        self.assertIn('"$WG_ANIM/Project/Labrador/model/Pet_AM.tga";', text)
        self.assertIn(r'\"$WG_ANIM/x/normal.png\""', text)      # inside a string inside a string
        self.assertEqual(text.count("W:/") + text.count("old"), 0)


class WhereAVariableIsSet(unittest.TestCase):
    """coverage.py: Maya Gate's environments, Windows, every Maya.env Maya reads."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.documents = self.folder / "Documents" / "maya"
        self.app_dir = self.folder / "prefs_dev"
        self.gate = self.folder / "config.json"
        self.gate.write_text(json.dumps({
            "maya": {"Dev": {"MAYA_APP_DIR": str(self.app_dir)}},
            "custom": {"Dev": {"WG_ANIM": "E:/branches/Animation"}, "Stable": {"WG_ANIM": ""}}}), encoding="utf-8")

    def env_file(self, folder, text):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "Maya.env").write_text(text, encoding="utf-8")

    def test_only_dev_sets_it(self):
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents, windows={})["WG_ANIM"]
        self.assertEqual(found.gate_with, ["Dev"])
        self.assertEqual(found.gate_without, ["<default>", "Stable"])
        gaps = found.gaps()
        self.assertEqual(len(gaps), 3)                     # a plain Maya, <default>, Stable
        self.assertIn("not started from Maya Gate", gaps[0])
        self.assertIn("Maya Gate · <default>: — not set", found.describe())

    def test_the_documents_maya_env_covers_a_plain_maya_and_environments_without_their_own(self):
        self.env_file(self.documents / "2024", "WG_ANIM = E:/branches/Animation  \n")
        self.env_file(self.documents, "WG_ANIM = not read by Maya\n")       # no year: Maya doesn't read it
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents, windows={})["WG_ANIM"]
        self.assertEqual(found.maya_env["Maya 2024"], "E:/branches/Animation")
        self.assertEqual(found.gaps(), [])   # Dev has it itself; <default> / Stable read the Documents one

    def test_an_environment_with_its_own_prefs_reads_only_its_own_maya_env(self):
        self.gate.write_text(json.dumps({"maya": {"Stable": {"MAYA_APP_DIR": str(self.app_dir)}}}), encoding="utf-8")
        self.env_file(self.documents / "2024", "WG_ANIM=E:/a\n")
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents, windows={})["WG_ANIM"]
        self.assertEqual(found.gaps(), ["Maya Gate · Stable"])
        self.env_file(self.app_dir / "2024", "WG_ANIM=E:/b\n")
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents, windows={})["WG_ANIM"]
        self.assertEqual(found.gaps(), [])

    def test_lines_meant_for_it_that_dont_set_it_are_named(self):
        self.env_file(self.documents / "2024", "$WG_anim = E:\\branches\\Animation;\nwg_anim2 = x\n")
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents, windows={})["WG_ANIM"]
        self.assertEqual(found.maya_env["Maya 2024"], "")
        self.assertEqual(len(found.problems), 1)
        self.assertIn("no “$” before the name", found.problems[0])
        self.env_file(self.documents / "2024", "wg_anim = E:/branches/Animation;\n")
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents, windows={})["WG_ANIM"]
        self.assertIn("makes it a list", found.problems[0])
        self.env_file(self.documents / "2024", "wg_anim = E:/branches/Animation\n")   # any case, as on Windows
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents, windows={})["WG_ANIM"]
        self.assertEqual((found.maya_env["Maya 2024"], found.problems), ("E:/branches/Animation", []))

    def test_windows_sets_it_for_everything(self):
        found = coverage.coverage(["WG_ANIM"], self.gate, ["2024"], self.documents,
                                  windows={"user": {"WG_ANIM": "E:/branches/Animation"}})["WG_ANIM"]
        self.assertEqual((found.in_windows, found.gaps()), ("E:/branches/Animation", []))


if __name__ == "__main__":
    unittest.main()
