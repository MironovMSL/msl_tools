"""
Network Client
Code Namespace:
    core_network  # import msl.core.network.network_client as core_network

Note: this module should not import "maya.cmds", so it stays usable outside of Maya too.
"""

import http.client as http_client
import urllib.request
import logging
from pathlib import Path


class NetworkClient:
    """HTTP/network utilities. Никаких исключений наружу — все ошибки логируются,
    методы возвращают None/False на неудаче."""

    def __init__(self, logger: logging.Logger | None = None):
        self._logger = logger or logging.getLogger(__name__)

    @staticmethod
    def parse_url(url: str) -> tuple[str, str]:
        """Разбирает URL на (host, path).
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
        Делает HTTP GET запрос и возвращает (response, response_content).
        Возвращает (None, None) при любой ошибке.
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

    def read_url_content(self, url: str) -> str | None:
        """Читает содержимое URL как UTF-8 строку. None при ошибке."""
        try:
            with urllib.request.urlopen(url) as response:
                if response.getcode() == 200:
                    return response.read().decode("utf-8")
                self._logger.warning(f"Failed to open URL. Status code: {response.getcode()}")
        except Exception as e:
            self._logger.warning(f"Unable to read URL content. Issue: {e}")
        return None

    def download_file(self, url: str, destination: str | Path,
                       chunk_size: int = 8192, callback=None) -> bool:
        """
        Скачивает файл по URL и сохраняет по указанному пути.
        Возвращает True при успехе, False при любой ошибке.

        callback(progress: float) вызывается с прогрессом 0-100, если передан.
        """
        try:
            with urllib.request.urlopen(url) as response, open(destination, "wb") as file:
                total_size = int(response.info().get("Content-Length", 0))
                downloaded = 0
                while True:
                    data = response.read(chunk_size)
                    if not data:
                        break
                    file.write(data)
                    downloaded += len(data)
                    if total_size > 0 and callback:
                        callback((downloaded / total_size) * 100)
                if callback:
                    callback(100)
            return True
        except Exception as e:
            self._logger.warning(f"Unable to download file from {url}. Issue: {e}")
            return False

    def is_connected_to_internet(self, timeout_ms: int = 1000,
                                  server: str = "8.8.8.8", port: int = 53) -> bool:
        """Проверяет доступность интернета через TCP-подключение к указанному серверу/порту."""
        import socket
        try:
            socket.setdefaulttimeout(timeout_ms / 1000)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((server, port))
            sock.close()
            return True
        except Exception as e:
            self._logger.debug(f'Unable to connect to "{server}:{port}". Issue: {e}')
            return False

    @staticmethod
    def get_http_response_type(status_code: int) -> str:
        """Классифицирует HTTP статус-код по типу."""
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