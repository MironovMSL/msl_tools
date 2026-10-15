# core/environment/taskbar.py
"""The progress shown on a window's taskbar button (Windows) — Qt-free.

Windows draws a green bar across the taskbar button of a window that
reports progress (ITaskbarList3) — the user sees how far long work is
without opening the window. Qt 6 has no wrapper for it, so the COM
interface is called directly through ctypes.
"""
from __future__ import annotations

import sys

_CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11D0-958A-006097C9A090}"
_IID_TASKBAR_LIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"
# The slots of ITaskbarList3 that are used (IUnknown takes 0-2, ITaskbarList 3-7, ITaskbarList2 8).
_RELEASE, _HR_INIT, _SET_VALUE, _SET_STATE = 2, 3, 9, 10
_NO_PROGRESS, _NORMAL, _ERROR = 0, 2, 4
_STEPS = 1000


class TaskbarProgress:
    """The progress bar on the taskbar button of ONE window.

        bar = TaskbarProgress(int(window.winId()))
        bar.set(0.4)        # 40 %
        bar.set(1.0, error=True)   # full and red
        bar.clear()

    Call it from the thread that owns the window. Nothing here raises:
    where the taskbar can't be reached (not Windows, no real window) every
    call returns False and does nothing.
    """

    def __init__(self, window_id: int):
        self._window = int(window_id or 0)
        self._taskbar = None      # the COM object, once it was made
        self._methods: dict = {}
        self._failed = False

    def set(self, fraction: float, error: bool = False) -> bool:
        """Shows `fraction` (0..1) on the button; `error` paints it red."""
        if not self._connect():
            return False
        done = int(min(max(float(fraction), 0.0), 1.0) * _STEPS)
        return (self._call(_SET_STATE, _ERROR if error else _NORMAL)
                and self._call(_SET_VALUE, done, _STEPS))

    def clear(self) -> bool:
        """Takes the bar off the button."""
        if self._taskbar is None:
            return False
        return self._call(_SET_STATE, _NO_PROGRESS)

    # --- COM ----------------------------------------------------------------------------

    def _connect(self) -> bool:
        if self._taskbar is not None:
            return True
        if self._failed or sys.platform != "win32" or not self._window:
            return False
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class Guid(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                            ("d", ctypes.c_ubyte * 8)]

            def guid(text: str) -> Guid:
                return Guid.from_buffer_copy(uuid.UUID(text).bytes_le)

            ole = ctypes.WinDLL("ole32")  # own handle (argtypes are set below)
            ole.CoInitialize(None)  # a GUI thread has done this already; a second call is harmless
            pointer = ctypes.c_void_p()
            ole.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                             ctypes.c_void_p]
            ole.CoCreateInstance.restype = ctypes.c_long
            result = ole.CoCreateInstance(ctypes.byref(guid(_CLSID_TASKBAR_LIST)), None, 1,
                                          ctypes.byref(guid(_IID_TASKBAR_LIST3)), ctypes.byref(pointer))
            if result != 0 or not pointer.value:
                raise OSError(f"CoCreateInstance: {result:#x}")
            table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            this, handle = ctypes.c_void_p, wintypes.HWND
            signatures = {
                _RELEASE: (ctypes.c_ulong, this),
                _HR_INIT: (ctypes.c_long, this),
                _SET_VALUE: (ctypes.c_long, this, handle, ctypes.c_ulonglong, ctypes.c_ulonglong),
                _SET_STATE: (ctypes.c_long, this, handle, ctypes.c_int),
            }
            self._methods = {slot: ctypes.WINFUNCTYPE(*signature)(table[slot])
                             for slot, signature in signatures.items()}
            self._taskbar = pointer
            if self._methods[_HR_INIT](pointer) != 0:
                raise OSError("ITaskbarList3.HrInit failed")
        except Exception:  # noqa: BLE001 - a missing taskbar bar must never break the work it reports on
            self._taskbar, self._failed = None, True
            return False
        return True

    def _call(self, slot: int, *arguments) -> bool:
        try:
            return self._methods[slot](self._taskbar, self._window, *arguments) == 0
        except Exception:  # noqa: BLE001
            return False

    def __del__(self):
        try:
            if self._taskbar is not None:
                self._methods[_RELEASE](self._taskbar)
        except Exception:  # noqa: BLE001
            pass


# The taskbar's "AppUserModel" properties of a window (propkey.h: FMTID_AppUserModel, pid).
_FMTID_APP_USER_MODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_PID_RELAUNCH_COMMAND, _PID_RELAUNCH_ICON, _PID_RELAUNCH_NAME, _PID_ID = 2, 3, 4, 5
_IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_PS_RELEASE, _PS_SET_VALUE, _PS_COMMIT = 2, 6, 7
_VT_LPWSTR = 31


def set_window_identity(window_id: int, app_id: str, name: str, icon: str, command: str) -> bool:
    """Tells the taskbar what a window IS, so its button never depends on what the window
    answers at the moment it appears: the group (`app_id`, the same as the process's own
    AppUserModelID), the name and icon of that group (`icon`: an .ico file, or "file,index"),
    and the command that starts it again (a button pinned to the taskbar runs it).
    Windows only; never raises — False where it couldn't be done."""
    if sys.platform != "win32" or not window_id:
        return False
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class Guid(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                        ("d", ctypes.c_ubyte * 8)]

        class PropertyKey(ctypes.Structure):
            _fields_ = [("fmtid", Guid), ("pid", wintypes.DWORD)]

        class PropVariant(ctypes.Structure):   # only the VT_LPWSTR form is needed
            _fields_ = [("vt", ctypes.c_ushort), ("reserved1", ctypes.c_ushort), ("reserved2", ctypes.c_ushort),
                        ("reserved3", ctypes.c_ushort), ("text", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]

        def guid(text: str) -> Guid:
            return Guid.from_buffer_copy(uuid.UUID(text).bytes_le)

        shell = ctypes.WinDLL("shell32")   # own handle (argtypes are set below)
        shell.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p]
        shell.SHGetPropertyStoreForWindow.restype = ctypes.c_long
        store = ctypes.c_void_p()
        if shell.SHGetPropertyStoreForWindow(window_id, ctypes.byref(guid(_IID_PROPERTY_STORE)),
                                             ctypes.byref(store)) != 0 or not store.value:
            return False
        table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        this = ctypes.c_void_p
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, this, ctypes.POINTER(PropertyKey),
                                       ctypes.POINTER(PropVariant))(table[_PS_SET_VALUE])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, this)(table[_PS_COMMIT])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, this)(table[_PS_RELEASE])
        done = True
        try:
            # the relaunch values first: the ID is what makes the taskbar read them
            for pid, text in ((_PID_RELAUNCH_COMMAND, command), (_PID_RELAUNCH_NAME, name),
                              (_PID_RELAUNCH_ICON, icon), (_PID_ID, app_id)):
                key = PropertyKey(guid(_FMTID_APP_USER_MODEL), pid)
                value = PropVariant(_VT_LPWSTR, 0, 0, 0, text, None)
                done = set_value(store, ctypes.byref(key), ctypes.byref(value)) == 0 and done
            done = commit(store) == 0 and done
        finally:
            release(store)
        return done
    except Exception:  # noqa: BLE001 - a plainer taskbar button must never stop the hub
        return False


_KEPT_ICONS: list = []   # icon handles given to windows: they must live as long as the windows do


def set_window_icons(window_id: int, icon_file: str) -> bool:
    """Gives a window its icons from an .ico file, big (the taskbar button, Alt+Tab) and small (the
    title), at the window's DPI — as the window's own (WM_SETICON: the taskbar redraws the button)
    AND as its window class's (what the taskbar falls back to when the window doesn't answer it in
    time; Qt's class carries the default application icon — the blank button the hub sometimes
    got). Windows only; never raises — False where it couldn't be done."""
    if sys.platform != "win32" or not window_id:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")   # own handle (argtypes are set below)
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int,
                                      ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetClassLongPtrW.restype = ctypes.c_size_t
        dpi = user32.GetDpiForWindow(window_id) or 96
        icons = {}
        for kind, size in (("big", 32), ("small", 16)):
            pixels = max(16, round(size * dpi / 96))
            handle = user32.LoadImageW(None, str(icon_file), 1, pixels, pixels, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
            if not handle:
                return False
            icons[kind] = handle
            _KEPT_ICONS.append(handle)
        user32.SetClassLongPtrW(window_id, -14, icons["big"])      # GCLP_HICON
        user32.SetClassLongPtrW(window_id, -34, icons["small"])    # GCLP_HICONSM
        user32.SendMessageW(window_id, 0x80, 1, icons["big"])      # WM_SETICON, ICON_BIG
        user32.SendMessageW(window_id, 0x80, 0, icons["small"])    # WM_SETICON, ICON_SMALL
        return True
    except Exception:  # noqa: BLE001
        return False
