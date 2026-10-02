# tools/desktop/media/source.py
"""What was dropped on the Media tool, read and ready to show — Qt-free.

load_source() blocks (it asks ffprobe and makes a thumbnail with ffmpeg):
the page calls it on a worker thread.
"""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from msl_tools.msl.core.media import FfmpegTools, ImageSequence, MediaError, MediaInfo, find_sequences, probe, sequence_of
from msl_tools.msl.core.media.probe import AUDIO, IMAGE
from msl_tools.msl.core.media.sequence import IMAGE_SUFFIXES
from msl_tools.msl.core.media.thumbnail import thumbnail

AUDIO_SUFFIXES = (".wav", ".mp3", ".aac", ".m4a", ".ogg", ".flac", ".aif", ".aiff")
THUMBNAIL_WIDTH = 320


@dataclass
class MediaSource:
    """One thing to work on: a video file, or an image sequence.

    Attributes:
        path: The video file, or the folder of the sequence.
        info: The video — or, for a sequence, one of its frames (the frame size comes from it).
        sequence: The image sequence (None for a video).
        siblings: Every sequence of that folder, the chosen one included (for a chooser).
        thumbnail: A small picture of it (None if it couldn't be made).
    """

    path: Path
    info: MediaInfo
    sequence: ImageSequence | None = None
    siblings: list = field(default_factory=list)
    thumbnail: Path | None = None

    @property
    def is_sequence(self) -> bool:
        return self.sequence is not None

    def title(self) -> str:
        return self.sequence.name if self.sequence is not None else self.path.name

    def facts(self) -> str:
        """One line about it: "1920×1080 · 30 fps · 0:13.3 · 4.1 MB · h264 · sound"."""
        info = self.info
        if self.sequence is not None:
            parts = ["Image sequence", f"{self.sequence.count} frames", info.resolution_text(),
                     self.sequence.suffix.lstrip(".").upper()]
        else:
            parts = [info.resolution_text(), info.fps_text(), info.duration_text(), info.size_text(),
                     info.video_codec, "sound" if info.has_audio else "no sound"]
        return "  ·  ".join(part for part in parts if part)

    def warning(self) -> str:
        """What is wrong with it ("" = nothing)."""
        if self.sequence is not None and self.sequence.missing:
            count = len(self.sequence.missing)
            return f"{count} frame{'s are' if count != 1 else ' is'} missing: {self.sequence.missing_text()}"
        return ""


def load_source(tools: FfmpegTools, path: str | Path, chosen: ImageSequence | None = None) -> MediaSource:
    """Reads what `path` is: a video, a folder of frames, or one frame of a
    sequence (`chosen` picks one of a folder's sequences). Raises MediaError
    with a message for the user when it is nothing the tool works on."""
    path = Path(path)
    if chosen is not None:
        sequence, siblings = chosen, find_sequences(chosen.folder)
    elif path.is_dir():
        siblings = find_sequences(path)
        if not siblings:
            raise MediaError(f"No image sequence in “{path.name}” — it needs numbered pictures like shot.0001.png.")
        sequence = siblings[0]
    elif path.suffix.lower() in IMAGE_SUFFIXES:
        sequence = sequence_of(path)
        if sequence is None:
            raise MediaError(f"“{path.name}” is one picture, not a frame of a sequence.")
        siblings = find_sequences(path.parent)
    elif path.suffix.lower() in AUDIO_SUFFIXES:
        raise MediaError(f"“{path.name}” is sound. Drop a video or an image sequence first — "
                         f"sound can then be put under a sequence.")
    else:
        info = probe(tools, path)
        if info.kind == AUDIO:
            raise MediaError(f"“{path.name}” is sound, not a video.")
        if info.kind == IMAGE:
            raise MediaError(f"“{path.name}” is one picture, not a video.")
        return MediaSource(path=path, info=info, thumbnail=_thumbnail(tools, info))

    frame = sequence.file(sequence.frames[len(sequence.frames) // 2])
    info = probe(tools, frame)
    return MediaSource(path=sequence.folder, info=info, sequence=sequence, siblings=siblings,
                       thumbnail=_thumbnail(tools, info))


def _thumbnail(tools: FfmpegTools, info: MediaInfo) -> Path | None:
    """A cached thumbnail of `info` in the temp folder (the name follows the
    file and its change time, so an edited file gets a new one)."""
    try:
        stamp = f"{info.path}|{info.path.stat().st_mtime_ns}|{THUMBNAIL_WIDTH}"
    except OSError:
        return None
    folder = Path(tempfile.gettempdir()) / "msl_tools" / "media" / "thumbs"
    target = folder / (hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:20] + ".jpg")
    if target.is_file():
        return target
    return thumbnail(tools, info, target, THUMBNAIL_WIDTH)


def parse_time(text: str) -> float | None:
    """"12.5", "0:12.5", "1:02:03" -> seconds; None if it isn't a time."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        parts = [float(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) > 3 or any(part < 0 for part in parts):
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def format_time(seconds: float) -> str:
    """12.5 -> "0:12.5"; 125 -> "2:05"; 3725.25 -> "1:02:05.25"."""
    seconds = max(float(seconds), 0.0)
    whole = int(seconds)
    rest = f"{seconds - whole:.3f}".rstrip("0").rstrip(".")[1:]  # ".5", ".25", ""
    hours, minutes, secs = whole // 3600, whole % 3600 // 60, whole % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}{rest}"
    return f"{minutes}:{secs:02d}{rest}"
