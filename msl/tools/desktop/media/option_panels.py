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
from msl_tools.msl.core.media import (Job, MediaError, Overlays, adjust, adjust_audio, chain, compare, contact_sheet,
                                      convert, convert_sequence, default_output, extract_audio, fit, frame, gif,
                                      gpu_encoding_works, join, loop, remove_audio, replace_audio, sequence_to_video,
                                      shrink, stamp, to_frames, trim, trim_pieces)
from msl_tools.msl.core.media.recipes import FORMATS, GAPS_ERROR, GAPS_HOLD, IMAGE_FORMATS, SOUND_FORMATS
from msl_tools.msl.core.media.run import clean_up, quality_crops
from msl_tools.msl.core.media.thumbnail import frames_at
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES, MediaSource, format_time, parse_time
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.crop_picker import CropPicker
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.compositions.range_strip import RangeStrip
from msl_tools.msl.ui.workers.result_worker import ResultWorker

NL = chr(10)


class SectionHeader(qt.QtWidgets.QWidget):
    """A small heading across an action's form — "PICTURE", "SOUND" — ruled
    off by a hairline, so a long form reads as a few short ones. A FOLDABLE
    one hides what is under it on a click (the panel does the hiding) and,
    while folded, says in a few words what is set there.

    Signals:
        toggled(bool) — a foldable header was clicked; True = open now.
    """

    toggled = qt.QtCore.Signal(bool)

    def __init__(self, title: str, foldable: bool = False, parent=None):
        super().__init__(parent)
        self._foldable = foldable
        self._open = True
        icons = UiResources().iconManager
        self._icons = {True: icons.get_icon("chevron_down", sub_folder="actions"),
                       False: icons.get_icon("chevron_right", sub_folder="actions")}
        self._chevron = TintedIcon(self._icons[True], 10)
        self._title = qt.QtWidgets.QLabel(title.upper())
        self._title.setObjectName("mediaSection")
        self._summary = qt.QtWidgets.QLabel()
        self._summary.setObjectName("mediaHint")
        rule = qt.QtWidgets.QFrame()
        rule.setObjectName("mediaDivider")
        rule.setFixedHeight(1)
        line = qt.QtWidgets.QHBoxLayout(self)
        line.setContentsMargins(0, 6, 0, 0)
        line.setSpacing(6)
        line.addWidget(self._chevron)
        line.addWidget(self._title)
        line.addWidget(self._summary)
        line.addWidget(rule, 1)
        if not foldable:
            self._chevron.hide()
        else:
            self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Click to show or hide these settings")
        self._summary.hide()

    def is_open(self) -> bool:
        return self._open

    def set_open(self, is_open: bool) -> None:
        """Opens / folds without emitting toggled."""
        self._open = bool(is_open)
        self._chevron.set_icon(self._icons[self._open])
        self._summary.setVisible(not self._open and bool(self._summary.text()))

    def set_summary(self, text: str) -> None:
        """What is set under this header — shown only while it is folded."""
        self._summary.setText(text)
        self._summary.setVisible(not self._open and bool(text))

    def mouseReleaseEvent(self, event) -> None:
        if self._foldable and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.set_open(not self._open)
            self.toggled.emit(self._open)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class OptionPanel(qt.QtWidgets.QFrame):
    """Base of an action's settings: a two-column form (dimmed caption, control).
    The page puts it into the action's card, under the card's header.

    A subclass sets:
        KEY / TITLE / BUTTON — its id, its name in the action picker, the start button's text
        TIP — one line saying what the action does (the picker's tooltip, the card's header)
        ICON — its icon in the picker and the header (assets/icons/actions/<ICON>.svg)
        GROUP — what kind of action it is ("change" the video, "convert" it into
                something else, "combine" several): the picker rules the groups off
        COMBINES — True: ONE job is made from all the sources (join, compare);
                   False: one job per source
        PRESETS — built-in presets {name: settings}
        PREVIEW — the action can show a few seconds of its result before the
                  start; PREVIEW_TIP — what its "Preview" button says it plays;
                  PREVIEW_SECONDS — how much; PREVIEW_FROM_START — the START of
                  the result, not a piece from its middle (where the beginning
                  is the point)
        COMPARES_SIZE — the finished job says how much smaller than its
                  source the result is (pointless where it is a piece of it)
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

    KEY = TITLE = BUTTON = TIP = ICON = GROUP = ""
    COMBINES = False
    PRESETS: dict = {}
    PREVIEW = True
    PREVIEW_TIP = "Make three seconds from the middle with these settings and play them"
    PREVIEW_SECONDS = 3.0
    PREVIEW_FROM_START = False
    COMPARES_SIZE = True
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
            grows = (isinstance(widget, (qt.QtWidgets.QLineEdit, RangeStrip, ChipBar, CropPicker))
                     and widget.maximumWidth() > 1000)                 or (isinstance(widget, qt.QtWidgets.QLabel) and widget.wordWrap())
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

    def _add_section(self, title: str, foldable: bool = False) -> SectionHeader:
        """Adds a heading across the form; the rows added after it belong to it."""
        header = SectionHeader(title, foldable)
        self._form.addWidget(header, self._form.rowCount(), 0, 1, 2)
        return header

    @staticmethod
    def _note(text: str) -> qt.QtWidgets.QLabel:
        """A small dimmed word beside a control, saying what it is."""
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("mediaHint")
        return label

    def set_sound_target(self, lit: bool) -> None:
        """A sound file is being dragged over the page and would land in this
        panel's sound field: the field shows that it is the target."""

    @staticmethod
    def _light_field(field: qt.QtWidgets.QLineEdit, lit: bool) -> None:
        if bool(field.property("dropTarget")) != lit:
            field.setProperty("dropTarget", lit)  # media.qss: QLineEdit[dropTarget="true"]
            repolish(field)

    def source_facts(self, sources: list) -> list:
        """(value, what it is) pairs this action adds to the source's tiles —
        something about the source that depends on the settings here."""
        return []

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

    def jobs(self, source: MediaSource, output: Path) -> list:
        """The jobs for ONE source — one, unless the action makes several
        results of it (Trim's separate pieces: each gets a name of its own
        derived from `output`)."""
        return [self.job(source, output)]

    def combined_job(self, sources: list, output: Path) -> Job:
        raise NotImplementedError

    def bind(self, panels: dict) -> None:
        """Called once by the page with every panel by KEY — for an action
        that uses the settings of others ("Several at once")."""

    def refresh(self) -> None:
        """Called when this action is picked: bring anything that depends on other panels up to date."""

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


def _remove_files(paths) -> None:
    """Deletes the temporary pictures of a preview (None entries skipped)."""
    for path in paths or []:
        if path is not None:
            try:
                Path(path).unlink()
            except OSError:
                pass


def _videos(sources: list) -> bool:
    return bool(sources) and not any(source.is_sequence for source in sources)


QUALITY_HIGH = {"Best": "best", "High": "high", "Good": "good", "Small": "small"}
SPEEDS = {"Fast": "fast", "Balanced": "balanced", "Compact": "compact"}
SPEED_TIP = ("Fast: done soonest, a bigger file." + NL + "Balanced: the usual choice." + NL
             + "Compact: takes longer, the smallest file at the same quality.")
VIDEO_FORMATS = {"MP4": "mp4", "ProRes": "prores", "HQ": "prores_hq", "DNxHR": "dnxhr_hq"}
FORMAT_TIP = ("MP4: small, plays everywhere — for watching and sending." + NL
              + "ProRes / HQ (ProRes HQ) / DNxHR: big files that keep far more of the picture — for editing "
                "and grading.")
RENAMED = {"ProRes HQ": "HQ"}  # labels of earlier versions, as saved settings and presets still spell them
# The "msl" mark as a picture ffmpeg can lay over a video (rendered from watermark.svg beside it).
BRAND_WATERMARK = Resources().fsManager.icons / "brand" / "watermark.png"
IMAGE_PATTERNS = "Pictures (*.png *.jpg *.jpeg *.tif *.tiff *.tga *.bmp *.webp)"
SOUND_PATTERNS = "Sound (" + " ".join(f"*{suffix}" for suffix in AUDIO_SUFFIXES) + ")"


class _OverlayRows:
    """Mixin for a panel that can draw on the picture: the rows "Show"
    (frame number, time, date — pills switched on and off), "Label" and
    "Watermark" (image, size, opacity), and their settings. Call
    _add_overlay_rows() where they go."""

    MARK_SIZES = ("10%", "15%", "25%", "40%")
    MARK_OPACITIES = ("100%", "70%", "40%")
    BURNS = {"frame": ("Frame number", "The number of each frame, bottom right"),
             "time": ("Time", "The time since the start, bottom centre"),
             "date": ("Date", "Today’s date, top right")}

    def _add_overlay_rows(self) -> list[int]:
        self._burn = ChipBar(multiple=True)
        self._burn.set_chips([(key, title, tip) for key, (title, tip) in self.BURNS.items()])
        self._burn.clicked.connect(lambda _key: self.changed.emit())
        self._label = qt.QtWidgets.QLineEdit()
        self._label.setPlaceholderText("text for the top-left corner — a shot name, a version")
        self._label.textChanged.connect(lambda _text: self.changed.emit())
        self._mark, self._mark_button = self._file_field("none — a picture for the bottom-right corner",
                                                         "A picture to use as a watermark", IMAGE_PATTERNS)
        # One click instead of browsing: our own mark, shipped with the tool.
        self._mark_brand = IconPushButton(UiResources().iconManager.get_icon("brand_mark", sub_folder="actions"),
                                          "Use the msl mark as the watermark", fallback_text="M")
        self._mark_brand.setFixedSize(26, 22)
        self._mark_brand.clicked.connect(lambda: self._mark.setText(str(BRAND_WATERMARK)))
        if not BRAND_WATERMARK.is_file():
            self._mark_brand.hide()
        self._mark_size = BaseComboBox(list(self.MARK_SIZES), "15%")
        self._mark_size.setFixedWidth(64)
        self._mark_size.setToolTip("The watermark’s width, as a part of the frame’s width")
        self._mark_opacity = BaseComboBox(list(self.MARK_OPACITIES), "70%")
        self._mark_opacity.setFixedWidth(68)
        self._mark_opacity.setToolTip("How solid the watermark is")
        for combo in (self._mark_size, self._mark_opacity):
            combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        return [self._add_row("Show", self._burn),
                self._add_row("Label", self._label),
                self._add_row("Watermark", self._mark, self._mark_button, self._mark_brand),
                # on a line of their own: in one row with the field they made the window 604 px wide at least
                self._add_row("", self._mark_size, self._note("of the frame's width"), self._mark_opacity,
                              self._note("solid"))]

    def _overlay_summary(self) -> str:
        """What is drawn, in a few words ("frame number · date · a label"), or "nothing"."""
        shown = self._burn.checked()
        parts = [self.BURNS[key][0].lower() for key in self.BURNS if key in shown]
        parts += ["a label"] if self._label.text().strip() else []
        parts += ["a watermark"] if self._mark.text().strip() else []
        return "  ·  ".join(parts) or "nothing"

    def _overlays(self) -> Overlays:
        shown = self._burn.checked()
        return Overlays(frame_number="frame" in shown, time="time" in shown,
                        date="date" in shown, label=self._label.text().strip(),
                        watermark=self._mark.text().strip(),
                        watermark_size=int(self._mark_size.currentText().rstrip("%")),
                        watermark_opacity=int(self._mark_opacity.currentText().rstrip("%")))

    def _overlay_settings(self) -> dict:
        shown = self._burn.checked()
        return {"burn_frame": "frame" in shown, "burn_time": "time" in shown,
                "burn_date": "date" in shown, "label": self._label.text(),
                "watermark": self._mark.text(), "watermark_size": self._mark_size.currentText(),
                "watermark_opacity": self._mark_opacity.currentText()}

    def _apply_overlay_settings(self, settings: dict) -> None:
        self._burn.set_checked([key for key in self.BURNS if settings.get(f"burn_{key}", False)])
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
    ICON, GROUP = "film", "make"
    TIP = "Turn the frames into a video"
    FRAME_RATES = ("12", "15", "23.976", "24", "25", "29.97", "30", "48", "50", "60")
    PRESETS = {
        "Preview · fast": {"quality": "Good", "speed": "Fast", "format": "MP4"},
        "Review · frame numbers": {"quality": "Good", "speed": "Balanced", "format": "MP4",
                                   "burn_frame": True, "burn_date": True, "draw_open": True},
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
        self._sound, self._sound_button = self._file_field("none — drop a sound file here, or choose one",
                                                           "The sound to put under the video", SOUND_PATTERNS)
        sound_icon = TintedIcon(UiResources().iconManager.get_icon("volume", sub_folder="actions"), 16)
        sound_icon.setToolTip("A sound file dropped anywhere on the page goes here")
        self._hold = self._check("Show the frame before a gap until the next one")

        # Three short forms instead of one long one.
        self._add_section("Picture")
        self._add_row("Frame rate", self._fps, hint="frames per second")
        self._add_row("Format", self._format)
        self._quality_row = self._add_row("Quality", self._quality)
        self._speed_row = self._add_row("Encoding", self._speed)
        self._gap_row = self._add_row("Gaps", self._hold)
        self._set_row_visible(self._gap_row, False)
        self._add_section("Sound")
        self._add_row("Sound", sound_icon, self._sound, self._sound_button)
        # Folded until wanted; folded, its header says what is drawn. Folding hides the
        # settings - it doesn't switch them off.
        self._draw = self._add_section("Draw on the picture", foldable=True)
        self._draw.set_open(False)
        self._overlay_rows = self._add_overlay_rows()
        self._format.current_changed.connect(lambda _option: self._sync())
        self._draw.toggled.connect(self._on_draw_toggled)
        self.changed.connect(lambda: self._draw.set_summary(self._overlay_summary()))
        self._sync()

    def _on_draw_toggled(self, _is_open: bool) -> None:
        self._sync()
        self.changed.emit()  # the fold is remembered

    def _sync(self) -> None:
        mp4 = self._format.current() == "MP4"
        self._set_row_visible(self._quality_row, mp4)   # the editing formats have no quality / speed choice
        self._set_row_visible(self._speed_row, mp4)
        for row in self._overlay_rows:
            self._set_row_visible(row, self._draw.is_open())
        self._draw.set_summary(self._overlay_summary())

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

    def set_sound_target(self, lit: bool) -> None:
        self._light_field(self._sound, lit)

    def source_facts(self, sources: list) -> list:
        """How long the video will be at the picked frame rate."""
        try:
            fps = float(self._fps.currentText())
        except ValueError:
            return []
        frames = sum(source.sequence.last - source.sequence.first + 1 for source in sources)
        return [(format_time(round(frames / fps, 1)), f"at {self._fps.currentText()} fps")] if fps else []

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
        overlays = self._overlays()
        return sequence_to_video(source.sequence, output, fps=fps, quality=QUALITY_HIGH[self._quality.current()],
                                 speed=SPEEDS[self._speed.current()], audio=sound or None,
                                 gaps=GAPS_HOLD if self._hold.isChecked() else GAPS_ERROR,
                                 overlays=overlays if overlays.any() else None,
                                 frame_size=(source.info.width, source.info.height),
                                 video_format=VIDEO_FORMATS[self._format.current()])

    def settings(self) -> dict:
        # "overlays_open" is what versions up to 0.1.6 read: there it SWITCHED the burn-ins on.
        return {"fps": self._fps.currentText(), "quality": self._quality.current(), "speed": self._speed.current(),
                "format": self._format.current(), "draw_open": self._draw.is_open(),
                "overlays_open": self._overlays().any(), **self._overlay_settings()}

    def apply_settings(self, settings: dict) -> None:
        if str(settings.get("fps", "")) in self.FRAME_RATES:
            self._fps.setCurrentText(str(settings["fps"]))
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        self._speed.set_current(str(settings.get("speed", "")), animate=False)
        chosen = str(settings.get("format", ""))
        self._format.set_current(RENAMED.get(chosen, chosen), animate=False)
        # Settings saved by 0.1.6 or older: "overlays_open" off meant "draw nothing", whatever
        # was ticked under it - so nothing is taken over from there.
        switched_off = "draw_open" not in settings and not settings.get("overlays_open", False)
        self._apply_overlay_settings({} if switched_off else settings)
        self._draw.set_open(bool(settings.get("draw_open", settings.get("overlays_open", False))))
        self._sync()


class ShrinkPanel(OptionPanel):
    """Video -> a smaller copy for sending: frame size, then either a quality
    or a file size to fit into."""

    KEY, TITLE, BUTTON, TAG = "shrink", "Make smaller", "Make smaller", "_small"
    ICON, GROUP = "compress", "change"
    TIP = "A lighter copy for sending"
    HEIGHTS = {"Keep": 0, "1080p": 1080, "720p": 720, "480p": 480}
    BY_QUALITY, BY_SIZE = "By quality", "Fit into a size"
    QUALITIES = {"Good": "good", "Small": "small", "Smallest": "smallest"}
    CODECS = {"H.264": "h264", "H.265": "h265"}
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
        self._codec = self._switch(self.CODECS, "H.264",
                                   "H.264: plays everywhere." + NL + "H.265: about a third smaller at the same "
                                   "quality — but old players and some chats don’t open it.")
        self._gpu = self._check("On the graphics card", False,
                                "Encode on the graphics card: several times faster, a somewhat bigger file "
                                "for the same look")
        self._gpu_works = False
        self._gpu_asked = False
        self._workers: list = []
        # Before / after: the middle of the frame at 1:1, as it is and as it will be.
        self._source: MediaSource | None = None
        self._look_token = 0
        self._before, self._after = self._look_picture("as it is"), self._look_picture("as it will be")
        self._look_timer = qt.QtCore.QTimer(self)
        self._look_timer.setSingleShot(True)
        self._look_timer.setInterval(self.LOOK_DELAY_MS)
        self._look_timer.timeout.connect(self._load_look)
        self.changed.connect(self._schedule_look)

        self._add_row("Frame size", self._height)
        self._add_row("Aim for", self._mode)
        self._quality_row = self._add_row("Quality", self._quality)
        self._size_row = self._add_row("File size", self._megabytes, self._megabytes_note)
        self._codec_row = self._add_row("Codec", self._codec, self._gpu)
        self._sound_row = self._add_row("Sound", self._sound)
        self._look_row = self._add_row("Look", self._before, self._after,
                                       hint="the middle of the frame, pixel for pixel: as it is · as it will be")
        self._mode.current_changed.connect(lambda _option: self._sync())
        self._sync()

    def _sync(self) -> None:
        by_size = self._mode.current() == self.BY_SIZE
        self._set_row_visible(self._quality_row, not by_size)
        self._set_row_visible(self._size_row, by_size)
        self._set_row_visible(self._codec_row, not by_size)  # fitting a size is always H.264 (see core shrink)
        self._gpu.setVisible(self._gpu_works and not by_size)

    accepts = staticmethod(_videos)

    LOOK_SIZE = qt.QtCore.QSize(136, 77)   # two of them side by side: wider ones made the window 626 px at least
    LOOK_DELAY_MS = 900

    def _look_picture(self, tip: str) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel()
        label.setObjectName("mediaThumbnail")
        label.setFixedSize(self.LOOK_SIZE)
        label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setToolTip(tip)
        return label

    def _schedule_look(self) -> None:
        self._look_token += 1  # a picture on its way is for the old settings
        self._look_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_look()

    def _load_look(self) -> None:
        """Encodes a short piece with the settings on screen and shows the same spot before and after."""
        tools, source = self._tools(), self._source
        if tools is None or source is None or not self.isVisible():
            return
        try:
            job = self.job(source, Path(tempfile.gettempdir()) / "msl_tools" / "media" / "look" / "look.mp4")
        except MediaError:
            return
        token = self._look_token
        folder = Path(tempfile.gettempdir()) / "msl_tools" / "media" / "look"
        for label in (self._before, self._after):
            label.setText("…")

        def work():
            try:
                return quality_crops(tools, job, source.info, folder, f"look_{id(self)}",
                                     (self.LOOK_SIZE.width(), self.LOOK_SIZE.height()))
            finally:
                clean_up(job, remove_output=False)

        def done(paths) -> None:
            if token != self._look_token:
                return
            for label, path in zip((self._before, self._after), paths):
                label.setText("")
                label.setPixmap(qt.QtGui.QPixmap(str(path)))

        def failed(_error) -> None:
            if token == self._look_token:
                for label in (self._before, self._after):
                    label.setText("—")

        worker = ResultWorker(work, parent=self)
        self._workers.append(worker)
        worker.done.connect(done)
        worker.failed.connect(failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def set_sources(self, sources: list) -> None:
        self._source = sources[0]
        self._schedule_look()
        self._set_row_visible(self._sound_row, any(source.info.has_audio for source in sources))
        tools = self._tools()
        if tools is not None and not self._gpu_asked:
            self._gpu_asked = True  # asked once, by encoding a few frames - on a worker

            def done(works) -> None:
                self._gpu_works = bool(works)
                self._sync()

            worker = ResultWorker(lambda: gpu_encoding_works(tools), parent=self)
            self._workers.append(worker)
            worker.done.connect(done)
            worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
            worker.start()

    def chain_settings(self) -> dict:
        """What "Several at once" takes from here: the frame size, the quality, the codec."""
        return {"max_height": self.HEIGHTS[self._height.current()], "quality": self.QUALITIES[self._quality.current()],
                "keep_audio": self._sound.isChecked(), "codec": self.CODECS[self._codec.current()],
                "gpu": self._gpu.isChecked() and self._gpu_works}

    def summary(self) -> str:
        height = self._height.current()
        return (f"{'the frame as it is' if height == 'Keep' else height}  ·  {self._quality.current().lower()} quality"
                f"  ·  {self._codec.current()}")

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
                      keep_audio=self._sound.isChecked(), codec=self.CODECS[self._codec.current()],
                      gpu=self._gpu.isChecked() and self._gpu_works)

    def settings(self) -> dict:
        return {"height": self._height.current(), "mode": self._mode.current(), "quality": self._quality.current(),
                "megabytes": self._megabytes.text(), "codec": self._codec.current(), "gpu": self._gpu.isChecked()}

    def apply_settings(self, settings: dict) -> None:
        self._height.set_current(str(settings.get("height", "")), animate=False)
        self._mode.set_current(str(settings.get("mode", "")), animate=False)
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        if str(settings.get("megabytes", "")).strip():
            self._megabytes.setText(str(settings["megabytes"]))
        self._codec.set_current(str(settings.get("codec", "")), animate=False)
        self._gpu.set_checked_immediate(bool(settings.get("gpu", False)))
        self._sync()


class _TimeEdit(qt.QtWidgets.QLineEdit):
    """Private: a time field whose Up / Down keys ask for a step (one frame)."""

    stepped = qt.QtCore.Signal(int)  # +1 / -1

    def keyPressEvent(self, event) -> None:
        if event.key() in (qt.QtCore.Qt.Key.Key_Up, qt.QtCore.Qt.Key.Key_Down):
            self.stepped.emit(1 if event.key() == qt.QtCore.Qt.Key.Key_Up else -1)
            event.accept()
            return
        super().keyPressEvent(event)


class TrimPanel(OptionPanel):
    """Video -> one piece of it. The piece is picked by eye on a strip of
    the video's frames (two handles) or typed as times; the frames at both
    ends are shown, so one sees where the cut falls.

    The cut is set TO THE FRAME: the ‹ › buttons beside each time (and
    Up / Down in the field, Left / Right on the strip) move that end by one
    frame, Shift by ten; times snap to the video's frames, and the line
    under them counts the frames of the piece. The page's "Preview" plays
    the piece as it will be cut."""

    KEY, TITLE, BUTTON, TAG = "trim", "Trim", "Cut this piece", "_cut"
    ICON, GROUP = "scissors", "change"
    TIP = "Keep one piece of the video"
    PREVIEW_TEXT = "Play the piece"
    PREVIEW_TIP = "Play the piece as it will be cut (its first minute)"
    ONE, SEPARATE = "One video", "Separate files"
    PREVIEW_SECONDS = 60.0
    PREVIEW_FROM_START = True
    COMPARES_SIZE = False
    EXACT, FAST = "Exact", "Fast"
    STRIP_FRAMES = 12
    PREVIEW_SIZE = qt.QtCore.QSize(128, 72)
    PREVIEW_DELAY_MS = 350

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._source: MediaSource | None = None
        self._duration = 0.0
        self._fps = 24.0
        self._syncing = False
        self._workers: list = []
        self._token = 0
        self._ends_token = 0  # the end pictures' own (see _load_previews)
        self._strip = RangeStrip()
        self._strip.setToolTip("Drag the handles to pick the piece; drag between them to move it." + NL
                               + "Left / Right move the handle you touched last by one frame (Shift: ten).")
        self._start = _TimeEdit("0:00")
        self._end = _TimeEdit()
        for field in (self._start, self._end):
            field.setFixedWidth(84)
            field.setToolTip("Seconds, or minutes:seconds — 12.5, 0:12.5, 1:02:03" + NL
                             + "Up / Down: one frame (Shift: ten)")
            field.textChanged.connect(self._on_times_typed)
        self._start.stepped.connect(lambda frames: self._step(self._start, frames))
        self._end.stepped.connect(lambda frames: self._step(self._end, frames))
        self._length_label = qt.QtWidgets.QLabel()
        self._length_label.setObjectName("mediaHint")
        self._length_label.setWordWrap(True)  # so the row gives it the room that is left
        self._first_preview, self._last_preview = self._preview(), self._preview()
        self._mode = self._switch([self.EXACT, self.FAST], self.EXACT,
                                  "Exact: the cut is where you asked, to the frame (the piece is re-encoded)."
                                  + NL + "Fast: instant and lossless, but the cut can start a moment early "
                                         "and run a moment long.")
        self._preview_timer = qt.QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(self.PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._load_previews)

        # Several pieces of one video: each is added from what is picked above.
        self._pieces: list[tuple] = []
        self._add_piece = link_button("+ Add this piece", "Keep the piece picked above and pick another — "
                                                         "all of them are cut out in one go")
        self._piece_chips = ChipBar()
        self._piece_chips.clicked.connect(self._on_piece_clicked)
        self._together = self._switch([self.ONE, self.SEPARATE], self.ONE,
                                      "One video: the pieces one after another in one file." + NL
                                      + "Separate files: a file for each piece.")
        self._add_piece.clicked.connect(self._on_add_piece)
        to_caption = qt.QtWidgets.QLabel("to")
        to_caption.setObjectName("mediaCaption")
        self._strip_row = self._add_row("Piece", self._strip)
        self._add_row("From", self._stepper(self._start), to_caption, self._stepper(self._end))
        self._add_row("", self._length_label)
        self._add_row("Frames", self._first_preview, self._last_preview, hint="the first and the last frame of the piece")
        self._add_row("Cut", self._mode)
        self._add_row("More pieces", self._add_piece, self._piece_chips)
        self._together_row = self._add_row("Make", self._together)
        self._set_row_visible(self._together_row, False)
        self._strip.range_changed.connect(self._on_strip_moved)

    def _preview(self) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel()
        label.setObjectName("mediaThumbnail")
        label.setFixedSize(self.PREVIEW_SIZE)
        label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        return label

    def _stepper(self, field: qt.QtWidgets.QLineEdit) -> qt.QtWidgets.QWidget:
        """`field` between a "one frame back" and a "one frame on" button."""
        holder = qt.QtWidgets.QWidget()
        line = qt.QtWidgets.QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        back = link_button("‹", "One frame back (Shift: ten)")
        forward = link_button("›", "One frame on (Shift: ten)")
        back.clicked.connect(lambda: self._step(field, -1))
        forward.clicked.connect(lambda: self._step(field, 1))
        for widget in (back, field, forward):
            line.addWidget(widget)
        return holder

    def _step(self, field: qt.QtWidgets.QLineEdit, frames: int) -> None:
        """Moves the start or the end by `frames` frames (ten times that with Shift)."""
        value = parse_time(field.text())
        start, end = self._times()
        if value is None or not self._duration:
            return
        if qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier:
            frames *= 10
        last = int(round(self._duration * self._fps))
        frame = int(round(value * self._fps)) + frames
        if field is self._start:
            frame = min(max(frame, 0), (int(round(end * self._fps)) if end is not None else last) - 1)
        else:
            frame = min(max(frame, (int(round(start * self._fps)) if start is not None else 0) + 1), last)
        field.setText(format_time(round(min(frame / self._fps, self._duration), 3)))

    accepts = staticmethod(_videos)

    def set_sources(self, sources: list) -> None:
        source = sources[0]
        # With several videos the same times are cut out of each; the strip shows the first.
        self._source, self._duration = source, min(other.info.duration for other in sources)
        self._fps = source.info.fps or 24.0
        self._pieces = []  # they belonged to the previous video
        self._show_pieces()
        self._strip.set_step(1.0 / max(self._duration * self._fps, 1.0))
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
        self._start.setText(format_time(self._on_frame(start * self._duration)))
        self._end.setText(format_time(self._on_frame(end * self._duration)))
        self._syncing = False
        self._after_change()

    def _on_frame(self, seconds: float) -> float:
        """`seconds` moved onto the nearest frame of the video."""
        return round(min(round(seconds * self._fps) / self._fps, self._duration), 3)

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
            end = min(end, self._duration or end)
            first = int(round(start * self._fps))
            last = max(int(round(end * self._fps)) - 1, first)
            count = last - first + 1
            text = (f"a piece of {format_time(round(end - start, 2))}  ·  {count} frame{'s' if count != 1 else ''}"
                    f"  ·  frame {first + 1} to {last + 1} of {int(round(self._duration * self._fps))}")
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
        # Each request counts (a handle nudged twice within ffmpeg's start-up sends two): only the
        # newest is shown, and each writes files of its own — never ones another run is writing.
        self._ends_token += 1
        token, source_token = self._ends_token, self._token
        last = max(min(end, source.info.duration) - 0.04, 0.0)  # the last frame that is still in the piece

        def done(paths) -> None:
            if token != self._ends_token or source_token != self._token:
                _remove_files(paths)
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
            _remove_files(paths)  # in memory now

        prefix = f"ends_{id(self)}_{token}"
        self._run(lambda: frames_at(tools, source.info, [start, last], self._cache(), prefix, 256), done)

    # --- the job -------------------------------------------------------------------------------

    # --- several pieces ------------------------------------------------------------------------

    BUTTON = property(lambda self: f"Cut {len(self._pieces)} pieces" if len(self._pieces) > 1 else "Cut this piece")

    def _on_add_piece(self) -> None:
        start, end = self._times()
        if start is None or end is None or end <= start:
            return
        piece = (round(start, 3), round(min(end, self._duration or end), 3))
        if piece not in self._pieces:
            self._pieces.append(piece)
            self._show_pieces()
            self.changed.emit()

    def _on_piece_clicked(self, key: str) -> None:
        """A click on a piece's chip takes it out again."""
        self._pieces = [piece for index, piece in enumerate(self._pieces) if str(index) != key]
        self._show_pieces()
        self.changed.emit()

    def _show_pieces(self) -> None:
        self._piece_chips.set_chips([(str(index), f"{format_time(start)} – {format_time(end)}  ✕",
                                      "Click to take this piece out") for index, (start, end) in enumerate(self._pieces)])
        self._set_row_visible(self._together_row, len(self._pieces) > 1)

    def summary(self) -> str:
        """The piece that is picked, in words (for "Several at once")."""
        start, end = self._times()
        if start is None or end is None or end <= start:
            return "no piece picked"
        return f"{format_time(start)} – {format_time(min(end, self._duration or end))}"

    def piece(self) -> tuple:
        """(start, end) of the piece that is picked; raises MediaError if the times aren't usable."""
        start, end = self._times()
        if start is None or end is None:
            raise MediaError("Type the times as seconds or minutes:seconds, for example 0:12.5.")
        return start, end

    # --- the job -------------------------------------------------------------------------------

    def job(self, source: MediaSource, output: Path) -> Job:
        start, end = self.piece()
        if start >= (source.info.duration or start + 1):
            raise MediaError(f"The video is only {format_time(source.info.duration)} long.")
        return trim(source.info, output, start, end, exact=self._mode.current() == self.EXACT)

    def jobs(self, source: MediaSource, output: Path) -> list:
        """One piece: the one picked. Several (added with "+ Add this piece"):
        all of them as one video, or a file each (`<name>_1`, `<name>_2`, ...)."""
        if not self._pieces:
            return [self.job(source, output)]
        exact = self._mode.current() == self.EXACT
        if len(self._pieces) == 1:
            return [trim(source.info, output, *self._pieces[0], exact=exact)]
        if self._together.current() == self.ONE:
            return [trim_pieces(source.info, output.with_suffix(".mp4"), self._pieces)]
        return [trim(source.info, output.with_name(f"{output.stem}_{index}{output.suffix}"), start, end, exact=exact)
                for index, (start, end) in enumerate(self._pieces, 1)]

    def settings(self) -> dict:
        return {"mode": self._mode.current(), "together": self._together.current()}

    def apply_settings(self, settings: dict) -> None:
        self._mode.set_current(str(settings.get("mode", "")), animate=False)
        self._together.set_current(str(settings.get("together", "")), animate=False)


class StampPanel(_OverlayRows, OptionPanel):
    """Video -> a copy with burn-ins and / or a watermark drawn over it."""

    KEY, TITLE, BUTTON, TAG = "stamp", "Stamp", "Stamp the video", "_stamped"
    ICON, GROUP = "text_frame", "change"
    TIP = "Draw frame numbers, the date, a label or a watermark on the picture"
    PRESETS = {"Review · frame numbers": {"burn_frame": True, "burn_date": True, "burn_time": False},
               "Time code": {"burn_frame": False, "burn_date": False, "burn_time": True}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._add_overlay_rows()
        self._quality = self._switch(QUALITY_HIGH, "High", "How good the picture looks — better is also bigger")
        self._add_row("Quality", self._quality)
        self._burn.set_checked(["frame"])

    accepts = staticmethod(_videos)

    def job(self, source: MediaSource, output: Path) -> Job:
        return stamp(source.info, output, self._overlays(), quality=QUALITY_HIGH[self._quality.current()])

    def settings(self) -> dict:
        return {"quality": self._quality.current(), **self._overlay_settings()}

    def apply_settings(self, settings: dict) -> None:
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        self._apply_overlay_settings(settings)


class LoopPanel(OptionPanel):
    """Video -> the same video several times in a row: a cycle (a walk, a
    gallop) that keeps going, forward every time or there and back."""

    KEY, TITLE, BUTTON, TAG = "loop", "Loop", "Loop the video", "_loop"
    ICON, GROUP = "repeat", "change"
    TIP = "Repeat a cycle several times in a row"
    REPEAT, BACK = "Repeat", "There and back"
    TIMES = ("2", "3", "4", "5", "6", "8", "10", "20")
    PRESETS = {"Cycle ×4": {"way": REPEAT, "times": "4"}, "There and back ×3": {"way": BACK, "times": "3"}}
    PREVIEW_TEXT = "Play the start"
    PREVIEW_TIP = "Play the first seconds of the loop — enough to see how it goes round"
    PREVIEW_FROM_START = True
    COMPARES_SIZE = False

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._source: MediaSource | None = None
        self._way = self._switch([self.REPEAT, self.BACK], self.REPEAT,
                                 "Repeat: the video again and again, as it is." + NL
                                 + "There and back: forward, then backward, and that again — for motion that "
                                   "doesn’t end where it began. Without sound; for short videos.")
        self._times = BaseComboBox(list(self.TIMES), "4")
        self._times.setFixedWidth(64)
        self._times.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self._length = qt.QtWidgets.QLabel()
        self._length.setObjectName("mediaHint")
        self._length.setWordWrap(True)  # so the row gives it the room that is left
        self._quality = self._switch(QUALITY_HIGH, "High", "How good the picture looks — better is also bigger")
        self._add_row("Way", self._way)
        self._add_row("Times", self._times, self._length)
        self._add_row("Quality", self._quality)
        self.changed.connect(self._update_length)

    accepts = staticmethod(_videos)

    # a loop is watched at its seam: the preview is as long as one round and a bit, 12 s at most
    PREVIEW_SECONDS = property(lambda self: min(self._round() * 1.5, 12.0) if self._source else 3.0)

    def _round(self) -> float:
        """Seconds of one round of the loop."""
        length = self._source.info.duration if self._source is not None else 0.0
        return length * (2 if self._way.current() == self.BACK else 1)

    def set_sources(self, sources: list) -> None:
        self._source = sources[0]
        self._update_length()

    def _update_length(self) -> None:
        if self._source is None:
            return
        times = int(self._times.currentText())
        self._length.setText(f"times  ·  {format_time(round(self._source.info.duration, 1))} becomes "
                             f"{format_time(round(self._round() * times, 1))}")

    def job(self, source: MediaSource, output: Path) -> Job:
        return loop(source.info, output, times=int(self._times.currentText()),
                    there_and_back=self._way.current() == self.BACK, quality=QUALITY_HIGH[self._quality.current()])

    def settings(self) -> dict:
        return {"way": self._way.current(), "times": self._times.currentText(), "quality": self._quality.current()}

    def apply_settings(self, settings: dict) -> None:
        self._way.set_current(str(settings.get("way", "")), animate=False)
        self._quality.set_current(str(settings.get("quality", "")), animate=False)
        if str(settings.get("times", "")) in self.TIMES:
            self._times.setCurrentText(str(settings["times"]))
        self._update_length()


class SoundPanel(OptionPanel):
    """Video -> its sound taken out as a file, the sound removed, or another sound put under it."""

    KEY, TITLE = "sound", "Sound"
    ICON, GROUP = "volume", "change"
    COMPARES_SIZE = False
    TIP = "Take the sound out, remove it, replace it — or make it louder, even, fade it"
    EXTRACT, REMOVE, REPLACE, CHANGE = "Extract", "Remove", "Replace", "Adjust"
    MODES_RENAMED = {"Take it out": "Extract"}  # as versions up to 0.1.6 saved it
    SOUND_KINDS = {"WAV": "wav", "MP3": "mp3", "M4A": "m4a"}
    EVEN = "Even out"
    VOLUMES = {"As it is": 1.0, EVEN: 1.0, "50%": 0.5, "75%": 0.75, "150%": 1.5, "200%": 2.0}
    FADES = {"None": 0.0, "0.5 s": 0.5, "1 s": 1.0, "2 s": 2.0, "3 s": 3.0}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._mode = self._switch([self.EXTRACT, self.REMOVE, self.REPLACE, self.CHANGE], self.EXTRACT,
                                  "Extract: the sound as a file of its own." + NL
                                  + "Remove: the same video without sound." + NL
                                  + "Replace: the same video with another sound." + NL
                                  + "Adjust: the same video, its sound louder or quieter, evened out, faded.")
        self._volume = BaseComboBox(list(self.VOLUMES), "As it is")
        self._volume.setFixedWidth(96)
        self._volume.setToolTip("How loud. “Even out” brings the sound to the usual loudness of videos — "
                                "quiet places up, loud ones down")
        self._fade_in = BaseComboBox(list(self.FADES), "None")
        self._fade_out = BaseComboBox(list(self.FADES), "None")
        for combo, tip in ((self._fade_in, "The sound rises from silence at the start"),
                           (self._fade_out, "The sound dies away at the end")):
            combo.setFixedWidth(72)
            combo.setToolTip(tip)
        for combo in (self._volume, self._fade_in, self._fade_out):
            combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self._kind = self._switch(self.SOUND_KINDS, "WAV", "WAV: exactly as it is, big. MP3 / M4A: small.")
        self._new, self._new_button = self._file_field("the sound file to use", "The sound to put under the video",
                                                       SOUND_PATTERNS)
        self._add_row("Do", self._mode)
        self._kind_row = self._add_row("As", self._kind)
        self._new_row = self._add_row("New sound", self._new, self._new_button)
        self._volume_row = self._add_row("Volume", self._volume)
        self._fade_row = self._add_row("Fade", self._fade_in, self._note("in"), self._fade_out, self._note("out"))
        self._note_row = self._add_row("", hint="The picture is copied as it is — instant, nothing is lost.")
        self._mode.current_changed.connect(lambda _option: self._sync())
        self._sync()

    def _sync(self) -> None:
        mode = self._mode.current()
        self._set_row_visible(self._kind_row, mode == self.EXTRACT)
        self._set_row_visible(self._new_row, mode == self.REPLACE)
        self._set_row_visible(self._volume_row, mode == self.CHANGE)
        self._set_row_visible(self._fade_row, mode == self.CHANGE)
        self._set_row_visible(self._note_row, mode != self.EXTRACT)

    BUTTON = property(lambda self: {self.EXTRACT: "Take the sound out", self.REMOVE: "Remove the sound",
                                    self.REPLACE: "Replace the sound",
                                    self.CHANGE: "Change the sound"}[self._mode.current()])
    TAG = property(lambda self: {self.EXTRACT: "", self.REMOVE: "_silent", self.REPLACE: "_sound",
                                 self.CHANGE: "_sound"}[self._mode.current()])

    accepts = staticmethod(_videos)

    def set_sound_target(self, lit: bool) -> None:
        self._light_field(self._new, lit)

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
        if mode == self.CHANGE:
            return adjust_audio(source.info, output, volume=self.VOLUMES[self._volume.currentText()],
                                even=self._volume.currentText() == self.EVEN,
                                fade_in=self.FADES[self._fade_in.currentText()],
                                fade_out=self.FADES[self._fade_out.currentText()])
        sound = self._new.text().strip()
        if not sound:
            raise MediaError("Choose the sound file to put under the video.")
        if not Path(sound).is_file():
            raise MediaError(f"The sound file isn’t there: {sound}")
        return replace_audio(source.info, output, sound)

    def settings(self) -> dict:
        return {"mode": self._mode.current(), "kind": self._kind.current(), "volume": self._volume.currentText(),
                "fade_in": self._fade_in.currentText(), "fade_out": self._fade_out.currentText()}

    def apply_settings(self, settings: dict) -> None:
        mode = str(settings.get("mode", ""))
        self._mode.set_current(self.MODES_RENAMED.get(mode, mode), animate=False)
        self._kind.set_current(str(settings.get("kind", "")), animate=False)
        for combo, key, known in ((self._volume, "volume", self.VOLUMES), (self._fade_in, "fade_in", self.FADES),
                                  (self._fade_out, "fade_out", self.FADES)):
            if str(settings.get(key, "")) in known:
                combo.setCurrentText(str(settings[key]))
        self._sync()


class GifPanel(OptionPanel):
    """Video -> an animated GIF for a chat or a document."""

    KEY, TITLE, BUTTON = "gif", "GIF", "Create GIF"
    ICON, GROUP = "gif", "convert"
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
    ICON, GROUP = "clapper", "convert"
    TIP = "A big file that keeps the picture — for editing and grading"
    KINDS = {"ProRes": "prores", "HQ": "prores_hq", "4444": "prores_4444", "DNxHR": "dnxhr_hq"}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._kind = self._switch(self.KINDS, "ProRes",
                                  "ProRes: the usual choice. HQ: ProRes HQ — more of the picture, bigger." + NL
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
        chosen = str(settings.get("kind", ""))
        self._kind.set_current(RENAMED.get(chosen, chosen), animate=False)


class AdjustPanel(OptionPanel):
    """Video -> a corrected copy: turned, cropped to a shape, at another frame rate, faster or slower."""

    KEY, TITLE, BUTTON, TAG = "adjust", "Adjust", "Adjust the video", "_adjusted"
    ICON, GROUP = "crop", "change"
    TIP = "Turn, crop, change the frame rate or the speed"
    TURNS = {"No": 0, "Right": 90, "Left": -90, "180°": 180}
    TURNS_RENAMED = {"90° right": "Right", "90° left": "Left"}  # as earlier versions saved them
    DRAW = "Draw"
    SHAPES = {"Keep": "", "16:9": "16:9", "4:3": "4:3", "1:1": "1:1", "9:16": "9:16", DRAW: ""}
    RATES = {"Keep": None, "24": 24.0, "25": 25.0, "30": 30.0, "60": 60.0}
    FACTORS = {"0.25×": 0.25, "0.5×": 0.5, "1×": 1.0, "1.5×": 1.5, "2×": 2.0, "4×": 4.0}
    PRESETS = {"Vertical 9:16": {"turn": "No", "shape": "9:16", "rate": "Keep", "factor": "1×"},
               "Square": {"turn": "No", "shape": "1:1", "rate": "Keep", "factor": "1×"},
               "Twice as fast": {"turn": "No", "shape": "Keep", "rate": "Keep", "factor": "2×"}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._turn = self._switch(self.TURNS, "No", "Turn the picture: a quarter to the right or to the left, "
                                                    "or upside down")
        self._shape = BaseComboBox(list(self.SHAPES), "Keep")
        self._shape.setFixedWidth(96)
        self._shape.setToolTip("Crop the picture around its centre to this shape — or “Draw”: mark what to keep "
                               "on the picture yourself")
        self._shape.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self._source: MediaSource | None = None
        self._workers: list = []
        self._token = 0
        self._crop = CropPicker()
        self._crop.setToolTip("Drag a corner or an edge to resize what is kept; drag inside to move it")
        self._crop.set_box(0.1, 0.1, 0.8, 0.8)
        self._crop_note = self._note("")
        self._crop.box_changed.connect(lambda *_box: self._on_crop_changed())
        self._shape.currentIndexChanged.connect(lambda _index: self._sync())
        self._rate = self._switch(self.RATES, "Keep", "Frames per second of the result")
        # six options: a list, not a switch (a switch is as wide as options x its widest label)
        self._factor = BaseComboBox(list(self.FACTORS), "1×")
        self._factor.setFixedWidth(84)
        self._factor.setToolTip("Play faster or slower — the sound follows at its own pitch")
        self._factor.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self._add_row("Turn", self._turn)
        self._add_row("Crop to", self._shape)
        self._crop_row = self._add_row("", self._crop)
        self._crop_note_row = self._add_row("", self._crop_note)
        self._add_row("Frame rate", self._rate)
        self._add_row("Speed", self._factor, hint="1× = as it is")
        self._sync()

    accepts = staticmethod(_videos)

    def _drawing(self) -> bool:
        return self._shape.currentText() == self.DRAW

    def _sync(self) -> None:
        self._set_row_visible(self._crop_row, self._drawing())
        self._set_row_visible(self._crop_note_row, self._drawing())
        if self._drawing():
            self._on_crop_changed(emit=False)
            self._load_picture()

    def _on_crop_changed(self, emit: bool = True) -> None:
        if self._source is not None:
            _x, _y, width, height = self._crop.box()
            info = self._source.info
            self._crop_note.setText(f"keeps {int(info.width * width) // 2 * 2}×{int(info.height * height) // 2 * 2} "
                                    f"of {info.resolution_text()}")
        if emit:
            self.changed.emit()

    def set_sources(self, sources: list) -> None:
        self._source = sources[0]
        self._token += 1
        self._crop.set_picture(None)
        self._crop.set_box(0.1, 0.1, 0.8, 0.8)
        if self._drawing():
            self._on_crop_changed(emit=False)
            self._load_picture()

    def _load_picture(self) -> None:
        """A frame from the middle of the video to draw the crop on (made on a worker)."""
        tools, source = self._tools(), self._source
        if tools is None or source is None:
            return
        token = self._token

        def done(paths) -> None:
            if token == self._token and paths and paths[0] is not None:
                self._crop.set_picture(qt.QtGui.QPixmap(str(paths[0])))

        cache = Path(tempfile.gettempdir()) / "msl_tools" / "media" / "trim"
        worker = ResultWorker(lambda: frames_at(tools, source.info, [source.info.duration / 2], cache,
                                                f"crop_{id(self)}", 640), parent=self)
        self._workers.append(worker)
        worker.done.connect(done)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def job(self, source: MediaSource, output: Path) -> Job:
        return adjust(source.info, output, rotate=self.TURNS[self._turn.current()],
                      aspect=self.SHAPES[self._shape.currentText()], fps=self.RATES[self._rate.current()],
                      speed_factor=self.FACTORS[self._factor.currentText()],
                      crop_box=self._crop.box() if self._drawing() else None)

    def settings(self) -> dict:
        return {"turn": self._turn.current(), "shape": self._shape.currentText(), "rate": self._rate.current(),
                "factor": self._factor.currentText()}

    def apply_settings(self, settings: dict) -> None:
        turn = str(settings.get("turn", ""))
        self._turn.set_current(self.TURNS_RENAMED.get(turn, turn), animate=False)
        if str(settings.get("shape", "")) in self.SHAPES:
            self._shape.setCurrentText(str(settings["shape"]))
        self._rate.set_current(str(settings.get("rate", "")), animate=False)
        if str(settings.get("factor", "")) in self.FACTORS:
            self._factor.setCurrentText(str(settings["factor"]))
        self._sync()


class FramesPanel(OptionPanel):
    """Video -> pictures: every frame (or every Nth) as an image sequence in
    a folder of its own, or ONE frame, picked by time and shown before it
    is saved."""

    KEY, TITLE = "frames", "To frames"
    ICON, GROUP = "image_stack", "convert"
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
        self._one_token = 0  # the one-frame picture's own (see _load_preview)
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

    PREVIEW = False          # frames are pictures: "One frame" shows its own
    COMPARES_SIZE = False
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
        self._one_token += 1  # as in TrimPanel._load_previews: the newest request wins, own files
        token, source_token = self._one_token, self._token

        def done(paths) -> None:
            if token != self._one_token or source_token != self._token:
                _remove_files(paths)
                return
            pixmap = qt.QtGui.QPixmap(str(paths[0])) if paths and paths[0] is not None else qt.QtGui.QPixmap()
            _remove_files(paths)  # in memory now
            if pixmap.isNull():
                self._preview.setPixmap(qt.QtGui.QPixmap())
                return
            ratio = self.devicePixelRatioF()
            scaled = pixmap.scaled(self.PREVIEW_SIZE * ratio, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                   qt.QtCore.Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            self._preview.setPixmap(scaled)

        cache = Path(tempfile.gettempdir()) / "msl_tools" / "media" / "trim"
        worker = ResultWorker(lambda: frames_at(tools, source.info, [at], cache, f"one_{id(self)}_{token}", 256), parent=self)
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


class FitPanel(OptionPanel):
    """Video -> the same video in a frame of another shape, nothing cut off:
    for a place that wants 9:16, 1:1, 16:9."""

    KEY, TITLE, BUTTON = "fit", "Fit a shape", "Fit the video"
    ICON, GROUP = "frame_fit", "change"
    TIP = "Put the whole picture into 9:16, 1:1 or 16:9 — with a blurred background or bars"
    SHAPES = ("9:16", "1:1", "4:5", "16:9")
    HEIGHTS = {"1080p": 1080, "720p": 720}
    FILLS = {"Blurred": "blur", "Bars": "bars"}
    PRESETS = {"Shorts · 9:16": {"shape": "9:16", "height": "1080p", "fill": "Blurred"},
               "Square": {"shape": "1:1", "height": "1080p", "fill": "Blurred"}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._shape = self._switch(self.SHAPES, "9:16", "The shape of the new frame (width : height)")
        self._height = self._switch(self.HEIGHTS, "1080p", "The height of the new frame")
        self._fill = self._switch(self.FILLS, "Blurred",
                                  "Blurred: around the picture, the same picture blown up and blurred." + NL
                                  + "Bars: black bars.")
        self._add_row("Shape", self._shape)
        self._add_row("Height", self._height)
        self._add_row("Around it", self._fill)
        self._add_row("", hint="Nothing is cut off. To CUT the picture to a shape instead, use Adjust → Crop to.")

    accepts = staticmethod(_videos)
    TAG = property(lambda self: "_" + self._shape.current().replace(":", "x"))

    def job(self, source: MediaSource, output: Path) -> Job:
        return fit(source.info, output, aspect=self._shape.current(), height=self.HEIGHTS[self._height.current()],
                   fill=self.FILLS[self._fill.current()])

    def settings(self) -> dict:
        return {"shape": self._shape.current(), "height": self._height.current(), "fill": self._fill.current()}

    def apply_settings(self, settings: dict) -> None:
        self._shape.set_current(str(settings.get("shape", "")), animate=False)
        self._height.set_current(str(settings.get("height", "")), animate=False)
        self._fill.set_current(str(settings.get("fill", "")), animate=False)


class SheetPanel(OptionPanel):
    """Video -> ONE picture with frames taken evenly along it: the whole shot at a glance."""

    KEY, TITLE, BUTTON, TAG = "sheet", "Contact sheet", "Make the sheet", "_sheet"
    ICON, GROUP = "grid", "convert"
    TIP = "One picture with frames from along the video — the whole shot at a glance"
    COLUMNS = ("3", "4", "5", "6", "8")
    ROWS = ("1", "2", "3", "4", "5", "6")
    KINDS = {"JPG": ".jpg", "PNG": ".png"}
    WIDTHS = {"1920": 1920, "2560": 2560, "3840": 3840}
    PREVIEW = False            # it is one picture, made in a moment
    COMPARES_SIZE = False

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._across = BaseComboBox(list(self.COLUMNS), "4")
        self._down = BaseComboBox(list(self.ROWS), "3")
        for combo in (self._across, self._down):
            combo.setFixedWidth(56)
            combo.currentIndexChanged.connect(lambda _index: self._on_changed())
        self._count = self._note("")
        self._times = self._check("Write each frame’s time on it", True)
        self._kind = self._switch(self.KINDS, "JPG")
        self._width = self._switch(self.WIDTHS, "1920", "How wide the whole sheet is, in pixels")
        self._add_row("Frames", self._across, self._note("across"), self._down, self._note("down"), self._count)
        self._add_row("Times", self._times)
        self._add_row("Width", self._width)
        self._add_row("Format", self._kind)
        self._on_changed(emit=False)

    def _on_changed(self, emit: bool = True) -> None:
        self._count.setText(f"= {int(self._across.currentText()) * int(self._down.currentText())} frames")
        if emit:
            self.changed.emit()

    accepts = staticmethod(_videos)

    def suffix(self, source: MediaSource) -> str:
        return self.KINDS[self._kind.current()]

    def job(self, source: MediaSource, output: Path) -> Job:
        return contact_sheet(source.info, output, columns=int(self._across.currentText()),
                             rows=int(self._down.currentText()), width=self.WIDTHS[self._width.current()],
                             times=self._times.isChecked())

    def settings(self) -> dict:
        return {"columns": self._across.currentText(), "rows": self._down.currentText(),
                "times": self._times.isChecked(), "kind": self._kind.current(), "width": self._width.current()}

    def apply_settings(self, settings: dict) -> None:
        if str(settings.get("columns", "")) in self.COLUMNS:
            self._across.setCurrentText(str(settings["columns"]))
        if str(settings.get("rows", "")) in self.ROWS:
            self._down.setCurrentText(str(settings["rows"]))
        self._times.set_checked_immediate(bool(settings.get("times", True)))
        self._kind.set_current(str(settings.get("kind", "")), animate=False)
        self._width.set_current(str(settings.get("width", "")), animate=False)
        self._on_changed(emit=False)


class ReframePanel(OptionPanel):
    """Image sequence -> another image sequence: another picture format and / or
    a smaller frame, the same frame numbers."""

    KEY, TITLE, BUTTON = "reframe", "Convert frames", "Convert the frames"
    ICON, GROUP = "image_stack", "convert"
    TIP = "The same frames in another format or a smaller size — still an image sequence"
    KINDS = {"PNG": "png", "JPG": "jpg", "TIFF": "tiff"}
    JPG_QUALITIES = {"Best": "best", "Good": "good", "Small": "small"}
    HEIGHTS = {"Keep": 0, "1080p": 1080, "720p": 720, "480p": 480}
    INTO_FOLDER = True
    PREVIEW = False
    COMPARES_SIZE = False

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._kind = self._switch(self.KINDS, "JPG", "PNG: exact, big. JPG: small, slightly lossy. TIFF: exact.")
        self._jpg = self._switch(self.JPG_QUALITIES, "Best", "How good the JPG pictures are — better is bigger")
        self._height = self._switch(self.HEIGHTS, "Keep", "The height of the frames. Smaller frames are never enlarged.")
        self._add_row("Format", self._kind)
        self._jpg_row = self._add_row("Quality", self._jpg)
        self._add_row("Frame size", self._height)
        self._kind.current_changed.connect(lambda _option: self._sync())
        self._sync()

    def _sync(self) -> None:
        self._set_row_visible(self._jpg_row, self._kind.current() == "JPG")

    @staticmethod
    def accepts(sources: list) -> bool:
        return bool(sources) and all(source.is_sequence for source in sources)

    TAG = property(lambda self: "_" + self.KINDS[self._kind.current()])

    def suffix(self, source: MediaSource) -> str:
        return ""  # the result is a folder

    def job(self, source: MediaSource, output: Path) -> Job:
        if output.resolve() == source.sequence.folder.resolve():
            raise MediaError("The new frames can’t go into the folder of the frames they are made from — "
                             "pick another folder.")
        return convert_sequence(source.sequence, output, image_format=self.KINDS[self._kind.current()],
                                max_height=self.HEIGHTS[self._height.current()],
                                jpg_quality=self.JPG_QUALITIES[self._jpg.current()],
                                frame_size=(source.info.width, source.info.height))

    def settings(self) -> dict:
        return {"kind": self._kind.current(), "jpg": self._jpg.current(), "height": self._height.current()}

    def apply_settings(self, settings: dict) -> None:
        self._kind.set_current(str(settings.get("kind", "")), animate=False)
        self._jpg.set_current(str(settings.get("jpg", "")), animate=False)
        self._height.set_current(str(settings.get("height", "")), animate=False)
        self._sync()


class ChainPanel(OptionPanel):
    """Video -> several things done to it in ONE run: a piece cut out, the frame
    made smaller, burn-ins drawn — each with the settings its own action has.
    One run means one loss of quality instead of one per step, and one wait."""

    KEY, TITLE, BUTTON, TAG = "chain", "Several at once", "Do it all", "_edit"
    ICON, GROUP = "steps", "several"
    TIP = "Cut a piece, make it smaller and stamp it — in one run"
    STEPS = (("trim", "Cut the piece", "the piece picked on Trim"),
             ("shrink", "Make it smaller", "the frame size, quality and codec of Make smaller"),
             ("stamp", "Stamp it", "what Stamp draws on the picture"))
    PRESETS = {"Review cut": {"trim": True, "shrink": True, "stamp": True},
               "Small + stamp": {"trim": False, "shrink": True, "stamp": True}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._panels: dict = {}
        self._checks, self._notes = {}, {}
        for key, title, tip in self.STEPS:
            self._checks[key] = self._check(title, True, f"Uses {tip}")
            self._notes[key] = self._note("")
            self._notes[key].setWordWrap(True)  # so the row gives it the room that is left
            self._checks[key].toggled.connect(lambda _checked: self.refresh())
        self._add_row("Steps", self._checks["trim"])
        self._add_row("", self._notes["trim"])
        self._add_row("", self._checks["shrink"])
        self._add_row("", self._notes["shrink"])
        self._add_row("", self._checks["stamp"])
        self._add_row("", self._notes["stamp"])
        self._add_row("", hint="Each step takes its settings from its own action — set them there, come back here.")

    accepts = staticmethod(_videos)

    def bind(self, panels: dict) -> None:
        self._panels = panels
        for key in self._checks:
            if key in panels:
                panels[key].changed.connect(self.refresh)

    def refresh(self) -> None:
        """Says under each step what it will do, from that action's settings."""
        trim_panel, shrink_panel, stamp_panel = (self._panels.get(key) for key in ("trim", "shrink", "stamp"))
        texts = {"trim": trim_panel.summary() if trim_panel else "",
                 "shrink": shrink_panel.summary() if shrink_panel else "",
                 "stamp": stamp_panel._overlay_summary() if stamp_panel else ""}
        for key, note in self._notes.items():
            note.setText(texts[key] if self._checks[key].isChecked() else "not done")

    def set_sources(self, sources: list) -> None:
        self.refresh()

    def job(self, source: MediaSource, output: Path) -> Job:
        if not all(key in self._panels for key in ("trim", "shrink", "stamp")):
            raise MediaError("The steps’ own actions aren’t available.")
        start = end = None
        if self._checks["trim"].isChecked():
            start, end = self._panels["trim"].piece()
        size = self._panels["shrink"].chain_settings()
        if not self._checks["shrink"].isChecked():
            size = {**size, "max_height": 0, "quality": "high"}
        overlays = self._panels["stamp"]._overlays() if self._checks["stamp"].isChecked() else None
        return chain(source.info, output, start=start, end=end, overlays=overlays, **size)

    def settings(self) -> dict:
        return {key: check.isChecked() for key, check in self._checks.items()}

    def apply_settings(self, settings: dict) -> None:
        for key, check in self._checks.items():
            check.set_checked_immediate(bool(settings.get(key, True)))
        self.refresh()


class JoinPanel(OptionPanel):
    """Several videos -> one, in the order they were dropped."""

    KEY, TITLE, BUTTON, TAG, COMBINES = "join", "Join", "Join the videos", "_joined", True
    ICON, GROUP = "merge", "combine"
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
    ICON, GROUP = "split_view", "combine"
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


PANELS = (SequencePanel, ReframePanel, ShrinkPanel, TrimPanel, LoopPanel, StampPanel, SoundPanel, AdjustPanel,
          FitPanel, GifPanel, FramesPanel, SheetPanel, EditingPanel, ChainPanel, JoinPanel, ComparePanel)
