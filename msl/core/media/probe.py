# core/media/probe.py
"""What a media file is: length, frame size, frame rate, codecs — Qt-free (asks ffprobe)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from msl_tools.msl.core.media.ffmpeg import FfmpegTools, MediaError, run_quiet

VIDEO, AUDIO, IMAGE = "video", "audio", "image"
_IMAGE_FORMATS = ("image2", "png_pipe", "jpeg_pipe", "tiff_pipe", "exr_pipe", "bmp_pipe", "webp_pipe", "tga_pipe")


@dataclass(frozen=True)
class MediaInfo:
    """One media file, as ffprobe sees it.

    Attributes:
        path: The file.
        kind: VIDEO, AUDIO or IMAGE (a single picture).
        duration: Seconds (0 for a picture).
        size: Bytes.
        width / height: Frame size (0 without a video stream).
        fps: Frames per second (0 if unknown).
        frames: Number of video frames (counted by the container, else duration x fps).
        video_codec / pixel_format: Of the first video stream ("" without one).
        audio_codec: Of the first audio stream ("" = no sound).
    """

    path: Path
    kind: str = VIDEO
    duration: float = 0.0
    size: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    frames: int = 0
    video_codec: str = ""
    pixel_format: str = ""
    audio_codec: str = ""

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_codec)

    def resolution_text(self) -> str:
        return f"{self.width}×{self.height}" if self.width and self.height else ""

    def fps_text(self) -> str:
        """"24 fps", "29.97 fps"."""
        if not self.fps:
            return ""
        return f"{self.fps:.2f}".rstrip("0").rstrip(".") + " fps"

    def duration_text(self) -> str:
        """"0:13.3", "2:05", "1:02:40"."""
        seconds = max(self.duration, 0.0)
        if seconds < 60:
            return f"0:{seconds:04.1f}"
        whole = int(round(seconds))
        hours, rest = divmod(whole, 3600)
        minutes, secs = divmod(rest, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    def size_text(self) -> str:
        megabytes = self.size / 1024 ** 2
        if megabytes < 1:
            return f"{self.size / 1024:.0f} KB"
        return f"{megabytes:.1f} MB" if megabytes < 1024 else f"{megabytes / 1024:.2f} GB"


def probe(tools: FfmpegTools, path: str | Path) -> MediaInfo:
    """Reads `path` with ffprobe. Raises MediaError if it isn't there or isn't media."""
    path = Path(path)
    if not path.is_file():
        raise MediaError(f"That file isn’t there: {path}")
    try:
        answer = run_quiet([tools.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path])
        data = json.loads(answer.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise MediaError(f"Couldn’t read {path.name}.") from error
    streams = data.get("streams") or []
    container = data.get("format") or {}
    if not streams:
        raise MediaError(f"{path.name} isn’t a video, a picture or a sound file ffmpeg can read.")
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)

    duration = _number(container.get("duration")) or _number((video or audio or {}).get("duration"))
    fps = _rate((video or {}).get("avg_frame_rate")) or _rate((video or {}).get("r_frame_rate"))
    frames = int(_number((video or {}).get("nb_frames"))) or (int(round(duration * fps)) if video else 0)
    picture = video is not None and audio is None and (
        str(container.get("format_name", "")) in _IMAGE_FORMATS or frames <= 1 and duration < 0.2)
    return MediaInfo(
        path=path,
        kind=IMAGE if picture else VIDEO if video is not None else AUDIO,
        duration=0.0 if picture else duration,
        size=int(_number(container.get("size"))) or path.stat().st_size,
        width=int(_number((video or {}).get("width"))), height=int(_number((video or {}).get("height"))),
        fps=0.0 if picture else fps, frames=1 if picture else frames,
        video_codec=str((video or {}).get("codec_name") or ""),
        pixel_format=str((video or {}).get("pix_fmt") or ""),
        audio_codec=str((audio or {}).get("codec_name") or ""))


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rate(value) -> float:
    """"30000/1001" -> 29.97; "0/0" or junk -> 0."""
    try:
        top, _, bottom = str(value).partition("/")
        bottom = float(bottom) if bottom else 1.0
        return float(top) / bottom if bottom else 0.0
    except (TypeError, ValueError):
        return 0.0
