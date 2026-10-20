# tools/maya/animation/window.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.animation.panel import AnimationPanel  # registers animation.qss first
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.tooltips import install_tooltip_router
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


class AnimationWindow(FramelessDialog):
    """The Animation tool's window inside Maya: our own frameless window, a child of Maya's main
    window, holding an AnimationPanel; what the panel says shows in the header. One at a time
    (`open()` brings it to the front); it remembers where it was (configsMayaMng "animation":
    `window`). Esc doesn't close it (Esc puts a slider's drag back)."""

    OBJECT_NAME = "mslAnimationWindow"

    def __init__(self, parent=None):
        super().__init__(title="MSL Animation", width=400, height=150, fade_when_inactive=False,
                         show_minimize_button=False, show_maximize_button=False, parent=parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._config = Resources().configsMayaMng.get_config(AnimationPanel.TOOL_NAME)
        self.panel = AnimationPanel()
        self.add_widget(self.panel)
        icon = TintedIcon(UiResources().iconManager.get_icon("animation", sub_folder="actions"), 16)
        icon.setObjectName("animationTitleIcon")
        icon.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.header.leading_layout.insertWidget(0, icon)
        for index, widget in enumerate(self.panel.header_widgets()):
            self.header.trailing_layout.insertWidget(index, widget)
        self._status = ""
        label = self.header.subtitle_label
        label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        label.setMinimumWidth(0)
        label.installEventFilter(self)
        main = self.header.main_layout
        main.setStretch(main.indexOf(self.header.leading_layout), 1)
        main.setStretch(main.indexOf(self.header.leading_layout) + 1, 0)
        self.header.leading_layout.setStretchFactor(label, 1)
        self.panel.status_changed.connect(self._show_status)
        self.panel.installEventFilter(self)     # a row shown / hidden: the window follows its height
        self.finished.connect(self._remember_geometry)
        # every tooltip of this window (and its menus) as our bubble - not Maya's
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
        elif watched is getattr(self, "panel", None) and event.type() == qt.QtCore.QEvent.Type.LayoutRequest:
            qt.QtCore.QTimer.singleShot(30, self._fit_height)   # after Qt has laid it out anew
        return super().eventFilter(watched, event)

    def _fit_height(self) -> None:
        """As tall as what it shows - never taller (the sliders don't need room to grow into)."""
        if self.isVisible() and not self.isMaximized():
            layout = self.layout()
            wanted = layout.totalHeightForWidth(self.width()) if layout is not None and                 layout.hasHeightForWidth() else -1
            wanted = max(wanted, self.minimumSizeHint().height())   # the groups wrap: their height follows the width
            if wanted != self.height():
                self.resize(self.width(), wanted)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            qt.QtCore.QTimer.singleShot(30, self._fit_height)   # narrower = the groups wrap into more lines

    @classmethod
    def open(cls) -> "AnimationWindow":
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
        window._fit_height()
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
