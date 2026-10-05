# tools/desktop/media/panels/sequence.py
"""The actions of an image sequence: To video, Convert frames."""
from pathlib import Path

from msl_tools.msl.core.media import Job, MediaError, convert_sequence, sequence_to_video
from msl_tools.msl.core.media.recipes import FORMATS, GAPS_ERROR, GAPS_HOLD
from msl_tools.msl.tools.desktop.media.source import MediaSource, format_time
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.tools.desktop.media.panels.base import FORMAT_TIP, OptionPanel, QUALITY_HIGH, RENAMED, SOUND_PATTERNS, SPEEDS, SPEED_TIP, VIDEO_FORMATS, _OverlayRows


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

    def job(self, source: MediaSource, output: Path, use_sound: bool = True) -> Job:
        """`use_sound` False: without the sound field's file (a watched folder's renders aren't the
        sequence that sound was picked for)."""
        sound = self._sound.text().strip() if use_sound else ""
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
