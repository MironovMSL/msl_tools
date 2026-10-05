# core/environment/system_actions.py
"""What a long batch may do when it is over — Qt-free: play a "done" sound
(done_sounds(): our own or Windows'), or shut the computer down after a grace period that can be
called off.

The shutdown goes through Windows' own `shutdown /s /t <seconds>`: Windows
says it is coming, and `shutdown /a` (cancel_shutdown) stops it until the
last second. `run` is how the command is started — tests pass a fake: a
test must NEVER reach the real one.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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


def chime(sound: str = "") -> None:
    """Plays `sound` (a .wav file) without waiting for it — "" or a file that isn't there: the
    system's own "done" sound. Never raises; silent where there is no sound."""
    if sys.platform != "win32":
        return
    try:
        import winsound
        if sound and os.path.isfile(sound):
            winsound.PlaySound(sound, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except (ImportError, RuntimeError, OSError):
        pass


def done_sounds(own_folder) -> dict:
    """The sounds to pick from for "the jobs are done": {name: .wav path} — ours (`own_folder`:
    bells, marimba, done — synthesized for msl_tools) first, then a few of Windows' own that exist."""
    sounds = {}
    for name, file in (("Bells", "bells.wav"), ("Marimba", "marimba.wav"), ("Soft", "done.wav")):
        path = Path(own_folder) / file
        if path.is_file():
            sounds[name] = str(path)
    media = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Media"
    for name, file in (("Ta-da", "tada.wav"), ("Chimes", "chimes.wav"), ("Chord", "chord.wav"),
                       ("Notify", "Windows Notify System Generic.wav"), ("Alarm", "Alarm01.wav")):
        path = media / file
        if path.is_file():
            sounds[name] = str(path)
    return sounds
