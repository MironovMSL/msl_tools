# tools/desktop/media/panels/frames.py
"""To frames: a video taken apart into pictures (or one frame)."""
import tempfile
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, MediaError, frame, to_frames
from msl_tools.msl.core.media.recipes import IMAGE_FORMATS
from msl_tools.msl.core.media.thumbnail import frames_at
from msl_tools.msl.tools.desktop.media.source import MediaSource, format_time, parse_time
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.workers.result_worker import run_in_background
from msl_tools.msl.tools.desktop.media.panels.base import NL, OptionPanel, _remove_files, _videos


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
        run_in_background(lambda: frames_at(tools, source.info, [at], cache, f"one_{id(self)}_{token}", 256), done,
                          keep=self._workers, parent=self)

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
