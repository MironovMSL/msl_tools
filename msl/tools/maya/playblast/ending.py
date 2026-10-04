# tools/maya/playblast/ending.py
"""The end of a playblast that doesn't need its window.

A playblast's video is made in the background, after the panel is free —
and the user may close the window meanwhile (the panel is deleted with it).
What has to happen at the end anyway lives here, in one long-lived object
of the session, not in the panel:

- the "latest" copy ({work+}),
- the record in the history (the RECENT card of any later window),
- the result on the clipboard ("Copy file"), the player ("Open when done"),
- the names of results still on their way (`taken`), shared by every panel.

A panel that is still there listens to `ended` and only SHOWS the outcome
(its status line, its RECENT card); `progressed` carries the encoding's
progress. Both are emitted in Maya's main thread.

The run is a dict the panel builds when a capture starts (see
PlayblastPanel._next_capture): id, target, latest, video, copy, open,
started, scene, scene_path, note, frames, camera, error.
"""
import itertools
import shutil
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.playblast.recent import open_result, size_text

TOOL_NAME = "playblast"
HISTORY_KEPT = 40   # results remembered, all scenes together


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

    _instance = None
    _ids = itertools.count(1)
    # Results on their way: their files aren't there yet, but the names are taken — also for
    # a panel opened after the one that started them was closed.
    taken: set = set()

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
        if run.get("copy"):
            data = qt.QtCore.QMimeData()  # the FILE, as a file manager copies it — and its path as text
            data.setUrls([qt.QtCore.QUrl.fromLocalFile(str(result))])
            data.setText(str(result))
            qt.QtWidgets.QApplication.clipboard().setMimeData(data)
        if run.get("open"):
            open_result(result)
        self.ended.emit(dict(run, message=message, state=state))

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
