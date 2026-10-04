# tools/desktop/media/panels/adjust.py
"""Adjust: rotate, crop (also drawn on a frame), frame rate, speed."""
import tempfile
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, adjust
from msl_tools.msl.core.media.thumbnail import frames_at
from msl_tools.msl.tools.desktop.media.source import MediaSource
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.compositions.crop_picker import CropPicker
from msl_tools.msl.ui.workers.result_worker import ResultWorker
from msl_tools.msl.tools.desktop.media.panels.base import OptionPanel, _videos


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
