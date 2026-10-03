# tools/maya/playblast/naming.py
"""Where a playblast is written: folder and file name with {tokens} — Qt-free and Maya-free."""
from __future__ import annotations

import re
import time
from pathlib import Path

# token -> what it stands for (shown in the "insert a token" menu)
TOKENS = {
    "project": "the Maya project's folder",
    "scene": "the scene's name, without its folder and extension",
    "camera": "the camera the playblast is seen through",
    "timestamp": "the date and time: 20261003_154210",
    "date": "the date: 2026-10-03",
}
DEFAULT_FOLDER = "{project}/movies"
DEFAULT_NAME = "{scene}_{camera}"
_TOKEN = re.compile(r"\{([a-z_]+)\}")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')


def token_values(project: str, scene: str, camera: str, now: float | None = None) -> dict:
    """The value of every token for one playblast."""
    moment = time.localtime(now)
    return {"project": str(project).rstrip("/\\"), "scene": scene or "untitled",
            "camera": camera.split("|")[-1].replace(":", "_") or "camera",
            "timestamp": time.strftime("%Y%m%d_%H%M%S", moment), "date": time.strftime("%Y-%m-%d", moment)}


def expand(template: str, values: dict) -> str:
    """`template` with its {tokens} replaced; a token that isn't known stays as it is."""
    return _TOKEN.sub(lambda match: str(values.get(match.group(1), match.group(0))), template)


def output_path(folder: str, name: str, values: dict, suffix: str) -> Path:
    """The file (or, with an empty `suffix`, the folder) a playblast goes to.
    A name is cleaned of the characters a file name can't hold; a `suffix`
    typed into the name is dropped in favour of the real one."""
    file_name = _FORBIDDEN.sub("_", expand(name.strip() or DEFAULT_NAME, values)).strip(" .") or "playblast"
    if suffix and Path(file_name).suffix.lower() in (".mp4", ".mov", ".png", ".jpg"):
        file_name = Path(file_name).stem
    return Path(expand(folder.strip() or DEFAULT_FOLDER, values)) / (file_name + suffix)


def free_path(path: Path) -> Path:
    """`path`, or — if something is there already — the first of `<name>_2`, `<name>_3`, ... that is free."""
    candidate, counter = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        counter += 1
    return candidate
