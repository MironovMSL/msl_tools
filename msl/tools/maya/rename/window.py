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
        # fully opaque when Maya has the focus: the list is read while working in the viewport
        super().__init__(title="MSL Rename", width=400, height=600, fade_when_inactive=False,
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
        for index, widget in enumerate(self.panel.header_widgets()):
            self.header.trailing_layout.insertWidget(index, widget)
        # what the panel says shows in the header ("MSL Rename › Renamed 5"), cut to the room there is
        self._status = ("", "")
        label = self.header.subtitle_label
        label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        label.setMinimumWidth(0)
        label.installEventFilter(self)
        self.header.leading_layout.setStretchFactor(label, 1)
        main = self.header.main_layout  # the room between the title and the buttons goes to the status
        main.setStretch(main.indexOf(self.header.leading_layout), 1)
        main.setStretch(main.indexOf(self.header.leading_layout) + 1, 0)
        self.panel.status_changed.connect(self._show_status)
        # the height follows the content (a list of 2 rows, cards hidden: a short window) until the
        # user drags the height themselves; the settings menu turns it back on
        self._fitting = False
        self._fit_timer = qt.QtCore.QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(40)
        self._fit_timer.timeout.connect(self._fit_height)
        body = self.panel.findChild(qt.QtWidgets.QScrollArea, "renameScroll").widget()
        body.installEventFilter(self)
        self._body = body
        self.panel.fit_changed.connect(lambda on: self._fit_timer.start() if on else None)
        self.finished.connect(self._remember_geometry)

    def _show_status(self, text: str, state: str = "") -> None:
        from msl_tools.msl.ui.theme.qss import repolish
        self._status = (text, state)
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
        text = self._status[0]
        if text:
            width = max(20, label.width() - label.fontMetrics().horizontalAdvance("\u203a  ") - 4)
            label.setText("\u203a  " + label.fontMetrics().elidedText(text, qt.QtCore.Qt.TextElideMode.ElideRight, width))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.header.subtitle_label and event.type() == qt.QtCore.QEvent.Type.Resize:
            self._fit_status()
        elif watched is getattr(self, "_body", None) and event.type() == qt.QtCore.QEvent.Type.LayoutRequest:
            if self.panel.fits_height():
                self._fit_timer.start()
        return super().eventFilter(watched, event)

    def _fit_height(self) -> None:
        if not self.isVisible() or self.isMaximized() or not self.panel.fits_height():
            return
        change = self.panel.content_height_change()
        if abs(change) < 2:
            return
        screen = self.screen().availableGeometry() if self.screen() is not None else None
        top = self.geometry().top()
        wanted = self.height() + change
        if screen is not None:
            wanted = min(wanted, screen.bottom() - top + 1)
        wanted = max(wanted, self.minimumHeight())
        if wanted != self.height():
            self._fitting = True
            self.resize(self.width(), wanted)
            self._fitting = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # a height dragged by hand: the window keeps it (the settings menu brings the fitting back)
        if not getattr(self, "_fitting", True) and self.isVisible() and event.oldSize().isValid() \
                and event.oldSize().height() != event.size().height() \
                and qt.QtWidgets.QApplication.mouseButtons() & qt.QtCore.Qt.MouseButton.LeftButton \
                and self.panel.fits_height():
            self.panel.set_fits_height(False)

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
