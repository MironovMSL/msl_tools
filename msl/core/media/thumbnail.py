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
