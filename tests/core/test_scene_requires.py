"""The `requires` lines of a .ma (core/scene_paths/requires.py), their way through the Paths tab's scan and
write, and the Sessions tab's reading of "Plug-in ... was not found" lines (maya_gate/missing_plugins.py)."""
import tempfile
import unittest
from pathlib import Path

from msl_tools.msl.core.scene_paths import ma_paths, requires
from msl_tools.msl.tools.desktop.maya_gate import missing_plugins

SCENE = (b'//Maya ASCII 2024 scene\n'
         b'//Codeset: 1252\n'
         b'file -rdi 1 -ns "dog" -rfn "dogRN" -typ "mayaAscii" "E:/branches/Animation/rig.ma";\n'
         b'requires maya "2024";\r\n'
         b'requires -nodeType "aiOptions" -nodeType "aiAOVDriver" "mtoa" "5.3.4.1";\r\n'
         b'requires "stereoCamera" "10.0";\r\n'
         b'requires "evoattrib" "1.0";\r\n'
         b'requires -nodeType "turtleBakeLayer" "TurtleForMaya2009" "1.0";\r\n'
         b'requires -dataType "byronData" "ByronsPolyTools" "1.0";\r\n'
         b'currentUnit -l centimeter -a degree -t film;\r\n'
         b'createNode transform -n "keep";\r\n'
         b'createNode aiOptions -s -n "defaultArnoldRenderOptions";\r\n')


class ReadTest(unittest.TestCase):
    def test_used_unused_and_the_default(self):
        found = {item.plugin: item for item in requires.read(SCENE, known={"mtoa", "stereocamera"})}
        self.assertNotIn("maya", found)
        self.assertTrue(found["mtoa"].used)
        self.assertFalse(found["mtoa"].removable)
        self.assertTrue(found["stereoCamera"].removable)
        self.assertFalse(found["stereoCamera"].remove)            # Maya has it: only when picked
        self.assertTrue(found["evoattrib"].remove)                # no node types, no Maya has it
        self.assertTrue(found["TurtleForMaya2009"].remove)        # its node type isn't created
        self.assertFalse(found["ByronsPolyTools"].removable)      # a data type: can't be told
        self.assertEqual(found["mtoa"].version, "5.3.4.1")

    def test_without_knowing_the_plugins_nothing_is_picked(self):
        self.assertFalse(any(item.remove for item in requires.read(SCENE, known=None)))

    def test_strip_takes_out_only_unused_lines(self):
        data, removed = requires.strip(SCENE, ["EVOATTRIB", "turtleformaya2009", "mtoa", "ByronsPolyTools"])
        self.assertEqual(removed, 2)
        self.assertNotIn(b"evoattrib", data)
        self.assertNotIn(b"Turtle", data)
        self.assertIn(b'"mtoa"', data)
        self.assertIn(b"ByronsPolyTools", data)
        self.assertIn(b'requires "stereoCamera" "10.0";\r\nrequires -dataType', data)   # line endings kept
        self.assertEqual(len(SCENE) - len(data), len(b'requires "evoattrib" "1.0";\r\n')
                         + len(b'requires -nodeType "turtleBakeLayer" "TurtleForMaya2009" "1.0";\r\n'))

    def test_a_requires_after_the_first_node_is_not_touched(self):
        data = SCENE + b'requires "evoattrib" "1.0";\n'
        stripped, removed = requires.strip(data, ["evoattrib"])
        self.assertEqual(removed, 1)
        self.assertTrue(stripped.endswith(b'requires "evoattrib" "1.0";\n'))


class KnownPluginsTest(unittest.TestCase):
    def test_bin_plugins_and_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            install = root / "Maya2024"
            (install / "bin" / "plug-ins").mkdir(parents=True)
            (install / "bin" / "plug-ins" / "stereoCamera.mll").write_bytes(b"")
            (install / "bin" / "plug-ins" / "fbxmaya.mll").write_bytes(b"")
            arnold = root / "Program Files" / "Arnold" / "maya2024"
            (arnold / "plug-ins").mkdir(parents=True)
            (arnold / "plug-ins" / "mtoa.mll").write_bytes(b"")
            (install / "modules").mkdir()
            (install / "modules" / "mtoa.mod").write_text(f"+ MAYAVERSION:2024 PLATFORM:win64 mtoa any {arnold}\n",
                                                          encoding="utf-8")
            known = requires.known_plugins({"2024": install}, documents=root / "docs", shared=root / "shared")
        self.assertEqual(known, {"stereocamera", "fbxmaya", "mtoa"})


class ScanAndWriteTest(unittest.TestCase):
    def test_a_scene_with_only_requires_to_take_out(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rig.ma"
            path.write_bytes(SCENE)
            result = ma_paths.scan(path, [], known_plugins={"mtoa", "stereocamera"})
            self.assertEqual(sorted(item.plugin for item in result.requires_out), ["TurtleForMaya2009", "evoattrib"])
            self.assertEqual(result.writes, [])
            done = ma_paths.apply(result, backup=True)
            self.assertEqual((done.changed, done.requires), (2, 2))
            self.assertTrue(done.backup.exists())
            self.assertEqual(done.backup.read_bytes(), SCENE)
            self.assertNotIn(b"evoattrib", path.read_bytes())
            again = ma_paths.scan(path, [], known_plugins={"mtoa", "stereocamera"})
            self.assertEqual(again.requires_out, [])

    def test_a_kept_line_is_not_written(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rig.ma"
            path.write_bytes(SCENE)
            result = ma_paths.scan(path, [], known_plugins=set())
            for item in result.requires:
                item.remove = False
            self.assertEqual(ma_paths.apply(result).changed, 0)
            self.assertEqual(path.read_bytes(), SCENE)


class MissingPluginLinesTest(unittest.TestCase):
    LINE = ('file: E:/branches/Animation/Animal_Animation/Project/D_Shiba_Inu/rigs/Rig_Shiba_01.ma line 11: '
            'RuntimeError: file <maya console> line 1: Plug-in, "evoattrib", was not found on MAYA_PLUG_IN_PATH.')

    def test_the_line(self):
        self.assertEqual(missing_plugins.missing_plugin(self.LINE),
                         ("evoattrib", "E:/branches/Animation/Animal_Animation/Project/D_Shiba_Inu/rigs/Rig_Shiba_01.ma"))
        self.assertEqual(missing_plugins.missing_plugin('Plug-in, "x", was not found on MAYA_PLUG_IN_PATH.'), ("x", ""))
        self.assertIsNone(missing_plugins.missing_plugin("Error: something else"))
        self.assertTrue(missing_plugins.needs_arnold("The MtoA plug-in needed for this scene is not loaded."))

    def test_summary_and_files(self):
        missing = {"evoattrib": "E:/a/Rig.ma", "Turtle": "E:/a/Rig.ma", "x": ""}
        self.assertIn("3 plug-ins missing, asked for by Rig.ma", missing_plugins.summary(missing))
        self.assertIn("(the open scene)", missing_plugins.summary(missing, "e:\\a\\rig.ma"))
        self.assertEqual(missing_plugins.files_of(missing, "E:/a/shot.ma"), ["E:/a/Rig.ma"])
        self.assertEqual(missing_plugins.files_of(missing, "E:/a/Rig.ma"), [])
        self.assertEqual(missing_plugins.summary({}), "")


if __name__ == "__main__":
    unittest.main()
