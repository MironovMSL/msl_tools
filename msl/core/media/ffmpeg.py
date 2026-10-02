# core/media/ffmpeg.py
"""Where ffmpeg is, and how it is called — Qt-free.

ffmpeg is NOT part of msl_tools: it is never committed and never shipped in
a release (over 100 MB). It is found on the machine, in this order:

    1. the path the user set (a setting of the tool that uses it),
    2. the managed copy `<tools dir>/ffmpeg/<version>/bin` (FfmpegInstaller
       puts it there; the tools dir is `%LOCALAPPDATA%\\MSL\\tools`, next to
       the hub's Python runtime — an update or reinstall of the hub leaves
       it alone; MSL_TOOLS_DIR overrides the folder, e.g. in tests),
    3. whatever `ffmpeg` is on PATH.

Everything here starts ffmpeg through run_quiet(): no console window, stdin
closed. The second matters: started from a program, ffmpeg can write its
whole output and then sit waiting for a key press (measured, 8.0).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TOOLS_ENV_VAR = "MSL_TOOLS_DIR"
EXECUTABLE_SUFFIX = ".exe" if sys.platform == "win32" else ""
_VERSION = re.compile(r"ffmpeg version (\S+)")


class MediaError(Exception):
    """Something about media went wrong; the message is written for the user."""


def tools_dir() -> Path:
    """Folder for the external programs msl_tools manages itself (see the module docstring)."""
    override = os.environ.get(TOOLS_ENV_VAR)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "MSL" / "tools"


def run_quiet(arguments: list[str], timeout: float | None = 30.0) -> subprocess.CompletedProcess:
    """Runs a console program to its end and returns what it printed (text).
    No console window pops up (the hub runs under pythonw), stdin is closed."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run([str(argument) for argument in arguments], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=flags)


@dataclass(frozen=True)
class FfmpegTools:
    """One usable ffmpeg: the two programs, its version, and where it was found.

    Attributes:
        ffmpeg: Path of ffmpeg(.exe).
        ffprobe: Path of ffprobe(.exe), from the same folder.
        version: What `ffmpeg -version` reports ("8.0-essentials_build-www.gyan.dev").
        source: FfmpegLocator.SETTINGS / MANAGED / PATH.
    """

    ffmpeg: Path
    ffprobe: Path
    version: str
    source: str = ""

    @property
    def short_version(self) -> str:
        """The number alone: "8.0"."""
        match = re.match(r"[nN]?(\d+(?:\.\d+)*)", self.version)
        return match.group(1) if match else self.version

    def encoders(self) -> set[str]:
        """Names of the encoders this build has ("libx264", "prores_ks", ...). Asks ffmpeg — call it sparingly."""
        try:
            listing = run_quiet([self.ffmpeg, "-hide_banner", "-encoders"]).stdout
        except (OSError, subprocess.SubprocessError):
            return set()
        names = set()
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) >= 2 and re.fullmatch(r"[VAS][A-Z.]{5}", parts[0]):
                names.add(parts[1])
        return names


class FfmpegLocator:
    """Finds a usable ffmpeg (see the module docstring for the order).

        tools = FfmpegLocator(configured=settings.get("ffmpeg_path")).find()
        if tools is None: ...   # offer to download it, or to point at a copy

    `configured` may be the executable, its `bin` folder, or the folder an
    archive was unpacked to. Nothing is looked up before find() / inspect().
    """

    SETTINGS, MANAGED, PATH = "settings", "managed", "path"
    FOLDER = "ffmpeg"

    def __init__(self, configured: str | Path | None = None, tools_root: str | Path | None = None):
        self._configured = str(configured or "").strip()
        self._root = Path(tools_root) if tools_root else tools_dir()

    def managed_root(self) -> Path:
        """`<tools dir>/ffmpeg` — one sub-folder per installed version."""
        return self._root / self.FOLDER

    def managed_versions(self) -> list[str]:
        """Versions of the managed copy that are on disk, newest first."""
        root = self.managed_root()
        if not root.is_dir():
            return []
        names = [path.name for path in root.iterdir()
                 if path.is_dir() and (path / "bin" / f"ffmpeg{EXECUTABLE_SUFFIX}").is_file()]
        return sorted(names, key=_version_key, reverse=True)

    def find(self) -> FfmpegTools | None:
        """The first usable ffmpeg, or None."""
        for source, location in self.candidates():
            tools = self.inspect(location, source)
            if tools is not None:
                return tools
        return None

    def candidates(self) -> list[tuple[str, Path]]:
        """(source, location) of every place worth a look, in order."""
        found: list[tuple[str, Path]] = []
        if self._configured:
            found.append((self.SETTINGS, Path(self._configured)))
        found += [(self.MANAGED, self.managed_root() / version) for version in self.managed_versions()]
        on_path = shutil.which("ffmpeg")
        if on_path:
            found.append((self.PATH, Path(on_path)))
        return found

    @staticmethod
    def inspect(location: str | Path, source: str = "") -> FfmpegTools | None:
        """The ffmpeg at `location` (the executable, its folder, or the folder
        above `bin`) if it is complete and runs; None otherwise."""
        location = Path(location)
        name, probe_name = f"ffmpeg{EXECUTABLE_SUFFIX}", f"ffprobe{EXECUTABLE_SUFFIX}"
        if location.is_file():
            folders = [location.parent]
        else:
            folders = [location, location / "bin"]
            # an archive unpacked as it came: <folder>/ffmpeg-8.0-essentials_build/bin
            if location.is_dir():
                folders += [child / "bin" for child in sorted(location.iterdir()) if child.is_dir()]
        for folder in folders:
            ffmpeg, ffprobe = folder / name, folder / probe_name
            if not (ffmpeg.is_file() and ffprobe.is_file()):
                continue
            try:
                answer = run_quiet([ffmpeg, "-hide_banner", "-version"], timeout=15.0)
            except (OSError, subprocess.SubprocessError):
                continue
            match = _VERSION.search(answer.stdout or "")
            if answer.returncode == 0 and match:
                return FfmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe, version=match.group(1), source=source)
        return None


def _version_key(name: str) -> tuple:
    """Sort key for version folder names: "10.1" after "8.0"."""
    return tuple(int(part) if part.isdigit() else -1 for part in re.split(r"[.\-_]", name))
