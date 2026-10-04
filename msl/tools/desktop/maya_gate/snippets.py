# tools/desktop/maya_gate/snippets.py
"""Console snippets: named pieces of Python kept for the Sessions tab's
console — Qt-free. One JSON file, `<base_dir>/console/snippets.json`:
{"snippets": [{"name": ..., "code": ...}, ...]}, in the order they were added."""
from __future__ import annotations

from pathlib import Path

from msl_tools.msl.core.fs.safe_json import JsonUnavailable, read_json_object, write_json_atomic


class SnippetStore:
    """Named code snippets, in the order they were added.

    Nothing is read until first asked. A file that can't be read is an
    empty list; one that can't be written leaves the snippets in memory.
    """

    def __init__(self, base_dir: str | Path):
        self._path = Path(base_dir) / "console" / "snippets.json"
        self._items: list[tuple[str, str]] | None = None
        self._locked = False  # the file exists but couldn't be read: never write over it

    def _load(self) -> list[tuple[str, str]]:
        if self._items is None:
            try:
                items = read_json_object(self._path).get("snippets")
            except JsonUnavailable:  # locked right now: show none, and don't write over it
                self._locked, items = True, None
            self._items = [(str(item.get("name") or ""), str(item.get("code") or ""))
                           for item in (items if isinstance(items, list) else [])
                           if isinstance(item, dict) and item.get("name")]
        return self._items

    def names(self) -> list[str]:
        return [name for name, _code in self._load()]

    def code(self, name: str) -> str:
        return next((code for item, code in self._load() if item == name), "")

    def save(self, name: str, code: str) -> None:
        """Adds a snippet at the end; one with the same name is replaced where it stands."""
        items = self._load()
        for index, (item, _code) in enumerate(items):
            if item == name:
                items[index] = (name, code)
                break
        else:
            items.append((name, code))
        self._write()

    def delete(self, name: str) -> None:
        self._items = [(item, code) for item, code in self._load() if item != name]
        self._write()

    def _write(self) -> None:
        if self._locked:
            return
        try:
            payload = {"snippets": [{"name": name, "code": code} for name, code in self._items or []]}
            write_json_atomic(self._path, payload, indent=2)
        except OSError:
            pass
