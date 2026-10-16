"""core/batch/stages.py: where a render job stands, as the CURRENT RENDER card's steps."""
import unittest

from msl_tools.msl.core.batch.job import CHECKING, DONE, FAILED, RUNNING, WAITING, BatchJob
from msl_tools.msl.core.batch.stages import stage_of, steps_of


def _job(**values) -> BatchJob:
    job = BatchJob(scene="C:/shots/sh010.ma")
    for name, value in values.items():
        setattr(job, name, value)
    return job


class StagesTest(unittest.TestCase):
    def test_the_video_step_only_when_it_makes_one(self):
        self.assertEqual(steps_of(_job()), ["Read", "Open", "Render", "Video"])
        self.assertEqual(steps_of(_job(make_video=False)), ["Read", "Open", "Render"])

    def test_reading_opening_rendering(self):
        self.assertEqual(stage_of(_job(state=CHECKING)), (0, "running"))
        self.assertEqual(stage_of(_job(state=WAITING)), (0, "waiting"))
        self.assertEqual(stage_of(_job(state=WAITING, probe={"cameras": []})), (1, "waiting"))
        self.assertEqual(stage_of(_job(state=RUNNING, probe={"x": 1}, message="starting Maya 2024")), (1, "running"))
        self.assertEqual(stage_of(_job(state=RUNNING, probe={"x": 1}, message="frame 3 of 48")), (2, "running"))
        self.assertEqual(stage_of(_job(state=RUNNING, probe={"x": 1}, done=[1, 2])), (2, "running"))

    def test_the_video_and_the_end(self):
        rendered = dict(state=DONE, probe={"x": 1}, done=[1, 2])
        self.assertEqual(stage_of(_job(**rendered), making_video=True), (3, "running"))
        self.assertEqual(stage_of(_job(**rendered, video="C:/sh010.mp4")), (4, "done"))
        self.assertEqual(stage_of(_job(**rendered, message="done · the video failed: x")), (3, "error"))
        self.assertEqual(stage_of(_job(**rendered, make_video=False)), (3, "done"))

    def test_a_failure_at_the_step_it_happened(self):
        self.assertEqual(stage_of(_job(state=FAILED)), (0, "error"))
        self.assertEqual(stage_of(_job(state=FAILED, probe={"x": 1})), (1, "error"))
        self.assertEqual(stage_of(_job(state=FAILED, probe={"x": 1}, done=[1])), (2, "error"))


if __name__ == "__main__":
    unittest.main()
