# tools/maya/playblast/ending.py
"""The end of a playblast that doesn't need its window.

A playblast's video is made in the background, after the panel is free —
and the user may close the window meanwhile (the panel is deleted with it).
What has to happen at the end anyway lives here, in one long-lived object
of the session, not in the panel:

- the "latest" copy ({work+}),
- the record in the history (the RECENT card of any later window),
- the result on the clipboard ("Copy file"), the player ("Open when done"),
- the names of results still on their way (`taken`), shared by every panel,
- the jobs a finished playblast may lead to (side jobs, `side_done`): a light
  copy for a chat (`<name>_light.mp4`, made after every playblast with "Light
  copy" on, or asked for), a comparison with the previous version
  (`<name>_vs_<previous>.mp4`). They run on workers, also with no window open.

A panel that is still there listens to `ended` and only SHOWS the outcome
(its status line, its RECENT card); `progressed` carries the encoding's
progress. Both are emitted in Maya's main thread.

The run is a dict the panel builds when a capture starts (see
PlayblastPanel._next_capture): id, target, latest, video, copy, open,
started, scene, scene_path, note, frames, camera, error.
"""
import functools
import itertools
import shutil
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import compare, probe, run_job, shrink
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.playblast.recent import open_result, size_text
from msl_tools.msl.ui.workers.result_worker import run_in_background

TOOL_NAME = "playblast"
HISTORY_KEPT = 40   # results remembered, all scenes together
LIGHT_MB = 9.0      # a light copy fits a chat's / mail's limit with room to spare
LIGHT_HEIGHT = 720  # ... and is never taller than this (never scaled up)


def light_copy_path(path: Path) -> Path:
    return Path(path).with_name(f"{Path(path).stem}_light.mp4")


def compare_path(current: Path, previous: Path) -> Path:
    return Path(current).with_name(f"{Path(current).stem}_vs_{Path(previous).stem}.mp4")


def _light_copy(tools, path: Path) -> Path:
    """On a worker: the light copy of `path` — or `path` itself when it is light already."""
    info = probe(tools, path)
    limit = LIGHT_MB * 1024 * 1024
    if info.size <= limit and info.height <= LIGHT_HEIGHT:
        return path
    target = light_copy_path(path)
    # Under the limit already (only too tall): smaller picture at a small quality — fitting it to
    # LIGHT_MB would RAISE its bitrate and make the "light" copy bigger than the playblast.
    job = shrink(info, target, max_height=LIGHT_HEIGHT, target_mb=LIGHT_MB) if info.size > limit else \
        shrink(info, target, max_height=LIGHT_HEIGHT, quality="small")
    run_job(tools, job)
    if target.stat().st_size >= info.size:  # nothing gained: the playblast itself is the light one
        target.unlink()
        return path
    return target


def _compare(tools, previous: Path, current: Path) -> Path:
    """On a worker: the two side by side, the previous one on the left, each named over its half."""
    target = compare_path(current, previous)
    run_job(tools, compare(probe(tools, previous), probe(tools, current), target, labels=True))
    return target


def _side(info: dict, work) -> dict:
    """Runs a side job; its outcome as a dict (never raises: the answer has to come back)."""
    try:
        return dict(info, output=str(work()), state="done")
    except Exception as error:
        return dict(info, output="", state="error", message=str(error) or "It couldn’t be made.")


class RunEnding(qt.QtCore.QObject):
    """See the module docstring. One per Maya session: instance().

    Signals:
        ended(object): a run is over — the run, with "message" and "state"
            ("done" / "error") added for the status line.
        progressed(float): how far the video being made is (0..1); safe to
            emit from the encoding thread.
    """

    ended = qt.QtCore.Signal(object)
    progressed = qt.QtCore.Signal(float)
    # A side job is over: {"kind": "light" | "compare", "source", "output", "state", "message"}.
    side_done = qt.QtCore.Signal(object)

    _instance = None
    _ids = itertools.count(1)
    # Results on their way: their files aren't there yet, but the names are taken — also for
    # a panel opened after the one that started them was closed.
    taken: set = set()
    # Running side jobs: kept by the class, parentless (a QThread destroyed while it runs takes Maya down).
    _workers: set = set()

    @classmethod
    def instance(cls) -> "RunEnding":
        # Parentless and kept by the class: it must outlive every window. Made in Maya's main
        # thread (by the first panel), so slots connected to it run there.
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def next_id(cls) -> int:
        return next(cls._ids)

    @classmethod
    def report_progress(cls, fraction: float, _progress=None) -> None:
        """run_job's `on_progress(fraction, progress)`, from the encoding thread -> `progressed`."""
        cls.instance().progressed.emit(float(fraction))

    def take(self, run: dict) -> None:
        """A run is over (a video made, frames written, or an error): does what its end needs,
        then tells whoever listens. Called in the main thread — a worker's `done` is queued here."""
        self.taken.discard(run.get("target"))
        logger = Resources().logsMaya.get(TOOL_NAME)
        if run.get("error"):
            logger.warning(f"Playblast failed: {run['error']}")
            self.ended.emit(dict(run, message=run["error"], state="error"))
            return
        result = Path(run["target"])
        note = size_text(result.stat().st_size) if result.is_file() else f"{run.get('frames', 0)} frames"
        message = " · ".join(("Done", note, f"{time.time() - run['started']:.1f} s"))
        state = "done"
        error = self._write_latest(result, run.get("latest"))
        if error:
            message, state = f"Done — but the latest copy couldn’t be written: {error}", "error"
        self._remember(run, result)
        light = bool(run.get("light")) and result.is_file() and run.get("tools") is not None
        if light:  # its own end comes later (side_done): the clipboard then gets the light copy
            message += " · making a light copy…"
            self.make_light_copy(result, run["tools"], copy=bool(run.get("copy")))
        if run.get("copy") and not light:
            data = qt.QtCore.QMimeData()  # the FILE, as a file manager copies it — and its path as text
            data.setUrls([qt.QtCore.QUrl.fromLocalFile(str(result))])
            data.setText(str(result))
            qt.QtWidgets.QApplication.clipboard().setMimeData(data)
        if run.get("open"):
            open_result(result)
        self.ended.emit(dict(run, message=message, state=state))

    # --- side jobs -------------------------------------------------------------------------

    def make_light_copy(self, path, tools, copy: bool = False) -> None:
        """`<name>_light.mp4` next to `path` (see LIGHT_MB); `copy` puts it on the clipboard as a file."""
        self._side_job({"kind": "light", "source": str(path), "copy": copy},
                       functools.partial(_light_copy, tools, Path(path)))

    def compare_with(self, current, previous, tools) -> None:
        """`<current>_vs_<previous>.mp4` beside `current`, then opened in the player."""
        self._side_job({"kind": "compare", "source": str(current), "previous": str(previous), "open": True},
                       functools.partial(_compare, tools, Path(previous), Path(current)))

    def _side_job(self, info: dict, work) -> None:
        # on_done is a bound method of this main-thread object: queued here
        run_in_background(functools.partial(_side, info, work), self._on_side_done, keep=RunEnding._workers)

    def _on_side_done(self, result: dict) -> None:
        if result.get("state") == "done":
            output = Path(result["output"])
            if result.get("kind") == "light":
                same = output == Path(result["source"])
                result["message"] = (f"Light enough already ({size_text(output.stat().st_size)}) — no copy needed"
                                     if same else f"Light copy · {size_text(output.stat().st_size)} · {output.name}")
            else:
                result["message"] = f"Compared with {Path(result.get('previous', '')).name} · {output.name}"
            if result.get("copy"):
                data = qt.QtCore.QMimeData()
                data.setUrls([qt.QtCore.QUrl.fromLocalFile(str(output))])
                data.setText(str(output))
                qt.QtWidgets.QApplication.clipboard().setMimeData(data)
                result["message"] += " · on the clipboard"
            if result.get("open"):
                open_result(output)
        else:
            Resources().logsMaya.get(TOOL_NAME).warning(f"Playblast {result.get('kind')}: {result.get('message')}")
        self.side_done.emit(result)

    @staticmethod
    def _write_latest(result: Path, latest) -> str:
        """The {work+} copy without a version; "" when done (or not wanted), else the error."""
        if latest is None:
            return ""
        latest = Path(latest)
        try:
            if result.is_dir():
                shutil.rmtree(latest, ignore_errors=True)
                shutil.copytree(result, latest)
            else:
                latest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(result, latest)
        except OSError as error:
            return str(error)
        return ""

    @staticmethod
    def _remember(run: dict, result: Path) -> None:
        """The history record, with the scene and note as they were when the capture STARTED —
        another scene may be open by the time the video is made."""
        config = Resources().configsMayaMng.get_config(TOOL_NAME)
        try:
            history = [dict(entry) for entry in config["history"]]
        except (KeyError, TypeError, ValueError):
            history = []
        entry = {"path": str(result), "scene": run.get("scene") or "untitled",
                 "scene_path": run.get("scene_path", ""), "camera": run.get("camera", ""),
                 "frames": int(run.get("frames", 0)), "time": time.time(), "note": run.get("note", "")}
        kept = [old for old in history if old.get("path") != entry["path"]]
        config["history"] = (kept + [entry])[-HISTORY_KEPT:]
