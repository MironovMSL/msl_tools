# core/batch/__init__.py
"""Batch — Maya scenes rendered one after another without anyone opening Maya. Qt-free.

    frames.py    "1-10, 20, 30-40x2" <-> a list of frame numbers
    job.py       BatchJob (one scene to render, how, where) and BatchStore (the queue on disk)
    checks.py    what a probe of a scene means for its render: problems, warnings, what is fine
    commands.py  how a job runs: the program, its arguments, the task file for the runner in Maya

The part inside Maya is tools/maya/batch_runner.py; the hub's page is tools/desktop/batch/.
"""
from .checks import ERROR, OK, WARNING, Issue, check, choose_renderer
from .frames import FramesError, format_frames, parse_frames
from .job import BatchJob, BatchStore

__all__ = ["BatchJob", "BatchStore", "ERROR", "FramesError", "Issue", "OK", "WARNING", "check", "choose_renderer",
           "format_frames", "parse_frames"]
