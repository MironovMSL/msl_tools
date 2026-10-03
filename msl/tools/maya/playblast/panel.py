# tools/maya/playblast/panel.py
import json
import shutil
import tempfile
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.fs.manager import FileSystemManager
from msl_tools.msl.core.media import FfmpegLocator, MediaError, find_sequences, run_job, sequence_to_video
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.playblast import capture, naming
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel
from msl_tools.msl.ui.widgets.atoms.progress.base_progress_bar import BaseProgressBar
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces.stable_scroll_area import StableScrollArea
from msl_tools.msl.ui.widgets.compositions.fact_tiles import FactTiles
from msl_tools.msl.ui.workers.result_worker import ResultWorker

StylesheetBuilder.register_template(Path(__file__).with_name("playblast.qss"))

ACTIVE_VIEW = "Active view"
SIZE_RENDER, SIZE_CUSTOM = "Render settings", "Custom"
RANGE_CUSTOM = "Custom"
FORMAT_MP4, FORMAT_FRAMES = "MP4", "Frames"
QUALITY = {"Best": "best", "High": "high", "Good": "good", "Small": "small"}  # the word shown -> core/media's


class PlayblastPanel(qt.QtWidgets.QWidget):
    """The playblast tool's panel inside Maya (shown in a PlayblastWindow; it
    can also sit in a Maya panel through MayaDock).

    What is seen through which camera, at what size, which frames — then
    where the result goes (folder and name take {tokens}, see naming.py) and
    as what: an MP4 made by our own ffmpeg chain (core/media — Maya writes
    PNG frames into a temporary folder, ffmpeg makes the video with the
    timeline's sound under it), or the frames themselves. The player opens
    when it is done.

    Maya draws the frames in its main thread (the window waits, Esc
    cancels); encoding runs on a worker with a progress bar. The scene is
    read when the panel is shown and when the pointer enters it, never in
    the constructor. Settings: configsMayaMng "playblast" (`settings`). ffmpeg is the
    hub's: the path set in the Media tool, the managed copy, or PATH.
    """

    TOOL_NAME = "playblast"
    DEFAULTS = {"camera": "", "size": "HD 1080", "width": 1920, "height": 1080, "range": capture.RANGE_PLAYBACK,
                "start": 1, "end": 24, "folder": naming.DEFAULT_FOLDER, "name": naming.DEFAULT_NAME,
                "format": FORMAT_MP4, "quality": "High", "sound": True, "overwrite": False, "open": True,
                "ornaments": False}

    _encoding_progressed = qt.QtCore.Signal(float)
    # Running workers, kept by the CLASS and parentless: a docked panel can be closed (and deleted)
    # at any moment, and a QThread destroyed while it runs takes Maya down with it.
    _workers: set = set()

    def __init__(self, parent=None):
        super().__init__(parent)
        config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": dict(self.DEFAULTS)})
        self._settings = config["settings"]
        self._logger = Resources().logsMaya.get(self.TOOL_NAME)
        self._tools = None            # FfmpegTools once found
        self._tools_looked = False
        self._busy = False
        self._result: Path | None = None
        self._pending: tuple | None = None   # (target, when it started) of the video being made
        self._capture_job: tuple | None = None   # (settings, target, video) of the capture about to start
        self._loading = False
        self._build_widgets()
        self._build_layout()
        self._apply_settings()
        self._connect()

    # ------------------------------------------------------------------ building

    def _build_widgets(self) -> None:
        icons = UiResources().iconManager
        self._title_icon = TintedIcon(icons.get_icon("clapper", sub_folder="actions"), 16)
        self._title_icon.setObjectName("playblastTitleIcon")
        self._title = qt.QtWidgets.QLabel("PLAYBLAST")
        self._title.setObjectName("playblastTitle")
        self._ffmpeg_note = qt.QtWidgets.QLabel()
        self._ffmpeg_note.setObjectName("playblastHint")
        self._facts = FactTiles()

        self._camera = BaseComboBox([ACTIVE_VIEW], ACTIVE_VIEW)
        self._camera.setToolTip("The camera the playblast is seen through.\n"
                                "The viewport gets its own camera back afterwards.")
        self._size = BaseComboBox([SIZE_RENDER, *capture.RESOLUTIONS, SIZE_CUSTOM], "HD 1080")
        self._width, self._height = self._number_field(4), self._number_field(4)
        self._times = qt.QtWidgets.QLabel("×")
        self._times.setObjectName("playblastHint")
        self._range = BaseComboBox([capture.RANGE_PLAYBACK, capture.RANGE_ANIMATION, capture.RANGE_RENDER,
                                    RANGE_CUSTOM], capture.RANGE_PLAYBACK)
        self._range.setToolTip("Playback: the range slider's frames.\nAnimation: the whole timeline.\n"
                               "Render: the frames of the render settings.")
        self._start, self._end = self._number_field(6, signed=True), self._number_field(6, signed=True)
        self._dash = qt.QtWidgets.QLabel("–")
        self._dash.setObjectName("playblastHint")

        tokens = "\n".join(f"{{{token}}} — {meaning}" for token, meaning in naming.TOKENS.items())
        self._folder = qt.QtWidgets.QLineEdit()
        self._folder.setPlaceholderText(naming.DEFAULT_FOLDER)
        self._folder.setToolTip("The folder the playblast goes to. It may hold:\n" + tokens)
        self._browse = IconPushButton(icons.get_icon("browse", sub_folder="actions"), "Choose the folder…")
        self._browse.setFixedSize(24, 22)
        self._name = qt.QtWidgets.QLineEdit()
        self._name.setPlaceholderText(naming.DEFAULT_NAME)
        self._name.setToolTip("The file's name, without the extension. It may hold:\n" + tokens)
        self._token = qt.QtWidgets.QPushButton("{ }")
        self._token.setObjectName("playblastToken")
        self._token.setToolTip("Put a token into the name")
        self._token.setFixedSize(24, 22)
        self._token.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._path = ElidedLabel("", qt.QtCore.Qt.TextElideMode.ElideLeft)
        self._path.setObjectName("playblastHint")

        self._format = SegmentedControl([FORMAT_MP4, FORMAT_FRAMES], FORMAT_MP4)
        self._format.setToolTip("MP4: a video, with the timeline's sound.\nFrames: PNG pictures in a folder.")
        self._quality = BaseComboBox(list(QUALITY), "High")
        self._sound = BaseCheckbox("Sound")
        self._sound.setToolTip("The sound shown on the timeline goes under the video.")
        self._ornaments = BaseCheckbox("Viewport HUD")
        self._ornaments.setToolTip("Keep the viewport's own overlays (heads-up display, axis) in the picture.")
        self._overwrite = BaseCheckbox("Overwrite")
        self._overwrite.setToolTip("On: a playblast of the same name is replaced.\n"
                                   "Off: the new one gets a number — name_2, name_3…")
        self._open = BaseCheckbox("Open when done")
        self._open.setToolTip("The finished playblast opens in the system's player.")

        self._status = qt.QtWidgets.QLabel()
        self._status.setObjectName("playblastStatus")
        self._status.setWordWrap(True)
        self._progress = BaseProgressBar()
        self._progress.setFixedHeight(4)
        self._progress.hide()
        self._play = GlyphButton("▶", "Open the playblast")
        self._play.set_icon(icons.get_icon("play", sub_folder="actions"))
        self._show = GlyphButton("…", "Show it in its folder")
        self._show.set_icon(icons.get_icon("browse", sub_folder="actions"))
        for button in (self._play, self._show):
            button.setObjectName("playblastAction")
            button.hide()
        self._start_button = IconPushButton(icons.get_icon("clapper", sub_folder="actions"))
        self._start_button.setText("Playblast")
        self._start_button.setObjectName("playblastStart")
        self._start_button.setProperty("primary", True)
        self._start_button.setMinimumHeight(28)

    @staticmethod
    def _number_field(digits: int, signed: bool = False) -> qt.QtWidgets.QLineEdit:
        field = qt.QtWidgets.QLineEdit()
        field.setValidator(qt.QtGui.QIntValidator(-99999 if signed else 2, 99999, field))
        field.setFixedWidth(14 + digits * 8)
        field.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        return field

    def _build_layout(self) -> None:
        self._title_row = qt.QtWidgets.QWidget()
        header = qt.QtWidgets.QHBoxLayout(self._title_row)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self._title_icon)
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._ffmpeg_note)

        picture = self._card("PICTURE", [
            ("Camera", [self._camera]),
            ("Size", [self._size, self._width, self._times, self._height]),
            ("Frames", [self._range, self._start, self._dash, self._end]),
        ])
        output = self._card("RESULT", [
            ("Folder", [self._folder, self._browse]),
            ("Name", [self._name, self._token]),
            ("", [self._path]),
            ("Format", [self._format, self._quality]),
        ])
        checks = qt.QtWidgets.QGridLayout()
        checks.setContentsMargins(0, 2, 0, 0)
        checks.setHorizontalSpacing(14)
        checks.setVerticalSpacing(6)
        for index, box in enumerate((self._sound, self._ornaments, self._overwrite, self._open)):
            checks.addWidget(box, index // 2, index % 2)
        checks.setColumnStretch(2, 1)
        output.layout().addLayout(checks)

        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(10, 10, 4, 6)
        column.setSpacing(8)
        column.addWidget(self._title_row)
        column.addWidget(self._facts)
        column.addWidget(picture)
        column.addWidget(output)
        column.addStretch(1)
        scroll = StableScrollArea()
        scroll.setObjectName("playblastScroll")
        scroll.setWidget(body)

        result = qt.QtWidgets.QHBoxLayout()
        result.setSpacing(4)
        result.addWidget(self._status, 1)
        result.addWidget(self._play)
        result.addWidget(self._show)
        foot = qt.QtWidgets.QVBoxLayout()
        foot.setContentsMargins(10, 0, 10, 10)
        foot.setSpacing(6)
        foot.addLayout(result)
        foot.addWidget(self._progress)
        foot.addWidget(self._start_button)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(scroll, 1)
        layout.addLayout(foot)

    def detach_title(self) -> qt.QtWidgets.QLabel:
        """For a window whose own header names the tool: the panel's title row goes away, and
        the one live thing in it — the "ffmpeg 8.0" note — is handed over to be put there."""
        self._ffmpeg_note.setParent(None)
        self._title_row.hide()
        return self._ffmpeg_note

    @staticmethod
    def _card(title: str, rows: list) -> qt.QtWidgets.QFrame:
        """A card: a small heading over caption / controls rows."""
        card = qt.QtWidgets.QFrame()
        card.setObjectName("playblastCard")
        heading = qt.QtWidgets.QLabel(title)
        heading.setObjectName("playblastSection")
        form = qt.QtWidgets.QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 1)
        for index, (caption, widgets) in enumerate(rows):
            if caption:
                label = qt.QtWidgets.QLabel(caption)
                label.setObjectName("playblastCaption")
                form.addWidget(label, index, 0)
            line = qt.QtWidgets.QHBoxLayout()
            line.setSpacing(4)
            for position, widget in enumerate(widgets):
                line.addWidget(widget, 1 if position == 0 else 0)
            form.addLayout(line, index, 1)
        box = qt.QtWidgets.QVBoxLayout(card)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        box.addWidget(heading)
        box.addLayout(form)
        return card

    def _connect(self) -> None:
        self._camera.currentTextChanged.connect(self._on_changed)
        self._size.currentTextChanged.connect(self._on_size_changed)
        self._range.currentTextChanged.connect(self._on_range_changed)
        for field in (self._width, self._height, self._start, self._end, self._folder, self._name):
            field.textEdited.connect(self._on_changed)
        self._format.current_changed.connect(self._on_changed)
        self._quality.currentTextChanged.connect(self._on_changed)
        for box in (self._sound, self._ornaments, self._overwrite, self._open):
            box.toggled.connect(self._on_changed)
        self._browse.clicked.connect(self._on_browse)
        self._token.clicked.connect(self._on_token_menu)
        self._start_button.clicked.connect(self._on_start)
        self._play.clicked.connect(lambda: self._open_result(self._result))
        self._show.clicked.connect(lambda: self._result and ProcessLauncher.open_file_explorer(self._result))
        self._encoding_progressed.connect(self._on_encoding_progress)

    # ------------------------------------------------------------------ settings

    def _apply_settings(self) -> None:
        """The saved choices onto the controls (without saving them back)."""
        self._loading = True
        get = lambda key: self._settings.get(key, self.DEFAULTS[key])
        self._set_combo(self._size, get("size"))
        self._set_combo(self._range, get("range"))
        self._width.setText(str(get("width")))
        self._height.setText(str(get("height")))
        self._start.setText(str(get("start")))
        self._end.setText(str(get("end")))
        self._folder.setText(get("folder"))
        self._name.setText(get("name"))
        self._format.set_current(get("format") if get("format") in self._format.options() else FORMAT_MP4, animate=False)
        self._set_combo(self._quality, get("quality"))
        for box, key in ((self._sound, "sound"), (self._ornaments, "ornaments"), (self._overwrite, "overwrite"),
                         (self._open, "open")):
            box.set_checked_immediate(bool(get(key)))
        self._loading = False
        self._sync_enabled()

    @staticmethod
    def _set_combo(combo, text: str) -> None:
        index = combo.findText(str(text))
        if index >= 0:
            combo.setCurrentIndex(index)

    def _save_settings(self) -> None:
        camera = self._camera.currentText()
        values = {"camera": "" if camera == ACTIVE_VIEW else camera, "size": self._size.currentText(),
                  "range": self._range.currentText(), "folder": self._folder.text().strip(),
                  "name": self._name.text().strip(), "format": self._format.current(),
                  "quality": self._quality.currentText(), "sound": self._sound.isChecked(),
                  "ornaments": self._ornaments.isChecked(), "overwrite": self._overwrite.isChecked(),
                  "open": self._open.isChecked()}
        if self._size.currentText() == SIZE_CUSTOM:
            values["width"], values["height"] = self._frame_size()
        if self._range.currentText() == RANGE_CUSTOM:
            values["start"], values["end"] = self._frames()
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value

    def _sync_enabled(self) -> None:
        custom_size = self._size.currentText() == SIZE_CUSTOM
        custom_range = self._range.currentText() == RANGE_CUSTOM
        for field in (self._width, self._height):
            field.setReadOnly(not custom_size)
            self._set_state(field, "" if custom_size else "shown")
        for field in (self._start, self._end):
            field.setReadOnly(not custom_range)
            self._set_state(field, "" if custom_range else "shown")
        video = self._format.current() == FORMAT_MP4
        self._quality.setEnabled(video)
        self._sound.setEnabled(video)

    @staticmethod
    def _set_state(widget, state: str) -> None:
        if (widget.property("state") or "") != state:
            widget.setProperty("state", state)
            repolish(widget)

    # ------------------------------------------------------------------ the scene

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        if not self._tools_looked:
            self._tools_looked = True
            self._find_ffmpeg()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if not self._busy:
            self.refresh()

    def refresh(self) -> None:
        """Reads the scene again: cameras, the named sizes and ranges, the facts on top, the path."""
        self._loading = True
        wanted = self._camera.currentText() if self._camera.count() > 1 else (self._settings.get("camera") or "")
        names = [ACTIVE_VIEW] + capture.cameras()
        if names != [self._camera.itemText(index) for index in range(self._camera.count())]:
            self._camera.clear()
            self._camera.addItems(names)
        self._set_combo(self._camera, wanted if wanted in names else ACTIVE_VIEW)
        size = self._size.currentText()
        if size != SIZE_CUSTOM:
            width, height = capture.render_resolution() if size == SIZE_RENDER else capture.RESOLUTIONS[size]
            self._width.setText(str(width))
            self._height.setText(str(height))
        kind = self._range.currentText()
        if kind != RANGE_CUSTOM:
            start, end = capture.frame_range(kind)
            self._start.setText(str(start))
            self._end.setText(str(end))
        self._loading = False
        self._refresh_facts()

    def _refresh_facts(self) -> None:
        start, end = self._frames()
        fps = capture.frame_rate()
        frames = max(0, end - start + 1)
        sound, _frame = capture.timeline_sound()
        pairs = [(capture.scene_name() or "untitled", "scene"), (f"{fps:g}", "fps"),
                 (f"{frames}", "frames"), (self._seconds_text(frames / fps if fps else 0.0), "long"),
                 (self._camera_name(), "camera")]
        if sound:
            pairs.append((Path(sound).name, "sound"))
        self._facts.set_pairs(pairs)
        path = self._output_path()
        self._path.setText(str(path))
        self._path.setToolTip(str(path))

    @staticmethod
    def _seconds_text(seconds: float) -> str:
        return f"{int(seconds // 60)}:{seconds % 60:04.1f}"

    def _camera_name(self) -> str:
        chosen = self._camera.currentText()
        return (capture.active_camera() or "camera") if chosen == ACTIVE_VIEW else chosen

    def _frame_size(self) -> tuple[int, int]:
        return self._number(self._width, 1920), self._number(self._height, 1080)

    def _frames(self) -> tuple[int, int]:
        return self._number(self._start, 1), self._number(self._end, 1)

    @staticmethod
    def _number(field, fallback: int) -> int:
        try:
            return int(field.text())
        except ValueError:
            return fallback

    def _output_path(self) -> Path:
        """Where the playblast would go with what is on screen: the video's file, or the frames' folder."""
        values = naming.token_values(capture.project_folder(), capture.scene_name(), self._camera_name())
        suffix = ".mp4" if self._format.current() == FORMAT_MP4 else ""
        return naming.output_path(self._folder.text(), self._name.text(), values, suffix)

    # ------------------------------------------------------------------ what the user does

    def _on_changed(self, *_args) -> None:
        if self._loading:
            return
        self._sync_enabled()
        self._save_settings()
        self._refresh_facts()

    def _on_size_changed(self, *_args) -> None:
        if not self._loading:
            self._sync_enabled()
            self.refresh()
            self._save_settings()

    def _on_range_changed(self, *_args) -> None:
        self._on_size_changed()

    def _on_browse(self) -> None:
        values = naming.token_values(capture.project_folder(), capture.scene_name(), self._camera_name())
        current = naming.expand(self._folder.text().strip() or naming.DEFAULT_FOLDER, values)
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "Where playblasts go", current)
        if folder:
            project = values["project"].replace("\\", "/")
            if project and folder.replace("\\", "/").lower().startswith(project.lower() + "/"):
                folder = "{project}" + folder.replace("\\", "/")[len(project):]  # stays right in another project
            self._folder.setText(folder)
            self._on_changed()

    def _on_token_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        for token, meaning in naming.TOKENS.items():
            action = menu.addAction(f"{{{token}}}")
            action.setToolTip(meaning)
            action.triggered.connect(lambda _checked=False, text=f"{{{token}}}": self._insert_token(text))
        menu.setToolTipsVisible(True)
        menu.exec(self._token.mapToGlobal(qt.QtCore.QPoint(0, self._token.height() + 2)))

    def _insert_token(self, text: str) -> None:
        self._name.insert(text)
        self._name.setFocus()
        self._on_changed()

    # ------------------------------------------------------------------ ffmpeg

    def _find_ffmpeg(self) -> None:
        """Looks for ffmpeg on a worker (its first start from inside Maya takes a few seconds)."""
        configured = self._configured_ffmpeg()
        worker = ResultWorker(lambda: FfmpegLocator(configured=configured).find())
        worker.done.connect(self._on_ffmpeg)
        worker.failed.connect(self._on_ffmpeg_failed)
        self._keep(worker)
        worker.start()

    @staticmethod
    def _configured_ffmpeg() -> str:
        """The ffmpeg path set in the hub's Media tool ("" = none). Read from its file, never written."""
        try:
            path = FileSystemManager.configsDesktop / "media" / "config.json"
            return str(json.loads(path.read_text(encoding="utf-8")).get("settings", {}).get("ffmpeg_path", "") or "")
        except (OSError, ValueError, AttributeError):
            return ""

    def _on_ffmpeg_failed(self, _error) -> None:
        self._on_ffmpeg(None)

    def _on_ffmpeg(self, tools) -> None:
        self._tools = tools
        if tools is not None:
            self._ffmpeg_note.setText(f"ffmpeg {tools.short_version}")
            self._ffmpeg_note.setToolTip(str(tools.ffmpeg))
        else:
            self._ffmpeg_note.setText("no ffmpeg")
            self._ffmpeg_note.setToolTip("ffmpeg wasn’t found: open Media in the MSL Tools hub to download it.\n"
                                         "Until then a playblast can be saved as frames.")

    @classmethod
    def _keep(cls, worker) -> None:
        workers = cls._workers
        workers.add(worker)
        worker.finished.connect(lambda: workers.discard(worker))

    # ------------------------------------------------------------------ the playblast

    def _on_start(self) -> None:
        if self._busy:
            return
        self.refresh()
        self._save_settings()
        video = self._format.current() == FORMAT_MP4
        if video and self._tools is None:
            self._say("ffmpeg wasn’t found — open Media in the MSL Tools hub to download it, "
                      "or choose “Frames”.", "error")
            return
        width, height = self._frame_size()
        start, end = self._frames()
        target = self._output_path()
        if not self._overwrite.isChecked():
            target = naming.free_path(target)
        chosen = self._camera.currentText()
        if video:
            frames_folder = Path(tempfile.gettempdir()) / "msl_tools" / "playblast" / time.strftime("%Y%m%d_%H%M%S")
            frames_name = "frame"
        else:
            frames_folder, frames_name = target, target.name
        settings = capture.CaptureSettings(
            folder=frames_folder, name=frames_name, start=start, end=end, width=width, height=height,
            camera=capture.ACTIVE_VIEW if chosen == ACTIVE_VIEW else chosen, ornaments=self._ornaments.isChecked())
        self._set_busy(True)
        self._say("Maya is drawing the frames… (Esc cancels)")
        # a moment later, so the line above is on screen before Maya takes over (and never
        # processEvents() here: it would run whatever else is waiting in the middle of a click)
        self._capture_job = (settings, target, video)
        qt.QtCore.QTimer.singleShot(60, self._capture)

    def _capture(self) -> None:
        """Maya draws the frames (the window waits), then the video is made on a worker."""
        settings, target, video = self._capture_job
        frames_folder = settings.folder
        started = time.time()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not video and target.is_dir() and self._overwrite.isChecked():
                for old in target.glob(f"{target.name}.*.png"):
                    old.unlink()  # a shorter range must not leave the longer one's last frames behind
            shot = capture.capture(settings)
        except (capture.CaptureError, OSError) as error:
            if video:
                shutil.rmtree(frames_folder, ignore_errors=True)
            self._finish(None, str(error))
            return
        if not video:
            self._finish(target, "", f"{shot.frames} frames", time.time() - started)
            return
        self._say("Making the video…")
        self._progress.set_progress(0)
        self._progress.show()
        sound = shot.sound if self._sound.isChecked() and shot.sound and Path(shot.sound).is_file() else None
        quality = QUALITY.get(self._quality.currentText(), "high")
        tools, report = self._tools, self._report_progress
        self._pending = (target, started)
        worker = ResultWorker(lambda: self._encode(tools, shot, target, quality, sound, report))
        worker.done.connect(self._on_encoded)
        worker.failed.connect(self._on_encode_failed)
        self._keep(worker)
        worker.start()

    def _report_progress(self, fraction: float, _report=None) -> None:
        try:
            self._encoding_progressed.emit(fraction)
        except RuntimeError:
            pass  # the panel was closed meanwhile; the video is finished all the same

    def _on_encoded(self, _result) -> None:
        target, started = self._pending
        self._finish(target, "", "", time.time() - started)

    def _on_encode_failed(self, error) -> None:
        self._finish(None, str(error))

    @staticmethod
    def _encode(tools, shot, target: Path, quality: str, sound, report) -> None:
        """On a worker: the frames in `shot.folder` -> the video `target`; the frames are removed either way."""
        try:
            sequences = find_sequences(shot.folder)
            if not sequences:
                raise MediaError("Maya wrote no frames.")
            job = sequence_to_video(sequences[0], target, fps=shot.fps, quality=quality, speed="fast", audio=sound,
                                    audio_start=shot.sound_start)
            run_job(tools, job, on_progress=report)
        finally:
            shutil.rmtree(shot.folder, ignore_errors=True)

    def _on_encoding_progress(self, fraction: float) -> None:
        self._progress.set_progress(int(fraction * 100))

    def _finish(self, result: Path | None, error: str, note: str = "", seconds: float = 0.0) -> None:
        self._progress.hide()
        self._set_busy(False)
        self._result = result
        for button in (self._play, self._show):
            button.setVisible(result is not None)
        if result is None:
            self._logger.warning(f"Playblast failed: {error}")
            self._say(error or "The playblast failed.", "error")
            return
        if not note:
            note = self._size_text(result.stat().st_size) if result.is_file() else ""
        self._say(" · ".join(part for part in (result.name, note, f"{seconds:.1f} s") if part), "done")
        self._status.setToolTip(str(result))
        self._refresh_facts()
        if self._open.isChecked():
            self._open_result(result)

    @staticmethod
    def _size_text(size: int) -> str:
        return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{max(1, size // 1024)} KB"

    @staticmethod
    def _open_result(result: Path | None) -> None:
        if result is not None and result.exists():
            qt.QtGui.QDesktopServices.openUrl(qt.QtCore.QUrl.fromLocalFile(str(result)))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._start_button.setEnabled(not busy)
        self._start_button.setText("Working…" if busy else "Playblast")

    def _say(self, text: str, state: str = "") -> None:
        self._status.setText(text)
        self._status.setToolTip("")
        self._set_state(self._status, state)
