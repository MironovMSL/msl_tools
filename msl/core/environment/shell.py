# core/environment/shell.py
"""Asking the operating system's shell (Windows Explorer) for things — Qt-free."""
from __future__ import annotations

import sys
from pathlib import Path


def select_in_file_manager(path: str | Path) -> bool:
    """Shows `path` in the file manager with the file SELECTED, in a window
    that is brought to the front. If its folder is open in a window already,
    that window is used — `explorer /select,` opens one more window every
    time. Windows only; returns False where it can't be done (not Windows,
    the path is gone, the shell refused), so the caller can fall back."""
    path = Path(path)
    if sys.platform != "win32" or not path.exists():
        return False
    try:
        import ctypes

        shell, ole = ctypes.WinDLL("shell32"), ctypes.WinDLL("ole32")  # own handles: argtypes set on ctypes.windll would change every caller's calls
        ole.CoInitialize(None)  # a GUI thread has done this already; a second call is harmless
        shell.SHParseDisplayName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                             ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
        shell.SHParseDisplayName.restype = ctypes.c_long
        shell.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_ulong]
        shell.SHOpenFolderAndSelectItems.restype = ctypes.c_long
        shell.ILFree.argtypes = [ctypes.c_void_p]
        item = ctypes.c_void_p()
        if shell.SHParseDisplayName(str(path), None, ctypes.byref(item), 0, None) != 0 or not item.value:
            return False
        try:
            # no child items given: the item itself is selected in its parent folder
            return shell.SHOpenFolderAndSelectItems(item, 0, None, 0) == 0
        finally:
            shell.ILFree(item)
    except Exception:  # noqa: BLE001 - showing a file must never break what asked for it
        return False
