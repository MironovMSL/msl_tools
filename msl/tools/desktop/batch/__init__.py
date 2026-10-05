"""Batch — Maya scenes rendered one after another, without anyone opening Maya."""
from __future__ import annotations

from msl_tools.msl.ui.widgets.windows.hub import ToolDescriptor


def _page():
    from msl_tools.msl.tools.desktop.batch.page import BatchPage  # built when the tool is first opened
    return BatchPage()


TOOL_DESCRIPTOR = ToolDescriptor(
    id="batch",
    title="Batch",
    widget_factory=_page,
    icon="batch",
    icon_sub_folder="tools",
)
