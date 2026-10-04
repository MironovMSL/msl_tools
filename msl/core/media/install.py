# core/media/install.py
"""Getting ffmpeg onto the machine: the managed copy — Qt-free.

One PINNED build is downloaded (the release "essentials" build by gyan.dev,
from its GitHub releases — the build the commands of core/media were tested
with), checked against the SHA-256 written here, and unpacked to
`<tools dir>/ffmpeg/<version>/bin` (see core/media/ffmpeg.py). Newer ffmpeg
versions are not chased: for what msl_tools does they change nothing, and a
tested build beats a newer one that was never tried. To move on, test the
new build, then change PINNED_VERSION and its checksum here.

MSL_FFMPEG_ARCHIVE_URL overrides the address (a `file:///` URL in tests);
the checksum is then not checked — the archive is test-read instead.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from msl_tools.msl.core.media.ffmpeg import EXECUTABLE_SUFFIX, FfmpegLocator, FfmpegTools, MediaError, tools_dir

PINNED_VERSION = "8.0"
ARCHIVE_URL = "https://github.com/GyanD/codexffmpeg/releases/download/{version}/ffmpeg-{version}-essentials_build.zip"
ARCHIVE_SHA256 = {"8.0": "647e467caf82b9fa200a562769b5ff4d736aaf725804ed2c64ea9752106fa569"}
ARCHIVE_SIZE = {"8.0": 105_748_282}   # bytes, to say what a download will cost before it starts
URL_ENV_VAR = "MSL_FFMPEG_ARCHIVE_URL"
PROGRAMS = ("ffmpeg", "ffprobe", "ffplay")   # what is taken out of the archive (the rest is documentation)


class FfmpegInstaller:
    """Downloads and unpacks the managed copy of ffmpeg.

        tools = FfmpegInstaller().install(progress=lambda stage, done, total: ...)

    `progress(stage, done, total)`: stage "download" (bytes; total 0 if the
    server didn't say) or "unpack" (files). install() blocks — call it from
    a worker thread. It raises MediaError with a message for the user.
    """

    CHUNK_SIZE = 256 * 1024
    TIMEOUT = 30

    def __init__(self, tools_root: str | Path | None = None, logger: logging.Logger | None = None):
        self._root = (Path(tools_root) if tools_root else tools_dir()) / FfmpegLocator.FOLDER
        self._logger = logger or logging.getLogger(__name__)
        self.version = PINNED_VERSION

    def target_dir(self) -> Path:
        return self._root / self.version

    def download_size(self) -> int:
        """Bytes the download takes (0 = unknown)."""
        return ARCHIVE_SIZE.get(self.version, 0)

    def installed(self) -> FfmpegTools | None:
        """The managed copy of the pinned version, if it is there and runs.
        Runs ffmpeg (up to 15 s while an antivirus scans a fresh copy): not on a UI thread."""
        return FfmpegLocator.inspect(self.target_dir(), FfmpegLocator.MANAGED)

    def is_downloaded(self) -> bool:
        """Whether the pinned version's files are in place — file checks only, no run (a menu
        may ask this). installed() is the one that also checks they work."""
        bin_dir = self.target_dir() / "bin"
        return all((bin_dir / f"{name}{EXECUTABLE_SUFFIX}").is_file() for name in ("ffmpeg", "ffprobe"))

    def install(self, progress=None, should_cancel=None) -> FfmpegTools:
        if sys.platform != "win32" and not os.environ.get(URL_ENV_VAR):
            raise MediaError("ffmpeg can only be downloaded for Windows here — install it yourself and point at it.")
        progress = progress or (lambda stage, done, total: None)
        override = os.environ.get(URL_ENV_VAR)
        url = override or ARCHIVE_URL.format(version=self.version)
        work = self._root / ".download"
        shutil.rmtree(work, ignore_errors=True)
        try:
            work.mkdir(parents=True, exist_ok=True)
            archive = work / "ffmpeg.zip"
            digest = self._download(url, archive, progress, should_cancel)
            expected = None if override else ARCHIVE_SHA256.get(self.version)
            if expected and digest != expected:
                self._logger.warning(f"ffmpeg archive checksum mismatch: {digest} != {expected}")
                raise MediaError("The downloaded ffmpeg is not the file that was expected — nothing was installed.")
            staging = work / "staging"
            self._unpack(archive, staging / "bin", test=not expected, progress=progress)
            tools = FfmpegLocator.inspect(staging, FfmpegLocator.MANAGED)
            if tools is None:
                raise MediaError("The downloaded ffmpeg doesn’t run on this machine — nothing was installed.")
            target = self.target_dir()
            shutil.rmtree(target, ignore_errors=True)
            self._move(staging, target)
        except OSError as error:
            self._logger.warning(f"ffmpeg install failed. Issue: {error}")
            raise MediaError(f"ffmpeg couldn’t be installed: {error}") from error
        finally:
            shutil.rmtree(work, ignore_errors=True)
        installed = self.installed()
        if installed is None:
            raise MediaError("ffmpeg was unpacked but doesn’t run from its folder.")
        return installed

    def _download(self, url: str, destination: Path, progress, should_cancel) -> str:
        """Saves `url` to `destination`; returns the SHA-256 of what was saved."""
        request = urllib.request.Request(url, headers={"User-Agent": "msl_tools"})
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response, open(destination, "wb") as file:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                progress("download", done, total)
                while True:
                    if should_cancel is not None and should_cancel():
                        raise MediaError("Cancelled.")
                    chunk = response.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    file.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress("download", done, total)
        except (OSError, ValueError) as error:  # URLError / timeouts are OSErrors
            self._logger.warning(f'Download of "{url}" failed. Issue: {error}')
            raise MediaError("ffmpeg couldn’t be downloaded. Check the internet connection — "
                             "or download it yourself and point at it.") from error
        return digest.hexdigest()

    @staticmethod
    def _unpack(archive: Path, bin_dir: Path, test: bool, progress) -> None:
        """Takes the programs out of the archive into `bin_dir` — by their
        file NAME only, so no path inside the archive can lead anywhere else."""
        wanted = {f"{name}{EXECUTABLE_SUFFIX}" for name in PROGRAMS}
        try:
            with zipfile.ZipFile(archive) as bundle:
                if test and bundle.testzip() is not None:
                    raise MediaError("The downloaded ffmpeg archive is damaged.")
                members = [info for info in bundle.infolist()
                           if not info.is_dir() and Path(info.filename).name in wanted
                           and Path(info.filename).parent.name == "bin"]
                if not {f"ffmpeg{EXECUTABLE_SUFFIX}", f"ffprobe{EXECUTABLE_SUFFIX}"} <= {
                        Path(info.filename).name for info in members}:
                    raise MediaError("The downloaded archive has no ffmpeg in it.")
                bin_dir.mkdir(parents=True, exist_ok=True)
                for index, info in enumerate(members):
                    progress("unpack", index, len(members))
                    with bundle.open(info) as source, open(bin_dir / Path(info.filename).name, "wb") as target:
                        shutil.copyfileobj(source, target, 1024 * 1024)
                progress("unpack", len(members), len(members))
        except zipfile.BadZipFile as error:
            raise MediaError("The downloaded ffmpeg archive is damaged.") from error

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        """Moves the unpacked folder into place. Freshly written programs are
        often held by an antivirus scan for a moment: retry, then copy."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(10):
            try:
                os.replace(source, destination)
                return
            except OSError:
                time.sleep(0.5)
        shutil.copytree(source, destination)
