# tools/desktop/batch/page.py
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.batch.checks import choose_renderer
from msl_tools.msl.core.batch.job import CANCELLED, CHECKING, DONE, FAILED, RENDERER_TITLES, RUNNING, BatchJob, BatchStore
from msl_tools.msl.core.batch import environments
from msl_tools.msl.core.batch.frames import FramesError
from msl_tools.msl.core.environment import system_actions
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.batch.job_row import DRAG_MIME, JobRow
from msl_tools.msl.ui.desktop_notice import DesktopNotice
from msl_tools.msl.ui.widgets.windows.image_dialog import ImageDialog
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.tools.desktop.batch.runner import BatchRunner
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.charts.ring_gauge import RingGauge
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.compositions.drop_area import DropArea

StylesheetBuilder.register_template(Path(__file__).with_name("batch.qss"))
SCENE_SUFFIXES = (".ma", ".mb")


def clock(seconds: float) -> str:
    """00:02:14 — hours, minutes, seconds."""
    seconds = max(int(seconds), 0)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def card(title: str, icon: str) -> tuple:
    """(a card frame, the layout for its body, its title label) — the look of the page's cards."""
    frame = qt.QtWidgets.QFrame()
    frame.setObjectName("batchCard")
    heading = qt.QtWidgets.QHBoxLayout()
    heading.setContentsMargins(0, 0, 0, 0)
    heading.setSpacing(8)
    symbol = TintedIcon(UiResources().iconManager.get_icon(icon, sub_folder="actions"), 16)
    symbol.setObjectName("batchCardIcon")
    label = qt.QtWidgets.QLabel(title.upper())
    label.setObjectName("batchCardTitle")
    heading.addWidget(symbol)
    heading.addWidget(label, 1)
    layout = qt.QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(12, 9, 12, 10)
    layout.setSpacing(8)
    layout.addLayout(heading)
    return frame, layout, heading


class BatchPage(qt.QtWidgets.QWidget):
    """Batch — Maya scenes rendered one after another, nobody opening Maya (core/batch, runner.py,
    the Maya side: tools/maya/batch_runner.py). Laid out after the user's reference (a Blender batch
    renderer):

    - RENDER PROGRESS: rings for frames and scenes done, the time left (big, a clock) and the time
      the queue has been running, the last frame's time;
    - CURRENT RENDER: the Maya and renderer at work, the frame, the watchdog, the scene and its
      path, the last frame written (a click opens it);
    - the QUEUE: a JobRow per scene — its settings are chips ON the row (a click changes one), the
      fold arrow shows its check, folder and "then a video". Empty, the queue IS the drop area
      (DropArea, as Media's); with scenes in it, a slim drop strip stays under them. Scenes are
      taken when dropped anywhere on the page;
    - the bottom bar: OUTPUT (the latest word from the Maya at work — Arnold's "60% done"), what
      happens when the queue is done, Start / Pause / Stop.

    The queue is kept in configs/desktop/batch/queue.json; a job that was interrupted (the hub
    closed) goes on from its first missing frame.
    """

    TOOL_NAME = "batch"
    PICTURE = qt.QtCore.QSize(128, 72)
    MESSAGE_MS = 9000
    WHEN_DONE = {"": "Nothing", "sound": "Play a sound", "shutdown": "Shut the computer down"}
    CORES_FREE = (0, 1, 2, 4)   # Arnold leaves that many cores to the person at the computer

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
        self._picture_file = ""
        self._started_at = 0.0
        self.runner = BatchRunner(self.jobs, self._save, self)
        fs = resources.fsManager
        self.runner.gate_config = resources.configsDesktopHubMng.base_dir / "maya_gate" / "config.json"
        self.runner.package_parent = fs.PARENT_DIR
        self.runner.module_folder = fs.msl / "maya_module"
        self._apply_computer_settings()
        self._notice: DesktopNotice | None = None
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

        # RENDER PROGRESS
        progress_card, progress_layout, _heading = card("Render progress", "clock")
        self._frames_gauge = RingGauge()
        self._jobs_gauge = RingGauge()
        self._jobs_gauge.setObjectName("ringDone")
        left_caption = qt.QtWidgets.QLabel("time left")
        left_caption.setObjectName("batchCaption")
        left_caption.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._time_left = qt.QtWidgets.QLabel("--:--:--")
        self._time_left.setObjectName("batchClock")
        self._time_left.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._time_running = qt.QtWidgets.QLabel()
        self._time_running.setObjectName("batchHint")
        self._time_running.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        times = qt.QtWidgets.QVBoxLayout()
        times.setSpacing(1)
        times.addStretch(1)
        times.addWidget(left_caption)
        times.addWidget(self._time_left)
        times.addWidget(self._time_running)
        times.addStretch(1)
        gauges = qt.QtWidgets.QHBoxLayout()
        gauges.setSpacing(4)
        gauges.addWidget(self._frames_gauge)
        gauges.addWidget(self._jobs_gauge)
        gauges.addLayout(times, 1)
        progress_layout.addLayout(gauges)

        # CURRENT RENDER
        current_card, current_layout, _heading = card("Current render", "clapper")
        self._now = qt.QtWidgets.QLabel()
        self._now.setObjectName("batchNow")
        self._now.setWordWrap(True)
        self._engine = qt.QtWidgets.QLabel()
        self._engine.setObjectName("batchSubtitle")
        self._watchdog = qt.QtWidgets.QLabel()
        self._watchdog.setObjectName("batchHint")
        self._scene = ElidedLabel(elide=qt.QtCore.Qt.TextElideMode.ElideLeft)
        self._scene.setObjectName("batchHint")
        self._picture = qt.QtWidgets.QLabel("the last frame")
        self._picture.setObjectName("batchPicture")
        self._picture.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._picture.setFixedSize(self.PICTURE)
        self._picture.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._picture.installEventFilter(self)
        texts = qt.QtWidgets.QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(self._now)
        texts.addWidget(self._engine)
        texts.addWidget(self._watchdog)
        texts.addWidget(self._scene)
        texts.addStretch(1)
        current = qt.QtWidgets.QHBoxLayout()
        current.setSpacing(10)
        current.addLayout(texts, 1)
        current.addWidget(self._picture, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        current_layout.addLayout(current)

        top = qt.QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(progress_card, 4)
        top.addWidget(current_card, 5)

        # QUEUE
        self._jobs_card, jobs_layout, jobs_heading = card("Queue", "film")
        jobs_layout.setContentsMargins(1, 9, 1, 8)
        jobs_heading.setContentsMargins(11, 0, 11, 0)
        self._jobs_title = jobs_heading.itemAt(1).widget()
        self._add = qt.QtWidgets.QPushButton("+ Add scenes")
        self._add.setObjectName("batchLink")
        self._add.setFlat(True)
        self._add.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        jobs_heading.addWidget(self._add)
        self._holder = qt.QtWidgets.QWidget()
        self._list = qt.QtWidgets.QVBoxLayout(self._holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(0)
        self._list.addStretch(1)
        self._scroll = StableScrollArea()
        self._scroll.setObjectName("batchJobs")
        self._scroll.setWidget(self._holder)
        self._drop = DropArea(icons.get_icon("batch", sub_folder="tools"), "Drop Maya scenes here",
                              ".ma / .mb — each is read and checked first, then rendered in turn; Maya stays closed")
        self._drop_file = self._drop.add_button(icons.get_icon("file_add", sub_folder="actions"),
                                                "Choose scenes", "+")
        self._drop_strip = qt.QtWidgets.QPushButton("+  Drop more scenes here — or click to choose")
        self._drop_strip.setObjectName("batchDropStrip")
        self._drop_strip.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        drop_holder = qt.QtWidgets.QHBoxLayout()
        drop_holder.setContentsMargins(11, 0, 11, 0)
        drop_holder.addWidget(self._drop)
        strip_holder = qt.QtWidgets.QHBoxLayout()
        strip_holder.setContentsMargins(11, 4, 11, 0)
        strip_holder.addWidget(self._drop_strip)
        jobs_layout.addWidget(self._scroll, 1)
        jobs_layout.addLayout(drop_holder, 1)
        jobs_layout.addLayout(strip_holder)

        # the message line and the shutdown notice
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

        # the bottom bar
        bottom = qt.QtWidgets.QFrame()
        bottom.setObjectName("batchCard")
        output_caption = qt.QtWidgets.QLabel("OUTPUT")
        output_caption.setObjectName("batchCardTitle")
        self._output = ElidedLabel()
        self._output.setObjectName("batchOutput")
        self._when = qt.QtWidgets.QPushButton()
        self._when.setObjectName("batchChip")
        self._when.setIcon(icons.get_icon("bell", sub_folder="actions"))
        self._when.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._when.setToolTip("What happens when the queue is done")
        self._computer = qt.QtWidgets.QPushButton()
        self._computer.setObjectName("batchChip")
        self._computer.setIcon(icons.get_icon("gpu", sub_folder="actions"))
        self._computer.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._computer.setToolTip("How much of the computer the render takes — so you can keep working")
        self._pause = qt.QtWidgets.QPushButton("Pause")
        self._pause.setIcon(icons.get_icon("pause", sub_folder="actions"))
        self._start = qt.QtWidgets.QPushButton("Start")
        self._start.setProperty("primary", True)
        self._start.setMinimumWidth(96)
        bottom_layout = qt.QtWidgets.QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 7, 10, 7)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(output_caption)
        bottom_layout.addWidget(self._output, 1)
        bottom_layout.addWidget(self._computer)
        bottom_layout.addWidget(self._when)
        bottom_layout.addWidget(self._pause)
        bottom_layout.addWidget(self._start)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 10)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(top)
        layout.addWidget(self._message)
        layout.addWidget(self._shutdown_bar)
        layout.addWidget(self._jobs_card, 1)
        layout.addWidget(bottom)
        self._show_empty()

    def _connect(self) -> None:
        self._add.clicked.connect(self._on_add)
        self._drop_file.clicked.connect(self._on_add)
        self._drop_strip.clicked.connect(self._on_add)
        self._start.clicked.connect(self._on_start)
        self._pause.clicked.connect(self._on_pause)
        self._when.clicked.connect(self._on_when)
        self._computer.clicked.connect(self._on_computer)
        self.runner.tested.connect(self._on_tested)
        self._shutdown_cancel.clicked.connect(self._on_cancel_shutdown)
        self.runner.changed.connect(self._on_job_changed)
        self.runner.frame.connect(self._on_frame)
        self.runner.idle.connect(self._on_idle)
        self.runner.paused_changed.connect(lambda _paused: self._refresh_summary())
        self._clock = qt.QtCore.QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._refresh_summary)
        self._clock.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            for job in self._store.load():
                self._add_job(job, save=False)
            self.runner._next_probe()
            if self.jobs:
                self._pick(self.jobs[0].id)
            self._refresh_summary()

    def _show_empty(self) -> None:
        """Empty, the queue is one big drop area; with scenes, a slim strip under them."""
        empty = not self.jobs
        self._scroll.setVisible(not empty)
        self._drop.setVisible(empty)
        self._drop_strip.setVisible(not empty)
        self._jobs_title.setText(f"QUEUE  ·  {len(self.jobs)}" if self.jobs else "QUEUE")

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
        row = JobRow(job, self.runner.installed(), environments.names(self.runner.gate_config))
        row.picked.connect(self._pick)
        row.split.connect(self._split)
        row.changed.connect(self._on_row_changed)
        row.reread.connect(self._on_reread)
        row.menu_requested.connect(self._on_row_menu)
        self._rows[job.id] = row
        self._list.insertWidget(self._list.count() - 1, row)
        self._show_empty()
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
        if self._selected == job_id:
            self._selected = ""
            if self.jobs:
                self._pick(self.jobs[0].id)
        self._show_empty()
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

    def _save(self) -> None:
        self._store.save(self.jobs)

    # --- what the runner and the rows report ----------------------------------------------------------

    def _on_job_changed(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        row = self._rows.get(job_id)
        if job is not None and row is not None:
            row.set_testing(self.runner.testing(job_id))
            row.update_job(job)
        self._refresh_summary()

    def _on_row_changed(self, job_id: str) -> None:
        self._save()
        self._refresh_summary()

    def _on_reread(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        if job is not None:
            self.runner.probe(job)
            self._save()

    def _on_frame(self, _job_id: str, file: str) -> None:
        self._show_picture(file)

    def _on_idle(self) -> None:
        self._refresh_summary()
        done = [job for job in self.jobs if job.state == DONE and job.finished > self._started_at]
        failed = [job for job in self.jobs if job.state == FAILED and job.finished > self._started_at]
        if done or failed:
            text = f"The queue is done: {len(done)} rendered" + (f", {len(failed)} failed." if failed else ".")
            self._say(text)
            self._after_queue()
            window = self.window()
            if not (self.isVisible() and window.isActiveWindow()):
                if self._notice is None:
                    self._notice = DesktopNotice(UiResources().iconManager.get_icon("hub", sub_folder="brand"), self)
                    self._notice.clicked.connect(self._on_notice_clicked)
                self._notice.show("MSL Tools · Batch", text)
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

    def _on_row_menu(self, job_id: str, position) -> None:
        job = self.runner.find(job_id)
        if job is None:
            return
        row = self._rows[job_id]
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        busy = job.state in (RUNNING, CHECKING)
        if busy:
            menu.addAction("Cancel").triggered.connect(lambda: self.runner.cancel(job_id))
        else:
            menu.addAction("Read the scene again").triggered.connect(lambda: self._on_reread(job_id))
            if job.state in (DONE, FAILED, CANCELLED):
                menu.addAction("Render again (keeps what is there)").triggered.connect(lambda: self._reset(job_id))
        menu.addAction("Hide the check" if row.is_open() else "Show the check").triggered.connect(row.toggle_open)
        test = menu.addMenu("Test frame — one frame, now")
        make_rounded_popup(test)
        try:
            frames = job.frame_list()
        except FramesError:
            frames = []
        test.setEnabled(bool(job.probe) and bool(frames) and not busy and not self.runner.testing(job_id))
        for title, frame in (("first", frames[0] if frames else 0), ("middle", frames[len(frames) // 2] if frames else 0),
                             ("last", frames[-1] if frames else 0)):
            test.addAction(f"The {title} — frame {frame}").triggered.connect(
                lambda _checked=False, frame=frame: self._test(job_id, frame))
        if job.test_file and Path(job.test_file).is_file():
            menu.addAction("Show the last test frame").triggered.connect(lambda: self._show_test(job_id))
        log = menu.addAction("Show Maya’s log")
        log.setEnabled(bool(job.log) and Path(job.log).is_file())
        log.triggered.connect(lambda: self._show_log(job_id))
        menu.addAction("Duplicate").triggered.connect(lambda: self._duplicate(job_id))
        menu.addSeparator()
        folder = menu.addAction("Show the frames")
        folder.setEnabled(job.output_folder().is_dir())
        folder.triggered.connect(lambda: ProcessLauncher.open_file_explorer(Path(job.last_file) if job.last_file
                                                                            else job.output_folder()))
        if job.video and Path(job.video).is_file():
            menu.addAction("Play the video").triggered.connect(lambda: qt.QtGui.QDesktopServices.openUrl(
                qt.QtCore.QUrl.fromLocalFile(job.video)))
            menu.addAction("Open the video in Media").triggered.connect(lambda: self._to_media(job.video))
        menu.addAction("Show the scene").triggered.connect(lambda: ProcessLauncher.open_file_explorer(Path(job.scene)))
        menu.addSeparator()
        menu.addAction("Sooner").triggered.connect(lambda: self._move(job_id, -1))
        menu.addAction("Later").triggered.connect(lambda: self._move(job_id, 1))
        remove = menu.addAction("Remove from the queue")
        remove.setEnabled(not busy)
        remove.triggered.connect(lambda: self._remove(job_id))
        self._row_menu = menu  # for tests; deletes itself on close
        menu.popup(position)

    # --- test frames, logs, Media, one job per camera / layer ------------------------------------------

    def _test(self, job_id: str, frame: int) -> None:
        job = self.runner.find(job_id)
        if job is None:
            return
        problem = self.runner.test_frame(job, frame)
        if problem:
            self._say(problem, "error")
        else:
            self._say(f"Rendering frame {frame} of {job.name} as a test — it opens when it is there.")

    def _on_tested(self, job_id: str, file: str, error: str) -> None:
        job = self.runner.find(job_id)
        if job is None:
            return
        self._on_job_changed(job_id)
        if error:
            self._say(f"The test frame of {job.name} failed: {error}", "error")
            return
        try:
            count = len(job.frame_list())
        except FramesError:
            count = 0
        guess = f" — {count} frames ≈ {self._duration(count * job.test_seconds)}" if count > 1 else ""
        self._say(f"Test frame of {job.name}: {job.test_seconds:.1f} s{guess}.")
        self._show_test(job_id)

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = int(seconds)
        if seconds >= 3600:
            return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"
        return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"

    def _show_test(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        if job is None or not job.test_file:
            return
        image = qt.QtGui.QImage(job.test_file)
        if image.isNull():  # an EXR: Qt has no reader for it
            self._say(f"The test frame is there, as {Path(job.test_file).suffix} — Qt can’t show it: {job.test_file}")
            return
        caption = f"{job.name} · {Path(job.test_file).stem.rsplit('.', 1)[-1]} · {job.test_seconds:.1f} s"
        ImageDialog.show_for(self.window(), image, caption, title="Test frame")

    def _show_log(self, job_id: str) -> None:
        job = self.runner.find(job_id)
        if job is None or not job.log:
            return
        try:
            text = Path(job.log).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            self._say(f"Couldn’t read the log: {error}", "error")
            return
        TextDialog.show_for(self, f"Maya’s log  ·  {job.name}", text[-200_000:] or "(empty)")

    def _to_media(self, video: str) -> None:
        """The video into the hub's Media tool (its sources)."""
        window = self.window()
        open_tool = getattr(window, "open_tool", None)
        if not callable(open_tool):
            return
        open_tool("media")
        from msl_tools.msl.tools.desktop.media.page import MediaPage
        pages = window.findChildren(MediaPage)
        if pages:
            pages[0].open([video])

    def _split(self, job_id: str, kind: str) -> None:
        """A job for every camera (kind "camera") or Render Setup layer ("layer") of this one's scene —
        this job takes the first, copies after it take the rest."""
        job = self.runner.find(job_id)
        if job is None:
            return
        if kind == "camera":
            values = [camera["name"] for camera in job.probe.get("cameras") or [] if not camera.get("startup")]
        else:
            values = list(job.probe.get("render_layers") or [])
        if len(values) < 2:
            return
        setattr(job, kind, values[0])
        self._on_job_changed(job_id)
        index = self.jobs.index(job)
        for offset, value in enumerate(values[1:], start=1):
            data = {key: value_ for key, value_ in job.to_dict().items()
                    if key not in ("id", "state", "message", "done", "seconds", "last_file", "started", "finished",
                                   "video", "test_seconds", "test_file", "log")}
            data[kind] = value
            copy = BatchJob.from_dict(data)
            self._add_job(copy, save=False)
            self._move(copy.id, index + offset - self.jobs.index(copy))
        self._save()
        self._say(f"{job.name}: a job for each of its {len(values)} {kind}s.")

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
        runner = self.runner
        totals = runner.totals()
        frames_all, frames_done = totals["frames_all"], totals["frames_done"]
        self._frames_gauge.set_value(frames_done / frames_all if frames_all else 0.0,
                                     f"{frames_done}/{frames_all}" if frames_all else "–", "frames")
        self._jobs_gauge.set_value(totals["jobs_done"] / totals["jobs_all"] if totals["jobs_all"] else 0.0,
                                   f"{totals['jobs_done']}/{totals['jobs_all']}", "scenes")
        running, paused = runner.is_running(), runner.is_paused()
        left = totals["seconds_left"]
        self._time_left.setText(clock(left) if running and left > 0 else "--:--:--")
        parts = []
        if running and runner.run_started:
            parts.append(f"running {clock(time.monotonic() - runner.run_started)}")
        if runner.last_frame_seconds >= 0.05:
            parts.append(f"last frame {runner.last_frame_seconds:.1f} s")
        if paused:
            parts.append("paused")
        self._time_running.setText("  ·  ".join(parts))
        job = runner.current()
        if job is not None:
            renderer = RENDERER_TITLES.get(choose_renderer(job), "")
            frame = job.message if job.message.startswith(("rendering", "frame")) else job.message
            self._now.setText(f"{job.name}  ·  {frame}")
            self._engine.setText(f"Maya {runner.maya_for(job)} · {renderer} · "
                                 + ("with Maya" if job.mode == "window" and renderer == "Arnold" else "no window"))
            retries = runner._retries.get(job.id, 0)
            self._watchdog.setText(f"watchdog on · restarts {retries} / {runner.RETRIES}"
                                   + (f" · {job.seconds:.1f} s per frame" if job.seconds >= 0.05 else ""))
            self._scene.setText(job.scene)
            self._output.setText(runner.last_output())
        else:
            ready = sum(1 for each in self.jobs if runner.runnable(each))
            enabled = [each for each in self.jobs if each.enabled]
            if not self.jobs:
                self._now.setText("Nothing in the queue")
            elif enabled and not ready and all(each.state == DONE for each in enabled):
                self._now.setText(f"All {len(enabled)} scene{'s' if len(enabled) != 1 else ''} rendered")
            else:
                self._now.setText(f"{ready} scene{'s' if ready != 1 else ''} ready to render")
            self._engine.setText("waiting for scenes to be read…" if running else "")
            self._watchdog.setText("")
            self._scene.setText("")
            if not running:
                self._output.setText("")
        cores = int(self._settings.get("cores_free", 2) or 0)
        self._computer.setText(("low priority" if self.runner.low_priority else "normal priority")
                               + (f" · {cores} free" if cores else ""))
        when = self._when_done()
        self._when.setText({"": "after: nothing", "sound": "after: a sound", "shutdown": "after: shut down"}[when])
        if (self._when.property("tone") or "") != ("warning" if when == "shutdown" else ""):
            self._when.setProperty("tone", "warning" if when == "shutdown" else "")
            repolish(self._when)
        self._start.setText("Stop" if running else "Start")
        if bool(self._start.property("danger")) != running:
            self._start.setProperty("danger", running)   # base.qss: a red primary while it stops
            repolish(self._start)
        self._pause.setVisible(running)
        self._pause.setText("Go on" if paused else "Pause")
        self._pause.setIcon(UiResources().iconManager.get_icon("play" if paused else "pause", sub_folder="actions"))

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

    def _on_notice_clicked(self) -> None:
        window = self.window()
        open_tool = getattr(window, "open_tool", None)
        if callable(open_tool):
            open_tool(self.TOOL_NAME)
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()

    # --- how much of the computer a render takes ------------------------------------------------------

    def _apply_computer_settings(self) -> None:
        self.runner.low_priority = bool(self._settings.get("low_priority", True))
        cores = int(self._settings.get("cores_free", 2) or 0)
        self.runner.threads = -cores if cores else 0

    def _on_computer(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        low = menu.addAction("Low priority — the computer stays smooth")
        low.setCheckable(True)
        low.setChecked(self.runner.low_priority)
        low.triggered.connect(lambda checked: self._set_computer("low_priority", bool(checked)))
        menu.addSeparator()
        current = int(self._settings.get("cores_free", 2) or 0)
        for cores in self.CORES_FREE:
            title = "Arnold takes every core" if not cores else f"Leave {cores} core{'s' if cores != 1 else ''} free"
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(cores == current)
            action.triggered.connect(lambda _checked=False, cores=cores: self._set_computer("cores_free", cores))
        self._computer_menu = menu
        menu.popup(self._computer.mapToGlobal(qt.QtCore.QPoint(0, -menu.sizeHint().height() - 4)))

    def _set_computer(self, key: str, value) -> None:
        self._settings[key] = value
        self._apply_computer_settings()
        self._refresh_summary()
        self._say("For the next Maya the queue starts.")

    # --- when the queue is done -----------------------------------------------------------------------

    def _when_done(self) -> str:
        if self._shutdown_armed:
            return "shutdown"
        return "sound" if self._settings.get("when_done") == "sound" else ""

    def _on_when(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        current = self._when_done()
        for key, title in self.WHEN_DONE.items():
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(lambda _checked=False, key=key: self._set_when_done(key))
        self._when_menu = menu
        menu.popup(self._when.mapToGlobal(qt.QtCore.QPoint(0, -menu.sizeHint().height() - 4)))

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

    def _set_dragging(self, dragging: bool) -> None:
        self._drop.set_dragging(dragging)
        if bool(self._jobs_card.property("dragging")) != dragging:
            self._jobs_card.setProperty("dragging", dragging)   # batch.qss: the queue lights up
            repolish(self._jobs_card)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(DRAG_MIME):
            event.acceptProposedAction()
        elif self._scenes_of(event):
            event.acceptProposedAction()
            self._set_dragging(True)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(DRAG_MIME) or self._scenes_of(event):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_dragging(False)

    def dropEvent(self, event) -> None:
        self._set_dragging(False)
        if event.mimeData().hasFormat(DRAG_MIME):
            event.acceptProposedAction()
            self._drop_row(bytes(event.mimeData().data(DRAG_MIME)).decode(), event.position().toPoint())
            return
        scenes = self._scenes_of(event)
        if scenes:
            event.acceptProposedAction()
            self.add_scenes(scenes)

    def _drop_row(self, job_id: str, position) -> None:
        """A row let go at `position` (page coordinates): it goes before the row under it, or last."""
        job = self.runner.find(job_id)
        if job is None:
            return
        y = self._holder.mapFrom(self, position).y()
        target = len(self.jobs) - 1
        for index, each in enumerate(self.jobs):
            row = self._rows[each.id]
            if y < row.geometry().center().y():
                target = index if index <= self.jobs.index(job) else index - 1
                break
        self._move(job_id, target - self.jobs.index(job))

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
