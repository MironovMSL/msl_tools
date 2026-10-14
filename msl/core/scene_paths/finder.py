# core/scene_paths/finder.py
"""Finding a scene's missing files again: by their NAME, under the roots' folders (and any other the
user adds) — a texture that moved from W:/WarGaming_Maya/.../texture to E:/branches/Animation/.../model
is found where it is now.

Several files of that name: the one whose path ends most like the old one (the most folders in
common, counted from the file upwards) is taken — only when it is ahead of the rest; a tie is left
for the user to pick. A found file is written through a root when it lies under one ($WG_ANIM/...).

Qt-free; reads folder listings only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from msl_tools.msl.core.scene_paths.roots import Root, normalized

INDEX_AT_MOST = 400_000          # files; a whole drive given as a folder stops here
SKIP_FOLDERS = ("incrementalSave", "__pycache__", "node_modules")


@dataclass
class FileIndex:
    """File names (lower case) -> the files of that name, from a walk of some folders."""

    folders: list[str]
    files: dict[str, list[str]] = field(default_factory=dict)
    count: int = 0
    cut: bool = False             # stopped at INDEX_AT_MOST


def build_index(folders, limit: int = INDEX_AT_MOST) -> FileIndex:
    """Walks `folders` all the way down (hidden folders, Maya's incrementalSave copies left out)."""
    index = FileIndex([normalized(folder) for folder in folders])
    seen: set[str] = set()
    for folder in index.folders:
        for current, folders_below, files in os.walk(folder):
            key = os.path.normcase(current)
            if key in seen:            # one folder inside another of the list
                folders_below[:] = []
                continue
            seen.add(key)
            folders_below[:] = [name for name in folders_below
                                if not name.startswith(".") and name not in SKIP_FOLDERS]
            base = normalized(current)
            for name in files:
                index.files.setdefault(name.lower(), []).append(f"{base}/{name}")
                index.count += 1
                if index.count >= limit:
                    index.cut = True
                    return index
    return index


def file_name(path: str) -> str:
    return normalized(path).rsplit("/", 1)[-1]


def _common_tail(old: str, new: str) -> int:
    """How many path parts two paths share, counted from their ends (the file name included)."""
    a, b = normalized(old).lower().split("/"), normalized(new).lower().split("/")
    count = 0
    while count < min(len(a), len(b)) and a[-1 - count] == b[-1 - count]:
        count += 1
    return count


def candidates(missing: str, index: FileIndex) -> list[str]:
    """The files named like `missing`, the most alike first (then the shorter path, then by name)."""
    found = index.files.get(file_name(missing).lower(), [])
    return sorted(found, key=lambda path: (-_common_tail(missing, path), len(path), path.lower()))


def best(missing: str, found: list[str]) -> str:
    """The one candidate ahead of the rest ("" when there is none, or a tie at the top)."""
    if not found:
        return ""
    if len(found) == 1:
        return found[0]
    first, second = _common_tail(missing, found[0]), _common_tail(missing, found[1])
    return found[0] if first > second else ""


def through_root(path: str, roots: list[Root]) -> str:
    """`path` written through the deepest root it lies under ("$WG_ANIM/..."), else as it is."""
    shown = normalized(path)
    lowered = shown.lower()
    for root in roots:   # deepest first (roots_from sorts them)
        folder = root.value.lower()
        if lowered == folder or lowered.startswith(folder + "/"):
            return root.token + shown[len(root.value):]
    return shown


def key_of(path: str) -> str:
    """How a missing path is remembered (the same file named with other slashes / case is one)."""
    return normalized(path).lower()
