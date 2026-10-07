# tools/maya/rename/window.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.rename.panel import RenamePanel  # registers rename.qss before the window styles itself
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


class RenameWindow(FramelessDialog):
    """The rename tool's window inside Maya: our own frameless window, compact, a child of Maya's
    main window, holding a RenamePanel. One at a time (`open()` brings it to the front); it
    remembers where it was (configsMayaMng "rename": `window`). Esc doesn't close it — in a
    field Esc is "never mind"."""

    OBJECT_NAME = "mslRenameWindow"

    def __init__(self, parent=None):
        super().__init__(title="MSL Rename", width=400, height=600,
                         show_minimize_button=False, show_maximize_button=False, parent=parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._config = Resources().configsMayaMng.get_config(RenamePanel.TOOL_NAME)
        self.panel = RenamePanel()
        self.add_widget(self.panel)
        icon = TintedIcon(UiResources().iconManager.get_icon("rename", sub_folder="actions"), 16)
        icon.setObjectName("renameTitleIcon")  # rename.qss: the accent
        icon.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.header.leading_layout.insertWidget(0, icon)
        self.finished.connect(self._remember_geometry)

    @classmethod
    def find(cls) -> "RenameWindow | None":
        main = MayaWindowQuery.get_maya_main_window()
        window = main.findChild(qt.QtWidgets.QWidget, cls.OBJECT_NAME) if main is not None else None
        return window if isinstance(window, cls) and window.isVisible() else None

    @classmethod
    def open(cls) -> "RenameWindow":
        """Shows the window (the open one, if there is one) and returns it."""
        main = MayaWindowQuery.get_maya_main_window()
        window = main.findChild(qt.QtWidgets.QWidget, cls.OBJECT_NAME) if main is not None else None
        if isinstance(window, cls) and window.isVisible():
            window.raise_()
            window.activateWindow()
            return window
        if window is not None:
            # left over from before "Reload Code" (old code), or closed a moment ago: never reused
            window.setObjectName("")
            window.close()
            window.deleteLater()
        window = cls(parent=main)
        window._restore_geometry()
        window.show()
        window.panel.focus_field()
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
