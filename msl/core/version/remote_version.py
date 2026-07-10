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


if __name__ == "__main__":

    from msl_tools.msl.core.network.network_client import NetworkClient

    remote_version_config = RemoteVersionConfig(
        releases_url="https://api.github.com/repos/MironovMSL/msl_tools/releases",
        latest_release_url="https://api.github.com/repos/MironovMSL/msl_tools/releases/latest",
    )
    remote_version = RemoteVersionChecker(remote_version_config, network_client=NetworkClient())

    print(remote_version.get_latest_version())