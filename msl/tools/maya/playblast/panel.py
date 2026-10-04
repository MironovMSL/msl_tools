# tools/maya/playblast/panel.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.playblast import capture, mask, naming
from msl_tools.msl.tools.maya.playblast.ending import LIGHT_MB, RunEnding
from msl_tools.msl.tools.maya.playblast.panel_share import _ShareMixin
from msl_tools.msl.tools.maya.playblast.mask_preview import MaskPreview
from msl_tools.msl.tools.maya.playblast.recent import RecentCard
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.color_swatch_button import ColorSwatchButton
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
from msl_tools.msl.tools.maya.playblast.panel_tables import (
    ACTIVE_VIEW, BACKGROUNDS, CODECS, FORMAT_FRAMES, FORMAT_MOV, FORMAT_MP4, MASK_BARS, MASK_DIGITS, MASK_LETTERBOX,
    MASK_OPACITY, MASK_PLACES, MASK_TEXT, OVERSCAN, QUALITY, RANGE_CUSTOM, SHOW_VIEWPORT, SIZE_CUSTOM, SIZE_RENDER,
    VIDEO_FORMATS, _plain)
from msl_tools.msl.tools.maya.playblast.panel_cards import _Card, _Toggle
from msl_tools.msl.tools.maya.playblast.panel_mask import _MaskMixin
from msl_tools.msl.tools.maya.playblast.panel_presets import _PresetsMixin
from msl_tools.msl.tools.maya.playblast.panel_run import _RunMixin


StylesheetBuilder.register_template(Path(__file__).with_name("playblast.qss"))


class PlayblastPanel(_ShareMixin, _MaskMixin, _PresetsMixin, _RunMixin, qt.QtWidgets.QWidget):
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
                "copy": False, "light": False, "smooth": False, "background": "Viewport", "overscan": "Off",
                "codec": "H.264", "gpu": False, "occlusion": False, "cameras": [],
                "folded": {"picture": False, "result": False},
                "ornaments": False, "show": SHOW_VIEWPORT, "show_custom": list(capture.VISIBILITY_PRESETS["Geometry"]),
                "mask": {"shown": False, "texts": dict(mask.DEFAULT_TEXTS), "text": "Medium", "bars": "Solid",
                         "text_color": "#ffffff", "bar_color": "#000000", "note": "", "warn": True,
                         "top_bar": True, "bottom_bar": True, "logo": "", "open": False}}

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
        self._session = None                     # the CaptureSession while Maya draws the frames
        self._tools_known = False                # ffmpeg was looked for (found or not)
        self._queue: list = []                   # the cameras still to shoot in this run
        self._run: dict | None = None            # the capture going on now
        self._capture_camera = None              # its camera ("" = the active view), for the tokens
        self._encoding: set = set()              # ids of this panel's runs whose video is being made
        self._mask_applied = None                # the MaskSettings last put into the viewport
        self._recent_scene = None                # the scene the RECENT card was filled for
        self._run_number = 0
        self._start_when_ready = False           # start() came before that
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
        self._presets = ChipBar(add_text="Save all of these settings as a preset",
                                name_placeholder="Preset name, then Enter",
                                add_icon=icons.get_icon("bookmark_add", sub_folder="actions"))
        self._presets.setToolTip("Presets of the whole playblast: size, what it shows, the result, the mask.\n"
                                 "Right click one of your own to remove it.")
        self._facts = FactTiles()
        self._facts.set_clickable({"camera", "frames", "long", "scene", "fps"})
        self._start_text = "Playblast"

        self._camera = BaseComboBox([ACTIVE_VIEW], ACTIVE_VIEW)
        self._camera.setToolTip("The camera the playblast is seen through.\n"
                                "The viewport gets its own camera back afterwards.")
        self._cameras_button = IconPushButton(icons.get_icon("select_all", sub_folder="actions"),
                                              "Several cameras in one go: a playblast of each…")
        self._cameras_button.setFixedSize(24, 22)
        self._visible = BaseComboBox([SHOW_VIEWPORT], SHOW_VIEWPORT)
        self._visible_edit = IconPushButton(icons.get_icon("edit", sub_folder="actions"),
                                         "Choose what the playblast shows, and save it as a preset…")
        self._visible_edit.setFixedSize(24, 22)
        self._size = BaseComboBox([SIZE_RENDER, *capture.RESOLUTIONS, SIZE_CUSTOM], "HD 1080")
        self._width, self._height = self._number_field(4), self._number_field(4)
        self._times = qt.QtWidgets.QLabel("×")
        self._times.setObjectName("playblastHint")
        self._range = BaseComboBox([capture.RANGE_PLAYBACK, capture.RANGE_ANIMATION, capture.RANGE_RENDER,
                                    capture.RANGE_SELECTED, RANGE_CUSTOM], capture.RANGE_PLAYBACK)
        self._range.setToolTip("Playback: the range slider's frames.\nAnimation: the whole timeline.\n"
                               "Render: the frames of the render settings.\n"
                               "Selected: the frames highlighted on the timeline (Shift + drag there).")
        self._smooth = _Toggle("Smooth edges", "smooth",
                               "Anti-aliasing switched on for the playblast (the viewport gets its own back).")
        self._occlusion = _Toggle("Occlusion", "shade",
                                  "Ambient occlusion switched on for the playblast — soft contact shadows\n"
                                  "(the viewport gets its own back).")
        self._start, self._end = self._number_field(6, signed=True), self._number_field(6, signed=True)
        self._background = SegmentedControl(list(BACKGROUNDS), "Viewport")
        self._background.setToolTip("The background of the playblast.\nViewport: as the viewport shows it "
                                    "(often a gradient).\nGray / Black: one even color — calmer, smaller files.\n"
                                    "Maya's own background is put back afterwards.")
        self._overscan = BaseComboBox(list(OVERSCAN), "Off")
        self._overscan.setToolTip("Room around the frame: the picture shows that much more past its edges,\n"
                                  "for notes on the composition. The shot mask marks the frame's edge.\n"
                                  "The camera's own overscan is put back afterwards.")
        self._still = IconPushButton(icons.get_icon("still", sub_folder="actions"),
                                     "Preview this frame: one picture with the size, background, overscan\n"
                                     "and shot mask chosen here — before the whole playblast")
        self._still.setFixedSize(24, 22)
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

        self._format = SegmentedControl([FORMAT_MP4, FORMAT_MOV, FORMAT_FRAMES], FORMAT_MP4)
        self._format.setToolTip("MP4: a video for watching and sending, with the timeline's sound.\n"
                                "MOV: ProRes 422 — a big file that keeps the picture, for editing.\n"
                                "Frames: PNG pictures in a folder.")
        self._codec = BaseComboBox(list(CODECS), "H.264")
        self._codec.setToolTip("H.264: plays everywhere.\nH.265: about half the size at the same look; "
                               "some older players can't play it.")
        self._gpu = _Toggle("Graphics card", "gpu", "The MP4 is made on the graphics card (NVIDIA): much faster,\n"
                                                    "a somewhat bigger file for the same look.")
        self._gpu.hide()  # shown once this ffmpeg was seen encoding on the card here
        self._quality = BaseComboBox(list(QUALITY), "High")
        self._sound = _Toggle("Sound", "volume", "The sound shown on the timeline goes under the video.")
        self._ornaments = _Toggle("Viewport HUD", "hud",
                                  "Keep the viewport's own overlays (heads-up display, axis) in the picture.")
        self._overwrite = _Toggle("Overwrite", "save", "On: a playblast of the same name is replaced.\n"
                                                       "Off: the new one gets a number — name_2, name_3…")
        self._open = _Toggle("Open when done", "play", "The finished playblast opens in the system's player.")
        self._copy = _Toggle("Copy file", "copy", "The finished playblast is put on the clipboard as a FILE:\n"
                                                  "Ctrl+V pastes it into a chat or a folder.")
        self._light = _Toggle("Light copy", "compress",
                              f"After each video playblast, a copy for a chat next to it: at most {LIGHT_MB:g} MB "
                              f"and 720p,\n<name>_light.mp4. With “Copy file” on, the light copy goes on the "
                              f"clipboard.")

        self._mask_on = BaseCheckbox("In the viewport")
        self._mask_on.setToolTip("Bars and text over the viewport while you animate — and so in the playblast.\n"
                                 "It is no part of the scene: a saved scene never holds it.\n"
                                 "The first time, Maya asks whether to allow our plug-in that draws it.")
        mask_tokens = "\n".join(f"{{{token}}} — {meaning}" for token, meaning in mask.TOKENS.items())
        # the six texts: a sketch of the frame to pick a slot in, one field to write the picked one
        self._mask_texts = dict(mask.DEFAULT_TEXTS)
        self._mask_slot = "topLeft"
        self._mask_preview = MaskPreview()
        self._mask_preview.setToolTip("The mask, roughly as it will look. Click a slot to write its text below.")
        self._mask_slot_label = qt.QtWidgets.QLabel(MASK_PLACES["topLeft"])
        self._mask_slot_label.setObjectName("playblastCaption")
        self._mask_slot_label.setFixedWidth(84)
        self._mask_safe_action = _Toggle("Action safe", "safe_frame",
                                         "A thin frame at 90 % of the picture: what a screen surely shows.")
        self._mask_safe_title = _Toggle("Title safe", "text_frame",
                                        "A dashed frame at 80 % of the picture: where text is safe to put.")
        self._mask_outside = _Toggle("Cover outside the picture", "crop",
                                     "The viewport outside what the playblast takes is covered in the bars'\n"
                                     "color — the camera's own film gate may have another shape. With overscan\n"
                                     "the room around the frame stays: it is in the picture.")
        self._mask_attr = IconPushButton(icons.get_icon("attribute", sub_folder="actions"),
                                         "Put in the value of an attribute: select a control, then the attribute\n"
                                         "in the Channel Box, then click — {attr:ctrl.stretch} shows its value on "
                                         "every frame")
        self._mask_attr.setFixedSize(24, 22)
        self._mask_edit = TokenLineEdit(mask.TOKENS)
        self._mask_edit.setPlaceholderText("nothing here — right click for the tokens")
        self._mask_edit.setToolTip(f"The text of the picked slot. A | starts a new line.\n"
                                   f"It may hold:\n{mask_tokens}{hint}")
        self._mask_chevron = TintedIcon(icons.get_icon("chevron_right", sub_folder="actions"), 10)
        self._mask_summary = ElidedLabel("", qt.QtCore.Qt.TextElideMode.ElideRight)
        self._mask_summary.setObjectName("playblastHint")
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
        self._mask_top = _Toggle("", "bar_top", "The bar along the top (its texts stay without it)")
        self._mask_bottom = _Toggle("", "bar_bottom", "The bar along the bottom (its texts stay without it)")
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

        picture = self._picture_card = self._card("PICTURE", "film", extras=[self._smooth, self._occlusion], rows=[
            (("camera", "Camera"), [self._camera, self._cameras_button]),
            (("eye", "What it shows"), [self._visible, self._visible_edit]),
            (("frame_fit", "Size"), [self._size, self._width, self._times, self._height]),
            (("film", "Frames"), [self._range, self._start, self._dash, self._end, self._still]),
            (("background", "Background"), [self._background]),
            (("overscan", "Room around the frame (overscan)"), [self._overscan]),
        ])
        output = self._result_card = self._card("RESULT", "save", extras=[self._sound, self._ornaments, self._overwrite, self._open,
                                                      self._copy, self._light, self._gpu], rows=[
            ("Folder", [self._folder, self._browse]),
            ("Name", [self._name]),
            ("", [self._path]),
            ("Format", [self._format, self._quality, self._codec]),
        ])

        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(10, 10, 4, 6)
        column.setSpacing(8)
        column.addWidget(self._title_row)
        column.addWidget(self._facts)
        column.addWidget(self._presets)
        column.addWidget(picture)
        column.addWidget(output)
        column.addWidget(self._mask_card())
        self._recent = RecentCard()
        column.addWidget(self._recent)
        column.addStretch(1)
        scroll = StableScrollArea()
        scroll.setObjectName("playblastScroll")
        scroll.setWidget(body)

        foot = qt.QtWidgets.QVBoxLayout()
        foot.setContentsMargins(10, 0, 10, 10)
        foot.setSpacing(6)
        foot.addWidget(self._status)
        foot.addWidget(self._progress)
        foot.addWidget(self._start_button)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(scroll, 1)
        layout.addLayout(foot)

    def eventFilter(self, watched, event) -> bool:
        if (watched is getattr(self, "_mask_header", None)
                and event.type() == qt.QtCore.QEvent.Type.MouseButtonRelease
                and event.button() == qt.QtCore.Qt.MouseButton.LeftButton):
            self._set_mask_open(not self._mask_body.isVisibleTo(self._mask_body.parentWidget()))
            return True
        return super().eventFilter(watched, event)

    def detach_title(self) -> qt.QtWidgets.QLabel:
        """For a window whose own header names the tool: the panel's title row goes away, and
        the one live thing in it — the "ffmpeg 8.0" note — is handed over to be put there."""
        self._ffmpeg_note.setParent(None)
        self._title_row.hide()
        return self._ffmpeg_note

    @staticmethod
    def _card(title: str, icon: str, rows: list, extras=()) -> _Card:
        """A card that folds: caption / controls rows under its heading. A caption is a word, or
        (icon, what it is) — then the icon stands for the word, which is its tooltip. `extras`: small
        widgets at the end of the heading (the card's yes / no choices)."""
        icons = UiResources().iconManager
        card = _Card(title, icon, extras)
        form = qt.QtWidgets.QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 1)
        for index, (caption, widgets) in enumerate(rows):
            if isinstance(caption, tuple):
                label = TintedIcon(icons.get_icon(caption[0], sub_folder="actions"), 14)
                label.setObjectName("playblastRowIcon")
                label.setToolTip(caption[1])
                form.addWidget(label, index, 0)
            elif caption:
                label = qt.QtWidgets.QLabel(caption)
                label.setObjectName("playblastCaption")
                form.addWidget(label, index, 0)
            line = qt.QtWidgets.QHBoxLayout()
            line.setSpacing(4)
            for position, widget in enumerate(widgets):
                line.addWidget(widget, 1 if position == 0 else 0)
            form.addLayout(line, index, 1)
        card.body_layout.addLayout(form)
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
        self._background.current_changed.connect(self._on_changed)
        self._overscan.currentTextChanged.connect(self._on_changed)
        self._codec.currentTextChanged.connect(self._on_changed)
        self._gpu.toggled.connect(self._on_changed)
        self._still.clicked.connect(self._on_preview_frame)
        self._quality.currentTextChanged.connect(self._on_changed)
        for box in (self._sound, self._ornaments, self._overwrite, self._open, self._copy, self._light,
                    self._smooth, self._occlusion):
            box.toggled.connect(self._on_changed)
        self._folder.token_inserted.connect(self._on_changed)
        self._name.token_inserted.connect(self._on_changed)
        self._browse.clicked.connect(self._on_browse)
        self._start_button.clicked.connect(self._on_start)
        self._facts.clicked.connect(self._on_fact_clicked)
        self._presets.clicked.connect(self._on_preset)
        self._presets.add_requested.connect(self._on_preset_saved)
        self._presets.remove_requested.connect(self._on_preset_removed)
        self._cameras_button.clicked.connect(self._on_cameras_menu)
        self._picture_card.toggled.connect(self._on_card_folded)
        self._result_card.toggled.connect(self._on_card_folded)
        self._recent.clear_requested.connect(self._on_recent_clear)
        self._recent.action_requested.connect(self._on_recent_action)
        RunEnding.instance().side_done.connect(self._on_side_done)
        # The end of a run lives outside the panel (ending.py): the panel may be closed before
        # its video is made. Bound methods: the connections go with the panel.
        RunEnding.instance().ended.connect(self._on_run_ended)
        RunEnding.instance().progressed.connect(self._on_encoding_progress)
        self._mask_on.toggled.connect(self._on_mask_toggled)
        self._mask_preview.slot_picked.connect(self._select_mask_slot)
        self._mask_edit.textEdited.connect(self._on_mask_edit)
        self._mask_attr.clicked.connect(self._on_insert_attribute)
        for box in (self._mask_safe_action, self._mask_safe_title, self._mask_outside):
            box.toggled.connect(self._on_mask_changed)
        self._mask_edit.token_inserted.connect(self._on_mask_edit)
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
        folded = _plain(get("folded")) or {}
        self._picture_card.set_open(not folded.get("picture", False))
        self._result_card.set_open(not folded.get("result", False))
        self._set_combo(self._size, get("size"))
        self._set_combo(self._range, get("range"))
        self._width.setText(str(get("width")))
        self._height.setText(str(get("height")))
        self._start.setText(str(get("start")))
        self._end.setText(str(get("end")))
        self._folder.setText(get("folder"))
        self._name.setText(get("name"))
        self._format.set_current(get("format") if get("format") in self._format.options() else FORMAT_MP4, animate=False)
        self._background.set_current(get("background") if get("background") in BACKGROUNDS else "Viewport",
                                     animate=False)
        self._set_combo(self._overscan, get("overscan") if get("overscan") in OVERSCAN else "Off")
        self._set_combo(self._codec, get("codec") if get("codec") in CODECS else "H.264")
        self._gpu.set_checked_immediate(bool(get("gpu")))
        self._set_combo(self._quality, get("quality"))
        for box, key in ((self._sound, "sound"), (self._ornaments, "ornaments"), (self._overwrite, "overwrite"),
                         (self._open, "open"), (self._copy, "copy"), (self._light, "light"),
                         (self._smooth, "smooth"),
                         (self._occlusion, "occlusion")):
            box.set_checked_immediate(bool(get(key)))
        saved = self._settings.get("mask") or {}
        self._apply_mask_look(saved)
        self._mask_note.setText(str(saved.get("note", "")))
        self._mask_logo.setText(str(saved.get("logo", "")))
        self._mask_warn.set_checked_immediate(bool(saved.get("warn", True)))
        self._mask_on.set_checked_immediate(bool(saved.get("shown", False)))
        self._show_mask_presets()
        self._set_mask_open(bool(saved.get("open", False)), save=False)
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
                  "open": self._open.isChecked(), "copy": self._copy.isChecked(),
                  "light": self._light.isChecked(), "background": self._background.current(),
                  "overscan": self._overscan.currentText(), "codec": self._codec.currentText(),
                  "gpu": self._gpu.isChecked(),
                  "smooth": self._smooth.isChecked(), "occlusion": self._occlusion.isChecked()}
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
        video = self._format.current() in VIDEO_FORMATS
        mp4 = self._format.current() == FORMAT_MP4
        self._quality.setEnabled(mp4)  # ProRes has one quality
        self._codec.setVisible(mp4)
        self._gpu.setEnabled(mp4)
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
            self._sweep_old_frames()

    FRAMES_KEPT_HOURS = 12  # temporary frames of a capture this old belong to no run any more

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
        self._refresh_mask_preview()
        self._mark_presets()
        if capture.scene_path() != self._recent_scene:  # refresh() runs on every pointer enter:
            self._refresh_recent()                      # the files are checked when the scene changed

    def _refresh_facts(self) -> None:
        start, end = self._frames()
        fps = capture.frame_rate()
        frames = max(0, end - start + 1)
        sound, _frame = capture.timeline_sound()
        pairs = [(capture.scene_name() or "untitled", "scene"), (f"{fps:g}", "fps"),
                 (f"{frames}", "frames"), (self._seconds_text(frames / fps if fps else 0.0), "long"),
                 (self._camera_name(), "camera")]
        several = self._several_cameras()
        if several:
            pairs[-1] = (f"{len(several)} cameras", "camera")
        self._camera.setEnabled(not several)
        self._camera.setToolTip(("A playblast of each of: " + ", ".join(several) + ".\nThe button beside changes that.")
                                if several else
                                "The camera the playblast is seen through.\n"
                                "The viewport gets its own camera back afterwards.")
        self._cameras_button.setProperty("primary", bool(several))
        repolish(self._cameras_button)
        if sound:
            pairs.append((Path(sound).name, "sound"))
        self._facts.set_pairs(pairs)
        width, height = self._frame_size()
        self._start_text = (f"Playblast  ·  {frames} frames  ·  {width}×{height}"
                            + (f"  ·  {len(several)} cameras" if several else ""))
        size_name = self._size.currentText()
        self._picture_card.set_summary("  ·  ".join(
            [f"{len(several)} cameras" if several else self._camera_name(), self._visible.currentText(),
             size_name if size_name != SIZE_CUSTOM else f"{width}×{height}",
             f"{start}–{end}"]))
        self._result_card.set_summary("  ·  ".join(
            [self._folder.text().strip() or naming.DEFAULT_FOLDER, self._name_template(), self._format.current()]))
        if not self._busy:
            self._start_button.setText(self._start_text)
        path = self._output_path()
        latest = self._latest_path()
        self._path.setText(str(path) if latest is None else f"{path}   + {latest.name}")
        self._path.setToolTip(str(path) if latest is None else
                              f"{path}\n\nand, always the latest, without a version:\n{latest}")

    @staticmethod
    def _seconds_text(seconds: float) -> str:
        return f"{int(seconds // 60)}:{seconds % 60:04.1f}"

    def _camera_name(self) -> str:
        """The camera a playblast is (or would be) seen through — while one is being taken, that one's."""
        chosen = self._capture_camera if self._capture_camera is not None else self._one_camera()
        return chosen or capture.active_camera() or "camera"

    def _one_camera(self) -> str:
        """The camera the list says ("" = the active view)."""
        chosen = self._camera.currentText()
        return "" if chosen == ACTIVE_VIEW or chosen not in capture.cameras() else chosen

    def _several_cameras(self) -> list:
        """The cameras ticked for "several in one go" that are still in the scene (fewer than two: none)."""
        existing = capture.cameras()
        ticked = [name for name in _plain(self._settings.get("cameras") or []) if name in existing]
        return ticked if len(ticked) >= 2 else []

    def _on_cameras_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        ticked = set(_plain(self._settings.get("cameras") or []))
        for name in capture.cameras():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name in ticked)
            action.toggled.connect(lambda checked, camera=name: self._tick_camera(camera, checked))
        menu.addSeparator()
        menu.addAction("One camera only").triggered.connect(lambda: self._set_cameras([]))
        menu.exec(self._cameras_button.mapToGlobal(qt.QtCore.QPoint(0, self._cameras_button.height() + 2)))

    def _tick_camera(self, camera: str, checked: bool) -> None:
        ticked = [name for name in _plain(self._settings.get("cameras") or []) if name != camera]
        self._set_cameras(ticked + [camera] if checked else ticked)

    def _set_cameras(self, cameras: list) -> None:
        self._settings["cameras"] = list(cameras)
        self.refresh()

    def _on_card_folded(self, *_args) -> None:
        self._settings["folded"] = {"picture": not self._picture_card.is_open(),
                                    "result": not self._result_card.is_open()}

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

    def _token_values(self) -> dict:
        return naming.token_values(capture.project_folder(), capture.scene_name(), self._camera_name(),
                                   scene_folder=capture.scene_folder())

    def _keeps_latest(self) -> bool:
        """The folder says {work+}: versions in the work folder, and one copy without a version —
        always the latest — one folder up."""
        return naming.WORK_LATEST_TOKEN in self._folder.text()

    def _name_template(self) -> str:
        """The name as written — with {work+} a version is part of it even if nobody wrote one."""
        name = self._name.text().strip() or naming.DEFAULT_NAME
        if self._several_cameras() and "{camera}" not in name:
            name += "_{camera}"  # one file per camera: the camera is part of the name, written or not
        if self._keeps_latest() and naming.VERSION_TOKEN not in name:
            name += "_" + naming.VERSION_TOKEN
        return name

    def _output_path(self) -> Path:
        """Where the playblast would go with what is on screen: the video's file, or the frames' folder."""
        values = self._token_values()
        suffix = VIDEO_FORMATS[self._format.current()][1] if self._format.current() in VIDEO_FORMATS else ""
        name = self._name_template()
        if naming.VERSION_TOKEN in name:
            # the next version — or, replacing, the last one
            values["version"] = naming.version_for(self._folder.text(), name, values, suffix,
                                                   reuse=self._overwrite.isChecked())
        return naming.output_path(self._folder.text(), name, values, suffix)

    def _latest_path(self) -> Path | None:
        """With {work+}: where the copy without a version goes (None without it)."""
        if not self._keeps_latest():
            return None
        values = self._token_values()
        suffix = VIDEO_FORMATS[self._format.current()][1] if self._format.current() in VIDEO_FORMATS else ""
        folder = str(Path(values["work"]).parent)
        return naming.output_path(folder, naming.without_version(self._name_template()), values, suffix)

    # ------------------------------------------------------------------ what the user does

    def _on_changed(self, *_args) -> None:
        if self._loading:
            return
        self._sync_enabled()
        self._save_settings()
        self._refresh_facts()
        self._describe_show()
        self._mark_presets()
        if self._mask_on.isChecked():
            self._sync_mask()  # the frame it frames, {resolution} and the range it warns about follow

    def _on_size_changed(self, *_args) -> None:
        if not self._loading:
            self._sync_enabled()
            self.refresh()
            self._save_settings()

    def _on_range_changed(self, *_args) -> None:
        self._on_size_changed()

    # ------------------------------------------------------------------ what was made before

    RECENT_SHOWN = 4    # ... of which the scene's last ones are listed

    def _on_fact_clicked(self, caption: str) -> None:
        """A fact on top is a way in to the setting it shows."""
        if caption == "scene":
            scene = capture.scene_path()
            if scene:
                ProcessLauncher.open_file_explorer(scene)  # the scene file, shown in its folder
            else:
                self._say("The scene isn’t saved yet — there is no folder to show.")
            return
        if caption == "fps":
            self._on_fps_menu()
            return
        if caption == "camera" and self._several_cameras():
            self._on_cameras_menu()
            return
        card = self._picture_card
        if not card.is_open():
            card.set_open(True)
            self._on_card_folded()
        combo = self._camera if caption == "camera" else self._range
        combo.setFocus()
        combo.showPopup()

    def _on_fps_menu(self) -> None:
        """The scene's frame rate, picked from the usual ones."""
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        current = f"{capture.frame_rate():g}"
        for label in capture.FRAME_RATES:
            action = menu.addAction(f"{label} fps")
            action.setCheckable(True)
            action.setChecked(f"{float(label):g}" == current)
            action.triggered.connect(lambda _checked=False, rate=label: self._set_fps(rate))
        menu.exec(qt.QtGui.QCursor.pos())

    def _set_fps(self, label: str) -> None:
        try:
            capture.set_frame_rate(label)
        except RuntimeError as error:
            self._say(f"Maya didn’t take {label} fps: {str(error).strip()}", "error")
            return
        self.refresh()

    def _say(self, text: str, state: str = "") -> None:
        self._status.setText(text)
        self._status.setToolTip("")
        self._set_state(self._status, state)
