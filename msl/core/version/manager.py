from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional
import logging
from pathlib import Path

from msl_tools.msl.core.version.version import Version
from msl_tools.msl.core.version.remote_version import RemoteVersionChecker, RemoteVersionConfig
from msl_tools.msl.core.version.local_version import LocalVersionReader


class UpdateStatus(Enum):
    UP_TO_DATE       = auto()
    UPDATE_AVAILABLE = auto()
    NOT_INSTALLED    = auto()
    UNKNOWN          = auto()


@dataclass(frozen=True)
class UpdateInfo:
    status: UpdateStatus
    current_version: str
    latest_version: Optional[str] = None

    @property
    def has_update(self) -> bool:
        return self.status == UpdateStatus.UPDATE_AVAILABLE

    def __str__(self) -> str:
        if self.status is UpdateStatus.UPDATE_AVAILABLE:
            return f"Update available: {self.current_version} → {self.latest_version}"
        if self.status is UpdateStatus.UP_TO_DATE:
            return f"The latest version is installed ({self.current_version})"
        if self.status is UpdateStatus.NOT_INSTALLED:
            return "Not installed yet"
        return "Failed to check for updates"


class VersionManager:
    """Ties a local version (of any path with an __init__.py) to the release check on GitHub.
    Keeps no fixed path — takes it on every check_for_update() call."""

    # Relative path from the install root to the package that holds the version.
    # The only place this knowledge is encoded — change it here if the package layout changes.
    PACKAGE_SUBPATH = Path("msl_tools") / "msl"

    def __init__(self,
                 releases_url: str,
                 latest_release_url: str,
                 network_client,
                 core_module_path: str | Path, *,
                 logger: logging.Logger | None = None):

        config = RemoteVersionConfig(releases_url=releases_url, latest_release_url=latest_release_url)

        self.local_reader        = LocalVersionReader()
        self.core_module_path    = core_module_path
        self.core_raw_version    = self.local_reader.get_version(self.core_module_path)
        self._remote_checker     = RemoteVersionChecker(config, network_client=network_client)
        self._logger             = logger or logging.getLogger(__name__)

    def _resolve_package_root(self, install_root: str | Path) -> Path:
        """Builds the full path to the package (with __init__.py) inside the given root folder."""
        return Path(install_root) / self.PACKAGE_SUBPATH

    def check_for_remote_update(self) -> UpdateInfo:

        if self.core_raw_version is None:
            self._logger.warning(f"Failed to read package version: {self.core_module_path}")
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version="unknown")

        current_version = Version.parse(self.core_raw_version)
        latest          = self._remote_checker.get_latest_version()

        if latest is None:
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version=current_version)

        try:
            comparison = Version.compare(latest, current_version)
        except ValueError as e:
            self._logger.warning(f"Unable to compare versions: {e}")
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version=current_version)

        if comparison == Version.BIGGER:
            return UpdateInfo(status=UpdateStatus.UPDATE_AVAILABLE, current_version=current_version, latest_version=latest)
        return UpdateInfo(status=UpdateStatus.UP_TO_DATE, current_version=current_version)

    def get_releases(self):
        """Published releases with their notes (list[ReleaseNote], newest
        first), or None when they couldn't be loaded. A network request —
        call it off the GUI thread."""
        return self._remote_checker.get_releases()

    def check_install_status(self, install_root: str | Path) -> UpdateInfo:
        """install_root is the install's root folder (e.g. Documents\\maya\\scripts
        or H:\\ProjectsDev\\MSL_Others), not the path of the package itself.
        The method finds msl_tools\\msl inside it by itself."""

        if self.core_raw_version is None:
            self._logger.warning(f"Failed to read package version: {self.core_module_path}")
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version="unknown")

        current_version       = Version.parse(self.core_raw_version)
        resolved_install_path = self._resolve_package_root(install_root)
        installed_raw         = self.local_reader.get_version(resolved_install_path)

        if installed_raw is None:
            return UpdateInfo(status=UpdateStatus.NOT_INSTALLED, current_version="not installed", latest_version=current_version)

        installed_version = Version.parse(installed_raw)

        try:
            comparison = Version.compare(current_version, installed_version)
        except ValueError as e:
            self._logger.warning(f"Unable to compare versions: {e}")
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version=installed_version)

        if comparison == Version.BIGGER:
            return UpdateInfo(status=UpdateStatus.UPDATE_AVAILABLE, current_version=installed_version, latest_version=current_version)
        return UpdateInfo(status=UpdateStatus.UP_TO_DATE, current_version=installed_version)


if __name__ == "__main__":

    from msl_tools.msl.core.network.network_client import NetworkClient

    package_root       = Path(r"H:\ProjectsDev\MSL_Others\msl_tools\msl")
    releases_url       = "https://api.github.com/repos/MironovMSL/msl_tools/releases"
    latest_release_url = "https://api.github.com/repos/MironovMSL/msl_tools/releases/latest"
    root               = Path(r"H:\ProjectsDev\MSL_Others")


    manager = VersionManager(releases_url       =releases_url,
                             latest_release_url =latest_release_url,
                             network_client     =NetworkClient(),
                             core_module_path   =package_root)

    info = manager.check_for_remote_update()
    print(info)
    print(info.status, "status")
    print(info.current_version, "current_version")
    print(info.latest_version, "latest_version")
    print(info.has_update, "has_update")

    print(manager.check_install_status(root))
