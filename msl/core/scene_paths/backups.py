# core/scene_paths/backups.py
"""The .bak copies the Paths tab leaves beside a scene before writing it (ma_paths.backup_name):
"<scene>.<YYYYmmdd-HHMMSS>[-n].bak". Only files of exactly that form are ever listed — a .bak of
anything else (another program's, the user's own) is not ours to clear. Qt-free; reads folder listings.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def backups_of(scene) -> list[Path]:
    """The copies of `scene` beside it, oldest first."""
    scene = Path(scene)
    pattern = re.compile(re.escape(scene.name) + r"\.\d{8}-\d{6}(?:-\d+)?\.bak$", re.IGNORECASE)
    try:
        names = os.listdir(scene.parent)
    except OSError:
        return []
    return sorted((scene.parent / name for name in names if pattern.match(name)), key=lambda path: path.name)


def size_text(paths) -> str:
    """"12.4 MB" — the copies' size together."""
    total = 0
    for path in paths:
        try:
            total += Path(path).stat().st_size
        except OSError:
            pass
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB":
            return f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
        total /= 1024
