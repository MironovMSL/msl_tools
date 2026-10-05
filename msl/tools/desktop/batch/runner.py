# tools/desktop/batch/runner.py
"""Runs the Batch queue: a Maya per job (one at a time), a second one reading scenes meanwhile."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.batch import commands
from msl_tools.msl.core.batch.checks import ERROR, check
from msl_tools.msl.core.batch.frames import FramesError
from msl_tools.msl.core.batch.job import CANCELLED, CHECKING, DONE, FAILED, RUNNING, WAITING, BatchJob
from msl_tools.msl.core.environment.processes import resume_process, suspend_process
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.core.media import FfmpegLocator, MediaError, sequence_to_video
from msl_tools.msl.core.media.sequence import sequence_of
from msl_tools.msl.ui.media import FfmpegRunner


class _MayaProcess(qt.QtCore.QObject):
    """Private: one Maya (mayapy / maya.exe / Render.exe) doing one task for one job. What it does
    is read from the runner's progress file (or, for Render.exe, from the frame files appearing);
    its own output is drained and kept as the tail of a log."""

    event = qt.QtCore.Signal(object)        # a dict from the progress file
    ended = qt.QtCore.Signal(int)           # exit code (-1 = it couldn't start / was killed)

    TAIL = 20_000

    def __init__(self, program: str, arguments: list, environment: dict, progress: Path | None, parent=None):
        super().__init__(parent)
        self.progress = progress
        self._offset = 0
        self.output = ""
        self.process = qt.QtCore.QProcess(self)
        environment_object = qt.QtCore.QProcessEnvironment()
        for name, value in environment.items():
            environment_object.insert(name, str(value))
        self.process.setProcessEnvironment(environment_object)
        self.process.setProgram(program)
        self.process.setArguments(arguments)
        self.process.setStandardInputFile(qt.QtCore.QProcess.nullDevice())
        self.process.setProcessChannelMode(qt.QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._drain)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        self._timer = qt.QtCore.QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.poll)
        self._over = False

    def start(self) -> None:
        self.process.start()
        self._timer.start()

    def pid(self) -> int:
        return int(self.process.processId() or 0)

    def kill(self) -> None:
        if self.process.state() != qt.QtCore.QProcess.ProcessState.NotRunning:
            resume_process(self.pid())  # a frozen process takes the kill too, but don't leave it to chance
            self.process.kill()

    def poll(self) -> None:
        if self.progress is None:
            return
        events, self._offset = commands.read_progress(self.progress, self._offset)
        for event in events:
            self.event.emit(event)

    def _drain(self) -> None:
        text = bytes(self.process.readAllStandardOutput().data()).decode("utf-8", "replace")
        self.output = (self.output + text)[-self.TAIL:]

    def _on_error(self, error) -> None:
        if error == qt.QtCore.QProcess.ProcessError.FailedToStart and not self._over:
            self._over = True
            self._timer.stop()
            self.output += f"\n{self.process.program()} couldn’t be started."
            self.ended.emit(-1)

    def _on_finished(self, code: int, _status) -> None:
        if self._over:
            return
        self._over = True
        self._drain()
        self.poll()
        self._timer.stop()
        self.ended.emit(int(code))


class BatchRunner(qt.QtCore.QObject):
    """The Batch queue at work. `jobs` is the page's list (shared, in queue order).

    - Every job is CHECKED first (probe(): a mayapy reads the scene — tools/maya/batch_runner.py —
      and core/batch/checks.py says what it means); a scene with an ERROR isn't rendered.
      Checks run on their own Maya, also while a render runs.
    - Renders run one at a time, in the list's order, enabled jobs only (start / pause / resume /
      cancel). A job picks up where it stopped: frames already on disk are skipped.
    - The watchdog: a Maya that writes nothing for STALL_S (the first frame: STALL_S + START_S)
      is taken for hung — killed, the job tried again once (RETRIES), then marked failed.
    - Then: with `make_video` the frames become <prefix>.mp4 beside their folder (ffmpeg — the one
      Media uses), and the next job starts.

    Signals:
        changed(str) — that job moved on (state, progress, picture).
        frame(str, str) — a frame of that job was written (its file).
        idle() — nothing left to render (the queue ran through, or was stopped).
        paused_changed(bool)
    """

    changed = qt.QtCore.Signal(str)
    frame = qt.QtCore.Signal(str, str)
    idle = qt.QtCore.Signal()
    paused_changed = qt.QtCore.Signal(bool)

    STALL_S = 15 * 60
    START_S = 5 * 60
    RETRIES = 1
    TICK_MS = 1000

    def __init__(self, jobs: list, save, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self._save = save                     # () -> None: the page keeps the queue on disk
        self.environment = commands.clean_environment()
        self.work_root = Path(tempfile.gettempdir()) / "msl_tools" / "batch"
        self._render: _MayaProcess | None = None
        self._render_job: BatchJob | None = None
        self._probe: _MayaProcess | None = None
        self._probe_job: BatchJob | None = None
        self._running = False
        self._paused = False
        self._last_sign = 0.0                 # when the running Maya last showed it was alive
        self._seen_files: set = set()
        self._retries: dict = {}
        self._video: FfmpegRunner | None = None
        self._video_job: BatchJob | None = None
        self._ffmpeg = None
        self._tick = qt.QtCore.QTimer(self)
        self._tick.setInterval(self.TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

    # --- what is there --------------------------------------------------------------------------

    @staticmethod
    def installed() -> dict:
        return MayaPaths.get_available_installs()

    def maya_for(self, job: BatchJob) -> str:
        return commands.pick_maya(job, self.installed())

    def is_running(self) -> bool:
        return self._running

    def is_paused(self) -> bool:
        return self._paused

    def current(self) -> BatchJob | None:
        return self._render_job

    def find(self, job_id: str) -> BatchJob | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    # --- checking --------------------------------------------------------------------------------

    def probe(self, job: BatchJob) -> None:
        """Reads the scene again (the next probe that is free)."""
        job.probe = {}
        if job.state not in (RUNNING,):
            job.state, job.message = WAITING, ""
        self.changed.emit(job.id)
        self._next_probe()

    def _next_probe(self) -> None:
        if self._probe is not None:
            return
        job = next((job for job in self.jobs if not job.probe and job.state in (WAITING, FAILED)
                    and job is not self._render_job and not job.message.startswith("couldn’t read")), None)
        if job is None:
            return
        year = self.maya_for(job)
        if not year:
            job.state, job.message = FAILED, "couldn’t read the scene: no Maya is installed"
            self.changed.emit(job.id)
            return
        work = self.work_root / job.id
        task = commands.write_task(job, "probe", work)
        program, arguments, extra = commands.command(job, "probe", self.installed()[year], task)
        process = _MayaProcess(program, arguments, dict(self.environment, **extra), work / "probe_progress.jsonl", self)
        process.ended.connect(lambda code, job=job, work=work: self._on_probe_ended(job, work, code))
        self._probe, self._probe_job = process, job
        job.state, job.message = CHECKING, f"reading the scene in Maya {year}…"
        self.changed.emit(job.id)
        process.start()

    def _on_probe_ended(self, job: BatchJob, work: Path, code: int) -> None:
        process, self._probe, self._probe_job = self._probe, None, None
        report = work / "probe.json"
        try:
            job.probe = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            job.probe = {}
        if job.probe:
            issues = check(job)
            errors = [issue for issue in issues if issue.level == ERROR]
            job.state = WAITING
            job.message = (f"{len(errors)} problem{'s' if len(errors) != 1 else ''} — won’t render" if errors else
                           "ready")
        else:
            tail = process.output.strip().splitlines()[-3:] if process is not None else []
            job.state, job.message = FAILED, "couldn’t read the scene" + (": " + " / ".join(tail)[-200:] if tail else "")
        if process is not None:
            process.deleteLater()
        self.changed.emit(job.id)
        self._save()
        self._next_probe()
        if self._running and self._render is None:
            self._next_render()

    # --- rendering --------------------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        if self._paused:
            self.resume()
        self._next_render()

    def stop(self) -> None:
        """No new job starts; the running one is cancelled."""
        self._running = False
        if self._render_job is not None:
            self.cancel(self._render_job.id)

    def pause(self) -> None:
        if self._paused or not self._running:
            return
        self._paused = True
        if self._render is not None:
            suspend_process(self._render.pid())
        self.paused_changed.emit(True)

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if self._render is not None:
            resume_process(self._render.pid())
            self._last_sign = time.monotonic()  # the pause isn't a hang
        self.paused_changed.emit(False)
        self._next_render()

    def cancel(self, job_id: str) -> None:
        job = self.find(job_id)
        if job is None:
            return
        if job is self._render_job and self._render is not None:
            job.state, job.message = CANCELLED, "cancelled"
            self._render.kill()
        elif job is self._probe_job and self._probe is not None:
            self._probe.kill()

    def runnable(self, job: BatchJob) -> bool:
        if not (job.enabled and job.state == WAITING and job.probe):
            return False
        if any(issue.level == ERROR for issue in check(job)):
            return False
        return True

    def _next_render(self) -> None:
        if not self._running or self._paused or self._render is not None or self._video is not None:
            return
        job = next((job for job in self.jobs if self.runnable(job)), None)
        if job is None:
            if not any(job.enabled and job.state in (WAITING, CHECKING) and not job.probe for job in self.jobs):
                self._running = False
                self.idle.emit()
            return
        year = self.maya_for(job)
        try:
            frames = job.frame_list()
        except FramesError as error:
            job.state, job.message = FAILED, str(error)
            self.changed.emit(job.id)
            self._next_render()
            return
        job.output_folder().mkdir(parents=True, exist_ok=True)
        job.state, job.started, job.finished = RUNNING, time.time(), 0.0
        job.done = job.existing_frames()
        job.message = f"starting Maya {year}…" + (" (from where it stopped)" if job.done else "")
        self._seen_files = {str(job.frame_file(frame)) for frame in job.done}
        self._started_at = time.monotonic()
        self._frames_total = len(frames)
        self._launch(job, year)
        self.changed.emit(job.id)

    def _launch(self, job: BatchJob, year: str) -> None:
        """Starts the Maya that renders `job` (a Render.exe: its next run of missing frames)."""
        work = self.work_root / job.id
        task = commands.write_task(job, "render", work)
        program, arguments, extra = commands.command(job, "render", self.installed()[year], task)
        progress = None if commands.uses_render_exe(job) else work / "render_progress.jsonl"
        process = _MayaProcess(program, arguments, dict(self.environment, **extra), progress, self)
        process.event.connect(lambda event, job=job: self._on_event(job, event))
        process.ended.connect(lambda code, job=job: self._on_render_ended(job, code))
        self._render, self._render_job = process, job
        self._render_year = year
        self._files_at_launch = len(self._seen_files)
        self._last_sign = time.monotonic()
        process.start()

    def _on_event(self, job: BatchJob, event: dict) -> None:
        self._last_sign = time.monotonic()
        kind = event.get("event")
        if kind == "scene_open":
            job.message = "the scene is open"
        elif kind == "frame_start":
            job.message = f"rendering frame {event.get('frame')}"
        elif kind == "frame_done":
            self._frame_written(job, int(event["frame"]), str(event.get("file", "")), float(event.get("seconds", 0)))
            return
        elif kind == "frame_failed":
            job.message = f"frame {event.get('frame')} failed: {event.get('error', '')}"
        elif kind == "failed":
            job.message = str(event.get("error", "failed"))
        self.changed.emit(job.id)

    def _frame_written(self, job: BatchJob, frame: int, file: str, seconds: float) -> None:
        if frame not in job.done:
            job.done.append(frame)
        rendered = len(job.done)
        if seconds:
            # the average of Maya's own time per frame (what "time left" is worked out from)
            count = max(rendered, 1)
            job.seconds = round((job.seconds * (count - 1) + seconds) / count, 2)
        job.last_file = file
        job.message = f"frame {frame} done"
        self.changed.emit(job.id)
        self.frame.emit(job.id, file)

    def _on_tick(self) -> None:
        """The frame files of a Render.exe job; the watchdog."""
        job, process = self._render_job, self._render
        if job is None or process is None or self._paused:
            return
        if process.progress is None:  # Render.exe: progress = the files
            self._on_tick_files(job)
        limit = self.STALL_S + (self.START_S if not job.done else 0)
        if time.monotonic() - self._last_sign > limit:
            job.message = f"no sign of life for {int(limit // 60)} min — Maya restarted"
            self._stalled = True
            process.kill()

    def _on_tick_files(self, job: BatchJob) -> None:
        """A Render.exe job's progress: the frame files that appeared since the last look."""
        try:
            frames = job.frame_list()
        except FramesError:
            frames = []
        for frame in frames:
            path = job.frame_file(frame)
            key = str(path)
            if key not in self._seen_files and path.is_file():
                self._seen_files.add(key)
                now = time.monotonic()
                seconds = now - getattr(self, "_last_frame_at", self._started_at)
                self._last_frame_at = now
                self._last_sign = now
                self._frame_written(job, frame, key, round(seconds, 2) if len(job.done) else 0.0)

    def _on_render_ended(self, job: BatchJob, code: int) -> None:
        process, self._render, self._render_job = self._render, None, None
        stalled, self._stalled = getattr(self, "_stalled", False), False
        if process is not None and commands.uses_render_exe(job):
            self._on_tick_files(job)  # the last frame may have landed after the last tick
        if hasattr(self, "_last_frame_at"):
            del self._last_frame_at
        job.finished = time.time()
        try:
            missing = [frame for frame in job.frame_list() if not job.frame_file(frame).is_file()]
        except FramesError:
            missing = []
        tail = process.output.strip().splitlines()[-4:] if process is not None else []
        if process is not None:
            process.deleteLater()
        if job.state != CANCELLED and missing and code == 0 and commands.uses_render_exe(job)                 and len(self._seen_files) > self._files_at_launch:
            self._launch(job, self._render_year)  # that run is rendered: Render.exe for the next one
            self.changed.emit(job.id)
            return
        if job.state == CANCELLED:
            pass
        elif not missing:
            job.state, job.message = DONE, f"{len(job.done)} frames · {self._duration(job)}"
        elif stalled and self._retries.get(job.id, 0) < self.RETRIES:
            self._retries[job.id] = self._retries.get(job.id, 0) + 1
            job.state = WAITING  # tried again at once, from the first missing frame
        else:
            reason = job.message if job.message and not job.message.startswith(("frame ", "rendering", "starting",
                                                                                  "the scene")) else ""
            job.state = FAILED
            job.message = (reason or f"{len(missing)} frame{'s' if len(missing) != 1 else ''} not rendered"
                           + (f" (Maya exited with {code})" if code else "")
                           + (": " + " / ".join(tail)[-200:] if tail and not reason else ""))
        self.changed.emit(job.id)
        self._save()
        if job.state == DONE and job.make_video:
            self._make_video(job)
        else:
            self._next_render()

    @staticmethod
    def _duration(job: BatchJob) -> str:
        seconds = int(max(job.finished - job.started, 0))
        return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"

    # --- the video ----------------------------------------------------------------------------

    def _tools(self):
        if self._ffmpeg is None:
            configured = ""
            try:
                from msl_tools.msl.core.resources import Resources
                path = Resources().fsManager.configsDesktop / "media" / "config.json"
                configured = str(json.loads(path.read_text(encoding="utf-8")).get("settings", {}).get("ffmpeg_path", ""))
            except (OSError, ValueError, AttributeError):
                pass
            self._ffmpeg = FfmpegLocator(configured=configured).find() or False
        return self._ffmpeg or None

    def _make_video(self, job: BatchJob) -> None:
        tools = self._tools()
        sequence = sequence_of(job.last_file) if job.last_file else None
        if tools is None or sequence is None:
            job.message += " · no video (ffmpeg isn’t there)" if tools is None else ""
            self.changed.emit(job.id)
            self._next_render()
            return
        folder = job.output_folder()
        output = folder.parent / f"{folder.name}.mp4"  # named after its frames' folder: two jobs never share one
        fps = {"film": 24.0, "ntsc": 30.0, "pal": 25.0, "ntscf": 60.0, "game": 15.0, "show": 48.0,
               "palf": 50.0}.get(str(job.probe.get("time_unit", "")), 24.0)
        try:
            video = sequence_to_video(sequence, output, fps=fps, quality="high", gaps="hold")
        except MediaError as error:
            job.message += f" · no video: {error}"
            self.changed.emit(job.id)
            self._next_render()
            return
        self._video, self._video_job = FfmpegRunner(self), job
        self._video.finished.connect(self._on_video_done)
        job.message += " · making the video…"
        self.changed.emit(job.id)
        self._video.start(tools, video)

    def _on_video_done(self, ok: bool, message: str) -> None:
        job, runner = self._video_job, self._video
        self._video, self._video_job = None, None
        if runner is not None:
            runner.deleteLater()
        if job is not None:
            job.message = job.message.replace(" · making the video…", "")
            if ok:
                job.video = message
                job.message += f" · {Path(message).name}"
            else:
                job.message += f" · the video failed: {message[:120]}"
            self.changed.emit(job.id)
            self._save()
        self._next_render()

    # --- for the summary ---------------------------------------------------------------------------

    def totals(self) -> dict:
        """Frames and jobs of the enabled queue: done / all, and the seconds still to go (a guess)."""
        frames_done = frames_all = jobs_done = jobs_all = 0
        left = 0.0
        for job in self.jobs:
            if not job.enabled:
                continue
            try:
                count = len(job.frame_list())
            except FramesError:
                continue
            jobs_all += 1
            frames_all += count
            done = len(job.done) if job.state in (RUNNING, DONE) else len(job.existing_frames()) if job.probe else 0
            done = min(done, count)
            frames_done += done
            jobs_done += job.state == DONE
            if job.state != DONE:
                left += (count - done) * (job.seconds or 0)
        return {"frames_done": frames_done, "frames_all": frames_all, "jobs_done": jobs_done, "jobs_all": jobs_all,
                "seconds_left": left}

    def shutdown(self) -> None:
        """The hub closes: every Maya of the queue goes with it (the job goes on from there next time)."""
        for process in (self._render, self._probe):
            if process is not None:
                process.kill()
                process.process.waitForFinished(3000)
        if self._video is not None:
            self._video.cancel()
