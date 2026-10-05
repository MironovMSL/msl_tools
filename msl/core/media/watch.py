# core/media/watch.py
"""Watching a render folder — Qt-free: which image sequences in it have
FINISHED growing, so a video can be made of each.

    watch = FolderWatch(folder)          # what is there now is the starting point
    ...                                   # every few seconds, on a worker thread:
    for sequence in watch.scan():         # grown, then quiet for `settle_seconds`
        make_a_video(sequence)
        watch.mark_made(sequence)

A renderer writes a frame at a time, so "done" can only be guessed: a
sequence is READY once it has new frames since the watch started (or since
its last video) and neither its frame count nor its last frame changed for
`settle_seconds`. A sequence that grows again later (a re-render, more
frames) is ready again. Sequences already there when the watch starts are
the starting point — they are not made into videos unless they change.

The folder itself and its sub-folders one level down are looked at
(renderers often write a folder per layer or camera). Only file names and
the last frame's time are read.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from msl_tools.msl.core.media.sequence import ImageSequence, find_sequences

SETTLE_SECONDS = 8.0


def _key(sequence: ImageSequence) -> tuple:
    return str(sequence.folder), sequence.prefix, sequence.suffix, sequence.padding


def _signature(sequence: ImageSequence) -> tuple:
    """What changes while frames are written: how many, the last one, when the last one was written."""
    try:
        written = os.path.getmtime(sequence.file(sequence.last))
    except OSError:
        written = 0.0
    return sequence.count, sequence.last, written


@dataclass
class _Seen:
    signature: tuple
    changed_at: float
    made: tuple | None = None       # the signature its last video was made from (None = none yet)


@dataclass
class FolderWatch:
    """See the module's docstring. `clock` is time.monotonic (tests pass their own)."""

    folder: Path
    settle_seconds: float = SETTLE_SECONDS
    depth: int = 1
    clock: object = time.monotonic
    _seen: dict = field(default_factory=dict)
    _started: bool = False

    def __post_init__(self) -> None:
        self.folder = Path(self.folder)

    def sequences(self) -> list[ImageSequence]:
        """Every image sequence in the folder and its sub-folders (`depth` levels down)."""
        found, folders = [], [(self.folder, 0)]
        while folders:
            folder, level = folders.pop(0)
            found += find_sequences(folder)
            if level < self.depth:
                try:
                    folders += sorted((Path(entry.path), level + 1) for entry in os.scandir(folder)
                                      if entry.is_dir() and not entry.name.startswith("."))
                except OSError:
                    pass
        return found

    def scan(self) -> list[ImageSequence]:
        """The sequences that are ready now (see the module's docstring). The first scan only takes
        stock and returns nothing."""
        now = self.clock()
        ready, present = [], set()
        for sequence in self.sequences():
            key = _key(sequence)
            present.add(key)
            signature = _signature(sequence)
            seen = self._seen.get(key)
            if seen is None:
                # there before the watch started: the starting point, not a new render
                self._seen[key] = _Seen(signature, now, made=signature if not self._started else None)
                continue
            if signature != seen.signature:
                seen.signature, seen.changed_at = signature, now
                continue
            if signature != seen.made and now - seen.changed_at >= self.settle_seconds:
                ready.append(sequence)
        for key in [key for key in self._seen if key not in present]:
            del self._seen[key]  # deleted (or renamed): if it comes back, it is a new one
        self._started = True
        return ready

    def mark_made(self, sequence: ImageSequence) -> None:
        """A video of `sequence` as it is now was made (or queued): it isn't ready again until it changes."""
        seen = self._seen.get(_key(sequence))
        if seen is not None:
            seen.made = _signature(sequence)

    def waiting(self) -> int:
        """Sequences that changed since their last video and are still being written (or settling)."""
        return sum(1 for seen in self._seen.values() if seen.signature != seen.made)
