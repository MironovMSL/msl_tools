# tools/maya/playblast/window.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.playblast.panel import PlayblastPanel  # registers playblast.qss before the window styles itself
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


class PlayblastWindow(FramelessDialog):
    """The playblast tool's window inside Maya: our own frameless window (the
    hub's kind — rounded corners, resizing; the header carries the tool's
    icon and name, the "ffmpeg 8.0" note and the theme toggle)
    holding a PlayblastPanel, a child of Maya's main window so it stays
    above it and goes away with it.

    One at a time: `open()` brings the existing one to the front. It
    remembers where it was (configsMayaMng "playblast": `window`). Esc does
    not close it — inside Maya Esc is what cancels a playblast.
    """

    OBJECT_NAME = "mslPlayblastWindow"

    def __init__(self, parent=None):
        super().__init__(title="MSL Playblast", width=400, height=580,
                         show_minimize_button=False, show_maximize_button=False, parent=parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._config = Resources().configsMayaMng.get_config(PlayblastPanel.TOOL_NAME)
        self.panel = PlayblastPanel()
        self.add_widget(self.panel)
        # the header does the panel's title row's job: the tool's icon, its name, the ffmpeg note
        icon = TintedIcon(UiResources().iconManager.get_icon("clapper", sub_folder="actions"), 16)
        icon.setObjectName("playblastTitleIcon")  # playblast.qss: the accent
        icon.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.header.leading_layout.insertWidget(0, icon)
        self.header.add_leading_widget(self.panel.detach_title())  # right after the title
        self.finished.connect(self._remember_geometry)

    @classmethod
    def open(cls) -> "PlayblastWindow":
        """Shows the window (the one that is open already, if there is one) and returns it."""
        main = MayaWindowQuery.get_maya_main_window()
        window = main.findChild(qt.QtWidgets.QWidget, cls.OBJECT_NAME) if main is not None else None
        if isinstance(window, cls) and window.isVisible():
            window.raise_()
            window.activateWindow()
            return window
        if window is not None:
            # left over from before "Reload Code" (old code), or closed a moment ago and not
            # deleted yet: never handed out again
            window.setObjectName("")
            window.close()
            window.deleteLater()
        window = cls(parent=main)
        window._restore_geometry()
        window.show()
        return window

    def keyPressEvent(self, event) -> None:
        if event.key() == qt.QtCore.Qt.Key.Key_Escape:
            event.ignore()  # a QDialog closes on Esc; this one must not
            return
        super().keyPressEvent(event)

    def _restore_geometry(self) -> None:
        try:
            saved = self._config["window"]
            self.restore_normal_geometry(qt.QtCore.QRect(*[int(value) for value in saved]))
        except (KeyError, TypeError, ValueError):
            pass  # first time, or something unreadable: the default placement

    def _remember_geometry(self, *_args) -> None:
        rect = self.normal_geometry()
        self._config["window"] = [rect.x(), rect.y(), rect.width(), rect.height()]
