# ui/windows/maya_dock.py
import ctypes
import sys

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.toggles.sun_moon_toggle import SunMoonToggle
from msl_tools.msl.ui.widgets.compositions.window_header import WindowHeader

_WM_SYSCOMMAND = 0x0112
_SC_MOVE_BY_CAPTION = 0xF012
_SC_SIZE = 0xF000  # + the edge: 1 left, 2 right, 6 bottom, 7 bottom-left, 8 bottom-right


def _post_system_command(window: qt.QtWidgets.QWidget, command: int) -> bool:
    """Asks Windows to move / resize `window` with the pointer (what Qt does inside
    startSystemMove / startSystemResize)."""
    if sys.platform != "win32":
        return False
    try:
        user32 = _user32()
        user32.ReleaseCapture()
        return bool(user32.PostMessageW(int(window.winId()), _WM_SYSCOMMAND, command, 0))
    except (OSError, AttributeError, RuntimeError):
        return False


_USER32 = None


def _user32():
    """OUR OWN handle on user32 with the types set — never `ctypes.windll.user32`: that object is
    shared by everything in the process (Maya, other tools), and setting argtypes on it would change
    how THEIR calls are passed."""
    global _USER32
    if _USER32 is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW.restype = ctypes.c_int
        user32.ReleaseCapture.argtypes = []
        user32.ReleaseCapture.restype = ctypes.c_int
        _USER32 = user32
    return _USER32


def _qt_system_move(window: qt.QtWidgets.QWidget) -> bool:
    """Qt's own way to hand a window to the system for moving. False if it couldn't."""
    try:
        handle = window.windowHandle()
        return handle is not None and bool(handle.startSystemMove())
    except RuntimeError:
        # After the window was rebuilt (the frame taken off), PySide can hand back the wrapper
        # of the OLD QWindow: "Internal C++ object already deleted". It happened in Maya 2025.
        return False


def _native_system_move(window: qt.QtWidgets.QWidget) -> bool:
    return _post_system_command(window, _SC_MOVE_BY_CAPTION)


def start_system_move(window: qt.QtWidgets.QWidget) -> bool:
    """Lets the system move `window` with the pointer, as if its title bar had been pressed."""
    return _qt_system_move(window) or _native_system_move(window)


def _round_corners(window: qt.QtWidgets.QWidget, border: str = "") -> bool:
    """Rounded corners (and a hairline in `border`, "#rrggbb") for a frameless window, drawn by
    Windows 11 itself. False where the system can't (Windows 10, other systems): the window stays
    square. A window we don't own can't be made translucent to round it the way our own frameless
    windows are — this needs nothing from the window's contents."""
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.WinDLL("dwmapi")  # our own handle, not the process-wide ctypes.windll one
        dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        handle = ctypes.c_void_p(int(window.winId()))
        rounded = ctypes.c_int(2)  # DWMWCP_ROUND
        done = dwm.DwmSetWindowAttribute(handle, 33, ctypes.byref(rounded), ctypes.sizeof(rounded)) == 0
        color = qt.QtGui.QColor(border)
        if done and border and color.isValid():
            value = ctypes.c_uint(color.red() | color.green() << 8 | color.blue() << 16)  # 0x00bbggrr
            dwm.DwmSetWindowAttribute(handle, 34, ctypes.byref(value), ctypes.sizeof(value))
        return done
    except (OSError, AttributeError):
        return False


class _EdgeGrip(qt.QtWidgets.QWidget):
    """An invisible strip along an edge (or a corner) of a frameless window: pressing it lets
    the system resize the window from there."""

    def __init__(self, edge: int, cursor, parent=None):
        super().__init__(parent)
        self._edge = edge
        self.setCursor(cursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            _post_system_command(self.window(), _SC_SIZE + self._edge)


class DockHost(qt.QtWidgets.QWidget):
    """What sits in a Maya panel around a tool of ours.

    It carries our stylesheet (a docked panel is no window of ours, and
    inside Maya the QApplication is Maya's own — nothing of ours may be set
    on it) and follows theme changes.

    While the panel FLOATS alone in its window, that window is made to look
    like our own frameless windows: Maya's native frame is taken off, OUR
    `WindowHeader` is shown (`self.header` — the same header the hub has:
    icon, title, subtitle, extra widgets, the theme toggle, close), the
    corners are rounded by the system (Windows 11) and the edges resize.
    The window itself stays Maya's — it cannot be a FramelessDialog: Maya
    docks only its own panel windows. Dragging the header moves the window
    the system's way (start_system_move), which Maya still takes for a drag
    of the panel — so it docks exactly as with the native title bar (tried
    by hand, Maya 2025).

    While the panel is DOCKED (or shares a floating window with other tabs)
    the header is hidden and the frame is Maya's: there Maya's own tab
    names the panel.

    Maya rebuilds the floating window whenever a panel is torn off, with
    its native frame again, and tells nobody — so the state is looked at on
    a slow timer while the panel is on screen (`_sync`).
    """

    SYNC_MS = 250
    GRIP = 5  # how wide the resize strips along the edges are

    def __init__(self, content: qt.QtWidgets.QWidget, title: str = "", on_close=None, control_name: str = "",
                 icon=None, subtitle: str = "", show_theme_toggle: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("mayaDockHost")
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.content = content
        self._floating: bool | None = None
        self._rounded_handle = 0  # the native window the corners were rounded for
        self._control_name = control_name  # Maya's name of the panel this sits in ("" = not in one)
        icons = UiResources().iconManager
        self.header = WindowHeader(title=title, height=34)
        icon = icon if icon is not None else icons.get_icon("hub", sub_folder="brand")
        if icon is not None:
            self.header.set_icon(icon)
        if subtitle:
            self.header.set_subtitle(subtitle)
        self._theme_toggle = None
        if show_theme_toggle:
            self._theme_toggle = SunMoonToggle()
            self._theme_toggle.toggled.connect(self._on_theme_toggled)
            self.header.add_trailing_widget(self._theme_toggle)
        close = self.header.add_close_only_controls(on_close if on_close is not None else self._close_window)
        close.set_icon(icons.get_icon("close", sub_folder="window"))
        self.header.installEventFilter(self)
        self.header.hide()
        cursors = qt.QtCore.Qt.CursorShape
        self._grips = {"left": _EdgeGrip(1, cursors.SizeHorCursor, self),
                       "right": _EdgeGrip(2, cursors.SizeHorCursor, self),
                       "bottom": _EdgeGrip(6, cursors.SizeVerCursor, self),
                       "bottom_left": _EdgeGrip(7, cursors.SizeBDiagCursor, self),
                       "bottom_right": _EdgeGrip(8, cursors.SizeFDiagCursor, self)}
        for grip in self._grips.values():
            grip.hide()
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(content, 1)
        self._timer = qt.QtCore.QTimer(self)
        self._timer.setInterval(self.SYNC_MS)
        self._timer.timeout.connect(self._sync)
        manager = UiResources().themeManager
        manager.theme_changed.connect(self._apply_theme)
        self._apply_theme(manager.current_theme)

    def _apply_theme(self, theme) -> None:
        self.setStyleSheet(StylesheetBuilder.build(theme))
        if self._theme_toggle is not None:
            self._theme_toggle.set_icon_color(theme.text_primary)
            self._theme_toggle.set_checked_immediate(theme.name == "dark")
        self._rounded_handle = 0  # the hairline's color follows the theme: round again

    @staticmethod
    def _on_theme_toggled(is_dark: bool) -> None:
        UiResources().themeManager.set_theme("dark" if is_dark else "light")

    def _close_window(self) -> None:
        self.window().close()

    # ---------------------------------------------------------------- floating / docked

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()
        qt.QtCore.QTimer.singleShot(0, self._sync)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_grips()

    def _place_grips(self) -> None:
        width, height, grip, corner = self.width(), self.height(), self.GRIP, self.GRIP * 3
        top = self.header.height()
        self._grips["left"].setGeometry(0, top, grip, height - top - corner)
        self._grips["right"].setGeometry(width - grip, top, grip, height - top - corner)
        self._grips["bottom"].setGeometry(corner, height - grip, width - 2 * corner, grip)
        self._grips["bottom_left"].setGeometry(0, height - corner, corner, corner)
        self._grips["bottom_right"].setGeometry(width - corner, height - corner, corner, corner)
        for name in ("left", "right", "bottom"):
            self._grips[name].raise_()
        # a corner is only its two thin arms, so it doesn't cover the content under it
        for name, mirrored in (("bottom_left", False), ("bottom_right", True)):
            arm = qt.QtGui.QRegion(0, corner - grip, corner, grip) + qt.QtGui.QRegion(
                corner - grip if mirrored else 0, 0, grip, corner)
            self._grips[name].setMask(arm)
            self._grips[name].raise_()

    def _alone_in_floating_window(self) -> bool:
        """The panel floats, and its window holds nothing else (no second tab, no split)."""
        window = self.window()
        if window is self or not self._control_name:
            return False  # not inside a panel at all
        from maya import cmds
        try:
            if not cmds.workspaceControl(self._control_name, query=True, floating=True):
                return False  # docked
        except RuntimeError:
            return False  # the panel is being closed
        # Alone = no second tab beside it and no other panel split off beside it: read from
        # the widgets ABOVE this one. (Not findChildren() on the window: Maya deletes and
        # rebuilds those containers, and PySide hands back wrappers of the deleted ones —
        # "Internal C++ object already deleted" on the first call. It happened.)
        try:
            widget = self.parentWidget()
            while widget is not None and widget is not window:
                if isinstance(widget, (qt.QtWidgets.QTabWidget, qt.QtWidgets.QSplitter)) and widget.count() > 1:
                    return False
                widget = widget.parentWidget()
        except RuntimeError:
            pass  # a container that is going away: the next look is in a moment
        return True

    def _sync(self) -> None:
        try:
            self._sync_chrome()
        except RuntimeError:
            pass  # Maya is rebuilding the window right now; looked at again on the next tick

    def _sync_chrome(self) -> None:
        if not self.isVisible():
            return
        floating = self._alone_in_floating_window()
        window = self.window()
        frameless = qt.QtCore.Qt.WindowType.FramelessWindowHint
        if floating and not window.windowFlags() & frameless:
            if qt.QtWidgets.QApplication.mouseButtons() != qt.QtCore.Qt.MouseButton.NoButton:
                return  # in the middle of a drag: the window must not be rebuilt under the pointer
            geometry = window.geometry()
            window.setWindowFlag(frameless, True)
            window.setGeometry(geometry)
            window.show()
        rounded = bool(self.property("rounded"))
        if floating and int(window.winId()) != self._rounded_handle:
            self._rounded_handle = int(window.winId())  # a rebuilt window is a new native one
            theme = UiResources().themeManager.current_theme
            rounded = _round_corners(window, theme.border)
        if floating != self._floating or rounded != bool(self.property("rounded")):
            self._floating = floating
            self.header.setVisible(floating)
            for grip in self._grips.values():
                grip.setVisible(floating)
            # where the system draws no rounded frame, a hairline of ours goes around the window
            edge = 1 if floating and not rounded else 0
            self.layout().setContentsMargins(edge, edge, edge, edge)
            self.setProperty("rounded", rounded)
            self.setProperty("floating", floating)  # widgets.qss
            repolish(self)
            self._place_grips()

    def eventFilter(self, watched, event) -> bool:
        if (watched is self.header and event.type() == qt.QtCore.QEvent.Type.MouseButtonPress
                and event.button() == qt.QtCore.Qt.MouseButton.LeftButton):
            # the system moves the window: Maya sees a panel being dragged
            if start_system_move(self.window()):
                return True
        return super().eventFilter(watched, event)


class MayaDock:
    """Shows a tool of ours as a Maya PANEL (a workspace control): it floats
    as a window of its own — looking like our own windows, see DockHost —,
    and can be dragged onto Maya's panels to dock — beside the Channel Box,
    under the Outliner — and torn off again.

        MayaDock.show("mslPlayblast", "MSL Playblast", PlayblastPanel,
                      restore_script="from pkg.tool import restore; restore()")

    `factory` builds the tool's widget (no arguments). `restore_script` is
    Python that Maya runs to fill the panel again when it rebuilds its
    layout — at the next start, if the panel was open when Maya closed; it
    should end up calling MayaDock.fill() for the same name with the same
    header options. Header options (`icon`, `subtitle`,
    `show_theme_toggle`) go to DockHost; `MayaDock.host(name).header` is
    the WindowHeader itself, for anything more (extra widgets).
    Maya 2025+ (PySide6) only: the widgets come through the project's Qt shim.
    """

    _hosts: dict[str, DockHost] = {}
    _wanted: set = set()  # panels opened through show() in this session

    @classmethod
    def show(cls, name: str, label: str, factory, restore_script: str = "", width: int = 380,
             height: int = 620, **header) -> qt.QtWidgets.QWidget | None:
        """Opens the panel (or brings it back if it is open already) and returns the tool's widget."""
        from maya import cmds
        cls._wanted.add(name)
        if cmds.workspaceControl(name, exists=True):
            if cls._filled(name, cls._control(name)):
                cmds.workspaceControl(name, edit=True, restore=True)
                cmds.workspaceControl(name, edit=True, visible=True)
                return cls._hosts[name].content
            cmds.deleteUI(name)  # a panel left empty (its content was lost with a code reload)
        options = {"uiScript": restore_script} if restore_script else {}
        cmds.workspaceControl(name, label=label, retain=False, floating=True, initialWidth=width,
                              initialHeight=height, minimumWidth=320, **options)
        return cls.fill(name, factory, **header)  # the restore script may have filled it already

    @classmethod
    def fill(cls, name: str, factory, **header) -> qt.QtWidgets.QWidget | None:
        """Puts the tool's widget into the panel `name` (once). Returns it, or None if there is no such panel."""
        from maya import cmds
        control = cls._control(name)
        if control is None:
            return None
        if cls._filled(name, control):
            return cls._hosts[name].content
        label = cmds.workspaceControl(name, query=True, label=True) or name
        host = DockHost(factory(), title=label, on_close=lambda: cls.close(name), control_name=name, **header)
        control.layout().addWidget(host)
        cls._hosts[name] = host
        return host.content

    @classmethod
    def wanted(cls, name: str) -> bool:
        """The panel `name` was opened through show() in this session (as opposed to one that
        only Maya's saved layout still names)."""
        return name in cls._wanted

    @classmethod
    def host(cls, name: str) -> DockHost | None:
        """The DockHost of the open panel `name` (its `header` is the WindowHeader), or None."""
        host = cls._hosts.get(name)
        return host if host is not None and qt.shiboken.isValid(host) else None

    @staticmethod
    def close(name: str) -> None:
        """Closes the panel `name` (what the header's × does)."""
        from maya import cmds
        if cmds.workspaceControl(name, exists=True):
            cmds.workspaceControl(name, edit=True, close=True)

    @staticmethod
    def _control(name: str) -> qt.QtWidgets.QWidget | None:
        """Maya's panel `name` as a widget (None if there is no such panel)."""
        from maya import OpenMayaUI
        pointer = OpenMayaUI.MQtUtil.findControl(name)
        return qt.shiboken.wrapInstance(int(pointer), qt.QtWidgets.QWidget) if pointer else None

    @classmethod
    def _filled(cls, name: str, control) -> bool:
        """Our widget sits in THIS panel. A closed panel's widget can outlive it for a moment
        (it is deleted later), and must not be taken for the content of a new panel."""
        host = cls._hosts.get(name)
        return (host is not None and control is not None and qt.shiboken.isValid(host)
                and control.isAncestorOf(host))
