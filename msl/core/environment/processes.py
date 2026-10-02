# core/environment/processes.py
"""Questions about other processes on this machine — Qt-free."""
from __future__ import annotations

import os
import sys


def is_process_running(pid: int) -> bool:
    """True while a process with id `pid` exists.

    On Windows this asks the system for the process (never os.kill(pid, 0):
    there, signal 0 TERMINATES the process)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        synchronize, wait_timeout = 0x00100000, 0x00000102
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(synchronize, False, int(pid))
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_process(pid: int) -> bool:
    """Ends process `pid` at once, without asking it (its unsaved work is
    lost). True if the system accepted the request."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if not handle:
            return False
        try:
            return bool(kernel.TerminateProcess(handle, 1))
        finally:
            kernel.CloseHandle(handle)
    import signal
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    return True


def process_memory(pid: int) -> int | None:
    """Bytes of physical memory process `pid` uses right now (its working
    set); None if it can't be told (no such process, another system)."""
    if pid <= 0 or sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)
    finally:
        kernel.CloseHandle(handle)
