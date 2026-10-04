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
    "version": "the next version of this name: v001, v002…",
    "work": "a folder for working versions next to the scene: <scene's folder>/playblast/work",
    "work+": "the same — plus a copy without a version, always the latest, one folder up",
}
DEFAULT_FOLDER = "{project}/movies"
DEFAULT_NAME = "{scene}_{camera}"
_TOKEN = re.compile(r"\{([a-z_]+\+?)\}")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')


WORK_TOKEN, WORK_LATEST_TOKEN = "{work}", "{work+}"


def work_folder(project: str, scene_folder: str) -> str:
    """Where working versions of a scene's playblasts go: `playblast/work` next to the scene
    file — for a scene never saved, under the project's `scenes`."""
    base = str(scene_folder).rstrip("/\\") or str(project).rstrip("/\\") + "/scenes"
    return base + "/playblast/work"


def token_values(project: str, scene: str, camera: str, now: float | None = None,
                 scene_folder: str = "") -> dict:
    """The value of every token for one playblast. `scene_folder`: where the scene file is
    ("" = never saved)."""
    moment = time.localtime(now)
    work = work_folder(project, scene_folder)
    return {"project": str(project).rstrip("/\\"), "scene": scene or "untitled", "work": work, "work+": work,
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
    target_folder = Path(expand(folder.strip() or DEFAULT_FOLDER, values))
    if not target_folder.is_absolute() and values.get("project"):
        # "movies" typed without {project}: inside the project, not wherever Maya's working folder is
        target_folder = Path(values["project"]) / target_folder
    return target_folder / (file_name + suffix)


VERSION_TOKEN = "{version}"


def version_for(folder: str, name: str, values: dict, suffix: str, reuse: bool = False,
                taken=()) -> str:
    """What {version} stands for: "v001" for the first playblast of this name, then the number
    after the highest one found in the folder ("v007" -> "v008"). `reuse`: the highest one
    itself (a playblast that replaces the last version instead of adding one). `taken`: paths
    of results still being made — no file yet, but their number counts (a second playblast
    started while the first one's video is made got the same version)."""
    mark = "\uE000"
    target = output_path(folder, name, dict(values, version=mark), suffix)
    if mark not in target.name:
        return "v001"  # {version} only counts in the NAME
    before, after = target.name.split(mark, 1)
    pattern = re.compile(re.escape(before) + r"v(\d+)" + re.escape(after.replace(mark, "")) + "$", re.IGNORECASE)
    highest = 0
    names = []
    try:
        names = [entry.name for entry in target.parent.iterdir()]
    except OSError:
        pass
    names += [Path(path).name for path in taken if Path(path).parent == target.parent]
    for entry_name in names:
        match = pattern.match(entry_name)
        if match:
            highest = max(highest, int(match.group(1)))
    number = max(1, highest) if reuse else highest + 1
    return f"v{number:03d}"


def without_version(name: str) -> str:
    """A name template with its {version} (and the separator before it) taken out."""
    return re.sub(r"[ _.\-]*\{version\}", "", name).strip(" _.-")


def free_path(path: Path, taken=()) -> Path:
    """`path`, or — if something is there already, or it is in `taken` (results on their way,
    no file yet) — the first of `<name>_2`, `<name>_3`, ... that is free."""
    taken = {Path(item) for item in taken}
    candidate, counter = path, 2
    while candidate.exists() or candidate in taken:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        counter += 1
    return candidate


_VERSIONED = re.compile(r"^(.*?)v(\d+)(.*)$", re.IGNORECASE)


def previous_version(path: Path) -> Path | None:
    """The playblast one version before `path` in the same folder ("shot_v003.mp4" ->
    the highest of shot_v001 / shot_v002 that exists); None for a name without a version
    or when there is no earlier one. Derived files (_light, _vs_) aren't versions."""
    path = Path(path)
    match = _VERSIONED.match(path.name)
    if match is None:
        return None
    before, number, after = match.group(1), int(match.group(2)), match.group(3)
    pattern = re.compile(re.escape(before) + r"v(\d+)" + re.escape(after) + "$", re.IGNORECASE)
    best, best_number = None, 0
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        return None
    for entry in entries:
        found = pattern.match(entry.name)
        if found and best_number < int(found.group(1)) < number:
            best, best_number = entry, int(found.group(1))
    return best
