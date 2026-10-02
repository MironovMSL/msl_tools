# tools/desktop/media/job_queue.py
import time
from dataclasses import dataclass
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.ui.media import FfmpegRunner
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.widgets.atoms.progress.base_progress_bar import BaseProgressBar, ProgressState
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
        size: Bytes of the result.
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


class JobQueue(qt.QtCore.QObject):
    """Runs the Media tool's jobs one after another (FfmpegRunner), in the
    order they were added. `tools` is asked for (a callable) at the moment a
    job starts — the ffmpeg in use may change while jobs wait.

    Signals:
        added(object) / changed(object) — a QueueItem appeared / moved on.
        removed(int) — the item with this id is gone from the queue.
    """

    added = qt.QtCore.Signal(object)
    changed = qt.QtCore.Signal(object)
    removed = qt.QtCore.Signal(int)

    def __init__(self, tools, parent=None):
        super().__init__(parent)
        self._tools = tools
        self._items: list[QueueItem] = []
        self._next_id = 1
        self._current: QueueItem | None = None
        self._started = 0.0
        self._runner = FfmpegRunner(self)
        self._runner.progressed.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)

    def items(self) -> list[QueueItem]:
        return list(self._items)

    def outputs(self) -> list[Path]:
        """Files the jobs that aren't over yet will write (so a new job picks another name)."""
        return [item.job.output for item in self._items if item.state in (WAITING, RUNNING)]

    def add(self, job: Job) -> QueueItem:
        tools = self._tools()
        item = QueueItem(id=self._next_id, job=job, command=job.command_text(tools))
        self._next_id += 1
        self._items.append(item)
        self.added.emit(item)
        self._start_next()
        return item

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
            item.seconds = time.time() - self._started
            if ok:
                item.state, item.fraction = DONE, 1.0
                try:
                    item.size = item.job.output.stat().st_size
                except OSError:
                    item.size = 0
            elif message == "Cancelled.":
                item.state = CANCELLED
            else:
                item.state, item.message = FAILED, message
            self.changed.emit(item)
        self._start_next()


class _JobRow(qt.QtWidgets.QFrame):
    """Private: one job of the list — a state dot, what it does, where it
    stands, and what can be done with it; a thin progress bar while it runs."""

    cancel_requested = qt.QtCore.Signal(int)
    remove_requested = qt.QtCore.Signal(int)
    show_requested = qt.QtCore.Signal(int)
    command_requested = qt.QtCore.Signal(int)

    def __init__(self, item: QueueItem, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaJob")
        self.item_id = item.id
        self._dot = qt.QtWidgets.QLabel()
        self._dot.setObjectName("mediaJobDot")
        self._dot.setFixedSize(8, 8)
        self._title = qt.QtWidgets.QLabel(item.job.title)
        self._title.setObjectName("mediaJobTitle")
        self._title.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._title.setToolTip(str(item.job.output))
        self._status = qt.QtWidgets.QLabel()
        self._status.setObjectName("mediaJobStatus")
        self._show_button = link_button("Show", "Show the result in its folder")
        self._command_button = link_button("Command", "What ffmpeg was asked to do")
        self._cancel_button = link_button("Cancel")
        self._remove_button = link_button("Remove", "Take this line off the list (the result file stays)")
        self._bar = BaseProgressBar()
        self._show_button.clicked.connect(lambda: self.show_requested.emit(self.item_id))
        self._command_button.clicked.connect(lambda: self.command_requested.emit(self.item_id))
        self._cancel_button.clicked.connect(lambda: self.cancel_requested.emit(self.item_id))
        self._remove_button.clicked.connect(lambda: self.remove_requested.emit(self.item_id))

        line = qt.QtWidgets.QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(self._dot)
        line.addWidget(self._title, 1)
        line.addWidget(self._status)
        line.addWidget(self._show_button)
        line.addWidget(self._command_button)
        line.addWidget(self._cancel_button)
        line.addWidget(self._remove_button)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(line)
        layout.addWidget(self._bar)
        self.update_item(item)

    def update_item(self, item: QueueItem) -> None:
        state = item.state
        if self._dot.property("state") != state:
            self._dot.setProperty("state", state)        # media.qss: QLabel#mediaJobDot[state=...]
            self._status.setProperty("state", state)
            repolish(self._dot)
            repolish(self._status)
        running = state == RUNNING
        self._bar.setVisible(running)
        if running:
            self._bar.set_state(ProgressState.NORMAL)
            self._bar.set_indeterminate(item.fraction < 0)
            if item.fraction >= 0:
                self._bar.set_progress(int(item.fraction * 100))
        if state == WAITING:
            text = "waiting"
        elif running:
            text = (f"{int(item.fraction * 100)}%" if item.fraction >= 0 else "working")
            if item.speed:
                text += f"  ·  {item.speed:.1f}× real time"
        elif state == DONE:
            megabytes = item.size / 1024 ** 2
            size = f"{megabytes:.1f} MB" if megabytes >= 1 else f"{item.size / 1024:.0f} KB"
            text = f"{size}  ·  {item.seconds:.0f} s"
        elif state == CANCELLED:
            text = "cancelled"
        else:
            text = item.message
        self._status.setText(text)
        self._status.setToolTip(item.message if state == FAILED else "")
        self._show_button.setVisible(state == DONE)
        self._command_button.setVisible(state in (DONE, FAILED))
        self._cancel_button.setVisible(state in (WAITING, RUNNING))
        self._remove_button.setVisible(state in (DONE, FAILED, CANCELLED))


class JobList(qt.QtWidgets.QWidget):
    """The Media tool's list of jobs: a row per QueueItem of a JobQueue,
    newest first, in a scroll area; "Jobs appear here" while it is empty.
    It only shows the queue and passes on what was clicked.

    Signals:
        show_requested(object) / command_requested(object) — for a QueueItem.
    """

    show_requested = qt.QtCore.Signal(object)
    command_requested = qt.QtCore.Signal(object)

    def __init__(self, queue: JobQueue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self._rows: dict[int, _JobRow] = {}
        self._empty = qt.QtWidgets.QLabel("What you start shows up here: its progress, then the finished file.")
        self._empty.setObjectName("mediaJobsEmpty")
        self._empty.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
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

    def _on_added(self, item: QueueItem) -> None:
        row = _JobRow(item)
        row.cancel_requested.connect(self._queue.cancel)
        row.remove_requested.connect(self._queue.remove)
        row.show_requested.connect(lambda item_id: self._forward(self.show_requested, item_id))
        row.command_requested.connect(lambda item_id: self._forward(self.command_requested, item_id))
        self._rows[item.id] = row
        self._list.insertWidget(0, row)  # newest on top
        self._empty.hide()

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
