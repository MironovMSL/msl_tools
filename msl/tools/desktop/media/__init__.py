"""Media — quick work with video and image sequences through ffmpeg."""
from __future__ import annotations

from msl_tools.msl.ui.widgets.windows.hub import ToolDescriptor


def _page():
    from msl_tools.msl.tools.desktop.media.page import MediaPage  # built when the tool is first opened
    return MediaPage()


TOOL_DESCRIPTOR = ToolDescriptor(
    id="media",
    title="Media",
    widget_factory=_page,
    icon="media",
    icon_sub_folder="tools",
)
