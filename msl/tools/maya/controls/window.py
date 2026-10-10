# tools/maya/controls/window.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.controls.panel import ControlsPanel  # registers controls.qss first
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


class ControlsWindow(FramelessDialog):
    """The Controls tool's window inside Maya: our own frameless window, a child of Maya's main
    window, holding a ControlsPanel; what the panel says shows in the header. One at a time
    (`open()` brings it to the front); it remembers where it was (configsMayaMng "controls":
    `window`). Esc doesn't close it."""

    OBJECT_NAME = "mslControlsWindow"

    def __init__(self, parent=None):
        super().__init__(title="MSL Controls", width=460, height=640, fade_when_inactive=False,
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
        self.finished.connect(self._remember_geometry)

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
        return super().eventFilter(watched, event)

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
