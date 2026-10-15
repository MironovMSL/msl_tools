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
import time
from pathlib import Path

from msl_tools.msl.core.batch.commands import clean_environment, scene_maya_version
from msl_tools.msl.core.scene_paths import ma_paths
from msl_tools.msl.core.scene_paths.ma_paths import ApplyResult, PathUse, SceneScan
from msl_tools.msl.core.scene_paths.progress import Progress
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


POLL_SECONDS = 0.3


class Stopped(ma_paths.ScenePathsError):
    """The user stopped the run: the mayapy was ended; the scenes it hadn't finished stay as they were.
    `done` = the runner's results for the scenes it HAD finished (it writes them after each one)."""

    def __init__(self, message: str, done: list | None = None):
        super().__init__(message)
        self.done = done or []


def _partial(result_file: Path) -> list:
    try:
        return list(json.loads(result_file.read_text(encoding="utf-8")).get("scenes") or [])
    except (OSError, ValueError, AttributeError):
        return []


def _run(maya_folder: Path, task: dict, environment: dict, progress: Progress | None = None) -> dict:
    """Runs the runner on `task` in a mayapy of `maya_folder`; returns its result {"scenes": [...]}.
    Watched every POLL_SECONDS: each scene the runner finishes (its progress file's "scene_done") counts in
    `progress`; `progress.stopped` ends the mayapy (raises Stopped) — between saves a scene is never cut
    in half by it except while Maya writes one (Maya's own save then decides)."""
    work = Path(tempfile.mkdtemp(prefix="msl_scene_paths_"))
    try:
        task = dict(task, result=str(work / "result.json"), progress=str(work / "progress.jsonl"))
        task_file = work / "task.json"
        task_file.write_text(json.dumps(task), encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        timeout = START_SECONDS + SECONDS_PER_SCENE * len(task["scenes"])
        log = open(work / "output.txt", "w", encoding="utf-8", errors="replace")   # not a pipe: nobody reads it live
        try:
            process = subprocess.Popen([str(Path(maya_folder) / "bin" / "mayapy.exe"), str(RUNNER), str(task_file)],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       env=environment, creationflags=flags)
        except OSError as error:
            log.close()
            raise ma_paths.ScenePathsError(f"mayapy couldn’t be started: {error.strerror or error}") from error
        started, base = time.monotonic(), progress.done if progress is not None else 0
        progress_file = Path(task["progress"])
        try:
            while process.poll() is None:
                if progress is not None:
                    try:
                        finished = progress_file.read_text(encoding="utf-8", errors="replace").count('"scene_done"')
                    except OSError:
                        finished = 0
                    progress.done = base + finished
                    if progress.stopped:
                        process.kill()
                        process.wait(10)
                        raise Stopped("stopped", _partial(Path(task["result"])))
                if time.monotonic() - started > timeout:
                    process.kill()
                    process.wait(10)
                    raise ma_paths.ScenePathsError(f"Maya didn’t finish in {timeout // 60} min")
                time.sleep(POLL_SECONDS)
        finally:
            log.close()
        if progress is not None:
            progress.done = base + len(task["scenes"])
        result_file = Path(task["result"])
        if not result_file.is_file():
            tail = (work / "output.txt").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]
            raise ma_paths.ScenePathsError("Maya stopped before it was done" + (": " + " / ".join(tail) if tail else ""))
        return json.loads(result_file.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def read_raw(scenes, installed: dict, environment: dict, progress: Progress | None = None) -> dict[str, dict]:
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
            if progress is not None and progress.stopped:
                raise Stopped("stopped")
            answer = _run(installed[year], task, environment, progress)
        except Stopped as stop:
            finished = {str(Path(item.get("path", ""))) for item in stop.done}
            answer = {"scenes": stop.done + [{"path": str(scene), "error": Progress.STOPPED}
                                             for scene in group if str(scene) not in finished]}
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
            under = [root for root in roots
                     if lowered == root.value.lower() or lowered.startswith(root.value.lower() + "/")]
            if under:
                use.root = under[0]
                use.state = ma_paths.LEFT if item.get("inside") else ma_paths.CHANGE
                use.note = str(item.get("note") or "")
                if use.state == ma_paths.CHANGE:
                    use.options = [(root, 0) for root in under]   # Maya writes it: no byte offset
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
                 backup: bool = True, progress: Progress | None = None) -> list[tuple[Path, ApplyResult | None, str]]:
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
                            "relink": {use.key: use.relink for use in result.relinks},
                            # exactly what to swap and through which variable (the runner checks each)
                            "writes": {use.key: use.new_path for use in result.changes}}
                           for result, _copy in group]}
        try:
            if progress is not None and progress.stopped:
                raise Stopped("stopped")
            answer = _run(installed[year], task, environment, progress)
        except Stopped as stop:
            answer = {"scenes": stop.done}   # the scenes Maya finished (saved) before the stop count as done
            finished = {str(Path(item.get("path", ""))) for item in stop.done}
            outcome += [(result.path, None, f"{result.path.name}: stopped before Maya wrote it (or while it did — "
                                            f"its .bak is beside it)") for result, _copy in group
                        if str(result.path) not in finished]
            group = [(result, copy) for result, copy in group if str(result.path) in finished]
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
