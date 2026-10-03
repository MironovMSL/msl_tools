# core/environment/send_to.py
"""The "Send to" menu of Windows Explorer — Qt-free.

A shortcut in the user's SendTo folder appears in Explorer's right-click
menu under "Send to"; picking it starts the shortcut's program with the
selected files appended as arguments. That is how "Send to → MSL Media"
hands files to the hub.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def send_to_dir() -> Path | None:
    """The user's SendTo folder (MSL_SENDTO_DIR overrides it — use that in tests); None off Windows."""
    if os.environ.get("MSL_SENDTO_DIR"):
        return Path(os.environ["MSL_SENDTO_DIR"])
    if os.name != "nt" or not os.environ.get("APPDATA"):
        return None
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo"


def send_to_path(name: str) -> Path | None:
    folder = send_to_dir()
    return folder / f"{name}.lnk" if folder is not None else None


def has_send_to(name: str) -> bool:
    path = send_to_path(name)
    return path is not None and path.is_file()


def create_send_to(name: str, target: str | Path, arguments: list, working_dir: str | Path,
                   icon: str | Path | None = None) -> bool:
    """Puts "Send to → `name`" into Explorer: a shortcut that runs `target`
    with `arguments` (the selected files are added after them) in
    `working_dir`. False if it couldn't be made (or not on Windows)."""
    path = send_to_path(name)
    if path is None or os.name != "nt":
        return False
    # The values travel as environment variables: no path needs quoting inside the script.
    script = ("$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:MSL_LNK_PATH);"
              "$link.TargetPath = $env:MSL_LNK_TARGET;"
              "$link.Arguments = $env:MSL_LNK_ARGS;"
              "$link.WorkingDirectory = $env:MSL_LNK_CWD;"
              "$link.Description = $env:MSL_LNK_NAME;"
              "if ($env:MSL_LNK_ICON -and (Test-Path $env:MSL_LNK_ICON)) { $link.IconLocation = $env:MSL_LNK_ICON };"
              "$link.Save()")
    environment = dict(os.environ, MSL_LNK_PATH=str(path), MSL_LNK_TARGET=str(target),
                       MSL_LNK_ARGS=subprocess.list2cmdline([str(argument) for argument in arguments]),
                       MSL_LNK_CWD=str(working_dir), MSL_LNK_NAME=name, MSL_LNK_ICON=str(icon or ""))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=environment,
                              capture_output=True, text=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and path.is_file()


def remove_send_to(name: str) -> bool:
    """Takes "Send to → `name`" out of Explorer again (not there = success)."""
    path = send_to_path(name)
    if path is None:
        return True
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True
