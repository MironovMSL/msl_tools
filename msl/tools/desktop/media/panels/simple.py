# tools/desktop/media/panels/simple.py
"""The short forms: Stamp, Loop, Sound, GIF, For editing, Fit a shape, Contact sheet."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import (Job, MediaError, adjust_audio, contact_sheet, convert, extract_audio, fit, gif,
                                      loop, remove_audio, replace_audio, stamp)
from msl_tools.msl.core.media.recipes import SOUND_FORMATS
from msl_tools.msl.tools.desktop.media.source import MediaSource, format_time
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.tools.desktop.media.panels.base import NL, OptionPanel, QUALITY_HIGH, RENAMED, SOUND_PATTERNS, _OverlayRows, _videos


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
