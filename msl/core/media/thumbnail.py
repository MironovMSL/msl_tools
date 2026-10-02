# core/media/thumbnail.py
"""A small picture of a media file — Qt-free (asks ffmpeg; blocks for well under a second)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from msl_tools.msl.core.media.ffmpeg import FfmpegTools, run_quiet
from msl_tools.msl.core.media.probe import AUDIO, VIDEO, MediaInfo


def thumbnail(tools: FfmpegTools, info: MediaInfo, target: str | Path, width: int = 320) -> Path | None:
    """Writes a `width`-pixel-wide JPEG of `info` to `target`: the middle of
    a video, or the picture itself. Returns the file, or None when there is
    nothing to show (sound) or ffmpeg couldn't make it."""
    if info.kind == AUDIO:
        return None
    target = Path(target)
    arguments = [tools.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y"]
    if info.kind == VIDEO and info.duration > 0:
        arguments += ["-ss", f"{info.duration / 2:.3f}"]  # before -i: a fast seek, exact enough for a thumbnail
    arguments += ["-i", info.path, "-frames:v", "1", "-vf", f"scale={int(width)}:-2", "-q:v", "4", target]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        answer = run_quiet(arguments, timeout=30.0)
    except (OSError, subprocess.SubprocessError):
        return None
    return target if answer.returncode == 0 and target.is_file() else None


def frame_at(tools: FfmpegTools, info: MediaInfo, seconds: float, target: str | Path, width: int = 160) -> Path | None:
    """Writes the frame of a video at `seconds` to `target` as a small JPEG
    (a fast seek: the nearest frame ffmpeg can reach quickly, good to
    within a frame or two). None if it couldn't be made."""
    if info.kind != VIDEO:
        return None
    target = Path(target)
    seconds = min(max(float(seconds), 0.0), max(info.duration - 0.05, 0.0))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        answer = run_quiet([tools.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss", f"{seconds:.3f}",
                            "-i", info.path, "-frames:v", "1", "-vf", f"scale={int(width)}:-2", "-q:v", "5", target],
                           timeout=30.0)
    except (OSError, subprocess.SubprocessError):
        return None
    return target if answer.returncode == 0 and target.is_file() else None


def frames_at(tools: FfmpegTools, info: MediaInfo, times: list, folder: str | Path, prefix: str = "frame",
              width: int = 160) -> list:
    """The frames of a video at each of `times` (seconds) as small JPEGs in
    `folder` — all in ONE ffmpeg run (starting ffmpeg costs more than a
    seek). Returns a path per time, None where a frame couldn't be made."""
    if info.kind != VIDEO or not times:
        return [None] * len(times)
    folder = Path(folder)
    arguments = [tools.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y"]
    last = max(info.duration - 0.05, 0.0)
    for seconds in times:
        arguments += ["-ss", f"{min(max(float(seconds), 0.0), last):.3f}", "-i", info.path]
    targets = []
    for index in range(len(times)):
        target = folder / f"{prefix}_{index:03d}.jpg"
        targets.append(target)
        arguments += ["-map", f"{index}:v:0", "-frames:v", "1", "-vf", f"scale={int(width)}:-2", "-q:v", "5", target]
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for target in targets:
            if target.exists():
                target.unlink()
        run_quiet(arguments, timeout=60.0)
    except (OSError, subprocess.SubprocessError):
        pass
    return [target if target.is_file() else None for target in targets]
