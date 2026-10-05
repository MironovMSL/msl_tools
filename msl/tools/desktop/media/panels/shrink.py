# tools/desktop/media/panels/shrink.py
"""Make smaller — with its before / after crops and the graphics-card check."""
import tempfile
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, MediaError, gpu_encoding_works, shrink
from msl_tools.msl.core.media.run import clean_up, quality_crops
from msl_tools.msl.tools.desktop.media.source import MediaSource
from msl_tools.msl.ui.workers.result_worker import run_in_background
from msl_tools.msl.tools.desktop.media.panels.base import NL, OptionPanel, _videos


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

        run_in_background(work, done, failed, keep=self._workers, parent=self)

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

            run_in_background(lambda: gpu_encoding_works(tools), done, keep=self._workers, parent=self)

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
