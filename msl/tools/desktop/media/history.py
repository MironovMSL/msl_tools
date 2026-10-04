# tools/desktop/media/history.py
"""The results the Media tool made, kept across hub restarts — Qt-free."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from msl_tools.msl.core.fs.safe_json import JsonUnavailable, read_json_object, write_json_atomic


@dataclass
class ResultRecord:
    """One finished job.

    Attributes:
        title: What it did ("shot.mp4 → shot_small.mp4").
        output: The file it wrote — or the folder, for frames.
        folder: True when `output` is a folder of files.
        size: Bytes of the result.
        files: How many files a folder result holds (0 for one file).
        seconds: How long the job ran.
        source_size: Bytes of what it was made from (0 = not compared).
        finished: When it was over (seconds since the epoch).
        recipe: What made it, to set it up again: {"action", "settings", "sources"}.
    """

    title: str
    output: str
    folder: bool = False
    size: int = 0
    files: int = 0
    seconds: float = 0.0
    source_size: int = 0
    finished: float = 0.0
    recipe: dict = field(default_factory=dict)


class ResultHistory:
    """The last KEPT results, oldest first, in `<base_dir>/history.json`.

    Nothing is read until load() is called. A file that can't be read or
    written is an empty history — losing it must never get in the way of
    the tool. A broken file is moved aside, a locked one is never written
    over (core/fs/safe_json.py).
    """

    KEPT = 50

    def __init__(self, base_dir: str | Path):
        self._path = Path(base_dir) / "history.json"
        self._locked = False  # the file exists but couldn't be read: never write over it

    def load(self) -> list[ResultRecord]:
        try:
            items = read_json_object(self._path).get("results")
            self._locked = False
        except JsonUnavailable:
            self._locked = True
            return []
        known = {field.name for field in fields(ResultRecord)}
        records = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not item.get("output"):
                continue
            try:  # keys a newer version added are ignored, missing ones take their defaults
                records.append(ResultRecord(**{key: value for key, value in item.items() if key in known}))
            except TypeError:
                continue
        return records[-self.KEPT:]

    def save(self, records: list[ResultRecord]) -> None:
        if self._locked:
            return
        try:
            write_json_atomic(self._path, {"results": [asdict(record) for record in records[-self.KEPT:]]}, indent=2)
        except OSError:
            pass
