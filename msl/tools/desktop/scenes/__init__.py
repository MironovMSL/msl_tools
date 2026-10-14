"""Scenes — work on many Maya scenes at once, Maya closed: Render (tools/desktop/batch) and
Paths (tools/desktop/scene_paths) as tabs of one hub tool."""
from __future__ import annotations

from msl_tools.msl.ui.widgets.windows.hub import ToolDescriptor

# Tool ids this one took over: a hub that remembers one of them opens Scenes (run_hub).
REPLACED_TOOL_IDS = ("batch", "scene_paths")


def _page():
    from msl_tools.msl.tools.desktop.scenes.page import ScenesPage  # built when the tool is first opened
    return ScenesPage()


TOOL_DESCRIPTOR = ToolDescriptor(
    id="scenes",
    title="Scenes",
    widget_factory=_page,
    icon="scenes",
    icon_sub_folder="tools",
)
