# tools/desktop/maya_gate/session_history.py
"""The Maya sessions that are over — Qt-free.

The Sessions tab lists what is running NOW; this keeps what ran before: one
record per Maya that left (it quit, or its connection just broke), newest
first, in `<base_dir>/sessions/history.json`. It survives a hub restart, so
"Maya 2025 ended unexpectedly yesterday, here is its log" is still there the
next day.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SessionRecord:
    """One finished Maya session.

    Attributes:
        pid: Maya's process id.
        version: Maya's year ("2025").
        environment: The Maya Gate environment it ran in ("" = none).
        scene: Path of the scene that was open at the end ("" = untitled).
        modified: That scene had unsaved changes at the end.
        boosted: It was started with boost start.
        connected_at: time.time() when it connected to the hub.
        ended_at: time.time() when it left.
        clean: True = it quit; False = the connection just broke (a crash, a killed process).
        log_file: The log saved for an unclean end ("" = none).
    """

    pid: int = 0
    version: str = ""
    environment: str = ""
    scene: str = ""
    modified: bool = False
    boosted: bool = False
    connected_at: float = 0.0
    ended_at: float = 0.0
    clean: bool = True
    log_file: str = ""

    @property
    def scene_name(self) -> str:
        return os.path.basename(self.scene) if self.scene else "untitled"

    def duration_text(self) -> str:
        """How long it ran: "under a minute", "12 min", "3 h 05 min"."""
        minutes = int(max(self.ended_at - self.connected_at, 0) // 60)
        if minutes < 1:
            return "under a minute"
        if minutes < 60:
            return f"{minutes} min"
        return f"{minutes // 60} h {minutes % 60:02d} min"

    def ended_text(self, now: float | None = None) -> str:
        """When it ended, as one reads it today: "13:44", "yesterday 13:44", "28 Sep 13:44"."""
        now = time.time() if now is None else now
        ended, today = time.localtime(self.ended_at), time.localtime(now)
        clock = time.strftime("%H:%M", ended)
        if ended[:3] == today[:3]:
            return clock
        if ended[:3] == time.localtime(now - 86400)[:3]:
            return "yesterday " + clock
        return f"{ended.tm_mday} {time.strftime('%b', ended)} {clock}"

    @classmethod
    def from_dict(cls, data: dict) -> "SessionRecord":
        """A record from stored data (unknown keys ignored, missing ones defaulted)."""
        return cls(pid=int(data.get("pid") or 0),
                   version=str(data.get("version") or ""),
                   environment=str(data.get("environment") or ""),
                   scene=str(data.get("scene") or ""),
                   modified=bool(data.get("modified")),
                   boosted=bool(data.get("boosted")),
                   connected_at=float(data.get("connected_at") or 0.0),
                   ended_at=float(data.get("ended_at") or 0.0),
                   clean=bool(data.get("clean", True)),
                   log_file=str(data.get("log_file") or ""))


class SessionHistory:
    """The last KEPT finished sessions, newest first.

    Nothing is read until records() / add() is first called. A file that
    can't be read or written is treated as an empty history — losing the
    history must never get in the way of the tab.
    """

    KEPT = 30

    def __init__(self, base_dir: str | Path):
        self._path = Path(base_dir) / "sessions" / "history.json"
        self._records: list[SessionRecord] | None = None

    def records(self) -> list[SessionRecord]:
        if self._records is None:
            self._records = self._read()
        return list(self._records)

    def add(self, record: SessionRecord) -> None:
        self._records = ([record] + self.records())[:self.KEPT]
        self._write()

    def discard(self, pid: int, ended_at: float) -> None:
        """Takes back a record (a Maya taken for gone that was only restarting its link)."""
        kept = [record for record in self.records() if (record.pid, record.ended_at) != (pid, ended_at)]
        if len(kept) != len(self.records()):
            self._records = kept
            self._write()

    def clear(self) -> None:
        self._records = []
        self._write()

    def _read(self) -> list[SessionRecord]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            items = data.get("sessions") if isinstance(data, dict) else None
            return [SessionRecord.from_dict(item) for item in items or [] if isinstance(item, dict)][:self.KEPT]
        except (OSError, ValueError, TypeError):
            return []

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"sessions": [asdict(record) for record in self._records or []]}
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass
