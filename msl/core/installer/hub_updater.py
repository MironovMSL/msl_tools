"""One-click update of an installed hub: download a release, check it, hand
it to the helper that swaps it in.

    updater = HubUpdater(root, archive_url="https://github.com/.../archive/refs/tags/{tag}.zip")
    if updater.blocked_reason() is None:
        updater.prepare("v0.2.0", "0.2.0", progress=...)   # download + check; blocking, raises UpdateError
        updater.start_apply("0.2.0", "0.1.0")              # starts update_helper.py - now quit the hub

Everything happens in `<root>/.update/` (same drive as the install, so the
swap is a rename):

    download.zip    the release archive
    staged/         the checked new version: msl/ + root files
    backup/         the previous version (kept until the next update)
    apply_update.py the NEW version's update_helper.py, run after the hub quits
    result.json     what the helper did - read once by the hub on its next start
    update.log

Qt-free. Updating is refused in a git checkout (a developer updates with git).
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from msl_tools.msl.core.installer.hub_installer import HubInstaller
from msl_tools.msl.core.version.local_version import LocalVersionReader
from msl_tools.msl.core.version.version import Version


class UpdateError(Exception):
    """The update could not be prepared; str(error) is a message for the user."""


@dataclass(frozen=True)
class UpdateResult:
    """What the last update attempt did (from `.update/result.json`).

    Attributes:
        status: "updated", "rolled_back" (failed, previous version restored)
            or "failed" (failed and could not be restored).
        version: The version that was being installed.
        previous_version: The version it replaced.
        message: Why it failed ("" on success).
    """

    status: str
    version: str = ""
    previous_version: str = ""
    message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "updated"


class HubUpdater:
    """Downloads and stages a release for the hub installed at `root`."""

    WORK_DIR_NAME = ".update"
    ARCHIVE_URL_ENV_VAR = "MSL_UPDATE_ARCHIVE_URL"  # overrides `archive_url` (tests: a file:// URL)
    HELPER_RELATIVE = Path("msl") / "core" / "installer" / "update_helper.py"
    DOWNLOAD_TIMEOUT = 30    # seconds without data
    CHUNK_SIZE = 64 * 1024
    MOVE_RETRY_SECONDS = 8

    def __init__(self, root: str | Path, archive_url: str, logger: logging.Logger | None = None):
        """
        Args:
            root: The installed package root (the folder that contains `msl/`).
            archive_url: Where a release's zip archive is, with `{tag}` for
                the release tag.
        """
        self.root = Path(root).resolve()
        self._archive_url = os.environ.get(self.ARCHIVE_URL_ENV_VAR) or archive_url
        self._logger = logger or logging.getLogger(__name__)
        self._busy = threading.Lock()

    # --- locations / state -------------------------------------------------------

    @property
    def work_dir(self) -> Path:
        return self.root / self.WORK_DIR_NAME

    @property
    def log_file(self) -> Path:
        return self.work_dir / "update.log"

    def blocked_reason(self) -> str | None:
        """Why this copy can't update itself (a short sentence), or None if it can."""
        if (self.root / ".git").exists():
            return "This copy is a git checkout — update it with git."
        if not os.access(self.root, os.W_OK):
            return "The install folder is read-only."
        return None

    def take_result(self) -> UpdateResult | None:
        """The outcome of the last update, ONCE: the file is removed, so the
        next start doesn't report it again. None if there is nothing to report."""
        result_file = self.work_dir / "result.json"
        if not result_file.is_file():
            return None
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            result = UpdateResult(status=str(data.get("status", "")), version=str(data.get("version", "")),
                                  previous_version=str(data.get("previous_version", "")),
                                  message=str(data.get("message", "")))
        except (OSError, ValueError, AttributeError) as error:
            self._logger.warning(f"Unreadable update result. Issue: {error}")
            result = None
        try:
            result_file.unlink()
        except OSError:
            pass
        return result

    # --- prepare -----------------------------------------------------------------

    def prepare(self, tag: str, version: str,
                progress: Callable[[str, int, int], None] | None = None) -> None:
        """Downloads release `tag` and stages it in `.update/staged`.
        Blocking - call it off the GUI thread.

        Args:
            tag: The release tag ("v0.2.0").
            version: The version that tag must contain ("0.2.0"); a
                mismatching archive is refused.
            progress: Called as progress(stage, done, total) with stage
                "download" (bytes; total 0 = unknown size) or "check".

        Raises:
            UpdateError: with a message for the user; nothing is staged then.
        """
        reason = self.blocked_reason()
        if reason:
            raise UpdateError(reason)
        if not self._busy.acquire(blocking=False):
            raise UpdateError("An update is already being downloaded.")
        try:
            self._prepare(tag, version, progress or (lambda stage, done, total: None))
        except UpdateError as error:
            self._logger.warning(f"Update to {version} not prepared: {error}")
            raise
        finally:
            self._busy.release()

    def _prepare(self, tag: str, version: str, progress) -> None:
        staged, unpacked, archive = self.work_dir / "staged", self.work_dir / "unpacked", self.work_dir / "download.zip"
        try:
            for leftover in (staged, unpacked):
                if leftover.exists():
                    shutil.rmtree(leftover)
            self.work_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise UpdateError(f"Can’t write to the install folder ({error}).") from error

        self._download(self._archive_url.format(tag=tag), archive, progress)
        progress("check", 0, 0)
        try:
            source_root = self._unpack(archive, unpacked)
            self._check(source_root, version)
            staged.mkdir()
            self._move_folder(source_root / HubInstaller.MAIN_MODULE, staged / HubInstaller.MAIN_MODULE)
            for name in HubInstaller.ROOT_FILES:
                if (source_root / name).is_file():
                    shutil.copy2(source_root / name, staged / name)
        except (OSError, zipfile.BadZipFile) as error:
            shutil.rmtree(staged, ignore_errors=True)
            raise UpdateError(f"The downloaded update is damaged ({error}).") from error
        except UpdateError:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(unpacked, ignore_errors=True)
            try:
                archive.unlink()
            except OSError:
                pass
        self._logger.info(f'Update {version} staged in "{staged}".')

    @classmethod
    def _move_folder(cls, source: Path, destination: Path) -> None:
        """Renames a folder; freshly unpacked files are often still held by
        an antivirus scan ("Access is denied"), so it retries for a while and
        then copies instead."""
        deadline = time.monotonic() + cls.MOVE_RETRY_SECONDS
        while True:
            try:
                os.replace(source, destination)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.3)
        shutil.copytree(source, destination)

    def _download(self, url: str, destination: Path, progress) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "msl_tools"})
        try:
            with urllib.request.urlopen(request, timeout=self.DOWNLOAD_TIMEOUT) as response, \
                    open(destination, "wb") as file:
                total = int(response.headers.get("Content-Length") or 0)  # GitHub archives often don't say
                done = 0
                progress("download", done, total)
                while True:
                    chunk = response.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    file.write(chunk)
                    done += len(chunk)
                    progress("download", done, total)
        except (OSError, ValueError) as error:  # URLError / timeouts are OSErrors
            self._logger.warning(f'Download of "{url}" failed. Issue: {error}')
            if getattr(error, "code", None) == 404:
                raise UpdateError("This release has no download yet. Try again later.") from error
            raise UpdateError("Couldn’t download the update. Check your internet connection.") from error

    @staticmethod
    def _unpack(archive: Path, destination: Path) -> Path:
        """Unpacks the archive and returns the folder inside it that holds
        `msl/` (GitHub wraps everything in "<repo>-<tag>/")."""
        with zipfile.ZipFile(archive) as bundle:
            damaged = bundle.testzip()
            if damaged is not None:
                raise UpdateError(f"The downloaded update is damaged ({damaged}).")
            target = destination.resolve()
            for name in bundle.namelist():
                if not (target / name).resolve().is_relative_to(target):
                    raise UpdateError("The downloaded update has an unexpected layout.")
            bundle.extractall(destination)
        candidates = [destination, *(path for path in destination.iterdir() if path.is_dir())]
        for candidate in candidates:
            if (candidate / HubInstaller.MAIN_MODULE / "__init__.py").is_file():
                return candidate
        raise UpdateError("The downloaded update has an unexpected layout.")

    def _check(self, source_root: Path, version: str) -> None:
        main = source_root / HubInstaller.MAIN_MODULE
        if not all((main / name).is_dir() for name in HubInstaller.REQUIRED_DIRS):
            raise UpdateError("The downloaded update is incomplete.")
        if not (source_root / self.HELPER_RELATIVE).is_file():
            raise UpdateError("The downloaded update is incomplete.")
        found = LocalVersionReader().get_version(main)
        try:
            same = found is not None and Version.compare(found, version) == Version.EQUAL
        except ValueError:
            same = False
        if not same:
            raise UpdateError(f"The download contains version {found or 'unknown'}, not {version}.")

    # --- apply -------------------------------------------------------------------

    def start_apply(self, version: str, previous_version: str = "", start_hub: bool = True) -> bool:
        """Starts the helper that swaps the staged version in once THIS
        process has exited - quit the application right after a True.
        The helper is the staged (new) version's own."""
        staged_helper = self.work_dir / "staged" / self.HELPER_RELATIVE
        helper = self.work_dir / "apply_update.py"
        try:
            shutil.copy2(staged_helper, helper)
        except OSError as error:
            self._logger.warning(f"Unable to start the update. Issue: {error}")
            return False

        command = [sys.executable, str(helper), "--root", str(self.root), "--wait-pid", str(os.getpid()),
                   "--version", version, "--previous-version", previous_version,
                   "--root-files", *HubInstaller.ROOT_FILES]
        if not start_hub:
            command.append("--no-start")
        options = {"cwd": str(self.root.parent), "close_fds": True}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            options["start_new_session"] = True
        try:
            subprocess.Popen(command, **options)
        except OSError as error:
            self._logger.warning(f"Unable to start the update. Issue: {error}")
            return False
        self._logger.info(f"Update helper started for {version}.")
        return True
