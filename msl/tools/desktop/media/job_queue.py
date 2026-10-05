# tools/desktop/media/job_queue.py
import time
from dataclasses import dataclass, field
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job
from msl_tools.msl.core.media.run import clean_up
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.tools.desktop.media.history import ResultRecord
from msl_tools.msl.tools.desktop.media.source import result_thumbnail
from msl_tools.msl.ui.media import FfmpegRunner
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.workers.result_worker import ResultWorker, run_in_background
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea

WAITING, RUNNING, DONE, FAILED, CANCELLED = "waiting", "running", "done", "failed", "cancelled"


@dataclass
class QueueItem:
    """One job of the queue and where it stands.

    Attributes:
        id: Its number in this session.
        job: What ffmpeg is asked to do.
        command: The command as text (for "Command").
        state: WAITING / RUNNING / DONE / FAILED / CANCELLED.
        fraction: 0..1 while running (-1 = unknown).
        speed: Times faster than real time, while running.
        message: Why it failed.
        seconds: How long it ran.
        size: Bytes of the result (of everything in it, when the result is a folder).
        files: How many files the result holds (a folder of frames; 0 for one file).
        source_size: Bytes of what the job was made from (0 = nothing to compare the result with).
        finished: When it was over (seconds since the epoch; 0 while it isn't).
        gone: A result from an earlier run of the hub whose file isn't there any more.
        thumbnail: A small picture of the result, once it was made (None: not yet, or it has none).
        recipe: What made it — {"action", "settings", "sources"} — so it can be set up again ({} = unknown).
    """

    id: int
    job: Job
    command: str = ""
    state: str = WAITING
    fraction: float = 0.0
    speed: float = 0.0
    message: str = ""
    seconds: float = 0.0
    size: int = 0
    files: int = 0
    source_size: int = 0
    finished: float = 0.0
    gone: bool = False
    thumbnail: Path | None = None
    recipe: dict = field(default_factory=dict)


class JobQueue(qt.QtCore.QObject):
    """Runs the Media tool's jobs one after another (FfmpegRunner), in the
    order they were added. `tools` is asked for (a callable) at the moment a
    job starts — the ffmpeg in use may change while jobs wait.

    A BATCH is everything added since the queue was last idle: overall()
    is how far that batch is (for one progress bar over all of it), and
    last_batch() — read when `idle` fires — is what just ended.

    Results of earlier runs of the hub come back through restore() as
    finished items; results() is what there is to keep for the next run.

    Every finished result gets a small picture (QueueItem.thumbnail), made
    one after another on a worker thread; `changed` follows when one is
    there. refresh_thumbnails() makes the ones still owed — call it when
    ffmpeg becomes available.

    Signals:
        added(object) / changed(object) — a QueueItem appeared / moved on.
        removed(int) — the item with this id is gone from the queue.
        idle() — the last job of the line is over (nothing waits or runs).
    """

    added = qt.QtCore.Signal(object)
    changed = qt.QtCore.Signal(object)
    removed = qt.QtCore.Signal(int)
    moved = qt.QtCore.Signal()   # the order of the jobs changed
    idle = qt.QtCore.Signal()

    def __init__(self, tools, parent=None):
        super().__init__(parent)
        self._tools = tools
        self._items: list[QueueItem] = []
        self._next_id = 1
        self._current: QueueItem | None = None
        self._started = 0.0
        self._batch: list[QueueItem] = []
        self._last_batch: list[QueueItem] = []
        self._thumbnails_owed: list[QueueItem] = []
        self._thumbnail_worker: ResultWorker | None = None
        self._thumbnail_workers: list = []
        self._runner = FfmpegRunner(self)
        self._runner.progressed.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)

    def items(self) -> list[QueueItem]:
        return list(self._items)

    def outputs(self) -> list[Path]:
        """Files the jobs that aren't over yet will write (so a new job picks another name)."""
        return [item.job.output for item in self._items if item.state in (WAITING, RUNNING)]

    def add(self, job: Job, source_size: int = 0, recipe: dict | None = None) -> QueueItem:
        """Puts `job` at the end of the line. `source_size`: bytes of what it
        is made from — the finished row then says how much smaller the result
        is. `recipe`: what made it ({"action", "settings", "sources"}), kept
        with the result so it can be set up again."""
        tools = self._tools()
        item = QueueItem(id=self._next_id, job=job, command=job.command_text(tools), source_size=int(source_size),
                         recipe=dict(recipe or {}))
        self._next_id += 1
        self._items.append(item)
        self._batch.append(item)
        self.added.emit(item)
        self._start_next()
        self._check_idle()
        return item

    def restore(self, records: list) -> None:
        """Shows results of earlier runs (ResultRecords, oldest first) as finished jobs."""
        for record in records:
            output = Path(record.output)
            job = Job(title=record.title, output=output, passes=[], folder=output if record.folder else None)
            item = QueueItem(id=self._next_id, job=job, state=DONE, fraction=1.0, seconds=record.seconds,
                             size=record.size, files=record.files, source_size=record.source_size,
                             finished=record.finished, gone=not output.exists(), recipe=dict(record.recipe or {}))
            self._next_id += 1
            self._items.append(item)
            self.added.emit(item)
            if not item.gone:
                self._thumbnails_owed.append(item)
        self._next_thumbnail()

    def refresh_thumbnails(self) -> None:
        """Makes the pictures still owed (they wait while there is no ffmpeg)."""
        self._next_thumbnail()

    def _next_thumbnail(self) -> None:
        tools = self._tools()
        if self._thumbnail_worker is not None or not self._thumbnails_owed or tools is None:
            return
        item = self._thumbnails_owed.pop(0)
        if item not in self._items:
            self._next_thumbnail()
            return
        output = item.job.output

        def done(path) -> None:
            if path is not None and item in self._items:
                item.thumbnail = path
                self.changed.emit(item)

        def over() -> None:
            self._thumbnail_worker = None
            self._next_thumbnail()

        self._thumbnail_worker = run_in_background(lambda: result_thumbnail(tools, output), done,
                                                   keep=self._thumbnail_workers, parent=self)
        self._thumbnail_worker.finished.connect(over)

    def busy(self) -> bool:
        """Jobs wait or run."""
        return bool(self._batch)

    def batch_counts(self) -> tuple:
        """(jobs of the current batch that are over, jobs in it) — (0, 0) while idle."""
        return sum(1 for item in self._batch if item.state not in (WAITING, RUNNING)), len(self._batch)

    def results(self) -> list:
        """The finished jobs whose result is still there, oldest first, as ResultRecords."""
        return [ResultRecord(title=item.job.title, output=str(item.job.output), folder=item.job.folder is not None,
                             size=item.size, files=item.files, seconds=round(item.seconds, 1),
                             source_size=item.source_size, finished=item.finished, recipe=item.recipe)
                for item in self._items if item.state == DONE and not item.gone]

    def run_next(self, item_id: int) -> None:
        """A waiting job goes to the front of the line: it starts as soon as the running one is over."""
        item = self._find(item_id)
        if item is None or item.state != WAITING:
            return
        first = next((other for other in self._items if other.state == WAITING), None)
        if first is item:
            return
        self._items.remove(item)
        self._items.insert(self._items.index(first), item)
        self.moved.emit()

    def overall(self) -> float:
        """How far the current batch is, 0..1 (1 when nothing waits or runs)."""
        if not self._batch:
            return 1.0
        over = sum(1.0 for item in self._batch if item.state not in (WAITING, RUNNING))
        running = max(self._current.fraction, 0.0) if self._current is not None else 0.0
        return min((over + running) / len(self._batch), 1.0)

    def last_batch(self) -> list[QueueItem]:
        """The jobs of the batch that ended last."""
        return list(self._last_batch)

    def cancel(self, item_id: int) -> None:
        """Stops a running job, or takes a waiting one out of the line."""
        item = self._find(item_id)
        if item is None:
            return
        if item is self._current:
            self._runner.cancel()
        elif item.state == WAITING:
            item.state = CANCELLED
            for path in item.job.temporary:
                try:
                    Path(path).unlink()
                except OSError:
                    pass
            self.changed.emit(item)
            self._check_idle()

    def remove(self, item_id: int) -> None:
        """Takes a job that is over off the list (its result file stays)."""
        item = self._find(item_id)
        if item is not None and item.state not in (WAITING, RUNNING):
            self._items.remove(item)
            self.removed.emit(item_id)

    def clear_finished(self) -> None:
        for item in [item for item in self._items if item.state not in (WAITING, RUNNING)]:
            self.remove(item.id)

    def _find(self, item_id: int) -> QueueItem | None:
        return next((item for item in self._items if item.id == item_id), None)

    def _start_next(self) -> None:
        if self._current is not None:
            return
        item = next((item for item in self._items if item.state == WAITING), None)
        if item is None:
            return
        tools = self._tools()
        if tools is None:
            clean_up(item.job, remove_output=False)  # its burn-in texts / frame lists are files
            item.state, item.message = FAILED, "ffmpeg isn’t available."
            self.changed.emit(item)
            self._start_next()
            return
        self._current, self._started = item, time.time()
        item.state, item.fraction = RUNNING, 0.0
        self.changed.emit(item)
        self._runner.start(tools, item.job)

    def _on_progress(self, fraction: float, progress) -> None:
        if self._current is not None:
            self._current.fraction, self._current.speed = fraction, progress.speed
            self.changed.emit(self._current)

    def _on_finished(self, ok: bool, message: str) -> None:
        item, self._current = self._current, None
        if item is not None:
            item.finished = time.time()
            item.seconds = item.finished - self._started
            if ok:
                item.state, item.fraction = DONE, 1.0
                try:
                    if item.job.folder is not None:
                        sizes = [entry.stat().st_size for entry in item.job.folder.iterdir() if entry.is_file()]
                        item.size, item.files = sum(sizes), len(sizes)
                    else:
                        item.size = item.job.output.stat().st_size
                except OSError:
                    item.size = 0
                self._thumbnails_owed.append(item)
            elif message == "Cancelled.":
                item.state = CANCELLED
            else:
                item.state, item.message = FAILED, message
            self.changed.emit(item)
        self._start_next()
        self._check_idle()
        self._next_thumbnail()

    def _check_idle(self) -> None:
        """The batch is over once nothing of it waits or runs."""
        if self._batch and self._current is None and all(item.state != WAITING for item in self._batch):
            self._last_batch, self._batch = self._batch, []
            self.idle.emit()


def _size_text(size: int) -> str:
    megabytes = size / 1024 ** 2
    return f"{megabytes:.1f} MB" if megabytes >= 1 else f"{size / 1024:.0f} KB"


class _ResultLabel(qt.QtWidgets.QLabel):
    """Private: a job's title. Once the job is done it is a handle on the
    RESULT FILE: a click opens it (plays it), and it can be dragged — into
    a chat, a folder, another program — like a file from the file manager."""

    activated = qt.QtCore.Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("mediaJobTitle")
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._path = ""            # the result file; "" while there is none
        self._pressed = False
        self._press_position = qt.QtCore.QPoint()

    def set_result(self, path: str) -> None:
        self._path = path
        if path:
            self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        if bool(self.property("link")) != bool(path):
            self.setProperty("link", bool(path))  # media.qss: QLabel#mediaJobTitle[link="true"]:hover
            repolish(self)

    def drag_data(self) -> qt.QtCore.QMimeData:
        """What a drag (or "Copy") of the result carries: the file, and its path as text."""
        data = qt.QtCore.QMimeData()
        data.setUrls([qt.QtCore.QUrl.fromLocalFile(self._path)])
        data.setText(self._path)
        return data

    def mousePressEvent(self, event) -> None:
        if self._path and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            self._press_position = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed and (event.position().toPoint() - self._press_position).manhattanLength() \
                >= qt.QtWidgets.QApplication.startDragDistance():
            self._pressed = False  # it became a drag: the release that follows is not a click
            drag = qt.QtGui.QDrag(self)
            drag.setMimeData(self.drag_data())
            drag.exec(qt.QtCore.Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _JobRow(qt.QtWidgets.QFrame):
    """Private: one job of the list — a state dot, the NAME OF ITS RESULT
    (what it is made from is in the tooltip: with both names the line was
    too long to read), where it stands; while it runs, the row itself is
    filled from the left as far as the job is.
    When it is done the name is the result file itself (click = open, drag
    = take it somewhere) with a play button in front of it; the icon
    buttons copy the file to the clipboard and show it in its folder; a right click has the rest (the command,
    the path, remove)."""

    COPIED_MS = 1500
    BUTTON_SIZE = qt.QtCore.QSize(26, 22)
    APPEAR_MS = 170

    # A running job fills its row from the left as far as it is (media.qss sets the color).
    progressColor = color_property("_progress_color")
    THUMBNAIL_SIZE = qt.QtCore.QSize(40, 23)   # the slot of the state dot / the result's picture
    THUMBNAIL_RADIUS = 3

    cancel_requested = qt.QtCore.Signal(int)
    remove_requested = qt.QtCore.Signal(int)
    again_requested = qt.QtCore.Signal(int)
    run_next_requested = qt.QtCore.Signal(int)
    show_requested = qt.QtCore.Signal(int)
    open_requested = qt.QtCore.Signal(int)
    command_requested = qt.QtCore.Signal(int)

    def __init__(self, item: QueueItem, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaJob")
        self.item_id = item.id
        self._state = ""
        self._fraction: float | None = None   # None = not running; < 0 = running, how far isn't known
        self._progress_color = qt.QtGui.QColor(ThemeRegistry.fallback().accent)  # until QSS applies
        self._progress_color.setAlpha(40)
        self._appear: qt.QtCore.QPropertyAnimation | None = None
        self._has_command = bool(item.command)  # a result restored from an earlier run has none
        self._dot = qt.QtWidgets.QLabel()
        self._dot.setObjectName("mediaJobDot")
        self._dot.setFixedSize(8, 8)
        # One slot for both: the state dot while there is nothing to show, then the result's picture.
        self._picture = qt.QtWidgets.QLabel()
        self._picture.setFixedSize(self.THUMBNAIL_SIZE)
        self._picture_path: Path | None = None
        self._slot = qt.QtWidgets.QWidget()
        self._slot.setFixedSize(self.THUMBNAIL_SIZE)
        slot = qt.QtWidgets.QHBoxLayout(self._slot)
        slot.setContentsMargins(0, 0, 0, 0)
        slot.setSpacing(0)
        slot.addWidget(self._dot, 0, qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        slot.addWidget(self._picture)
        self._picture.hide()
        self._title = _ResultLabel(item.job.output.name + ("/" if item.job.folder is not None else ""))
        self._status = qt.QtWidgets.QLabel()
        self._status.setObjectName("mediaJobStatus")
        self._status.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._status.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignRight | qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        # in front of the name: says that a click plays it (a folder of frames: opens the folder)
        self._play_button = self._button("play", "▶", "Open it — a video plays in your player")
        if item.job.folder is not None:
            self._play_button.set_icon(UiResources().iconManager.get_icon("image_stack", sub_folder="actions"))
            self._play_button.setToolTip("Open the folder with the frames")
        policy = self._play_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # the names of all rows start at the same place
        self._play_button.setSizePolicy(policy)
        self._copy_button = self._button("copy", "⧉", "Copy the file — then paste it into a chat or a folder (Ctrl+V)")
        self._show_button = self._button("browse", "▸", "Show the result in its folder")
        self._cancel_button = self._button("stop", "■", "Cancel this job")
        self._remove_button = self._button("clear", "✕", "Take this line off the list (the result file stays)")
        self._again_button = self._button("restart", "↻", "Set it up again: its video and its settings, on the "
                                                          "page — change what you like and start")
        self._has_recipe = bool(item.recipe)
        self._title.activated.connect(lambda: self.open_requested.emit(self.item_id))
        self._play_button.clicked.connect(lambda: self.open_requested.emit(self.item_id))
        self._copy_button.clicked.connect(self.copy_file)
        self._show_button.clicked.connect(lambda: self.show_requested.emit(self.item_id))
        self._cancel_button.clicked.connect(lambda: self.cancel_requested.emit(self.item_id))
        self._remove_button.clicked.connect(lambda: self.remove_requested.emit(self.item_id))
        self._again_button.clicked.connect(lambda: self.again_requested.emit(self.item_id))

        line = qt.QtWidgets.QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(self._slot)
        line.addWidget(self._play_button)
        # Both give way in a narrow window - the name less than what is said about it.
        line.addWidget(self._title, 3)
        line.addWidget(self._status, 2)
        line.addWidget(self._again_button)
        line.addWidget(self._copy_button)
        line.addWidget(self._show_button)
        line.addWidget(self._cancel_button)
        line.addWidget(self._remove_button)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(line)
        self.update_item(item)

    def appear(self) -> None:
        """Grows into place instead of popping in (for a job that was just added)."""
        height = self.sizeHint().height()
        self.setMaximumHeight(0)
        self._appear = qt.QtCore.QPropertyAnimation(self, b"maximumHeight", self)
        self._appear.setDuration(self.APPEAR_MS)
        self._appear.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._appear.setStartValue(0)
        self._appear.setEndValue(height)
        self._appear.finished.connect(lambda: self.setMaximumHeight(16777215))  # QWIDGETSIZE_MAX: free again
        self._appear.start()

    def paintEvent(self, event) -> None:
        if self._fraction is not None:
            painter = qt.QtGui.QPainter(self)
            width = self.width() * (min(max(self._fraction, 0.0), 1.0) if self._fraction >= 0 else 1.0)
            color = qt.QtGui.QColor(self._progress_color)
            if self._fraction < 0:
                color.setAlpha(color.alpha() // 2)  # how far isn't known: the whole row, fainter
            painter.fillRect(qt.QtCore.QRectF(0, 0, width, self.height()), color)
            painter.end()
        super().paintEvent(event)

    def _show_picture(self, path: Path | None) -> None:
        """The result's picture in the slot (cropped to fill it, corners rounded) — or the state dot."""
        if path is None:
            self._picture.hide()
            self._dot.show()
            return
        if path != self._picture_path:
            source = qt.QtGui.QPixmap(str(path))
            if source.isNull():
                return
            ratio = self.devicePixelRatioF()
            size = self.THUMBNAIL_SIZE * ratio
            scaled = source.scaled(size, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   qt.QtCore.Qt.TransformationMode.SmoothTransformation)
            picture = qt.QtGui.QPixmap(size)
            picture.fill(qt.QtCore.Qt.GlobalColor.transparent)
            painter = qt.QtGui.QPainter(picture)
            painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
            clip = qt.QtGui.QPainterPath()
            clip.addRoundedRect(qt.QtCore.QRectF(0, 0, size.width(), size.height()),
                                self.THUMBNAIL_RADIUS * ratio, self.THUMBNAIL_RADIUS * ratio)
            painter.setClipPath(clip)
            painter.drawPixmap((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
            painter.end()
            picture.setDevicePixelRatio(ratio)
            self._picture.setPixmap(picture)
            self._picture_path = path
        self._dot.hide()
        self._picture.show()

    def _button(self, icon: str, glyph: str, tooltip: str) -> GlyphButton:
        button = GlyphButton(glyph, tooltip, size=self.BUTTON_SIZE)
        button.setObjectName("mediaAction")  # media.qss: accent icons
        button.set_icon(UiResources().iconManager.get_icon(icon, sub_folder="actions"))
        return button

    def update_item(self, item: QueueItem) -> None:
        state = self._state = item.state
        look = "gone" if item.gone else state
        if self._dot.property("state") != look:
            self._dot.setProperty("state", look)         # media.qss: QLabel#mediaJobDot[state=...]
            self._status.setProperty("state", look)
            repolish(self._dot)
            repolish(self._status)
        there = state == DONE and not item.gone
        self._show_picture(item.thumbnail if there else None)
        running = state == RUNNING
        fraction = item.fraction if running else None
        if fraction != self._fraction:
            self._fraction = fraction
            self.update()
        if state == WAITING:
            text = "waiting"
        elif running:
            text = (f"{int(item.fraction * 100)}%" if item.fraction >= 0 else "working")
            if item.speed:
                text += f"  ·  {item.speed:.1f}× real time"
        elif item.gone:
            text = "the file is gone"
        elif state == DONE:
            size = _size_text(item.size)
            if item.source_size and item.size and not item.files:
                change = max(round((item.size / item.source_size - 1) * 100), -99)  # never "−100 %": something is left
                size = f"{_size_text(item.source_size)} → {size} ({'+' if change > 0 else '−'}{abs(change)} %)"
            text = (f"{item.files} files  ·  " if item.files else "") + f"{size}  ·  {item.seconds:.0f} s"
            if item.finished and time.strftime("%Y%m%d", time.localtime(item.finished)) != time.strftime("%Y%m%d"):
                text += "  ·  " + time.strftime("%d %b", time.localtime(item.finished)).lstrip("0")
        elif state == CANCELLED:
            text = "cancelled"
        else:
            text = item.message
        self._status.setText(text)
        self._status.setToolTip(item.message if state == FAILED else
                                time.strftime("Finished %d %b %Y, %H:%M", time.localtime(item.finished))
                                if state == DONE and item.finished else "")
        self._title.set_result(str(item.job.output) if there else "")
        self._title.setToolTip(item.job.title + chr(10) + f"{item.job.output}"
                               + (chr(10) + "Click: open it  ·  drag: take the file somewhere  ·  right click: more"
                                  if there else ""))
        self._there = there
        self._play_button.setVisible(there)
        self._copy_button.setVisible(there)
        self._show_button.setVisible(there)
        self._cancel_button.setVisible(state in (WAITING, RUNNING))
        self._remove_button.setVisible(state in (FAILED, CANCELLED) or item.gone)
        self._again_button.setVisible(self._has_recipe and state in (DONE, FAILED, CANCELLED))

    def copy_file(self) -> None:
        """Puts the result file on the clipboard (as a file: Ctrl+V pastes it into a chat or a folder)."""
        qt.QtGui.QGuiApplication.clipboard().setMimeData(self._title.drag_data())
        self._copy_button.flash_icon(UiResources().iconManager.get_icon("check", sub_folder="actions"), self.COPIED_MS)

    def contextMenuEvent(self, event) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if self._there:
            menu.addAction("Open").triggered.connect(lambda: self.open_requested.emit(self.item_id))
            menu.addAction("Copy the file").triggered.connect(self.copy_file)
            menu.addAction("Copy its path").triggered.connect(
                lambda: qt.QtGui.QGuiApplication.clipboard().setText(self._title.drag_data().text()))
            menu.addAction("Show in folder").triggered.connect(lambda: self.show_requested.emit(self.item_id))
            menu.addSeparator()
        if self._has_command:
            menu.addAction("Command").triggered.connect(lambda: self.command_requested.emit(self.item_id))
        if self._state == WAITING:
            menu.addAction("Run next").triggered.connect(lambda: self.run_next_requested.emit(self.item_id))
        if self._has_recipe and self._state in (DONE, FAILED, CANCELLED):
            menu.addAction("Set up again").triggered.connect(lambda: self.again_requested.emit(self.item_id))
        if self._state in (WAITING, RUNNING):
            menu.addAction("Cancel").triggered.connect(lambda: self.cancel_requested.emit(self.item_id))
        else:
            menu.addAction("Remove from the list").triggered.connect(lambda: self.remove_requested.emit(self.item_id))
        self._menu = menu  # for tests; the menu deletes itself on close
        menu.popup(event.globalPos())


class JobList(qt.QtWidgets.QWidget):
    """The Media tool's list of jobs: a row per QueueItem of a JobQueue,
    newest first, in a scroll area; a hint while it is empty. Results of
    earlier runs of the hub are rows like any other (JobQueue.restore). It only shows
    the queue and passes on what was clicked.

    Signals:
        show_requested(object) / open_requested(object) / command_requested(object) — for a QueueItem.
    """

    show_requested = qt.QtCore.Signal(object)
    open_requested = qt.QtCore.Signal(object)
    command_requested = qt.QtCore.Signal(object)
    again_requested = qt.QtCore.Signal(object)

    def __init__(self, queue: JobQueue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self._rows: dict[int, _JobRow] = {}
        empty_icon = TintedIcon(UiResources().iconManager.get_icon("film", sub_folder="actions"), 26)
        empty_text = qt.QtWidgets.QLabel("What you start shows up here: its progress, then the finished file — "
                                         "click it to open, drag it into a chat.")
        empty_text.setObjectName("mediaJobsEmpty")
        empty_text.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        empty_text.setWordWrap(True)
        self._empty = qt.QtWidgets.QWidget()
        empty = qt.QtWidgets.QVBoxLayout(self._empty)
        empty.setContentsMargins(24, 18, 24, 12)
        empty.setSpacing(8)
        empty.addWidget(empty_icon, 0, qt.QtCore.Qt.AlignmentFlag.AlignHCenter)
        empty.addWidget(empty_text)
        self._holder = qt.QtWidgets.QWidget()
        self._list = qt.QtWidgets.QVBoxLayout(self._holder)
        self._list.setContentsMargins(0, 4, 0, 4)
        self._list.setSpacing(0)
        self._list.addWidget(self._empty)
        self._list.addStretch(1)
        self._scroll = StableScrollArea()
        self._scroll.setObjectName("mediaJobs")
        self._scroll.setWidget(self._holder)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)
        queue.added.connect(self._on_added)
        queue.changed.connect(self._on_changed)
        queue.removed.connect(self._on_removed)
        queue.moved.connect(self._on_moved)

    def _on_added(self, item: QueueItem) -> None:
        row = _JobRow(item)
        row.cancel_requested.connect(self._queue.cancel)
        row.remove_requested.connect(self._queue.remove)
        row.show_requested.connect(lambda item_id: self._forward(self.show_requested, item_id))
        row.open_requested.connect(lambda item_id: self._forward(self.open_requested, item_id))
        row.command_requested.connect(lambda item_id: self._forward(self.command_requested, item_id))
        row.again_requested.connect(lambda item_id: self._forward(self.again_requested, item_id))
        row.run_next_requested.connect(self._queue.run_next)
        self._rows[item.id] = row
        self._list.insertWidget(0, row)  # newest on top
        self._empty.hide()
        if item.state in (WAITING, RUNNING) and self.isVisible():
            row.appear()  # a job just started: results restored from an earlier run are simply there

    def _on_moved(self) -> None:
        """The rows follow the queue's order (newest — and last to run — on top)."""
        for item in self._queue.items():
            row = self._rows.get(item.id)
            if row is not None:
                self._list.removeWidget(row)
                self._list.insertWidget(0, row)

    def _on_changed(self, item: QueueItem) -> None:
        row = self._rows.get(item.id)
        if row is not None:
            row.update_item(item)

    def _on_removed(self, item_id: int) -> None:
        row = self._rows.pop(item_id, None)
        if row is not None:
            row.hide()
            row.deleteLater()
        self._empty.setVisible(not self._rows)

    def _forward(self, signal, item_id: int) -> None:
        item = next((item for item in self._queue.items() if item.id == item_id), None)
        if item is not None:
            signal.emit(item)
