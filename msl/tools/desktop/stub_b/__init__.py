"""Placeholder tool B — exists only to test hub navigation."""

from msl_tools.msl.ui.widgets.windows.hub import ToolDescriptor
from msl_tools.msl.tools.desktop._stub_widget import StubToolWidget

TOOL_DESCRIPTOR = ToolDescriptor(
    id="stub_b",
    title="Stub B",
    widget_factory=lambda: StubToolWidget("Stub tool B"),
)