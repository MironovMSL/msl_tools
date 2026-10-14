# core/scene_paths/undo.py
"""Undoing a write of the Paths tab: each scene put back from the .bak copied aside before it was
written (ma_paths.apply / mb_paths.apply_binary).

A scene is put back only while it is still exactly as the write left it (size and time of change,
recorded right after the write): one saved again since — in Maya, by a colleague through SVN — holds
work the copy doesn't, and is left alone. A scene put back no longer needs its copy: the .bak is
removed. Qt-free; reads, writes and removes files.
"""
from __future__ import annotations

from pathlib import Path

from msl_tools.msl.core.fs.safe_json import write_bytes_atomic


def entry_for(scene, backup) -> dict | None:
    """What an undo needs of one written scene: {"scene", "backup", "size", "mtime_ns"} — the scene as
    the write left it. None when there is no copy (written without one) or the scene can't be read."""
    if not backup:
        return None
    try:
        stat = Path(scene).stat()
    except OSError:
        return None
    return {"scene": str(scene), "backup": str(backup), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def restore(entry: dict) -> str:
    """Puts one scene back from its copy. "" when it was put back, else why not (said to the user)."""
    scene, backup = Path(str(entry.get("scene") or "")), Path(str(entry.get("backup") or ""))
    try:
        stat = scene.stat()
    except OSError:
        return f"{scene.name}: it is gone"
    if (stat.st_size, stat.st_mtime_ns) != (entry.get("size"), entry.get("mtime_ns")):
        return f"{scene.name}: saved again since the replace — left as it is (its copy: {backup.name})"
    try:
        data = backup.read_bytes()
    except OSError:
        return f"{scene.name}: its copy {backup.name} is gone"
    try:
        write_bytes_atomic(scene, data)
    except OSError as error:
        return f"{scene.name}: couldn’t be written ({error.strerror or error})"
    try:
        backup.unlink()
    except OSError:
        pass   # put back all the same; the copy just stays
    return ""
