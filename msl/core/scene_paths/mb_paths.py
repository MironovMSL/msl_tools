# core/scene_paths/mb_paths.py
"""Binary scenes (.mb): their paths can't be read as text, so a mayapy reads them — and, asked to,
swaps the folders for variables and saves (tools/maya/scene_paths_runner.py, run by path).

One mayapy per Maya version for all the scenes of a run (Maya's start is most of the time).
Reading takes the version the scene was saved with, else the oldest newer one installed;
WRITING only the version it was saved with — saved by a newer Maya, a scene no longer opens in
the one it was made in. The environment is the caller's (the hub's, cleaned, + the Maya Gate
environment, so references named $VAR resolve and plug-ins are found); a userSetup is not run.

Qt-free; starts processes and reads / writes files.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from msl_tools.msl.core.batch.commands import clean_environment, scene_maya_version
from msl_tools.msl.core.scene_paths import ma_paths
from msl_tools.msl.core.scene_paths.ma_paths import ApplyResult, PathUse, SceneScan
from msl_tools.msl.core.scene_paths.roots import Root, normalized

RUNNER = Path(__file__).resolve().parents[2] / "tools" / "maya" / "scene_paths_runner.py"
SECONDS_PER_SCENE = 600      # a heavy scene with its references; the run's limit grows with the count
START_SECONDS = 180


def maya_to_read(scene, installed: dict) -> str:
    """The Maya that reads `scene`: its own version, else the oldest newer one installed ("" = none can)."""
    saved = scene_maya_version(scene)
    if saved in installed:
        return saved
    newer = sorted(year for year in installed if saved and year > saved)
    if newer:
        return newer[0]
    return "" if saved else (sorted(installed)[-1] if installed else "")


def maya_to_write(scene, installed: dict) -> tuple[str, str]:
    """(the Maya that may save `scene`, why none may — "" when one may)."""
    saved = scene_maya_version(scene)
    if not saved:
        return "", "the Maya version it was saved with can’t be read from it"
    if saved not in installed:
        return "", f"saved with Maya {saved}, which isn’t installed — a newer Maya would make it unreadable there"
    return saved, ""


def environment_for(variables: dict, base: dict | None = None) -> dict:
    """What the mayapy gets: the hub's environment without its own Python's variables, the Maya Gate
    environment's variables over it, no userSetup."""
    environment = clean_environment(base)
    environment.update({str(key): str(value) for key, value in variables.items()})
    environment["MAYA_SKIP_USERSETUP_PY"] = "1"
    return environment


def _run(maya_folder: Path, task: dict, environment: dict) -> dict:
    """Runs the runner on `task` in a mayapy of `maya_folder`; returns its result {"scenes": [...]}."""
    work = Path(tempfile.mkdtemp(prefix="msl_scene_paths_"))
    try:
        task = dict(task, result=str(work / "result.json"), progress=str(work / "progress.jsonl"))
        task_file = work / "task.json"
        task_file.write_text(json.dumps(task), encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        timeout = START_SECONDS + SECONDS_PER_SCENE * len(task["scenes"])
        try:
            done = subprocess.run([str(Path(maya_folder) / "bin" / "mayapy.exe"), str(RUNNER), str(task_file)],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, env=environment, creationflags=flags)
        except subprocess.TimeoutExpired as error:
            raise ma_paths.ScenePathsError(f"Maya didn’t finish in {timeout // 60} min") from error
        except OSError as error:
            raise ma_paths.ScenePathsError(f"mayapy couldn’t be started: {error.strerror or error}") from error
        result_file = Path(task["result"])
        if not result_file.is_file():
            tail = (done.stderr or done.stdout or "").strip().splitlines()[-6:]
            raise ma_paths.ScenePathsError("Maya stopped before it was done" + (": " + " / ".join(tail) if tail else ""))
        return json.loads(result_file.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def read_raw(scenes, installed: dict, environment: dict) -> dict[str, dict]:
    """What mayapy finds in the binary scenes, before any root is applied: {str(path): {"maya",
    "size", "mtime_ns" (the file as Maya read it), "data" (the runner's answer for it)}}. Kept by the
    caller: a change of roots only sorts these again (scan_from_raw) — no Maya."""
    raw: dict[str, dict] = {}
    groups: dict[str, list[Path]] = {}
    for scene in scenes:
        scene = Path(scene)
        year = maya_to_read(scene, installed)
        if not year:
            saved = scene_maya_version(scene)
            raw[str(scene)] = {"maya": "", "size": 0, "mtime_ns": 0, "data": {
                "error": f"saved with Maya {saved or '?'} — no Maya that can read it is installed"}}
            continue
        groups.setdefault(year, []).append(scene)
    for year, group in sorted(groups.items()):
        stats = {}
        for scene in group:
            try:
                stat = scene.stat()
                stats[str(scene)] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                stats[str(scene)] = (0, 0)
        task = {"mode": "list", "roots": [], "scenes": [{"path": str(scene)} for scene in group]}
        try:
            answer = _run(installed[year], task, environment)
        except ma_paths.ScenePathsError as error:
            answer = {"scenes": [{"path": str(scene), "error": str(error)} for scene in group]}
        found = {str(Path(item.get("path", ""))): item for item in answer.get("scenes") or []}
        for scene in group:
            size, mtime_ns = stats[str(scene)]
            raw[str(scene)] = {"maya": year, "size": size, "mtime_ns": mtime_ns,
                               "data": found.get(str(scene), {"error": "Maya gave no answer for it"})}
    return raw


def scan_from_raw(path, raw: dict, roots: list[Root], environment: dict, cache: dict | None = None) -> SceneScan:
    """A binary scene's SceneScan: what mayapy found (read_raw) sorted by `roots` — a path under a root
    becomes CHANGE, or LEFT when it lives in a referenced file (the runner's "inside")."""
    path = Path(path)
    data = raw.get("data") or {}
    result = SceneScan(path, size=int(raw.get("size") or 0), mtime_ns=int(raw.get("mtime_ns") or 0), codeset="",
                       error=str(data.get("error") or ""), binary=True, maya=str(raw.get("maya") or ""))
    cache = {} if cache is None else cache
    lookup = dict(environment)
    lookup.update({root.name: root.value for root in roots})
    for item in data.get("uses") or []:
        shown = normalized(str(item.get("path") or ""))   # any slashes, doubled or not
        use = PathUse(line=0, kind=str(item.get("kind") or ma_paths.ATTRIBUTE), node=str(item.get("node") or ""),
                      attribute=str(item.get("attribute") or ""), path=shown, start=-1, end=-1)
        if shown.startswith("$"):
            use.state, use.variable = ma_paths.VARIABLE, shown[1:].split("/", 1)[0]
        else:
            lowered = shown.lower()
            for root in roots:
                folder = root.value.lower()
                if lowered == folder or lowered.startswith(folder + "/"):
                    use.root = root
                    use.state = ma_paths.LEFT if item.get("inside") else ma_paths.CHANGE
                    use.note = str(item.get("note") or "")
                    break
        use.exists = ma_paths._exists(ma_paths._resolved(use, lookup), cache)
        result.uses.append(use)
    return result


def scan_binary(scenes, roots: list[Root], installed: dict, environment: dict,
                exists_cache: dict | None = None) -> dict[str, SceneScan]:
    """Reads the binary scenes in mayapy and sorts what is found by `roots`: {str(path): SceneScan}."""
    cache = {} if exists_cache is None else exists_cache
    return {path: scan_from_raw(path, raw, roots, environment, cache)
            for path, raw in read_raw(scenes, installed, environment).items()}


def apply_binary(scans: list[SceneScan], roots: list[Root], installed: dict, environment: dict,
                 backup: bool = True) -> list[tuple[Path, ApplyResult | None, str]]:
    """Swaps and saves the binary scenes in mayapy, each in the Maya it was saved with: a list of
    (path, ApplyResult or None, why not). The old file is copied aside first (backup)."""
    outcome: list = []
    groups: dict[str, list[tuple[SceneScan, Path | None]]] = {}
    for result in scans:
        year, why = maya_to_write(result.path, installed)
        if why:
            outcome.append((result.path, None, f"{result.path.name}: {why}"))
            continue
        try:
            stat = result.path.stat()
        except OSError as error:
            outcome.append((result.path, None, f"{result.path.name}: it is gone ({error.strerror or error})"))
            continue
        if (stat.st_size, stat.st_mtime_ns) != (result.size, result.mtime_ns):
            outcome.append((result.path, None, f"{result.path.name} changed since it was read — read it again first"))
            continue
        copy = None
        if backup:
            copy = ma_paths.backup_name(result.path)
            try:
                shutil.copy2(result.path, copy)
            except OSError as error:
                outcome.append((result.path, None, f"{result.path.name}: no backup could be made ({error.strerror or error})"))
                continue
        groups.setdefault(year, []).append((result, copy))
    for year, group in sorted(groups.items()):
        task = {"mode": "apply", "roots": [[root.name, root.value] for root in roots],
                "scenes": [{"path": str(result.path), "size": result.size, "mtime_ns": result.mtime_ns,
                            "relink": {use.key: use.relink for use in result.relinks}}
                           for result, _copy in group]}
        try:
            answer = _run(installed[year], task, environment)
        except ma_paths.ScenePathsError as error:
            outcome += [(result.path, None, f"{result.path.name}: {error}") for result, _copy in group]
            continue
        found = {str(Path(item.get("path", ""))): item for item in answer.get("scenes") or []}
        for result, copy in group:
            data = found.get(str(result.path), {"error": "Maya gave no answer for it"})
            if data.get("error"):
                outcome.append((result.path, None, f"{result.path.name}: {data['error']}"))
            else:
                outcome.append((result.path, ApplyResult(result.path, int(data.get("changed") or 0), copy), ""))
    return outcome
