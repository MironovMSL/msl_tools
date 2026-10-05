# tools/desktop/batch/page.py
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.batch.job import CANCELLED, CHECKING, DONE, FAILED, RUNNING, BatchJob, BatchStore
from msl_tools.msl.core.environment import system_actions
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.batch.job_details import JobDetails, card
from msl_tools.msl.tools.desktop.batch.job_row import JobRow
from msl_tools.msl.tools.desktop.batch.runner import BatchRunner
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.charts.ring_gauge import RingGauge
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea

StylesheetBuilder.register_template(Path(__file__).with_name("batch.qss"))
SCENE_SUFFIXES = (".ma", ".mb")


class BatchPage(qt.QtWidgets.QWidget):
    """Batch — Maya scenes rendered one after another, nobody opening Maya (core/batch, runner.py,
    the Maya side: tools/maya/batch_runner.py).

    Top to bottom: the summary (two rings — frames and jobs done —, the job and frame at work, the
    time left, the last frame written); the buttons (add scenes, start / stop, pause, "when done");
    the queue (JobRow — scenes are also DROPPED anywhere on the page); the picked job's check and
    settings (JobDetails). A scene is read (checked) by a Maya as soon as it is added; one whose
    check has a problem isn't rendered.

    The queue is kept in configs/desktop/batch/queue.json; a job that was interrupted (the hub
    closed) goes on from its first missing frame.
    """

    TOOL_NAME = "batch"
    PICTURE = qt.QtCore.QSize(160, 90)
    MESSAGE_MS = 9000
    WHEN_DONE = {"": "Nothing", "sound": "Play a sound", "shutdown": "Shut the computer down"}

    def __init__(self, parent=None):
        super().__init__(parent)
        resources = Resources()
        self._config = resources.configsDesktopHubMng.get_config(self.TOOL_NAME, defaults={"settings": {}})
        self._settings = self._config["settings"]
        self._store = BatchStore(resources.configsDesktopHubMng.base_dir / self.TOOL_NAME)
        self.jobs: list[BatchJob] = []
        self._rows: dict[str, JobRow] = {}
        self._selected = ""
        self._loaded = False
        self._shutdown_armed = False
        self._shutdown_at = 0.0
        self.runner = BatchRunner(self.jobs, self._save, self)
        self.setAcceptDrops(True)
        self._build()
        self._connect()
        application = qt.QtCore.QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.runner.shutdown)

    # --- construction ---------------------------------------------------------------------------

    def _build(self) -> None:
        icons = UiResources().iconManager
        title_icon = TintedIcon(icons.get_icon("batch", sub_folder="tools"), 16)
        title_icon.setObjectName("batchCardIcon")
        title = qt.QtWidgets.QLabel("BATCH")
        title.setObjectName("batchCardTitle")
        subtitle = qt.QtWidgets.QLabel("Maya scenes rendered one after another")
        subtitle.setObjectName("batchSubtitle")
        header = qt.QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(title_icon)
        header.addWidget(title)
        header.addWidget(subtitle, 1)

        self._summary = qt.QtWidgets.QFrame()
        self._summary.setObjectName("batchCard")
        self._frames_gauge = RingGauge()
        self._jobs_gauge = RingGauge()
        self._jobs_gauge.setObjectName("ringDone")
        self._now = qt.QtWidgets.QLabel()
        self._now.setObjectName("batchNow")
        self._now.setWordWrap(True)
        self._left = qt.QtWidgets.QLabel()
        self._left.setObjectName("batchSubtitle")
        self._left.setWordWrap(True)
        self._then = qt.QtWidgets.QLabel()
        self._then.setObjectName("batchSubtitle")
        self._picture = qt.QtWidgets.QLabel("the last frame\nshows here")
        self._picture.setObjectName("batchPicture")
        self._picture.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._picture.setFixedSize(self.PICTURE)
        self._picture.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._picture.setToolTip("Click: open the frame")
        self._picture.installEventFilter(self)
        self._picture_file = ""
        texts = qt.QtWidgets.QVBoxLayout()
        texts.setSpacing(2)
        texts.addStretch(1)
        texts.addWidget(self._now)
        texts.addWidget(self._left)
        texts.addWidget(self._then)
        texts.addStretch(1)
        summary = qt.QtWidgets.QHBoxLayout(self._summary)
        summary.setContentsMargins(12, 10, 12, 10)
        summary.setSpacing(12)
        summary.addWidget(self._frames_gauge)
        summary.addWidget(self._jobs_gauge)
        summary.addLayout(texts, 1)
        summary.addWidget(self._picture)

        self._add = qt.QtWidgets.QPushButton("  Add scenes")
        self._add.setIcon(icons.get_icon("file_add", sub_folder="actions"))
        self._start = qt.QtWidgets.QPushButton("Start")
        self._start.setProperty("primary", True)
        self._start.setMinimumWidth(90)
        self._pause = self._glyph("pause", "❚❚", "Pause — the Maya at work is frozen where it is")
        self._bell = self._glyph("bell", "◔", "When the queue is done…")
        self._when_note = qt.QtWidgets.QLabel()
        self._when_note.setObjectName("batchHint")
        drop_hint = qt.QtWidgets.QLabel("or drop .ma / .mb anywhere here")
        drop_hint.setObjectName("batchHint")
        toolbar = qt.QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(self._add)
        toolbar.addWidget(self._start)
        toolbar.addWidget(self._pause)
        toolbar.addWidget(self._bell)
        toolbar.addWidget(self._when_note)
        toolbar.addStretch(1)
        toolbar.addWidget(drop_hint)

        self._message = qt.QtWidgets.QLabel()
        self._message.setObjectName("batchMessage")
        self._message.setWordWrap(True)
        self._message.hide()
        self._message_timer = qt.QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.setInterval(self.MESSAGE_MS)
        self._message_timer.timeout.connect(self._message.hide)

        self._shutdown_bar = qt.QtWidgets.QFrame()
        self._shutdown_bar.setObjectName("batchShutdown")
        self._shutdown_text = qt.QtWidgets.QLabel()
        self._shutdown_cancel = qt.QtWidgets.QPushButton("Cancel the shutdown")
        self._shutdown_cancel.setObjectName("batchLink")
        self._shutdown_cancel.setFlat(True)
        bar = qt.QtWidgets.QHBoxLayout(self._shutdown_bar)
        bar.setContentsMargins(12, 6, 10, 6)
        bar.addWidget(self._shutdown_text, 1)
        bar.addWidget(self._shutdown_cancel)
        self._shutdown_bar.hide()
        self._shutdown_timer = qt.QtCore.QTimer(self)
        self._shutdown_timer.setInterval(1000)
        self._shutdown_timer.timeout.connect(self._tick_shutdown)

        self._jobs_card, jobs_layout, self._jobs_title = card("Queue", "film")
        jobs_layout.setContentsMargins(1, 9, 1, 1)
        self._jobs_title.parentWidget()
        self._holder = qt.QtWidgets.QWidget()
        self._list = qt.QtWidgets.QVBoxLayout(self._holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(0)
        self._empty = qt.QtWidgets.QLabel("Drop Maya scenes here (or “Add scenes”): each is read and checked first, "
                                          "then rendered in turn — Maya stays closed.")
        self._empty.setObjectName("batchHint")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty.setContentsMargins(24, 22, 24, 22)
        self._list.addWidget(self._empty)
        self._list.addStretch(1)
        scroll = StableScrollArea()
        scroll.setObjectName("batchJobs")
        scroll.setWidget(self._holder)
        scroll.setMinimumHeight(150)
        jobs_layout.addWidget(scroll, 1)

        self._details = JobDetails()

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 10)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self._summary)
        layout.addLayout(toolbar)
        layout.addWidget(self._message)
        layout.addWidget(self._shutdown_bar)
        layout.addWidget(self._jobs_card, 1)
        layout.addWidget(self._details)

    @staticmethod
    def _glyph(icon: str, glyph: str, tooltip: str) -> GlyphButton:
        button = GlyphButton(glyph, tooltip, size=qt.QtCore.QSize(28, 24))
        button.setObjectName("batchAction")
        button.set_icon(UiResources().iconManager.get_icon(icon, sub_folder="actions"))
        return button

    def _connect(self) -> None:
        self._add.clicked.connect(self._on_add)
        self._start.clicked.connect(self._on_start)
        self._pause.clicked.connect(self._on_pause)
        self._bell.clicked.connect(self._on_bell)
        self._shutdown_cancel.clicked.connect(self._on_cancel_shutdown)
        self.runner.changed.connect(self._on_job_changed)
        self.runner.frame.connect(self._on_frame)
        self.runner.idle.connect(self._on_idle)
        self.runner.paused_changed.connect(lambda _paused: self._refresh_summary())
        self._details.changed.connect(self._on_details_changed)
        self._details.reread.connect(self._on_reread)
        self._clock = qt.QtCore.QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._refresh_summary)
        self._clock.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._details.set_installed(list(self.runner.installed()))
            for job in self._store.load():
                self._add_job(job, save=False)
            self.runner._next_probe()
            if self.jobs:
                self._pick(self.jobs[0].id)
            self._refresh_summary()

    # --- the queue ---------------------------------------------------------------------------------

    def add_scenes(self, paths) -> None:
        """Puts these scenes at the end of the queue (repeats and non-scenes are left out); each is read."""
        added = 0
        for path in paths:
            path = Path(path)
            if path.suffix.lower() not in SCENE_SUFFIXES or not path.is_file():
                continue
            if any(Path(job.scene) == path and job.state != DONE for job in self.jobs):
                continue
            self._add_job(BatchJob(scene=str(path)))
            added += 1
        if added:
            self._save()
            self.runner._next_probe()
            self._say(f"{added} scene{'s' if added != 1 else ''} added — reading {'them' if added != 1 else 'it'} in Maya…")
        else:
            self._say("Nothing to add: drop Maya scenes (.ma / .mb).", "error")

    def _add_job(self, job: BatchJob, save: bool = True) -> None:
        self.jobs.append(job)
        row = JobRow(job)
        row.picked.connect(self._pick)
        row.toggled.connect(self._on_toggled)
        row.menu_requested.connect(self._on_row_menu)
        self._rows[job.id] = row
        self._list.insertWidget(self._list.count() - 1, row)
        self._empty.hide()
        if save:
            self._save()
        if not self._selected:
            self._pick(job.id)
        self._refresh_summary()

    def _remove(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        if job is None or job.state in (RUNNING, CHECKING):
            return
        self.jobs.remove(job)
        row = self._rows.pop(job_id)
        row.hide()
        row.deleteLater()
        self._empty.setVisible(not self.jobs)
        if self._selected == job_id:
            self._selected = ""
            self._pick(self.jobs[0].id if self.jobs else "")
        self._save()
        self._refresh_summary()

    def _move(self, job_id: str, steps: int) -> None:
        job = self.runner.find(job_id)
        if job is None:
            return
        index = self.jobs.index(job)
        target = min(max(index + steps, 0), len(self.jobs) - 1)
        if target == index:
            return
        self.jobs.insert(target, self.jobs.pop(index))
        row = self._rows[job_id]
        self._list.removeWidget(row)
        self._list.insertWidget(target, row)
        self._save()

    def _pick(self, job_id: str) -> None:
        self._selected = job_id
        for key, row in self._rows.items():
            row.set_selected(key == job_id)
        job = self.runner.find(job_id) if job_id else None
        self._details.show_job(job, self.runner.maya_for(job) if job is not None else "")

    def _save(self) -> None:
        self._store.save(self.jobs)

    # --- what the runner reports ------------------------------------------------------------------

    def _on_job_changed(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        row = self._rows.get(job_id)
        if job is not None and row is not None:
            row.update_job(job)
        if job_id == self._selected and job is not None:
            self._details.show_job(job, self.runner.maya_for(job))
        self._refresh_summary()

    def _on_frame(self, _job_id: str, file: str) -> None:
        self._show_picture(file)

    def _on_idle(self) -> None:
        self._refresh_summary()
        done = [job for job in self.jobs if job.state == DONE and job.finished > self._started_at]
        failed = [job for job in self.jobs if job.state == FAILED and job.finished > self._started_at]
        if done or failed:
            self._say(f"The queue is done: {len(done)} rendered" + (f", {len(failed)} failed." if failed else "."))
            self._after_queue()
        qt.QtWidgets.QApplication.alert(self.window())

    # --- buttons ---------------------------------------------------------------------------------

    def _on_add(self) -> None:
        paths, _filter = qt.QtWidgets.QFileDialog.getOpenFileNames(self, "Maya scenes to render",
                                                                   str(self._settings.get("last_folder", "") or ""),
                                                                   "Maya scenes (*.ma *.mb)")
        if paths:
            self._settings["last_folder"] = str(Path(paths[0]).parent)
            self.add_scenes(paths)

    def _on_start(self) -> None:
        if self.runner.is_running():
            self.runner.stop()
            self._say("Stopped. The frames that are there stay — a start goes on from the first missing one.")
        else:
            for job in self.jobs:
                if job.enabled and job.state in (FAILED, CANCELLED) and job.probe:
                    job.reset()  # tried again — what is rendered is skipped
                    self._on_job_changed(job.id)
            self._started_at = time.time()
            self.runner.start()
            if not self.runner.is_running():
                self._say("Nothing to render: no scene is ready (read, without problems, switched on).", "error")
        self._refresh_summary()

    def _on_pause(self) -> None:
        if self.runner.is_paused():
            self.runner.resume()
        else:
            self.runner.pause()
        self._refresh_summary()

    def _on_toggled(self, job_id: str, enabled: bool) -> None:
        job = self.runner.find(job_id)
        if job is not None:
            job.enabled = enabled
            self._on_job_changed(job_id)
            self._save()

    def _on_details_changed(self, job_id: str) -> None:
        self._on_job_changed(job_id)
        self._save()

    def _on_reread(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        if job is not None:
            self.runner.probe(job)
            self._save()

    def _on_row_menu(self, job_id: str, position) -> None:
        job = self.runner.find(job_id)
        if job is None:
            return
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        busy = job.state in (RUNNING, CHECKING)
        if busy:
            menu.addAction("Cancel").triggered.connect(lambda: self.runner.cancel(job_id))
        else:
            menu.addAction("Read the scene again").triggered.connect(lambda: self._on_reread(job_id))
            if job.state in (DONE, FAILED, CANCELLED):
                menu.addAction("Render again (keeps what is there)").triggered.connect(lambda: self._reset(job_id))
        menu.addAction("Duplicate").triggered.connect(lambda: self._duplicate(job_id))
        menu.addSeparator()
        folder = menu.addAction("Show the frames")
        folder.setEnabled(job.output_folder().is_dir())
        folder.triggered.connect(lambda: ProcessLauncher.open_file_explorer(Path(job.last_file) if job.last_file
                                                                            else job.output_folder()))
        if job.video:
            menu.addAction("Play the video").triggered.connect(lambda: qt.QtGui.QDesktopServices.openUrl(
                qt.QtCore.QUrl.fromLocalFile(job.video)))
        menu.addAction("Show the scene").triggered.connect(lambda: ProcessLauncher.open_file_explorer(Path(job.scene)))
        menu.addSeparator()
        menu.addAction("Sooner").triggered.connect(lambda: self._move(job_id, -1))
        menu.addAction("Later").triggered.connect(lambda: self._move(job_id, 1))
        remove = menu.addAction("Remove from the queue")
        remove.setEnabled(not busy)
        remove.triggered.connect(lambda: self._remove(job_id))
        self._row_menu = menu  # for tests; deletes itself on close
        menu.popup(position)

    def _reset(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        if job is not None:
            job.reset()
            self._on_job_changed(job_id)
            self._save()

    def _duplicate(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        if job is None:
            return
        copy = BatchJob.from_dict({key: value for key, value in job.to_dict().items()
                                   if key not in ("id", "state", "message", "done", "seconds", "last_file", "started",
                                                  "finished", "video")})
        self._add_job(copy)
        self._pick(copy.id)

    # --- the summary ---------------------------------------------------------------------------------

    def _refresh_summary(self) -> None:
        totals = self.runner.totals()
        frames_all, frames_done = totals["frames_all"], totals["frames_done"]
        self._frames_gauge.set_value(frames_done / frames_all if frames_all else 0.0,
                                     f"{int(100 * frames_done / frames_all)}%" if frames_all else "–",
                                     f"frames {frames_done} / {frames_all}")
        self._jobs_gauge.set_value(totals["jobs_done"] / totals["jobs_all"] if totals["jobs_all"] else 0.0,
                                   f"{totals['jobs_done']}/{totals['jobs_all']}", "scenes done")
        job = self.runner.current()
        running, paused = self.runner.is_running(), self.runner.is_paused()
        if job is not None:
            pace = f"  ·  {job.seconds:.1f} s per frame" if job.seconds else ""
            self._now.setText(f"{job.name}  ·  {job.message}{pace}")
        elif running:
            self._now.setText("Waiting for scenes to be read…")
        else:
            ready = sum(1 for job in self.jobs if self.runner.runnable(job))
            enabled = [job for job in self.jobs if job.enabled]
            if not self.jobs:
                self._now.setText("No scenes yet")
            elif enabled and not ready and all(job.state == DONE for job in enabled):
                self._now.setText(f"All {len(enabled)} scene{'s' if len(enabled) != 1 else ''} rendered")
            else:
                self._now.setText(f"{ready} scene{'s' if ready != 1 else ''} ready to render")
        left = totals["seconds_left"]
        if running and left > 0:
            minutes = int(left // 60) + 1
            done_at = time.strftime("%H:%M", time.localtime(time.time() + left))
            self._left.setText(f"about {minutes} min left  ·  done around {done_at}" + ("  ·  PAUSED" if paused else ""))
        else:
            self._left.setText("paused" if paused else "")
        when = self._when_done()
        self._then.setText({"": "", "sound": "then: a sound", "shutdown": "then: shut the computer down"}[when])
        self._when_note.setText("")
        self._start.setText("Stop" if running else "Start")
        self._pause.setVisible(running)
        self._pause.set_icon(UiResources().iconManager.get_icon("play" if paused else "pause", sub_folder="actions"))
        self._pause.setToolTip("Go on" if paused else "Pause — the Maya at work is frozen where it is")

    def _show_picture(self, file: str) -> None:
        pixmap = qt.QtGui.QPixmap(file)
        if pixmap.isNull():
            return
        self._picture_file = file
        ratio = self.devicePixelRatioF()
        scaled = pixmap.scaled(self.PICTURE * ratio, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                               qt.QtCore.Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self._picture.setPixmap(scaled)
        self._picture.setToolTip(f"{file}\nClick: open the frame")

    def eventFilter(self, watched, event) -> bool:
        if watched is self._picture and event.type() == qt.QtCore.QEvent.Type.MouseButtonRelease \
                and self._picture_file:
            qt.QtGui.QDesktopServices.openUrl(qt.QtCore.QUrl.fromLocalFile(self._picture_file))
            return True
        return super().eventFilter(watched, event)

    # --- when the queue is done -----------------------------------------------------------------------

    def _when_done(self) -> str:
        if self._shutdown_armed:
            return "shutdown"
        return "sound" if self._settings.get("when_done") == "sound" else ""

    def _on_bell(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        current = self._when_done()
        for key, title in self.WHEN_DONE.items():
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(lambda _checked=False, key=key: self._set_when_done(key))
        self._bell_menu = menu
        menu.popup(self._bell.mapToGlobal(qt.QtCore.QPoint(0, self._bell.height())))

    def _set_when_done(self, key: str) -> None:
        self._shutdown_armed = key == "shutdown"   # once, for this run — never remembered
        if key != "shutdown":
            self._settings["when_done"] = key
        self._refresh_summary()

    def _after_queue(self) -> None:
        when = self._when_done()
        if when == "sound":
            sounds = system_actions.done_sounds(Resources().fsManager.sounds)
            system_actions.chime(sounds.get("Bells", ""))
        elif when == "shutdown":
            self._shutdown_armed = False
            if system_actions.schedule_shutdown(system_actions.SHUTDOWN_GRACE_S, "MSL Tools: the Batch queue is done."):
                self._shutdown_at = time.monotonic() + system_actions.SHUTDOWN_GRACE_S
                self._shutdown_bar.show()
                self._tick_shutdown()
                self._shutdown_timer.start()
            self._refresh_summary()

    def _tick_shutdown(self) -> None:
        left = max(int(round(self._shutdown_at - time.monotonic())), 0)
        self._shutdown_text.setText(f"The queue is done — the computer shuts down in {left // 60}:{left % 60:02d}.")
        if left <= 0:
            self._shutdown_timer.stop()

    def _on_cancel_shutdown(self) -> None:
        self._shutdown_timer.stop()
        self._shutdown_bar.hide()
        system_actions.cancel_shutdown()
        self._say("Shutdown called off.")

    # --- drops / messages ---------------------------------------------------------------------------

    @staticmethod
    def _scenes_of(event) -> list:
        data = event.mimeData()
        if not data.hasUrls():
            return []
        return [url.toLocalFile() for url in data.urls()
                if url.isLocalFile() and url.toLocalFile().lower().endswith(SCENE_SUFFIXES)]

    def dragEnterEvent(self, event) -> None:
        if self._scenes_of(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._scenes_of(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        scenes = self._scenes_of(event)
        if scenes:
            event.acceptProposedAction()
            self.add_scenes(scenes)

    def open(self, paths) -> None:
        """Scenes handed to the page from outside (the hub, a test)."""
        self.add_scenes(paths)

    def _say(self, text: str, state: str = "") -> None:
        self._message.setText(text)
        if self._message.property("state") != state:
            self._message.setProperty("state", state)
            repolish(self._message)
        self._message.show()
        self._message_timer.start()

    _started_at = 0.0
