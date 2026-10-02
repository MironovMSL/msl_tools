# core/media/__init__.py
"""Working with video, sound and image sequences through ffmpeg — the Qt-free
foundation under the Media tool (and, later, batch jobs and Maya playblasts).

    ffmpeg.py    where ffmpeg is (FfmpegLocator -> FfmpegTools), MediaError
    install.py   the managed copy: FfmpegInstaller downloads a pinned build
    probe.py     what a file is: probe() -> MediaInfo
    sequence.py  image sequences in a folder: find_sequences() -> ImageSequence
    recipes.py   tasks as ffmpeg arguments -> Job: sequence_to_video, shrink,
                 trim, stamp (burn-ins, watermark), convert (editing formats),
                 extract / remove / replace the sound, join, gif, compare, adjust,
                 to_frames / frame (a video taken apart into pictures), loop
    run.py       following a run: ProgressParser, run_job() (blocking), estimate(), preview()
    thumbnail.py a small picture of a file: thumbnail(), frame_at()

A window runs jobs with ui/media/ffmpeg_runner.py (never blocks).
"""
from .ffmpeg import FfmpegLocator, FfmpegTools, MediaError, tools_dir
from .install import FfmpegInstaller
from .probe import MediaInfo, probe
from .recipes import (Job, Overlays, adjust, compare, convert, default_output, extract_audio, frame, gif,
                      join, loop, remove_audio, replace_audio, sequence_to_video, shrink, stamp, to_frames, trim)
from .run import Estimate, Progress, ProgressParser, estimate, preview, run_job
from .sequence import ImageSequence, find_sequences, sequence_of

__all__ = ["Estimate", "FfmpegInstaller", "FfmpegLocator", "FfmpegTools", "ImageSequence", "Job", "MediaError",
           "MediaInfo", "Overlays", "Progress", "ProgressParser", "adjust", "compare", "convert", "default_output",
           "estimate", "extract_audio", "find_sequences", "frame", "gif", "join", "loop", "preview", "probe",
           "remove_audio", "replace_audio", "run_job", "sequence_of", "sequence_to_video", "shrink", "stamp", "to_frames", "tools_dir", "trim"]
