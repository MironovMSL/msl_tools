# core/media/run.py
"""Running a Job and following it — Qt-free.

ProgressParser reads what ffmpeg prints with `-progress pipe:1`; run_job()
runs a Job to its end in the calling thread (for scripts, tests and
headless work). A window uses ui/media/ffmpeg_runner.py instead, which
never blocks — both share the parser and the helpers below.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from msl_tools.msl.core.media.ffmpeg import FfmpegTools, MediaError
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


def clean_up(job: Job, remove_output: bool) -> None:
    """Removes the job's temporary files — and its output, when the job failed or was cancelled."""
    for path in list(job.temporary) + ([job.output] if remove_output else []):
        try:
            Path(path).unlink()
        except OSError:
            pass


def run_job(tools: FfmpegTools, job: Job, on_progress=None, should_cancel=None) -> None:
    """Runs `job` to its end. `on_progress(fraction, Progress)` is called as
    it advances; `should_cancel()` returning True stops it. Raises
    MediaError when ffmpeg fails or the job is cancelled — the half-written
    output is removed then."""
    job.output.parent.mkdir(parents=True, exist_ok=True)  # ffmpeg doesn't create folders
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        for index, command in enumerate(job.commands(tools)):
            parser = ProgressParser()
            # stderr goes to a file: a pipe nobody reads fills up and ffmpeg stops forever
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errors:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                                           text=True, encoding="utf-8", errors="replace", creationflags=flags)
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
