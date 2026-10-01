"""Hub window: lists tools in a sidebar and shows the selected tool's page
in a content area.
"""
from __future__ import annotations

from typing import Dict, Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import Theme, ThemeRegistry
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_tile_button import IconTileButton
from msl_tools.msl.ui.widgets.atoms.surfaces import BasePanel
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog

from .tool_descriptor import ToolDescriptor


class HubSidebar(qt.QtWidgets.QWidget):
    """The hub's tool column. Paints the selection "pill" UNDER the tiles, so
    it can SLIDE from the old tool's tile to the new one (like the tab
    indicator and the segmented control) instead of the tiles swapping a
    static checked look. Colors: qproperty pillTopColor -> pillColor (the
    lit-from-above gradient) and pillEdgeTopColor -> pillEdgeBottomColor
    (the bevel), set in widgets.qss from the --nav-* tokens."""

    RADIUS = 10
    ANIMATION_MS = 220

    pillTopColor = color_property("_pill_top_color")
    pillColor = color_property("_pill_color")
    pillEdgeTopColor = color_property("_pill_edge_top_color")
    pillEdgeBottomColor = color_property("_pill_edge_bottom_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._pill_top_color = qt.QtGui.QColor(fallback.surface)
        self._pill_color = qt.QtGui.QColor(fallback.surface)
        self._pill_edge_top_color = qt.QtGui.QColor(fallback.border)
        self._pill_edge_bottom_color = qt.QtGui.QColor(fallback.border)
        self._pill = qt.QtCore.QRectF()
        self._target: qt.QtWidgets.QWidget | None = None
        self._animation = qt.QtCore.QVariantAnimation(self)
        self._animation.setDuration(self.ANIMATION_MS)
        self._animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_pill_moved)

    def select(self, tile: qt.QtWidgets.QWidget) -> None:
        """Moves the pill under `tile` — sliding when it's already showing."""
        if self._target is not None:
            self._target.removeEventFilter(self)
        self._target = tile
        tile.installEventFilter(self)  # follow the tile if the layout moves it
        target = qt.QtCore.QRectF(tile.geometry())
        if self._pill.isEmpty() or not self.isVisible():
            self._snap()
            return
        self._animation.stop()
        self._animation.setStartValue(qt.QtCore.QRectF(self._pill))
        self._animation.setEndValue(target)
        self._animation.start()

    def _snap(self) -> None:
        self._animation.stop()
        self._pill = qt.QtCore.QRectF(self._target.geometry()) if self._target is not None else qt.QtCore.QRectF()
        self.update()

    def _on_pill_moved(self, rect) -> None:
        self._pill = qt.QtCore.QRectF(rect)
        self.update()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._target and event.type() in (qt.QtCore.QEvent.Type.Move, qt.QtCore.QEvent.Type.Resize):
            if self._animation.state() == qt.QtCore.QAbstractAnimation.State.Running:
                self._animation.setEndValue(qt.QtCore.QRectF(self._target.geometry()))
            else:
                self._snap()
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        if self._pill.isEmpty():
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = self._pill.adjusted(0.5, 0.5, -0.5, -0.5)
        fill = qt.QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, self._pill_top_color)
        fill.setColorAt(1.0, self._pill_color)
        # The bevel: light top edge fading into the dark bottom edge.
        edge = qt.QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        edge.setColorAt(0.0, self._pill_edge_top_color)
        edge.setColorAt(1.0, self._pill_edge_bottom_color)
        painter.setPen(qt.QtGui.QPen(qt.QtGui.QBrush(edge), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.end()


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

    Sidebar entries are checkable IconTileButtons named "hubNavButton" —
    icon on top, short label under it, so the icon leads (Zoom-style) —
    styled by ui/theme/widgets.qss (flat, hover tint, checked = card color).
    A tool's optional icon (ToolDescriptor.icon) is tinted from QSS; the
    open tool's entry carries the dynamic property current="true", so its
    icon can take a stronger color than the others.

    Storage-agnostic, like the rest of ui/: the caller passes which tool to
    open (`current_tool_id`) and listens to `tool_changed` to remember the
    choice (run_hub.py keeps it in the "hub" config).

    Signals:
        tool_changed(str): id of the tool the user switched to.
        footer_clicked(): the sidebar's footer text (the version) was clicked.

    Args:
        tools: Descriptors for every tool the hub should list, in order.
        current_tool_id: Tool opened on start; None or an unknown id opens
            the first one.
        footer_text: Small dimmed text at the bottom of the sidebar (run_hub
            passes the package version, "v0.0.0"); None = no footer. It is a
            button: clicking it emits footer_clicked (run_hub opens the
            "What's new" dialog); `footer_tooltip` is its tooltip.
        title: Window title shown in the frameless chrome.
        icon: Window icon — shown in the header and used by the OS
            (taskbar, Alt+Tab). run_hub.py passes assets/icons/brand/hub.svg.
        resources: Theme/icon composition root, forwarded to
            FramelessDialog. Defaults to a new UiResources() if omitted.
        parent: Optional parent widget.
    """

    SIDEBAR_WIDTH = 76
    NAV_ICON_SIZE = 20
    CARD_RADIUS = 8
    CARD_PADDING = 6

    tool_changed = qt.QtCore.Signal(str)
    footer_clicked = qt.QtCore.Signal()

    def __init__(self,
                 tools: Sequence[ToolDescriptor],
                 current_tool_id: str | None = None,
                 title: str = "MSL Tools",
                 icon: qt.QtGui.QIcon | None = None,
                 footer_text: str | None = None,
                 footer_tooltip: str = "",
                 resources: UiResources | None = None,
                 parent=None) -> None:
        # A standalone desktop app: keep the window opaque when unfocused (header still dims).
        super().__init__(title=title, icon=icon, width=900, height=600, fade_when_inactive=False,
                         resources=resources, parent=parent)

        self._pages: Dict[str, qt.QtWidgets.QWidget] = {}
        self._nav_buttons: Dict[str, qt.QtWidgets.QPushButton] = {}
        self._footer: qt.QtWidgets.QPushButton | None = None
        self._current_tool_id: str | None = None
        self._nav_group = qt.QtWidgets.QButtonGroup(self)
        self._nav_group.setExclusive(True)

        self._build_body(footer_text, footer_tooltip)
        for descriptor in tools:
            self._add_tool_button(descriptor)

        # FramelessDialog.__init__ applied the theme before the card existed.
        self._apply_theme(self._ui_resources.themeManager.current_theme)

        start = self._nav_buttons.get(current_tool_id)
        if start is None and self._nav_buttons:
            start = next(iter(self._nav_buttons.values()))
        if start is not None:
            start.click()

    def _build_body(self, footer_text: str | None, footer_tooltip: str = "") -> None:
        self.content_surface.content_layout().setContentsMargins(0, 0, 0, 0)

        sidebar = HubSidebar()
        sidebar.setFixedWidth(self.SIDEBAR_WIDTH)
        self._sidebar = sidebar
        self._sidebar_layout = qt.QtWidgets.QVBoxLayout(sidebar)
        self._sidebar_layout.setContentsMargins(4, 0, 4, 4)
        self._sidebar_layout.setSpacing(2)
        self._sidebar_layout.addStretch(1)
        if footer_text:
            footer = qt.QtWidgets.QPushButton(footer_text)
            footer.setObjectName("hubFooter")  # widgets.qss: a quiet text button
            footer.setToolTip(footer_tooltip)
            footer.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            footer.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            footer.clicked.connect(self.footer_clicked)
            self._sidebar_layout.addWidget(footer)
            self._footer = footer

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

    def set_footer_notice(self, tooltip: str) -> None:
        """Marks the footer as carrying news (accent color, widgets.qss
        `QPushButton#hubFooter[notice="true"]`) with `tooltip` saying what;
        "" clears the mark. run_hub calls it when an update is available."""
        if self._footer is None:
            return
        self._footer.setProperty("notice", bool(tooltip))
        if tooltip:
            self._footer.setToolTip(tooltip)
        repolish(self._footer)

    def _apply_theme(self, theme: Theme) -> None:
        super()._apply_theme(theme)
        # Window layer: FramelessDialog paints its content surface as the card;
        # here the sidebar shows the chrome through it and our own card holds the page.
        self.content_surface.set_background_color(qt.QtGui.QColor(0, 0, 0, 0))
        card = getattr(self, "_card", None)  # absent during FramelessDialog.__init__
        if card is not None:
            card.set_background_color(theme.surface)

    def _add_tool_button(self, descriptor: ToolDescriptor) -> None:
        icon = None
        if descriptor.icon:
            icon = self._ui_resources.iconManager.get_icon(descriptor.icon, sub_folder=descriptor.icon_sub_folder)
        button = IconTileButton(icon, descriptor.title, icon_size=self.NAV_ICON_SIZE)
        button.setObjectName("hubNavButton")
        button.setCheckable(True)
        button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._show_tool(descriptor))
        self._nav_group.addButton(button)
        self._nav_buttons[descriptor.id] = button
        self._sidebar_layout.insertWidget(len(self._nav_buttons) - 1, button)  # tiles stay above the stretch

    def _show_tool(self, descriptor: ToolDescriptor) -> None:
        page = self._pages.get(descriptor.id)
        if page is None:
            page = descriptor.widget_factory()
            self._pages[descriptor.id] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)
        self.header.set_subtitle(descriptor.title)  # breadcrumb: "MSL Tools › Maya Gate"
        # Tracked by id: QStackedWidget makes its first page current on add,
        # so "is it already the current widget" misses the very first tool.
        if descriptor.id != self._current_tool_id:
            self._current_tool_id = descriptor.id
            for tool_id, button in self._nav_buttons.items():
                button.setProperty("current", tool_id == descriptor.id)
                repolish(button)
            self._sidebar.select(self._nav_buttons[descriptor.id])  # the pill slides there
            self.tool_changed.emit(descriptor.id)
