# tools/desktop/media/source_card.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.tools.desktop.media.fact_tiles import FactTiles
from msl_tools.msl.tools.desktop.media.source import MediaSource, summary
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.compositions.drop_area import DropArea


VIDEO_PATTERNS = ("Video and pictures (*.mp4 *.mov *.avi *.mkv *.webm *.mxf *.m4v *.wmv *.png *.jpg *.jpeg *.tif *.tiff "
                  "*.exr *.tga *.bmp *.dpx);;All files (*.*)")


class SourceThumbnail(qt.QtWidgets.QLabel):
    """The source's picture. It is a button too: under the pointer it dims
    and shows a play mark, and a click asks to open the source.

    Colors are Qt properties set by media.qss: overlayColor (the dimming),
    markColor (the round mark), symbolColor (the triangle on it).

    Signals:
        clicked() — it was clicked.
    """

    MARK_RADIUS = 15

    clicked = qt.QtCore.Signal()

    overlayColor = color_property("_overlay_color")
    markColor = color_property("_mark_color")
    symbolColor = color_property("_symbol_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._overlay_color = qt.QtGui.QColor(fallback.surface)
        self._overlay_color.setAlpha(110)
        self._mark_color = qt.QtGui.QColor(fallback.accent)
        self._symbol_color = qt.QtGui.QColor(fallback.surface)
        self._hovered = False
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._hovered:
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._overlay_color)
        centre = qt.QtCore.QPointF(self.rect().center()) + qt.QtCore.QPointF(0.5, 0.5)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._mark_color)
        painter.drawEllipse(centre, self.MARK_RADIUS, self.MARK_RADIUS)
        side = self.MARK_RADIUS * 0.62
        triangle = qt.QtGui.QPolygonF([centre + qt.QtCore.QPointF(-side * 0.55, -side),
                                       centre + qt.QtCore.QPointF(-side * 0.55, side),
                                       centre + qt.QtCore.QPointF(side * 0.95, 0)])
        painter.setBrush(self._symbol_color)
        painter.drawPolygon(triangle)
        painter.end()


class SourceCard(qt.QtWidgets.QFrame):
    """What the Media tool is working on, in one of three looks:

        empty    a DropArea: a dashed frame, "Drop a video or an image
                 sequence here", and a pill of two round buttons — choose
                 a file / choose a folder
        loading  "Reading <name>…" in that frame
        loaded   a thumbnail (a click plays the source), the name, its
                 facts as small tiles (frame size, fps, length, size, ...),
                 a warning if something is wrong (missing frames), a
                 chooser when the folder holds several sequences; in the
                 corner "add another video" and "×" to clear.
                 Several sources (set_sources) show as one: "4 videos",
                 their total, their names on a line.

    The card shows and asks; it reads nothing itself — the page loads what
    was picked and hands the MediaSource back with set_source(). Drops are
    taken by the page (anywhere on it); set_dragging() lets the card show
    that it is the target.

    Signals:
        open_requested(str) — a file or folder was chosen with the buttons.
        add_requested(object) — more files (a list of paths) were chosen to work on TOGETHER with what is loaded.
        play_requested() — the thumbnail was clicked.
        sequence_picked(object) — another ImageSequence of the folder was chosen.
        cleared() — "×" was clicked.
    """

    HEIGHT = 116            # with a source
    EMPTY_HEIGHT = 148      # the drop area: taller, it is the only thing to do on the page then
    THUMBNAIL_SIZE = qt.QtCore.QSize(144, 81)
    DROP_TITLE = "Drop a video or an image sequence here"
    DROP_NOTE = "a folder of frames, or any one frame of it · several at once work too · or pick one:"

    open_requested = qt.QtCore.Signal(str)
    add_requested = qt.QtCore.Signal(object)
    play_requested = qt.QtCore.Signal()
    sequence_picked = qt.QtCore.Signal(object)
    cleared = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaSource")
        self.setFixedHeight(self.HEIGHT)
        self._source: MediaSource | None = None
        self._syncing = False

        # empty
        icons = UiResources().iconManager
        self._empty = DropArea(icons.get_icon("media", sub_folder="tools"), self.DROP_TITLE, self.DROP_NOTE)
        self._file_button = self._empty.add_button(icons.get_icon("file_video", sub_folder="actions"),
                                                   "Choose a file — a video, or one frame of an image sequence", "File")
        self._folder_button = self._empty.add_button(icons.get_icon("browse", sub_folder="actions"),
                                                     "Choose a folder — the frames of an image sequence", "Folder")

        # loaded
        self._thumbnail = SourceThumbnail()
        self._thumbnail.setObjectName("mediaThumbnail")
        self._thumbnail.setToolTip("Click to open it in your player")
        self._thumbnail.setFixedSize(self.THUMBNAIL_SIZE)
        self._thumbnail.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._title_label = qt.QtWidgets.QLabel()
        self._title_label.setObjectName("mediaSourceTitle")
        # a long name is clipped, it must not widen the window
        self._title_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._facts = FactTiles()  # the facts, a small tile each
        self._base_facts: list = []
        self._extra_facts: list = []
        self._warning_label = qt.QtWidgets.QLabel()
        self._warning_label.setObjectName("mediaSourceWarning")
        self._warning_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._chooser = BaseComboBox([], "")
        self._chooser.setToolTip("This folder holds several image sequences")
        self._chooser.setSizeAdjustPolicy(qt.QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._clear_button = GlyphButton("✕", "Take it away (the file itself stays where it is)")
        self._add_button = GlyphButton("+", "Add another video — to join them, compare them, or do the same to each")
        self._add_button.set_icon(UiResources().iconManager.get_icon("file_add", sub_folder="actions"))
        texts = qt.QtWidgets.QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(3)
        texts.addStretch(1)
        texts.addWidget(self._title_label)
        texts.addWidget(self._facts)
        texts.addWidget(self._warning_label)
        texts.addWidget(self._chooser, 0, qt.QtCore.Qt.AlignmentFlag.AlignLeft)
        texts.addStretch(1)
        self._loaded = qt.QtWidgets.QWidget()
        loaded_layout = qt.QtWidgets.QHBoxLayout(self._loaded)
        loaded_layout.setContentsMargins(10, 10, 8, 10)
        loaded_layout.setSpacing(12)
        loaded_layout.addWidget(self._thumbnail)
        loaded_layout.addLayout(texts, 1)
        loaded_layout.addWidget(self._add_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        loaded_layout.addWidget(self._clear_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)

        self._stack = qt.QtWidgets.QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._loaded)

        self._file_button.clicked.connect(self._on_choose_file)
        self._folder_button.clicked.connect(self._on_choose_folder)
        self._clear_button.clicked.connect(self.cleared)
        self._add_button.clicked.connect(self._on_add)
        self._thumbnail.clicked.connect(self.play_requested)
        self._chooser.currentIndexChanged.connect(self._on_chooser)
        self.set_source(None)

    def source(self) -> MediaSource | None:
        return self._source

    def set_sources(self, sources: list) -> None:
        """Shows several sources as one card (one: the same as set_source())."""
        if len(sources) <= 1:
            self.set_source(sources[0] if sources else None)
            return
        self.set_source(sources[0])
        title, pairs = summary(sources)
        names = [source.title() for source in sources]
        self._title_label.setText(title)
        self._title_label.setToolTip(chr(10).join(names))
        self._base_facts, self._extra_facts = list(pairs), []
        self._set_facts(pairs)
        problems = [f"{source.title()}: {source.warning()}" for source in sources if source.warning()]
        self._warning_label.setText(", ".join(names) if not problems else "; ".join(problems))
        self._warning_label.setProperty("plain", not problems)  # media.qss: a list of names isn't a warning
        repolish(self._warning_label)
        self._warning_label.setToolTip(chr(10).join(names))
        self._warning_label.show()
        self._chooser.hide()

    def set_source(self, source: MediaSource | None) -> None:
        self._source = source
        self._set_look("loaded" if source is not None else "empty")
        self._empty.set_texts(self.DROP_TITLE, self.DROP_NOTE)
        if source is None:
            self._stack.setCurrentWidget(self._empty)
            return
        self._title_label.setText(source.title())
        self._title_label.setToolTip(str(source.path))
        self._base_facts, self._extra_facts = source.fact_pairs(), []
        self._set_facts(self._base_facts)
        self._add_button.setVisible(not source.is_sequence)
        self._warning_label.setText(source.warning())
        self._warning_label.setToolTip("")
        if self._warning_label.property("plain"):
            self._warning_label.setProperty("plain", False)
            repolish(self._warning_label)
        self._warning_label.setVisible(bool(source.warning()))
        pixmap = qt.QtGui.QPixmap(str(source.thumbnail)) if source.thumbnail is not None else qt.QtGui.QPixmap()
        if pixmap.isNull():
            self._thumbnail.setPixmap(qt.QtGui.QPixmap())
            self._thumbnail.setText("no preview")
        else:
            ratio = self.devicePixelRatioF()
            scaled = pixmap.scaled(self.THUMBNAIL_SIZE * ratio, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                   qt.QtCore.Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            self._thumbnail.setText("")
            self._thumbnail.setPixmap(scaled)
        self._syncing = True
        self._chooser.clear()
        for sequence in source.siblings:
            self._chooser.addItem(f"{sequence.name}  ·  {sequence.count} frames", sequence)
        if source.sequence is not None:
            self._chooser.setCurrentIndex(max(source.siblings.index(source.sequence), 0)
                                          if source.sequence in source.siblings else 0)
        self._syncing = False
        self._chooser.setVisible(len(source.siblings) > 1)
        self._stack.setCurrentWidget(self._loaded)

    def _set_facts(self, pairs: list) -> None:
        self._facts.set_pairs(pairs)

    def set_extra_facts(self, pairs: list) -> None:
        """Tiles the picked action adds after the source's own (e.g. how long a
        sequence will be at the picked frame rate). [] takes them away."""
        if list(pairs) != self._extra_facts:
            self._extra_facts = list(pairs)
            self._set_facts(self._base_facts + self._extra_facts)

    def facts_text(self) -> str:
        """The tiles as one line of text."""
        return self._facts.text()

    def _on_add(self) -> None:
        paths, _filter = qt.QtWidgets.QFileDialog.getOpenFileNames(self, "Videos to add", "", VIDEO_PATTERNS)
        if paths:
            self.add_requested.emit(list(paths))

    def set_loading(self, name: str) -> None:
        """Shows "Reading <name>…" until set_source() / set_message()."""
        self._set_look("empty")
        self._empty.set_busy(f"Reading {name}…")
        self._stack.setCurrentWidget(self._empty)

    def set_enabled_for_input(self, enabled: bool, reason: str = "") -> None:
        """Without ffmpeg nothing can be read: the choose buttons go off and the hint says why."""
        self._empty.set_buttons_enabled(enabled)
        if not enabled and self._source is None:
            self._empty.set_texts(reason)

    def set_dragging(self, dragging: bool) -> None:
        """Something is being dragged over the page: the card shows it is the target."""
        self._empty.set_dragging(dragging)
        if bool(self.property("dragging")) != dragging:
            self.setProperty("dragging", dragging)  # media.qss: QFrame#mediaSource[dragging="true"]
            repolish(self)

    def _set_look(self, look: str) -> None:
        if self.property("look") != look:
            self.setProperty("look", look)  # media.qss: QFrame#mediaSource[look=...]
            repolish(self)
            self.setFixedHeight(self.HEIGHT if look == "loaded" else self.EMPTY_HEIGHT)

    def _on_choose_file(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(
            self, "A video, or one frame of an image sequence", "", VIDEO_PATTERNS)
        if path:
            self.open_requested.emit(path)

    def _on_choose_folder(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder of an image sequence")
        if folder:
            self.open_requested.emit(folder)

    def _on_chooser(self, index: int) -> None:
        if not self._syncing and index >= 0:
            self.sequence_picked.emit(self._chooser.itemData(index))
