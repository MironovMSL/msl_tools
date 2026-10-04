"""
Network Client
Code Namespace:
    core_network  # import msl.core.network.network_client as core_network

Note: this module should not import "maya.cmds", so it stays usable outside of Maya too.
"""

import http.client as http_client
import logging


class NetworkClient:
    """HTTP utilities. Nothing is raised: every error is logged and the
    methods return None / False instead."""

    def __init__(self, logger: logging.Logger | None = None):
        self._logger = logger or logging.getLogger(__name__)

    @staticmethod
    def parse_url(url: str) -> tuple[str, str]:
        """Splits a URL into (host, path).
        e.g. "https://api.github.com/repos/x/y" -> ("api.github.com", "/repos/x/y")
        """
        path_no_scheme = url.removeprefix("https://").removeprefix("http://")
        path_elements = path_no_scheme.split("/")
        host = path_elements[0]
        path = "/" + "/".join(path_elements[1:])
        return host, "" if path == "/" else path

    def http_get_request(self, url: str, timeout_ms: int = 2000,
                          host_overwrite: str | None = None,
                          path_overwrite: str | None = None):
        """
        Makes an HTTP GET request; returns (response, response_content),
        or (None, None) on any error.
        """
        try:
            host, path = self.parse_url(url)
            if host_overwrite:
                host = host_overwrite
            if isinstance(path_overwrite, str):
                path = path_overwrite

            connection = http_client.HTTPSConnection(host, timeout=timeout_ms / 1000)
            connection.request(
                "GET", path,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "User-Agent": "msl_tools",
                },
            )
            response = connection.getresponse()
            content = None
            try:
                content = response.read().decode("utf-8")
            except Exception as e:
                self._logger.debug(f'Failed to read HTTP response. Issue: "{e}".')
            connection.close()
            return response, content
        except Exception as e:
            self._logger.warning(f"Unable to get HTTP response. Issue: {e}")
            return None, None

    @staticmethod
    def get_http_response_type(status_code: int) -> str:
        """The kind of an HTTP status code ("successful", "client error", ...)."""
        if 100 <= status_code < 200:
            return "informational"
        if 200 <= status_code < 300:
            return "successful"
        if 300 <= status_code < 400:
            return "redirection"
        if 400 <= status_code < 500:
            return "client error"
        if 500 <= status_code < 600:
            return "server error"
        return "unknown response"