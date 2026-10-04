"""Playblast without Maya: naming, the capture session's set-up / restore against a fake
maya.cmds, and the end of a run (RunEnding) outside the panel."""
import logging
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from msl_tools.msl.tools.maya.playblast import naming


class FakeCmds:
    """The part of maya.cmds a CaptureSession touches, with state to check afterwards."""

    def __init__(self):
        self.state = {"camera": "persp", "selection": ["|ctrl"], "time": 7.0, "modified": False,
                      "undo": True, "vis": {}, "attrs": {"hardwareRenderingGlobals.multiSampleEnable": False,
                                                       "hardwareRenderingGlobals.lineAAEnable": False,
                                                       "hardwareRenderingGlobals.ssaoEnable": False},
                      "range": (1.0, 24.0), "gradient": True, "background": (0.2, 0.3, 0.5)}
        self.state["attrs"]["shotCamShape.overscan"] = 1.0
        self.fail = set()  # names of calls that raise RuntimeError

    def _maybe_fail(self, name):
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    def getPanel(self, withFocus=False, typeOf=None, visiblePanels=False):
        if typeOf:
            return "modelPanel"
        return ["modelPanel4"] if visiblePanels else "modelPanel4"

    def modelPanel(self, panel, query=False, camera=False):
        return self.state["camera"]

    def ls(self, selection=False, long=False):
        return list(self.state["selection"])

    def currentTime(self, value=None, query=False, edit=False):
        if query:
            return self.state["time"]
        self.state["time"] = value

    def file(self, query=False, modified=None, sceneName=False):
        if query and modified:
            return self.state["modified"]
        if query and sceneName:
            return ""
        if modified is not None:
            self.state["modified"] = modified

    def modelEditor(self, panel, query=False, edit=False, **flags):
        if query:
            return self.state["vis"].get(next(iter(flags)), True)
        self._maybe_fail("modelEditor")
        self.state["vis"].update(flags)

    def getAttr(self, plug):
        return self.state["attrs"][plug]

    def setAttr(self, plug, value):
        self._maybe_fail("setAttr")
        self.state["attrs"][plug] = value

    def lookThru(self, panel, camera):
        self._maybe_fail("lookThru")
        self.state["camera"] = camera
        self.state["modified"] = True  # what Maya does: looking through another camera marks the scene

    def select(self, items=None, clear=False, replace=False):
        self._maybe_fail("select")
        self.state["selection"] = [] if clear else list(items)

    def objExists(self, name):
        return True

    def undoInfo(self, query=False, stateWithoutFlush=None):
        if query:
            return self.state["undo"]
        self.state["undo"] = stateWithoutFlush

    def playbackOptions(self, query=False, minTime=False, maxTime=False, **_):
        return self.state["range"][0] if minTime else self.state["range"][1]

    def playblast(self, **_):
        self._maybe_fail("playblast")
        return "frame"

    def nodeType(self, name):
        return "transform"

    def listRelatives(self, node, shapes=False, type=None, fullPath=False):
        return [node + "Shape"]

    def displayPref(self, query=False, displayGradient=None):
        if query:
            return self.state["gradient"]
        self.state["gradient"] = displayGradient

    def displayRGBColor(self, name, *color, query=False):
        if query:
            return list(self.state["background"])
        self.state["background"] = tuple(color)

    def timeControl(self, slider, query=False, **flags):
        return "" if "sound" in flags else False  # no sound on the timeline, no range highlighted


def _render_switches():
    """The values of Viewport 2.0's switches a capture may turn on."""
    return [value for plug, value in cmds.state["attrs"].items() if plug.startswith("hardwareRenderingGlobals.")]


def setUpModule():
    global capture, cmds
    cmds = FakeCmds()
    maya = types.ModuleType("maya")
    maya.cmds = cmds
    maya.mel = types.SimpleNamespace(eval=lambda _command: "24")
    patch = mock.patch.dict(sys.modules, {"maya": maya, "maya.cmds": maya.cmds, "maya.mel": maya.mel})
    patch.start()
    unittest.addModuleCleanup(patch.stop)
    sys.modules.pop("msl_tools.msl.tools.maya.playblast.capture", None)
    from msl_tools.msl.tools.maya.playblast import capture as module
    capture = module


class Naming(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_results_on_their_way_count_for_the_version(self):
        # Before: a second playblast started while the first one's video was made got the same v003.
        (self.folder / "shot_v002.mp4").write_bytes(b"")
        values = {"project": str(self.folder)}
        taken = {self.folder / "shot_v003.mp4"}
        self.assertEqual(naming.version_for(str(self.folder), "shot_{version}", values, ".mp4"), "v003")
        self.assertEqual(naming.version_for(str(self.folder), "shot_{version}", values, ".mp4", taken=taken), "v004")

    def test_free_path_skips_taken_names(self):
        target = self.folder / "shot.mp4"
        self.assertEqual(naming.free_path(target, {target}), self.folder / "shot_2.mp4")
        (self.folder / "shot_2.mp4").write_bytes(b"")
        self.assertEqual(naming.free_path(target, {target}), self.folder / "shot_3.mp4")

    def test_previous_version(self):
        for name in ("shot_v001.mp4", "shot_v002.mp4", "shot_v002_light.mp4", "shot_v010.mp4", "other_v002.mp4"):
            (self.folder / name).write_bytes(b"")
        self.assertEqual(naming.previous_version(self.folder / "shot_v010.mp4"), self.folder / "shot_v002.mp4")
        self.assertEqual(naming.previous_version(self.folder / "shot_v002.mp4"), self.folder / "shot_v001.mp4")
        self.assertIsNone(naming.previous_version(self.folder / "shot_v001.mp4"))
        self.assertIsNone(naming.previous_version(self.folder / "shot.mp4"))  # no version in the name

    def test_relative_folder_goes_into_the_project(self):
        # Before: "movies" was written to Maya's working folder (its bin folder, or Documents).
        values = {"project": str(self.folder / "proj")}
        self.assertEqual(naming.output_path("movies", "shot", values, ".mp4"),
                         self.folder / "proj" / "movies" / "shot.mp4")
        absolute = self.folder / "elsewhere"
        self.assertEqual(naming.output_path(str(absolute), "shot", values, ".mp4"), absolute / "shot.mp4")


class CaptureSessionPutsBack(unittest.TestCase):
    def setUp(self):
        cmds.__init__()  # a fresh fake scene
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.settings = capture.CaptureSettings(folder=Path(temp.name), start=1, end=3, camera="shotCam",
                                                visibility=["polymeshes"], smooth=True, occlusion=True)

    def assert_as_before(self):
        state = cmds.state
        self.assertEqual(state["camera"], "persp")
        self.assertEqual(state["selection"], ["|ctrl"])
        self.assertEqual(state["time"], 7.0)
        self.assertFalse(state["modified"])
        self.assertFalse(any(_render_switches()))
        self.assertTrue(state["undo"])

    def test_a_whole_capture(self):
        session = capture.CaptureSession(self.settings)
        while session.step():
            pass
        session.finish()
        self.assert_as_before()

    def test_setup_that_fails_halfway_puts_back_what_it_changed(self):
        # Before: the render switches stayed on, the panel stayed "Working…".
        cmds.fail.add("lookThru")
        with self.assertRaises(capture.CaptureError):
            capture.CaptureSession(self.settings)
        cmds.fail.clear()
        self.assertFalse(any(_render_switches()))
        self.assertTrue(cmds.state["undo"])

    def test_one_failing_restore_step_doesnt_stop_the_others(self):
        session = capture.CaptureSession(self.settings)
        session.step()
        cmds.fail.add("lookThru")  # e.g. another scene was opened meanwhile
        session.abort()
        cmds.fail.clear()
        self.assertFalse(any(_render_switches()))  # the render switches still went back
        self.assertEqual(cmds.state["time"], 7.0)
        self.assertEqual(cmds.state["selection"], ["|ctrl"])

    def test_undo_left_off_stays_off(self):
        # Before: switched ON after every step, whatever it was.
        cmds.state["undo"] = False
        session = capture.CaptureSession(self.settings)
        session.step()
        session.finish()
        self.assertFalse(cmds.state["undo"])

    def test_background_and_overscan_are_set_for_the_capture_and_put_back(self):
        self.settings.background, self.settings.overscan = (0.0, 0.0, 0.0), 1.1
        session = capture.CaptureSession(self.settings)
        self.assertEqual((cmds.state["gradient"], cmds.state["background"]), (False, (0.0, 0.0, 0.0)))
        self.assertEqual(cmds.state["attrs"]["shotCamShape.overscan"], 1.1)
        session.step()
        session.finish()
        self.assertEqual((cmds.state["gradient"], cmds.state["background"]), (True, (0.2, 0.3, 0.5)))
        self.assertEqual(cmds.state["attrs"]["shotCamShape.overscan"], 1.0)

    def test_sub_frame_ranges_cover_whole_frames(self):
        cmds.state["range"] = (-0.5, 100.5)
        self.assertEqual(capture.frame_range(capture.RANGE_PLAYBACK), (-1, 101))
        cmds.state["range"] = (1.0, 24.0)
        self.assertEqual(capture.frame_range(capture.RANGE_PLAYBACK), (1, 24))


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
except ImportError:
    qt = None


@unittest.skipIf(qt is None, "PySide6 is not installed")
class RunEndsWithoutThePanel(unittest.TestCase):
    """What the end of a run does needs no panel: the window may have been closed meanwhile."""

    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])
        from msl_tools.msl.tools.maya.playblast import ending
        cls.ending = ending

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.config = {}
        resources = types.SimpleNamespace(
            configsMayaMng=types.SimpleNamespace(get_config=lambda _name: self.config),
            logsMaya=types.SimpleNamespace(get=lambda _name: logging.getLogger("test_playblast")))
        patch = mock.patch.object(self.ending, "Resources", lambda: resources)  # never the user's configs
        patch.start()
        self.addCleanup(patch.stop)
        opened = mock.patch.object(self.ending, "open_result")
        self.open_result = opened.start()
        self.addCleanup(opened.stop)

    def run_dict(self, **extra) -> dict:
        target = self.folder / "work" / "shot_v003.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 2048)
        run = {"id": 1, "target": target, "latest": self.folder / "shot.mp4", "video": True, "copy": False,
               "open": True, "started": time.time(), "scene": "shot_010", "scene_path": "D:/a/shot_010.ma",
               "note": "blocking", "frames": 48, "camera": "shotCam", "error": ""}
        run.update(extra)
        self.ending.RunEnding.taken.add(run["target"])
        return run

    def test_ending_with_no_one_listening(self):
        ended = []
        ending = self.ending.RunEnding()
        ending.ended.connect(ended.append)
        run = self.run_dict()
        ending.take(run)
        self.assertTrue((self.folder / "shot.mp4").is_file())  # the {work+} latest copy
        [entry] = self.config["history"]
        self.assertEqual((entry["scene"], entry["scene_path"], entry["note"]),
                         ("shot_010", "D:/a/shot_010.ma", "blocking"))  # as at the START of the capture
        self.open_result.assert_called_once()
        self.assertNotIn(run["target"], self.ending.RunEnding.taken)
        self.assertEqual(ended[0]["state"], "done")

    def test_an_error_is_said_and_nothing_remembered(self):
        ended = []
        ending = self.ending.RunEnding()
        ending.ended.connect(ended.append)
        with self.assertLogs("test_playblast", "WARNING"):
            ending.take(self.run_dict(error="ffmpeg failed"))
        self.assertNotIn("history", self.config)
        self.open_result.assert_not_called()
        self.assertEqual((ended[0]["state"], ended[0]["message"]), ("error", "ffmpeg failed"))


if __name__ == "__main__":
    unittest.main()


def _ffmpeg():
    try:
        from msl_tools.msl.core.media import FfmpegLocator
        return FfmpegLocator().find()
    except Exception:
        return None


@unittest.skipIf(qt is None or _ffmpeg() is None, "needs PySide6 and ffmpeg")
class SideJobs(unittest.TestCase):
    """The light copy and the comparison, made by RunEnding with a real ffmpeg."""

    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])
        from msl_tools.msl.tools.maya.playblast import ending
        cls.ending = ending
        cls.tools = _ffmpeg()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        for name, color in (("shot_v001.mp4", "red"), ("shot_v002.mp4", "blue")):
            import subprocess
            subprocess.run([str(self.tools.ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                            f"color={color}:size=640x480:rate=24", "-t", "1", "-pix_fmt", "yuv420p",
                            str(self.folder / name)], check=True, stdin=subprocess.DEVNULL)
        resources = types.SimpleNamespace(logsMaya=types.SimpleNamespace(get=lambda _n: logging.getLogger("t")))
        for name, value in (("Resources", lambda: resources), ("open_result", lambda _path: None)):
            patch = mock.patch.object(self.ending, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def wait(self, ending) -> dict:
        results = []
        ending.side_done.connect(results.append)
        deadline = time.monotonic() + 60
        while not results and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        self.assertTrue(results, "no answer")
        return results[0]

    def test_light_copy(self):
        ending = self.ending.RunEnding()
        with mock.patch.object(self.ending, "LIGHT_HEIGHT", 240):  # 480 px is "too tall" now: a copy is made
            ending.make_light_copy(self.folder / "shot_v002.mp4", self.tools, copy=True)
            result = self.wait(ending)
        self.assertEqual(result["state"], "done", result.get("message"))
        self.assertEqual(Path(result["output"]).name, "shot_v002_light.mp4")
        self.assertTrue(Path(result["output"]).is_file())
        from msl_tools.msl.core.media import probe
        self.assertEqual(probe(self.tools, Path(result["output"])).height, 240)
        # under the size limit, only too tall: a small-quality copy, never bigger than the playblast
        self.assertLess(Path(result["output"]).stat().st_size, (self.folder / "shot_v002.mp4").stat().st_size)
        urls = qt.QtWidgets.QApplication.clipboard().mimeData().urls()
        self.assertEqual(Path(urls[0].toLocalFile()).name, "shot_v002_light.mp4")  # the light one, ready to paste

    def test_light_enough_already(self):
        ending = self.ending.RunEnding()
        ending.make_light_copy(self.folder / "shot_v002.mp4", self.tools)
        result = self.wait(ending)
        self.assertEqual(Path(result["output"]), self.folder / "shot_v002.mp4")
        self.assertIn("Light enough already", result["message"])

    def test_compare_with_previous(self):
        ending = self.ending.RunEnding()
        ending.compare_with(self.folder / "shot_v002.mp4", self.folder / "shot_v001.mp4", self.tools)
        result = self.wait(ending)
        self.assertEqual(result["state"], "done", result.get("message"))
        self.assertEqual(Path(result["output"]).name, "shot_v002_vs_shot_v001.mp4")
        from msl_tools.msl.core.media import probe
        self.assertEqual(probe(self.tools, Path(result["output"])).width, 1280)  # two 640 wide side by side
