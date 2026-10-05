# tools/desktop/media/panels/trim.py
"""Trim: a strip of frames with two handles, to the frame."""
import tempfile
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, MediaError, frame, trim, trim_pieces
from msl_tools.msl.core.media.thumbnail import frames_at
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.tools.desktop.media.source import MediaSource, format_time, parse_time
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.range_strip import RangeStrip
from msl_tools.msl.ui.workers.result_worker import run_in_background
from msl_tools.msl.tools.desktop.media.panels.base import NL, OptionPanel, _remove_files, _videos


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
        run_in_background(target, on_done, keep=self._workers, parent=self)

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
