# tools/maya/playblast/recent.py
import hashlib
import tempfile
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import probe
from msl_tools.msl.core.media.thumbnail import thumbnail
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tinted_menu_icon
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel
from msl_tools.msl.ui.workers.result_worker import ResultWorker


# What a tile's menu can ask the panel for (RecentCard.action_requested)
ACTION_MEDIA, ACTION_COMPARE, ACTION_LIGHT = "media", "compare", "light"


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


class _Picture(qt.QtWidgets.QWidget):
    """A result's picture, 16:9 whatever its width: a click opens the result, dragging it
    out carries the file (into a chat, a folder), a right click offers the rest. Under the
    pointer it dims and shows a play mark."""

    groundColor = color_property("_ground_color", "update")
    markColor = color_property("_mark_color", "update")
    # The right-click menu's icons: QIcons, which QSS can't tint — tinted with this when it opens.
    menuIconColor = color_property("_menu_icon_color", None)
    MENU_ICON_SIZE = 16

    def __init__(self, path: Path, parent=None, on_action=None):
        super().__init__(parent)
        self._on_action = on_action  # (action, path) -> None: what the card's menu asks for
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._ground_color = qt.QtGui.QColor(fallback.border)
        self._mark_color = qt.QtGui.QColor(fallback.text_primary)
        self._menu_icon_color = qt.QtGui.QColor(fallback.text_secondary)
        self._path = path
        self._pixmap = qt.QtGui.QPixmap()
        self._pressed_at = None
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(56)

    def set_picture(self, file: str) -> None:
        pixmap = qt.QtGui.QPixmap(file)
        if not pixmap.isNull():
            self._pixmap = pixmap
            self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        height = max(30, int(round(self.width() * 9 / 16)))
        if self.height() != height:
            self.setFixedHeight(height)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHints(qt.QtGui.QPainter.RenderHint.Antialiasing
                               | qt.QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        rect = qt.QtCore.QRectF(self.rect())
        clip = qt.QtGui.QPainterPath()
        clip.addRoundedRect(rect, 5, 5)
        painter.setClipPath(clip)
        painter.fillRect(rect, self._ground_color)
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(self.size(), qt.QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         qt.QtCore.Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(int((self.width() - scaled.width()) / 2), int((self.height() - scaled.height()) / 2),
                               scaled)
        if self.underMouse():
            painter.fillRect(rect, qt.QtGui.QColor(0, 0, 0, 90))
            side = min(rect.width(), rect.height()) * 0.3
            centre = rect.center()
            mark = qt.QtGui.QPolygonF([qt.QtCore.QPointF(centre.x() - side * 0.4, centre.y() - side * 0.5),
                                       qt.QtCore.QPointF(centre.x() - side * 0.4, centre.y() + side * 0.5),
                                       qt.QtCore.QPointF(centre.x() + side * 0.55, centre.y())])
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._mark_color)
            painter.drawPolygon(mark)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._pressed_at = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._pressed_at is None or not self._path.exists():
            return
        if (event.position().toPoint() - self._pressed_at).manhattanLength() < qt.QtWidgets.QApplication.startDragDistance():
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

    def _menu_icon(self, name: str, sub_folder: str = "actions") -> qt.QtGui.QIcon:
        """A one-color icon for the menu, in the theme's color (an empty icon if the file is missing)."""
        return tinted_menu_icon(UiResources().iconManager.get_icon(name, sub_folder=sub_folder),
                                self._menu_icon_color, self.devicePixelRatioF(), self.MENU_ICON_SIZE)

    def contextMenuEvent(self, event) -> None:
        path = self._path
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        icon = self._menu_icon
        menu.addAction(icon("play"), "Open").triggered.connect(lambda: open_result(path))
        menu.addAction(icon("browse"), "Show in folder").triggered.connect(
            lambda: ProcessLauncher.open_file_explorer(path))
        menu.addAction(icon("copy"), "Copy path").triggered.connect(
            lambda: qt.QtWidgets.QApplication.clipboard().setText(str(path)))
        if self._on_action is not None and path.exists():
            menu.addSeparator()
            act = self._on_action
            menu.addAction(icon("media", "tools"), "Open in MSL Tools Media").triggered.connect(
                lambda: act(ACTION_MEDIA, str(path)))
            if path.is_file():  # a video, not a folder of frames
                menu.addAction(icon("split_view"), "Compare with the previous version").triggered.connect(
                    lambda: act(ACTION_COMPARE, str(path)))
                menu.addAction(icon("compress"), "Make a light copy for a chat").triggered.connect(
                    lambda: act(ACTION_LIGHT, str(path)))
        menu.exec(event.globalPos())


class _FolderLink(ElidedLabel):
    """A result's name: a click shows the file in its folder."""

    def __init__(self, path: Path, parent=None):
        super().__init__(path.name, qt.QtCore.Qt.TextElideMode.ElideMiddle, parent)
        self._path = path
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            ProcessLauncher.open_file_explorer(self._path)


class _RecentTile(qt.QtWidgets.QWidget):
    """One finished playblast: its picture (a click opens it) over its name (a click shows it
    in its folder) and a line of facts ending in a folder button that does the same."""

    def __init__(self, entry: dict, parent=None, on_action=None):
        super().__init__(parent)
        path = Path(entry["path"])
        self.picture = _Picture(path, on_action=on_action)
        name = _FolderLink(path)
        name.setObjectName("playblastRecentName")
        facts = []
        try:
            facts.append(f"{entry.get('frames', 0)} fr" if path.is_dir() else size_text(path.stat().st_size))
        except OSError:
            pass
        facts.append(when_text(float(entry.get("time", 0.0))))
        note = ElidedLabel(" · ".join(facts), qt.QtCore.Qt.TextElideMode.ElideRight)
        note.setObjectName("playblastHint")
        about = "\n".join(part for part in (str(path), str(entry.get("camera", "")), str(entry.get("note", "")))
                          if part)
        self.picture.setToolTip(about + "\nClick to open, drag to take the file somewhere, right click for more")
        name.setToolTip(about + "\nClick to show it in its folder")
        note.setToolTip(about)
        folder = GlyphButton("…", "Show it in its folder", size=qt.QtCore.QSize(18, 16))
        folder.setObjectName("playblastAction")
        folder.set_icon(UiResources().iconManager.get_icon("browse", sub_folder="actions"))
        folder.clicked.connect(lambda: ProcessLauncher.open_file_explorer(path))
        line = qt.QtWidgets.QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(2)
        line.addWidget(note, 1)
        line.addWidget(folder)
        box = qt.QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(self.picture)
        box.addWidget(name)
        box.addLayout(line)


class RecentCard(qt.QtWidgets.QFrame):
    """The last playblasts of the scene as a row of tiles, newest first — a card
    that isn't there while there are none.

        card.show_results(entries, tools, total=9)   # entries: dicts with path, frames, camera, time
        card.clear_requested.connect(...)            # "Clear" in the heading

    The heading counts ALL of the scene's results (`total`), the row shows the
    last few. Pictures are made on workers (core/media thumbnail; a folder of
    frames shows its first frame) and cached in %TEMP%/msl_tools/playblast/thumbs.
    Looks: playblast.qss.

    Signals:
        clear_requested() — forget this scene's results (the files stay).
        action_requested(str, str) — (ACTION_*, path): a tile's menu asked to send the result to
            the hub's Media, compare it with the previous version, or make a light copy.
    """

    clear_requested = qt.QtCore.Signal()
    action_requested = qt.QtCore.Signal(str, str)
    _picture_ready = qt.QtCore.Signal(str, str)
    # kept by the CLASS, parentless: the card can be deleted while a worker runs (see PlayblastPanel)
    _workers: set = set()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("playblastCard")
        self._shown: list = []
        self._tiles: dict = {}
        icon = TintedIcon(UiResources().iconManager.get_icon("image_stack", sub_folder="actions"), 14)
        icon.setObjectName("playblastCardIcon")
        self._heading = qt.QtWidgets.QLabel("RECENT")
        self._heading.setObjectName("playblastSection")
        clear = qt.QtWidgets.QPushButton("Clear")
        clear.setObjectName("playblastLink")
        clear.setFlat(True)
        clear.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        clear.setToolTip("Forget this scene's playblasts here (the files stay where they are)")
        clear.clicked.connect(self.clear_requested)
        top = qt.QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(icon)
        top.addWidget(self._heading)
        top.addStretch(1)
        top.addWidget(clear)
        self._row = qt.QtWidgets.QHBoxLayout()
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(8)
        box = qt.QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        box.addLayout(top)
        box.addLayout(self._row)
        self._picture_ready.connect(self._on_picture)
        self.hide()

    def show_results(self, entries: list, tools, total: int = 0, slots: int = 4) -> None:
        key = [(entry["path"], entry.get("time")) for entry in entries] + [tools is not None, total]
        if key == self._shown:
            return
        self._shown = key
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._tiles = {}
        for entry in entries:
            tile = _RecentTile(entry, on_action=self.action_requested.emit)
            self._tiles[entry["path"]] = tile
            self._row.addWidget(tile, 1)
            if tools is not None:
                self._make_picture(tools, entry["path"])
        for _ in range(max(0, slots - len(entries))):  # fewer than a full row: the tiles keep their size
            self._row.addStretch(1)
        self._heading.setText(f"RECENT · {max(total, len(entries))}" if entries else "RECENT")
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
        tile = self._tiles.get(path)
        if file and tile is not None and qt.shiboken.isValid(tile):
            tile.picture.set_picture(file)

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
                thumbnail(tools, probe(tools, source), target, 240)
            return str(target) if target.is_file() else ""
        except Exception:
            return ""
