# tools/desktop/media/panels/base.py
"""What every panel is made of: OptionPanel, SectionHeader, the burn-in rows (_OverlayRows) and the
choices several panels share."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, Overlays, default_output
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES, MediaSource
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
