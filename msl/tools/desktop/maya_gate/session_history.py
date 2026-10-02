# tools/desktop/maya_gate/session_history.py
"""The Maya sessions that are over — Qt-free.

The Sessions tab lists what is running NOW; this keeps what ran before: one
record per Maya that left (it quit, or its connection just broke), newest
first, in `<base_dir>/sessions/history.json`. It survives a hub restart, so
"Maya 2025 ended unexpectedly yesterday, here is its log" is still there the
next day.

A session's log (what its Script Editor reported to the hub) is kept as a
plain text file next to the hub's logs: write_log() / read_log() are the
two ends of that format.
"""
from __future__ import annotations

import json
import os
import re
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
        forced: The unclean end was a "Force close" from the hub.
        autosave: The newest autosave of the scene found after an unclean end ("" = none).
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
    forced: bool = False
    autosave: str = ""

    @property
    def key(self) -> tuple:
        """What tells one record from another."""
        return (self.pid, self.ended_at)

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
                   log_file=str(data.get("log_file") or ""),
                   forced=bool(data.get("forced")),
                   autosave=str(data.get("autosave") or ""))

    def outcome_text(self) -> str:
        """How it ended, in two words."""
        return "closed" if self.clean else "force closed" if self.forced else "ended unexpectedly"


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
        records = [record] + self.records()
        for dropped in records[self.KEPT:]:  # the log of a session that falls out of the history goes with it
            _remove_log(dropped.log_file)
        self._records = records[:self.KEPT]
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


# --- a session's log as a file ---------------------------------------------------------------------

LOG_FOLDER_NAME = "sessions"
_LOG_RULE = "--- what its Script Editor reported"
_TEXT_COLUMN = 19   # "HH:MM:SS  level    " - where an entry's text starts; more lines of it are indented this far
_CLOCK = re.compile(r"\d\d:\d\d:\d\d$")


def write_log(folder: str | Path, record: SessionRecord, entries, full_version: str = "") -> Path | None:
    """Writes a finished session's log into `folder` and returns the file
    (None if it couldn't be written). `entries`: (level, text, time.time()) tuples."""
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(record.ended_at))
        path = folder / f"maya{record.version}_{stamp}_pid{record.pid}.log"
        clock = "%Y-%m-%d %H:%M:%S"
        lines = [f"Maya {full_version or record.version}, process {record.pid}",
                 f"Environment: {record.environment or '-'}   boost: {'on' if record.boosted else 'off'}",
                 f"Scene: {record.scene or 'untitled'}",
                 f"Unsaved changes in the scene: {'yes' if record.modified else 'no'}",
                 "Connected: " + time.strftime(clock, time.localtime(record.connected_at)),
                 ("Closed: " if record.clean else "Force closed: " if record.forced else "Ended unexpectedly: ")
                 + time.strftime(clock, time.localtime(record.ended_at)),
                 "", _LOG_RULE + " (warnings and errors; everything if \"All\" was on) ---"]
        for level, text, at in entries:
            first, *rest = (str(text).rstrip(chr(10)).split(chr(10)) or [""])
            lines.append(f"{time.strftime('%H:%M:%S', time.localtime(at))}  {level:7s}  {first}")
            lines += [" " * _TEXT_COLUMN + line for line in rest]
        if not entries:
            lines.append("(nothing was reported)")
        path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        return path
    except OSError:
        return None


def read_log(path: str | Path, day: float) -> list[tuple[str, str, float]] | None:
    """The entries of a file written by write_log(), as (level, text, time)
    tuples; None if the file can't be read. The file only keeps the clock
    time of an entry — `day` (any time.time() of that day) supplies the date."""
    try:
        lines = Path(path).read_text(encoding="utf-8").split(chr(10))
    except (OSError, ValueError):
        return None
    start = next((index + 1 for index, line in enumerate(lines) if line.startswith(_LOG_RULE)), len(lines))
    date = time.localtime(day)
    entries: list[list] = []
    for line in lines[start:]:
        if _CLOCK.match(line[:8]) and line[8:10] == "  ":
            hours, minutes, seconds = (int(part) for part in line[:8].split(":"))
            at = time.mktime((date.tm_year, date.tm_mon, date.tm_mday, hours, minutes, seconds, 0, 0, -1))
            entries.append([line[10:17].strip() or "info", line[_TEXT_COLUMN:], at])
        elif entries and line.startswith(" " * _TEXT_COLUMN):
            entries[-1][1] += chr(10) + line[_TEXT_COLUMN:]
    return [(level, text, at) for level, text, at in entries]


def _remove_log(path: str) -> None:
    """Deletes a session log — only one of ours (inside a "sessions" folder)."""
    if path and Path(path).parent.name == LOG_FOLDER_NAME:
        try:
            Path(path).unlink()
        except OSError:
            pass


# --- Maya's autosave files -------------------------------------------------------------------------

UNTITLED_AUTOSAVE = "__AUTO-SAVE__untitled"   # what Maya calls the autosaves of a scene with no file


def find_autosave(folder: str, scene: str, since: float) -> str:
    """The newest autosave Maya wrote for `scene` into `folder` at or after
    `since` — "" if there is none, or if the scene file itself is newer.

    Maya names them `<scene name>.<number>.ma|mb` (`__AUTO-SAVE__untitled.…`
    for a scene with no file) — measured with Maya 2025."""
    if not folder:
        return ""
    stem = os.path.splitext(os.path.basename(scene))[0] if scene else UNTITLED_AUTOSAVE
    pattern = re.compile(re.escape(stem) + r"\.\d+\.m[ab]$", re.IGNORECASE)
    newest, newest_time = "", since
    try:
        saved_at = os.path.getmtime(scene) if scene and os.path.isfile(scene) else 0.0
        for name in os.listdir(folder):
            if not pattern.match(name):
                continue
            path = os.path.join(folder, name)
            written = os.path.getmtime(path)
            if written >= newest_time and written > saved_at:
                newest, newest_time = path, written
    except OSError:
        return ""
    return newest.replace(os.sep, "/")
