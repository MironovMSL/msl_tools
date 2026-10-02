# tools/desktop/maya_gate/snippets.py
"""Console snippets: named pieces of Python kept for the Sessions tab's
console — Qt-free. One JSON file, `<base_dir>/console/snippets.json`:
{"snippets": [{"name": ..., "code": ...}, ...]}, in the order they were added."""
from __future__ import annotations

import json
from pathlib import Path


class SnippetStore:
    """Named code snippets, in the order they were added.

    Nothing is read until first asked. A file that can't be read is an
    empty list; one that can't be written leaves the snippets in memory.
    """

    def __init__(self, base_dir: str | Path):
        self._path = Path(base_dir) / "console" / "snippets.json"
        self._items: list[tuple[str, str]] | None = None

    def _load(self) -> list[tuple[str, str]]:
        if self._items is None:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                items = data.get("snippets") if isinstance(data, dict) else None
                self._items = [(str(item.get("name") or ""), str(item.get("code") or ""))
                               for item in items or [] if isinstance(item, dict) and item.get("name")]
            except (OSError, ValueError, TypeError):
                self._items = []
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
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"snippets": [{"name": name, "code": code} for name, code in self._items or []]}
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass
