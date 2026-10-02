# core/media/recipes.py
"""What ffmpeg is asked to do: each recipe turns a task in plain terms
("these frames into a video", "make it smaller", "cut this piece") into a
Job — the exact arguments — Qt-free and without running anything.

The traps of ffmpeg are handled here once, so no caller has to know them
(all measured with ffmpeg 8.0):
- frames whose numbering doesn't start near 0 need `-start_number`;
- a GAP in the numbering makes ffmpeg stop there and report success — a
  sequence with gaps is refused, or its gaps are filled by holding the
  frame before them;
- an odd frame width / height can't be encoded as yuv420p — sizes are
  rounded down to even;
- `-pix_fmt yuv420p` + `+faststart`: the file plays everywhere, and starts
  playing before it is fully downloaded;
- sound shorter than the picture is padded with silence, longer is cut.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from msl_tools.msl.core.media.ffmpeg import FfmpegTools, MediaError
from msl_tools.msl.core.media.probe import MediaInfo
from msl_tools.msl.core.media.sequence import ImageSequence

# Flags every run gets (the runners add them): quiet, never waiting for a key, progress as
# key=value on stdout, overwrite without asking (the output name was chosen not to clash).
GLOBAL_FLAGS = ["-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1", "-y"]

# Picture quality in words -> x264's CRF (lower = better and bigger).
QUALITY = {"best": 16, "high": 19, "good": 22, "small": 26, "smallest": 30}
# How long encoding may take -> x264's preset (slower = smaller file at the same quality).
SPEED = {"fast": "veryfast", "balanced": "medium", "compact": "slow"}
AUDIO_KBPS = 96
MIN_VIDEO_KBPS = 60     # below this a picture is not worth sending
GAPS_ERROR, GAPS_HOLD = "error", "hold"
_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


@dataclass
class Job:
    """One task for ffmpeg, ready to run.

    Attributes:
        title: What it does, for a list of jobs ("img_seq.[0001-0210].png → img_seq.mp4").
        output: The file it writes.
        passes: The arguments of each ffmpeg run, in order, without the
            program and GLOBAL_FLAGS (two runs for "fit into N MB").
        duration: Seconds of the result (for a progress bar; 0 = unknown).
        frames: Frames of the result (0 = unknown).
        temporary: Files the job needs while it runs; removed afterwards.
    """

    title: str
    output: Path
    passes: list[list[str]]
    duration: float = 0.0
    frames: int = 0
    temporary: list[Path] = field(default_factory=list)

    def commands(self, tools: FfmpegTools) -> list[list[str]]:
        """The full command line of every run."""
        return [[str(tools.ffmpeg), *GLOBAL_FLAGS, *arguments] for arguments in self.passes]

    def command_text(self, tools: FfmpegTools | None = None) -> str:
        """The commands as one would type them (for "Show command"), without the flags only a program needs."""
        program = str(tools.ffmpeg) if tools is not None else "ffmpeg"
        return chr(10).join(subprocess.list2cmdline([program, "-y", *arguments]) for arguments in self.passes)


def sequence_to_video(sequence: ImageSequence, output: str | Path, fps: float = 24.0, quality: str = "good",
                      speed: str = "balanced", audio: str | Path | None = None, gaps: str = GAPS_ERROR,
                      work_dir: str | Path | None = None) -> Job:
    """The frames of `sequence` as an H.264 .mp4 at `fps`, with `audio` under it if given.

    `gaps`: GAPS_ERROR refuses a sequence with missing frames (MediaError
    names them); GAPS_HOLD shows the frame before a gap for as long as the
    gap lasts, so the timing stays right.
    """
    output = Path(output)
    missing = sequence.missing
    temporary: list[Path] = []
    filters = [_EVEN]
    if not missing:
        source = ["-framerate", _number(fps), "-start_number", str(sequence.first), "-i", sequence.pattern_path]
    elif gaps == GAPS_HOLD:
        listing = _hold_list(sequence, fps, work_dir)
        temporary.append(listing)
        source = ["-f", "concat", "-safe", "0", "-i", str(listing)]
        filters.append(f"fps={_number(fps)}")  # every listed frame is shown for its time, at a constant rate
    else:
        raise MediaError(f"{len(missing)} frame(s) of {sequence.name} are missing: {sequence.missing_text()}.")
    frames = sequence.last - sequence.first + 1
    arguments = list(source)
    if audio:
        arguments += ["-i", str(audio)]
    arguments += ["-vf", ",".join(filters), *_video(quality, speed)]
    if missing:
        arguments += ["-frames:v", str(frames)]  # the list ends with its last frame twice (see _hold_list)
    if audio:
        # shorter sound is padded with silence, longer is cut at the last frame
        arguments += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-af", "apad", "-shortest"]
    arguments += ["-movflags", "+faststart", str(output)]
    return Job(title=f"{sequence.name} → {output.name}", output=output, passes=[arguments],
               duration=frames / fps if fps else 0.0, frames=frames, temporary=temporary)


def shrink(info: MediaInfo, output: str | Path, max_height: int = 720, quality: str = "small",
           target_mb: float | None = None, speed: str = "balanced", keep_audio: bool = True,
           work_dir: str | Path | None = None) -> Job:
    """A smaller copy of a video for sending: scaled down to `max_height`
    (never up) and re-encoded — at `quality`, or, with `target_mb`, to fit
    that many megabytes (two runs; lands within a few percent)."""
    output = Path(output)
    if not info.duration or not info.width:
        raise MediaError(f"{info.path.name} isn’t a video.")
    scale = f"scale=-2:{int(max_height) // 2 * 2}" if max_height and info.height > max_height else _EVEN
    sound = ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"] if info.has_audio and keep_audio else ["-an"]
    title = f"{info.path.name} → {output.name}"
    if target_mb is None:
        arguments = ["-i", str(info.path), "-vf", scale, *_video(quality, speed), *sound,
                     "-movflags", "+faststart", str(output)]
        return Job(title=title, output=output, passes=[arguments], duration=info.duration, frames=info.frames)

    kbps = int(float(target_mb) * 8 * 1024 / info.duration) - (AUDIO_KBPS if sound[0] != "-an" else 0)
    if kbps < MIN_VIDEO_KBPS:
        smallest = (MIN_VIDEO_KBPS + AUDIO_KBPS) * info.duration / 8 / 1024
        raise MediaError(f"{target_mb:g} MB is too little for {info.duration_text()} of video — "
                         f"ask for {smallest:.1f} MB or more, or trim it first.")
    folder = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "msl_tools" / "media"
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / f"pass_{os.getpid()}_{abs(hash(str(output))) % 10 ** 8}"
    common = ["-i", str(info.path), "-vf", scale, "-c:v", "libx264", "-b:v", f"{kbps}k",
              "-preset", SPEED.get(speed, SPEED["balanced"]), "-pix_fmt", "yuv420p", "-passlogfile", str(log)]
    first = common + ["-pass", "1", "-an", "-f", "null", os.devnull]
    second = common + ["-pass", "2", *sound, "-movflags", "+faststart", str(output)]
    return Job(title=title, output=output, passes=[first, second], duration=info.duration, frames=info.frames,
               temporary=[Path(f"{log}-0.log"), Path(f"{log}-0.log.mbtree")])


def trim(info: MediaInfo, output: str | Path, start: float, end: float, exact: bool = True,
         quality: str = "high", speed: str = "balanced") -> Job:
    """The piece of a video from `start` to `end` (seconds).

    exact=True re-encodes: the cut is where it was asked, to the frame.
    exact=False copies the streams: instant and lossless, but the cut can
    only start on a keyframe — it begins a little early and runs a little
    long (measured: 3.1 s for a 3.0 s request)."""
    output = Path(output)
    start, end = max(float(start), 0.0), float(end)
    if info.duration and end > info.duration:
        end = info.duration
    if end - start <= 0:
        raise MediaError("The end of the cut must be after its start.")
    arguments = ["-ss", _number(start), "-to", _number(end), "-i", str(info.path)]
    if exact:
        arguments += ["-vf", _EVEN, *_video(quality, speed)]
        arguments += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"] if info.has_audio else ["-an"]
    else:
        arguments += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    arguments += ["-movflags", "+faststart", str(output)]
    length = end - start
    return Job(title=f"{info.path.name} [{_number(start)}–{_number(end)} s] → {output.name}", output=output,
               passes=[arguments], duration=length, frames=int(round(length * info.fps)) if info.fps else 0)


def default_output(source: str | Path | ImageSequence, tag: str = "", suffix: str = ".mp4",
                   folder: str | Path | None = None, taken=()) -> Path:
    """A name for the result that clashes with nothing: next to the source
    (a sequence's video goes NEXT TO its frames' folder, not among the
    frames), named after it + `tag`; "_2", "_3", ... if that name is taken —
    by a file, or by one of `taken` (results of jobs that haven't run yet)."""
    taken = {Path(path) for path in taken}
    if isinstance(source, ImageSequence):
        stem = source.prefix.rstrip("._- ") or source.folder.name
        home = source.folder.parent
    else:
        source = Path(source)
        stem, home = source.stem, source.parent
    home = Path(folder) if folder else home
    candidate = home / f"{stem}{tag}{suffix}"
    counter = 2
    while candidate.exists() or candidate in taken:
        candidate = home / f"{stem}{tag}_{counter}{suffix}"
        counter += 1
    return candidate


def _video(quality: str, speed: str) -> list[str]:
    return ["-c:v", "libx264", "-crf", str(QUALITY.get(quality, QUALITY["good"])),
            "-preset", SPEED.get(speed, SPEED["balanced"]), "-pix_fmt", "yuv420p"]


def _number(value: float) -> str:
    """12.0 -> "12", 2.5 -> "2.5", 29.97002997 -> "29.97003"."""
    return f"{float(value):.5f}".rstrip("0").rstrip(".")


def _hold_list(sequence: ImageSequence, fps: float, work_dir: str | Path | None) -> Path:
    """Writes the list ffmpeg's concat reader takes for a sequence with gaps:
    every frame that exists, shown until the next one that exists."""
    folder = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "msl_tools" / "media"
    folder.mkdir(parents=True, exist_ok=True)
    listing = folder / f"frames_{os.getpid()}_{abs(hash(sequence.pattern_path)) % 10 ** 8}.txt"
    frames = list(sequence.frames)
    lines = []
    for index, frame in enumerate(frames):
        shown = (frames[index + 1] - frame) if index + 1 < len(frames) else 1
        lines.append(f"file '{_listed(sequence.file(frame))}'")
        lines.append(f"duration {shown / fps:.6f}")
    lines.append(f"file '{_listed(sequence.file(frames[-1]))}'")  # the reader drops the last duration otherwise
    listing.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    return listing


def _listed(path: Path) -> str:
    """A path as a concat list wants it: forward slashes, a quote written as '\\''."""
    return path.as_posix().replace("'", "'" + chr(92) + "''")
