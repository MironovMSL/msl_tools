# tools/desktop/media/option_panels.py
"""The settings of the Media tool's three actions. Each panel shows the
choices in plain words, remembers them (settings() / apply_settings()), and
turns them into a Job with job(source, output) — the ffmpeg arguments are
the recipes' business (core/media/recipes.py), never the panel's."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, MediaError, default_output, sequence_to_video, shrink, trim
from msl_tools.msl.core.media.recipes import GAPS_ERROR, GAPS_HOLD
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES, MediaSource, format_time, parse_time
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl


class OptionPanel(qt.QtWidgets.QFrame):
    """Base of an action's settings: a two-column form (dimmed caption, control).

    Subclasses add rows with _add_row(), and implement:
        KEY / TITLE / BUTTON — its id, its name on the action switch, the text of the start button
        set_source(source)   — a new source was loaded
        job(source, output)  — the Job for the current choices (may raise MediaError)
        output_for(source, taken) — the default name of the result
        settings() / apply_settings(dict) — what is remembered between sessions

    Signals:
        changed() — a choice changed (the page refreshes what depends on it).
    """

    KEY = TITLE = BUTTON = ""
    CAPTION_WIDTH = 84

    changed = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaOptions")
        self._form = qt.QtWidgets.QGridLayout(self)
        self._form.setContentsMargins(12, 10, 12, 10)
        self._form.setHorizontalSpacing(10)
        self._form.setVerticalSpacing(8)
        self._form.setColumnMinimumWidth(0, self.CAPTION_WIDTH)
        self._form.setColumnStretch(1, 1)
        self._rows: list[tuple] = []

    def _add_row(self, caption: str, *widgets, hint: str = "") -> int:
        """Adds a row: the caption, then the widgets left to right (the rest
        of the row stays empty). Returns the row's index for _set_row_visible()."""
        row = self._form.rowCount()
        label = qt.QtWidgets.QLabel(caption)
        label.setObjectName("mediaCaption")
        holder = qt.QtWidgets.QWidget()
        line = qt.QtWidgets.QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        for widget in widgets:
            line.addWidget(widget, 1 if isinstance(widget, qt.QtWidgets.QLineEdit) and widget.maximumWidth() > 1000 else 0)
        if hint:
            note = qt.QtWidgets.QLabel(hint)
            note.setObjectName("mediaHint")
            note.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
            line.addWidget(note, 1)
        else:
            line.addStretch(0 if any(isinstance(w, qt.QtWidgets.QLineEdit) and w.maximumWidth() > 1000 for w in widgets) else 1)
        self._form.addWidget(label, row, 0)
        self._form.addWidget(holder, row, 1)
        self._rows.append((label, holder))
        return len(self._rows) - 1

    def _set_row_visible(self, index: int, visible: bool) -> None:
        for widget in self._rows[index]:
            widget.setVisible(visible)

    def _switch(self, options: dict, current: str, tooltip: str = "") -> SegmentedControl:
        """A SegmentedControl over the labels of `options` ({label: value})."""
        control = SegmentedControl(list(options), current)
        control.setToolTip(tooltip)
        control.current_changed.connect(lambda _option: self.changed.emit())
        return control

    # --- for subclasses ---------------------------------------------------------------

    def set_source(self, source: MediaSource) -> None:
        pass

    def job(self, source: MediaSource, output: Path) -> Job:
        raise NotImplementedError

    def output_for(self, source: MediaSource, taken=()) -> Path:
        raise NotImplementedError

    def settings(self) -> dict:
        return {}

    def apply_settings(self, settings: dict) -> None:
        pass


QUALITY_HIGH = {"Best": "best", "High": "high", "Good": "good", "Small": "small"}
SPEEDS = {"Fast": "fast", "Balanced": "balanced", "Compact": "compact"}
SPEED_TIP = ("Fast: done soonest, a bigger file." + chr(10) + "Balanced: the usual choice." + chr(10)
             + "Compact: takes longer, the smallest file at the same quality.")


class SequencePanel(OptionPanel):
    """Image sequence -> video: frame rate, quality, speed, optional sound,
    and what to do about missing frames."""

    KEY, TITLE, BUTTON = "sequence", "To video", "Create video"
    FRAME_RATES = ("12", "15", "23.976", "24", "25", "29.97", "30", "48", "50", "60")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fps = BaseComboBox(list(self.FRAME_RATES), "24")
        self._fps.setFixedWidth(84)
        self._fps.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self._quality = self._switch(QUALITY_HIGH, "Good", "How good the picture looks — better is also bigger")
        self._speed = self._switch(SPEEDS, "Balanced", SPEED_TIP)
        self._sound = qt.QtWidgets.QLineEdit()
        self._sound.setPlaceholderText("none — choose a sound file, or drop one here")
        self._sound.setClearButtonEnabled(True)
        self._sound.textChanged.connect(lambda _text: self.changed.emit())
        self._sound_button = IconPushButton(UiResources().iconManager.get_icon("browse", sub_folder="actions"),
                                            "Choose a sound file", fallback_text="…")
        self._sound_button.setFixedSize(26, 22)
        self._sound_button.clicked.connect(self._on_browse_sound)
        self._hold = BaseCheckbox("Show the frame before a gap until the next one")
        self._hold.toggled.connect(lambda _checked: self.changed.emit())

        self._add_row("Frame rate", self._fps, hint="frames per second")
        self._add_row("Quality", self._quality)
        self._add_row("Encoding", self._speed)
        self._add_row("Sound", self._sound, self._sound_button)
        self._gap_row = self._add_row("Gaps", self._hold)
        self._set_row_visible(self._gap_row, False)

    def set_source(self, source: MediaSource) -> None:
        self._sound.clear()  # the sound belonged to the previous sequence
        missing = bool(source.sequence is not None and source.sequence.missing)
        self._set_row_visible(self._gap_row, missing)
        if missing:
            count = len(source.sequence.missing)
            self._hold.setToolTip(f"{count} frame(s) have no file. Ticked: the video keeps its length, the frame "
                                  f"before each gap stays on screen. Not ticked: the video isn’t made.")

    def set_sound(self, path: str) -> None:
        self._sound.setText(path)

    def job(self, source: MediaSource, output: Path) -> Job:
        sound = self._sound.text().strip()
        if sound and not Path(sound).is_file():
            raise MediaError(f"The sound file isn’t there: {sound}")
        try:
            fps = float(self._fps.currentText())
        except ValueError as error:
            raise MediaError("The frame rate must be a number.") from error
        return sequence_to_video(source.sequence, output, fps=fps, quality=QUALITY_HIGH[self._quality.current()],
                                 speed=SPEEDS[self._speed.current()], audio=sound or None,
                                 gaps=GAPS_HOLD if self._hold.isChecked() else GAPS_ERROR)

    def output_for(self, source: MediaSource, taken=()) -> Path:
        return default_output(source.sequence, taken=taken)

    def settings(self) -> dict:
        return {"fps": self._fps.currentText(), "quality": self._quality.current(), "speed": self._speed.current()}

    def apply_settings(self, settings: dict) -> None:
        if str(settings.get("fps", "")) in self.FRAME_RATES:
            self._fps.setCurrentText(str(settings["fps"]))
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        self._speed.set_current(str(settings.get("speed", "")), animate=False)

    def _on_browse_sound(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in AUDIO_SUFFIXES)
        path, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(self, "The sound to put under the video", "",
                                                                 f"Sound ({patterns});;All files (*.*)")
        if path:
            self._sound.setText(path)


class ShrinkPanel(OptionPanel):
    """Video -> a smaller copy for sending: frame size, then either a quality
    or a file size to fit into."""

    KEY, TITLE, BUTTON = "shrink", "Make smaller", "Make smaller"
    HEIGHTS = {"Keep": 0, "1080p": 1080, "720p": 720, "480p": 480}
    BY_QUALITY, BY_SIZE = "By quality", "Fit into a size"
    QUALITIES = {"Good": "good", "Small": "small", "Smallest": "smallest"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._height = self._switch(self.HEIGHTS, "720p", "The height of the picture. A video that is already "
                                                          "smaller is never enlarged.")
        self._mode = self._switch({self.BY_QUALITY: 0, self.BY_SIZE: 1}, self.BY_QUALITY,
                                  "By quality: pick how it should look, the size is what it comes to." + chr(10)
                                  + "Fit into a size: pick the megabytes, the quality is what fits.")
        self._quality = self._switch(self.QUALITIES, "Small")
        self._megabytes = qt.QtWidgets.QLineEdit("10")
        self._megabytes.setFixedWidth(64)
        self._megabytes.setValidator(qt.QtGui.QDoubleValidator(0.1, 100000.0, 1, self))
        self._megabytes.textChanged.connect(lambda _text: self.changed.emit())
        self._megabytes_note = qt.QtWidgets.QLabel("MB")
        self._megabytes_note.setObjectName("mediaHint")
        self._sound = BaseCheckbox("Keep the sound")
        self._sound.setChecked(True)
        self._sound.toggled.connect(lambda _checked: self.changed.emit())

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

    def set_source(self, source: MediaSource) -> None:
        self._set_row_visible(self._sound_row, source.info.has_audio)

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

    def output_for(self, source: MediaSource, taken=()) -> Path:
        return default_output(source.path, "_small", taken=taken)

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
    """Video -> one piece of it: from, to, and whether the cut must be exact."""

    KEY, TITLE, BUTTON = "trim", "Trim", "Cut this piece"
    EXACT, FAST = "Exact", "Fast"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0.0
        self._start = qt.QtWidgets.QLineEdit("0:00")
        self._end = qt.QtWidgets.QLineEdit()
        for field in (self._start, self._end):
            field.setFixedWidth(84)
            field.setToolTip("Seconds, or minutes:seconds — 12.5, 0:12.5, 1:02:03")
            field.textChanged.connect(self._on_times_changed)
        self._length_label = qt.QtWidgets.QLabel()
        self._length_label.setObjectName("mediaHint")
        self._mode = self._switch({self.EXACT: True, self.FAST: False}, self.EXACT,
                                  "Exact: the cut is where you asked, to the frame (the piece is re-encoded)."
                                  + chr(10) + "Fast: instant and lossless, but the cut can start a moment early "
                                              "and run a moment long.")
        self._add_row("From", self._start)
        self._add_row("To", self._end, self._length_label)
        self._add_row("Cut", self._mode)

    def set_source(self, source: MediaSource) -> None:
        self._duration = source.info.duration
        self._start.setText("0:00")
        self._end.setText(format_time(self._duration))

    def _times(self) -> tuple:
        return parse_time(self._start.text()), parse_time(self._end.text())

    def _on_times_changed(self) -> None:
        start, end = self._times()
        if start is None or end is None:
            text = "type a time like 0:12.5"
        elif end <= start:
            text = "the end must be after the start"
        else:
            text = f"a piece of {format_time(min(end, self._duration or end) - start)}"
        self._length_label.setText(text)
        self.changed.emit()

    def job(self, source: MediaSource, output: Path) -> Job:
        start, end = self._times()
        if start is None or end is None:
            raise MediaError("Type the times as seconds or minutes:seconds, for example 0:12.5.")
        if start >= (source.info.duration or start + 1):
            raise MediaError(f"The video is only {format_time(source.info.duration)} long.")
        return trim(source.info, output, start, end, exact=self._mode.current() == self.EXACT)

    def output_for(self, source: MediaSource, taken=()) -> Path:
        return default_output(source.path, "_cut", suffix=".mp4" if self._mode.current() == self.EXACT
                              else source.path.suffix, taken=taken)

    def settings(self) -> dict:
        return {"mode": self._mode.current()}

    def apply_settings(self, settings: dict) -> None:
        self._mode.set_current(str(settings.get("mode", "")), animate=False)
