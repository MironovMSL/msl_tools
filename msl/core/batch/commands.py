# core/batch/commands.py
"""How a job runs: which Maya, which program, its arguments, the task file for the runner.

Three roads (all measured with Maya 2024, 2026-10-05):
- Arnold, no window: `mayapy batch_runner.py <task.json>` — frame by frame, its own progress lines;
  Arnold watermarks the frames without a BATCH licence.
- Arnold, windowed: `maya.exe -command <exec the runner>` with MSL_BATCH_TASK — Maya opens
  (minimized), renders each frame into the Render View and saves it: the interactive licence, clean
  frames; ~15-20 s more to start.
- Viewport (Hardware 2.0) and Redshift: Maya's own `Render.exe -r hw2 | redshift` with the
  camera, a run of frames (-s / -e: hw2 takes no frame LIST, `-seq` is Arnold's), size and file
  names on its command line — one Render.exe per run of missing frames (`missing_runs`);
  progress = the frame files appearing.
  (Redshift isn't installed on the machine this was built on — that road is untried.)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from msl_tools.msl.core.batch.checks import choose_renderer
from msl_tools.msl.core.batch.job import ARNOLD, HW2, MODE_WINDOW, REDSHIFT, BatchJob

RUNNER = Path(__file__).resolve().parents[2] / "tools" / "maya" / "batch_runner.py"
_HEADER = re.compile(rb"Maya(?: ASCII| Binary)? (\d{4})|requires maya \"(\d{4})")


def scene_maya_version(scene) -> str:
    """The Maya version a scene was saved with ("2024"), read from its first bytes ("" = unknown)."""
    try:
        with open(scene, "rb") as handle:
            head = handle.read(65536)
    except OSError:
        return ""
    match = _HEADER.search(head)
    return (match.group(1) or match.group(2)).decode() if match else ""


def pick_maya(job: BatchJob, installed: dict) -> str:
    """The Maya a job runs in: its own choice if installed; else the version the scene was saved
    with; else the oldest installed one newer than that (a scene opens forward, not back); else
    the newest installed. "" = no Maya at all."""
    if not installed:
        return ""
    if job.maya in installed:
        return job.maya
    years = sorted(installed)
    saved = scene_maya_version(job.scene)
    if saved in installed:
        return saved
    newer = [year for year in years if saved and year > saved]
    return newer[0] if newer else years[-1]


def clean_environment(base=None) -> dict:
    """The environment a Maya gets: the hub's without its own Python's variables (a hub run from an
    IDE or a venv would hand them to mayapy, which has a Python of its own)."""
    environment = dict(os.environ if base is None else base)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM",
                 "QML2_IMPORT_PATH"):
        environment.pop(name, None)
    environment.setdefault("MAYA_DISABLE_CIP", "1")   # no "help improve Maya" prompt in a batch Maya
    environment.setdefault("MAYA_DISABLE_CER", "1")   # no crash reporter waiting for a click
    return environment


def write_task(job: BatchJob, mode: str, work: Path, threads: int = 0) -> Path:
    """The runner's task file for `mode` ("probe" / "render") in `work`; returns its path.
    `threads`: Arnold's thread count (negative = every core but that many; 0 = Arnold's choice)."""
    work.mkdir(parents=True, exist_ok=True)
    task = {"mode": mode, "scene": str(Path(job.scene)), "progress": str(work / f"{mode}_progress.jsonl"),
            "report": str(work / "probe.json"), "renderer": choose_renderer(job) if job.probe else ARNOLD,
            "window": job.mode == MODE_WINDOW,
            "search": [job.search_folder] if job.search_folder else []}
    if mode == "render":
        width, height = job.resolution()
        task.update(camera=job.camera_name(), frames=job.frame_list(), width=width, height=height,
                    folder=str(job.output_folder()), frame_dir=str(job.frame_dir()), prefix=job.prefix(),
                    skip_existing=True, layer=job.layer,
                    image_format=job.image_format, threads=int(threads))
    path = work / f"{mode}_task.json"
    Path(task["progress"]).unlink(missing_ok=True)
    path.write_text(json.dumps(task, indent=1), encoding="utf-8")
    return path


def missing_runs(job: BatchJob) -> list[tuple[int, int]]:
    """The frames still to render as runs of consecutive numbers: [(1, 40), (78, 78)]."""
    runs = []
    for frame in sorted(set(job.frame_list())):
        if job.frame_file(frame).is_file():
            continue
        if runs and frame == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], frame)
        else:
            runs.append((frame, frame))
    return runs


def _layer_arguments(job: BatchJob) -> list:
    """Render.exe renders EVERY renderable layer of a layered scene unless told one: -rl <layer>
    ("defaultRenderLayer" = the scene as saved; its frames land in "masterLayer")."""
    return ["-rl", job.layer or "defaultRenderLayer"] if job.layered() else []


def uses_render_exe(job: BatchJob) -> bool:
    return choose_renderer(job) in (HW2, REDSHIFT)


def thumbnail_command(job: BatchJob, maya_folder: Path, folder: Path, width: int = 384) -> tuple:
    """(program, arguments) of a quick viewport picture of the scene — the middle frame, Hardware 2.0,
    `width` wide — into `folder` as thumb.####.png. No licence, a few seconds after Maya's start."""
    frames = job.frame_list()
    middle = frames[len(frames) // 2]
    scene_width, scene_height = job.resolution()
    height = max(int(width * scene_height / max(scene_width, 1)) // 2 * 2, 2)
    arguments = ["-r", "hw2", "-cam", job.camera_name(), "-rd", str(folder), "-im", "thumb", "-of", "png",
                 "-pad", "4", "-fnc", "3", "-s", str(middle), "-e", str(middle), "-x", str(width), "-y", str(height)]
    arguments += _layer_arguments(job) + [str(Path(job.scene))]
    return str(Path(maya_folder) / "bin" / "Render.exe"), arguments


def command(job: BatchJob, mode: str, maya_folder: Path, task_path: Path, run: tuple | None = None) -> tuple:
    """(program, arguments, extra environment) that run `mode` of `job` with the Maya in `maya_folder`
    (`run`: the frames (first, last) a Render.exe renders — default: the first missing run)."""
    bin_folder = Path(maya_folder) / "bin"
    if mode == "probe":
        return str(bin_folder / "mayapy.exe"), [str(RUNNER), str(task_path)], {}
    renderer = choose_renderer(job)
    if renderer in (HW2, REDSHIFT):
        width, height = job.resolution()
        first, last = run or (missing_runs(job) or [(job.frame_list()[0],) * 2])[0]
        arguments = ["-r", "hw2" if renderer == HW2 else "redshift", "-cam", job.camera_name(),
                     "-rd", str(job.output_folder()), "-im", job.prefix(), "-of", job.image_format,
                     "-pad", "4", "-fnc", "3",
                     "-s", str(first), "-e", str(last), "-x", str(width), "-y", str(height)]
        arguments += _layer_arguments(job) + [str(Path(job.scene))]
        # Not -ehl ("high quality lighting"): in Maya 2024 it breaks the render script
        # (removeRenderLayerAdjustmentAndUnlock.mel: "No object matches name: .enableHighQualityLighting").
        return str(bin_folder / "Render.exe"), arguments, {}
    if job.mode == MODE_WINDOW:
        runner = str(RUNNER).replace("\\", "/")
        script = f'python("exec(open(r\\"{runner}\\").read())")'
        # -log: a windowed Maya's output goes to its Script Editor, not to a pipe — this keeps a copy
        log = Path(task_path).with_name("maya_window.log")
        return str(bin_folder / "maya.exe"), ["-log", str(log), "-command", script], {"MSL_BATCH_TASK": str(task_path)}
    return str(bin_folder / "mayapy.exe"), [str(RUNNER), str(task_path)], {}


def read_progress(path: Path, start: int = 0) -> tuple[list[dict], int]:
    """New events of a runner's progress file from byte `start` on: (events, the next start).
    A line still being written (no newline yet) waits for the next read."""
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            data = handle.read()
    except OSError:
        return [], start
    end = data.rfind(b"\n") + 1
    events = []
    for line in data[:end].splitlines():
        try:
            event = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events, start + end
