# tools/desktop/media/history.py
"""The results the Media tool made, kept across hub restarts — Qt-free."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


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
    """

    title: str
    output: str
    folder: bool = False
    size: int = 0
    files: int = 0
    seconds: float = 0.0
    source_size: int = 0
    finished: float = 0.0


class ResultHistory:
    """The last KEPT results, oldest first, in `<base_dir>/history.json`.

    Nothing is read until load() is called. A file that can't be read or
    written is an empty history — losing it must never get in the way of
    the tool.
    """

    KEPT = 50

    def __init__(self, base_dir: str | Path):
        self._path = Path(base_dir) / "history.json"

    def load(self) -> list[ResultRecord]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            items = data.get("results") if isinstance(data, dict) else None
        except (OSError, ValueError):
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
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps({"results": [asdict(record) for record in records[-self.KEPT:]]},
                              indent=2, ensure_ascii=False)
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            pass
