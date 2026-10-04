# tools/desktop/media/panels/combine.py
"""The actions that take several sources or several actions: Several at once, Join, Compare."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import Job, MediaError, chain, compare, join
from msl_tools.msl.tools.desktop.media.source import MediaSource
from msl_tools.msl.tools.desktop.media.panels.base import NL, OptionPanel, QUALITY_HIGH, _videos


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
