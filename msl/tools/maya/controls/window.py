# tools/maya/controls/window.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.controls.panel import ControlsPanel  # registers controls.qss first
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.tooltips import install_tooltip_router
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


class ControlsWindow(FramelessDialog):
    """The Controls tool's window inside Maya: our own frameless window, a child of Maya's main
    window, holding a ControlsPanel; what the panel says shows in the header. One at a time
    (`open()` brings it to the front); it remembers where it was (configsMayaMng "controls":
    `window`). Esc doesn't close it."""

    OBJECT_NAME = "mslControlsWindow"

    def __init__(self, parent=None):
        super().__init__(title="MSL Controls", width=460, height=600, fade_when_inactive=False,
                         show_minimize_button=False, show_maximize_button=False, parent=parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._config = Resources().configsMayaMng.get_config(ControlsPanel.TOOL_NAME)
        self.panel = ControlsPanel()
        self.add_widget(self.panel)
        icon = TintedIcon(UiResources().iconManager.get_icon("controls", sub_folder="actions"), 16)
        icon.setObjectName("controlsTitleIcon")
        icon.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.header.leading_layout.insertWidget(0, icon)
        for index, widget in enumerate(self.panel.header_widgets()):      # cards shown / hidden from the header
            self.header.trailing_layout.insertWidget(index, widget)
        self._status = ""
        label = self.header.subtitle_label
        label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        label.setMinimumWidth(0)
        label.installEventFilter(self)
        main = self.header.main_layout   # the room between the title and the buttons goes to the status
        main.setStretch(main.indexOf(self.header.leading_layout), 1)
        main.setStretch(main.indexOf(self.header.leading_layout) + 1, 0)
        self.header.leading_layout.setStretchFactor(label, 1)
        self.panel.status_changed.connect(self._show_status)
        # the window is as tall as what the panel shows: a card folded, the library opened, the
        # editor — no empty room under it, nothing to scroll (clamped to the screen)
        self._fit_timer = qt.QtCore.QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(15)
        self._fit_timer.timeout.connect(self._fit_height)
        scroll = self._scroll = self.panel.findChild(qt.QtWidgets.QScrollArea, "controlsScroll")
        self._body = scroll.widget() if scroll is not None else None
        if self._body is not None:
            self._body.installEventFilter(self)
        self.finished.connect(self._remember_geometry)
        # every tooltip of this window (and its menus, lists, dialogs) as our bubble - not Maya's
        install_tooltip_router(self)

    def _show_status(self, text: str, state: str = "") -> None:
        self._status = text
        label = self.header.subtitle_label
        if not text:
            label.hide()
            return
        label.show()
        if (label.property("state") or "") != state:
            label.setProperty("state", state)
            repolish(label)
        self._fit_status()

    def _fit_status(self) -> None:
        label = self.header.subtitle_label
        if self._status:
            width = max(20, label.width() - label.fontMetrics().horizontalAdvance("›  ") - 4)
            label.setText("›  " + label.fontMetrics().elidedText(self._status, qt.QtCore.Qt.TextElideMode.ElideRight,
                                                                      width))
            label.setToolTip(self._status)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.header.subtitle_label and event.type() == qt.QtCore.QEvent.Type.Resize:
            self._fit_status()
        elif watched is getattr(self, "_body", None) and event.type() == qt.QtCore.QEvent.Type.LayoutRequest:
            self._schedule_fit()
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_fit()

    def _schedule_fit(self) -> None:
        """The content changed its height: the window follows in a moment — and until it has, the
        scroll bar is held back (the content is taller than the view for that moment: the bar flashed)."""
        if self._scroll is not None and hasattr(self._scroll, "hold_bar"):
            self._scroll.hold_bar(True)
        self._fit_timer.start()

    def _fit_height(self) -> None:
        try:
            if not self.isVisible() or self.isMaximized():
                return
            change = self.panel.content_height_change()
            if abs(change) < 2:
                return
            wanted = self.height() + change
            screen = self.screen().availableGeometry() if self.screen() is not None else None
            if screen is not None:
                wanted = min(wanted, screen.bottom() - self.geometry().top() + 1)
            wanted = max(wanted, self.minimumHeight())
            if wanted != self.height():
                self.resize(self.width(), wanted)
        finally:
            # let go once the new size has been laid out: the bar then shows only if the window could
            # not grow enough (the screen ended)
            qt.QtCore.QTimer.singleShot(0, self._release_bar)

    def _release_bar(self) -> None:
        if self._scroll is not None and hasattr(self._scroll, "hold_bar") and not self._fit_timer.isActive():
            self._scroll.hold_bar(False)

    @classmethod
    def open(cls) -> "ControlsWindow":
        """Shows the window (the open one, if there is one) and returns it."""
        main = MayaWindowQuery.get_maya_main_window()
        window = main.findChild(qt.QtWidgets.QWidget, cls.OBJECT_NAME) if main is not None else None
        if isinstance(window, cls) and window.isVisible():
            window.raise_()
            window.activateWindow()
            return window
        if window is not None:   # left over from before "Reload Code", or closed a moment ago
            window.setObjectName("")
            window.close()
            window.deleteLater()
        window = cls(parent=main)
        window._restore_geometry()
        window.show()
        return window

    def keyPressEvent(self, event) -> None:
        if event.key() == qt.QtCore.Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def _restore_geometry(self) -> None:
        try:
            saved = self._config["window"]
            self.restore_normal_geometry(qt.QtCore.QRect(*[int(value) for value in saved]))
        except (KeyError, TypeError, ValueError):
            pass

    def _remember_geometry(self, *_args) -> None:
        rect = self.normal_geometry()
        self._config["window"] = [rect.x(), rect.y(), rect.width(), rect.height()]
