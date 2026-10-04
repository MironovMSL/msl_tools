# tools/desktop/media/panels/__init__.py
"""The settings of the Media tool's actions. Each panel shows the choices in
plain words, remembers them (settings() / apply_settings()), and turns them
into a Job with job(source, output) — the ffmpeg arguments are the recipes'
business (core/media/recipes.py), never the panel's.

    base.py      OptionPanel, SectionHeader, the burn-in rows, shared choices
    sequence.py  To video, Convert frames          (image sequences)
    shrink.py    Make smaller
    trim.py      Trim
    frames.py    To frames
    adjust.py    Adjust
    simple.py    Stamp, Loop, Sound, GIF, For editing, Fit a shape, Contact sheet
    combine.py   Several at once, Join, Compare

PANELS lists them in the order the action picker shows them.
"""
from msl_tools.msl.tools.desktop.media.panels.base import OptionPanel, SectionHeader
from msl_tools.msl.tools.desktop.media.panels.sequence import SequencePanel, ReframePanel
from msl_tools.msl.tools.desktop.media.panels.shrink import ShrinkPanel
from msl_tools.msl.tools.desktop.media.panels.trim import TrimPanel
from msl_tools.msl.tools.desktop.media.panels.frames import FramesPanel
from msl_tools.msl.tools.desktop.media.panels.adjust import AdjustPanel
from msl_tools.msl.tools.desktop.media.panels.simple import (StampPanel, LoopPanel, SoundPanel, GifPanel, EditingPanel,
                                                             FitPanel, SheetPanel)
from msl_tools.msl.tools.desktop.media.panels.combine import ChainPanel, JoinPanel, ComparePanel

PANELS = (SequencePanel, ReframePanel, ShrinkPanel, TrimPanel, LoopPanel, StampPanel, SoundPanel, AdjustPanel,
          FitPanel, GifPanel, FramesPanel, SheetPanel, EditingPanel, ChainPanel, JoinPanel, ComparePanel)
