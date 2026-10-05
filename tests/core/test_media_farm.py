"""Media's names from templates (core/media/names.py), the watched render folder
(core/media/watch.py) and what a batch does when it is over (core/environment/system_actions.py —
with a fake command runner: a test must never reach the real shutdown)."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from msl_tools.msl.core.environment import system_actions
from msl_tools.msl.core.media import default_output, names
from msl_tools.msl.core.media.watch import FolderWatch

MOMENT = time.mktime((2026, 10, 5, 15, 42, 0, 0, 0, -1))


class Names(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def test_tokens_and_tidy_separators(self):
        self.assertEqual(names.expand("{name}_{action}_{date}", "shot", "_small", MOMENT), "shot_small_2026-10-05")
        self.assertEqual(names.expand("{name}_{action}_v{n}", "shot", "", MOMENT, 7), "shot_v007")
        self.assertEqual(names.expand("{name}_{time}", "a:b", "", MOMENT), "a_b_1542")  # nothing unsafe in a name
        self.assertEqual(names.unknown_tokens("{name}_{nmae}_{n}"), ["nmae"])

    def test_versions_count_past_the_highest_in_the_folder_and_queued(self):
        (self.folder / "shot_small_v003.mp4").write_text("x")
        (self.folder / "shot_small_v001.mov").write_text("x")      # another suffix: not counted
        path = names.result_path("{name}_{action}_v{n}", self.folder, "shot", "_small", ".mp4", moment=MOMENT)
        self.assertEqual(path.name, "shot_small_v004.mp4")
        taken = [self.folder / "shot_small_v004.mp4"]
        path = names.result_path("{name}_{action}_v{n}", self.folder, "shot", "_small", ".mp4", taken, MOMENT)
        self.assertEqual(path.name, "shot_small_v005.mp4")

    def test_without_n_a_taken_name_gets_a_counter(self):
        (self.folder / "shot_2026-10-05.mp4").write_text("x")
        path = names.result_path("{name}_{date}", self.folder, "shot", "_small", ".mp4", moment=MOMENT)
        self.assertEqual(path.name, "shot_2026-10-05_2.mp4")

    def test_no_template_keeps_the_classic_name(self):
        source = self.folder / "shot.mov"
        self.assertEqual(default_output(source, "_small", ".mp4").name, "shot_small.mp4")
        self.assertEqual(default_output(source, "_small", ".mp4", template="{name}_v{n}").name, "shot_v001.mp4")


class Watch(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.now = 0.0
        self.watch = FolderWatch(self.root, settle_seconds=5, clock=lambda: self.now)

    def frames(self, folder, numbers, prefix="beauty."):
        folder.mkdir(parents=True, exist_ok=True)
        for number in numbers:
            path = folder / f"{prefix}{number:04d}.png"
            path.write_bytes(b"png")
            os.utime(path, (1000 + number, 1000 + number))

    def scan(self, after):
        self.now += after
        return [sequence.prefix for sequence in self.watch.scan()]

    def test_what_is_there_at_the_start_is_left_alone(self):
        self.frames(self.root, range(1, 11))
        self.assertEqual(self.scan(0), [])
        self.assertEqual(self.scan(60), [])

    def test_a_new_sequence_is_ready_once_it_stays_quiet(self):
        self.assertEqual(self.scan(0), [])
        self.frames(self.root / "layer", range(1, 5))          # a sub-folder one level down
        self.assertEqual(self.scan(1), [])                     # first seen
        self.frames(self.root / "layer", range(5, 9))
        self.assertEqual(self.scan(1), [])                     # still growing
        self.assertEqual(self.scan(4), [])                     # quiet for 4 s only
        ready = self.watch.scan()
        self.assertEqual(ready, [])
        self.now += 2
        ready = self.watch.scan()
        self.assertEqual([sequence.count for sequence in ready], [8])
        self.watch.mark_made(ready[0])
        self.assertEqual(self.scan(30), [])                    # made: not again until it changes
        self.frames(self.root / "layer", range(9, 13))         # a re-render with more frames
        self.assertEqual(self.scan(1), [])
        self.assertEqual(self.scan(6), ["beauty."])

    def test_a_sequence_that_was_there_and_grows_is_ready(self):
        self.frames(self.root, range(1, 5))
        self.scan(0)
        self.frames(self.root, range(5, 7))
        self.assertEqual(self.scan(1), [])
        self.assertEqual(self.scan(6), ["beauty."])


class SystemActions(unittest.TestCase):
    def test_shutdown_and_cancel_go_through_the_runner(self):
        calls = []

        def run(command):
            calls.append(command)
            return True

        self.assertTrue(system_actions.schedule_shutdown(90, "done", run=run))
        self.assertTrue(system_actions.cancel_shutdown(run=run))
        self.assertEqual(calls, [["shutdown", "/s", "/t", "90", "/c", "done"], ["shutdown", "/a"]])

    def test_a_refused_shutdown_says_so(self):
        self.assertFalse(system_actions.schedule_shutdown(90, run=lambda command: False))


if __name__ == "__main__":
    unittest.main()
