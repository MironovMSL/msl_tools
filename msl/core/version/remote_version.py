from dataclasses import dataclass
from json import loads
import logging


@dataclass(frozen=True)
class RemoteVersionConfig:
    releases_url: str        # e.g. "https://api.github.com/repos/<user>/msl_tools/releases"
    latest_release_url: str  # releases_url + "/latest"


class RemoteVersionChecker:
    """Проверка последней доступной версии через GitHub Releases API."""

    def __init__(self, config: RemoteVersionConfig, network_client, *,
                 logger: logging.Logger | None = None):
        self.config = config
        self._network_client = network_client
        self._logger = logger or logging.getLogger(__name__)

    def get_latest_version(self) -> str | None:
        response, content = self._network_client.http_get_request(self.config.latest_release_url)
        if response is None:
            self._logger.warning("Unable to check latest version. No response from server.")
            return None

        response_type = self._network_client.get_http_response_type(response.status)
        if response_type != "successful":
            self._logger.warning(f"Unsuccessful response checking latest version. Status: {response.status}")
            return None
        if not content:
            self._logger.warning("Latest version response content is empty.")
            return None

        try:
            data = loads(content)
            if isinstance(data, list):
                if not data:
                    self._logger.warning("Latest version response was an empty list.")
                    return None
                data = data[0]
        except Exception as e:
            self._logger.warning(f"Failed to parse version response. Issue: {e}")
            return None

        tag_name = data.get("tag_name")
        if not tag_name:
            self._logger.warning('Version response is missing "tag_name".')
            return None

        from msl_tools.msl.core.version.version import Version
        return Version.parse(tag_name)

    def get_releases(self, limit: int = 30, timeout_ms: int = 8000):
        """Published releases with their notes, newest first
        (list[ReleaseNote]) — or None when they couldn't be loaded (no
        network, rate limit, unexpected response). Blocking: call it off
        the GUI thread."""
        from msl_tools.msl.core.version.release_notes import parse_releases

        url = f"{self.config.releases_url}?per_page={limit}"
        response, content = self._network_client.http_get_request(url, timeout_ms=timeout_ms)
        if response is None:
            self._logger.warning("Unable to load releases. No response from server.")
            return None
        if self._network_client.get_http_response_type(response.status) != "successful" or not content:
            self._logger.warning(f"Unsuccessful response loading releases. Status: {response.status}")
            return None
        try:
            return parse_releases(content)
        except ValueError as e:
            self._logger.warning(f"Failed to parse releases. Issue: {e}")
            return None


if __name__ == "__main__":

    from msl_tools.msl.core.network.network_client import NetworkClient

    remote_version_config = RemoteVersionConfig(
        releases_url="https://api.github.com/repos/MironovMSL/msl_tools/releases",
        latest_release_url="https://api.github.com/repos/MironovMSL/msl_tools/releases/latest",
    )
    remote_version = RemoteVersionChecker(remote_version_config, network_client=NetworkClient())

    print(remote_version.get_latest_version())