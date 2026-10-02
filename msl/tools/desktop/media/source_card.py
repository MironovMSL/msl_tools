# tools/desktop/media/source_card.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.tools.desktop.media.source import MediaSource, summary
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox


class SourceCard(qt.QtWidgets.QFrame):
    """What the Media tool is working on, in one of three looks:

        empty    a dashed drop area: "Drop a video or an image sequence here",
                 with "Choose a file…" / "Choose a folder…"
        loading  "Reading <name>…"
        loaded   a thumbnail, the name, a line of facts, a warning if
                 something is wrong (missing frames), a chooser when the
                 folder holds several sequences, and "×" to clear.
                 Several sources (set_sources) show as one: "4 videos",
                 their total, their names on a line.

    The card shows and asks; it reads nothing itself — the page loads what
    was picked and hands the MediaSource back with set_source(). Drops are
    taken by the page (anywhere on it); set_dragging() lets the card show
    that it is the target.

    Signals:
        open_requested(str) — a file or folder was chosen with the buttons.
        sequence_picked(object) — another ImageSequence of the folder was chosen.
        cleared() — "×" was clicked.
    """

    HEIGHT = 104
    THUMBNAIL_SIZE = qt.QtCore.QSize(144, 81)

    open_requested = qt.QtCore.Signal(str)
    sequence_picked = qt.QtCore.Signal(object)
    cleared = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaSource")
        self.setFixedHeight(self.HEIGHT)
        self._source: MediaSource | None = None
        self._syncing = False

        # empty
        self._hint_label = qt.QtWidgets.QLabel("Drop a video, a folder of frames, or one frame of a sequence here")
        self._hint_label.setObjectName("mediaDropHint")
        self._hint_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._hint_label.setWordWrap(True)
        self._file_button = link_button("Choose a file…")
        self._folder_button = link_button("Choose a folder…", "The folder of an image sequence")
        buttons = qt.QtWidgets.QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        buttons.addStretch(1)
        buttons.addWidget(self._file_button)
        buttons.addWidget(self._folder_button)
        buttons.addStretch(1)
        self._empty = qt.QtWidgets.QWidget()
        empty_layout = qt.QtWidgets.QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(12, 8, 12, 8)
        empty_layout.setSpacing(4)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self._hint_label)
        empty_layout.addLayout(buttons)
        empty_layout.addStretch(1)

        # loaded
        self._thumbnail = qt.QtWidgets.QLabel()
        self._thumbnail.setObjectName("mediaThumbnail")
        self._thumbnail.setFixedSize(self.THUMBNAIL_SIZE)
        self._thumbnail.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._title_label = qt.QtWidgets.QLabel()
        self._title_label.setObjectName("mediaSourceTitle")
        # a long name is clipped, it must not widen the window
        self._title_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._facts_label = qt.QtWidgets.QLabel()
        self._facts_label.setObjectName("mediaSourceFacts")
        self._facts_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._warning_label = qt.QtWidgets.QLabel()
        self._warning_label.setObjectName("mediaSourceWarning")
        self._warning_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._chooser = BaseComboBox([], "")
        self._chooser.setToolTip("This folder holds several image sequences")
        self._chooser.setSizeAdjustPolicy(qt.QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._clear_button = GlyphButton("✕", "Take it away (the file itself stays where it is)")
        texts = qt.QtWidgets.QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(3)
        texts.addStretch(1)
        texts.addWidget(self._title_label)
        texts.addWidget(self._facts_label)
        texts.addWidget(self._warning_label)
        texts.addWidget(self._chooser, 0, qt.QtCore.Qt.AlignmentFlag.AlignLeft)
        texts.addStretch(1)
        self._loaded = qt.QtWidgets.QWidget()
        loaded_layout = qt.QtWidgets.QHBoxLayout(self._loaded)
        loaded_layout.setContentsMargins(10, 10, 8, 10)
        loaded_layout.setSpacing(12)
        loaded_layout.addWidget(self._thumbnail)
        loaded_layout.addLayout(texts, 1)
        loaded_layout.addWidget(self._clear_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)

        self._stack = qt.QtWidgets.QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._loaded)

        self._file_button.clicked.connect(self._on_choose_file)
        self._folder_button.clicked.connect(self._on_choose_folder)
        self._clear_button.clicked.connect(self.cleared)
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
        title, facts = summary(sources)
        names = [source.title() for source in sources]
        self._title_label.setText(title)
        self._title_label.setToolTip(chr(10).join(names))
        self._facts_label.setText(facts)
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
        self._hint_label.setText("Drop a video, a folder of frames, or one frame of a sequence here")
        self._file_button.show()
        self._folder_button.show()
        if source is None:
            self._stack.setCurrentWidget(self._empty)
            return
        self._title_label.setText(source.title())
        self._title_label.setToolTip(str(source.path))
        self._facts_label.setText(source.facts())
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

    def set_loading(self, name: str) -> None:
        """Shows "Reading <name>…" until set_source() / set_message()."""
        self._set_look("empty")
        self._hint_label.setText(f"Reading {name}…")
        self._file_button.hide()
        self._folder_button.hide()
        self._stack.setCurrentWidget(self._empty)

    def set_enabled_for_input(self, enabled: bool, reason: str = "") -> None:
        """Without ffmpeg nothing can be read: the choose buttons go off and the hint says why."""
        self._file_button.setEnabled(enabled)
        self._folder_button.setEnabled(enabled)
        if not enabled and self._source is None:
            self._hint_label.setText(reason)

    def set_dragging(self, dragging: bool) -> None:
        """Something is being dragged over the page: the card shows it is the target."""
        if bool(self.property("dragging")) != dragging:
            self.setProperty("dragging", dragging)  # media.qss: QFrame#mediaSource[dragging="true"]
            repolish(self)

    def _set_look(self, look: str) -> None:
        if self.property("look") != look:
            self.setProperty("look", look)  # media.qss: QFrame#mediaSource[look=...]
            repolish(self)

    def _on_choose_file(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(
            self, "A video, or one frame of an image sequence", "",
            "Video and pictures (*.mp4 *.mov *.avi *.mkv *.webm *.mxf *.m4v *.wmv *.png *.jpg *.jpeg *.tif *.tiff *.exr "
            "*.tga *.bmp *.dpx);;All files (*.*)")
        if path:
            self.open_requested.emit(path)

    def _on_choose_folder(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder of an image sequence")
        if folder:
            self.open_requested.emit(folder)

    def _on_chooser(self, index: int) -> None:
        if not self._syncing and index >= 0:
            self.sequence_picked.emit(self._chooser.itemData(index))
