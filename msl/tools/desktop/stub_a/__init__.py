"""Placeholder tool A — exists only to test hub navigation."""

from msl_tools.msl.ui.widgets.windows.hub import ToolDescriptor
from msl_tools.msl.tools.desktop._stub_widget import StubToolWidget

TOOL_DESCRIPTOR = ToolDescriptor(
    id="stub_a",
    title="Stub A",
    widget_factory=lambda: StubToolWidget("Stub tool A"),
    icon="maya1",
    icon_sub_folder="apps",
)