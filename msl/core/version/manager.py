from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional
import logging
from pathlib import Path

from msl_tools.msl.core.version.version import Version
from msl_tools.msl.core.version.remote_version import RemoteVersionChecker, RemoteVersionConfig
from msl_tools.msl.core.version.local_version import LocalVersionReader


class UpdateStatus(Enum):
    UP_TO_DATE = auto()
    UPDATE_AVAILABLE = auto()
    UNKNOWN = auto()


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
            return f"Доступно обновление: {self.current_version} → {self.latest_version}"
        if self.status is UpdateStatus.UP_TO_DATE:
            return f"Установлена последняя версия ({self.current_version})"
        return "Не удалось проверить наличие обновлений"


class VersionManager:
    """Связывает локальную версию (любого пути с __init__.py) с проверкой релизов на GitHub.
    Не хранит фиксированный путь — принимает его при каждом вызове check_for_update()."""

    def __init__(self, releases_url: str,latest_release_url: str, network_client, *, logger: logging.Logger | None = None):

        self.local_reader    = LocalVersionReader()

        config = RemoteVersionConfig(releases_url=releases_url, latest_release_url=latest_release_url)
        self._remote_checker = RemoteVersionChecker(config, network_client=network_client)
        self._logger = logger or logging.getLogger(__name__)

    def check_for_update(self, module_path: str | Path) -> UpdateInfo:
        current_raw = self.local_reader.get_version(module_path)
        if current_raw is None:
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version="unknown")
        current_version = Version.parse(current_raw)

        latest = self._remote_checker.get_latest_version()
        if latest is None:
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version=current_version)

        try:
            comparison = Version.compare(latest, current_version)
        except ValueError as e:
            self._logger.warning(f"Не удалось сравнить версии: {e}")
            return UpdateInfo(status=UpdateStatus.UNKNOWN, current_version=current_version)

        if comparison == Version.BIGGER:
            return UpdateInfo(status=UpdateStatus.UPDATE_AVAILABLE, current_version=current_version, latest_version=latest)
        return UpdateInfo(status=UpdateStatus.UP_TO_DATE, current_version=current_version)


if __name__ == "__main__":
    from msl_tools.msl.core.network.network_client import NetworkClient
    package_root = Path(r"H:\ProjectsDev\MSL_Others\msl_tools\msl")

    releases_url       ="https://api.github.com/repos/MironovMSL/msl_tools/releases"
    latest_release_url ="https://api.github.com/repos/MironovMSL/msl_tools/releases/latest"

    manager = VersionManager(releases_url=releases_url, latest_release_url=latest_release_url, network_client=NetworkClient())
    print(manager.check_for_update(package_root))

    package_tool = Path(r"H:\ProjectsDev\MSL_Others\msl_tools\msl\tools\maya\installer")
    print(LocalVersionReader.get_version(package_tool))
    print(manager.local_reader.get_version(package_tool))