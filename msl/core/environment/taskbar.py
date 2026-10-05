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
