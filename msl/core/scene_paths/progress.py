# core/scene_paths/progress.py
"""How far a run of the Paths tab is (reading or writing many scenes, in a worker) and whether the user
asked it to stop. Shared between the worker (which counts and checks `stopped` between scenes) and the
page (which shows the count on a timer and sets `stopped`). Plain attributes: one writer each. Qt-free.
"""
from __future__ import annotations


class Progress:
    """`done` of `total` scenes; `stopped` = stop after the scene at hand (each one stays whole)."""

    STOPPED = "not read — stopped"

    def __init__(self, total: int = 0, what: str = "Reading"):
        self.total = total
        self.done = 0
        self.what = what
        self.stopped = False

    def text(self, kind: str = "scene") -> str:
        """"Reading 120 of 500 scenes…" ("Stopping…" once asked)."""
        if self.stopped:
            return f"Stopping after the {kind} at hand…"
        return f"{self.what} {self.done} of {self.total} {kind}{'s' if self.total != 1 else ''}…"
