# core/media/run.py
"""Running a Job and following it — Qt-free.

ProgressParser reads what ffmpeg prints with `-progress pipe:1`; run_job()
runs a Job to its end in the calling thread (for scripts, tests and
headless work); estimate() guesses a job's size and time, preview() makes
a few seconds of it to look at. A window uses ui/media/ffmpeg_runner.py instead, which
never blocks — both share the parser and the helpers below.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from msl_tools.msl.core.media.ffmpeg import FfmpegTools, MediaError, run_quiet
from msl_tools.msl.core.media.probe import probe
from msl_tools.msl.core.media.recipes import Job


@dataclass(frozen=True)
class Progress:
    """Where one ffmpeg run is.

    Attributes:
        frame: Frames written so far.
        seconds: Seconds of output written so far.
        speed: Times faster than real time (0 = not known yet).
        done: This run has finished.
    """

    frame: int = 0
    seconds: float = 0.0
    speed: float = 0.0
    done: bool = False


class ProgressParser:
    """Turns ffmpeg's `-progress` output (blocks of key=value lines, each
    ending with a `progress=` line) into Progress objects. Feed it whatever
    arrived, in any chunking."""

    def __init__(self) -> None:
        self._tail = ""
        self._block: dict[str, str] = {}

    def feed(self, text: str) -> list[Progress]:
        lines = (self._tail + text).split(chr(10))
        self._tail = lines.pop()
        reports = []
        for line in lines:
            key, _, value = line.strip().partition("=")
            if not key:
                continue
            self._block[key] = value.strip()
            if key == "progress":
                reports.append(self._report(self._block))
                self._block = {}
        return reports

    @staticmethod
    def _report(block: dict) -> Progress:
        def number(key: str) -> float:
            try:
                return float(block.get(key, "").rstrip("x"))
            except ValueError:
                return 0.0

        # out_time_us is microseconds; out_time_ms too (an old misnomer ffmpeg keeps)
        micro = number("out_time_us") or number("out_time_ms")
        return Progress(frame=int(number("frame")), seconds=max(micro / 1_000_000, 0.0),
                        speed=number("speed"), done=block.get("progress") == "end")


def fraction(job: Job, run_index: int, progress: Progress) -> float:
    """How much of the whole job is done, 0..1 (-1 when its length isn't known)."""
    if progress.done:
        part = 1.0
    elif job.duration > 0:
        part = min(progress.seconds / job.duration, 1.0)
    elif job.frames > 0:
        part = min(progress.frame / job.frames, 1.0)
    else:
        return -1.0
    return (run_index + part) / max(len(job.passes), 1)


def error_summary(text: str) -> str:
    """The line of ffmpeg's error output that says what went wrong."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        plain = line.split("] ", 1)[-1] if line.startswith("[") else line
        if not plain.startswith(("Conversion failed", "Exiting", "Terminating thread", "Task finished")):
            return plain
    return lines[-1] if lines else "ffmpeg stopped without saying why."


def prepare(job: Job) -> None:
    """Makes the folders a job writes into (ffmpeg creates none). Raises OSError if it can't."""
    job.output.parent.mkdir(parents=True, exist_ok=True)
    if job.folder is not None:
        job.folder_was_new = not job.folder.exists()
        job.folder.mkdir(parents=True, exist_ok=True)


def clean_up(job: Job, remove_output: bool) -> None:
    """Removes the job's temporary files — and its output, when the job
    failed or was cancelled. A folder of frames is only taken away if this
    job created it: one that was there before may hold other files."""
    for path in list(job.temporary):
        try:
            Path(path).unlink()
        except OSError:
            pass
    if not remove_output:
        return
    if job.folder is not None:
        if job.folder_was_new:
            shutil.rmtree(job.folder, ignore_errors=True)
        return
    try:
        job.output.unlink()
    except OSError:
        pass


@dataclass(frozen=True)
class Estimate:
    """What a job is expected to produce.

    Attributes:
        size: Bytes of the result (0 = unknown).
        seconds: How long the job will take (0 = unknown).
    """

    size: int = 0
    seconds: float = 0.0

    def text(self) -> str:
        """"≈ 4.1 MB  ·  ≈ 6 s" ("" when nothing is known)."""
        parts = []
        if self.size:
            megabytes = self.size / 1024 ** 2
            parts.append(f"≈ {megabytes:.1f} MB" if megabytes >= 1 else f"≈ {self.size / 1024:.0f} KB")
        if self.seconds:
            parts.append(f"≈ {self.seconds:.0f} s" if self.seconds < 90 else f"≈ {self.seconds / 60:.0f} min")
        return "  ·  ".join(parts)


PREVIEW_SECONDS = 3.0    # how much of a job a preview shows
STARTUP_SECONDS = 0.7    # what starting ffmpeg costs on top of the encoding itself
KEYFRAME_EVERY = 250     # x264's default: one full picture, then up to this many that only hold changes


def estimate(tools: FfmpegTools, job: Job) -> Estimate | None:
    """Encodes the job's short sample (a second or two from its middle) and
    scales the result up to the whole job: its size and its time. Blocks for
    about as long as the sample takes — call it from a worker thread.
    None when the job has no sample (it is instant, or can't be sampled) or
    the sample failed.

    Two things keep a short sample honest: the time comes from the speed
    ffmpeg itself reports (starting the program isn't encoding), and the
    sample's full pictures (key frames) are counted apart from the frames
    that only hold changes — a sample always starts with a key frame, which
    a real video has once in a few hundred frames."""
    if not job.sample or not job.duration:
        return Estimate(size=job.expected_size) if job.expected_size else None
    try:
        length = min(float(job.sample[-1]), job.duration)
    except (ValueError, IndexError):
        return None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    handle, name = tempfile.mkstemp(suffix=job.output.suffix or ".mp4", prefix="msl_sample_")
    os.close(handle)
    try:
        done = subprocess.run([str(tools.ffmpeg), "-hide_banner", "-nostdin", "-nostats", "-v", "error", "-progress",
                               "pipe:1", "-y", *job.sample, name], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                              timeout=60, creationflags=flags)
        if done.returncode != 0:
            return None
        reports = ProgressParser().feed(done.stdout or "")
        speed = next((report.speed for report in reversed(reports) if report.speed > 0), 0.0)
        size = job.expected_size or _whole_size(tools, name, length, job)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.remove(name)
        except OSError:
            pass
    runs = 1.7 if len(job.passes) > 1 else 1.0  # the first of two passes writes nothing and is quicker
    seconds = job.duration / speed * runs + STARTUP_SECONDS * len(job.passes) if speed else 0.0
    return Estimate(size=size, seconds=seconds)


def preview_arguments(job: Job, seconds: float = PREVIEW_SECONDS) -> list[str]:
    """The arguments (without an output) that make a short piece of what
    `job` would make, with the job's own settings: its sample — from the
    middle — stretched to `seconds`, or, for a job without one, the start
    of the job itself. [] for a job that can't be previewed (it writes a
    folder of files)."""
    if job.folder is not None or not job.passes:
        return []
    arguments = list(job.sample) if job.sample else list(job.passes[-1][:-1])
    length = f"{min(seconds, job.duration) if job.duration else seconds:.3f}"
    if len(arguments) >= 2 and arguments[-2] == "-t":
        arguments[-1] = length
    else:
        arguments += ["-t", length]
    return arguments


def preview(tools: FfmpegTools, job: Job, target: str | Path, seconds: float = PREVIEW_SECONDS) -> Path:
    """Writes a short piece of what `job` would make into `target` (see
    preview_arguments) and returns it. Blocks — call it from a worker
    thread. Raises MediaError if the job has no preview or ffmpeg fails."""
    target = Path(target)
    arguments = preview_arguments(job, seconds)
    if not arguments:
        raise MediaError("This action has nothing to preview.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errors:
            done = subprocess.run([str(tools.ffmpeg), "-hide_banner", "-nostdin", "-nostats", "-y", *arguments,
                                   str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                                  timeout=600, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            errors.seek(0)
            if done.returncode != 0:
                raise MediaError(error_summary(errors.read()))
    except subprocess.TimeoutExpired as error:
        raise MediaError("The preview took too long.") from error
    except OSError as error:
        raise MediaError(f"The preview couldn’t be made: {error}") from error
    return target


def quality_crops(tools: FfmpegTools, job: Job, info, folder: str | Path, tag: str,
                  size: tuple = (176, 99)) -> tuple:
    """Before / after at the pixel: the same moment of the source and of what
    `job` would make (a short piece of it is encoded with the job's own
    settings), each cut to the middle `size` (width, height) of the RESULT's
    frame at 1:1 — the source scaled to the result's frame size first — so
    blur and blocks show as they will. Returns (source picture, result
    picture). Blocks — call it from a worker thread; raises MediaError."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    encoded = preview(tools, job, folder / f"{tag}_piece{job.output.suffix or '.mp4'}", seconds=0.8)
    result = probe(tools, encoded)
    width, height = (min(int(size[0]), result.width) // 2 * 2, min(int(size[1]), result.height) // 2 * 2)
    crop = f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2"
    start = float(job.sample[1]) if len(job.sample) > 1 and job.sample[0] == "-ss" else 0.0
    at = 0.4  # into the piece: past its very first frame (a key frame, the best one)
    after, before = folder / f"{tag}_after.png", folder / f"{tag}_before.png"
    for command in ([str(tools.ffmpeg), "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i",
                     str(encoded), "-frames:v", "1", "-update", "1", "-vf", crop, str(after)],
                    [str(tools.ffmpeg), "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss", f"{start + at:.3f}",
                     "-i", str(info.path), "-frames:v", "1", "-update", "1", "-vf",
                     f"scale={result.width}:{result.height},{crop}", str(before)]):
        done = run_quiet(command, timeout=60)  # UTF-8: ffmpeg's messages aren't in the system's code page
        if done.returncode != 0:
            raise MediaError(error_summary(done.stderr))
    try:
        encoded.unlink()
    except OSError:
        pass
    return before, after


def _whole_size(tools: FfmpegTools, sample: str, length: float, job: Job) -> int:
    """Bytes the whole job will come to, from its encoded sample."""
    total = os.path.getsize(sample)
    plain = int(total / length * job.duration)
    try:
        listing = run_quiet([str(tools.ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "packet=size,flags", "-of", "csv=p=0", sample], timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return plain
    key_bytes = key_count = other_bytes = other_count = 0
    for line in listing.splitlines():
        size, _, kind = line.partition(",")
        if not size.strip().isdigit():
            continue
        if "K" in kind:
            key_bytes, key_count = key_bytes + int(size), key_count + 1
        else:
            other_bytes, other_count = other_bytes + int(size), other_count + 1
    if not key_count or not other_count:
        return plain  # every frame is a full picture (ProRes, DNxHR): the sample scales as it is
    frames = (key_count + other_count) / length * job.duration
    changed, full = other_bytes / other_count, key_bytes / key_count
    picture = frames * changed + (frames / KEYFRAME_EVERY + 1) * max(full - changed, 0)
    rest = max(total - key_bytes - other_bytes, 0) / length * job.duration  # the sound and the container
    return int(picture + rest)


def run_job(tools: FfmpegTools, job: Job, on_progress=None, should_cancel=None) -> None:
    """Runs `job` to its end. `on_progress(fraction, Progress)` is called as
    it advances; `should_cancel()` returning True stops it. Raises
    MediaError when ffmpeg fails or the job is cancelled — the half-written
    output is removed then."""
    prepare(job)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        for index, command in enumerate(job.commands(tools)):
            parser = ProgressParser()
            # stderr goes to a file: a pipe nobody reads fills up and ffmpeg stops forever
            # `with` closes ffmpeg's stdout pipe afterwards (left open, one handle leaked per run)
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errors, \
                    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                                     text=True, encoding="utf-8", errors="replace", creationflags=flags) as process:
                for line in process.stdout:
                    for report in parser.feed(line):
                        if on_progress is not None:
                            on_progress(fraction(job, index, report), report)
                    if should_cancel is not None and should_cancel():
                        process.kill()
                        process.wait()
                        raise MediaError("Cancelled.")
                code = process.wait()
                errors.seek(0)
                if code != 0:
                    raise MediaError(error_summary(errors.read()))
    except BaseException:
        clean_up(job, remove_output=True)
        raise
    clean_up(job, remove_output=False)
