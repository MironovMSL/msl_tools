"""Hub window: lists tools in a sidebar and shows the selected tool's page
in a content area.
"""
from __future__ import annotations

from typing import Dict, Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog

from .tool_descriptor import ToolDescriptor


class HubWindow(FramelessDialog):
    """Top-level window that hosts a set of tools behind a sidebar.

    Built on FramelessDialog: only needs a title bar and a single content
    area (add_widget()), not FramelessMainWindow's extra setMenuBar()/
    addToolBar()/setStatusBar() surface.

    Sidebar uses plain QPushButton entries for now — BaseNavButton is
    built for the header's icon-only row and doesn't draw text, so it
    isn't a direct fit for a labeled vertical list without a subclass.

    Args:
        tools: Descriptors for every tool the hub should list, in order.
        title: Window title shown in the frameless chrome.
        resources: Theme/icon composition root, forwarded to
            FramelessDialog. Defaults to a new UiResources() if omitted.
        parent: Optional parent widget.
    """

    def __init__(self,
                 tools: Sequence[ToolDescriptor],
                 title: str = "MSL Tools",
                 resources: UiResources | None = None,
                 parent=None) -> None:
        # A standalone desktop app: keep the window opaque when unfocused (header still dims).
        super().__init__(title=title, width=900, height=600, fade_when_inactive=False,
                         resources=resources, parent=parent)

        self._pages: Dict[str, qt.QtWidgets.QWidget] = {}

        body = qt.QtWidgets.QWidget()
        body_layout = qt.QtWidgets.QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        self._sidebar_layout = qt.QtWidgets.QVBoxLayout()
        self._sidebar_layout.addStretch(1)
        self._stack = qt.QtWidgets.QStackedWidget()

        body_layout.addLayout(self._sidebar_layout)
        body_layout.addWidget(self._stack, 1)

        self.add_widget(body)

        for descriptor in tools:
            self._add_tool_button(descriptor)

    def _add_tool_button(self, descriptor: ToolDescriptor) -> None:
        button = qt.QtWidgets.QPushButton(descriptor.title)
        button.clicked.connect(lambda: self._show_tool(descriptor))
        self._sidebar_layout.insertWidget(self._sidebar_layout.count() - 1, button)

    def _show_tool(self, descriptor: ToolDescriptor) -> None:
        page = self._pages.get(descriptor.id)
        if page is None:
            page = descriptor.widget_factory()
            self._pages[descriptor.id] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)