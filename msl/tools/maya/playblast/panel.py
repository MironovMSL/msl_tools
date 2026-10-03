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
from msl_tools.msl.tools.maya.playblast import capture, mask, naming
from msl_tools.msl.tools.maya.playblast.recent import RecentCard, open_result, size_text
from msl_tools.msl.tools.maya.playblast.visibility_dialog import VisibilityDialog
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.color_swatch_button import ColorSwatchButton
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.editors.token_line_edit import TokenLineEdit
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel
from msl_tools.msl.ui.widgets.atoms.progress.base_progress_bar import BaseProgressBar
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces.stable_scroll_area import StableScrollArea
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.fact_tiles import FactTiles
from msl_tools.msl.ui.workers.result_worker import ResultWorker

StylesheetBuilder.register_template(Path(__file__).with_name("playblast.qss"))

ACTIVE_VIEW = "Active view"
SIZE_RENDER, SIZE_CUSTOM = "Render settings", "Custom"
RANGE_CUSTOM = "Custom"
FORMAT_MP4, FORMAT_FRAMES = "MP4", "Frames"
QUALITY = {"Best": "best", "High": "high", "Good": "good", "Small": "small"}  # the word shown -> core/media's
SHOW_VIEWPORT, SHOW_CUSTOM = "As in the viewport", "Custom"
MASK_TEXT = {"Small": 0.8, "Medium": 1.0, "Large": 1.3}       # the word shown -> the mask's text scale
MASK_BARS = {"Solid": 1.0, "75 %": 0.75, "50 %": 0.5, "None": 0.0}  # ... -> how solid its bars are
# The mask's looks that come with the tool (name -> what a click sets; the switch and the note stay).
MASK_PRESETS = {
    "Review": {"texts": dict(mask.DEFAULT_TEXTS), "text": "Medium", "bars": "Solid",
               "text_color": "#ffffff", "bar_color": "#000000"},
    "Client": {"texts": {"topLeft": "{logo}", "topCenter": "{note}", "topRight": "{date}", "bottomLeft": "{scene}",
                         "bottomCenter": "", "bottomRight": "{timecode}"},
               "text": "Medium", "bars": "75 %", "text_color": "#ffffff", "bar_color": "#000000"},
    "Frames": {"texts": {"topLeft": "", "topCenter": "", "topRight": "", "bottomLeft": "{range}",
                         "bottomCenter": "", "bottomRight": "{counter}"},
               "text": "Small", "bars": "None", "text_color": "#ffffff", "bar_color": "#000000"},
}
# Our own mark: what {logo} draws until another picture is chosen.
BRAND_LOGO = FileSystemManager.icons / "brand" / "watermark.png"
MASK_OPACITY = {"Solid": 1.0, "75 %": 0.75, "50 %": 0.5}             # ... -> how solid its text is
# ... -> the shape of the picture the bars leave between them (0 = the bars keep their own height)
MASK_LETTERBOX = {"Off": 0.0, "2.39:1": 2.39, "2.35:1": 2.35, "2:1": 2.0, "1.85:1": 1.85, "16:9": 16 / 9,
                  "4:3": 4 / 3, "1:1": 1.0}
MASK_DIGITS = ("2", "3", "4", "5", "6")
# every key of a mask's look with its default: a preset saved before a key existed means the default
MASK_LOOK_DEFAULTS = {"text": "Medium", "bars": "Solid", "text_color": "#ffffff", "bar_color": "#000000",
                      "top_bar": True, "bottom_bar": True, "font": "Consolas", "text_opacity": "Solid",
                      "letterbox": "Off", "digits": "4"}
MASK_PLACES = {"topLeft": "top left", "topCenter": "top centre", "topRight": "top right",
               "bottomLeft": "bottom left", "bottomCenter": "bottom centre", "bottomRight": "bottom right"}


def _plain(value):
    """A config node (or anything nested in one) as plain dicts and lists."""
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


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
                "ornaments": False, "show": SHOW_VIEWPORT, "show_custom": list(capture.VISIBILITY_PRESETS["Geometry"]),
                "mask": {"shown": False, "texts": dict(mask.DEFAULT_TEXTS), "text": "Medium", "bars": "Solid",
                         "text_color": "#ffffff", "bar_color": "#000000", "note": "", "warn": True,
                         "top_bar": True, "bottom_bar": True, "logo": ""}}

    _encoding_progressed = qt.QtCore.Signal(float)
    # Running workers, kept by the CLASS and parentless: a docked panel can be closed (and deleted)
    # at any moment, and a QThread destroyed while it runs takes Maya down with it.
    _workers: set = set()

    def __init__(self, parent=None):
        super().__init__(parent)
        config = Resources().configsMayaMng.get_config(self.TOOL_NAME, defaults={"settings": dict(self.DEFAULTS)})
        self._config = config
        self._settings = config["settings"]
        self._logger = Resources().logsMaya.get(self.TOOL_NAME)
        self._tools = None            # FfmpegTools once found
        self._tools_looked = False
        self._busy = False
        self._result: Path | None = None
        self._pending: tuple | None = None   # (target, when it started) of the video being made
        self._capture_job: tuple | None = None   # (settings, target, video) of the capture about to start
        self._capture_started = 0.0
        self._session = None                     # the CaptureSession while Maya draws the frames
        self._cancelled = False
        self._step_timer = qt.QtCore.QTimer(self)
        self._step_timer.setInterval(0)
        self._step_timer.timeout.connect(self._capture_step)
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
        self._visible = BaseComboBox([SHOW_VIEWPORT], SHOW_VIEWPORT)
        self._visible_edit = IconPushButton(icons.get_icon("edit", sub_folder="actions"),
                                         "Choose what the playblast shows, and save it as a preset…")
        self._visible_edit.setFixedSize(24, 22)
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
        hint = "\n\nRight click: put one in where you click."
        self._folder = TokenLineEdit(naming.TOKENS)
        self._folder.setPlaceholderText(naming.DEFAULT_FOLDER)
        self._folder.setToolTip("The folder the playblast goes to. It may hold:\n" + tokens + hint)
        self._browse = IconPushButton(icons.get_icon("browse", sub_folder="actions"), "Choose the folder…")
        self._browse.setFixedSize(24, 22)
        self._name = TokenLineEdit(naming.TOKENS)
        self._name.setPlaceholderText(naming.DEFAULT_NAME)
        self._name.setToolTip("The file's name, without the extension. It may hold:\n" + tokens + hint)
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

        self._mask_on = BaseCheckbox("Show in the viewport")
        self._mask_on.setToolTip("Bars and text over the viewport while you animate — and so in the playblast.\n"
                                 "It is no part of the scene: a saved scene never holds it.\n"
                                 "The first time, Maya asks whether to allow our plug-in that draws it.")
        mask_tokens = "\n".join(f"{{{token}}} — {meaning}" for token, meaning in mask.TOKENS.items())
        self._mask_fields = {}
        for slot, place in MASK_PLACES.items():
            field = TokenLineEdit(mask.TOKENS)
            field.setPlaceholderText(place)
            field.setToolTip(f"The text at the {place} of the frame. A | starts a new line.\n"
                             f"It may hold:\n{mask_tokens}{hint}")
            self._mask_fields[slot] = field
        self._mask_text = BaseComboBox(list(MASK_TEXT), "Medium")
        self._mask_text.setToolTip("The size of the mask's text")
        self._mask_bars = BaseComboBox(list(MASK_BARS), "Solid")
        self._mask_bars.setToolTip("How solid the bars under the text are")
        self._mask_text_color = ColorSwatchButton("#ffffff", "The color of the mask's text")
        self._mask_bar_color = ColorSwatchButton("#000000", "The color of the mask's bars")
        self._mask_font = BaseComboBox(["Consolas"], "Consolas")
        self._mask_font.setToolTip("The font of the mask's text")
        self._mask_font.setMinimumWidth(60)
        self._mask_text_opacity = BaseComboBox(list(MASK_OPACITY), "Solid")
        self._mask_text_opacity.setToolTip("How solid the text (and the logo) is")
        self._mask_letterbox = BaseComboBox(list(MASK_LETTERBOX), "Off")
        self._mask_letterbox.setToolTip("The bars as high as it takes to leave a picture of this shape\n"
                                        "between them — 2.39:1 inside a 16:9 frame, for example.")
        self._mask_digits = BaseComboBox(list(MASK_DIGITS), "4")
        self._mask_digits.setToolTip("How many digits {counter} has: 0042")
        self._mask_top = BaseCheckbox("Top bar")
        self._mask_bottom = BaseCheckbox("Bottom bar")
        self._mask_logo = qt.QtWidgets.QLineEdit()
        self._mask_logo.setPlaceholderText("the msl mark")
        self._mask_logo.setToolTip("The picture a slot shows where it says {logo} (PNG with transparency works best).\n"
                                   "Empty = our own msl mark.")
        self._mask_logo_browse = IconPushButton(UiResources().iconManager.get_icon("browse", sub_folder="actions"),
                                                "Choose a picture…")
        self._mask_logo_browse.setFixedSize(24, 22)
        self._mask_logo_brand = IconPushButton(UiResources().iconManager.get_icon("brand_mark", sub_folder="actions"),
                                               "Back to our own msl mark")
        self._mask_logo_brand.setFixedSize(24, 22)
        self._mask_note = qt.QtWidgets.QLineEdit()
        self._mask_note.setPlaceholderText("what {note} shows: WIP, for review…")
        self._mask_note.setToolTip("A few words about this playblast. A slot shows them where it says {note}.")
        self._mask_warn = BaseCheckbox("Mark frames outside the range")
        self._mask_warn.setToolTip("The slots that show the frame turn red while the current frame is\n"
                                   "outside the range chosen above — a frame the playblast won't take.")
        self._mask_presets = ChipBar(add_text="Save this mask as a preset", name_placeholder="Preset name, then Enter",
                                     add_icon=UiResources().iconManager.get_icon("bookmark_add", sub_folder="actions"))

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
            ("Show", [self._visible, self._visible_edit]),
            ("Size", [self._size, self._width, self._times, self._height]),
            ("Frames", [self._range, self._start, self._dash, self._end]),
        ])
        output = self._card("RESULT", [
            ("Folder", [self._folder, self._browse]),
            ("Name", [self._name]),
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
        column.addWidget(self._mask_card())
        self._recent = RecentCard()
        column.addWidget(self._recent)
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

    def _mask_card(self) -> qt.QtWidgets.QFrame:
        """The shot mask's card: the switch in its heading, the six texts laid out as on the frame."""
        card = qt.QtWidgets.QFrame()
        card.setObjectName("playblastCard")
        heading = qt.QtWidgets.QLabel("SHOT MASK")
        heading.setObjectName("playblastSection")
        top = qt.QtWidgets.QHBoxLayout()
        top.addWidget(heading)
        top.addStretch(1)
        top.addWidget(self._mask_on)
        grid = qt.QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(6)
        for index, slot in enumerate(mask.SLOTS):
            grid.addWidget(self._mask_fields[slot], index // 3, index % 3)
        # caption | controls, one row per thing the mask is made of
        look = qt.QtWidgets.QGridLayout()
        look.setContentsMargins(0, 0, 0, 0)
        look.setHorizontalSpacing(8)
        look.setVerticalSpacing(6)
        look.setColumnStretch(1, 1)
        rows = (("Text", [(self._mask_font, 3), (self._mask_text, 2), (self._mask_text_opacity, 2),
                          (self._mask_text_color, 0)]),
                ("Bars", [(self._mask_bars, 2), (self._mask_letterbox, 2), (self._mask_bar_color, 0)]),
                ("Counter", [(self._mask_digits, 0)]))
        for index, (caption, widgets) in enumerate(rows):
            label = qt.QtWidgets.QLabel(caption)
            label.setObjectName("playblastCaption")
            look.addWidget(label, index, 0)
            line = qt.QtWidgets.QHBoxLayout()
            line.setSpacing(4)
            for widget, stretch in widgets:
                line.addWidget(widget, stretch)
            if caption == "Counter":
                digits = qt.QtWidgets.QLabel("digits")
                digits.setObjectName("playblastHint")
                line.insertWidget(1, digits)
                line.insertStretch(2, 1)
            look.addLayout(line, index, 1)
        note = qt.QtWidgets.QHBoxLayout()
        note.setSpacing(8)
        note_label = qt.QtWidgets.QLabel("Note")
        note_label.setObjectName("playblastCaption")
        note.addWidget(note_label)
        note.addWidget(self._mask_note, 1)
        logo = qt.QtWidgets.QHBoxLayout()
        logo.setSpacing(4)
        logo_label = qt.QtWidgets.QLabel("Logo")
        logo_label.setObjectName("playblastCaption")
        logo.addWidget(logo_label)
        logo.addSpacing(4)
        logo.addWidget(self._mask_logo, 1)
        logo.addWidget(self._mask_logo_browse)
        logo.addWidget(self._mask_logo_brand)
        bars = qt.QtWidgets.QHBoxLayout()
        bars.setSpacing(14)
        bars.addWidget(self._mask_top)
        bars.addWidget(self._mask_bottom)
        bars.addStretch(1)
        box = qt.QtWidgets.QVBoxLayout(card)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        box.addLayout(top)
        box.addWidget(self._mask_presets)
        box.addLayout(grid)
        box.addLayout(look)
        box.addLayout(bars)
        box.addLayout(note)
        box.addLayout(logo)
        box.addWidget(self._mask_warn)
        return card

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
        self._visible.currentTextChanged.connect(self._on_changed)
        self._visible_edit.clicked.connect(self._on_show_edit)
        self._size.currentTextChanged.connect(self._on_size_changed)
        self._range.currentTextChanged.connect(self._on_range_changed)
        for field in (self._width, self._height, self._start, self._end, self._folder, self._name):
            field.textEdited.connect(self._on_changed)
        self._format.current_changed.connect(self._on_changed)
        self._quality.currentTextChanged.connect(self._on_changed)
        for box in (self._sound, self._ornaments, self._overwrite, self._open):
            box.toggled.connect(self._on_changed)
        self._folder.token_inserted.connect(self._on_changed)
        self._name.token_inserted.connect(self._on_changed)
        self._browse.clicked.connect(self._on_browse)
        self._start_button.clicked.connect(self._on_start)
        self._play.clicked.connect(lambda: self._result and open_result(self._result))
        self._show.clicked.connect(lambda: self._result and ProcessLauncher.open_file_explorer(self._result))
        self._encoding_progressed.connect(self._on_encoding_progress)
        self._mask_on.toggled.connect(self._on_mask_toggled)
        for field in self._mask_fields.values():
            field.textEdited.connect(self._on_mask_changed)
            field.token_inserted.connect(self._on_mask_changed)
        self._mask_text.currentTextChanged.connect(self._on_mask_changed)
        self._mask_bars.currentTextChanged.connect(self._on_mask_changed)
        self._mask_text_color.color_changed.connect(self._on_mask_changed)
        self._mask_bar_color.color_changed.connect(self._on_mask_changed)
        self._mask_note.textEdited.connect(self._on_mask_changed)
        self._mask_top.toggled.connect(self._on_mask_changed)
        for combo in (self._mask_font, self._mask_text_opacity, self._mask_letterbox, self._mask_digits):
            combo.currentTextChanged.connect(self._on_mask_changed)
        self._mask_bottom.toggled.connect(self._on_mask_changed)
        self._mask_logo.editingFinished.connect(self._on_mask_changed)
        self._mask_logo_browse.clicked.connect(self._on_mask_logo_browse)
        self._mask_logo_brand.clicked.connect(self._on_mask_logo_brand)
        self._mask_warn.toggled.connect(self._on_mask_changed)
        self._mask_presets.clicked.connect(self._on_mask_preset)
        self._mask_presets.add_requested.connect(self._on_mask_preset_saved)
        self._mask_presets.remove_requested.connect(self._on_mask_preset_removed)

    # ------------------------------------------------------------------ settings

    def _apply_settings(self) -> None:
        """The saved choices onto the controls (without saving them back)."""
        self._loading = True
        get = lambda key: self._settings.get(key, self.DEFAULTS[key])
        self._fill_show(get("show"))
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
        saved = self._settings.get("mask") or {}
        self._apply_mask_look(saved)
        self._mask_note.setText(str(saved.get("note", "")))
        self._mask_logo.setText(str(saved.get("logo", "")))
        self._mask_warn.set_checked_immediate(bool(saved.get("warn", True)))
        self._mask_on.set_checked_immediate(bool(saved.get("shown", False)))
        self._show_mask_presets()
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
                  "show": self._visible.currentText(),
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
        self._load_fonts()
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
        self._sync_mask()
        self._refresh_recent()

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
        self._describe_show()
        if self._mask_on.isChecked():
            self._sync_mask()  # the frame it frames, {resolution} and the range it warns about follow

    def _on_size_changed(self, *_args) -> None:
        if not self._loading:
            self._sync_enabled()
            self.refresh()
            self._save_settings()

    def _on_range_changed(self, *_args) -> None:
        self._on_size_changed()

    # ------------------------------------------------------------------ what the playblast shows

    def _show_presets(self) -> dict:
        """name -> the kinds shown: the built-in presets, then the user's own (a same name replaces)."""
        presets = {name: list(kinds) for name, kinds in capture.VISIBILITY_PRESETS.items()}
        if "show_presets" in self._config.data:
            for name, kinds in _plain(self._config["show_presets"]).items():
                presets[str(name)] = [str(kind) for kind in kinds]
        return presets

    def _own_show_presets(self) -> dict:
        return dict(_plain(self._config["show_presets"])) if "show_presets" in self._config.data else {}

    def _fill_show(self, current: str) -> None:
        loading, self._loading = self._loading, True
        names = [SHOW_VIEWPORT, *self._show_presets(), SHOW_CUSTOM]
        self._visible.clear()
        self._visible.addItems(names)
        self._set_combo(self._visible, current if current in names else SHOW_VIEWPORT)
        self._loading = loading
        self._describe_show()

    def _shown_kinds(self):
        """The kinds the playblast shows, or None = whatever the viewport shows."""
        choice = self._visible.currentText()
        if choice == SHOW_VIEWPORT:
            return None
        if choice == SHOW_CUSTOM:
            return tuple(_plain(self._settings.get("show_custom") or []))
        return tuple(self._show_presets().get(choice, ()))

    def _describe_show(self) -> None:
        kinds = self._shown_kinds()
        if kinds is None:
            text = "The playblast shows what the viewport shows."
        else:
            names = [capture.VISIBILITY_LABELS.get(kind, kind) for kind in kinds]
            text = "The playblast shows only:\n" + (", ".join(names) or "nothing")
        self._visible.setToolTip(text + "\n\nThe viewport itself is put back afterwards.")

    def _on_show_edit(self) -> None:
        choice = self._visible.currentText()
        own = self._own_show_presets()
        kinds = self._shown_kinds()
        if kinds is None:
            try:
                kinds = [kind for kind, shown in capture.visibility_state().items() if shown]
            except capture.CaptureError:
                kinds = []
        answer = VisibilityDialog.ask(self.window(), kinds, preset=choice if choice in own else "",
                                      removable=choice in own)
        if answer is None:
            return
        kinds, name, removed = answer
        if removed:
            own.pop(choice, None)
            self._config["show_presets"] = own
            self._fill_show(SHOW_VIEWPORT)
        elif name and name not in (SHOW_VIEWPORT, SHOW_CUSTOM):
            own[name] = list(kinds)
            self._config["show_presets"] = own
            self._fill_show(name)
        else:
            self._settings["show_custom"] = list(kinds)
            self._fill_show(SHOW_CUSTOM)
        self._on_changed()

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

    # ------------------------------------------------------------------ what was made before

    HISTORY_KEPT = 40   # results remembered, all scenes together
    RECENT_SHOWN = 4    # ... of which the scene's last ones are listed

    def _history(self) -> list:
        try:
            return [dict(entry) for entry in self._config["history"]]
        except (KeyError, TypeError, ValueError):
            return []

    def _remember(self, result: Path, frames: int, camera: str) -> None:
        entry = {"path": str(result), "scene": capture.scene_name() or "untitled", "camera": camera,
                 "frames": int(frames), "time": time.time()}
        kept = [old for old in self._history() if old.get("path") != entry["path"]]
        self._config["history"] = (kept + [entry])[-self.HISTORY_KEPT:]

    def _refresh_recent(self) -> None:
        """The RECENT card: this scene's last playblasts that still exist, newest first."""
        scene = capture.scene_name() or "untitled"
        mine = [entry for entry in self._history()
                if entry.get("scene") == scene and entry.get("path") and Path(entry["path"]).exists()]
        self._recent.show_results(mine[-self.RECENT_SHOWN:][::-1], self._tools)

    # ------------------------------------------------------------------ the shot mask

    def _mask_settings(self) -> mask.MaskSettings:
        """The mask as the controls say it."""
        width, height = self._frame_size()
        start, end = self._frames()
        return mask.MaskSettings(
            texts={slot: field.text() for slot, field in self._mask_fields.items()},
            aspect=width / height if height else 0.0,
            text_scale=MASK_TEXT.get(self._mask_text.currentText(), 1.0),
            bar_opacity=MASK_BARS.get(self._mask_bars.currentText(), 1.0),
            text_color=self._mask_text_color.rgb(), bar_color=self._mask_bar_color.rgb(),
            font=self._mask_font.currentText(),
            text_opacity=MASK_OPACITY.get(self._mask_text_opacity.currentText(), 1.0),
            letterbox=MASK_LETTERBOX.get(self._mask_letterbox.currentText(), 0.0),
            counter_padding=int(self._mask_digits.currentText() or 4),
            top_bar=self._mask_top.isChecked(), bottom_bar=self._mask_bottom.isChecked(),
            logo=self._mask_logo.text().strip() or str(BRAND_LOGO),
            note=self._mask_note.text(), project=Path(capture.project_folder().rstrip("/\\")).name,
            width=width, height=height, warn_range=self._mask_warn.isChecked(), range_start=start, range_end=end)

    def _mask_look(self) -> dict:
        """What a preset keeps: the texts, the sizes, the colors."""
        return {"texts": {slot: field.text() for slot, field in self._mask_fields.items()},
                "text": self._mask_text.currentText(), "bars": self._mask_bars.currentText(),
                "text_color": self._mask_text_color.hex(), "bar_color": self._mask_bar_color.hex(),
                "top_bar": self._mask_top.isChecked(), "bottom_bar": self._mask_bottom.isChecked(),
                "font": self._mask_font.currentText(), "text_opacity": self._mask_text_opacity.currentText(),
                "letterbox": self._mask_letterbox.currentText(), "digits": self._mask_digits.currentText()}

    def _apply_mask_look(self, look) -> None:
        texts = look.get("texts") or mask.DEFAULT_TEXTS
        for slot, field in self._mask_fields.items():
            field.setText(str(texts.get(slot, "")))
        self._set_combo(self._mask_text, look.get("text", "Medium"))
        self._set_combo(self._mask_bars, look.get("bars", "Solid"))
        self._mask_text_color.set_color(str(look.get("text_color", "#ffffff")))
        self._mask_bar_color.set_color(str(look.get("bar_color", "#000000")))
        self._mask_top.set_checked_immediate(bool(look.get("top_bar", True)))
        self._mask_bottom.set_checked_immediate(bool(look.get("bottom_bar", True)))
        font = str(look.get("font", MASK_LOOK_DEFAULTS["font"]))
        if self._mask_font.findText(font) < 0:
            self._mask_font.addItem(font)  # the list of real fonts comes when the panel is shown
        self._set_combo(self._mask_font, font)
        self._set_combo(self._mask_text_opacity, look.get("text_opacity", MASK_LOOK_DEFAULTS["text_opacity"]))
        self._set_combo(self._mask_letterbox, look.get("letterbox", MASK_LOOK_DEFAULTS["letterbox"]))
        self._set_combo(self._mask_digits, look.get("digits", MASK_LOOK_DEFAULTS["digits"]))

    # presets of the mask: the built-in ones until the user saves or removes one, then the config's

    def _mask_preset_list(self) -> list:
        """[(name, look)], in the order shown."""
        # asked of the stored data: reading a key that isn't there gives an empty node, not an error
        if "mask_presets" in self._config.data:
            try:
                return [(str(entry["name"]), _plain(entry["look"])) for entry in self._config["mask_presets"]]
            except (KeyError, TypeError, ValueError):
                pass
        return [(name, dict(look)) for name, look in MASK_PRESETS.items()]

    def _store_mask_presets(self, presets: list) -> None:
        self._config["mask_presets"] = [{"name": name, "look": look} for name, look in presets]
        self._show_mask_presets()

    def _show_mask_presets(self) -> None:
        presets = self._mask_preset_list()
        self._mask_presets.set_chips([(name, name, "") for name, _look in presets],
                                     removable={name for name, _look in presets})
        current = self._mask_look()
        self._mask_presets.set_marked([name for name, look in presets
                                       if dict(MASK_LOOK_DEFAULTS, **look) == current])

    def _on_mask_preset(self, name: str) -> None:
        look = dict(self._mask_preset_list()).get(name)
        if look is None:
            return
        self._loading = True
        self._apply_mask_look(look)
        self._loading = False
        self._on_mask_changed()

    def _on_mask_preset_saved(self, name: str) -> None:
        name = name.strip()
        if not name:
            return
        presets = [(old, look) for old, look in self._mask_preset_list() if old != name]
        self._store_mask_presets(presets + [(name, self._mask_look())])

    def _on_mask_preset_removed(self, name: str) -> None:
        self._store_mask_presets([(old, look) for old, look in self._mask_preset_list() if old != name])

    def _save_mask(self) -> None:
        self._settings["mask"] = dict(self._mask_look(), shown=self._mask_on.isChecked(),
                                      note=self._mask_note.text(), warn=self._mask_warn.isChecked(),
                                      logo=self._mask_logo.text().strip())
        self._show_mask_presets()  # the one that matches what is on screen is outlined

    def _load_fonts(self) -> None:
        """The fonts Maya's viewport can draw, into the list (once; asked of Maya, so not in the constructor)."""
        if self._mask_font.count() > 3:
            return
        current = self._mask_font.currentText()
        names = mask.fonts()
        if current and current not in names:
            names.append(current)
        self._loading = True
        self._mask_font.clear()
        self._mask_font.addItems(names)
        self._set_combo(self._mask_font, current or "Consolas")
        self._loading = False

    def _sync_mask(self) -> None:
        """Makes the viewport match the switch: a new or reopened scene has lost the mask, and the
        frame it frames follows the size chosen above."""
        if self._busy:
            return
        try:
            if self._mask_on.isChecked():
                mask.show(self._mask_settings())
            elif mask.is_shown():
                mask.hide()
        except mask.MaskError as error:
            self._mask_on.set_checked_immediate(False)
            self._save_mask()
            self._say(str(error), "error")

    def _on_mask_toggled(self, *_args) -> None:
        if not self._loading:
            self._save_mask()
            self._sync_mask()

    def _on_mask_changed(self, *_args) -> None:
        if not self._loading:
            self._save_mask()
            if self._mask_on.isChecked():
                self._sync_mask()

    def _on_mask_logo_browse(self) -> None:
        current = self._mask_logo.text().strip() or str(BRAND_LOGO)
        file, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(
            self, "The logo", str(Path(current).parent), "Pictures (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if file:
            self._mask_logo.setText(file)
            self._on_mask_changed()

    def _on_mask_logo_brand(self) -> None:
        self._mask_logo.setText("")
        self._on_mask_changed()

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
        self._refresh_recent()  # pictures need ffmpeg
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
            if self._session is not None:
                self._cancelled = True  # the button reads "Cancel" while Maya draws
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
            camera=capture.ACTIVE_VIEW if chosen == ACTIVE_VIEW else chosen, ornaments=self._ornaments.isChecked(),
            visibility=self._shown_kinds())
        self._set_busy(True)
        self._say("Maya is drawing the frames…")
        # a moment later, so the line above is on screen before Maya takes over (and never
        # processEvents() here: it would run whatever else is waiting in the middle of a click)
        self._capture_job = (settings, target, video)
        qt.QtCore.QTimer.singleShot(60, self._capture)

    def _capture(self) -> None:
        """Maya draws the frames, one per turn of the event loop — the bar moves and Cancel works —,
        then the video is made on a worker."""
        settings, target, video = self._capture_job
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not video and target.is_dir() and self._overwrite.isChecked():
                for old in target.glob(f"{target.name}.*.png"):
                    old.unlink()  # a shorter range must not leave the longer one's last frames behind
            self._session = capture.CaptureSession(settings)
        except (capture.CaptureError, OSError) as error:
            self._capture_failed(str(error))
            return
        self._cancelled = False
        self._capture_started = time.time()
        self._progress.set_progress(0)
        self._progress.show()
        self._start_button.setText("Cancel")
        self._start_button.setEnabled(True)
        self._step_timer.start()

    def _capture_step(self) -> None:
        """One frame (the timer's tick)."""
        session = self._session
        if session is None:
            self._step_timer.stop()
            return
        if self._cancelled:
            self._step_timer.stop()
            session.abort()
            self._capture_failed("Cancelled.")
            return
        try:
            more = session.step()
        except capture.CaptureError as error:
            self._step_timer.stop()
            self._capture_failed(str(error))
            return
        self._progress.set_progress(int(session.done * 100 / session.total))
        self._say(f"Frame {session.done} of {session.total}…")
        if more:
            return
        self._step_timer.stop()
        self._session = None
        self._after_capture(session.finish())

    def _capture_failed(self, message: str) -> None:
        settings, _target, video = self._capture_job
        self._session = None
        if video:
            shutil.rmtree(settings.folder, ignore_errors=True)
        self._finish(None, message)

    def _after_capture(self, shot) -> None:
        _settings, target, video = self._capture_job
        started = self._capture_started
        self._set_busy(True)  # no Cancel any more: the button waits
        if not video:
            self._finish(target, "", f"{shot.frames} frames", time.time() - started, frames=shot.frames,
                         camera=shot.camera)
            return
        self._say("Making the video…")
        self._progress.set_progress(0)
        sound = shot.sound if self._sound.isChecked() and shot.sound and Path(shot.sound).is_file() else None
        quality = QUALITY.get(self._quality.currentText(), "high")
        tools, report = self._tools, self._report_progress
        self._pending = (target, started, shot.frames, shot.camera)
        worker = ResultWorker(lambda: self._encode(tools, shot, target, quality, sound, report))
        worker.done.connect(self._on_encoded)
        worker.failed.connect(self._on_encode_failed)
        self._keep(worker)
        worker.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._session is not None:  # the window was closed in the middle of a capture
            self._step_timer.stop()
            self._session.abort()
            self._capture_failed("Cancelled.")

    def _report_progress(self, fraction: float, _report=None) -> None:
        try:
            self._encoding_progressed.emit(fraction)
        except RuntimeError:
            pass  # the panel was closed meanwhile; the video is finished all the same

    def _on_encoded(self, _result) -> None:
        target, started, frames, camera = self._pending
        self._finish(target, "", "", time.time() - started, frames=frames, camera=camera)

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

    def _finish(self, result: Path | None, error: str, note: str = "", seconds: float = 0.0, frames: int = 0,
                camera: str = "") -> None:
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
            note = size_text(result.stat().st_size) if result.is_file() else ""
        self._say(" · ".join(part for part in (result.name, note, f"{seconds:.1f} s") if part), "done")
        self._status.setToolTip(str(result))
        self._remember(result, frames, camera)
        self._refresh_facts()
        self._refresh_recent()
        if self._open.isChecked():
            open_result(result)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._start_button.setEnabled(not busy)
        self._start_button.setText("Working…" if busy else "Playblast")

    def _say(self, text: str, state: str = "") -> None:
        self._status.setText(text)
        self._status.setToolTip("")
        self._set_state(self._status, state)
