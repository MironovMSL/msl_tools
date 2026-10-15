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


def move_to_recycle_bin(paths) -> list[str]:
    """Moves files to the Recycle Bin (they can be put back from there) — never deletes them outright.
    Windows only. Returns the paths that are still there afterwards (refused, in use; all of them where
    it can't be done)."""
    paths = [str(Path(path)) for path in paths if Path(path).exists()]
    if not paths:
        return []
    if sys.platform != "win32":
        return paths
    try:
        import ctypes
        from ctypes import wintypes

        class _Operation(ctypes.Structure):   # SHFILEOPSTRUCTW
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

        shell = ctypes.WinDLL("shell32")   # own handle (see select_in_file_manager)
        shell.SHFileOperationW.argtypes = [ctypes.POINTER(_Operation)]
        shell.SHFileOperationW.restype = ctypes.c_int
        delete, allow_undo, no_confirmation, silent, no_error_ui = 3, 0x40, 0x10, 0x4, 0x400
        operation = _Operation(None, delete, "\0".join(paths) + "\0\0", None,
                               allow_undo | no_confirmation | silent | no_error_ui, False, None, None)
        shell.SHFileOperationW(ctypes.byref(operation))
    except Exception:
        pass
    return [path for path in paths if Path(path).exists()]
