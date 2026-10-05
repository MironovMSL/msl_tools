"""core/batch: frame lists, jobs and their queue file, what a scene's probe means, how a job runs."""
import json
import tempfile
import unittest
from pathlib import Path

from msl_tools.msl.core.batch import ERROR, OK, WARNING, check, choose_renderer, format_frames, parse_frames
from msl_tools.msl.core.batch import commands, environments
from msl_tools.msl.core.batch.frames import FramesError
from msl_tools.msl.core.batch.job import (ARNOLD, HW2, MODE_HEADLESS, MODE_WINDOW, REDSHIFT, RUNNING, WAITING, BatchJob,
                                          BatchStore)

PROBE = {"maya": "2024", "renderer": "arnold", "renderers": ["arnold", "mayaHardware2", "mayaSoftware"],
         "unknown_plugins": [], "cameras": [{"name": "persp", "renderable": True, "startup": True},
                                            {"name": "shotCam", "renderable": False, "startup": False}],
         "resolution": [1920, 1080], "playback": [1.0, 5.0], "lights": ["keyShape"], "textures": 2,
         "missing_textures": [], "caches": [], "references": [], "time_unit": "film"}


class Frames(unittest.TestCase):
    def test_ways_of_writing(self):
        self.assertEqual(parse_frames("1-5"), [1, 2, 3, 4, 5])
        self.assertEqual(parse_frames("1, 20, 78"), [1, 20, 78])
        self.assertEqual(parse_frames("1 20 78"), [1, 20, 78])
        self.assertEqual(parse_frames("1-10x3"), [1, 4, 7, 10])
        self.assertEqual(parse_frames("1..3"), [1, 2, 3])
        self.assertEqual(parse_frames("10-8"), [8, 9, 10])
        self.assertEqual(parse_frames("5, 3-6"), [5, 3, 4, 6])   # in the order written, each once
        self.assertEqual(format_frames([1, 2, 3, 5, 7, 8]), "1-3, 5, 7-8")

    def test_wrong_text_says_why(self):
        for text in ("", "abc", "1-5x0", "1,,a"):
            with self.assertRaises(FramesError):
                parse_frames(text)


class Jobs(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.job = BatchJob(scene=str(self.folder / "shot_010.ma"), probe=dict(PROBE))

    def test_defaults_come_from_the_scene(self):
        self.assertEqual(self.job.frame_list(), [1, 2, 3, 4, 5])
        self.assertEqual(self.job.camera_name(), "shotCam")              # the scene's own, not persp
        self.assertEqual(self.job.prefix(), "shot_010_shotCam")
        self.assertEqual(self.job.output_folder(), self.folder / "renders" / "shot_010")
        self.job.size = "50%"
        self.assertEqual(self.job.resolution(), (960, 540))

    def test_frames_already_there_are_known(self):
        self.job.output_folder().mkdir(parents=True)
        self.job.frame_file(2).write_bytes(b"png")
        self.assertEqual(self.job.existing_frames(), [2])
        self.assertEqual(commands.missing_runs(self.job), [(1, 1), (3, 5)])

    def test_store_round_trip_and_interrupted_jobs_wait(self):
        store = BatchStore(self.folder / "cfg")
        self.job.state = RUNNING
        store.save([self.job])
        loaded = store.load()
        self.assertEqual(loaded[0].scene, self.job.scene)
        self.assertEqual(loaded[0].state, WAITING)
        self.assertIn("where it stopped", loaded[0].message)


class Layers(unittest.TestCase):
    def test_a_layered_scenes_frames_land_in_the_layers_folder(self):
        job = BatchJob(scene="C:/x/shot.ma", probe=dict(PROBE, render_layers=["beauty", "shadow"]))
        self.assertEqual(job.frame_dir().name, "masterLayer")
        job.layer = "beauty"
        self.assertEqual(job.frame_dir(), job.output_folder() / "beauty")
        self.assertEqual(job.video_path().name, "shot_shotCam_beauty.mp4")
        job.renderer = HW2
        _program, arguments, _extra = commands.command(job, "render", Path("M"), Path("task.json"), run=(1, 5))
        self.assertEqual(arguments[arguments.index("-rl") + 1], "beauty")   # one layer, not every layer
        plain = BatchJob(scene="C:/x/shot.ma", probe=dict(PROBE))
        self.assertEqual(plain.frame_dir(), plain.output_folder())

    def test_the_likely_shot_camera_is_picked(self):
        cameras = [{"name": name, "renderable": False, "startup": False} for name in ("Cam", "Cam_cam1", "Cam_cam")]
        job = BatchJob(scene="C:/x/shot.ma", probe=dict(PROBE, cameras=cameras))
        self.assertEqual(job.camera_name(), "Cam_cam")


class Environments(unittest.TestCase):
    def test_variables_and_msl_paths_in_front(self):
        folder = Path(tempfile.mkdtemp())
        config = folder / "config.json"
        config.write_text(json.dumps({"maya": {"Dev": {"MAYA_MODULE_PATH": "D:/modules", "EMPTY": ""}},
                                      "custom": {"Dev": {"STUDIO": "x"}, "Lighting": {}}}), encoding="utf-8")
        self.assertIn("Lighting", environments.names(config))
        result = environments.variables(config, "Dev", "H:/pkg", "H:/pkg/msl/maya_module", base={"PYTHONPATH": "ide"})
        self.assertEqual(result["STUDIO"], "x")
        self.assertNotIn("EMPTY", result)
        self.assertTrue(result["MAYA_MODULE_PATH"].startswith("H:/pkg/msl/maya_module"))
        self.assertTrue(result["MAYA_MODULE_PATH"].endswith("D:/modules"))
        self.assertEqual(result["PYTHONPATH"], "H:/pkg")                 # the hub's own PYTHONPATH never goes along


class Checks(unittest.TestCase):
    def job(self, **probe):
        return BatchJob(scene="C:/x/shot.ma", probe=dict(PROBE, **probe))

    def levels(self, job):
        return {issue.level for issue in check(job)}

    def test_a_good_scene_has_no_problem(self):
        self.assertEqual(self.levels(self.job()), {OK})

    def test_no_light_is_an_error_except_for_the_viewport(self):
        job = self.job(lights=[])
        self.assertIn(ERROR, self.levels(job))
        job.renderer = HW2
        self.assertNotIn(ERROR, self.levels(job))

    def test_redshift_scene_without_redshift(self):
        job = self.job(renderer="mayaSoftware", unknown_plugins=["redshift4maya"])
        self.assertEqual(choose_renderer(job), REDSHIFT)
        self.assertTrue(any(issue.level == ERROR and "Redshift" in issue.text for issue in check(job)))

    def test_missing_files(self):
        job = self.job(caches=[["D:/gone.abc", False]], missing_textures=["D:/a.png"])
        issues = check(job)
        self.assertEqual(issues[0].level, ERROR)
        self.assertTrue(any(issue.level == WARNING and "texture" in issue.text for issue in issues))


class Commands(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.scene = self.folder / "shot.ma"
        self.scene.write_text('//Maya ASCII 2023 scene\nrequires maya "2023";\n')
        self.job = BatchJob(scene=str(self.scene), probe=dict(PROBE))

    def test_which_maya(self):
        installed = {"2020": Path("a"), "2024": Path("b"), "2025": Path("c")}
        self.assertEqual(commands.scene_maya_version(self.scene), "2023")
        self.assertEqual(commands.pick_maya(self.job, installed), "2024")      # the next one up
        self.job.maya = "2025"
        self.assertEqual(commands.pick_maya(self.job, installed), "2025")

    def test_roads(self):
        task = commands.write_task(self.job, "render", self.folder / "work")
        self.assertEqual(json.loads(task.read_text())["frames"], [1, 2, 3, 4, 5])
        self.job.mode = MODE_WINDOW
        program, arguments, extra = commands.command(self.job, "render", Path("M"), task)
        self.assertTrue(program.endswith("maya.exe") and "MSL_BATCH_TASK" in extra)
        self.job.mode = MODE_HEADLESS
        program, arguments, extra = commands.command(self.job, "render", Path("M"), task)
        self.assertTrue(program.endswith("mayapy.exe"))
        self.job.renderer = HW2
        program, arguments, _extra = commands.command(self.job, "render", Path("M"), task)
        self.assertTrue(program.endswith("Render.exe"))
        self.assertEqual(arguments[arguments.index("-s") + 1:arguments.index("-s") + 4], ["1", "-e", "5"])
        self.assertNotIn("-seq", arguments)    # hw2 takes no frame list
        self.assertNotIn("-ehl", arguments)    # breaks Maya 2024's render script

    def test_the_environment_drops_the_hubs_python(self):
        environment = commands.clean_environment({"PYTHONPATH": "x", "PATH": "p"})
        self.assertNotIn("PYTHONPATH", environment)
        self.assertEqual(environment["PATH"], "p")

    def test_progress_reads_whole_lines_only(self):
        path = self.folder / "progress.jsonl"
        path.write_text('{"event": "started"}\n{"event": "frame_do', encoding="utf-8")
        events, offset = commands.read_progress(path)
        self.assertEqual([event["event"] for event in events], ["started"])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('ne", "frame": 1}\n')
        events, offset = commands.read_progress(path, offset)
        self.assertEqual(events, [{"event": "frame_done", "frame": 1}])


if __name__ == "__main__":
    unittest.main()
