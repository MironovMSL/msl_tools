# core/media/recipes.py
"""What ffmpeg is asked to do: each recipe turns a task in plain terms
("these frames into a video", "make it smaller", "cut this piece") into a
Job — the exact arguments — Qt-free and without running anything.

The traps of ffmpeg are handled here once, so no caller has to know them
(all measured with ffmpeg 8.0, the filters also with 7.1.1):
- frames whose numbering doesn't start near 0 need `-start_number`;
- a GAP in the numbering makes ffmpeg stop there and report success — a
  sequence with gaps is refused, or its gaps are filled by holding the
  frame before them;
- an odd frame width / height can't be encoded as yuv420p — sizes are
  rounded down to even;
- `-pix_fmt yuv420p` + `+faststart`: the file plays everywhere, and starts
  playing before it is fully downloaded;
- sound shorter than the picture is padded with silence, longer is cut;
- text drawn on the picture is passed as a FILE (`textfile=`,
  `expansion=none`): no character of it needs escaping. A path inside a
  filter is written quoted, forward slashes, the drive's colon escaped
  once (`'C\\:/Windows/Fonts/consola.ttf'`) — quoted AND escaped twice fails;
- clips of different sizes / rates are brought to one size and rate before
  they are joined or put side by side.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
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
# What the result is for -> (video codec arguments, sound codec arguments, file suffix).
# "mp4" is for watching and sending; the others keep much more of the picture, for editing.
FORMATS = {
    "mp4": (None, ["-c:a", "aac", "-b:a", "96k"], ".mp4"),
    "prores": (["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"],
               ["-c:a", "pcm_s16le"], ".mov"),
    "prores_hq": (["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"],
                  ["-c:a", "pcm_s16le"], ".mov"),
    "prores_4444": (["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", "-vendor", "apl0"],
                    ["-c:a", "pcm_s16le"], ".mov"),
    "dnxhr_hq": (["-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p"], ["-c:a", "pcm_s16le"], ".mov"),
}
# Still pictures a video can be taken apart into -> (arguments, file suffix).
IMAGE_FORMATS = {"png": ([], ".png"), "jpg": (["-q:v", "2"], ".jpg"), "tiff": ([], ".tif")}
JPG_QUALITY = {"best": 2, "good": 5, "small": 10}   # ffmpeg's -q:v for JPEG: 2 is the best, 31 the worst
SOUND_FORMATS = {"wav": (["-c:a", "pcm_s16le"], ".wav"), "mp3": (["-c:a", "libmp3lame", "-q:a", "2"], ".mp3"),
                 "m4a": (["-c:a", "aac", "-b:a", "192k"], ".m4a")}
AUDIO_KBPS = 96
MIN_VIDEO_KBPS = 60     # below this a picture is not worth sending
SAMPLE_SECONDS = 1.5    # how much of a job is encoded to estimate its size and time
LOOP_MEMORY = 1024 ** 3  # bytes of raw frames a "there and back" loop may hold at once (ffmpeg keeps them ~3 times)
GAPS_ERROR, GAPS_HOLD = "error", "hold"
_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
_FONTS = ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf",
          "/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")


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
        sample: Arguments of a short run from the middle of the job, WITHOUT
            its output — encoded once to estimate size and time ([] = no
            estimate: the job is instant, or its size can't be sampled).
        expected_size: Bytes the result will have when that is known in
            advance ("fit into N MB"); 0 otherwise.
        folder: Set when the job writes MANY files (frames) into a folder —
            `output` is then that folder. The runners create it, and take it
            away again after a failure only if they created it.
    """

    title: str
    output: Path
    passes: list[list[str]]
    duration: float = 0.0
    frames: int = 0
    temporary: list[Path] = field(default_factory=list)
    sample: list[str] = field(default_factory=list)
    expected_size: int = 0
    folder: Path | None = None
    folder_was_new: bool = False   # set by the runner: the folder didn't exist before this job

    def commands(self, tools: FfmpegTools) -> list[list[str]]:
        """The full command line of every run."""
        return [[str(tools.ffmpeg), *GLOBAL_FLAGS, *arguments] for arguments in self.passes]

    def command_text(self, tools: FfmpegTools | None = None) -> str:
        """The commands as one would type them (for "Show command"), without the flags only a program needs."""
        program = str(tools.ffmpeg) if tools is not None else "ffmpeg"
        return chr(10).join(subprocess.list2cmdline([program, "-y", *arguments]) for arguments in self.passes)


@dataclass
class Overlays:
    """What is drawn over the picture.

    Attributes:
        frame_number: The frame's number, bottom right (counted from `first_frame`).
        time: The time since the start (hours:minutes:seconds.ms), bottom centre.
        label: Free text, top left (a shot name, a version).
        date: Today's date, top right.
        first_frame: The number shown on the first frame.
        watermark: An image put into the bottom-right corner ("" = none).
        watermark_size: Its width, in percent of the frame's width.
        watermark_opacity: How solid it is, in percent.
    """

    frame_number: bool = False
    time: bool = False
    label: str = ""
    date: bool = False
    first_frame: int = 1
    watermark: str = ""
    watermark_size: int = 15
    watermark_opacity: int = 70

    def texts(self) -> bool:
        return bool(self.frame_number or self.time or self.label.strip() or self.date)

    def any(self) -> bool:
        return self.texts() or bool(self.watermark)


# --- the recipes ----------------------------------------------------------------------------------


def sequence_to_video(sequence: ImageSequence, output: str | Path, fps: float = 24.0, quality: str = "good",
                      speed: str = "balanced", audio: str | Path | None = None, gaps: str = GAPS_ERROR,
                      work_dir: str | Path | None = None, overlays: Overlays | None = None,
                      frame_size: tuple = (0, 0), video_format: str = "mp4") -> Job:
    """The frames of `sequence` as a video at `fps`, with `audio` under it if given.

    `gaps`: GAPS_ERROR refuses a sequence with missing frames (MediaError
    names them); GAPS_HOLD shows the frame before a gap for as long as the
    gap lasts, so the timing stays right.
    `overlays` draws burn-ins / a watermark (it needs `frame_size`, the
    frames' width and height). `video_format`: a key of FORMATS.
    """
    output = Path(output)
    missing = sequence.missing
    temporary: list[Path] = []
    filters = [_EVEN]
    middle = sequence.frames[len(sequence.frames) // 2]
    if not missing:
        source = ["-framerate", _number(fps), "-start_number", str(sequence.first), "-i", sequence.pattern_path]
        sample_source = ["-framerate", _number(fps), "-start_number", str(middle), "-i", sequence.pattern_path]
    elif gaps == GAPS_HOLD:
        listing = _hold_list(sequence, fps, work_dir)
        temporary.append(listing)
        source = sample_source = ["-f", "concat", "-safe", "0", "-i", str(listing)]
        filters.append(f"fps={_number(fps)}")  # every listed frame is shown for its time, at a constant rate
    else:
        raise MediaError(f"{len(missing)} frame(s) of {sequence.name} are missing: {sequence.missing_text()}.")
    frames = sequence.last - sequence.first + 1
    if overlays is not None:
        overlays.first_frame = sequence.first
    inputs = [source] + ([["-i", str(audio)]] if audio else [])
    picture, more = _picture(inputs, filters, overlays, frame_size, work_dir)
    temporary += more
    video_codec, sound_codec, _suffix = FORMATS.get(video_format, FORMATS["mp4"])
    tail = list(video_codec) if video_codec else _video(quality, speed)
    if missing:
        tail += ["-frames:v", str(frames)]  # the list ends with its last frame twice (see _hold_list)
    if audio:
        # shorter sound is padded with silence, longer is cut at the last frame
        tail += ["-map", "1:a"] if "-map" in picture else []
        tail += [*sound_codec, "-af", "apad", "-shortest"]
    tail += ["-movflags", "+faststart"]
    arguments = _flat(inputs) + picture + tail + [str(output)]
    sample = _flat([sample_source] + inputs[1:]) + picture + tail + ["-t", _number(SAMPLE_SECONDS)]
    return Job(title=f"{sequence.name} → {output.name}", output=output, passes=[arguments],
               duration=frames / fps if fps else 0.0, frames=frames, temporary=temporary, sample=sample)


def shrink(info: MediaInfo, output: str | Path, max_height: int = 720, quality: str = "small",
           target_mb: float | None = None, speed: str = "balanced", keep_audio: bool = True,
           work_dir: str | Path | None = None) -> Job:
    """A smaller copy of a video for sending: scaled down to `max_height`
    (never up) and re-encoded — at `quality`, or, with `target_mb`, to fit
    that many megabytes (two runs; lands within a few percent)."""
    output = Path(output)
    _need_video(info)
    scale = f"scale=-2:{int(max_height) // 2 * 2}" if max_height and info.height > max_height else _EVEN
    sound = ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"] if info.has_audio and keep_audio else ["-an"]
    title = f"{info.path.name} → {output.name}"
    if target_mb is None:
        body = ["-i", str(info.path), "-vf", scale, *_video(quality, speed), *sound, "-movflags", "+faststart"]
        return Job(title=title, output=output, passes=[body + [str(output)]], duration=info.duration,
                   frames=info.frames, sample=_sample(body, info.duration))

    kbps = int(float(target_mb) * 8 * 1024 / info.duration) - (AUDIO_KBPS if sound[0] != "-an" else 0)
    if kbps < MIN_VIDEO_KBPS:
        smallest = (MIN_VIDEO_KBPS + AUDIO_KBPS) * info.duration / 8 / 1024
        raise MediaError(f"{target_mb:g} MB is too little for {info.duration_text()} of video — "
                         f"ask for {smallest:.1f} MB or more, or trim it first.")
    folder = _work_dir(work_dir)
    log = folder / f"pass_{os.getpid()}_{abs(hash(str(output))) % 10 ** 8}"
    common = ["-i", str(info.path), "-vf", scale, "-c:v", "libx264", "-b:v", f"{kbps}k",
              "-preset", SPEED.get(speed, SPEED["balanced"]), "-pix_fmt", "yuv420p"]
    first = common + ["-passlogfile", str(log), "-pass", "1", "-an", "-f", "null", os.devnull]
    second = common + ["-passlogfile", str(log), "-pass", "2", *sound, "-movflags", "+faststart", str(output)]
    return Job(title=title, output=output, passes=[first, second], duration=info.duration, frames=info.frames,
               temporary=[Path(f"{log}-0.log"), Path(f"{log}-0.log.mbtree")],
               sample=_sample(common + sound, info.duration), expected_size=int(float(target_mb) * 1024 ** 2))


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
    body = ["-ss", _number(start), "-to", _number(end), "-i", str(info.path)]
    if exact:
        body += ["-vf", _EVEN, *_video(quality, speed)]
        body += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"] if info.has_audio else ["-an"]
    else:
        body += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    body += ["-movflags", "+faststart"]
    length = end - start
    return Job(title=f"{info.path.name} [{_number(start)}–{_number(end)} s] → {output.name}", output=output,
               passes=[body + [str(output)]], duration=length,
               frames=int(round(length * info.fps)) if info.fps else 0,
               sample=body + ["-t", _number(min(SAMPLE_SECONDS, length))] if exact else [])


def stamp(info: MediaInfo, output: str | Path, overlays: Overlays, quality: str = "high", speed: str = "balanced",
          work_dir: str | Path | None = None) -> Job:
    """A copy of a video with burn-ins (frame number, time, a label, the
    date) and / or a watermark drawn over it. The sound is kept as it is."""
    output = Path(output)
    _need_video(info)
    if not overlays.any():
        raise MediaError("Pick something to put on the picture first.")
    inputs = [["-i", str(info.path)]]
    picture, temporary = _picture(inputs, [_EVEN], overlays, (info.width, info.height), work_dir)
    tail = _video(quality, speed)
    if info.has_audio:
        tail += (["-map", "0:a"] if "-map" in picture else []) + ["-c:a", "copy"]
    tail += ["-movflags", "+faststart"]
    body = _flat(inputs) + picture + tail
    return Job(title=f"{info.path.name} → {output.name}", output=output, passes=[body + [str(output)]],
               duration=info.duration, frames=info.frames, temporary=temporary, sample=_sample(body, info.duration))


def convert(info: MediaInfo, output: str | Path, video_format: str = "prores") -> Job:
    """A video in an editing format (a key of FORMATS: ProRes, DNxHR) — big
    files that keep much more of the picture than an .mp4 and cut smoothly."""
    output = Path(output)
    _need_video(info)
    video_codec, sound_codec, _suffix = FORMATS.get(video_format, FORMATS["prores"])
    body = ["-i", str(info.path), "-vf", _EVEN, *(video_codec or _video("high", "balanced"))]
    body += list(sound_codec) if info.has_audio else ["-an"]
    return Job(title=f"{info.path.name} → {output.name}", output=output, passes=[body + [str(output)]],
               duration=info.duration, frames=info.frames, sample=_sample(body, info.duration))


def extract_audio(info: MediaInfo, output: str | Path, sound_format: str = "wav") -> Job:
    """The sound of a video as a sound file (a key of SOUND_FORMATS)."""
    output = Path(output)
    if not info.has_audio:
        raise MediaError(f"{info.path.name} has no sound.")
    codec, _suffix = SOUND_FORMATS.get(sound_format, SOUND_FORMATS["wav"])
    return Job(title=f"{info.path.name} → {output.name}", output=output, duration=info.duration,
               passes=[["-i", str(info.path), "-vn", *codec, str(output)]])


def remove_audio(info: MediaInfo, output: str | Path) -> Job:
    """A copy of a video without its sound (the picture is copied, not re-encoded)."""
    output = Path(output)
    _need_video(info)
    return Job(title=f"{info.path.name} → {output.name}", output=output, duration=info.duration, frames=info.frames,
               passes=[["-i", str(info.path), "-c:v", "copy", "-an", "-movflags", "+faststart", str(output)]])


def replace_audio(info: MediaInfo, output: str | Path, audio: str | Path) -> Job:
    """A copy of a video with `audio` as its sound (the picture is copied;
    shorter sound is padded with silence, longer is cut at the last frame)."""
    output = Path(output)
    _need_video(info)
    return Job(title=f"{info.path.name} + {Path(audio).name} → {output.name}", output=output,
               duration=info.duration, frames=info.frames,
               passes=[["-i", str(info.path), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", f"{AUDIO_KBPS * 2}k", "-af", "apad", "-shortest",
                        "-movflags", "+faststart", str(output)]])


def join(infos: list, output: str | Path, quality: str = "high", speed: str = "balanced") -> Job:
    """Several videos, one after another, as one. Every clip is brought to
    the frame size and rate of the FIRST (smaller ones get bars, none is
    stretched). The sound is kept only when every clip has sound."""
    output = Path(output)
    if len(infos) < 2:
        raise MediaError("Joining needs at least two videos.")
    for info in infos:
        _need_video(info)
    first = infos[0]
    width, height = first.width // 2 * 2, first.height // 2 * 2
    fps = _number(first.fps or 24.0)
    sound = all(info.has_audio for info in infos)
    parts, joined = [], ""
    for index in range(len(infos)):
        parts.append(f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                     f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{index}]")
        joined += f"[v{index}]" + (f"[{index}:a]" if sound else "")
    graph = (";".join(parts) + f";{joined}concat=n={len(infos)}:v=1:a={1 if sound else 0}[out]"
             + ("[sound]" if sound else ""))
    body = _flat([["-i", str(info.path)] for info in infos]) + ["-filter_complex", graph, "-map", "[out]"]
    body += (["-map", "[sound]", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS * 2}k"] if sound else []) + _video(quality, speed)
    body += ["-movflags", "+faststart"]
    duration = sum(info.duration for info in infos)
    return Job(title=f"{len(infos)} videos → {output.name}", output=output, passes=[body + [str(output)]],
               duration=duration, frames=int(round(duration * (first.fps or 24.0))))


def gif(info: MediaInfo, output: str | Path, width: int = 480, fps: float = 12.0) -> Job:
    """A video as an animated GIF — for a chat or a document. Fewer frames
    per second and a smaller width keep it light; the colors are picked
    from the video itself (a palette), so it doesn't look washed out."""
    output = Path(output)
    _need_video(info)
    size = f"scale={int(width)}:-1:flags=lanczos," if width and info.width > width else ""
    chain = (f"fps={_number(fps)},{size}split[a][b];[a]palettegen=stats_mode=diff[p];"
             f"[b][p]paletteuse=dither=bayer:bayer_scale=5")
    body = ["-i", str(info.path), "-vf", chain]
    return Job(title=f"{info.path.name} → {output.name}", output=output, passes=[body + [str(output)]],
               duration=info.duration, frames=int(round(info.duration * fps)), sample=_sample(body, info.duration))


def compare(first: MediaInfo, second: MediaInfo, output: str | Path, stacked: bool = False, labels: bool = True,
            quality: str = "high", speed: str = "balanced", work_dir: str | Path | None = None) -> Job:
    """Two videos in one picture — side by side, or one above the other
    (`stacked`) — to compare them frame for frame. Both are brought to the
    same height (width, when stacked) and to the first one's rate; the
    result is as long as the shorter one; `labels` writes each file's name
    over its half. The sound is the first video's."""
    output = Path(output)
    _need_video(first)
    _need_video(second)
    fps = _number(first.fps or 24.0)
    temporary: list[Path] = []
    chains = []
    for index, info in enumerate((first, second)):
        if stacked:
            side = min(first.width, second.width) // 2 * 2
            scale = f"scale={side}:-2"
            shown_height = int(info.height * side / max(info.width, 1))
        else:
            side = min(first.height, second.height) // 2 * 2
            scale = f"scale=-2:{side}"
            shown_height = side
        chain = f"[{index}:v]{scale},setsar=1,fps={fps}"
        if labels:
            text = _text_file(info.path.stem, work_dir)
            temporary.append(text)
            chain += "," + _drawtext(shown_height, f"textfile={_value(text)}:expansion=none", "{m}", "{m}")
        chains.append(chain + f"[v{index}]")
    graph = ";".join(chains) + f";[v0][v1]{'vstack' if stacked else 'hstack'}=inputs=2:shortest=1,{_EVEN}[out]"
    body = ["-i", str(first.path), "-i", str(second.path), "-filter_complex", graph, "-map", "[out]"]
    body += (["-map", "0:a", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"] if first.has_audio else []) + _video(quality, speed)
    body += ["-shortest", "-movflags", "+faststart"]
    duration = min(first.duration, second.duration)
    return Job(title=f"{first.path.name} | {second.path.name} → {output.name}", output=output,
               passes=[body + [str(output)]], duration=duration, temporary=temporary,
               frames=int(round(duration * (first.fps or 24.0))))


def adjust(info: MediaInfo, output: str | Path, rotate: int = 0, aspect: str = "", fps: float | None = None,
           speed_factor: float = 1.0, quality: str = "high", speed: str = "balanced") -> Job:
    """A corrected copy of a video: turned (`rotate`: 90 = clockwise, -90,
    180), cropped around its centre to a shape (`aspect`: "16:9", "1:1",
    "9:16", ...), at another frame rate, faster or slower (`speed_factor`:
    2 = twice as fast; the sound follows, at its own pitch)."""
    output = Path(output)
    _need_video(info)
    filters, sound = [], []
    if rotate in (90, -90, 270):
        filters.append("transpose=1" if rotate == 90 else "transpose=2")
    elif rotate == 180:
        filters.append("hflip,vflip")
    if aspect:
        try:
            across, down = (float(part) for part in aspect.split(":"))
            ratio = across / down
        except (ValueError, ZeroDivisionError) as error:
            raise MediaError(f"“{aspect}” isn’t a shape like 16:9.") from error
        filters.append(f"crop='min(iw,ih*{ratio:.6f})':'min(ih,iw/{ratio:.6f})'")
    if speed_factor and abs(speed_factor - 1.0) > 1e-6:
        if not 0.1 <= speed_factor <= 16:
            raise MediaError("The speed must be between 0.1× and 16×.")
        filters.append(f"setpts=PTS/{_number(speed_factor)}")
        sound = ["-af", ",".join(_tempo(speed_factor))]
    if fps:
        filters.append(f"fps={_number(fps)}")
    if not filters:
        raise MediaError("Pick something to change first.")
    filters.append(_EVEN)
    body = ["-i", str(info.path), "-vf", ",".join(filters), *_video(quality, speed)]
    body += (sound + ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"]) if info.has_audio else ["-an"]
    body += ["-movflags", "+faststart"]
    duration = info.duration / (speed_factor or 1.0)
    rate = fps or info.fps
    return Job(title=f"{info.path.name} → {output.name}", output=output, passes=[body + [str(output)]],
               duration=duration, frames=int(round(duration * rate)) if rate else 0,
               sample=_sample(body, info.duration))


def loop(info: MediaInfo, output: str | Path, times: int = 3, there_and_back: bool = False,
         quality: str = "high", speed: str = "balanced") -> Job:
    """A video repeated `times` times in a row — a walk or gallop cycle that
    keeps going. `there_and_back` plays it forward, then backward, and
    repeats THAT (the frames where it turns aren't shown twice, so the
    motion doesn't stall); it has no sound, and ffmpeg holds the whole
    video in memory for it — a long one is refused."""
    output = Path(output)
    _need_video(info)
    times = int(times)
    if times < 2:
        raise MediaError("A loop repeats the video at least twice.")
    codec = _video(quality, speed)
    if not there_and_back:
        body = ["-stream_loop", str(times - 1), "-i", str(info.path), "-vf", _EVEN, *codec]
        body += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"] if info.has_audio else ["-an"]
        duration, frames = info.duration * times, info.frames * times
        how = f"×{times}"
    else:
        count = info.frames or int(round(info.duration * (info.fps or 24.0)))
        if count < 3:
            raise MediaError("The video is too short to play there and back.")
        if count * info.width * info.height * 1.5 > LOOP_MEMORY:
            fit = LOOP_MEMORY / (info.width * info.height * 1.5) / (info.fps or 24.0)
            raise MediaError(f"“There and back” keeps the whole video in memory — {info.duration_text()} of "
                             f"{info.resolution_text()} is too much (about {fit:.0f} s fit). Trim the cycle first.")
        cycle = 2 * count - 2
        graph = (f"[0:v]{_EVEN},split[a][b];"
                 f"[b]reverse,trim=start_frame=1:end_frame={count - 1},setpts=PTS-STARTPTS[r];"
                 f"[a][r]concat=n=2:v=1:a=0,loop=loop={times - 1}:size={cycle}:start=0,setpts=N/FRAME_RATE/TB[out]")
        body = ["-i", str(info.path), "-filter_complex", graph, "-map", "[out]", *codec, "-an"]
        duration, frames = info.duration * cycle / count * times, cycle * times
        how = f"there and back ×{times}"
    body += ["-movflags", "+faststart"]
    return Job(title=f"{info.path.name} {how} → {output.name}", output=output, passes=[body + [str(output)]],
               duration=duration, frames=frames, sample=_sample(body, info.duration))


def to_frames(info: MediaInfo, folder: str | Path, name: str = "", image_format: str = "png",
              jpg_quality: str = "best", first_number: int = 1, padding: int = 4, every: int = 1) -> Job:
    """A video taken apart into numbered pictures in `folder`:
    `<name>.<number>.<suffix>` — an image sequence. `every`: 1 = each frame,
    2 = every second one, ... `first_number` / `padding`: how the files are
    numbered ("0001" = 1 and 4). The job's output IS the folder."""
    folder = Path(folder)
    _need_video(info)
    arguments, suffix = IMAGE_FORMATS.get(image_format, IMAGE_FORMATS["png"])
    arguments = list(arguments)
    if image_format == "jpg":
        arguments = ["-q:v", str(JPG_QUALITY.get(jpg_quality, JPG_QUALITY["best"]))]
    every = max(int(every), 1)
    rate = (info.fps or 24.0) / every
    filters = ["-vf", f"fps={_number(rate)}"] if every > 1 else []
    name = (name or info.path.stem).replace("%", "%%")
    pattern = folder / f"{name}.%0{max(int(padding), 1)}d{suffix}"
    body = ["-i", str(info.path), *filters, *arguments, "-start_number", str(int(first_number)), str(pattern)]
    frames = int(round(info.duration * rate)) if info.duration else 0
    return Job(title=f"{info.path.name} → {folder.name}/ ({frames} {suffix.lstrip('.').upper()} frames)",
               output=folder, passes=[body], duration=info.duration, frames=frames, folder=folder)


def frame(info: MediaInfo, output: str | Path, seconds: float, jpg_quality: str = "best") -> Job:
    """One frame of a video, at `seconds`, as a picture (the format follows `output`'s suffix)."""
    output = Path(output)
    _need_video(info)
    seconds = min(max(float(seconds), 0.0), max(info.duration - 0.04, 0.0))
    quality = ["-q:v", str(JPG_QUALITY.get(jpg_quality, 2))] if output.suffix.lower() in (".jpg", ".jpeg") else []
    return Job(title=f"{info.path.name} at {_number(round(seconds, 2))} s → {output.name}", output=output,
               passes=[["-ss", _number(seconds), "-i", str(info.path), "-frames:v", "1", *quality, str(output)]])


def default_output(source: str | Path | ImageSequence, tag: str = "", suffix: str = ".mp4",
                   folder: str | Path | None = None, taken=()) -> Path:
    """A name for the result that clashes with nothing: next to the source
    (a sequence's video goes NEXT TO its frames' folder, not among the
    frames) or in `folder`, named after the source + `tag`; "_2", "_3", ...
    if that name is taken — by a file, or by one of `taken` (results of
    jobs that haven't run yet)."""
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


# --- the pieces ---------------------------------------------------------------------------------------


def _need_video(info: MediaInfo) -> None:
    if not info.duration or not info.width:
        raise MediaError(f"{info.path.name} isn’t a video.")


def _video(quality: str, speed: str) -> list[str]:
    return ["-c:v", "libx264", "-crf", str(QUALITY.get(quality, QUALITY["good"])),
            "-preset", SPEED.get(speed, SPEED["balanced"]), "-pix_fmt", "yuv420p"]


def _number(value: float) -> str:
    """12.0 -> "12", 2.5 -> "2.5", 29.97002997 -> "29.97003"."""
    return f"{float(value):.5f}".rstrip("0").rstrip(".")


def _flat(lists: list) -> list[str]:
    return [item for part in lists for item in part]


def _sample(body: list[str], duration: float) -> list[str]:
    """`body` (a job's arguments without its output) as a short run from the
    middle of the video — what is encoded to estimate the whole."""
    seconds = min(SAMPLE_SECONDS, duration or SAMPLE_SECONDS)
    middle = max((duration - seconds) / 2, 0.0) if duration else 0.0
    return ["-ss", _number(middle)] + list(body) + ["-t", _number(seconds)]


def _tempo(factor: float) -> list[str]:
    """The sound filters for a speed change: `atempo` takes 0.5..2 at a time, so big changes are chained."""
    filters = []
    while factor > 2.0 + 1e-9:
        filters.append("atempo=2")
        factor /= 2.0
    while factor < 0.5 - 1e-9:
        filters.append("atempo=0.5")
        factor /= 0.5
    filters.append(f"atempo={_number(factor)}")
    return filters


def _work_dir(work_dir: str | Path | None) -> Path:
    folder = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "msl_tools" / "media"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _value(path: str | Path) -> str:
    """A path as the value of a filter option: quoted, forward slashes, the
    drive's colon escaped once (the one spelling both 7.1 and 8.0 take)."""
    return "'" + str(path).replace(chr(92), "/").replace(":", chr(92) + ":") + "'"


def _font() -> str:
    """`fontfile=...:` for drawtext — a fixed-width font, so numbers don't
    jump — or "" to let ffmpeg pick its default."""
    for candidate in _FONTS:
        if os.path.isfile(candidate):
            return f"fontfile={_value(candidate)}:"
    return ""


def _text_file(text: str, work_dir: str | Path | None) -> Path:
    """`text` in a temporary file: drawtext reads it with `textfile=`, so no
    character of it has to be escaped."""
    folder = _work_dir(work_dir)
    path = folder / f"text_{os.getpid()}_{time.time_ns() % 10 ** 12}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _drawtext(frame_height: int, what: str, x: str, y: str) -> str:
    """One drawtext filter: `what` (text=... / textfile=...) at `x`, `y`
    ({m} = the margin), white on a half-transparent box, sized to the frame."""
    size = max(int(frame_height / 30), 12)
    margin = max(int(frame_height / 45), 6)
    return (f"drawtext={_font()}{what}:fontcolor=white:fontsize={size}:box=1:boxcolor=black@0.5:"
            f"boxborderw={max(size // 4, 3)}:x={x.format(m=margin)}:y={y.format(m=margin)}")


def _picture(inputs: list, filters: list[str], overlays: Overlays | None, frame_size: tuple,
             work_dir: str | Path | None) -> tuple:
    """The picture's filter arguments (and the temporary files they need).
    Without a watermark that is `-vf <chain>`; with one, the image is added
    to `inputs` and a `-filter_complex` graph puts it into the corner —
    then `-map "[out]"` is part of the result and the caller maps the sound."""
    chain, temporary = list(filters), []
    width, height = (int(frame_size[0] or 0), int(frame_size[1] or 0)) if frame_size else (0, 0)
    if overlays is not None and overlays.texts():
        if not height:
            raise MediaError("The frame size is needed to draw on the picture.")
        if overlays.label.strip():
            text = _text_file(overlays.label.strip(), work_dir)
            temporary.append(text)
            chain.append(_drawtext(height, f"textfile={_value(text)}:expansion=none", "{m}", "{m}"))
        if overlays.date:
            text = _text_file(time.strftime("%Y-%m-%d"), work_dir)
            temporary.append(text)
            chain.append(_drawtext(height, f"textfile={_value(text)}:expansion=none", "w-tw-{m}", "{m}"))
        if overlays.time:
            chain.append(_drawtext(height, "text='%{pts" + chr(92) + ":hms}'", "(w-tw)/2", "h-th-{m}"))
        if overlays.frame_number:
            chain.append(_drawtext(height, f"text='%{{frame_num}}':start_number={int(overlays.first_frame)}",
                                   "w-tw-{m}", "h-th-{m}"))
    if overlays is None or not overlays.watermark:
        return ["-vf", ",".join(chain)], temporary
    if not os.path.isfile(overlays.watermark):
        raise MediaError(f"The watermark image isn’t there: {overlays.watermark}")
    if not width:
        raise MediaError("The frame size is needed to place the watermark.")
    index = len(inputs)
    inputs.append(["-i", str(overlays.watermark)])
    mark_width = max(int(width * min(max(overlays.watermark_size, 1), 100) / 100) // 2 * 2, 2)
    margin = max(int(height / 45), 6)
    opacity = min(max(overlays.watermark_opacity, 0), 100) / 100
    graph = (f"[0:v]{','.join(chain)}[base];"
             f"[{index}:v]scale={mark_width}:-1,format=rgba,colorchannelmixer=aa={opacity:.2f}[mark];"
             f"[base][mark]overlay=W-w-{margin}:H-h-{margin}[out]")
    return ["-filter_complex", graph, "-map", "[out]"], temporary


def _hold_list(sequence: ImageSequence, fps: float, work_dir: str | Path | None) -> Path:
    """Writes the list ffmpeg's concat reader takes for a sequence with gaps:
    every frame that exists, shown until the next one that exists."""
    folder = _work_dir(work_dir)
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
