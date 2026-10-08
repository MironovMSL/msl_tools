# tools/maya/keyboard_keeper.py
"""English in Maya: while a Maya window is the active one the keyboard is English, so Maya's
hotkeys work (Maya doesn't understand them on a Cyrillic layout); leaving Maya gives the window
that comes next the layout that was there before.

Switched on per Maya Gate environment: a launch carries MSL_GATE_KEEP_ENGLISH=1, and
hub_link.start() (run in every launch from Maya Gate) calls start() here.

How:
- Maya becomes the active application (QApplication.applicationStateChanged): the layout Maya has
  is remembered, and if it isn't English, Maya's active window is asked to switch to an English
  layout the user HAS installed (WM_INPUTLANGCHANGEREQUEST — the way Windows itself switches a
  window; one that isn't installed is never added).
- Maya stops being active: if Maya still has the English layout we put on (the user didn't
  switch by hand meanwhile) and the window that came next has it too (Windows' default: one
  layout for all windows), that window is given the remembered layout back. With Windows'
  "a different input method for each app window" the next window keeps its own and isn't touched.
Switching by hand inside Maya (Alt+Shift, Win+Space) works as always, until Maya is left.

MSL_GATE_KEEP_ENGLISH=only ("English only"): while Maya is active its layout is looked at every
HOLD_INTERVAL_MS, and a switch to anything not English is turned back at once — another layout
can't be used inside Maya. Leaving Maya still gives the next window the layout from before.
(Not by swallowing WM_INPUTLANGCHANGEREQUEST in a native event filter: Python would then run for
every message Maya gets, and Win+Space on Windows 8+ doesn't always go through that request.)

Windows only; nothing happens elsewhere. Python-3.9-valid and PySide2 / PySide6 both, NOT
through the Qt shim (Maya 2023 / 2024 ship PySide2) — like hub_link.py. Never raises.
"""
import ctypes
import os
import sys

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:  # Maya 2023 / 2024
    from PySide2 import QtCore, QtWidgets

VARIABLE = "MSL_GATE_KEEP_ENGLISH"
OBJECT_NAME = "mslKeyboardKeeper"
LANG_ENGLISH = 0x09
WM_INPUTLANGCHANGEREQUEST = 0x0050
RESTORE_DELAY_MS = 60  # leaving Maya: give Windows the moment it takes to make the next window active
HOLD_INTERVAL_MS = 120  # "English only": how soon a switch by hand is turned back


def _user32():
    # our own handle: argtypes set on ctypes.windll would change the calls of every other tool in Maya
    library = ctypes.WinDLL("user32")
    library.GetKeyboardLayout.argtypes = [ctypes.c_ulong]
    library.GetKeyboardLayout.restype = ctypes.c_void_p
    library.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    library.GetKeyboardLayoutList.restype = ctypes.c_int
    library.GetForegroundWindow.restype = ctypes.c_void_p
    library.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    library.GetWindowThreadProcessId.restype = ctypes.c_ulong
    library.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    library.PostMessageW.restype = ctypes.c_int
    return library


def _language(layout) -> int:
    """The primary language of a keyboard layout handle (its low word's low ten bits)."""
    return (int(layout or 0) & 0xFFFF) & 0x3FF


class KeyboardKeeper(QtCore.QObject):
    """Puts the English layout on while Maya is the active application (see the module's text)."""

    def __init__(self, parent, only=False):
        super(KeyboardKeeper, self).__init__(parent)
        self.setObjectName(OBJECT_NAME)
        self._only = bool(only)
        self._user32 = _user32()
        self._previous = None      # the layout Maya had when it became active (not English)
        self._english = None       # the English layout we put on
        self._restore_timer = QtCore.QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.setInterval(RESTORE_DELAY_MS)
        self._restore_timer.timeout.connect(self._restore)
        self._hold_timer = QtCore.QTimer(self)
        self._hold_timer.setInterval(HOLD_INTERVAL_MS)
        self._hold_timer.timeout.connect(self._hold)
        parent.applicationStateChanged.connect(self._on_state)
        if parent.applicationState() == QtCore.Qt.ApplicationState.ApplicationActive:
            self._on_state(parent.applicationState())

    def english_layout(self):
        """An installed English layout (the first one in the user's list), or None."""
        count = self._user32.GetKeyboardLayoutList(0, None)
        if count <= 0:
            return None
        layouts = (ctypes.c_void_p * count)()
        self._user32.GetKeyboardLayoutList(count, layouts)
        for layout in layouts:
            if _language(layout) == LANG_ENGLISH:
                return layout
        return None

    def _window_layout(self, window):
        thread = self._user32.GetWindowThreadProcessId(window, None)
        return self._user32.GetKeyboardLayout(thread)

    def _own_window(self, window) -> bool:
        process = ctypes.c_ulong()
        self._user32.GetWindowThreadProcessId(window, ctypes.byref(process))
        return process.value == os.getpid()

    def _on_state(self, state) -> None:
        try:
            if state == QtCore.Qt.ApplicationState.ApplicationActive:
                self._restore_timer.stop()
                self._activate()
                if self._only:
                    self._hold_timer.start()
                return
            self._hold_timer.stop()
            if self._english is not None:
                self._restore_timer.start()
        except Exception:
            pass  # never in the way of Maya

    def _activate(self) -> None:
        window = self._user32.GetForegroundWindow()
        if not window or not self._own_window(window):
            return
        current = self._window_layout(window)
        english = self.english_layout()
        if english is None or _language(current) == LANG_ENGLISH:
            self._previous, self._english = None, None
            return
        self._previous, self._english = current, english
        self._user32.PostMessageW(window, WM_INPUTLANGCHANGEREQUEST, None, english)

    def _hold(self) -> None:
        """"English only": Maya's window is on another layout -> back to English."""
        try:
            window = self._user32.GetForegroundWindow()
            if not window or not self._own_window(window):
                return
            if _language(self._window_layout(window)) == LANG_ENGLISH:
                return
            english = self._english or self.english_layout()
            if english is not None:
                self._user32.PostMessageW(window, WM_INPUTLANGCHANGEREQUEST, None, english)
        except Exception:
            pass

    def _restore(self) -> None:
        try:
            previous, english = self._previous, self._english
            self._previous, self._english = None, None
            if previous is None or english is None:
                return
            # did the user switch by hand inside Maya? then their choice stays ("English only": no choice)
            own = self._user32.GetKeyboardLayout(0)
            if not self._only and int(own or 0) != int(english or 0):
                return
            window = self._user32.GetForegroundWindow()
            if not window or self._own_window(window):
                return
            if int(self._window_layout(window) or 0) == int(english or 0):  # it took our English: one layout for all
                self._user32.PostMessageW(window, WM_INPUTLANGCHANGEREQUEST, None, previous)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self.parent().applicationStateChanged.disconnect(self._on_state)
        except Exception:
            pass
        self._restore_timer.stop()
        self._hold_timer.stop()
        self.deleteLater()


def start() -> bool:
    """Starts keeping English if this launch asks for it (MSL_GATE_KEEP_ENGLISH=1, or "only": no
    other layout inside Maya) — safe to call again (the one running is replaced: "Reload code").
    True if it runs."""
    try:
        application = QtWidgets.QApplication.instance()
        if application is None:
            return False
        old = application.findChild(QtCore.QObject, OBJECT_NAME)
        if old is not None:
            try:
                old.stop()
            except Exception:
                old.deleteLater()
        value = os.environ.get(VARIABLE)
        if sys.platform != "win32" or value not in ("1", "only"):
            return False
        # owned by the QApplication: outlives this module being reloaded
        KeyboardKeeper(application, only=value == "only")
        return True
    except Exception:
        return False
