"""Maya Gate — pick a Maya version and named environment, launch it."""
from __future__ import annotations

from msl_tools.msl.ui.widgets.windows.hub import ToolDescriptor
from msl_tools.msl.tools.desktop.maya_gate.page import MayaGatePage

TOOL_DESCRIPTOR = ToolDescriptor(
    id="maya_gate",
    title="Maya Gate",
    widget_factory=lambda: MayaGatePage(),
)