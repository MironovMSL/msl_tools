# tools/maya/playblast/panel_run.py
"""The playblast itself: ffmpeg, the capture, the video made in the background."""
import functools
import glob
import json
import shutil
import tempfile
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.fs.manager import FileSystemManager
from msl_tools.msl.core.media import FfmpegLocator, MediaError, find_sequences, run_job, sequence_to_video
from msl_tools.msl.core.media.recipes import gpu_encoding_works
from msl_tools.msl.tools.maya.playblast import capture, naming
from msl_tools.msl.tools.maya.playblast.ending import RunEnding
from msl_tools.msl.ui.workers.result_worker import ResultWorker
from msl_tools.msl.tools.maya.playblast.panel_tables import (BACKGROUNDS, CODECS, FORMAT_MP4, OVERSCAN, QUALITY,
                                                             VIDEO_FORMATS)
from msl_tools.msl.tools.maya.playblast.preview_dialog import PreviewDialog


class _RunMixin:
    """PlayblastPanel's playblast itself: ffmpeg, the capture one frame at a time, the video made
    in the background (methods of PlayblastPanel, moved as they were)."""

    # ------------------------------------------------------------------ ffmpeg

    def _find_ffmpeg(self) -> None:
        """Looks for ffmpeg on a worker (its first start from inside Maya takes a few seconds)."""
        configured = self._configured_ffmpeg()
        worker = ResultWorker(lambda: FfmpegLocator(configured=configured).find())
        worker.done.connect(self._on_ffmpeg)
        worker.failed.connect(self._on_ffmpeg_failed)
        self._keep(worker)
        worker.start()

    @staticmethod
    def _configured_ffmpeg() -> str:
        """The ffmpeg path set in the hub's Media tool ("" = none). Read from its file, never written."""
        try:
            path = FileSystemManager.configsDesktop / "media" / "config.json"
            return str(json.loads(path.read_text(encoding="utf-8")).get("settings", {}).get("ffmpeg_path", "") or "")
        except (OSError, ValueError, AttributeError):
            return ""

    def _on_ffmpeg_failed(self, _error) -> None:
        self._on_ffmpeg(None)

    def _on_ffmpeg(self, tools) -> None:
        self._tools = tools
        self._tools_known = True
        if self._start_when_ready:
            self._start_when_ready = False
            qt.QtCore.QTimer.singleShot(0, self._on_start)
        self._refresh_recent()  # pictures need ffmpeg
        if tools is not None and not getattr(type(self), "_gpu_known", False):
            worker = ResultWorker(functools.partial(gpu_encoding_works, tools))
            worker.done.connect(self._on_gpu_known)
            self._keep(worker)
            worker.start()
        elif getattr(type(self), "_gpu_works", False):
            self._gpu.show()
        if tools is not None:
            self._ffmpeg_note.setText(f"ffmpeg {tools.short_version}")
            self._ffmpeg_note.setToolTip(str(tools.ffmpeg))
        else:
            self._ffmpeg_note.setText("no ffmpeg")
            self._ffmpeg_note.setToolTip("ffmpeg wasn’t found: open Media in the MSL Tools hub to download it.\n"
                                         "Until then a playblast can be saved as frames.")

    @classmethod
    def _keep(cls, worker) -> None:
        workers = cls._workers
        workers.add(worker)
        worker.finished.connect(lambda: workers.discard(worker))

    # ------------------------------------------------------------------ the playblast

    def start(self) -> None:
        """Starts a playblast with what the controls say (what the button does) — also right after
        the panel was made: it waits for ffmpeg to be found first."""
        if self._busy:
            return  # a second press of the "repeat" hotkey must not cancel the playblast going on
        if self._tools is None and not self._tools_known:
            self._start_when_ready = True
            return
        self._on_start()

    def toggle_mask(self) -> None:
        """Shows the shot mask if it is hidden, hides it if it is shown."""
        self._mask_on.setChecked(not self._mask_on.isChecked())

    def _on_start(self) -> None:
        if self._busy:
            if self._session is not None:
                self._cancelled = True  # the button reads "Cancel" while Maya draws
            return
        self.refresh()
        self._save_settings()
        if self._format.current() in VIDEO_FORMATS and self._tools is None:
            self._say("ffmpeg wasn’t found — open Media in the MSL Tools hub to download it, "
                      "or choose “Frames”.", "error")
            return
        self._queue = list(self._several_cameras()) or [self._one_camera()]
        self._next_capture()

    def _next_capture(self) -> None:
        """Starts the capture of the next camera of this run."""
        camera = self._queue.pop(0)
        self._capture_camera = camera
        video = self._format.current() in VIDEO_FORMATS
        width, height = self._frame_size()
        start, end = self._frames()
        target = self._output_path()
        latest = self._latest_path()
        taken = RunEnding.taken  # results still being made have no file yet: their names are taken all the same
        if not self._overwrite.isChecked() or target in taken:
            target = naming.free_path(target, taken)
        taken.add(target)
        self._run_number += 1
        if video:
            frames_folder = (Path(tempfile.gettempdir()) / "msl_tools" / "playblast"
                             / f"{time.strftime('%Y%m%d_%H%M%S')}_{self._run_number}")
            frames_name = "frame"
        else:
            frames_folder, frames_name = target, target.name
        settings = capture.CaptureSettings(
            folder=frames_folder, name=frames_name, start=start, end=end, width=width, height=height,
            camera=camera or capture.ACTIVE_VIEW, ornaments=self._ornaments.isChecked(),
            background=BACKGROUNDS.get(self._background.current()), overscan=OVERSCAN.get(self._overscan.currentText(), 1.0),
            visibility=self._shown_kinds(), smooth=self._smooth.isChecked(), occlusion=self._occlusion.isChecked())
        # everything the end of this playblast needs, as the controls say NOW: by the time its video is
        # made the user may have changed them, or started the next one
        self._run = {"settings": settings, "target": target, "video": video, "latest": latest,
                     "copy": self._copy.isChecked(), "open": self._open.isChecked(),
                     "light": self._light.isChecked() and video, "tools": self._tools,
                     "video_format": VIDEO_FORMATS[self._format.current()][0] if video else "",
                     "codec": CODECS.get(self._codec.currentText(), "h264"),
                     "gpu": self._format.current() == FORMAT_MP4 and self._gpu.isChecked() and self._gpu.isVisible(),
                     "sound": self._sound.isChecked(), "quality": QUALITY.get(self._quality.currentText(), "high"),
                     "started": time.time(), "left": len(self._queue), "id": RunEnding.next_id(),
                     # as they are NOW: another scene may be open by the time the video is made
                     "scene": capture.scene_name() or "untitled", "scene_path": capture.scene_path(),
                     "note": self._mask_note.text().strip()}
        self._set_busy(True)
        self._say("Maya is drawing the frames…")
        # a moment later, so the line above is on screen before Maya takes over (and never
        # processEvents() here: it would run whatever else is waiting in the middle of a click)
        qt.QtCore.QTimer.singleShot(60, self._capture)

    def _capture(self) -> None:
        """Maya draws the frames, one per turn of the event loop — the bar moves and Cancel works —,
        then the video is made on a worker."""
        run = self._run
        settings, target, video = run["settings"], run["target"], run["video"]
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not video and target.is_dir() and self._overwrite.isChecked():
                for old in target.glob(glob.escape(target.name) + ".*.png"):  # "[v2]" in a name isn't a pattern
                    old.unlink()  # a shorter range must not leave the longer one's last frames behind
            self._session = capture.CaptureSession(settings)
        except Exception as error:  # Maya's own RuntimeError too: the panel must never stay "Working…"
            self._capture_failed(str(error) or type(error).__name__)
            return
        self._cancelled = False
        self._progress.set_progress(0)
        self._progress.show()
        self._start_button.setText("Cancel")
        self._start_button.setEnabled(True)
        self._step_timer.start()

    def _capture_step(self) -> None:
        """One frame (the timer's tick)."""
        session = self._session
        if session is None:
            self._step_timer.stop()
            return
        if self._cancelled:
            self._step_timer.stop()
            session.abort()
            self._capture_failed("Cancelled.")
            return
        try:
            more = session.step()
        except Exception as error:  # CaptureError, or Maya's own (another scene opened meanwhile)
            self._step_timer.stop()
            try:
                session.abort()
            except Exception:
                pass
            self._capture_failed(str(error) or type(error).__name__)
            return
        self._progress.set_progress(int(session.done * 100 / session.total))
        camera = f"{self._camera_name()}: " if self._run["left"] or self._several_cameras() else ""
        self._say(f"{camera}frame {session.done} of {session.total}…")
        if more:
            return
        self._step_timer.stop()
        try:
            shot = session.finish()
        except Exception as error:
            self._capture_failed(f"Maya couldn’t finish the playblast: {error}")
            return
        self._session = None
        self._after_capture(shot)

    def _capture_failed(self, message: str) -> None:
        """The capture going on gave up (an error, Cancel): the rest of this run is dropped too."""
        run = self._run
        self._session = None
        self._queue = []
        if run["video"]:
            shutil.rmtree(run["settings"].folder, ignore_errors=True)
        self._free()
        RunEnding.instance().take(dict(run, error=message))

    def _free(self) -> None:
        """No capture is going on any more: the button is the start button again."""
        self._capture_camera = None
        self._run = None
        self._set_busy(False)
        if not self._encodes:
            self._progress.hide()

    def _after_capture(self, shot) -> None:
        """The frames are there. A video is made on a worker — in the BACKGROUND: the panel is free
        at once, for the next camera of this run or for whatever the user does next."""
        run = dict(self._run, frames=shot.frames, camera=shot.camera, error="")
        if run["video"]:
            sound = shot.sound if run["sound"] and shot.sound and Path(shot.sound).is_file() else None
            ending = RunEnding.instance()
            self._encoding.add(run["id"])
            # Nothing of the panel goes along: it may be closed before the video is made.
            # _encode never raises, so `done` always comes — to the ending, in the main thread.
            worker = ResultWorker(functools.partial(type(self)._encode, self._tools, shot, run, sound,
                                                    RunEnding.report_progress))
            worker.done.connect(ending.take)
            self._keep(worker)
            worker.start()
        if self._queue:
            if not run["video"]:
                RunEnding.instance().take(run)
            self._next_capture()
            return
        self._free()
        if run["video"]:
            self._progress.set_progress(0)
            self._progress.show()
            self._say(self._encoding_text())
        else:
            RunEnding.instance().take(run)

    def _on_gpu_known(self, works) -> None:
        """Whether this ffmpeg encodes on the graphics card here (asked once per Maya session)."""
        type(self)._gpu_known, type(self)._gpu_works = True, bool(works)
        if works:
            self._gpu.show()

    def _on_preview_frame(self) -> None:
        """One frame — the current one — as the playblast would draw it, shown in a window: the
        size, the background, the overscan and the shot mask, without the whole range."""
        if self._busy:
            return
        self.refresh()
        self._sync_mask()
        width, height = self._frame_size()
        frame = capture.current_frame()
        camera = self._one_camera()
        folder = Path(tempfile.gettempdir()) / "msl_tools" / "playblast" / f"preview_{time.time_ns()}"
        settings = capture.CaptureSettings(
            folder=folder, name="preview", start=frame, end=frame, width=width, height=height,
            camera=camera or capture.ACTIVE_VIEW, ornaments=self._ornaments.isChecked(),
            visibility=self._shown_kinds(), smooth=self._smooth.isChecked(), occlusion=self._occlusion.isChecked(),
            background=BACKGROUNDS.get(self._background.current()),
            overscan=OVERSCAN.get(self._overscan.currentText(), 1.0))
        try:
            session = capture.CaptureSession(settings)
            try:
                session.step()
            finally:
                session.finish()
            pictures = sorted(folder.glob("*.png"))
            image = qt.QtGui.QImage(str(pictures[0])) if pictures else qt.QtGui.QImage()
        except Exception as error:
            self._say(f"The preview couldn’t be made: {error}", "error")
            return
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        if image.isNull():
            self._say("Maya drew no picture for the preview.", "error")
            return
        # A playblast's PNG keeps the background in its colors but marks it see-through (alpha 0);
        # the video drops the alpha (measured: Gray comes out 91, 91, 91) — so does the preview.
        image = image.convertToFormat(qt.QtGui.QImage.Format.Format_ARGB32)
        image.reinterpretAsFormat(qt.QtGui.QImage.Format.Format_RGB32)
        caption = f"Frame {frame} · {width}×{height} · {self._camera_name()}"
        PreviewDialog.show_for(self.window(), image, caption)

    def _encoding_text(self) -> str:
        return "Making the video…" if self._encodes == 1 else f"Making {self._encodes} videos…"

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        # The window closed mid-capture. Not a SPONTANEOUS hide: minimizing Maya (the window's
        # owner) or another tab in front of a docked panel isn't a reason to throw the frames away.
        if self._session is not None and not event.spontaneous():
            self._step_timer.stop()
            self._session.abort()
            self._capture_failed("Cancelled.")

    @staticmethod
    def _encode(tools, shot, run: dict, sound, report) -> dict:
        """On a worker: the frames in `shot.folder` -> the video `run["target"]`; the frames are removed
        either way. Returns `run` — with `error` set if it failed (never raises: the run it belongs to
        has to come back with the answer)."""
        try:
            sequences = find_sequences(shot.folder)
            if not sequences:
                raise MediaError("Maya wrote no frames.")
            job = sequence_to_video(sequences[0], run["target"], fps=shot.fps, quality=run["quality"], speed="fast",
                                    audio=sound, audio_start=shot.sound_start,
                                    video_format=run.get("video_format") or "mp4", codec=run.get("codec", "h264"),
                                    gpu=bool(run.get("gpu")))
            run_job(tools, job, on_progress=report)
        except Exception as error:
            run = dict(run, error=str(error) or "The video couldn’t be made.")
        finally:
            shutil.rmtree(shot.folder, ignore_errors=True)
        return run

    def _on_encoding_progress(self, fraction: float) -> None:
        if not self._busy:  # while Maya draws frames the bar is the capture's
            self._progress.set_progress(int(fraction * 100))

    @property
    def _encodes(self) -> int:
        """Videos of this panel's runs being made in the background."""
        return len(self._encoding)

    def _on_run_ended(self, run: dict) -> None:
        """A run is over and its end was taken care of (RunEnding): only SHOWN here — the
        status line, the RECENT card. Also for a run a closed window started."""
        self._encoding.discard(run.get("id"))
        capturing = self._busy
        if not capturing and not self._encodes:
            self._progress.hide()
        if not capturing:  # the line belongs to the capture while one is going on
            message = run.get("message", "")
            if self._encodes and run.get("state") == "done":
                message += f" · {self._encoding_text()[:-1].lower()}"
            self._say(message, run.get("state", ""))
            if run.get("state") == "done":
                self._status.setToolTip(str(run["target"]))
                self._refresh_facts()
        if run.get("state") == "done":
            self._refresh_recent()
            if not capturing and not self._encodes:
                qt.QtWidgets.QApplication.alert(self.window())  # the taskbar says so if Maya isn't in front

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._start_button.setEnabled(not busy)
        self._start_button.setText("Working…" if busy else self._start_text)

    @classmethod
    def _sweep_old_frames(cls) -> None:
        """Removes the temporary frame folders a capture left behind (Maya crashed or was closed
        mid-run: nothing else ever deletes them — gigabytes of PNGs). On a worker: it may be a lot."""
        root = Path(tempfile.gettempdir()) / "msl_tools" / "playblast"
        limit = time.time() - cls.FRAMES_KEPT_HOURS * 3600

        def sweep() -> None:
            for folder in root.iterdir() if root.is_dir() else []:
                try:
                    if folder.is_dir() and folder.name[:8].isdigit() and folder.stat().st_mtime < limit:
                        shutil.rmtree(folder, ignore_errors=True)
                except OSError:
                    continue

        worker = ResultWorker(sweep)
        cls._keep(worker)
        worker.start()
