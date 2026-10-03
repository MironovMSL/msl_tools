# tools/maya/playblast/recent.py
import hashlib
import tempfile
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import probe
from msl_tools.msl.core.media.thumbnail import thumbnail
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel
from msl_tools.msl.ui.workers.result_worker import ResultWorker

THUMB_SIZE = qt.QtCore.QSize(64, 36)


def open_result(path: Path) -> None:
    """Opens a playblast with the system's player (a folder of frames: the folder)."""
    if path.exists():
        qt.QtGui.QDesktopServices.openUrl(qt.QtCore.QUrl.fromLocalFile(str(path)))


def size_text(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{max(1, size // 1024)} KB"


def when_text(moment: float) -> str:
    """"12:40" for today, "3 Oct" for another day."""
    then, now = time.localtime(moment), time.localtime()
    if (then.tm_year, then.tm_yday) == (now.tm_year, now.tm_yday):
        return time.strftime("%H:%M", then)
    return f"{then.tm_mday} {time.strftime('%b', then)}"


class _FileLabel(ElidedLabel):
    """A result's name: a click opens it, dragging it out carries the file (into a chat, a folder)."""

    def __init__(self, path: Path, parent=None):
        super().__init__(path.name, qt.QtCore.Qt.TextElideMode.ElideMiddle, parent)
        self._path = path
        self._pressed_at = None
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{path}\nClick to open, drag to take the file somewhere")

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._pressed_at = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._pressed_at is None or not self._path.exists():
            return
        moved = (event.position().toPoint() - self._pressed_at).manhattanLength()
        if moved < qt.QtWidgets.QApplication.startDragDistance():
            return
        self._pressed_at = None
        data = qt.QtCore.QMimeData()
        data.setUrls([qt.QtCore.QUrl.fromLocalFile(str(self._path))])
        drag = qt.QtGui.QDrag(self)
        drag.setMimeData(data)
        drag.exec(qt.QtCore.Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed_at is not None and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._pressed_at = None
            open_result(self._path)


class _RecentRow(qt.QtWidgets.QWidget):
    """One finished playblast: its picture, name, size and time, open / show in folder."""

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        path = Path(entry["path"])
        icons = UiResources().iconManager
        self._thumb = qt.QtWidgets.QLabel()
        self._thumb.setObjectName("playblastThumb")
        self._thumb.setFixedSize(THUMB_SIZE)
        self._thumb.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        name = _FileLabel(path)
        name.setObjectName("playblastRecentName")
        facts = []
        try:
            facts.append(f"{entry.get('frames', 0)} frames" if path.is_dir() else size_text(path.stat().st_size))
        except OSError:
            pass
        if entry.get("camera"):
            facts.append(str(entry["camera"]))
        facts.append(when_text(float(entry.get("time", 0.0))))
        note = qt.QtWidgets.QLabel(" · ".join(facts))
        note.setObjectName("playblastHint")
        play = GlyphButton("▶", "Open it")
        play.set_icon(icons.get_icon("play", sub_folder="actions"))
        play.clicked.connect(lambda: open_result(path))
        show = GlyphButton("…", "Show it in its folder")
        show.set_icon(icons.get_icon("browse", sub_folder="actions"))
        show.clicked.connect(lambda: ProcessLauncher.open_file_explorer(path))
        for button in (play, show):
            button.setObjectName("playblastAction")
        text = qt.QtWidgets.QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        text.addWidget(name)
        text.addWidget(note)
        row = qt.QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._thumb)
        row.addLayout(text, 1)
        row.addWidget(play)
        row.addWidget(show)

    def set_picture(self, file: str) -> None:
        pixmap = qt.QtGui.QPixmap(file)
        if not pixmap.isNull():
            self._thumb.setPixmap(pixmap.scaled(THUMB_SIZE, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                qt.QtCore.Qt.TransformationMode.SmoothTransformation))


class RecentCard(qt.QtWidgets.QFrame):
    """The last playblasts of the scene, newest first — a card that isn't there while
    there are none.

        card.show_results(entries, tools)   # entries: dicts with path, frames, camera, time

    Pictures are made on workers (core/media thumbnail; a folder of frames shows its
    first frame) and cached in %TEMP%/msl_tools/playblast/thumbs. Looks: playblast.qss.
    """

    _picture_ready = qt.QtCore.Signal(str, str)
    # kept by the CLASS, parentless: the card can be deleted while a worker runs (see PlayblastPanel)
    _workers: set = set()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("playblastCard")
        self._shown: list = []
        self._rows: dict = {}
        self._heading = qt.QtWidgets.QLabel("RECENT")
        self._heading.setObjectName("playblastSection")
        self._list = qt.QtWidgets.QVBoxLayout()
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(8)
        box = qt.QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        box.addWidget(self._heading)
        box.addLayout(self._list)
        self._picture_ready.connect(self._on_picture)
        self.hide()

    def show_results(self, entries: list, tools) -> None:
        key = [(entry["path"], entry.get("time")) for entry in entries] + [tools is not None]
        if key == self._shown:
            return
        self._shown = key
        while self._list.count():
            item = self._list.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._rows = {}
        for entry in entries:
            row = _RecentRow(entry)
            self._rows[entry["path"]] = row
            self._list.addWidget(row)
            if tools is not None:
                self._make_picture(tools, entry["path"])
        self.setVisible(bool(entries))

    def _make_picture(self, tools, path: str) -> None:
        emit = self._emit_picture
        worker = ResultWorker(lambda: emit(path, self._thumbnail(tools, Path(path))))
        workers = RecentCard._workers
        workers.add(worker)
        worker.finished.connect(lambda: workers.discard(worker))
        worker.start()

    def _emit_picture(self, path: str, file: str) -> None:
        try:
            self._picture_ready.emit(path, file)
        except RuntimeError:
            pass  # the card is gone

    def _on_picture(self, path: str, file: str) -> None:
        row = self._rows.get(path)
        if file and row is not None and qt.shiboken.isValid(row):
            row.set_picture(file)

    @staticmethod
    def _thumbnail(tools, path: Path) -> str:
        """On a worker: a small picture of the result ("" if none could be made)."""
        try:
            source = path
            if path.is_dir():
                frames = sorted(entry for entry in path.iterdir() if entry.suffix.lower() in (".png", ".jpg"))
                if not frames:
                    return ""
                source = frames[0]
            stamp = f"{source}|{source.stat().st_mtime_ns}".encode("utf-8")
            folder = Path(tempfile.gettempdir()) / "msl_tools" / "playblast" / "thumbs"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (hashlib.md5(stamp).hexdigest() + ".jpg")
            if not target.is_file():
                thumbnail(tools, probe(tools, source), target, 128)
            return str(target) if target.is_file() else ""
        except Exception:
            return ""
