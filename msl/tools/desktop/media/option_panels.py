# tools/desktop/media/option_panels.py
"""The settings of the Media tool's actions. Each panel shows the choices in
plain words, remembers them (settings() / apply_settings()), and turns them
into a Job with job(source, output) — the ffmpeg arguments are the recipes'
business (core/media/recipes.py), never the panel's.

PANELS lists them in the order the action picker shows them.
"""
import tempfile
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import (Job, MediaError, Overlays, adjust, compare, convert, default_output,
                                      extract_audio, frame, gif, join, remove_audio, replace_audio,
                                      sequence_to_video, shrink, stamp, to_frames, trim)
from msl_tools.msl.core.media.recipes import FORMATS, GAPS_ERROR, GAPS_HOLD, IMAGE_FORMATS, SOUND_FORMATS
from msl_tools.msl.core.media.thumbnail import frames_at
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES, MediaSource, format_time, parse_time
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.compositions.range_strip import RangeStrip
from msl_tools.msl.ui.workers.result_worker import ResultWorker

NL = chr(10)


class OptionPanel(qt.QtWidgets.QFrame):
    """Base of an action's settings: a two-column form (dimmed caption, control).

    A subclass sets:
        KEY / TITLE / BUTTON — its id, its name in the action picker, the start button's text
        TIP — one line saying what the action does (the picker's tooltip)
        COMBINES — True: ONE job is made from all the sources (join, compare);
                   False: one job per source
        PRESETS — built-in presets {name: settings}
    and implements:
        accepts(sources) — is this action offered for these sources
        set_sources(sources) — new sources were loaded
        job(source, output) / combined_job(sources, output) — may raise MediaError
        output_for(source, folder, taken) — the default name of a result
        settings() / apply_settings(dict) — what is remembered and what a preset holds

    `tools` (given by the page) is a callable returning the FfmpegTools in
    use — for panels that show previews.

    Signals:
        changed() — a choice changed (the page refreshes what depends on it).
    """

    KEY = TITLE = BUTTON = TIP = ""
    COMBINES = False
    PRESETS: dict = {}
    CAPTION_WIDTH = 84

    changed = qt.QtCore.Signal()

    def __init__(self, tools=None, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaOptions")
        self._tools = tools or (lambda: None)
        self._form = qt.QtWidgets.QGridLayout(self)
        self._form.setContentsMargins(12, 10, 12, 10)
        self._form.setHorizontalSpacing(10)
        self._form.setVerticalSpacing(8)
        self._form.setColumnMinimumWidth(0, self.CAPTION_WIDTH)
        self._form.setColumnStretch(1, 1)
        self._rows: list[tuple] = []

    # --- building the form ---------------------------------------------------------------

    def _add_row(self, caption: str, *widgets, hint: str = "") -> int:
        """Adds a row: the caption, then the widgets left to right. A line
        edit without a fixed width (or a label that wraps) takes the room
        that is left; otherwise the row ends empty. Returns the row's index
        for _set_row_visible()."""
        row = self._form.rowCount()
        label = qt.QtWidgets.QLabel(caption)
        label.setObjectName("mediaCaption")
        holder = qt.QtWidgets.QWidget()
        line = qt.QtWidgets.QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        stretches = False
        for widget in widgets:
            grows = (isinstance(widget, (qt.QtWidgets.QLineEdit, RangeStrip)) and widget.maximumWidth() > 1000)                 or (isinstance(widget, qt.QtWidgets.QLabel) and widget.wordWrap())
            stretches = stretches or grows
            line.addWidget(widget, 1 if grows else 0)
        if hint:
            note = qt.QtWidgets.QLabel(hint)
            note.setObjectName("mediaHint")
            note.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
            line.addWidget(note, 1)
        elif not stretches:
            line.addStretch(1)
        self._form.addWidget(label, row, 0)
        self._form.addWidget(holder, row, 1)
        self._rows.append((label, holder))
        return len(self._rows) - 1

    def _set_row_visible(self, index: int, visible: bool) -> None:
        for widget in self._rows[index]:
            widget.setVisible(visible)

    def _switch(self, options, current: str, tooltip: str = "") -> SegmentedControl:
        """A SegmentedControl over `options` (a list, or the keys of a dict)."""
        control = SegmentedControl(list(options), current)
        control.setToolTip(tooltip)
        control.current_changed.connect(lambda _option: self.changed.emit())
        return control

    def _check(self, text: str, checked: bool = False, tooltip: str = "") -> BaseCheckbox:
        box = BaseCheckbox(text)
        box.setChecked(checked)
        box.setToolTip(tooltip)
        box.toggled.connect(lambda _checked: self.changed.emit())
        return box

    def _file_field(self, placeholder: str, title: str, patterns: str) -> tuple:
        """(line edit, browse button) for choosing a file."""
        field = qt.QtWidgets.QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setClearButtonEnabled(True)
        field.textChanged.connect(lambda _text: self.changed.emit())
        button = IconPushButton(UiResources().iconManager.get_icon("browse", sub_folder="actions"), title,
                                fallback_text="…")
        button.setFixedSize(26, 22)

        def browse() -> None:
            path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(self, title, field.text(),
                                                                     f"{patterns};;All files (*.*)")
            if path:
                field.setText(path)

        button.clicked.connect(browse)
        return field, button

    # --- for subclasses --------------------------------------------------------------------

    @staticmethod
    def accepts(sources: list) -> bool:
        return False

    def set_sources(self, sources: list) -> None:
        pass

    def job(self, source: MediaSource, output: Path) -> Job:
        raise NotImplementedError

    def combined_job(self, sources: list, output: Path) -> Job:
        raise NotImplementedError

    def suffix(self, source: MediaSource) -> str:
        """The file suffix of a result."""
        return ".mp4"

    TAG = ""  # what is added to the source's name for the result
    INTO_FOLDER = False  # the result is a FOLDER of files (frames), not one file

    def output_for(self, source: MediaSource, folder=None, taken=()) -> Path:
        return default_output(source.sequence or source.path, self.TAG, self.suffix(source), folder=folder, taken=taken)

    def settings(self) -> dict:
        return {}

    def apply_settings(self, settings: dict) -> None:
        pass


def _videos(sources: list) -> bool:
    return bool(sources) and not any(source.is_sequence for source in sources)


QUALITY_HIGH = {"Best": "best", "High": "high", "Good": "good", "Small": "small"}
SPEEDS = {"Fast": "fast", "Balanced": "balanced", "Compact": "compact"}
SPEED_TIP = ("Fast: done soonest, a bigger file." + NL + "Balanced: the usual choice." + NL
             + "Compact: takes longer, the smallest file at the same quality.")
VIDEO_FORMATS = {"MP4": "mp4", "ProRes": "prores", "ProRes HQ": "prores_hq", "DNxHR": "dnxhr_hq"}
FORMAT_TIP = ("MP4: small, plays everywhere — for watching and sending." + NL
              + "ProRes / ProRes HQ / DNxHR: big files that keep far more of the picture — for editing and grading.")
IMAGE_PATTERNS = "Pictures (*.png *.jpg *.jpeg *.tif *.tiff *.tga *.bmp *.webp)"
SOUND_PATTERNS = "Sound (" + " ".join(f"*{suffix}" for suffix in AUDIO_SUFFIXES) + ")"


class _OverlayRows:
    """Mixin for a panel that can draw on the picture: the rows "Burn in"
    (frame number, time, date), "Label" and "Watermark" (image, size,
    opacity), and their settings. Call _add_overlay_rows() where they go."""

    MARK_SIZES = ("10%", "15%", "25%", "40%")
    MARK_OPACITIES = ("100%", "70%", "40%")

    def _add_overlay_rows(self) -> list[int]:
        self._burn_frame = self._check("Frame number", tooltip="The number of each frame, bottom right")
        self._burn_time = self._check("Time", tooltip="The time since the start, bottom centre")
        self._burn_date = self._check("Date", tooltip="Today’s date, top right")
        self._label = qt.QtWidgets.QLineEdit()
        self._label.setPlaceholderText("text for the top-left corner — a shot name, a version")
        self._label.textChanged.connect(lambda _text: self.changed.emit())
        self._mark, self._mark_button = self._file_field("none — a picture for the bottom-right corner",
                                                         "A picture to use as a watermark", IMAGE_PATTERNS)
        self._mark_size = BaseComboBox(list(self.MARK_SIZES), "15%")
        self._mark_size.setFixedWidth(64)
        self._mark_size.setToolTip("The watermark’s width, as a part of the frame’s width")
        self._mark_opacity = BaseComboBox(list(self.MARK_OPACITIES), "70%")
        self._mark_opacity.setFixedWidth(68)
        self._mark_opacity.setToolTip("How solid the watermark is")
        for combo in (self._mark_size, self._mark_opacity):
            combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        return [self._add_row("Burn in", self._burn_frame, self._burn_time, self._burn_date),
                self._add_row("Label", self._label),
                self._add_row("Watermark", self._mark, self._mark_button, self._mark_size, self._mark_opacity)]

    def _overlays(self) -> Overlays:
        return Overlays(frame_number=self._burn_frame.isChecked(), time=self._burn_time.isChecked(),
                        date=self._burn_date.isChecked(), label=self._label.text().strip(),
                        watermark=self._mark.text().strip(),
                        watermark_size=int(self._mark_size.currentText().rstrip("%")),
                        watermark_opacity=int(self._mark_opacity.currentText().rstrip("%")))

    def _overlay_settings(self) -> dict:
        return {"burn_frame": self._burn_frame.isChecked(), "burn_time": self._burn_time.isChecked(),
                "burn_date": self._burn_date.isChecked(), "label": self._label.text(),
                "watermark": self._mark.text(), "watermark_size": self._mark_size.currentText(),
                "watermark_opacity": self._mark_opacity.currentText()}

    def _apply_overlay_settings(self, settings: dict) -> None:
        self._burn_frame.set_checked_immediate(bool(settings.get("burn_frame", False)))
        self._burn_time.set_checked_immediate(bool(settings.get("burn_time", False)))
        self._burn_date.set_checked_immediate(bool(settings.get("burn_date", False)))
        self._label.setText(str(settings.get("label", "")))
        self._mark.setText(str(settings.get("watermark", "")))
        if str(settings.get("watermark_size", "")) in self.MARK_SIZES:
            self._mark_size.setCurrentText(str(settings["watermark_size"]))
        if str(settings.get("watermark_opacity", "")) in self.MARK_OPACITIES:
            self._mark_opacity.setCurrentText(str(settings["watermark_opacity"]))


class SequencePanel(_OverlayRows, OptionPanel):
    """Image sequence -> video: frame rate, quality, speed, format, optional
    sound, burn-ins / watermark, and what to do about missing frames."""

    KEY, TITLE, BUTTON = "sequence", "To video", "Create video"
    TIP = "Turn the frames into a video"
    FRAME_RATES = ("12", "15", "23.976", "24", "25", "29.97", "30", "48", "50", "60")
    PRESETS = {
        "Preview · fast": {"quality": "Good", "speed": "Fast", "format": "MP4"},
        "Review · frame numbers": {"quality": "Good", "speed": "Balanced", "format": "MP4",
                                   "burn_frame": True, "burn_date": True, "overlays_open": True},
        "For editing · ProRes": {"format": "ProRes"},
    }

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._fps = BaseComboBox(list(self.FRAME_RATES), "24")
        self._fps.setFixedWidth(84)
        self._fps.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self._format = self._switch(VIDEO_FORMATS, "MP4", FORMAT_TIP)
        self._quality = self._switch(QUALITY_HIGH, "Good", "How good the picture looks — better is also bigger")
        self._speed = self._switch(SPEEDS, "Balanced", SPEED_TIP)
        self._sound, self._sound_button = self._file_field("none — choose a sound file, or drop one here",
                                                           "The sound to put under the video", SOUND_PATTERNS)
        self._more = self._check("Draw on the picture", tooltip="Frame numbers, the date, a label, a watermark")
        self._hold = self._check("Show the frame before a gap until the next one")

        self._add_row("Frame rate", self._fps, hint="frames per second")
        self._add_row("Format", self._format)
        self._quality_row = self._add_row("Quality", self._quality)
        self._speed_row = self._add_row("Encoding", self._speed)
        self._add_row("Sound", self._sound, self._sound_button)
        self._add_row("Burn-ins", self._more)
        self._overlay_rows = self._add_overlay_rows()
        self._gap_row = self._add_row("Gaps", self._hold)
        self._set_row_visible(self._gap_row, False)
        self._format.current_changed.connect(lambda _option: self._sync())
        self._more.toggled.connect(lambda _checked: self._sync())
        self._sync()

    def _sync(self) -> None:
        mp4 = self._format.current() == "MP4"
        self._set_row_visible(self._quality_row, mp4)   # the editing formats have no quality / speed choice
        self._set_row_visible(self._speed_row, mp4)
        for row in self._overlay_rows:
            self._set_row_visible(row, self._more.isChecked())

    @staticmethod
    def accepts(sources: list) -> bool:
        return bool(sources) and all(source.is_sequence for source in sources)

    def set_sources(self, sources: list) -> None:
        self._sound.clear()  # the sound belonged to the previous sequence
        missing = sum(len(source.sequence.missing) for source in sources)
        self._set_row_visible(self._gap_row, bool(missing))
        if missing:
            self._hold.setToolTip(f"{missing} frame(s) have no file. Ticked: the video keeps its length, the frame "
                                  f"before each gap stays on screen. Not ticked: the video isn’t made.")

    def set_sound(self, path: str) -> None:
        self._sound.setText(path)

    def suffix(self, source: MediaSource) -> str:
        return FORMATS[VIDEO_FORMATS[self._format.current()]][2]

    def job(self, source: MediaSource, output: Path) -> Job:
        sound = self._sound.text().strip()
        if sound and not Path(sound).is_file():
            raise MediaError(f"The sound file isn’t there: {sound}")
        try:
            fps = float(self._fps.currentText())
        except ValueError as error:
            raise MediaError("The frame rate must be a number.") from error
        overlays = self._overlays() if self._more.isChecked() else None
        return sequence_to_video(source.sequence, output, fps=fps, quality=QUALITY_HIGH[self._quality.current()],
                                 speed=SPEEDS[self._speed.current()], audio=sound or None,
                                 gaps=GAPS_HOLD if self._hold.isChecked() else GAPS_ERROR,
                                 overlays=overlays if overlays is not None and overlays.any() else None,
                                 frame_size=(source.info.width, source.info.height),
                                 video_format=VIDEO_FORMATS[self._format.current()])

    def settings(self) -> dict:
        return {"fps": self._fps.currentText(), "quality": self._quality.current(), "speed": self._speed.current(),
                "format": self._format.current(), "overlays_open": self._more.isChecked(),
                **self._overlay_settings()}

    def apply_settings(self, settings: dict) -> None:
        if str(settings.get("fps", "")) in self.FRAME_RATES:
            self._fps.setCurrentText(str(settings["fps"]))
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        self._speed.set_current(str(settings.get("speed", "")), animate=False)
        self._format.set_current(str(settings.get("format", "")), animate=False)
        self._more.set_checked_immediate(bool(settings.get("overlays_open", False)))
        self._apply_overlay_settings(settings)
        self._sync()


class ShrinkPanel(OptionPanel):
    """Video -> a smaller copy for sending: frame size, then either a quality
    or a file size to fit into."""

    KEY, TITLE, BUTTON, TAG = "shrink", "Make smaller", "Make smaller", "_small"
    TIP = "A lighter copy for sending"
    HEIGHTS = {"Keep": 0, "1080p": 1080, "720p": 720, "480p": 480}
    BY_QUALITY, BY_SIZE = "By quality", "Fit into a size"
    QUALITIES = {"Good": "good", "Small": "small", "Smallest": "smallest"}
    PRESETS = {
        "Messenger · 10 MB": {"height": "720p", "mode": BY_SIZE, "megabytes": "10"},
        "Mail · 25 MB": {"height": "1080p", "mode": BY_SIZE, "megabytes": "25"},
        "Preview 720p": {"height": "720p", "mode": BY_QUALITY, "quality": "Small"},
        "Tiny 480p": {"height": "480p", "mode": BY_QUALITY, "quality": "Smallest"},
    }

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._height = self._switch(self.HEIGHTS, "720p", "The height of the picture. A video that is already "
                                                          "smaller is never enlarged.")
        self._mode = self._switch([self.BY_QUALITY, self.BY_SIZE], self.BY_QUALITY,
                                  "By quality: pick how it should look, the size is what it comes to." + NL
                                  + "Fit into a size: pick the megabytes, the quality is what fits.")
        self._quality = self._switch(self.QUALITIES, "Small")
        self._megabytes = qt.QtWidgets.QLineEdit("10")
        self._megabytes.setFixedWidth(64)
        self._megabytes.setValidator(qt.QtGui.QDoubleValidator(0.1, 100000.0, 1, self))
        self._megabytes.textChanged.connect(lambda _text: self.changed.emit())
        self._megabytes_note = qt.QtWidgets.QLabel("MB")
        self._megabytes_note.setObjectName("mediaHint")
        self._sound = self._check("Keep the sound", True)

        self._add_row("Frame size", self._height)
        self._add_row("Aim for", self._mode)
        self._quality_row = self._add_row("Quality", self._quality)
        self._size_row = self._add_row("File size", self._megabytes, self._megabytes_note)
        self._sound_row = self._add_row("Sound", self._sound)
        self._mode.current_changed.connect(lambda _option: self._sync())
        self._sync()

    def _sync(self) -> None:
        by_size = self._mode.current() == self.BY_SIZE
        self._set_row_visible(self._quality_row, not by_size)
        self._set_row_visible(self._size_row, by_size)

    accepts = staticmethod(_videos)

    def set_sources(self, sources: list) -> None:
        self._set_row_visible(self._sound_row, any(source.info.has_audio for source in sources))

    def job(self, source: MediaSource, output: Path) -> Job:
        target = None
        if self._mode.current() == self.BY_SIZE:
            try:
                target = float(self._megabytes.text().replace(",", "."))
            except ValueError as error:
                raise MediaError("Type the size in megabytes, for example 10.") from error
            if target <= 0:
                raise MediaError("The size must be more than zero.")
        return shrink(source.info, output, max_height=self.HEIGHTS[self._height.current()],
                      quality=self.QUALITIES[self._quality.current()], target_mb=target,
                      keep_audio=self._sound.isChecked())

    def settings(self) -> dict:
        return {"height": self._height.current(), "mode": self._mode.current(), "quality": self._quality.current(),
                "megabytes": self._megabytes.text()}

    def apply_settings(self, settings: dict) -> None:
        self._height.set_current(str(settings.get("height", "")), animate=False)
        self._mode.set_current(str(settings.get("mode", "")), animate=False)
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        if str(settings.get("megabytes", "")).strip():
            self._megabytes.setText(str(settings["megabytes"]))
        self._sync()


class TrimPanel(OptionPanel):
    """Video -> one piece of it. The piece is picked by eye on a strip of
    the video's frames (two handles) or typed as times; the frames at both
    ends are shown, so one sees where the cut falls."""

    KEY, TITLE, BUTTON, TAG = "trim", "Trim", "Cut this piece", "_cut"
    TIP = "Keep one piece of the video"
    EXACT, FAST = "Exact", "Fast"
    STRIP_FRAMES = 12
    PREVIEW_SIZE = qt.QtCore.QSize(128, 72)
    PREVIEW_DELAY_MS = 350

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._source: MediaSource | None = None
        self._duration = 0.0
        self._syncing = False
        self._workers: list = []
        self._token = 0
        self._strip = RangeStrip()
        self._strip.setToolTip("Drag the handles to pick the piece; drag between them to move it")
        self._start = qt.QtWidgets.QLineEdit("0:00")
        self._end = qt.QtWidgets.QLineEdit()
        for field in (self._start, self._end):
            field.setFixedWidth(84)
            field.setToolTip("Seconds, or minutes:seconds — 12.5, 0:12.5, 1:02:03")
            field.textChanged.connect(self._on_times_typed)
        self._length_label = qt.QtWidgets.QLabel()
        self._length_label.setObjectName("mediaHint")
        self._first_preview, self._last_preview = self._preview(), self._preview()
        self._mode = self._switch([self.EXACT, self.FAST], self.EXACT,
                                  "Exact: the cut is where you asked, to the frame (the piece is re-encoded)."
                                  + NL + "Fast: instant and lossless, but the cut can start a moment early "
                                         "and run a moment long.")
        self._preview_timer = qt.QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(self.PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._load_previews)

        to_caption = qt.QtWidgets.QLabel("to")
        to_caption.setObjectName("mediaCaption")
        self._strip_row = self._add_row("Piece", self._strip)
        self._add_row("From", self._start, to_caption, self._end, self._length_label)
        self._add_row("Frames", self._first_preview, self._last_preview, hint="the first and the last frame of the piece")
        self._add_row("Cut", self._mode)
        self._strip.range_changed.connect(self._on_strip_moved)

    def _preview(self) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel()
        label.setObjectName("mediaThumbnail")
        label.setFixedSize(self.PREVIEW_SIZE)
        label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        return label

    accepts = staticmethod(_videos)

    def set_sources(self, sources: list) -> None:
        source = sources[0]
        # With several videos the same times are cut out of each; the strip shows the first.
        self._source, self._duration = source, min(other.info.duration for other in sources)
        self._syncing = True
        self._start.setText("0:00")
        self._end.setText(format_time(self._duration))
        self._strip.set_range(0.0, 1.0)
        self._syncing = False
        self._strip.set_pictures([None] * self.STRIP_FRAMES)
        self._update_length()
        self._load_strip()
        self._preview_timer.start()

    def suffix(self, source: MediaSource) -> str:
        return ".mp4" if self._mode.current() == self.EXACT else source.path.suffix

    # --- times <-> strip -------------------------------------------------------------------

    def _times(self) -> tuple:
        return parse_time(self._start.text()), parse_time(self._end.text())

    def _on_strip_moved(self, start: float, end: float) -> None:
        self._syncing = True
        self._start.setText(format_time(round(start * self._duration, 2)))
        self._end.setText(format_time(round(end * self._duration, 2)))
        self._syncing = False
        self._after_change()

    def _on_times_typed(self) -> None:
        if self._syncing:
            return
        start, end = self._times()
        if start is not None and end is not None and end > start and self._duration:
            self._strip.set_range(start / self._duration, min(end, self._duration) / self._duration)
        self._after_change()

    def _after_change(self) -> None:
        self._update_length()
        self._preview_timer.start()
        self.changed.emit()

    def _update_length(self) -> None:
        start, end = self._times()
        if start is None or end is None:
            text = "type a time like 0:12.5"
        elif end <= start:
            text = "the end must be after the start"
        else:
            text = f"a piece of {format_time(round(min(end, self._duration or end) - start, 2))}"
        self._length_label.setText(text)

    # --- pictures (made by ffmpeg on worker threads) -------------------------------------------

    def _cache(self) -> Path:
        return Path(tempfile.gettempdir()) / "msl_tools" / "media" / "trim"

    def _run(self, target, on_done) -> None:
        worker = ResultWorker(target, parent=self)
        self._workers.append(worker)
        worker.done.connect(on_done)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _load_strip(self) -> None:
        tools, source = self._tools(), self._source
        if tools is None or source is None:
            return
        self._token += 1
        token = self._token
        count = self.STRIP_FRAMES
        times = [source.info.duration * (index + 0.5) / count for index in range(count)]

        def done(paths) -> None:
            if token == self._token:
                self._strip.set_pictures([qt.QtGui.QPixmap(str(path)) if path is not None else None for path in paths])

        self._run(lambda: frames_at(tools, source.info, times, self._cache(), f"strip_{id(self)}", 160), done)

    def _load_previews(self) -> None:
        tools, source = self._tools(), self._source
        start, end = self._times()
        if tools is None or source is None or start is None or end is None:
            return
        token = self._token
        last = max(min(end, source.info.duration) - 0.04, 0.0)  # the last frame that is still in the piece

        def done(paths) -> None:
            if token != self._token:
                return
            for label, path in zip((self._first_preview, self._last_preview), paths):
                pixmap = qt.QtGui.QPixmap(str(path)) if path is not None else qt.QtGui.QPixmap()
                if pixmap.isNull():
                    label.setPixmap(qt.QtGui.QPixmap())
                    continue
                ratio = self.devicePixelRatioF()
                scaled = pixmap.scaled(self.PREVIEW_SIZE * ratio, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                       qt.QtCore.Qt.TransformationMode.SmoothTransformation)
                scaled.setDevicePixelRatio(ratio)
                label.setPixmap(scaled)

        self._run(lambda: frames_at(tools, source.info, [start, last], self._cache(), f"ends_{id(self)}", 256), done)

    # --- the job -------------------------------------------------------------------------------

    def job(self, source: MediaSource, output: Path) -> Job:
        start, end = self._times()
        if start is None or end is None:
            raise MediaError("Type the times as seconds or minutes:seconds, for example 0:12.5.")
        if start >= (source.info.duration or start + 1):
            raise MediaError(f"The video is only {format_time(source.info.duration)} long.")
        return trim(source.info, output, start, end, exact=self._mode.current() == self.EXACT)

    def settings(self) -> dict:
        return {"mode": self._mode.current()}

    def apply_settings(self, settings: dict) -> None:
        self._mode.set_current(str(settings.get("mode", "")), animate=False)


class StampPanel(_OverlayRows, OptionPanel):
    """Video -> a copy with burn-ins and / or a watermark drawn over it."""

    KEY, TITLE, BUTTON, TAG = "stamp", "Stamp", "Stamp the video", "_stamped"
    TIP = "Draw frame numbers, the date, a label or a watermark on the picture"
    PRESETS = {"Review · frame numbers": {"burn_frame": True, "burn_date": True, "burn_time": False},
               "Time code": {"burn_frame": False, "burn_date": False, "burn_time": True}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._add_overlay_rows()
        self._quality = self._switch(QUALITY_HIGH, "High", "How good the picture looks — better is also bigger")
        self._add_row("Quality", self._quality)
        self._burn_frame.set_checked_immediate(True)

    accepts = staticmethod(_videos)

    def job(self, source: MediaSource, output: Path) -> Job:
        return stamp(source.info, output, self._overlays(), quality=QUALITY_HIGH[self._quality.current()])

    def settings(self) -> dict:
        return {"quality": self._quality.current(), **self._overlay_settings()}

    def apply_settings(self, settings: dict) -> None:
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        self._apply_overlay_settings(settings)


class SoundPanel(OptionPanel):
    """Video -> its sound taken out as a file, the sound removed, or another sound put under it."""

    KEY, TITLE = "sound", "Sound"
    TIP = "Take the sound out, remove it, or replace it"
    EXTRACT, REMOVE, REPLACE = "Take it out", "Remove", "Replace"
    SOUND_KINDS = {"WAV": "wav", "MP3": "mp3", "M4A": "m4a"}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._mode = self._switch([self.EXTRACT, self.REMOVE, self.REPLACE], self.EXTRACT,
                                  "Take it out: the sound as a file of its own." + NL
                                  + "Remove: the same video without sound." + NL
                                  + "Replace: the same video with another sound.")
        self._kind = self._switch(self.SOUND_KINDS, "WAV", "WAV: exactly as it is, big. MP3 / M4A: small.")
        self._new, self._new_button = self._file_field("the sound file to use", "The sound to put under the video",
                                                       SOUND_PATTERNS)
        self._add_row("Do", self._mode)
        self._kind_row = self._add_row("As", self._kind)
        self._new_row = self._add_row("New sound", self._new, self._new_button)
        self._note_row = self._add_row("", hint="The picture is copied as it is — instant, nothing is lost.")
        self._mode.current_changed.connect(lambda _option: self._sync())
        self._sync()

    def _sync(self) -> None:
        mode = self._mode.current()
        self._set_row_visible(self._kind_row, mode == self.EXTRACT)
        self._set_row_visible(self._new_row, mode == self.REPLACE)
        self._set_row_visible(self._note_row, mode != self.EXTRACT)

    BUTTON = property(lambda self: {self.EXTRACT: "Take the sound out", self.REMOVE: "Remove the sound",
                                    self.REPLACE: "Replace the sound"}[self._mode.current()])
    TAG = property(lambda self: {self.EXTRACT: "", self.REMOVE: "_silent", self.REPLACE: "_sound"}[self._mode.current()])

    accepts = staticmethod(_videos)

    def set_sound(self, path: str) -> None:
        self._mode.set_current(self.REPLACE, animate=False)
        self._new.setText(path)
        self._sync()

    def suffix(self, source: MediaSource) -> str:
        if self._mode.current() == self.EXTRACT:
            return SOUND_FORMATS[self.SOUND_KINDS[self._kind.current()]][1]
        return source.path.suffix or ".mp4"

    def job(self, source: MediaSource, output: Path) -> Job:
        mode = self._mode.current()
        if mode == self.EXTRACT:
            return extract_audio(source.info, output, self.SOUND_KINDS[self._kind.current()])
        if mode == self.REMOVE:
            return remove_audio(source.info, output)
        sound = self._new.text().strip()
        if not sound:
            raise MediaError("Choose the sound file to put under the video.")
        if not Path(sound).is_file():
            raise MediaError(f"The sound file isn’t there: {sound}")
        return replace_audio(source.info, output, sound)

    def settings(self) -> dict:
        return {"mode": self._mode.current(), "kind": self._kind.current()}

    def apply_settings(self, settings: dict) -> None:
        self._mode.set_current(str(settings.get("mode", "")), animate=False)
        self._kind.set_current(str(settings.get("kind", "")), animate=False)
        self._sync()


class GifPanel(OptionPanel):
    """Video -> an animated GIF for a chat or a document."""

    KEY, TITLE, BUTTON = "gif", "GIF", "Create GIF"
    TIP = "An animated picture for a chat or a document"
    WIDTHS = {"320": 320, "480": 480, "640": 640, "800": 800, "Keep": 0}
    RATES = ("8", "10", "12", "15", "24")
    PRESETS = {"Chat · 480": {"width": "480", "fps": "12"}, "Light · 320": {"width": "320", "fps": "10"},
               "Smooth · 640": {"width": "640", "fps": "24"}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._width = self._switch(self.WIDTHS, "480", "The GIF’s width in pixels — narrower is much lighter")
        self._fps = self._switch(self.RATES, "12", "Frames per second — fewer is lighter, 12 still reads as motion")
        self._add_row("Width", self._width)
        self._add_row("Frame rate", self._fps, hint="A GIF is heavy: keep it short — trim the video first.")

    accepts = staticmethod(_videos)

    def suffix(self, source: MediaSource) -> str:
        return ".gif"

    def job(self, source: MediaSource, output: Path) -> Job:
        return gif(source.info, output, width=self.WIDTHS[self._width.current()], fps=float(self._fps.current()))

    def settings(self) -> dict:
        return {"width": self._width.current(), "fps": self._fps.current()}

    def apply_settings(self, settings: dict) -> None:
        self._width.set_current(str(settings.get("width", "")), animate=False)
        self._fps.set_current(str(settings.get("fps", "")), animate=False)


class EditingPanel(OptionPanel):
    """Video -> an editing format (ProRes / DNxHR)."""

    KEY, TITLE, BUTTON = "editing", "For editing", "Convert"
    TIP = "A big file that keeps the picture — for editing and grading"
    KINDS = {"ProRes": "prores", "ProRes HQ": "prores_hq", "4444": "prores_4444", "DNxHR": "dnxhr_hq"}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._kind = self._switch(self.KINDS, "ProRes",
                                  "ProRes: the usual choice. ProRes HQ: more of the picture, bigger." + NL
                                  + "4444: ProRes 4444 — the most, with transparency. DNxHR: Avid’s counterpart (HQ).")
        self._add_row("Format", self._kind)
        self._add_row("", hint="These files are large — about 50–100 MB for ten seconds of 720p — and are meant "
                               "for an editing program, not for sending.")

    accepts = staticmethod(_videos)
    TAG = property(lambda self: "_" + self.KINDS[self._kind.current()])

    def suffix(self, source: MediaSource) -> str:
        return ".mov"

    def job(self, source: MediaSource, output: Path) -> Job:
        return convert(source.info, output, self.KINDS[self._kind.current()])

    def settings(self) -> dict:
        return {"kind": self._kind.current()}

    def apply_settings(self, settings: dict) -> None:
        self._kind.set_current(str(settings.get("kind", "")), animate=False)


class AdjustPanel(OptionPanel):
    """Video -> a corrected copy: turned, cropped to a shape, at another frame rate, faster or slower."""

    KEY, TITLE, BUTTON, TAG = "adjust", "Adjust", "Adjust the video", "_adjusted"
    TIP = "Turn, crop, change the frame rate or the speed"
    TURNS = {"No": 0, "90° right": 90, "90° left": -90, "180°": 180}
    SHAPES = {"Keep": "", "16:9": "16:9", "4:3": "4:3", "1:1": "1:1", "9:16": "9:16"}
    RATES = {"Keep": None, "24": 24.0, "25": 25.0, "30": 30.0, "60": 60.0}
    FACTORS = {"0.25×": 0.25, "0.5×": 0.5, "1×": 1.0, "1.5×": 1.5, "2×": 2.0, "4×": 4.0}
    PRESETS = {"Vertical 9:16": {"turn": "No", "shape": "9:16", "rate": "Keep", "factor": "1×"},
               "Square": {"turn": "No", "shape": "1:1", "rate": "Keep", "factor": "1×"},
               "Twice as fast": {"turn": "No", "shape": "Keep", "rate": "Keep", "factor": "2×"}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._turn = self._switch(self.TURNS, "No", "Turn the picture")
        self._shape = self._switch(self.SHAPES, "Keep", "Crop the picture around its centre to this shape")
        self._rate = self._switch(self.RATES, "Keep", "Frames per second of the result")
        self._factor = self._switch(self.FACTORS, "1×", "Play faster or slower — the sound follows at its own pitch")
        self._add_row("Turn", self._turn)
        self._add_row("Crop to", self._shape)
        self._add_row("Frame rate", self._rate)
        self._add_row("Speed", self._factor)

    accepts = staticmethod(_videos)

    def job(self, source: MediaSource, output: Path) -> Job:
        return adjust(source.info, output, rotate=self.TURNS[self._turn.current()],
                      aspect=self.SHAPES[self._shape.current()], fps=self.RATES[self._rate.current()],
                      speed_factor=self.FACTORS[self._factor.current()])

    def settings(self) -> dict:
        return {"turn": self._turn.current(), "shape": self._shape.current(), "rate": self._rate.current(),
                "factor": self._factor.current()}

    def apply_settings(self, settings: dict) -> None:
        self._turn.set_current(str(settings.get("turn", "")), animate=False)
        self._shape.set_current(str(settings.get("shape", "")), animate=False)
        self._rate.set_current(str(settings.get("rate", "")), animate=False)
        self._factor.set_current(str(settings.get("factor", "")), animate=False)


class FramesPanel(OptionPanel):
    """Video -> pictures: every frame (or every Nth) as an image sequence in
    a folder of its own, or ONE frame, picked by time and shown before it
    is saved."""

    KEY, TITLE = "frames", "To frames"
    TIP = "Take the video apart into pictures — an image sequence, or one frame"
    ALL, SOME, ONE = "All frames", "Every Nth", "One frame"
    KINDS = {"PNG": "png", "JPG": "jpg", "TIFF": "tiff"}
    JPG_QUALITIES = {"Best": "best", "Good": "good", "Small": "small"}
    STEPS = ("2", "3", "4", "5", "10", "25")
    DIGITS = ("3", "4", "5", "6")
    PREVIEW_SIZE = qt.QtCore.QSize(128, 72)
    PREVIEW_DELAY_MS = 350
    PRESETS = {"PNG sequence": {"take": ALL, "kind": "PNG", "first": "1", "digits": "4"},
               "JPG, every 5th": {"take": SOME, "step": "5", "kind": "JPG", "jpg": "Good"}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._source: MediaSource | None = None
        self._workers: list = []
        self._token = 0
        self._take = self._switch([self.ALL, self.SOME, self.ONE], self.ALL,
                                  "All frames: the whole video as an image sequence." + NL
                                  + "Every Nth: a thinner sequence — every 2nd, 5th, ... frame." + NL
                                  + "One frame: a single picture from the moment you pick.")
        self._step = BaseComboBox(list(self.STEPS), "2")
        self._step.setFixedWidth(64)
        self._step.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self._at = qt.QtWidgets.QLineEdit("0:00")
        self._at.setFixedWidth(84)
        self._at.setToolTip("Seconds, or minutes:seconds — 12.5, 0:12.5, 1:02:03")
        self._at.textChanged.connect(self._on_time_typed)
        self._preview = qt.QtWidgets.QLabel()
        self._preview.setObjectName("mediaThumbnail")
        self._preview.setFixedSize(self.PREVIEW_SIZE)
        self._preview.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._kind = self._switch(self.KINDS, "PNG", "PNG: exact, big. JPG: small, slightly lossy. TIFF: exact, "
                                                     "for programs that want it.")
        self._jpg = self._switch(self.JPG_QUALITIES, "Best", "How good the JPG pictures are — better is bigger")
        self._first = qt.QtWidgets.QLineEdit("1")
        self._first.setFixedWidth(64)
        self._first.setValidator(qt.QtGui.QIntValidator(0, 9_999_999, self))
        self._first.setToolTip("The number of the first picture")
        self._first.textChanged.connect(lambda _text: self.changed.emit())
        self._digits = BaseComboBox(list(self.DIGITS), "4")
        self._digits.setFixedWidth(56)
        self._digits.setToolTip("How many digits a number has: 4 = 0001, 0002, …")
        self._digits.currentIndexChanged.connect(lambda _index: self.changed.emit())
        digits_caption = qt.QtWidgets.QLabel("digits")
        digits_caption.setObjectName("mediaHint")
        self._example = qt.QtWidgets.QLabel()
        self._example.setObjectName("mediaHint")
        self._example.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._preview_timer = qt.QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(self.PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._load_preview)

        self._add_row("Take", self._take)
        self._step_row = self._add_row("Every", self._step, hint="th frame")
        self._at_row = self._add_row("At", self._at, self._preview)
        self._add_row("Format", self._kind)
        self._jpg_row = self._add_row("Quality", self._jpg)
        self._number_row = self._add_row("Numbers from", self._first, self._digits, digits_caption, self._example)
        self._take.current_changed.connect(lambda _option: self._sync())
        self._kind.current_changed.connect(lambda _option: self._sync())
        self.changed.connect(self._update_example)
        self._sync()

    def _sync(self) -> None:
        take = self._take.current()
        self._set_row_visible(self._step_row, take == self.SOME)
        self._set_row_visible(self._at_row, take == self.ONE)
        self._set_row_visible(self._number_row, take != self.ONE)
        self._set_row_visible(self._jpg_row, self._kind.current() == "JPG")
        self._update_example()
        if take == self.ONE:
            self._preview_timer.start()

    BUTTON = property(lambda self: "Save this frame" if self._take.current() == self.ONE else "Save the frames")
    TAG = property(lambda self: "_frame" if self._take.current() == self.ONE else "_frames")
    INTO_FOLDER = property(lambda self: self._take.current() != self.ONE)

    accepts = staticmethod(_videos)

    def set_sources(self, sources: list) -> None:
        self._source = sources[0]
        self._token += 1
        self._update_example()
        if self._take.current() == self.ONE:
            self._preview_timer.start()

    def suffix(self, source: MediaSource) -> str:
        """One frame is a picture file; a sequence goes into a FOLDER (no suffix)."""
        return IMAGE_FORMATS[self.KINDS[self._kind.current()]][1] if self._take.current() == self.ONE else ""

    def _update_example(self) -> None:
        if self._source is None:
            return
        try:
            number = str(int(self._first.text() or 0)).zfill(int(self._digits.currentText()))
        except ValueError:
            number = "0001"
        suffix = IMAGE_FORMATS[self.KINDS[self._kind.current()]][1]
        self._example.setText(f"{self._source.path.stem}.{number}{suffix}, …")

    def _on_time_typed(self) -> None:
        self._preview_timer.start()
        self.changed.emit()

    def _load_preview(self) -> None:
        tools, source = self._tools(), self._source
        at = parse_time(self._at.text())
        if tools is None or source is None or at is None or self._take.current() != self.ONE:
            return
        token = self._token

        def done(paths) -> None:
            if token != self._token:
                return
            pixmap = qt.QtGui.QPixmap(str(paths[0])) if paths and paths[0] is not None else qt.QtGui.QPixmap()
            if pixmap.isNull():
                self._preview.setPixmap(qt.QtGui.QPixmap())
                return
            ratio = self.devicePixelRatioF()
            scaled = pixmap.scaled(self.PREVIEW_SIZE * ratio, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                   qt.QtCore.Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            self._preview.setPixmap(scaled)

        cache = Path(tempfile.gettempdir()) / "msl_tools" / "media" / "trim"
        worker = ResultWorker(lambda: frames_at(tools, source.info, [at], cache, f"one_{id(self)}", 256), parent=self)
        self._workers.append(worker)
        worker.done.connect(done)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def job(self, source: MediaSource, output: Path) -> Job:
        take = self._take.current()
        quality = self.JPG_QUALITIES[self._jpg.current()]
        if take == self.ONE:
            at = parse_time(self._at.text())
            if at is None:
                raise MediaError("Type the moment as seconds or minutes:seconds, for example 0:12.5.")
            if at > source.info.duration:
                raise MediaError(f"The video is only {format_time(source.info.duration)} long.")
            return frame(source.info, output, at, jpg_quality=quality)
        try:
            first = int(self._first.text())
        except ValueError as error:
            raise MediaError("Type the number of the first picture, for example 1.") from error
        return to_frames(source.info, output, name=source.path.stem, image_format=self.KINDS[self._kind.current()],
                         jpg_quality=quality, first_number=first, padding=int(self._digits.currentText()),
                         every=int(self._step.currentText()) if take == self.SOME else 1)

    def settings(self) -> dict:
        return {"take": self._take.current(), "step": self._step.currentText(), "kind": self._kind.current(),
                "jpg": self._jpg.current(), "first": self._first.text(), "digits": self._digits.currentText()}

    def apply_settings(self, settings: dict) -> None:
        self._take.set_current(str(settings.get("take", "")), animate=False)
        self._kind.set_current(str(settings.get("kind", "")), animate=False)
        self._jpg.set_current(str(settings.get("jpg", "")), animate=False)
        if str(settings.get("step", "")) in self.STEPS:
            self._step.setCurrentText(str(settings["step"]))
        if str(settings.get("digits", "")) in self.DIGITS:
            self._digits.setCurrentText(str(settings["digits"]))
        if str(settings.get("first", "")).strip().isdigit():
            self._first.setText(str(settings["first"]))
        self._sync()


class JoinPanel(OptionPanel):
    """Several videos -> one, in the order they were dropped."""

    KEY, TITLE, BUTTON, TAG, COMBINES = "join", "Join", "Join the videos", "_joined", True
    TIP = "Put the videos one after another into one"

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._order = qt.QtWidgets.QLabel()
        self._order.setObjectName("mediaHint")
        self._order.setWordWrap(True)
        self._quality = self._switch(QUALITY_HIGH, "High")
        self._add_row("Order", self._order)
        self._add_row("Quality", self._quality)

    @staticmethod
    def accepts(sources: list) -> bool:
        return _videos(sources) and len(sources) >= 2

    def set_sources(self, sources: list) -> None:
        names = "  →  ".join(source.path.name for source in sources)
        note = "" if all(source.info.has_audio for source in sources) else \
            NL + "Not every video has sound: the result will have none."
        sizes = {(source.info.width, source.info.height) for source in sources}
        if len(sizes) > 1:
            first = sources[0].info
            note += NL + f"Their frame sizes differ: all are fitted into the first one’s {first.resolution_text()}."
        self._order.setText(names + note)

    def combined_job(self, sources: list, output: Path) -> Job:
        return join([source.info for source in sources], output, quality=QUALITY_HIGH[self._quality.current()])

    def settings(self) -> dict:
        return {"quality": self._quality.current()}

    def apply_settings(self, settings: dict) -> None:
        self._quality.set_current(str(settings.get("quality", "")), animate=False)


class ComparePanel(OptionPanel):
    """Two videos -> one picture with both, to compare them frame for frame."""

    KEY, TITLE, BUTTON, TAG, COMBINES = "compare", "Compare", "Create the comparison", "_compare", True
    TIP = "Two videos in one picture — before / after"
    SIDE, STACKED = "Side by side", "One above the other"

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._layout_switch = self._switch([self.SIDE, self.STACKED], self.SIDE)
        self._labels = self._check("Write each file’s name over its half", True)
        self._which = qt.QtWidgets.QLabel()
        self._which.setObjectName("mediaHint")
        self._which.setWordWrap(True)
        self._add_row("Layout", self._layout_switch)
        self._add_row("Names", self._labels)
        self._add_row("", self._which)

    @staticmethod
    def accepts(sources: list) -> bool:
        return _videos(sources) and len(sources) == 2

    def set_sources(self, sources: list) -> None:
        first, second = sources[0], sources[1]
        self._which.setText(f"{first.path.name}  |  {second.path.name} — as long as the shorter one; "
                            f"the sound is the first one’s.")

    def combined_job(self, sources: list, output: Path) -> Job:
        return compare(sources[0].info, sources[1].info, output, stacked=self._layout_switch.current() == self.STACKED,
                       labels=self._labels.isChecked())

    def settings(self) -> dict:
        return {"layout": self._layout_switch.current(), "labels": self._labels.isChecked()}

    def apply_settings(self, settings: dict) -> None:
        self._layout_switch.set_current(str(settings.get("layout", "")), animate=False)
        self._labels.set_checked_immediate(bool(settings.get("labels", True)))


PANELS = (SequencePanel, ShrinkPanel, TrimPanel, StampPanel, SoundPanel, GifPanel, FramesPanel, EditingPanel,
          AdjustPanel, JoinPanel, ComparePanel)
