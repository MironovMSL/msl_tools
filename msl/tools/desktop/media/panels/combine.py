# tools/desktop/media/panels/combine.py
"""The actions that take several sources or several actions: Several at once, Join, Dailies, Compare."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, MediaError, chain, compare, dailies, join
from msl_tools.msl.tools.desktop.media.source import MediaSource
from msl_tools.msl.tools.desktop.media.panels.base import NL, OptionPanel, QUALITY_HIGH, _videos
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.editors.token_line_edit import TokenLineEdit


class ChainPanel(OptionPanel):
    """Video -> several things done to it in ONE run: a piece cut out, the frame
    made smaller, burn-ins drawn — each with the settings its own action has.
    One run means one loss of quality instead of one per step, and one wait."""

    KEY, TITLE, BUTTON, TAG = "chain", "Several at once", "Do it all", "_edit"
    ICON, GROUP = "steps", "several"
    TIP = "Cut a piece, make it smaller and stamp it — in one run"
    STEPS = (("trim", "Cut the piece", "the piece picked on Trim"),
             ("shrink", "Make it smaller", "the frame size, quality and codec of Make smaller"),
             ("stamp", "Stamp it", "what Stamp draws on the picture"))
    PRESETS = {"Review cut": {"trim": True, "shrink": True, "stamp": True},
               "Small + stamp": {"trim": False, "shrink": True, "stamp": True}}

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._panels: dict = {}
        self._checks, self._notes = {}, {}
        for key, title, tip in self.STEPS:
            self._checks[key] = self._check(title, True, f"Uses {tip}")
            self._notes[key] = self._note("")
            self._notes[key].setWordWrap(True)  # so the row gives it the room that is left
            self._checks[key].toggled.connect(lambda _checked: self.refresh())
        self._add_row("Steps", self._checks["trim"])
        self._add_row("", self._notes["trim"])
        self._add_row("", self._checks["shrink"])
        self._add_row("", self._notes["shrink"])
        self._add_row("", self._checks["stamp"])
        self._add_row("", self._notes["stamp"])
        self._add_row("", hint="Each step takes its settings from its own action — set them there, come back here.")

    accepts = staticmethod(_videos)

    def bind(self, panels: dict) -> None:
        self._panels = panels
        for key in self._checks:
            if key in panels:
                panels[key].changed.connect(self.refresh)

    def refresh(self) -> None:
        """Says under each step what it will do, from that action's settings."""
        trim_panel, shrink_panel, stamp_panel = (self._panels.get(key) for key in ("trim", "shrink", "stamp"))
        texts = {"trim": trim_panel.summary() if trim_panel else "",
                 "shrink": shrink_panel.summary() if shrink_panel else "",
                 "stamp": stamp_panel._overlay_summary() if stamp_panel else ""}
        for key, note in self._notes.items():
            note.setText(texts[key] if self._checks[key].isChecked() else "not done")

    def set_sources(self, sources: list) -> None:
        self.refresh()

    def job(self, source: MediaSource, output: Path) -> Job:
        if not all(key in self._panels for key in ("trim", "shrink", "stamp")):
            raise MediaError("The steps’ own actions aren’t available.")
        start = end = None
        if self._checks["trim"].isChecked():
            start, end = self._panels["trim"].piece()
        size = self._panels["shrink"].chain_settings()
        if not self._checks["shrink"].isChecked():
            size = {**size, "max_height": 0, "quality": "high"}
        overlays = self._panels["stamp"]._overlays() if self._checks["stamp"].isChecked() else None
        return chain(source.info, output, start=start, end=end, overlays=overlays, **size)

    def settings(self) -> dict:
        return {key: check.isChecked() for key, check in self._checks.items()}

    def apply_settings(self, settings: dict) -> None:
        for key, check in self._checks.items():
            check.set_checked_immediate(bool(settings.get(key, True)))
        self.refresh()


class JoinPanel(OptionPanel):
    """Several videos -> one, in the order they were dropped."""

    KEY, TITLE, BUTTON, TAG, COMBINES = "join", "Join", "Join the videos", "_joined", True
    ICON, GROUP = "merge", "combine"
    TIP = "Put the videos one after another into one"

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._order = qt.QtWidgets.QLabel()
        self._order.setObjectName("mediaHint")
        self._order.setWordWrap(True)
        self._quality = self._switch(QUALITY_HIGH, "High")
        self._add_row("Order", self._order)
        self._add_row("Quality", self._quality)

    @staticmethod
    def accepts(sources: list) -> bool:
        return _videos(sources) and len(sources) >= 2

    def set_sources(self, sources: list) -> None:
        names = "  →  ".join(source.path.name for source in sources)
        note = "" if all(source.info.has_audio for source in sources) else \
            NL + "Not every video has sound: the result will have none."
        sizes = {(source.info.width, source.info.height) for source in sources}
        if len(sizes) > 1:
            first = sources[0].info
            note += NL + f"Their frame sizes differ: all are fitted into the first one’s {first.resolution_text()}."
        self._order.setText(names + note)

    def combined_job(self, sources: list, output: Path) -> Job:
        return join([source.info for source in sources], output, quality=QUALITY_HIGH[self._quality.current()])

    def settings(self) -> dict:
        return {"quality": self._quality.current()}

    def apply_settings(self, settings: dict) -> None:
        self._quality.set_current(str(settings.get("quality", "")), animate=False)


class DailiesPanel(OptionPanel):
    """Several playblasts -> one DAILIES reel: one after another, each with
    its caption ("01 · sh010_anim") burnt in and, if wanted, a black slate
    before it with the caption big; "2 / 5" in the corner. The clips can be
    put in another order here, and each caption typed over; the captions
    come from a pattern ({n} the clip's number, {name} its file's name).
    Clip captions are this reel's, not a setting: they are not kept."""

    KEY, TITLE, BUTTON, TAG, COMBINES = "dailies", "Dailies", "Make the reel", "_dailies", True
    ICON, GROUP = "timeline", "combine"
    TIP = "Playblasts in one reel, a slate and a caption for each"
    SLATES = {"Off": 0.0, "1 s": 1.0, "2 s": 2.0}
    CAPTION_TOKENS = {"n": "the clip's number: 01, 02…", "name": "its file's name"}
    DEFAULT_CAPTION = "{n}  ·  {name}"
    PRESETS = {"Review": {"slate": "1 s", "counter": True, "caption": DEFAULT_CAPTION},
               "Quick": {"slate": "Off", "counter": False, "caption": "{name}"}}
    PREVIEW_FROM_START = True
    PREVIEW_SECONDS = 6.0
    PREVIEW_TIP = "Make the start of the reel — the first slate and clip — and play it"
    COMPARES_SIZE = False
    BUTTON_SIZE = qt.QtCore.QSize(22, 22)

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._sources: list = []
        self._order: list[int] = []        # indices into _sources, in the reel's order
        self._typed: dict[str, str] = {}   # a clip's path -> the caption typed for it
        self._slate = self._switch(self.SLATES, "1 s", "A black card before each clip with its caption")
        self._counter = self._check("“2 / 5” in the corner", True)
        self._caption = TokenLineEdit(self.CAPTION_TOKENS)
        self._caption.setText(self.DEFAULT_CAPTION)
        self._caption.setPlaceholderText(self.DEFAULT_CAPTION)
        self._caption.setToolTip("How each clip is captioned — right click: {n}, {name}")
        self._caption.textChanged.connect(lambda _text: self._refresh_clips())
        self._caption.textChanged.connect(lambda _text: self.changed.emit())
        self._quality = self._switch(QUALITY_HIGH, "High")
        self._clips = qt.QtWidgets.QWidget()
        self._clips.setProperty("grows", True)  # its caption fields take the row's width
        self._clips_layout = qt.QtWidgets.QVBoxLayout(self._clips)
        self._clips_layout.setContentsMargins(0, 0, 0, 0)
        self._clips_layout.setSpacing(4)
        self._note_label = self._note("")
        self._note_label.setWordWrap(True)
        self._add_section("Clips")
        self._add_row("Order", self._clips)
        self._note_row = self._add_row("", self._note_label)
        self._add_section("Look")
        self._add_row("Captions", self._caption)
        self._add_row("Slate", self._slate, self._counter)
        self._add_row("Quality", self._quality)

    @staticmethod
    def accepts(sources: list) -> bool:
        return _videos(sources) and len(sources) >= 2

    def set_sources(self, sources: list) -> None:
        self._sources = list(sources)
        self._order = list(range(len(sources)))
        self._typed = {key: text for key, text in self._typed.items()
                       if any(str(source.path) == key for source in sources)}
        self._refresh_clips()

    def _refresh_note(self) -> None:
        """What the reel will be like that one might not expect: no sound, clips fitted into the first one."""
        sources = [self._sources[index] for index in self._order]
        note = "" if all(source.info.has_audio for source in sources) else \
            "Not every clip has sound: the reel will have none."
        sizes = {(source.info.width, source.info.height) for source in sources}
        if len(sizes) > 1:
            note += (NL if note else "") + (f"Their frame sizes differ: all are fitted into the first one’s "
                                            f"{sources[0].info.resolution_text()}.")
        self._note_label.setText(note)
        self._set_row_visible(self._note_row, bool(note))

    def _caption_for(self, place: int, source) -> str:
        pattern = self._caption.text() or self.DEFAULT_CAPTION
        return pattern.replace("{n}", f"{place + 1:02d}").replace("{name}", source.path.stem)

    def _refresh_clips(self) -> None:
        """One row per clip, in the reel's order: its number, its caption, sooner / later."""
        while self._clips_layout.count():
            widget = self._clips_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for place, index in enumerate(self._order):
            source = self._sources[index]
            row = qt.QtWidgets.QWidget()
            line = qt.QtWidgets.QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(6)
            number = self._note(f"{place + 1:02d}")
            number.setFixedWidth(18)
            field = qt.QtWidgets.QLineEdit(self._typed.get(str(source.path), ""))
            field.setPlaceholderText(self._caption_for(place, source))
            field.setToolTip(f"{source.path}" + NL + "Type to caption this clip differently")
            field.textEdited.connect(lambda text, key=str(source.path): self._on_typed(key, text))
            sooner = GlyphButton("↑", "Sooner in the reel", size=self.BUTTON_SIZE)
            later = GlyphButton("↓", "Later in the reel", size=self.BUTTON_SIZE)
            sooner.setEnabled(place > 0)
            later.setEnabled(place < len(self._order) - 1)
            sooner.clicked.connect(lambda _checked=False, place=place: self._move(place, -1))
            later.clicked.connect(lambda _checked=False, place=place: self._move(place, 1))
            line.addWidget(number)
            line.addWidget(field, 1)
            line.addWidget(sooner)
            line.addWidget(later)
            self._clips_layout.addWidget(row)
        self._refresh_note()

    def _on_typed(self, key: str, text: str) -> None:
        if text.strip():
            self._typed[key] = text
        else:
            self._typed.pop(key, None)
        self.changed.emit()

    def _move(self, place: int, steps: int) -> None:
        target = place + steps
        if 0 <= target < len(self._order):
            self._order[place], self._order[target] = self._order[target], self._order[place]
            self._refresh_clips()
            self.changed.emit()

    def ordered(self, sources: list) -> list:
        """`sources` in the reel's order (as they came, if they aren't the ones shown here)."""
        if [str(source.path) for source in sources] != [str(source.path) for source in self._sources]:
            return list(sources)
        return [sources[index] for index in self._order]

    def combined_job(self, sources: list, output: Path) -> Job:
        clips = self.ordered(sources)
        captions = [self._typed.get(str(source.path), "").strip() or self._caption_for(place, source)
                    for place, source in enumerate(clips)]
        return dailies([source.info for source in clips], output, captions=captions,
                       slate_seconds=self.SLATES.get(self._slate.current(), 1.0), counter=self._counter.isChecked(),
                       quality=QUALITY_HIGH[self._quality.current()])

    def settings(self) -> dict:
        return {"slate": self._slate.current(), "counter": self._counter.isChecked(),
                "caption": self._caption.text(), "quality": self._quality.current()}

    def apply_settings(self, settings: dict) -> None:
        self._slate.set_current(str(settings.get("slate", "")), animate=False)
        self._counter.set_checked_immediate(bool(settings.get("counter", True)))
        if "caption" in settings:
            self._caption.setText(str(settings["caption"]))
        self._quality.set_current(str(settings.get("quality", "")), animate=False)


class ComparePanel(OptionPanel):
    """Two videos -> one picture with both, to compare them frame for frame."""

    KEY, TITLE, BUTTON, TAG, COMBINES = "compare", "Compare", "Create the comparison", "_compare", True
    ICON, GROUP = "split_view", "combine"
    TIP = "Two videos in one picture — before / after"
    SIDE, STACKED = "Side by side", "One above the other"

    def __init__(self, tools=None, parent=None):
        super().__init__(tools, parent)
        self._layout_switch = self._switch([self.SIDE, self.STACKED], self.SIDE)
        self._labels = self._check("Write each file’s name over its half", True)
        self._which = qt.QtWidgets.QLabel()
        self._which.setObjectName("mediaHint")
        self._which.setWordWrap(True)
        self._add_row("Layout", self._layout_switch)
        self._add_row("Names", self._labels)
        self._add_row("", self._which)

    @staticmethod
    def accepts(sources: list) -> bool:
        return _videos(sources) and len(sources) == 2

    def set_sources(self, sources: list) -> None:
        first, second = sources[0], sources[1]
        self._which.setText(f"{first.path.name}  |  {second.path.name} — as long as the shorter one; "
                            f"the sound is the first one’s.")

    def combined_job(self, sources: list, output: Path) -> Job:
        return compare(sources[0].info, sources[1].info, output, stacked=self._layout_switch.current() == self.STACKED,
                       labels=self._labels.isChecked())

    def settings(self) -> dict:
        return {"layout": self._layout_switch.current(), "labels": self._labels.isChecked()}

    def apply_settings(self, settings: dict) -> None:
        self._layout_switch.set_current(str(settings.get("layout", "")), animate=False)
        self._labels.set_checked_immediate(bool(settings.get("labels", True)))
