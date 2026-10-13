"""core/link/assistant_guard.py: which code deserves a question first, and the journal."""
import os
import shutil
import tempfile
import time
import unittest

from msl_tools.msl.core.link import assistant_guard as guard
from msl_tools.msl.core.link import maya_snippets as snippets


class Risks(unittest.TestCase):
    def says(self, code: str) -> str:
        return ", ".join(guard.risks(code))

    def test_reading_and_ordinary_scene_work_ask_nothing(self):
        for code in ("import maya.cmds as cmds\ncmds.ls(sl=True)",
                     "cmds.file(q=True, sn=True)", "cmds.file(query=True, modified=True)",
                     "cmds.file(modified=False)",                      # only the mark
                     "cmds.file(save=False)",                          # plainly switched off
                     "cmds.polyCube(name='box')\ncmds.delete('box')",  # scene objects: undoable
                     "names.remove('a')",                              # a list's remove, not os.remove
                     "image.save(path, 'PNG')", "open(path).read()", "x = quit_requested",
                     "def f(:\n  broken"):                             # not Python: Maya refuses it itself
            self.assertEqual(guard.risks(code), [], code)

    def test_saving_opening_and_new_scenes(self):
        self.assertEqual(self.says("cmds.file(save=True)"), "saves the scene")
        self.assertEqual(self.says("cmds.file(rename='C:/a.ma')\ncmds.file(s=True, type='mayaAscii')"),
                         "gives the scene another file name, saves the scene")
        self.assertIn("starts a new scene", self.says("mc.file(new=True, force=True)"))
        self.assertIn("opens another scene", self.says("maya.cmds.file('C:/b.ma', o=True, f=True)"))
        self.assertIn("writes a scene file", self.says("cmds.file('C:/c.ma', exportSelected=True, type='mayaAscii')"))
        self.assertIn("saves the scene", self.says("pm.saveFile()"))

    def test_closing_deleting_and_other_programs(self):
        self.assertEqual(self.says("cmds.quit(force=True)"), "closes Maya")
        self.assertEqual(self.says("import os\nos.remove(path)"), "deletes a file")
        self.assertEqual(self.says("Path(folder).unlink()"), "deletes a file")
        self.assertIn("deletes a folder with everything in it", self.says("shutil.rmtree(folder)"))
        self.assertEqual(self.says("os.system('del x')"), "starts another program")
        self.assertEqual(self.says("subprocess.run(['x'])"), "starts another program")

    def test_what_cannot_be_read_is_asked_about(self):
        self.assertEqual(self.says("exec(text)"), "runs code the hub cannot read")
        self.assertEqual(self.says("mel.eval(command)"), "runs MEL the hub cannot read")
        self.assertEqual(self.says("mel.eval('file -f -save')"), "runs MEL that saves, opens or closes")
        self.assertEqual(guard.risks("mel.eval('ls -sl')"), [])

    def test_the_tools_own_snippets_ask_nothing(self):
        from msl_tools.msl import run_maya_mcp
        for code in (snippets.SCENE_CODE % {"mark": snippets.MARK},
                     snippets.NODE_CODE % {"mark": snippets.MARK, "node": "x"},
                     run_maya_mcp.VIEWPORT_CODE % {"path": "C:/x.png", "width": 640},
                     run_maya_mcp.WINDOW_CODE % {"path": "C:/x.png", "wanted": "controls"}):
            self.assertEqual(guard.risks(code), [])


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_entries_are_appended_to_the_days_file(self):
        journal = guard.Journal(os.path.join(self.folder, "assistant"))   # made on first use
        moment = time.mktime((2026, 10, 14, 9, 30, 5, 0, 0, -1))
        journal.record("ran Python", "Maya 2026 \u00b7 Dev \u00b7 pid 7", "cmds.ls()\n", "# Result: []", moment)
        journal.record("the user REFUSED code that saves the scene", "", "cmds.file(save=True)", "", moment + 60)
        with open(journal.file_for(moment), encoding="utf-8") as handle:
            text = handle.read()
        self.assertTrue(journal.file_for(moment).name == "2026-10-14.log")
        self.assertIn("=== 2026-10-14 09:30:05  ran Python  |  Maya 2026 \u00b7 Dev \u00b7 pid 7\ncmds.ls()\n--- outcome\n# Result: []\n", text)
        self.assertIn("=== 2026-10-14 09:31:05  the user REFUSED code that saves the scene\ncmds.file(save=True)\n", text)

    def test_long_code_is_cut_and_old_files_go(self):
        journal = guard.Journal(self.folder)
        old = os.path.join(self.folder, "2020-01-01.log")
        open(old, "w").close()
        os.utime(old, (0, 0))
        journal.record("ran Python", body="\n".join("line %d" % number for number in range(journal.BODY_LINES + 7)))
        with open(journal.file_for(), encoding="utf-8") as handle:
            self.assertIn("... 7 more lines", handle.read())
        self.assertFalse(os.path.exists(old))

    def test_a_folder_that_cannot_be_made_is_no_error(self):
        blocker = os.path.join(self.folder, "file")
        open(blocker, "w").close()
        guard.Journal(os.path.join(blocker, "under_a_file")).record("ran Python")   # must not raise


if __name__ == "__main__":
    unittest.main()
