# core/environment/system_actions.py
"""What a long batch may do when it is over — Qt-free: play the system's
"done" sound, or shut the computer down after a grace period that can be
called off.

The shutdown goes through Windows' own `shutdown /s /t <seconds>`: Windows
says it is coming, and `shutdown /a` (cancel_shutdown) stops it until the
last second. `run` is how the command is started — tests pass a fake: a
test must NEVER reach the real one.
"""
from __future__ import annotations

import subprocess
import sys

SHUTDOWN_GRACE_S = 120
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no console flashes up (the hub runs under pythonw)


def _start(command: list[str]) -> bool:
    try:
        flags = _NO_WINDOW if sys.platform == "win32" else 0
        return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=flags, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def schedule_shutdown(seconds: int = SHUTDOWN_GRACE_S, reason: str = "", run=_start) -> bool:
    """Asks Windows to shut down in `seconds` (it says so on screen). True if it took the request."""
    if sys.platform != "win32" and run is _start:
        return False
    command = ["shutdown", "/s", "/t", str(max(int(seconds), 0))]
    if reason:
        command += ["/c", reason[:500]]  # Windows takes at most 512 characters
    return bool(run(command))


def cancel_shutdown(run=_start) -> bool:
    """Calls off a shutdown asked for by schedule_shutdown (or anyone). True if one was called off."""
    if sys.platform != "win32" and run is _start:
        return False
    return bool(run(["shutdown", "/a"]))


def chime() -> None:
    """The system's "done" sound, without waiting for it. Never raises; silent where there is none."""
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except (ImportError, RuntimeError, OSError):
        pass
