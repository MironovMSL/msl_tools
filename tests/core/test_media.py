"""core/media + the Media tool's Qt-free helpers: what goes into ffmpeg's arguments.
No ffmpeg is needed — the jobs are built, not run."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from msl_tools.msl.core.media import recipes
from msl_tools.msl.core.media.probe import MediaInfo
from msl_tools.msl.core.media.recipes import GAPS_HOLD, Overlays, sequence_to_video, stamp, to_frames
from msl_tools.msl.core.media.run import clean_up
from msl_tools.msl.core.media.sequence import ImageSequence, find_sequences, pattern_in
from msl_tools.msl.tools.desktop.media.source import format_time, parse_time, prune_temp


class _Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def frames(self, folder: Path, numbers, name="shot.", suffix=".png") -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        for number in numbers:
            (folder / f"{name}{number:04d}{suffix}").write_bytes(b"")
        return folder


class Sequences(_Temp):
    def test_percent_in_the_folder_is_doubled(self):
        # Measured with 7.1.1 + 8.0: "50%_scale/f.%04d.png" -> No such file; "50%%_scale/..." reads.
        folder = self.frames(self.folder / "50%_scale", range(1, 4))
        [sequence] = find_sequences(folder)
        self.assertEqual(sequence.pattern_path, str(self.folder / "50%%_scale") + os.sep + "shot.%04d.png")
        self.assertEqual(pattern_in("C:/a%b", "x.%d.png"), "C:/a%%b" + os.sep + "x.%d.png")

    def test_percent_in_the_name_is_doubled_once(self):
        folder = self.frames(self.folder / "plain", range(1, 3), name="100%_shot.")
        [sequence] = find_sequences(folder)
        self.assertTrue(sequence.pattern_path.endswith("100%%_shot.%04d.png"))

    def test_writing_into_a_percent_folder(self):
        info = MediaInfo(path=self.folder / "clip.mp4", duration=2.0, width=64, height=48, fps=24.0)
        job = to_frames(info, self.folder / "out 50%")
        self.assertIn(str(self.folder / "out 50%%") + os.sep + "clip.%04d.png", job.passes[0])
        self.assertEqual(job.output, self.folder / "out 50%")  # the real folder, not the pattern

    def test_missing_frames_worked_out_once(self):
        sequence = ImageSequence(folder=self.folder, prefix="x_", suffix=".png", padding=0, frames=(1, 3, 6))
        self.assertEqual(sequence.missing, [2, 4, 5])
        self.assertIs(sequence.missing, sequence.missing)
        self.assertEqual(sequence.missing_text(), "2, 4, 5")


class FilterValues(unittest.TestCase):
    def test_drive_colon_and_slashes(self):
        self.assertEqual(recipes._value(r"C:\Temp\t.txt"), r"'C\:/Temp/t.txt'")

    def test_apostrophe(self):
        # Measured with 7.1.1 + 8.0: close the quote, \\\' , open it again; one backslash fails.
        self.assertEqual(recipes._value(r"C:\Users\O'Brien\t.txt"), "'C\\:/Users/O'\\\\\\''Brien/t.txt'")


class TemporaryFiles(_Temp):
    def test_each_frame_list_is_a_file_of_its_own(self):
        # Before: one name per sequence — the estimate deleted the list a waiting job still needed.
        folder = self.frames(self.folder / "gaps", (1, 2, 5))
        [sequence] = find_sequences(folder)
        work = self.folder / "work"
        first = sequence_to_video(sequence, self.folder / "a.mp4", gaps=GAPS_HOLD, work_dir=work)
        second = sequence_to_video(sequence, self.folder / "b.mp4", gaps=GAPS_HOLD, work_dir=work)
        lists = [path for job in (first, second) for path in job.temporary if Path(path).name.startswith("frames_")]
        self.assertEqual(len(lists), 2)
        self.assertNotEqual(lists[0], lists[1])
        clean_up(second, remove_output=False)  # what the estimate does with its throwaway job
        self.assertTrue(Path(lists[0]).is_file())

    def test_text_files_are_unique(self):
        names = {recipes._text_file("x", self.folder).name for _ in range(50)}
        self.assertEqual(len(names), 50)

    def test_stamp_label_file_is_temporary(self):
        info = MediaInfo(path=self.folder / "clip.mp4", duration=2.0, width=64, height=48, fps=24.0)
        job = stamp(info, self.folder / "out.mp4", Overlays(label="O'Brien: shot 10"), work_dir=self.folder)
        texts = [Path(path) for path in job.temporary]
        self.assertTrue(texts and all(path.is_file() for path in texts))
        self.assertEqual(texts[0].read_text(encoding="utf-8"), "O'Brien: shot 10")  # written as it is, no escaping

    def test_prune_temp_keeps_recent_files(self):
        old, new = self.folder / "preview" / "old.mp4", self.folder / "thumbs" / "new.jpg"
        for path in (old, new):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        week_ago = time.time() - 8 * 86400
        os.utime(old, (week_ago, week_ago))
        self.assertEqual(prune_temp(root=self.folder), 1)
        self.assertFalse(old.exists())
        self.assertFalse(old.parent.exists())  # emptied folder goes too
        self.assertTrue(new.exists())


class Times(unittest.TestCase):
    def test_format(self):
        for seconds, text in ((12.5, "0:12.5"), (125, "2:05"), (3725.25, "1:02:05.25"), (0, "0:00")):
            self.assertEqual(format_time(seconds), text)

    def test_rounding_up_carries_into_the_seconds(self):
        # Before: 9.9997 -> "0:09" (the rounded-up fraction was dropped): Trim lost the last second.
        self.assertEqual(format_time(9.9997), "0:10")
        self.assertEqual(format_time(59.9999), "1:00")

    def test_parse(self):
        for text, seconds in (("12.5", 12.5), ("0:12,5", 12.5), ("1:02:03", 3723.0)):
            self.assertEqual(parse_time(text), seconds)

    def test_parse_refuses_what_is_no_time(self):
        for text in ("", "abc", "-1", "1:2:3:4", "nan", "inf", "1:nan"):
            self.assertIsNone(parse_time(text), text)

    def test_round_trip(self):
        for seconds in (0.04, 1.5, 61.25, 3599.999):
            self.assertAlmostEqual(parse_time(format_time(seconds)), seconds, places=3)


if __name__ == "__main__":
    unittest.main()
