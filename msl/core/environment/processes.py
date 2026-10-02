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
