# tools/desktop/media/job_queue.py
import time
from dataclasses import dataclass
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.ui.media import FfmpegRunner
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
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
        size: Bytes of the result (of everything in it, when the result is a folder).
        files: How many files the result holds (a folder of frames; 0 for one file).
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


class JobQueue(qt.QtCore.QObject):
    """Runs the Media tool's jobs one after another (FfmpegRunner), in the
    order they were added. `tools` is asked for (a callable) at the moment a
    job starts — the ffmpeg in use may change while jobs wait.

    Signals:
        added(object) / changed(object) — a QueueItem appeared / moved on.
        removed(int) — the item with this id is gone from the queue.
        idle() — the last job of the line is over (nothing waits or runs).
    """

    added = qt.QtCore.Signal(object)
    changed = qt.QtCore.Signal(object)
    removed = qt.QtCore.Signal(int)
    idle = qt.QtCore.Signal()

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
                    if item.job.folder is not None:
                        sizes = [entry.stat().st_size for entry in item.job.folder.iterdir() if entry.is_file()]
                        item.size, item.files = sum(sizes), len(sizes)
                    else:
                        item.size = item.job.output.stat().st_size
                except OSError:
                    item.size = 0
            elif message == "Cancelled.":
                item.state = CANCELLED
            else:
                item.state, item.message = FAILED, message
            self.changed.emit(item)
        self._start_next()
        if self._current is None:
            self.idle.emit()


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
    """Private: one job of the list — a state dot, what it does, where it
    stands, a thin progress bar while it runs. When it is done the title is
    the result file itself (click = open, drag = take it somewhere), "Copy"
    puts the file on the clipboard, "Show" opens its folder; a right click
    has the rest (the command, the path, remove)."""

    COPIED_MS = 1500

    cancel_requested = qt.QtCore.Signal(int)
    remove_requested = qt.QtCore.Signal(int)
    show_requested = qt.QtCore.Signal(int)
    open_requested = qt.QtCore.Signal(int)
    command_requested = qt.QtCore.Signal(int)

    def __init__(self, item: QueueItem, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaJob")
        self.item_id = item.id
        self._state = ""
        self._dot = qt.QtWidgets.QLabel()
        self._dot.setObjectName("mediaJobDot")
        self._dot.setFixedSize(8, 8)
        self._title = _ResultLabel(item.job.title)
        self._status = qt.QtWidgets.QLabel()
        self._status.setObjectName("mediaJobStatus")
        self._copy_button = link_button("Copy", "Copy the file — then paste it into a chat or a folder (Ctrl+V)")
        self._show_button = link_button("Show", "Show the result in its folder")
        self._cancel_button = link_button("Cancel")
        self._remove_button = link_button("Remove", "Take this line off the list (the result file stays)")
        self._bar = BaseProgressBar()
        self._title.activated.connect(lambda: self.open_requested.emit(self.item_id))
        self._copy_button.clicked.connect(self.copy_file)
        self._show_button.clicked.connect(lambda: self.show_requested.emit(self.item_id))
        self._cancel_button.clicked.connect(lambda: self.cancel_requested.emit(self.item_id))
        self._remove_button.clicked.connect(lambda: self.remove_requested.emit(self.item_id))

        line = qt.QtWidgets.QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(self._dot)
        line.addWidget(self._title, 1)
        line.addWidget(self._status)
        line.addWidget(self._copy_button)
        line.addWidget(self._show_button)
        line.addWidget(self._cancel_button)
        line.addWidget(self._remove_button)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(line)
        layout.addWidget(self._bar)
        self.update_item(item)

    def update_item(self, item: QueueItem) -> None:
        state = self._state = item.state
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
            text = (f"{item.files} files  ·  " if item.files else "") + f"{size}  ·  {item.seconds:.0f} s"
        elif state == CANCELLED:
            text = "cancelled"
        else:
            text = item.message
        self._status.setText(text)
        self._status.setToolTip(item.message if state == FAILED else "")
        self._title.set_result(str(item.job.output) if state == DONE else "")
        self._title.setToolTip(f"{item.job.output}" + (chr(10) + "Click: open it  ·  drag: take the file somewhere  ·  "
                                                       "right click: more" if state == DONE else ""))
        self._copy_button.setVisible(state == DONE)
        self._show_button.setVisible(state == DONE)
        self._cancel_button.setVisible(state in (WAITING, RUNNING))
        self._remove_button.setVisible(state in (FAILED, CANCELLED))

    def copy_file(self) -> None:
        """Puts the result file on the clipboard (as a file: Ctrl+V pastes it into a chat or a folder)."""
        qt.QtGui.QGuiApplication.clipboard().setMimeData(self._title.drag_data())
        self._copy_button.setText("Copied")
        qt.QtCore.QTimer.singleShot(self.COPIED_MS, lambda: self._copy_button.setText("Copy"))

    def contextMenuEvent(self, event) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if self._state == DONE:
            menu.addAction("Open").triggered.connect(lambda: self.open_requested.emit(self.item_id))
            menu.addAction("Copy the file").triggered.connect(self.copy_file)
            menu.addAction("Copy its path").triggered.connect(
                lambda: qt.QtGui.QGuiApplication.clipboard().setText(self._title.drag_data().text()))
            menu.addAction("Show in folder").triggered.connect(lambda: self.show_requested.emit(self.item_id))
            menu.addSeparator()
        menu.addAction("Command").triggered.connect(lambda: self.command_requested.emit(self.item_id))
        if self._state in (WAITING, RUNNING):
            menu.addAction("Cancel").triggered.connect(lambda: self.cancel_requested.emit(self.item_id))
        else:
            menu.addAction("Remove from the list").triggered.connect(lambda: self.remove_requested.emit(self.item_id))
        self._menu = menu  # for tests; the menu deletes itself on close
        menu.popup(event.globalPos())


class JobList(qt.QtWidgets.QWidget):
    """The Media tool's list of jobs: a row per QueueItem of a JobQueue,
    newest first, in a scroll area; a hint while it is empty. It only shows
    the queue and passes on what was clicked.

    Signals:
        show_requested(object) / open_requested(object) / command_requested(object) — for a QueueItem.
    """

    show_requested = qt.QtCore.Signal(object)
    open_requested = qt.QtCore.Signal(object)
    command_requested = qt.QtCore.Signal(object)

    def __init__(self, queue: JobQueue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self._rows: dict[int, _JobRow] = {}
        self._empty = qt.QtWidgets.QLabel("What you start shows up here: its progress, then the finished file — "
                                          "click it to open, drag it into a chat.")
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
        row.open_requested.connect(lambda item_id: self._forward(self.open_requested, item_id))
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
