# core/media/__init__.py
"""Working with video, sound and image sequences through ffmpeg — the Qt-free
foundation under the Media tool (and, later, batch jobs and Maya playblasts).

    ffmpeg.py    where ffmpeg is (FfmpegLocator -> FfmpegTools), MediaError
    install.py   the managed copy: FfmpegInstaller downloads a pinned build
    probe.py     what a file is: probe() -> MediaInfo
    sequence.py  image sequences in a folder: find_sequences() -> ImageSequence
    recipes.py   tasks as ffmpeg arguments: sequence_to_video / shrink / trim -> Job
    run.py       following a run: ProgressParser, run_job() (blocking)
    thumbnail.py a small picture of a file: thumbnail()

A window runs jobs with ui/media/ffmpeg_runner.py (never blocks).
"""
from .ffmpeg import FfmpegLocator, FfmpegTools, MediaError, tools_dir
from .install import FfmpegInstaller
from .probe import MediaInfo, probe
from .recipes import Job, default_output, sequence_to_video, shrink, trim
from .run import Progress, ProgressParser, run_job
from .sequence import ImageSequence, find_sequences, sequence_of

__all__ = ["FfmpegInstaller", "FfmpegLocator", "FfmpegTools", "ImageSequence", "Job", "MediaError", "MediaInfo",
           "Progress", "ProgressParser", "default_output", "find_sequences", "probe", "run_job", "sequence_of",
           "sequence_to_video", "shrink", "tools_dir", "trim"]
