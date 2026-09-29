"""Hub window: lists tools in a sidebar and shows the selected tool's page
in a content area.
"""
from __future__ import annotations

from typing import Dict, Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.surfaces import BasePanel
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog

from .tool_descriptor import ToolDescriptor


class HubWindow(FramelessDialog):
    """Top-level window that hosts a set of tools behind a sidebar.

    Two visual zones, app-launcher style (think Zoom Workplace):
    - the sidebar sits directly on the window's chrome background — the same
      color as the title bar — so header + sidebar read as one frame;
    - the selected tool's page sits on a separate rounded "card"
      (`surface` color), inset from the frame.
    The selected sidebar entry takes the card's color, so it visually
    connects to the page it opened.

    Built on FramelessDialog: only needs a title bar and a single content
    area (add_widget()), not FramelessMainWindow's extra setMenuBar()/
    addToolBar()/setStatusBar() surface. FramelessDialog's own content
    surface is made transparent here; the card replaces it.

    Sidebar entries are checkable QPushButtons named "hubNavButton",
    styled by ui/theme/widgets.qss (flat, hover tint, checked = card color).

    Args:
        tools: Descriptors for every tool the hub should list, in order.
            The first one is opened on start.
        title: Window title shown in the frameless chrome.
        resources: Theme/icon composition root, forwarded to
            FramelessDialog. Defaults to a new UiResources() if omitted.
        parent: Optional parent widget.
    """

    SIDEBAR_WIDTH = 120
    CARD_RADIUS = 8
    CARD_PADDING = 6

    def __init__(self,
                 tools: Sequence[ToolDescriptor],
                 title: str = "MSL Tools",
                 resources: UiResources | None = None,
                 parent=None) -> None:
        # A standalone desktop app: keep the window opaque when unfocused (header still dims).
        super().__init__(title=title, width=900, height=600, fade_when_inactive=False,
                         resources=resources, parent=parent)

        self._pages: Dict[str, qt.QtWidgets.QWidget] = {}
        self._nav_group = qt.QtWidgets.QButtonGroup(self)
        self._nav_group.setExclusive(True)

        self._build_body()
        for descriptor in tools:
            self._add_tool_button(descriptor)

        # FramelessDialog.__init__ applied the theme before the card existed.
        self._apply_theme(self._ui_resources.themeManager.current_theme)

        buttons = self._nav_group.buttons()
        if buttons:
            buttons[0].click()

    def _build_body(self) -> None:
        self.content_surface.content_layout().setContentsMargins(0, 0, 0, 0)

        sidebar = qt.QtWidgets.QWidget()
        sidebar.setFixedWidth(self.SIDEBAR_WIDTH)
        self._sidebar_layout = qt.QtWidgets.QVBoxLayout(sidebar)
        self._sidebar_layout.setContentsMargins(4, 4, 6, 4)
        self._sidebar_layout.setSpacing(2)
        self._sidebar_layout.addStretch(1)

        self._stack = qt.QtWidgets.QStackedWidget()
        self._card = BasePanel(corner_radius=self.CARD_RADIUS)
        padding = self.CARD_PADDING
        self._card.content_layout().setContentsMargins(padding, padding, padding, padding)
        self._card.content_layout().addWidget(self._stack)

        body = qt.QtWidgets.QWidget()
        body_layout = qt.QtWidgets.QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 4, 4)
        body_layout.setSpacing(0)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(self._card, 1)
        self.add_widget(body)

    def _apply_theme(self, theme: Theme) -> None:
        super()._apply_theme(theme)
        # Window layer: FramelessDialog paints its content surface as the card;
        # here the sidebar shows the chrome through it and our own card holds the page.
        self.content_surface.set_background_color(qt.QtGui.QColor(0, 0, 0, 0))
        card = getattr(self, "_card", None)  # absent during FramelessDialog.__init__
        if card is not None:
            card.set_background_color(theme.surface)

    def _add_tool_button(self, descriptor: ToolDescriptor) -> None:
        button = qt.QtWidgets.QPushButton(descriptor.title)
        button.setObjectName("hubNavButton")
        button.setCheckable(True)
        button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._show_tool(descriptor))
        self._nav_group.addButton(button)
        self._sidebar_layout.insertWidget(self._sidebar_layout.count() - 1, button)

    def _show_tool(self, descriptor: ToolDescriptor) -> None:
        page = self._pages.get(descriptor.id)
        if page is None:
            page = descriptor.widget_factory()
            self._pages[descriptor.id] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)
